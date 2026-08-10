from __future__ import annotations

import time

import pytest

from backend.store.backends.sqlite import SQLiteStore
from backend.workers.handlers import HANDLERS
from backend.workers.worker import DurableWorker, RetryableJobError


@pytest.fixture
def store(tmp_path):
    instance = SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))
    yield instance
    instance.close()


def _job(store: SQLiteStore, kind: str = "test", **kwargs):
    return store.create_job(
        store.SEED_USER_ID, kind, "art_001", payload={"value": 2}, **kwargs
    )


def test_worker_claims_and_completes_job(store):
    job = _job(store)
    worker = DurableWorker(
        store, {"test": lambda context, payload: {"answer": payload["value"] * 3}},
        worker_id="worker-test", lease_seconds=6,
    )
    assert worker.run_once()
    completed = store.get_job(store.SEED_USER_ID, job["job_id"])
    assert completed["status"] == "completed"
    assert completed["result"] == {"answer": 6}
    assert completed["attempts"][0]["status"] == "completed"


def test_completed_effect_is_not_repeated_on_retry(store):
    job = _job(store, max_attempts=2)
    calls = {"count": 0}

    def handler(context, _payload):
        def side_effect():
            calls["count"] += 1
            return {"remote_id": "remote-1"}

        result = context.run_effect("remote-write", side_effect)
        if context.job["attempt_count"] == 1:
            raise RetryableJobError("fail after remote write")
        return result

    worker = DurableWorker(
        store, {"test": handler}, worker_id="worker-test", lease_seconds=6,
    )
    assert worker.run_once()
    waiting = store.get_job(store.SEED_USER_ID, job["job_id"])
    assert waiting["status"] == "waiting"
    store._con.execute(
        "UPDATE jobs SET available_at=created_at WHERE job_id=?", (job["job_id"],)
    )
    store._con.commit()
    assert worker.run_once()
    completed = store.get_job(store.SEED_USER_ID, job["job_id"])
    assert completed["status"] == "completed"
    assert completed["result"] == {"remote_id": "remote-1"}
    assert calls["count"] == 1


def test_known_failed_effect_is_released_for_retry(store):
    job = _job(store, max_attempts=2)
    calls = {"count": 0}

    def handler(context, _payload):
        def provider_call():
            calls["count"] += 1
            if calls["count"] == 1:
                raise RetryableJobError("provider unavailable")
            return {"value": "generated"}

        return context.run_effect(
            "provider-call", provider_call, release_on_error=True
        )

    worker = DurableWorker(
        store, {"test": handler}, worker_id="worker-test", lease_seconds=6,
    )
    assert worker.run_once()
    store._con.execute(
        "UPDATE jobs SET available_at=created_at WHERE job_id=?", (job["job_id"],)
    )
    store._con.commit()
    assert worker.run_once()
    assert store.get_job(store.SEED_USER_ID, job["job_id"])["status"] == "completed"
    assert calls["count"] == 2


def test_handler_observes_running_cancellation(store):
    job = _job(store, max_attempts=1)

    def handler(context, _payload):
        context.store.request_job_cancellation(context.user_id, context.job_id)
        context.check_stopped()
        return {}

    worker = DurableWorker(
        store, {"test": handler}, worker_id="worker-test", lease_seconds=6,
    )
    worker.run_once()
    canceled = store.get_job(store.SEED_USER_ID, job["job_id"])
    assert canceled["status"] == "canceled"


def test_timeout_is_recorded_and_job_stops_at_attempt_limit(store):
    job = _job(store, max_attempts=1, timeout_seconds=1)

    def slow_handler(context, _payload):
        time.sleep(1.2)
        context.check_stopped()
        return {}

    worker = DurableWorker(
        store, {"test": slow_handler}, worker_id="worker-test", lease_seconds=3,
    )
    worker.run_once()
    timed_out = store.get_job(store.SEED_USER_ID, job["job_id"])
    assert timed_out["status"] == "failed"
    assert "exceeded its timeout" in timed_out["error"]


def test_generation_handler_persists_article_and_session(store, monkeypatch):
    article = store.create_article(store.SEED_USER_ID, "Draft")
    session = store.create_agent_session(
        store.SEED_USER_ID, provider="openai", article_id=article["id"]
    )
    store.add_agent_message(store.SEED_USER_ID, session["id"], "user", "Write it")
    job = store.create_job(
        store.SEED_USER_ID,
        "generate",
        article["id"],
        payload={
            "article_id": article["id"],
            "brief": "Write it",
            "skill": "tutorial",
            "provider": "codex",
            "word_count": 1000,
            "context_text": None,
            "destinations": [],
            "session_id": session["id"],
        },
        queue="agents",
    )
    monkeypatch.setattr(
        "backend.services.agent_service.runner.run_task",
        lambda **_kwargs: {
            "exit_code": 0,
            "stdout": "# Worker Article\n\nDurably generated body.",
            "stderr": "",
        },
    )
    worker = DurableWorker(
        store, HANDLERS, worker_id="worker-test", queues=("agents",), lease_seconds=6,
    )
    worker.run_once()

    completed = store.get_job(store.SEED_USER_ID, job["job_id"])
    persisted_session = store.get_agent_session(store.SEED_USER_ID, session["id"])
    assert completed["status"] == "completed"
    assert "Durably generated body" in store.get_article(
        store.SEED_USER_ID, article["id"]
    )["body"]
    assert persisted_session["status"] == "completed"
    assert persisted_session["outputs"][0]["reference"] == article["id"]
