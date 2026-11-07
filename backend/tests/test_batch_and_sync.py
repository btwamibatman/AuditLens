"""Tests for B6: dataset sync/import deduplication, pinned checklist, only_missing, recovery."""

import copy
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core import db as core_db
from app.core.config import get_settings
from app.features.checklists.defaults import default_checklist_config
from app.features.checklists.service import ensure_default
from app.features.conversations.models import Conversation
from app.features.evaluations import export, service
from app.features.evaluations.llm import LLMResult
from app.features.evaluations.models import Evaluation
from app.features.evaluations.schemas import BatchRequest
from app.main import create_app


def _valid_llm_json(quote: str = "Добрый день! Меня зовут Алия.") -> str:
    return json.dumps(
        {
            "criteria": [
                {
                    "criterion_id": c.id,
                    "applicable": True,
                    "score": 0 if c.id == "critical" else c.scale_max,
                    "critical_violation": False,
                    "explanation": "Подтверждено по транскрипту.",
                    "evidence": [{"message_index": 1, "quote": quote}],
                }
                for c in default_checklist_config().criteria
            ],
            "summary": "Оператор корректно провёл диалог.",
        },
        ensure_ascii=False,
    )


def _sample_record(cid: str, channel: str = "agent chat", lang: str = "RU") -> dict:
    return {
        "conversation_id": cid,
        "channel": channel,
        "language": lang,
        "audio_url": "https://example.com/call.mp3" if "call" in channel else None,
        "transcript": [
            {"timestamp": "00:01", "speaker": "bot", "text": "Здравствуйте! Бот поддержки."},
            {"timestamp": "00:05", "speaker": "operator", "text": "Добрый день! Меня зовут Алия."},
            {"timestamp": "00:10", "speaker": "client", "text": "Спасибо!"},
            {"timestamp": "00:12", "speaker": "system", "text": "client_verified=true"},
        ],
    }


def _wait_batch(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 5.0
    while True:
        res = client.get(f"/api/evaluations/batch/{job_id}")
        assert res.status_code == 200
        body = res.json()
        if body["status"] != "running":
            return body
        assert time.monotonic() < deadline, f"Batch did not finish in time: {body}"
        time.sleep(0.01)


@pytest.fixture
def b6_env(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_batch_concurrency", 3)
    monkeypatch.setattr(settings, "llm_timeout_seconds", 2.0)
    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(settings, "dataset_api_url", "https://dataset.example.test/invoke")
    monkeypatch.setattr(service, "_evaluation_slots", threading.BoundedSemaphore(3))
    monkeypatch.setattr(service, "_jobs", {})

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'b6.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    core_db.import_all_models()
    core_db.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service, "SessionLocal", factory)

    with factory() as db:
        checklist_id = ensure_default(db).id

    app = create_app()

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[core_db.get_db] = database
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, sessions=factory, checklist_id=checklist_id)
    engine.dispose()


def test_sync_dataset_and_duplicate_id_detection_without_partial_save(b6_env, monkeypatch):
    client = b6_env.client
    records = [
        _sample_record("sync-chat-1", "agent chat", "ru"),
        _sample_record("sync-call-2", "voice call", "kz"),
    ]
    payload = {
        "error": None,
        "isSuccess": True,
        "data": {
            "dataset_group_id": "DEV",
            "total_records": 2,
            "records": records,
        },
    }

    def fake_get(url, *, params=None, timeout=None, follow_redirects=True):
        req = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=payload, request=req)

    monkeypatch.setattr(httpx, "get", fake_get)

    first = client.post("/api/conversations/sync?group_id=DEV")
    assert first.status_code == 200
    assert first.json() == {"dataset_group": "DEV", "created": 2, "updated": 0, "total": 2}

    # Повторный sync того же набора не создаёт дубликатов и сохраняет все исходные поля
    second = client.post("/api/conversations/sync?group_id=DEV")
    assert second.status_code == 200
    assert second.json() == {"dataset_group": "DEV", "created": 0, "updated": 2, "total": 2}

    call_conv = client.get("/api/conversations/sync-call-2").json()
    assert call_conv["channel"] == "voice call"
    assert call_conv["language"] == "KZ"
    assert call_conv["audio_url"] == "https://example.com/call.mp3"
    assert [t["speaker"] for t in call_conv["transcript"]] == [
        "bot",
        "operator",
        "client",
        "system",
    ]
    assert [t["timestamp"] for t in call_conv["transcript"]] == [
        "00:01",
        "00:05",
        "00:10",
        "00:12",
    ]

    # Дублирующийся conversation_id внутри одного набора отклоняется ДО частичного сохранения
    dup_import = client.post(
        "/api/conversations/import",
        json={
            "dataset_group": "DEV",
            "records": [
                _sample_record("new-unique-id"),
                _sample_record("dup-id"),
                _sample_record("dup-id"),
            ],
        },
    )
    assert dup_import.status_code == 400
    assert "Duplicate conversation_id" in dup_import.json()["detail"]

    # Убеждаемся, что new-unique-id не сохранился частично
    assert client.get("/api/conversations/new-unique-id").status_code == 404
    assert len(client.get("/api/conversations?dataset_group=DEV").json()) == 2

    # Ошибки внешнего API (isSuccess=false, group mismatch, HTTP) возвращают 502 и не портят БД
    payload["isSuccess"] = False
    payload["error"] = "Upstream failure"
    err_res = client.post("/api/conversations/sync?group_id=DEV")
    assert err_res.status_code == 502
    assert len(client.get("/api/conversations?dataset_group=DEV").json()) == 2


def test_batch_pins_checklist_version_when_live_checklist_is_edited_mid_run(b6_env, monkeypatch):
    client = b6_env.client
    monkeypatch.setattr(get_settings(), "llm_batch_concurrency", 1)
    monkeypatch.setattr(service, "_evaluation_slots", threading.BoundedSemaphore(1))

    client.post(
        "/api/conversations/import",
        json={
            "dataset_group": "PIN",
            "records": [_sample_record(cid) for cid in ["pin-1", "pin-2", "pin-3"]],
        },
    )

    first_started = threading.Event()
    allow_finish = threading.Event()

    class GateProvider:
        name = model = "gemini-3.6-flash"

        def generate(self, *, system_instruction: str, input_text: str, schema: dict) -> LLMResult:
            if "Conversation ID: pin-1\n" in input_text:
                first_started.set()
                assert allow_finish.wait(timeout=3.0)
            return LLMResult(text=_valid_llm_json(), model=self.model)

    monkeypatch.setattr(service, "get_provider", lambda: GateProvider())

    try:
        batch = client.post(
            "/api/evaluations/batch",
            json={"dataset_group": "PIN"},
        )
        assert batch.status_code == 202
        job_id = batch.json()["job_id"]
        assert first_started.wait(timeout=2.0)

        # Пока идёт оценка pin-1, в другом окне меняют активный чек-лист (version 1 -> 2)
        active = client.get("/api/checklists/active").json()
        edited_cfg = copy.deepcopy(active["config"])
        edited_cfg["criteria"][0]["name"] = "Изменённое во время batch имя"
        updated = client.put(
            f"/api/checklists/{active['id']}",
            json={"config": edited_cfg},
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2
    finally:
        allow_finish.set()

    job = _wait_batch(client, job_id)
    assert job["status"] == "done" and job["done"] == 3 and job["failed"] == 0

    with b6_env.sessions() as db:
        evals = [db.get(Evaluation, eid) for eid in job["evaluation_ids"]]
        assert all(ev is not None for ev in evals)
        assert {ev.checklist_id for ev in evals} == {b6_env.checklist_id}
        assert {ev.checklist_version for ev in evals} == {1}
        assert len({json.dumps(ev.checklist_snapshot, sort_keys=True) for ev in evals}) == 1
        assert all(
            ev.final_result["criteria"][0]["name"] == "Установление контакта" for ev in evals
        )


def test_batch_sqlite_parallel_writes_partial_failure_only_missing_and_restart_recovery(
    b6_env, monkeypatch
):
    client = b6_env.client
    records = [_sample_record(f"prod-{i:02d}") for i in range(1, 11)]
    dataset_doc = {
        "error": None,
        "isSuccess": True,
        "data": {
            "dataset_group_id": "PROD",
            "total_records": 10,
            "records": records,
        },
    }
    imp = client.post(
        "/api/conversations/import",
        json={"dataset_group": "PROD", "records": records},
    )
    assert imp.status_code == 200 and imp.json()["total"] == 10

    fail_ids = {"prod-03", "prod-07"}
    calls: list[str] = []

    class SelectiveProvider:
        name = model = "gemini-3.6-flash"

        def generate(self, *, system_instruction: str, input_text: str, schema: dict) -> LLMResult:
            for r in records:
                cid = r["conversation_id"]
                if f"Conversation ID: {cid}\n" in input_text:
                    calls.append(cid)
                    if cid in fail_ids:
                        return LLMResult(
                            text="broken json",
                            model=self.model,
                            input_tokens=500,
                            output_tokens=50,
                            thought_tokens=100,
                        )
                    return LLMResult(
                        text=_valid_llm_json(),
                        model=self.model,
                        input_tokens=1000,
                        output_tokens=200,
                        thought_tokens=300,
                    )
            raise AssertionError("Unknown conversation")

    monkeypatch.setattr(service, "get_provider", lambda: SelectiveProvider())

    # 1. Запускаем параллельный batch по всем 10 диалогам (8 ok, 2 failed)
    batch1 = client.post("/api/evaluations/batch", json={"dataset_group": "PROD"})
    assert batch1.status_code == 202
    job1_id = batch1.json()["job_id"]
    job1 = _wait_batch(client, job1_id)
    assert job1["status"] == "done"
    assert job1["done"] == 8 and job1["failed"] == 2
    assert len(job1["evaluation_ids"]) == 10
    assert set(job1["errors"].keys()) == {"prod-03", "prod-07"}

    # Проверяем, что официальный экспорт PROD принимает 8 ok + 2 error из этого прогона
    with b6_env.sessions() as db:
        evals1 = list(
            db.scalars(select(Evaluation).where(Evaluation.id.in_(job1["evaluation_ids"])))
        )
        convs = list(db.scalars(select(Conversation).where(Conversation.dataset_group == "PROD")))
        exported1 = export.build_export(
            dataset_doc,
            evals1,
            convs,
            kind="prod",
            group="PROD",
            checklist_id=b6_env.checklist_id,
            checklist_version=1,
            source="ai",
            team="AuditLens",
            model_mode="external_api",
        )
    assert len(exported1["results"]) == 10
    assert sum(r["status"] == "ok" for r in exported1["results"]) == 8
    assert sum(r["status"] == "error" for r in exported1["results"]) == 2

    # 2. Имитируем перезапуск сервера (очистка in-memory _jobs)
    service._jobs.clear()
    lost = client.get(f"/api/evaluations/batch/{job1_id}")
    assert lost.status_code == 404
    assert "GET /api/evaluations" in lost.json()["detail"]

    # Сохранённые оценки остаются доступны через API и фильтр по группе/версии
    persisted = client.get(
        f"/api/evaluations?dataset_group=PROD&checklist_id={b6_env.checklist_id}&checklist_version=1"
    )
    assert persisted.status_code == 200
    assert len(persisted.json()) == 10

    # 3. Повторный запуск с only_missing=True дооценивает только 2 упавших диалога
    fail_ids.clear()
    calls.clear()
    batch2 = client.post(
        "/api/evaluations/batch",
        json={
            "dataset_group": "PROD",
            "checklist_id": b6_env.checklist_id,
            "only_missing": True,
        },
    )
    assert batch2.status_code == 202
    job2 = _wait_batch(client, batch2.json()["job_id"])
    assert job2["total"] == 2 and job2["done"] == 2 and job2["failed"] == 0
    assert sorted(calls) == ["prod-03", "prod-07"]

    # Восстанавливаем полный список 10 ID оценок из БД для версии 1 и проверяем экспорт
    with b6_env.sessions() as db:
        recovered_ids = service.select_run_evaluation_ids(
            db,
            dataset_group="PROD",
            checklist_id=b6_env.checklist_id,
            checklist_version=1,
        )
        assert len(recovered_ids) == 10
        evals_recovered = list(
            db.scalars(select(Evaluation).where(Evaluation.id.in_(recovered_ids)))
        )
        exported2 = export.build_export(
            dataset_doc,
            evals_recovered,
            convs,
            kind="prod",
            group="PROD",
            checklist_id=b6_env.checklist_id,
            checklist_version=1,
            source="ai",
            team="AuditLens",
            model_mode="external_api",
        )
    assert sum(r["status"] == "ok" for r in exported2["results"]) == 10

    # 4. Если версия чек-листа увеличилась (v2), only_missing не выдаёт оценки v1 за актуальные
    active = client.get("/api/checklists/active").json()
    cfg_v2 = copy.deepcopy(active["config"])
    cfg_v2["evaluator_notes"] = "Обновлённое примечание v2"
    upd = client.put(f"/api/checklists/{b6_env.checklist_id}", json={"config": cfg_v2})
    assert upd.status_code == 200 and upd.json()["version"] == 2

    with b6_env.sessions() as db:
        targets_v2, _ = service.resolve_batch_targets(
            db,
            BatchRequest(
                dataset_group="PROD",
                checklist_id=b6_env.checklist_id,
                only_missing=True,
            ),
        )
    assert len(targets_v2) == 10
