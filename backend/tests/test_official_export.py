import copy
import json
from types import SimpleNamespace

import pytest

from app.features.checklists.defaults import DEFAULT_CHECKLIST
from app.features.evaluations.export import ExportError, build_export, write_atomic


def saved_result(*, critical=False):
    values = {
        "contact": 1,
        "discovery": None,
        "identification": None,
        "consultation": 15,
        "empathy": 1,
        "dialogue": 7,
        "closure": 1,
        "critical": int(critical),
    }
    criteria = []
    for name, value in values.items():
        criteria.append(
            {
                "criterion_id": name,
                "status": "na" if value is None else "scored",
                "score": value,
                "explanation": "Обоснование",
                "na_reason": "Общий вопрос",
                "critical_violation": critical if name == "critical" else False,
                "evidence": [{"message_index": 1}],
            }
        )
    return {"criteria": criteria, "total": 85.38, "has_critical_error": critical}


def fixture_set(count, group):
    records, evaluations, conversations = [], [], []
    for n in range(count):
        cid = f"test-{n}"
        transcript = [{"speaker": "client", "text": "x"}, {"speaker": "operator", "text": "y"}]
        records.append({"conversation_id": cid, "transcript": transcript})
        result = saved_result(critical=n == 1)
        evaluations.append(
            SimpleNamespace(
                id=n + 1,
                conversation_id=cid,
                checklist_id=1,
                checklist_version=2,
                checklist_snapshot=copy.deepcopy(DEFAULT_CHECKLIST),
                model="test-model",
                status="done",
                error=None,
                ai_result=result,
                final_result=copy.deepcopy(result),
            )
        )
        conversations.append(SimpleNamespace(id=cid, dataset_group=group, transcript=transcript))
    dataset = {
        "isSuccess": True,
        "data": {"dataset_group_id": group, "total_records": count, "records": records},
    }
    return dataset, evaluations, conversations


def build(items, kind, group):
    return build_export(
        *items,
        kind=kind,
        group=group,
        checklist_id=1,
        checklist_version=2,
        source="ai",
        team="Команда",
        model_mode="external_api",
    )


@pytest.mark.parametrize(("kind", "group", "count"), [("dev", "DEV", 65), ("prod", "CONTROL", 10)])
def test_official_export_mixed_results(tmp_path, kind, group, count):
    items = fixture_set(count, group)
    items[1][2].status = "failed"
    items[1][2].error = "Ошибка модели"
    output = build(items, kind, group)
    assert output["schema_version"] == "1.0" and len(output["results"]) == count
    success, critical, failure = output["results"][:3]
    assert success["score"] == {"final_score": 85.38, "critical_flag": False}
    assert success["criteria"][0]["value"] is True
    assert success["criteria"][1]["value"] is None
    assert success["criteria"][0]["evidence_turns"] == [2]
    assert critical["score"] == {"final_score": 85.38, "critical_flag": True}
    assert failure == {
        "conversation_id": "test-2",
        "status": "error",
        "criteria": [],
        "score": None,
        "error": "Ошибка модели",
    }
    path = tmp_path / "results.json"
    write_atomic(output, path)
    assert json.loads(path.read_text(encoding="utf-8")) == output


@pytest.mark.parametrize(
    "invalid",
    [
        "missing",
        "duplicate",
        "index",
        "value",
        "score",
        "critical",
        "snapshot",
        "transcript",
        "failure",
        "version",
    ],
)
def test_invalid_data_rejected_before_write(tmp_path, invalid):
    items = fixture_set(10, "CONTROL")
    dataset, evaluations, conversations = items
    if invalid == "missing":
        evaluations.pop()
    if invalid == "duplicate":
        dataset["data"]["records"][1]["conversation_id"] = "test-0"
    if invalid == "index":
        evaluations[0].ai_result["criteria"][0]["evidence"][0]["message_index"] = 2
    if invalid == "value":
        evaluations[0].ai_result["criteria"][3]["score"] = 6
    if invalid == "score":
        evaluations[0].ai_result["total"] = 1
    if invalid == "critical":
        evaluations[0].ai_result["has_critical_error"] = True
    if invalid == "snapshot":
        evaluations[0].checklist_snapshot = {"other": 1}
    if invalid == "transcript":
        conversations[0].transcript = []
    if invalid == "failure":
        evaluations[0].status, evaluations[0].error = "failed", ""
    if invalid == "version":
        evaluations[0].checklist_version = 3
    target = tmp_path / "results.json"
    target.write_text("existing", encoding="utf-8")
    with pytest.raises(ExportError):
        payload = build(items, "prod", "CONTROL")
        write_atomic(payload, target)
    assert target.read_text(encoding="utf-8") == "existing"


def test_final_results_require_hybrid_mode():
    items = fixture_set(10, "CONTROL")
    items[1][0].final_result["criteria"][0]["explanation"] = "Изменено проверяющим"
    with pytest.raises(ExportError, match="hybrid"):
        build_export(
            *items,
            kind="prod",
            group="CONTROL",
            checklist_id=1,
            checklist_version=2,
            source="final",
            team="Команда",
            model_mode="external_api",
        )


def test_partial_dataset_rejected():
    with pytest.raises(ExportError, match="count"):
        build(fixture_set(2, "DEV"), "dev", "DEV")
