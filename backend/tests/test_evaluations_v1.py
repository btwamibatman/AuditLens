import copy
import json

import httpx
import pytest

from app.features.evaluations.v1 import data, service
from app.features.evaluations.v1.provider import OpenAIProvider, ProviderSettings
from app.features.evaluations.v1.validation import InvalidEvaluation, calculate, validate


@pytest.fixture
def criteria():
    values = [True, None, True, 15, False, 7, True, True]
    return [
        {"criterion_id": rule["id"], "value": value, "rationale": "reason", "evidence_turns": [1]}
        for rule, value in zip(data.load_checklist()["criteria"], values, strict=True)
    ]


def test_score_and_na(criteria):
    checklist = data.load_checklist()
    validate({"criteria": criteria}, checklist, 1)
    assert calculate(criteria, checklist) == {"final_score": 71.18, "critical_flag": True}
    criteria[7]["value"] = False
    assert calculate(criteria, checklist) == {"final_score": 71.18, "critical_flag": False}
    criteria[1]["value"] = False
    assert calculate(criteria, checklist)["final_score"] == 60.5


@pytest.mark.parametrize(
    "kind", ["missing", "duplicate", "unknown", "bool", "number", "null", "evidence", "rationale"]
)
def test_validation(criteria, kind):
    items = copy.deepcopy(criteria)
    if kind == "missing":
        items.pop()
    if kind == "duplicate":
        items[0]["criterion_id"] = items[1]["criterion_id"]
    if kind == "unknown":
        items[0]["criterion_id"] = "other"
    if kind == "bool":
        items[0]["value"] = 1
    if kind == "number":
        items[3]["value"] = 3
    if kind == "null":
        items[0]["value"] = None
    if kind == "evidence":
        items[0]["evidence_turns"] = [0]
    if kind == "rationale":
        items[0]["rationale"] = " "
    with pytest.raises(InvalidEvaluation):
        validate({"criteria": items}, data.load_checklist(), 1)


def test_endpoint_success_and_unknown(client, monkeypatch, criteria):
    seen = []

    def post(url, **kwargs):
        seen.append(kwargs["json"])
        content = json.dumps({"criteria": criteria})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setenv("AI_API_KEY", "test")
    monkeypatch.setenv("AI_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("AI_MODEL", "test")
    response = client.post("/api/v1/evaluations", json={"conversation_id": "p1-ru-001"})
    assert response.status_code == 200
    assert response.json()["score"]["final_score"] == 71.18
    assert '"turn": 1' in seen[0]["messages"][1]["content"]
    response = client.post("/api/v1/evaluations", json={"conversation_id": "unknown"})
    assert response.status_code == 404
    assert response.json()["score"] is None


def test_provider_failure(monkeypatch):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        return httpx.Response(503)

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(service.time, "sleep", lambda _: None)
    provider = OpenAIProvider(
        ProviderSettings(ai_api_key="test", ai_base_url="https://example.com/v1", ai_model="test")
    )
    result, status = service.evaluate("p1-ru-001", provider)
    assert status == 502 and len(calls) == 3
    assert (
        result["conversation_id"] == "p1-ru-001"
        and result["criteria"] == []
        and result["score"] is None
    )
