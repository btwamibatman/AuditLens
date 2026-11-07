import json

import pytest

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
                "evidence": [],
            }
            for c in default_checklist_config().criteria
        ],
        "summary": "Test summary",
    }


def prepare_evaluation(client, monkeypatch, outputs):
    response = client.post(
        "/api/conversations/import",
        json={
            "records": [
                {
                    "conversation_id": "validation-test",
                    "transcript": [
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
        "missing", "duplicate", "unknown", "scale", "range", "critical", "forbidden_na",
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


@pytest.mark.parametrize("case", ["empty_criteria", "missing_score", "string_score"])
def test_corrected_retry_is_scored_with_na_and_critical_flag(client, monkeypatch, case):
    invalid = valid_output()
    if case == "empty_criteria":
        invalid["criteria"] = []
    elif case == "missing_score":
        invalid["criteria"][0].pop("score")
    else:
        invalid["criteria"][0]["score"] = "1"
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
