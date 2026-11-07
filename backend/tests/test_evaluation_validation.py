import json

import pytest

from app.core.errors import ExternalServiceError
from app.features.checklists.defaults import default_checklist_config
from app.features.evaluations import service
from app.features.evaluations.llm import LLMResult


def valid_output():
    return {
        "criteria": [
            {
                "criterion_id": c.id,
                "applicable": True,
                "score": 0 if c.id == "critical" else c.scale_max,
                "critical_violation": False,
                "explanation": "Test explanation",
                "evidence": [{"message_index": 0, "quote": "Hello! My name is Alex."}],
            }
            for c in default_checklist_config().criteria
        ],
        "summary": "Test summary",
    }


def prepare_evaluation(client, monkeypatch, outputs, *, transcript=None):
    response = client.post(
        "/api/conversations/import",
        json={
            "records": [
                {
                    "conversation_id": "validation-test",
                    "transcript": transcript if transcript is not None else [
                        {"speaker": "operator", "text": "Hello! My name is Alex."}
                    ],
                }
            ]
        },
    )
    assert response.status_code == 200
    calls = []

    class Provider:
        name = model = "test"

        def generate(self, **kwargs):
            payload = outputs[min(len(calls), len(outputs) - 1)]
            calls.append(kwargs)
            return LLMResult(text=json.dumps(payload), model=self.model)

    monkeypatch.setattr(service, "get_provider", lambda: Provider())
    return calls


@pytest.mark.parametrize(
    "case",
    [
        "missing", "duplicate", "unknown", "scale", "dialogue_scale", "range", "critical",
        "forbidden_na",
        "missing_score", "missing_applicable", "missing_critical_violation",
        "missing_explanation", "missing_evidence", "missing_summary", "missing_quote",
        "string_score", "bool_score", "float_score", "string_applicable", "int_critical",
        "string_index", "bool_index", "string_range",
    ],
)
def test_invalid_output_never_becomes_successful_evaluation(client, monkeypatch, case):
    payload = valid_output()
    criteria = payload["criteria"]
    if case == "missing":
        criteria.pop(0)
    elif case == "duplicate":
        criteria.append(dict(criteria[0]))
    elif case == "unknown":
        criteria[0]["criterion_id"] = "unknown"
    elif case == "scale":
        criteria[3]["score"] = 13
    elif case == "dialogue_scale":
        criteria[5]["score"] = 5
    elif case == "range":
        criteria[0]["score"] = 2
    elif case == "critical":
        criteria[-1]["score"] = 1
    elif case == "forbidden_na":
        criteria[0]["applicable"] = False
        criteria[0]["na_reason"] = "Not applicable"
    elif case == "missing_summary":
        payload.pop("summary")
    elif case.startswith("missing_") and case != "missing_quote":
        criteria[0].pop(case.removeprefix("missing_"))
    elif case in ("missing_quote", "string_index", "bool_index"):
        criteria[0]["evidence"] = [{"message_index": 0, "quote": "Hello!"}]
        if case == "missing_quote":
            criteria[0]["evidence"][0].pop("quote")
        else:
            criteria[0]["evidence"][0]["message_index"] = "0" if case == "string_index" else False
    elif case == "string_range":
        criteria[0]["checked_range"] = {"from_index": "0", "to_index": 0}
    else:
        field, value = {
            "string_score": ("score", "1"),
            "bool_score": ("score", True),
            "float_score": ("score", 1.0),
            "string_applicable": ("applicable", "true"),
            "int_critical": ("critical_violation", 0),
        }[case]
        criteria[0][field] = value

    calls = prepare_evaluation(client, monkeypatch, [payload])
    response = client.post("/api/evaluations", json={"conversation_id": "validation-test"})
    assert response.status_code == 502
    assert len(calls) == 2
    evaluations = client.get("/api/evaluations").json()
    assert len(evaluations) == 1 and evaluations[0]["status"] == "failed"
    saved = client.get(f"/api/evaluations/{evaluations[0]['id']}").json()
    assert saved["ai_result"] is None and saved["final_result"] is None
    assert saved["total_score"] is None and saved["error"]


@pytest.mark.parametrize(
    "case",
    ["empty_criteria", "missing_score", "string_score", "invalid_range", "no_evidence",
     "unverified_na"],
)
def test_corrected_retry_is_scored_with_na_and_critical_flag(client, monkeypatch, case):
    invalid = valid_output()
    if case == "empty_criteria":
        invalid["criteria"] = []
    elif case == "missing_score":
        invalid["criteria"][0].pop("score")
    elif case == "string_score":
        invalid["criteria"][0]["score"] = "1"
    elif case == "invalid_range":
        invalid["criteria"][0]["checked_range"] = {"from_index": 0, "to_index": 99}
    elif case == "no_evidence":
        invalid["criteria"][0]["evidence"] = []
    else:
        invalid["criteria"][1].update(
            applicable=False, score=0, na_reason="Request already clear", evidence=[],
        )
    valid = valid_output()
    valid["criteria"][0]["score"] = 0
    valid["criteria"][1].update(applicable=False, score=0, na_reason="Request already clear")
    valid["criteria"][-1].update(score=1, critical_violation=True)
    calls = prepare_evaluation(client, monkeypatch, [invalid, valid])
    response = client.post("/api/evaluations", json={"conversation_id": "validation-test"})
    assert response.status_code == 201
    result = response.json()
    assert len(calls) == 2 and result["status"] == "done"
    assert result["total_score"] == 88.24 and result["has_critical_error"] is True
    assert len(result["final_result"]["criteria"]) == 8
    assert result["final_result"]["criteria"][1]["status"] == "na"


@pytest.mark.parametrize(
    "index,quote,verified,expected_index",
    [
        (0, "Hello! My name is Alex.", True, 0),
        (99, "My name is Alex.", True, 0),
        (-1, "My name is Alex.", True, 0),
        (0, "Hello! My name is Alice.", False, 0),
        (0, "hello! my name is alex.", False, 0),
        (0, "Здравствуйте! Меня зовут Алекс.", False, 0),
        (0, "", False, 0),
        (0, "   ", False, 0),
        (99, "Invented quote", None, None),
        (-1, "", None, None),
    ],
)
def test_evidence_verification_is_preserved_in_saved_evaluation(
    client, monkeypatch, index, quote, verified, expected_index
):
    payload = valid_output()
    payload["criteria"][0]["evidence"] = [{"message_index": index, "quote": quote}]
    payload["criteria"][0]["checked_range"] = {"from_index": 0, "to_index": 0}
    prepare_evaluation(client, monkeypatch, [payload])
    response = client.post("/api/evaluations", json={"conversation_id": "validation-test"})
    assert response.status_code == 201
    saved = client.get(f"/api/evaluations/{response.json()['id']}").json()
    result = saved["ai_result"]["criteria"][0]
    assert result["explanation"] == "Test explanation"
    assert result["checked_range"]["from_index"] == 0
    if verified is None:
        assert result["evidence"] == []
        assert f"evidence_index_out_of_range:{index}" in result["warnings"]
    else:
        assert result["evidence"][0]["verified"] is verified
        assert result["evidence"][0]["message_index"] == expected_index
        assert result["evidence"][0]["quote"] == quote
        if not verified:
            assert f"quote_not_found:#{index}" in result["warnings"]


def test_exact_quote_relocated_with_original_metadata():
    transcript = [
        {"text": "Question", "speaker": "client", "timestamp": "00:00"},
        {"text": "Hello!\n My name is Alex.", "speaker": "operator", "timestamp": "00:05"},
    ]
    evidence = service._ground_one(transcript, 0, "Hello! My name is Alex.")
    assert evidence.verified is True
    assert evidence.message_index == 1
    assert evidence.speaker == "operator" and evidence.timestamp == "00:05"
    assert service._ground_one([], 0, "Hello!") is None


@pytest.mark.parametrize(
    "case,error_fragment",
    [
        ("no_support", "evidence"),
        ("unverified_quote", "evidence"),
        ("empty_quote", "evidence"),
        ("unresolvable_index", "evidence"),
        ("blank_explanation", "explanation"),
        ("negative_range", "checked_range"),
        ("oversized_range", "checked_range"),
        ("reversed_range", "checked_range"),
        ("na_without_reason", "N/A"),
        ("na_without_evidence", "N/A"),
        ("na_with_unverified_quote", "N/A"),
        ("na_with_range_only", "N/A"),
        ("na_critical", "N/A"),
    ],
)
def test_invalid_support_is_retried_and_saved_as_failed(client, monkeypatch, case, error_fragment):
    payload = valid_output()
    target = payload["criteria"][1 if case.startswith("na_") else 0]
    if case.startswith("na_"):
        target.update(applicable=False, score=0, na_reason="Request already clear")
    if case in ("no_support", "na_without_evidence", "na_with_range_only"):
        target["evidence"] = []
    elif case in ("unverified_quote", "na_with_unverified_quote"):
        target["evidence"][0]["quote"] = "Hello! My name is Alice."
    elif case == "empty_quote":
        target["evidence"][0]["quote"] = ""
    elif case == "unresolvable_index":
        target["evidence"] = [{"message_index": 99, "quote": "Invented quote"}]
    elif case == "blank_explanation":
        target["explanation"] = " \n "
    elif case.endswith("_range"):
        start, end = {
            "negative_range": (-1, 0),
            "oversized_range": (0, 2),
            "reversed_range": (1, 0),
        }[case]
        target["checked_range"] = {"from_index": start, "to_index": end}
    elif case == "na_without_reason":
        target["na_reason"] = " \n "
    elif case == "na_critical":
        target["critical_violation"] = True
    if case == "na_with_range_only":
        target["checked_range"] = {"from_index": 0, "to_index": 1}
    transcript = [
        {"speaker": "operator", "text": "Hello! My name is Alex."},
        {"speaker": "client", "text": "What are your fees?"},
    ]
    calls = prepare_evaluation(client, monkeypatch, [payload], transcript=transcript)
    response = client.post("/api/evaluations", json={"conversation_id": "validation-test"})
    assert response.status_code == 502 and len(calls) == 2
    saved = client.get(f"/api/evaluations/{client.get('/api/evaluations').json()[0]['id']}").json()
    assert saved["status"] == "failed" and error_fragment in saved["error"]
    assert saved["ai_result"] is None and saved["final_result"] is None
    assert saved["total_score"] is None


def test_missing_action_uses_range_and_na_can_cite_context(client, monkeypatch):
    payload = valid_output()
    for criterion in payload["criteria"]:
        criterion["evidence"][0]["quote"] = "The fees are published online."
    payload["criteria"][0].update(
        score=0, evidence=[], explanation="No greeting in the inspected opening.",
        checked_range={"from_index": 0, "to_index": 3},
    )
    payload["criteria"][1].update(
        applicable=False, score=0,
        na_reason="The client already stated a complete general question.",
        evidence=[{"message_index": 0, "quote": "What are your fees?"}],
    )
    transcript = [
        {"speaker": "bot", "text": "Welcome", "timestamp": "00:00"},
        {"speaker": "client", "text": "What are your fees?", "timestamp": "00:01"},
        {"speaker": "system", "text": "Operator joined", "timestamp": "00:02"},
        {"speaker": "operator", "text": "The fees are published online.", "timestamp": "00:03"},
    ]
    calls = prepare_evaluation(client, monkeypatch, [payload], transcript=transcript)
    response = client.post("/api/evaluations", json={"conversation_id": "validation-test"})
    assert response.status_code == 201 and len(calls) == 1
    saved = client.get(f"/api/evaluations/{response.json()['id']}").json()
    missing, na = saved["ai_result"]["criteria"][:2]
    assert missing["evidence"] == [] and missing["score"] == 0
    assert missing["explanation"] == "No greeting in the inspected opening."
    assert missing["checked_range"] == {
        "from_index": 0, "to_index": 3, "from_timestamp": "00:00", "to_timestamp": "00:03",
    }
    assert na["status"] == "na" and na["score"] is None
    assert na["na_reason"] == payload["criteria"][1]["na_reason"]
    assert na["evidence"][0]["message_index"] == 1
    assert na["evidence"][0]["speaker"] == "client" and na["evidence"][0]["verified"]
    assert saved["total_score"] == 88.24


@pytest.mark.parametrize(
    "case", ["omitted", "included_auto", "included_disabled", "missing_requested"]
)
def test_only_requested_criteria_are_required_from_ai(client, monkeypatch, case):
    config = default_checklist_config().model_dump(mode="json")
    config["criteria"][0]["channels"] = ["call"]
    config["criteria"][4]["enabled"] = False
    checklist = client.post("/api/checklists", json={"name": "Channel test", "config": config})
    assert checklist.status_code == 201
    payload = valid_output()
    auto = payload["criteria"].pop(0)
    disabled = payload["criteria"].pop(3)
    if case == "included_auto":
        payload["criteria"].append(auto)
    elif case == "included_disabled":
        payload["criteria"].append(disabled)
    elif case == "missing_requested":
        payload["criteria"].pop(0)
    calls = prepare_evaluation(client, monkeypatch, [payload])
    response = client.post("/api/evaluations", json={
        "conversation_id": "validation-test", "checklist_id": checklist.json()["id"],
    })
    properties = calls[0]["schema"]["properties"]["criteria"]["items"]["properties"]
    ids = properties["criterion_id"]["enum"]
    assert "contact" not in ids and "empathy" not in ids and len(ids) == 6
    if case != "omitted":
        assert response.status_code == 502 and len(calls) == 2
        return
    assert response.status_code == 201 and len(calls) == 1
    result = response.json()["ai_result"]
    assert len(result["criteria"]) == 7
    auto_result = result["criteria"][0]
    assert auto_result["criterion_id"] == "contact" and auto_result["source"] == "auto"
    assert auto_result["status"] == "na" and auto_result["score"] is None
    assert auto_result["evidence"] == [] and auto_result["checked_range"] is None
    assert auto_result["na_reason"] and auto_result["effective_weight"] == 0
    assert result["total"] == 100


def test_all_auto_na_does_not_call_ai(client, monkeypatch):
    config = default_checklist_config().model_dump(mode="json")
    for criterion in config["criteria"]:
        criterion["channels"] = ["call"]
    checklist = client.post("/api/checklists", json={"name": "Call only", "config": config})
    assert checklist.status_code == 201
    calls = prepare_evaluation(client, monkeypatch, [valid_output()])
    response = client.post("/api/evaluations", json={
        "conversation_id": "validation-test", "checklist_id": checklist.json()["id"],
    })
    assert response.status_code == 201 and calls == []
    result = response.json()["ai_result"]
    assert result["total"] is None and len(result["criteria"]) == 8
    assert all(c["source"] == "auto" and c["status"] == "na" for c in result["criteria"])


def test_missing_criterion_cannot_be_built_as_zero():
    criterion = default_checklist_config().criteria[0]
    with pytest.raises(ExternalServiceError, match="omitted criterion contact"):
        service.build_criterion_result(criterion, None, [])
