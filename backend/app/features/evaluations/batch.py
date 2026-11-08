
import argparse
import csv
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

from app.core.config import BACKEND_DIR
from app.core.db import SessionLocal
from app.features.checklists import service as checklist_service
from app.features.conversations import service as conversation_service
from app.features.evaluations import service
from app.features.evaluations.export import EXPECTED_COUNTS, write_atomic
from app.features.evaluations.llm import get_provider
from app.features.evaluations.models import Evaluation
from app.features.evaluations.schemas import BatchRequest


def main() -> int:
    parser = argparse.ArgumentParser(description="AuditLens batch evaluation")
    parser.add_argument("--group", help="dataset_group (DEV, контрольный group_id, manual)")
    parser.add_argument("--ids", nargs="*", help="конкретные conversation_id")
    parser.add_argument("--checklist", type=int, help="ID чек-листа (по умолчанию активный)")
    parser.add_argument("--sync", action="store_true", help="сначала загрузить набор из API")
    parser.add_argument("--sync-only", action="store_true", help="только получить набор, без LLM")
    parser.add_argument("--output-dir", type=Path, help="новая папка артефактов этого запуска")
    parser.add_argument("--only-missing", action="store_true", help="пропустить уже оценённые")
    parser.add_argument("--limit", type=int, help="оценить только первые N")
    args = parser.parse_args()

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.sync and not args.group:
        parser.error("--sync requires --group")
    if args.sync_only and not args.sync:
        parser.error("--sync-only requires --sync")
    export_dir = args.output_dir or (
        BACKEND_DIR / "data" / "exports"
        / f"run_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
    )
    # Отказываемся до API/LLM, если каталог уже занят или недоступен для записи.
    try:
        export_dir.mkdir(parents=True, exist_ok=False)
        ids_file = export_dir / "evaluation-ids.json"
        write_atomic([], ids_file)
    except OSError:
        parser.exit(1, "Cannot create a new writable --output-dir; use an unused path\n")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with SessionLocal() as db:
        if args.sync:
            dataset_file = export_dir / "dataset.json"
            records = conversation_service.fetch_dataset(args.group, save_to=dataset_file)
            res = conversation_service.upsert_records(db, args.group, records)
            print(f"Synced {res.total} records (new {res.created}, updated {res.updated})")
            print(f"Source dataset: {dataset_file.resolve()}")
        if args.sync_only:
            print("Sync only: no evaluations created; not an official submission.")
            return 0
        checklist_service.ensure_default(db)
        pinned = service._snapshot_checklist(args.checklist, db)
        req = BatchRequest(
            dataset_group=args.group,
            conversation_ids=args.ids,
            checklist_id=pinned[0],
        )
        requested, _ = service.resolve_batch_targets(db, req, pinned_checklist=pinned)
        ids, checklist_id = service.resolve_batch_targets(
            db, req.model_copy(update={"only_missing": args.only_missing}),
            pinned_checklist=pinned, allow_empty=True,
        )
        # Для --ids внутри группы полноту сравниваем со всей группой, не поднабором.
        dataset_ids = (
            [c.id for c in conversation_service.list_conversations(db, dataset_group=args.group)]
            if args.group else requested
        )
    if args.limit is not None:
        ids = ids[: args.limit]

    print(f"Checklist ID: {checklist_id} | version: {pinned[1]} | {len(ids)} conversations")

    def progress(cid, job):
        # Список только этого job, включая ID сохранённых failed-оценок.
        write_atomic(job.evaluation_ids, ids_file)
        mark = "ERR" if cid in job.errors else "ok "
        print(f"  [{job.done + job.failed:>3}/{job.total}] {mark} {cid}")

    if ids:
        provider = get_provider()
        m_name = getattr(provider, "model", provider.name)
        print(f"Model: {m_name}")
        job = service.run_batch(
            ids, checklist_id, on_progress=progress, pinned_checklist=pinned,
        )
        write_atomic(job.evaluation_ids, ids_file)
        selected = job.evaluation_ids
    else:
        job = None
        selected = []

    with SessionLocal() as db:
        rows = [db.get(Evaluation, i) for i in selected]
    rows = sorted((r for r in rows if r), key=lambda r: r.conversation_id)
    processed = {r.conversation_id for r in rows if r.status in ("done", "failed")}
    unprocessed = [
        cid for cid in dict.fromkeys([*dataset_ids, *requested]) if cid not in processed
    ]
    print(f"Evaluation IDs: {ids_file.resolve()}")
    print(f"Unprocessed conversations (no result from this run): {json.dumps(unprocessed)}")
    expected = EXPECTED_COUNTS["dev" if args.group == "DEV" else "prod"]
    complete = (
        bool(args.group) and len(dataset_ids) == expected
        and not unprocessed and processed == set(dataset_ids) and len(selected) == len(dataset_ids)
    )
    print(
        "Coverage complete; use the official exporter to validate the source dataset and results."
        if complete else
        "INCOMPLETE: this ID file is insufficient for a full official export; "
        "older evaluations were not added (including with --limit / --only-missing)."
    )
    write_atomic({
        "checklist_id": checklist_id, "checklist_version": pinned[1],
        "dataset_group": args.group, "evaluation_ids": selected,
        "unprocessed_conversation_ids": unprocessed, "coverage_complete": complete,
        "errors": job.errors if job else {},
    }, export_dir / "run.json")
    _export(rows, export_dir / "diagnostic")

    done, failed, cost = (job.done, job.failed, job.total_cost_usd) if job else (0, 0, 0.0)
    n = max(done, 1)
    print(f"\nDone: {done}, failed: {failed}")
    print(
        f"Estimated total cost: ${cost:.4f} | avg per evaluation: ${cost / n:.5f}"
    )
    for cid, err in (job.errors if job else {}).items():
        print(f"  ! {cid}: {err}")
    print(f"Diagnostic export (not a submission): {export_dir / 'diagnostic'}.json / .csv")
    return 0 if failed == 0 else 1


def _export(rows: list[Evaluation], path_stem: Path) -> None:
    data = [
        {
            "evaluation_id": r.id,
            "conversation_id": r.conversation_id,
            "total": r.total_score,
            "has_critical_error": r.has_critical_error,
            "cost_usd": r.cost_usd,
            "criteria": {
                c["criterion_id"]: ("N/A" if c["status"] == "na" else c["score"])
                for c in (r.final_result or {}).get("criteria", [])
            },
        }
        for r in rows
    ]
    path_stem.with_suffix(".json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    criteria_ids = list(dict.fromkeys(k for d in data for k in d["criteria"]))
    with path_stem.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["conversation_id", "total", "critical", *criteria_ids, "cost_usd"])
        for d in data:
            writer.writerow(
                [
                    d["conversation_id"],
                    d["total"],
                    d["has_critical_error"],
                    *[d["criteria"].get(k, "") for k in criteria_ids],
                    round(d["cost_usd"], 6),
                ]
            )


if __name__ == "__main__":
    raise SystemExit(main())
