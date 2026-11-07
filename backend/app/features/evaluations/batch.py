
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from app.core.config import BACKEND_DIR
from app.core.db import SessionLocal
from app.features.checklists import service as checklist_service
from app.features.conversations import service as conversation_service
from app.features.evaluations import service
from app.features.evaluations.llm import get_provider
from app.features.evaluations.models import Evaluation
from app.features.evaluations.schemas import BatchRequest


def main() -> int:
    parser = argparse.ArgumentParser(description="AuditLens batch evaluation")
    parser.add_argument("--group", help="dataset_group (DEV, контрольный group_id, manual)")
    parser.add_argument("--ids", nargs="*", help="конкретные conversation_id")
    parser.add_argument("--checklist", type=int, help="ID чек-листа (по умолчанию активный)")
    parser.add_argument("--sync", action="store_true", help="сначала загрузить набор из API")
    parser.add_argument("--only-missing", action="store_true", help="пропустить уже оценённые")
    parser.add_argument("--limit", type=int, help="оценить только первые N")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with SessionLocal() as db:
        if args.sync:
            if not args.group:
                parser.error("--sync requires --group")
            res = conversation_service.sync_dataset(db, args.group)
            print(f"Synced {res.total} records (new {res.created}, updated {res.updated})")
        checklist_service.ensure_default(db)
        ids, checklist_id = service.resolve_batch_targets(
            db,
            BatchRequest(
                dataset_group=args.group,
                conversation_ids=args.ids,
                checklist_id=args.checklist,
                only_missing=args.only_missing,
            ),
        )
    if args.limit:
        ids = ids[: args.limit]

    provider = get_provider()
    m_name = getattr(provider, "model", provider.name)
    print(f"Model: {m_name} | checklist #{checklist_id} | {len(ids)} conversations")

    def progress(cid, job):
        mark = "ERR" if cid in job.errors else "ok "
        print(f"  [{job.done + job.failed:>3}/{job.total}] {mark} {cid}")

    job = service.run_batch(ids, checklist_id, on_progress=progress)

    with SessionLocal() as db:
        rows = [db.get(Evaluation, i) for i in job.evaluation_ids]
    rows = sorted((r for r in rows if r), key=lambda r: r.conversation_id)
    export_dir = BACKEND_DIR / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.group or 'selection'}_{datetime.now():%Y%m%d_%H%M%S}"
    _export(rows, export_dir / stem)

    n = max(job.done, 1)
    print(f"\nDone: {job.done}, failed: {job.failed}")
    print(
        f"Total cost: ${job.total_cost_usd:.4f} | avg per evaluation: ${job.total_cost_usd / n:.5f}"
    )
    for cid, err in job.errors.items():
        print(f"  ! {cid}: {err}")
    print(f"Export: {export_dir / stem}.json / .csv")
    return 0 if job.failed == 0 else 1


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
