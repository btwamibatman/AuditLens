"""Controlled concurrency checks; no real provider calls or application database."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core import db as core_db
from app.core.config import get_settings
from app.core.errors import ConflictError
from app.features.checklists.service import ensure_default
from app.features.conversations.schemas import ConversationRecord
from app.features.conversations.service import upsert_records
from app.features.evaluations import service
from app.features.evaluations.llm import LLMResult, MockProvider
from app.features.evaluations.models import Evaluation
from app.main import create_app


class ControlledProvider:
    name = model = "controlled-offline-test"

    def __init__(self):
        self.gate = threading.Event()
        self.condition = threading.Condition()
        self.active = self.peak = self.calls = 0
        self.fail_ids = set()

    def wait_for_active(self, count):
        with self.condition:
            assert self.condition.wait_for(lambda: self.active >= count, timeout=3)

    def generate(self, **kwargs):
        with self.condition:
            self.active += 1
            self.calls += 1
            self.peak = max(self.peak, self.active)
            self.condition.notify_all()
        try:
            assert self.gate.wait(5), "Test did not release the provider"
            if any(kwargs["input_text"].startswith(f"Conversation ID: {cid}\n")
                   for cid in self.fail_ids):
                return LLMResult(text="Invalid test response", model=self.model)
            return MockProvider().generate(**kwargs)
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()


def wait_for_job(client, job_id):
    deadline = time.monotonic() + 5
    while True:
        response = client.get(f"/api/evaluations/batch/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] != "running":
            return job
        assert time.monotonic() < deadline, job
        time.sleep(0.01)


@pytest.fixture
def capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_batch_concurrency", 2)
    monkeypatch.setattr(service, "_evaluation_slots", threading.BoundedSemaphore(2))
    monkeypatch.setattr(service, "_jobs", {})
    provider = ControlledProvider()
    monkeypatch.setattr(service, "get_provider", lambda: provider)
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    core_db.import_all_models()
    core_db.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service, "SessionLocal", factory)
    with factory() as db:
        upsert_records(db, "TEST", [
            ConversationRecord(conversation_id=cid, transcript=[{
                "speaker": "operator", "text": "Hello, my name is Alex.",
            }]) for cid in ["single", "extra", "a", "b", "c"]
        ])
        checklist_id = ensure_default(db).id
    app = create_app()

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[core_db.get_db] = database
    with TestClient(app) as client:
        try:
            yield SimpleNamespace(
                client=client, provider=provider, sessions=factory, checklist_id=checklist_id,
            )
        finally:
            provider.gate.set()
            for job_id in list(service._jobs):
                wait_for_job(client, job_id)
    engine.dispose()


def test_single_and_batch_share_capacity_without_blocking_other_requests(capacity):
    client, provider = capacity.client, capacity.provider
    with ThreadPoolExecutor(max_workers=3) as requests:
        single = requests.submit(
            client.post, "/api/evaluations", json={"conversation_id": "single"},
        )
        try:
            provider.wait_for_active(1)
            batch = client.post(
                "/api/evaluations/batch", json={"conversation_ids": ["a", "b", "c"]},
            )
            assert batch.status_code == 202
            provider.wait_for_active(2)
            busy = requests.submit(
                client.post, "/api/evaluations", json={"conversation_id": "extra"},
            ).result(timeout=2)
            assert busy.status_code == 429 and busy.json()["code"] == "evaluation_busy"
            health = requests.submit(client.get, "/api/health").result(timeout=2)
            progress = requests.submit(
                client.get, f"/api/evaluations/batch/{batch.json()['job_id']}",
            ).result(timeout=2)
            assert health.status_code == 200 and progress.json()["status"] == "running"
            assert not single.done() and provider.peak == 2
            with capacity.sessions() as db:
                assert list(db.scalars(select(Evaluation).where(
                    Evaluation.conversation_id == "extra",
                ))) == []
        finally:
            provider.gate.set()
        assert single.result(timeout=3).status_code == 201
    job = wait_for_job(client, batch.json()["job_id"])
    assert job["done"] == 3 and job["failed"] == 0
    assert provider.peak == 2 and provider.calls == 4
    assert client.post("/api/evaluations", json={"conversation_id": "extra"}).status_code == 201


def test_simultaneous_batch_starts_accept_only_one(capacity):
    client, provider = capacity.client, capacity.provider
    barrier = threading.Barrier(4)

    def submit():
        barrier.wait(timeout=3)
        return client.post("/api/evaluations/batch", json={"conversation_ids": ["a", "b"]})

    try:
        with ThreadPoolExecutor(max_workers=4) as requests:
            responses = list(requests.map(lambda _: submit(), range(4)))
        assert sorted(r.status_code for r in responses) == [202, 409, 409, 409]
        assert all(r.json()["code"] == "batch_already_running"
                   for r in responses if r.status_code == 409)
        assert len(service._jobs) == 1
        provider.wait_for_active(2)
    finally:
        provider.gate.set()
    job = wait_for_job(client, next(r.json()["job_id"] for r in responses if r.status_code == 202))
    assert job["done"] == 2 and provider.peak == 2
    next_batch = client.post("/api/evaluations/batch", json={"conversation_ids": ["c"]})
    assert next_batch.status_code == 202
    assert wait_for_job(client, next_batch.json()["job_id"])["done"] == 1


@pytest.mark.parametrize("direct_first", [True, False])
def test_direct_and_http_batch_cannot_overlap(capacity, direct_first):
    client, provider = capacity.client, capacity.provider
    with ThreadPoolExecutor(max_workers=1) as requests:
        if direct_first:
            direct = requests.submit(service.run_batch, ["a", "b"], capacity.checklist_id)
            try:
                provider.wait_for_active(2)
                response = client.post("/api/evaluations/batch", json={"conversation_ids": ["c"]})
                assert response.status_code == 409
            finally:
                provider.gate.set()
            assert direct.result(timeout=3).done == 2
        else:
            response = client.post("/api/evaluations/batch", json={"conversation_ids": ["a", "b"]})
            try:
                provider.wait_for_active(2)
                with pytest.raises(ConflictError):
                    service.run_batch(["c"], capacity.checklist_id)
            finally:
                provider.gate.set()
            assert wait_for_job(client, response.json()["job_id"])["done"] == 2


def test_failed_evaluations_release_capacity_and_batch_admission(capacity):
    client, provider = capacity.client, capacity.provider
    provider.gate.set()
    provider.fail_ids = {"a", "b", "single"}
    assert client.post("/api/evaluations", json={"conversation_id": "single"}).status_code == 502
    response = client.post("/api/evaluations/batch", json={"conversation_ids": ["a", "b"]})
    job = wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "failed" and job["failed"] == 2
    provider.fail_ids.clear()
    assert client.post("/api/evaluations", json={"conversation_id": "extra"}).status_code == 201
    next_batch = client.post("/api/evaluations/batch", json={"conversation_ids": ["c"]})
    assert next_batch.status_code == 202
    assert wait_for_job(client, next_batch.json()["job_id"])["done"] == 1


def test_lookup_and_unexpected_errors_do_not_leak_evaluation_slots(capacity, monkeypatch):
    client, provider = capacity.client, capacity.provider
    provider.gate.set()
    for _ in range(3):
        response = client.post("/api/evaluations", json={"conversation_id": "unknown"})
        assert response.status_code == 404

    def fail(*args):
        raise RuntimeError("Simulated evaluation failure")

    with monkeypatch.context() as patch:
        patch.setattr(service, "_evaluate", fail)
        for _ in range(3):
            with pytest.raises(RuntimeError, match="Simulated"):
                client.post("/api/evaluations", json={"conversation_id": "single"})
    assert provider.calls == 0
    assert client.post("/api/evaluations", json={"conversation_id": "single"}).status_code == 201


def test_thread_start_failure_does_not_leave_a_job_or_block_next_batch(capacity, monkeypatch):
    def fail(*args):
        raise RuntimeError("Simulated thread start failure")

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", fail)
        with pytest.raises(RuntimeError, match="Simulated"):
            service.start_batch_job(["a"], capacity.checklist_id)
    assert service._jobs == {} and capacity.provider.calls == 0
    capacity.provider.gate.set()
    response = capacity.client.post("/api/evaluations/batch", json={"conversation_ids": ["a"]})
    assert response.status_code == 202
    assert wait_for_job(capacity.client, response.json()["job_id"])["done"] == 1


def test_background_failure_releases_batch_admission(capacity, monkeypatch):
    def fail(*args):
        raise RuntimeError("Simulated background failure")

    with monkeypatch.context() as patch:
        patch.setattr(service, "_run_batch", fail)
        response = capacity.client.post("/api/evaluations/batch", json={"conversation_ids": ["a"]})
        job = wait_for_job(capacity.client, response.json()["job_id"])
        assert job["status"] == "failed"
        assert job["errors"]["_batch"] == "Simulated background failure"
    capacity.provider.gate.set()
    response = capacity.client.post("/api/evaluations/batch", json={"conversation_ids": ["b"]})
    assert response.status_code == 202
    assert wait_for_job(capacity.client, response.json()["job_id"])["done"] == 1


def test_direct_batch_callback_failure_releases_batch_admission(capacity):
    def fail(*args):
        raise RuntimeError("Simulated progress callback failure")

    capacity.provider.gate.set()
    with pytest.raises(RuntimeError, match="Simulated"):
        service.run_batch(["a"], capacity.checklist_id, on_progress=fail)
    assert service.run_batch(["b"], capacity.checklist_id).done == 1


def test_batch_waits_for_busy_single_requests_without_failing_its_records(capacity):
    client, provider = capacity.client, capacity.provider
    with ThreadPoolExecutor(max_workers=3) as requests:
        singles = [requests.submit(
            client.post, "/api/evaluations", json={"conversation_id": cid},
        ) for cid in ["single", "extra"]]
        try:
            provider.wait_for_active(2)
            batch = requests.submit(
                client.post, "/api/evaluations/batch", json={"conversation_ids": ["a", "b"]},
            ).result(timeout=2)
            assert batch.status_code == 202
            health = requests.submit(client.get, "/api/health").result(timeout=2)
            assert health.status_code == 200
            progress = client.get(f"/api/evaluations/batch/{batch.json()['job_id']}").json()
            assert progress["done"] == 0 and progress["failed"] == 0 and provider.calls == 2
        finally:
            provider.gate.set()
        assert all(single.result(timeout=3).status_code == 201 for single in singles)
    job = wait_for_job(client, batch.json()["job_id"])
    assert job["done"] == 2 and job["failed"] == 0 and provider.peak == 2
