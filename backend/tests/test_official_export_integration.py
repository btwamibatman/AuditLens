"""Offline checks of persisted evaluations and the official export command."""

import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from itertools import product
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.db import Base, import_all_models
from app.core.errors import ExternalServiceError
from app.features.appeals import service as appeals_service
from app.features.appeals.schemas import AppealCreate, AppealReview
from app.features.checklists.defaults import default_checklist_config
from app.features.conversations.models import Conversation
from app.features.conversations.schemas import ConversationRecord
from app.features.conversations.service import upsert_records
from app.features.evaluations import export, service
from app.features.evaluations.llm import LLMResult
from app.features.evaluations.models import Evaluation
from app.features.evaluations.schemas import CriterionResult, Evidence
from app.features.evaluations.scoring import compute_totals


def test_every_official_score_combination_can_be_exported():
    config = default_checklist_config()
    choices = [
        [*allowed, None] if na_allowed else list(allowed)
        for _, allowed, na_allowed in export.SPECS.values()
    ]
    transcript = [{"speaker": "operator", "text": "Test evidence", "timestamp": "00:00"}]
    count = 0
    for values in product(*choices):
        criteria = []
        weighted, applicable_weight = Decimal(0), 0
        for rule, value in zip(config.criteria, values, strict=True):
            criteria.append(CriterionResult(
                criterion_id=rule.id, name=rule.name, answer_type=rule.answer_type,
                weight=rule.weight, scale_min=rule.scale_min, scale_max=rule.scale_max,
                is_critical=rule.is_critical, status="na" if value is None else "scored",
                score=value, na_reason="Test N/A reason" if value is None else "",
                explanation="Test explanation", critical_violation=bool(value) if rule.is_critical
                else False,
                evidence=[Evidence(message_index=0, quote="Test evidence", verified=True)],
            ))
            if value is not None and not rule.is_critical:
                weighted += Decimal(str(rule.weight)) * Decimal(value) / Decimal(rule.scale_max)
                applicable_weight += int(rule.weight)
        expected = (weighted * 100 / applicable_weight).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        saved = compute_totals(criteria, config.scoring).model_dump(mode="json")
        evaluation = SimpleNamespace(
            conversation_id="score-check", status="done", ai_result=saved,
        )
        result = export._convert(evaluation, transcript, "ai")
        assert Decimal(str(result["score"]["final_score"])) == expected
        assert result["score"]["critical_flag"] is bool(values[-1])
        count += 1
    assert count == 5184


def test_cli_exports_persisted_full_dev_with_failure_and_explicit_selection(tmp_path, monkeypatch):
    dataset_file = Path(__file__).resolve().parents[2] / "docs" / "invoke.json"
    dataset = json.loads(dataset_file.read_text(encoding="utf-8"))
    records = dataset["data"]["records"]
    assert len(records) == 65
    failed_id = records[2]["conversation_id"]
    calls = []

    class OfflineProvider:
        name = model = "offline-test-provider"

        def generate(self, *, system_instruction, input_text, schema):
            calls.append(input_text)
            if input_text.startswith(f"Conversation ID: {failed_id}\n"):
                return LLMResult(text="Invalid test response", model=self.model)
            size = sum(line.startswith("[#") for line in input_text.splitlines())
            ids = schema["properties"]["criteria"]["items"]["properties"]["criterion_id"]["enum"]
            return LLMResult(model=self.model, text=json.dumps({
                "criteria": [{
                    "criterion_id": cid, "applicable": True, "score": 0,
                    "critical_violation": False, "explanation": "OFFLINE TEST ONLY",
                    "evidence": [], "checked_range": {"from_index": 0, "to_index": size - 1},
                } for cid in ids],
                "summary": "OFFLINE TEST ONLY: not model quality results",
            }))

    monkeypatch.setattr(service, "get_provider", lambda: OfflineProvider())
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    import_all_models()
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    selected = []
    with session_factory() as db:
        upsert_records(db, "DEV", [ConversationRecord.model_validate(r) for r in records])
        for record in records:
            try:
                service.evaluate(db, record["conversation_id"])
            except ExternalServiceError:
                assert record["conversation_id"] == failed_id
        rows = list(db.scalars(select(Evaluation).order_by(Evaluation.id)))
        assert len(rows) == 65
        selected = [row.id for row in rows]
        checklist_id, checklist_version = rows[0].checklist_id, rows[0].checklist_version
        appeal = appeals_service.create_appeal(db, AppealCreate(
            evaluation_id=rows[0].id, criterion_id="contact", comment="Test review",
        ))
        appeals_service.review_appeal(db, appeal.id, AppealReview(
            decision="change", reviewer_comment="Offline test review", new_score=1,
        ))
        db.add(Evaluation(
            conversation_id=records[0]["conversation_id"], checklist_id=checklist_id,
            checklist_version=checklist_version, checklist_snapshot=rows[0].checklist_snapshot,
            model="unselected-later-evaluation", status="failed", error="Not selected",
        ))
        db.commit()
    assert len(calls) == 66  # 64 valid responses plus two invalid responses for one record.
    selection_file = tmp_path / "evaluation-ids.json"
    selection_file.write_text(json.dumps(selected), encoding="utf-8")
    monkeypatch.setattr(export, "SessionLocal", session_factory)
    monkeypatch.setattr(export, "ROOT_DIR", tmp_path / "test-project")
    monkeypatch.setattr(sys, "argv", [
        "export", "--kind", "dev", "--group", "DEV", "--dataset", str(dataset_file),
        "--evaluation-ids", str(selection_file), "--checklist-id", str(checklist_id),
        "--checklist-version", str(checklist_version), "--source", "ai", "--team", "Тест",
        "--model-mode", "external_api",
    ])
    export.main()
    target = export.ROOT_DIR / "results" / "dev" / "results.json"
    result = json.loads(target.read_text(encoding="utf-8"))
    assert result["team_name"] == "Тест"
    assert result["model"]["name"] == "offline-test-provider"
    assert [r["conversation_id"] for r in result["results"]] == [
        r["conversation_id"] for r in records
    ]
    assert sum(r["status"] == "error" for r in result["results"]) == 1
    failure = result["results"][2]
    assert failure["conversation_id"] == failed_id and failure["score"] is None
    assert failure["criteria"] == [] and "invalid output twice" in failure["error"]
    for source, exported in zip(records, result["results"], strict=True):
        if exported["status"] == "ok":
            assert exported["score"] == {"final_score": 0, "critical_flag": False}
            assert len(exported["criteria"]) == 8
            assert exported["criteria"][0]["evidence_turns"] == list(
                range(1, len(source["transcript"]) + 1)
            )
    sys.argv[sys.argv.index("--source") + 1] = "final"
    export.main()
    reviewed = json.loads(target.read_text(encoding="utf-8"))
    assert reviewed["model"]["mode"] == "external_api"
    assert reviewed["results"][0]["score"]["final_score"] == 10
    assert "Offline test review" in reviewed["results"][0]["criteria"][0]["rationale"]
    # A bad selection must not overwrite the already valid file.
    previous = target.read_bytes()
    selection_file.write_text(json.dumps(selected[:-1]), encoding="utf-8")
    try:
        export.main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Incomplete selection was accepted")
    assert target.read_bytes() == previous
    with session_factory() as db:
        assert len(list(db.scalars(select(Evaluation)))) == 66
        assert len(list(db.scalars(select(Conversation)))) == 65
        original = db.get(Evaluation, selected[0])
        assert original.ai_result["total"] == 0 and original.final_result["total"] == 10
    engine.dispose()
