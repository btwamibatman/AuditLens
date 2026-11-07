"""Export an explicitly selected set of saved evaluations in the official CQA format."""

import argparse
import json
import os
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.config import ROOT_DIR
from app.core.db import SessionLocal
from app.features.conversations.models import Conversation
from app.features.evaluations.models import Evaluation

SPECS = {
    "contact": (10, (0, 1), False),
    "discovery": (15, (0, 1), True),
    "identification": (20, (0, 1), True),
    "consultation": (20, (0, 5, 10, 15, 20), True),
    "empathy": (15, (0, 1), False),
    "dialogue": (15, (0, 4, 7, 10), False),
    "closure": (5, (0, 1), True),
    "critical": (0, (0, 1), False),
}
EXPECTED_COUNTS = {"dev": 65, "prod": 10}


class ExportError(ValueError):
    """The selected saved data cannot be exported safely."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ExportError(message)


def _validate_snapshot(snapshot: dict) -> None:
    rules = snapshot.get("criteria")
    _require(isinstance(rules, list) and len(rules) == len(SPECS), "Invalid checklist snapshot")
    _require(
        all(isinstance(rule, dict) and isinstance(rule.get("id"), str) for rule in rules),
        "Invalid checklist snapshot",
    )
    by_id = {rule["id"]: rule for rule in rules}
    _require(set(by_id) == set(SPECS), "Checklist criteria do not match official criteria")
    for name, (weight, allowed, na_allowed) in SPECS.items():
        rule = by_id[name]
        _require(
            rule.get("weight") == weight and rule.get("na_allowed", False) == na_allowed,
            f"{name}: checklist weight or N/A rule does not match official criteria",
        )
        _require(
            rule.get("answer_type") == ("binary" if len(allowed) == 2 else "scale"),
            f"{name}: incorrect checklist answer type",
        )
        if len(allowed) != 2:
            levels = rule.get("scale_levels", [])
            _require(
                isinstance(levels, list)
                and all(
                    isinstance(level, dict) and type(level.get("value")) is int for level in levels
                )
                and {level["value"] for level in levels} == set(allowed),
                f"{name}: checklist scale does not match official criteria",
            )
    _require(
        by_id["critical"].get("is_critical") is True,
        "Checklist critical criterion is not marked critical",
    )


def _convert(evaluation: Evaluation, transcript: list, source: str) -> dict:
    cid = evaluation.conversation_id
    if evaluation.status == "failed":
        _require(
            isinstance(evaluation.error, str) and bool(evaluation.error.strip()),
            f"{cid}: missing failure reason",
        )
        return {
            "conversation_id": cid,
            "status": "error",
            "criteria": [],
            "score": None,
            "error": evaluation.error,
        }
    _require(evaluation.status == "done", f"{cid}: evaluation is not complete")
    saved = evaluation.ai_result if source == "ai" else evaluation.final_result
    _require(
        isinstance(saved, dict) and isinstance(saved.get("criteria"), list),
        f"{cid}: missing saved {source} result",
    )
    by_id = {}
    for item in saved["criteria"]:
        _require(isinstance(item, dict), f"{cid}: invalid criterion")
        criterion_id = item.get("criterion_id")
        _require(
            criterion_id in SPECS and criterion_id not in by_id,
            f"{cid}: unknown or duplicate criterion {criterion_id}",
        )
        by_id[criterion_id] = item
    _require(set(by_id) == set(SPECS), f"{cid}: missing criteria")
    criteria = []
    numerator = Decimal(0)
    denominator = 0
    critical = None
    for criterion_id, (weight, allowed, na_allowed) in SPECS.items():
        item = by_id[criterion_id]
        status, raw = item.get("status"), item.get("score")
        _require(status in ("na", "scored"), f"{cid}/{criterion_id}: invalid status")
        if status == "na":
            _require(na_allowed and raw is None, f"{cid}/{criterion_id}: invalid N/A")
            value = None
            rationale = item.get("na_reason") or item.get("explanation")
        else:
            _require(type(raw) is int and raw in allowed, f"{cid}/{criterion_id}: invalid value")
            value = bool(raw) if len(allowed) == 2 else raw
            rationale = item.get("explanation")
            if criterion_id == "critical":
                _require(
                    type(item.get("critical_violation")) is bool
                    and item["critical_violation"] == value,
                    f"{cid}: inconsistent critical criterion",
                )
                critical = value
            else:
                numerator += Decimal(weight) * Decimal(raw) / Decimal(max(allowed))
                denominator += weight
        _require(
            isinstance(rationale, str) and bool(rationale.strip()),
            f"{cid}/{criterion_id}: missing rationale",
        )
        evidence = item.get("evidence")
        _require(
            isinstance(evidence, list) and bool(evidence), f"{cid}/{criterion_id}: missing evidence"
        )
        turns = []
        for entry in evidence:
            _require(
                isinstance(entry, dict)
                and type(entry.get("message_index")) is int
                and 0 <= entry["message_index"] < len(transcript),
                f"{cid}/{criterion_id}: invalid evidence index",
            )
            turns.append(entry["message_index"] + 1)
        criteria.append(
            {
                "criterion_id": criterion_id,
                "value": value,
                "rationale": rationale,
                "evidence_turns": turns,
            }
        )
    _require(denominator > 0 and type(critical) is bool, f"{cid}: cannot calculate score")
    expected = (Decimal(100) * numerator / Decimal(denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    actual = saved.get("total")
    _require(
        type(actual) in (int, float) and Decimal(str(actual)) == expected and 0 <= expected <= 100,
        f"{cid}: saved total does not match official scoring",
    )
    _require(
        type(saved.get("has_critical_error")) is bool and saved["has_critical_error"] == critical,
        f"{cid}: inconsistent critical flag",
    )
    return {
        "conversation_id": cid,
        "status": "ok",
        "criteria": criteria,
        "score": {"final_score": actual, "critical_flag": critical},
    }


def build_export(
    dataset: dict,
    evaluations: list[Evaluation],
    conversations: list[Conversation],
    *,
    kind: str,
    group: str,
    checklist_id: int,
    checklist_version: int,
    source: str,
    team: str,
    model_mode: str,
) -> dict:
    _require(kind in EXPECTED_COUNTS and source in ("ai", "final"), "Invalid export mode")
    _require(
        model_mode in ("local", "external_api", "hybrid") and bool(team.strip()),
        "Team name and valid model mode are required",
    )
    _require(
        dataset.get("isSuccess") is True and isinstance(dataset.get("data"), dict),
        "Invalid source dataset",
    )
    data = dataset["data"]
    records = data.get("records")
    _require(
        data.get("dataset_group_id") == group and isinstance(records, list),
        "Dataset group does not match",
    )
    _require(
        type(data.get("total_records")) is int
        and data["total_records"] == len(records) == EXPECTED_COUNTS[kind],
        "Incorrect source dataset count",
    )
    _require(
        all(
            isinstance(r, dict)
            and isinstance(r.get("conversation_id"), str)
            and r["conversation_id"].strip()
            and isinstance(r.get("transcript"), list)
            for r in records
        ),
        "Invalid source record",
    )
    ids = [r["conversation_id"] for r in records]
    _require(len(set(ids)) == len(ids), "Duplicate source conversation ID")
    _require(
        len(evaluations) == len(ids) and len({e.id for e in evaluations}) == len(ids),
        "Incorrect or duplicate evaluation selection",
    )
    evaluations_by_id = {e.conversation_id: e for e in evaluations}
    _require(
        len(evaluations_by_id) == len(evaluations) and set(evaluations_by_id) == set(ids),
        "Evaluation IDs do not match source conversations",
    )
    db_conversations = {c.id: c for c in conversations}
    _require(
        len(db_conversations) == len(conversations) and set(db_conversations) == set(ids),
        "Saved conversations do not match source conversations",
    )
    snapshots = set()
    models = set()
    results = []
    for record in records:
        cid = record["conversation_id"]
        evaluation = evaluations_by_id[cid]
        conv = db_conversations[cid]
        _require(
            conv.dataset_group == group and conv.transcript == record["transcript"],
            f"{cid}: saved transcript or group differs from source",
        )
        _require(
            evaluation.checklist_id == checklist_id
            and evaluation.checklist_version == checklist_version
            and isinstance(evaluation.checklist_snapshot, dict),
            f"{cid}: checklist mismatch",
        )
        _validate_snapshot(evaluation.checklist_snapshot)
        snapshots.add(json.dumps(evaluation.checklist_snapshot, sort_keys=True, ensure_ascii=False))
        _require(
            isinstance(evaluation.model, str) and bool(evaluation.model.strip()),
            f"{cid}: missing model name",
        )
        models.add(evaluation.model.strip())
        if source == "final" and evaluation.status == "done":
            _require(
                model_mode == "hybrid" or evaluation.final_result == evaluation.ai_result,
                f"{cid}: reviewed results require hybrid model mode",
            )
        results.append(_convert(evaluation, record["transcript"], source))
    _require(len(snapshots) == 1, "Checklist snapshots differ")
    return {
        "schema_version": "1.0",
        "team_name": team.strip(),
        "model": {"mode": model_mode, "name": ", ".join(sorted(models))},
        "results": results,
    }


def write_atomic(payload: dict, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=target.parent, delete=False
        ) as f:
            temp = Path(f.name)
            json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=EXPECTED_COUNTS)
    parser.add_argument("--group", required=True, help="Original dataset group ID")
    parser.add_argument("--dataset", required=True, type=Path, help="Original dataset JSON")
    parser.add_argument(
        "--evaluation-ids",
        required=True,
        type=Path,
        help="JSON array of selected saved evaluation IDs",
    )
    parser.add_argument("--checklist-id", required=True, type=int)
    parser.add_argument("--checklist-version", required=True, type=int)
    parser.add_argument("--source", required=True, choices=("ai", "final"))
    parser.add_argument("--team", required=True)
    parser.add_argument("--model-mode", required=True, choices=("local", "external_api", "hybrid"))
    args = parser.parse_args()
    try:
        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        selected = json.loads(args.evaluation_ids.read_text(encoding="utf-8"))
        _require(
            isinstance(selected, list)
            and all(type(i) is int and i > 0 for i in selected)
            and len(set(selected)) == len(selected),
            "Invalid evaluation ID selection",
        )
        with SessionLocal() as db:
            evaluations = list(db.scalars(select(Evaluation).where(Evaluation.id.in_(selected))))
            _require(len(evaluations) == len(selected), "Selected evaluation does not exist")
            conversations = list(
                db.scalars(
                    select(Conversation).where(
                        Conversation.id.in_([e.conversation_id for e in evaluations])
                    )
                )
            )
            payload = build_export(
                dataset,
                evaluations,
                conversations,
                kind=args.kind,
                group=args.group,
                checklist_id=args.checklist_id,
                checklist_version=args.checklist_version,
                source=args.source,
                team=args.team,
                model_mode=args.model_mode,
            )
        target = ROOT_DIR / "results" / args.kind / "results.json"
        write_atomic(payload, target)
        print(f"Wrote {len(payload['results'])} {args.source} results to {target}")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(1, f"Export failed: {exc}\n")


if __name__ == "__main__":
    main()
