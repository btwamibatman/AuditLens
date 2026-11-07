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
    ["missing", "duplicate", "unknown", "scale", "range", "critical", "forbidden_na"],
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
    else:
        criteria[0]["applicable"] = False
        criteria[0]["na_reason"] = "Not applicable"

    calls = prepare_evaluation(client, monkeypatch, [payload])
    response = client.post("/api/evaluations", json={"conversation_id": "validation-test"})
    assert response.status_code == 502
    assert len(calls) == 2
    evaluations = client.get("/api/evaluations").json()
    assert len(evaluations) == 1 and evaluations[0]["status"] == "failed"
    saved = client.get(f"/api/evaluations/{evaluations[0]['id']}").json()
    assert saved["ai_result"] is None and saved["final_result"] is None
    assert saved["total_score"] is None and saved["error"]


def test_corrected_retry_is_scored_with_na_and_critical_flag(client, monkeypatch):
    invalid = valid_output()
    invalid["criteria"] = []
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
