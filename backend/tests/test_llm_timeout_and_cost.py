"""Controlled offline tests for B3: SDK retry/timeout, evaluation deadline, and token/cost."""

import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import db as core_db
from app.core.config import get_settings
from app.core.errors import ExternalServiceError
from app.features.checklists.defaults import default_checklist_config
from app.features.checklists.service import ensure_default
from app.features.conversations.schemas import ConversationRecord
from app.features.conversations.service import upsert_records
from app.features.evaluations import service
from app.features.evaluations.llm import (
    GeminiProvider,
    LLMResult,
    _extract_usage_tokens,
    generate_with_retry,
)
from app.main import create_app


def _valid_payload() -> str:
    return json.dumps(
        {
            "criteria": [
                {
                    "criterion_id": c.id,
                    "applicable": True,
                    "score": 0 if c.id == "critical" else c.scale_max,
                    "critical_violation": False,
                    "explanation": "Confirmed by transcript.",
                    "evidence": [{"message_index": 0, "quote": "Hello, my name is Alex."}],
                }
                for c in default_checklist_config().criteria
            ],
            "summary": "Valid evaluation summary.",
        }
    )


def test_gemini_provider_disables_internal_sdk_retries_and_times_out_once():
    provider = GeminiProvider(
        api_key="offline-test-key",
        model="gemini-3.6-flash",
        thinking_level="medium",
        timeout=0.2,
    )
    retry_cfg = provider._client.interactions.sdk_configuration.retry_config
    assert retry_cfg.max_retries == 0

    transport_calls = 0

    def fake_send(request: httpx.Request, **kwargs) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        raise httpx.ReadTimeout("Simulated transport read timeout", request=request)

    provider._client.interactions.sdk_configuration.client.send = fake_send  # type: ignore[method-assign]

    with pytest.raises(ExternalServiceError, match="cancellation/billing is not guaranteed"):
        generate_with_retry(
            provider,
            system_instruction="sys",
            input_text="in",
            schema={"type": "object"},
            deadline=time.monotonic() + 1.0,
        )

    assert transport_calls == 1


def test_usage_tokens_never_double_count_thinking():
    # Обычный ответ Interactions API: total_output_tokens содержит только видимый ответ (601),
    # а total_thought_tokens отдельно (1125); total_tokens = 2199 + 601 + 1125 = 3925.
    separate = SimpleNamespace(
        total_input_tokens=2199,
        total_output_tokens=601,
        total_thought_tokens=1125,
        total_tokens=3925,
    )
    inp1, out1, th1 = _extract_usage_tokens(separate)
    assert (inp1, out1, th1) == (2199, 601, 1125)

    # Случай, когда total_output_tokens уже включает thought_tokens (601 + 1125 = 1726)
    inclusive = SimpleNamespace(
        total_input_tokens=2199,
        total_output_tokens=1726,
        total_thought_tokens=1125,
        total_tokens=3925,
    )
    inp2, out2, th2 = _extract_usage_tokens(inclusive)
    assert (inp2, out2, th2) == (2199, 601, 1125)

    res1 = LLMResult(
        text="{}",
        model="gemini-3.6-flash",
        input_tokens=inp1,
        output_tokens=out1,
        thought_tokens=th1,
    )
    res2 = LLMResult(
        text="{}",
        model="gemini-3.6-flash",
        input_tokens=inp2,
        output_tokens=out2,
        thought_tokens=th2,
    )
    assert res1.cost_usd() == pytest.approx(0.0162435)
    assert res2.cost_usd() == pytest.approx(0.0162435)


@pytest.fixture
def env(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_batch_concurrency", 1)
    monkeypatch.setattr(settings, "llm_timeout_seconds", 0.25)
    monkeypatch.setattr(settings, "llm_max_retries", 3)
    monkeypatch.setattr(service, "_evaluation_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(service, "_jobs", {})

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'b3.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    core_db.import_all_models()
    core_db.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service, "SessionLocal", factory)

    with factory() as db:
        upsert_records(
            db,
            "TEST",
            [
                ConversationRecord(
                    conversation_id=cid,
                    transcript=[{"speaker": "operator", "text": "Hello, my name is Alex."}],
                )
                for cid in ["hang-1", "ok-2", "fail-cost"]
            ],
        )
        checklist_id = ensure_default(db).id

    app = create_app()

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[core_db.get_db] = database
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, sessions=factory, checklist_id=checklist_id)
    engine.dispose()


def test_hanging_provider_is_bounded_and_releases_slot_for_next_dialogue(env, monkeypatch):
    release_hung_thread = threading.Event()
    calls: list[str] = []

    class HangingThenWorkingProvider:
        name = model = "gemini-3.6-flash"

        def generate(self, *, system_instruction: str, input_text: str, schema: dict) -> LLMResult:
            calls.append(input_text)
            if "Conversation ID: hang-1\n" in input_text:
                release_hung_thread.wait(timeout=3.0)
                return LLMResult(text=_valid_payload(), model=self.model)
            return LLMResult(
                text=_valid_payload(),
                model=self.model,
                input_tokens=1000,
                output_tokens=400,
                thought_tokens=600,
                latency_ms=45,
            )

    monkeypatch.setattr(service, "get_provider", lambda: HangingThenWorkingProvider())

    try:
        started = time.perf_counter()
        r1 = env.client.post("/api/evaluations", json={"conversation_id": "hang-1"})
        elapsed = time.perf_counter() - started
        assert r1.status_code == 502
        assert elapsed < 1.0
        assert len(calls) == 1  # Никаких повторных вызовов после истечения дедлайна

        # Следующий диалог сразу же получает освобождённый слот и успешно оценивается
        r2 = env.client.post("/api/evaluations", json={"conversation_id": "ok-2"})
        assert r2.status_code == 201
        ev2 = r2.json()
        assert ev2["status"] == "done"
        assert ev2["cost_usd"] == pytest.approx((1000 * 1.5 + 1000 * 7.5) / 1_000_000)

        # Проверяем, что неуспешная оценка hang-1 сохранена в БД со статусом failed и причиной
        evals = env.client.get("/api/evaluations?conversation_id=hang-1").json()
        assert len(evals) == 1
        saved_failed = env.client.get(f"/api/evaluations/{evals[0]['id']}").json()
        assert saved_failed["status"] == "failed"
        assert "cancellation/billing is not guaranteed" in saved_failed["error"]
        assert saved_failed["latency_ms"] >= 200
    finally:
        release_hung_thread.set()


def test_spent_tokens_are_preserved_across_retries_and_failed_evaluations(env, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_timeout_seconds", 5.0)
    attempt_num = 0

    class PartialAndInvalidProvider:
        name = model = "gemini-3.6-flash"

        def generate(self, *, system_instruction: str, input_text: str, schema: dict) -> LLMResult:
            nonlocal attempt_num
            attempt_num += 1
            if attempt_num == 1:
                # Сбой после частичного расхода токенов (например, обрыв потока/continuation)
                err = RuntimeError("Temporary 503 after partial generation")
                err.status_code = 503  # type: ignore[attr-defined]
                err.usage = SimpleNamespace(  # type: ignore[attr-defined]
                    total_input_tokens=1000,
                    total_output_tokens=100,
                    total_thought_tokens=300,
                    total_tokens=1400,
                )
                raise err
            # Вторая и третья попытки возвращают невалидный JSON, но тоже тратят токены
            return LLMResult(
                text='{"criteria": [], "summary": "broken"}',
                model=self.model,
                input_tokens=2000,
                output_tokens=200,
                thought_tokens=400,
                latency_ms=120,
            )

    monkeypatch.setattr(service, "get_provider", lambda: PartialAndInvalidProvider())
    monkeypatch.setattr(time, "sleep", lambda _: None)

    batch_res = service.run_batch(["fail-cost"], env.checklist_id)
    assert batch_res.status == "failed"
    assert batch_res.failed == 1
    assert len(batch_res.evaluation_ids) == 1

    # Всего потрачено:
    # - Попытка 1 (503 с partial usage): 1000 in, 100 out, 300 thought
    # - Попытка 2 (1-й ответ с невалидным JSON): 2000 in, 200 out, 400 thought
    # - Попытка 3 (2-й ответ с невалидным JSON): 2000 in, 200 out, 400 thought
    # Итого: 5000 in, 500 out, 1100 thought
    expected_cost = (5000 * 1.50 + (500 + 1100) * 7.50) / 1_000_000
    assert batch_res.total_cost_usd == pytest.approx(expected_cost)

    saved = env.client.get(f"/api/evaluations/{batch_res.evaluation_ids[0]}").json()
    assert saved["status"] == "failed"
    assert saved["input_tokens"] == 5000
    assert saved["output_tokens"] == 500
    assert saved["thought_tokens"] == 1100
    assert saved["cost_usd"] == pytest.approx(expected_cost)
