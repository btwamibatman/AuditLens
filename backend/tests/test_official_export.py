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
                "evidence": [{"message_index": 1, "quote": "y", "verified": True}],
            }
        )
    return {"criteria": criteria, "total": 85.38, "has_critical_error": critical}


def fixture_set(count, group):
    records, evaluations, conversations = [], [], []
    for n in range(count):
        cid = f"test-{n}"
        transcript = [
            {"speaker": "client", "text": "x", "timestamp": "00:00"},
            {"speaker": "operator", "text": "y", "timestamp": "00:01"},
        ]
        records.append({
            "conversation_id": cid, "transcript": transcript,
            "channel": "agent chat", "language": "RU", "audio_url": None,
        })
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
        conversations.append(SimpleNamespace(
            id=cid, dataset_group=group, transcript=transcript,
            channel="agent chat", language="RU", audio_url=None,
        ))
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


def test_ai_and_final_are_selected_explicitly_without_changing_model_deployment_mode():
    items = fixture_set(10, "CONTROL")
    items[1][0].final_result["criteria"][0]["explanation"] = "Изменено проверяющим"
    output = build_export(
            *items,
            kind="prod",
            group="CONTROL",
            checklist_id=1,
            checklist_version=2,
            source="final",
            team="Команда",
            model_mode="external_api",
    )
    assert output["model"] == {"mode": "external_api", "name": "test-model"}
    assert output["results"][0]["criteria"][0]["rationale"] == "Изменено проверяющим"
    original = build(items, "prod", "CONTROL")
    assert original["results"][0]["criteria"][0]["rationale"] == "Обоснование"


def test_partial_dataset_rejected():
    with pytest.raises(ExportError, match="count"):
        build(fixture_set(2, "DEV"), "dev", "DEV")


@pytest.mark.parametrize("invalid", [
    "mock", "disabled", "channel_rule", "binary_scale", "scale_max", "scoring_policy",
    "rounding", "extra_critical", "language", "channel", "audio", "unverified",
    "forged_verified", "na_without_reason", "na_with_range_only", "range_negative",
    "range_reversed", "range_oversized", "critical_on_other_criterion",
])
def test_incompatible_saved_data_cannot_be_submitted(invalid):
    items = fixture_set(10, "CONTROL")
    _, evaluations, conversations = items
    ev = evaluations[0]
    snapshot = ev.checklist_snapshot
    target = ev.ai_result["criteria"][0]
    if invalid == "mock":
        ev.model = "mock"
    elif invalid == "disabled":
        snapshot["criteria"][0]["enabled"] = False
    elif invalid == "channel_rule":
        snapshot["criteria"][0]["channels"] = ["call"]
    elif invalid == "binary_scale":
        snapshot["criteria"][0]["scale_max"] = 2
    elif invalid == "scale_max":
        snapshot["criteria"][3]["scale_max"] = 25
    elif invalid == "scoring_policy":
        snapshot["scoring"]["critical_policy"] = "zero_total"
    elif invalid == "rounding":
        snapshot["scoring"]["rounding_digits"] = 0
    elif invalid == "extra_critical":
        snapshot["criteria"][0]["is_critical"] = True
    elif invalid in ("language", "channel", "audio"):
        setattr(conversations[0], {"audio": "audio_url"}.get(invalid, invalid), "changed")
    elif invalid == "unverified":
        target["evidence"][0]["verified"] = False
    elif invalid == "forged_verified":
        target["evidence"][0]["quote"] = "Invented quote"
    elif invalid == "na_without_reason":
        ev.ai_result["criteria"][1]["na_reason"] = ""
    elif invalid == "na_with_range_only":
        ev.ai_result["criteria"][1].update(
            evidence=[], checked_range={"from_index": 0, "to_index": 1},
        )
    elif invalid.startswith("range_"):
        start, end = {"range_negative": (-1, 1), "range_reversed": (1, 0),
                      "range_oversized": (0, 2)}[invalid]
        target["checked_range"] = {"from_index": start, "to_index": end}
    else:
        target["critical_violation"] = True
    if invalid in {"disabled", "channel_rule", "binary_scale", "scale_max", "scoring_policy",
                   "rounding", "extra_critical"}:
        for evaluation in evaluations:
            evaluation.checklist_snapshot = copy.deepcopy(snapshot)
    with pytest.raises(ExportError):
        build(items, "prod", "CONTROL")


def test_ranges_and_verified_quotes_use_all_original_roles_once():
    items = fixture_set(10, "CONTROL")
    dataset, evaluations, conversations = items
    transcript = [
        {"speaker": "bot", "text": "Welcome", "timestamp": "00:00"},
        {"speaker": "client", "text": "General question", "timestamp": "00:01"},
        {"speaker": "system", "text": "Operator joined", "timestamp": "00:02"},
        {"speaker": "operator", "text": "y", "timestamp": "00:03"},
    ]
    dataset["data"]["records"][0]["transcript"] = transcript
    conversations[0].transcript = transcript
    for criterion in evaluations[0].ai_result["criteria"]:
        criterion["evidence"] = [{"message_index": 3, "quote": "y", "verified": True}]
    target = evaluations[0].ai_result["criteria"][0]
    target.update(evidence=[], checked_range={"from_index": 0, "to_index": 3})
    result = build(items, "prod", "CONTROL")["results"][0]
    assert result["criteria"][0]["evidence_turns"] == [1, 2, 3, 4]
    target["evidence"] = [
        {"message_index": 3, "quote": "y", "verified": True},
        {"message_index": 3, "quote": "y", "verified": True},
        {"message_index": 0, "quote": "fabricated", "verified": False},
    ]
    target["checked_range"] = {"from_index": 2, "to_index": 3}
    result = build(items, "prod", "CONTROL")["results"][0]
    assert result["criteria"][0]["evidence_turns"] == [3, 4]
    assert result["criteria"][1]["evidence_turns"] == [4]


def test_failed_write_preserves_existing_file_and_removes_temporary_file(tmp_path, monkeypatch):
    from app.features.evaluations import export

    target = tmp_path / "results.json"
    target.write_bytes(b"existing")

    def fail_replace(*args):
        raise OSError("Simulated write failure")

    monkeypatch.setattr(export.os, "replace", fail_replace)
    with pytest.raises(OSError, match="Simulated"):
        write_atomic(build(fixture_set(10, "CONTROL"), "prod", "CONTROL"), target)
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [target]


def test_input_order_is_preserved_and_selection_order_does_not_pick_latest():
    items = fixture_set(10, "CONTROL")
    items[1].reverse()
    items[2].reverse()
    result = build(items, "prod", "CONTROL")
    assert [r["conversation_id"] for r in result["results"]] == [f"test-{n}" for n in range(10)]


@pytest.mark.parametrize("dataset", [None, [], {}, {"isSuccess": False},
                                   {"isSuccess": True, "data": []}])
def test_invalid_dataset_envelope_has_clear_validation_error(dataset):
    _, evaluations, conversations = fixture_set(10, "CONTROL")
    with pytest.raises(ExportError, match="source dataset"):
        build((dataset, evaluations, conversations), "prod", "CONTROL")


@pytest.mark.parametrize("value", [True, 1.0, "1", None])
def test_evidence_indexes_remain_strict_integers(value):
    items = fixture_set(10, "CONTROL")
    items[1][0].ai_result["criteria"][0]["evidence"][0]["message_index"] = value
    with pytest.raises(ExportError, match="evidence"):
        build(items, "prod", "CONTROL")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "85.38"])
def test_invalid_saved_totals_are_rejected(value):
    items = fixture_set(10, "CONTROL")
    items[1][0].ai_result["total"] = value
    with pytest.raises(ExportError, match="total"):
        build(items, "prod", "CONTROL")


def test_serialization_failure_does_not_replace_existing_file(tmp_path):
    target = tmp_path / "results.json"
    target.write_bytes(b"existing")
    with pytest.raises(ValueError):
        write_atomic({"non_json_value": float("nan")}, target)
    assert target.read_bytes() == b"existing" and list(tmp_path.iterdir()) == [target]


def test_database_failure_has_clear_cli_error_without_connection_details(
    tmp_path, monkeypatch, capsys
):
    import sys

    from sqlalchemy.exc import SQLAlchemyError

    from app.features.evaluations import export

    dataset, _, _ = fixture_set(10, "CONTROL")
    dataset_file = tmp_path / "dataset.json"
    selected_file = tmp_path / "ids.json"
    dataset_file.write_text(json.dumps(dataset), encoding="utf-8")
    selected_file.write_text(json.dumps(list(range(1, 11))), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "export", "--kind", "prod", "--group", "CONTROL", "--dataset", str(dataset_file),
        "--evaluation-ids", str(selected_file), "--checklist-id", "1", "--checklist-version", "2",
        "--source", "ai", "--team", "Test", "--model-mode", "external_api",
    ])

    def unavailable():
        raise SQLAlchemyError("sensitive connection details")

    monkeypatch.setattr(export, "SessionLocal", unavailable)
    with pytest.raises(SystemExit) as exc:
        export.main()
    assert exc.value.code == 1
    error = capsys.readouterr().err
    assert "database" in error and "sensitive" not in error and "Traceback" not in error
