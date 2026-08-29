from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import backend.store.job_queue as job_queue
from backend.store.backends.sqlite import SQLiteStore
from backend.store.job_queue import UncertainSideEffect


@pytest.fixture
def store(tmp_path):
    instance = SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))
    yield instance
    instance.close()


def _enqueue(store: SQLiteStore, **overrides) -> dict:
    values = {
        "user_id": store.SEED_USER_ID,
        "job_type": "generate",
        "article_id": "art_001",
        "payload": {"brief": "durable work"},
    }
    values.update(overrides)
    return store.create_job(**values)


def test_queued_job_survives_database_restart(tmp_path):
    database = tmp_path / "bloghub.db"
    blobs = tmp_path / "blobs"
    first = SQLiteStore(str(database), str(blobs))
    job = _enqueue(first, idempotency_key="generate-art-001-v1")
    first.close()

    reopened = SQLiteStore(str(database), str(blobs))
    try:
        restored = reopened.get_job(reopened.SEED_USER_ID, job["job_id"])
        assert restored["status"] == "queued"
        assert restored["payload"] == {"brief": "durable work"}
        assert restored["attempt_count"] == 0
    finally:
        reopened.close()


def test_claim_is_atomic_across_independent_workers(tmp_path):
    database = tmp_path / "bloghub.db"
    blobs = tmp_path / "blobs"
    first = SQLiteStore(str(database), str(blobs))
    second = SQLiteStore(str(database), str(blobs))
    try:
        queued = _enqueue(first)
        claimed = first.claim_job("worker-a")
        assert claimed["job_id"] == queued["job_id"]
        assert claimed["attempt_count"] == 1
        assert second.claim_job("worker-b") is None
        assert first.get_job(first.SEED_USER_ID, queued["job_id"])["claimed_by"] == "worker-a"
    finally:
        first.close()
        second.close()


def test_idempotent_enqueue_returns_original_job(store):
    first = _enqueue(store, idempotency_key="same-request")
    second = _enqueue(
        store, idempotency_key="same-request", payload={"brief": "must be ignored"}
    )
    assert second["job_id"] == first["job_id"]
    assert second["payload"] == {"brief": "durable work"}
    assert store.queue_metrics()["total_jobs"] == 1


def test_idempotency_keys_are_scoped_by_job_type(store):
    generated = _enqueue(store, idempotency_key="request-1")
    pushed = _enqueue(
        store, job_type="push", idempotency_key="request-1",
        payload={"platforms": ["devto"]},
    )
    assert pushed["job_id"] != generated["job_id"]
    assert store.find_job_by_idempotency_key(
        store.SEED_USER_ID, "push", "request-1"
    )["job_id"] == pushed["job_id"]


def test_list_jobs_filters_article_and_active_lifecycle(store):
    active = _enqueue(store, article_id="art_001")
    terminal = _enqueue(store, article_id="art_001")
    other = _enqueue(store, article_id="art_002")
    store.request_job_cancellation(store.SEED_USER_ID, terminal["job_id"])

    assert [job["job_id"] for job in store.list_jobs(
        store.SEED_USER_ID, article_id="art_001", active=True
    )] == [active["job_id"]]
    assert [job["job_id"] for job in store.list_jobs(
        store.SEED_USER_ID, article_id="art_001", active=False
    )] == [terminal["job_id"]]
    assert other["job_id"] not in {
        job["job_id"] for job in store.list_jobs(
            store.SEED_USER_ID, article_id="art_001"
        )
    }


def test_retry_idempotency_survives_terminal_state(store):
    job = _enqueue(store)
    store.request_job_cancellation(store.SEED_USER_ID, job["job_id"])
    first = store.retry_job(
        store.SEED_USER_ID, job["job_id"], idempotency_key="retry-once"
    )
    store.request_job_cancellation(store.SEED_USER_ID, job["job_id"])
    repeated = store.retry_job(
        store.SEED_USER_ID, job["job_id"], idempotency_key="retry-once"
    )

    assert first["status"] == "queued"
    assert repeated["status"] == "canceled"


def test_queued_and_running_jobs_can_be_canceled(store):
    queued = _enqueue(store)
    canceled = store.request_job_cancellation(store.SEED_USER_ID, queued["job_id"])
    assert canceled["status"] == "canceled"
    assert store.claim_job("worker") is None

    running = _enqueue(store)
    store.claim_job("worker")
    requested = store.request_job_cancellation(store.SEED_USER_ID, running["job_id"])
    assert requested["status"] == "running"
    assert requested["cancel_requested_at"] is not None
    assert store.is_job_cancel_requested(running["job_id"], "worker")
    assert store.fail_job(running["job_id"], "worker", "Canceled", retryable=True) == "canceled"


def test_retry_uses_backoff_and_stops_at_max_attempts(store):
    job = _enqueue(store, max_attempts=2)
    store.claim_job("worker")
    assert store.fail_job(
        job["job_id"], "worker", "temporary", backoff_base_seconds=0
    ) == "waiting"
    retry = store.claim_job("worker")
    assert retry["attempt_count"] == 2
    assert store.fail_job(
        job["job_id"], "worker", "still broken", backoff_base_seconds=0
    ) == "failed"
    final = store.get_job(store.SEED_USER_ID, job["job_id"])
    assert final["status"] == "failed"
    assert final["error"] == "still broken"
    assert [attempt["status"] for attempt in final["attempts"]] == ["waiting", "failed"]

    retried = store.retry_job(store.SEED_USER_ID, job["job_id"])
    assert retried["status"] == "queued"
    assert retried["max_attempts"] == 3
    assert store.claim_job("operator-retry")["attempt_count"] == 3


def test_heartbeat_checkpoint_and_queue_metrics(store):
    job = _enqueue(store, queue="agents", priority=10)
    claimed = store.claim_job("worker", queues=("agents",), lease_seconds=10)
    old_lease = claimed["lease_expires_at"]
    assert store.heartbeat_job(job["job_id"], "worker", lease_seconds=60)
    assert store.checkpoint_job(job["job_id"], "worker", {"step": 3}) == {"step": 3}
    refreshed = store.get_job(store.SEED_USER_ID, job["job_id"])
    assert refreshed["lease_expires_at"] > old_lease
    assert refreshed["checkpoint"] == {"step": 3}
    metrics = store.queue_metrics()
    assert metrics["queues"]["agents"]["running"] == 1
    assert metrics["average_attempts"] == 1


def test_expired_worker_lease_recovers_job_and_marks_effect_uncertain(store):
    job = _enqueue(store, max_attempts=3)
    store.claim_job("dead-worker")
    _, acquired = store.begin_job_effect(job["job_id"], "dead-worker", "publish:devto")
    assert acquired
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    store._con.execute(
        "UPDATE jobs SET lease_expires_at=? WHERE job_id=?", (past, job["job_id"])
    )
    store._con.commit()

    recovery = store.recover_orphaned_jobs()
    assert recovery["recovered"] == 1
    recovered = store.get_job(store.SEED_USER_ID, job["job_id"])
    assert recovered["status"] == "waiting"
    assert recovered["attempts"][0]["status"] == "orphaned"
    store.claim_job("new-worker")
    with pytest.raises(UncertainSideEffect):
        store.begin_job_effect(job["job_id"], "new-worker", "publish:devto")


def test_completed_effect_is_reused_without_repeating_side_effect(store):
    job = _enqueue(store)
    store.claim_job("worker")
    cached, acquired = store.begin_job_effect(job["job_id"], "worker", "publish:hashnode")
    assert acquired and cached is None
    result = {"draft_id": "draft-123", "status": "draft"}
    store.complete_job_effect(job["job_id"], "worker", "publish:hashnode", result)

    cached, acquired = store.begin_job_effect(job["job_id"], "worker", "publish:hashnode")
    assert acquired is False
    assert cached == result


def test_parked_job_requires_explicit_retry(store):
    job = _enqueue(store)
    store.claim_job("worker")
    store.defer_job(job["job_id"], "worker", "Remote result is uncertain")

    assert store.claim_job("other-worker") is None
    store.retry_job(store.SEED_USER_ID, job["job_id"])
    assert store.claim_job("other-worker")["job_id"] == job["job_id"]


def test_aborted_effect_can_be_retried(store):
    job = _enqueue(store)
    store.claim_job("worker")
    _, acquired = store.begin_job_effect(job["job_id"], "worker", "provider-call")
    assert acquired
    store.abort_job_effect(job["job_id"], "worker", "provider-call")

    cached, acquired = store.begin_job_effect(job["job_id"], "worker", "provider-call")
    assert cached is None
    assert acquired


def test_job_expiration_prevents_claim(store, monkeypatch):
    start = datetime(2026, 8, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(job_queue, "_now", lambda: start)
    job = _enqueue(store, expires_in_seconds=5)
    monkeypatch.setattr(job_queue, "_now", lambda: start + timedelta(seconds=6))
    assert store.claim_job("worker") is None
    assert store.get_job(store.SEED_USER_ID, job["job_id"])["status"] == "expired"


def test_due_sync_schedule_enqueues_once_and_advances(store, monkeypatch):
    start = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(job_queue, "_now", lambda: start)
    schedule = store.upsert_sync_schedule(
        store.SEED_USER_ID, "medium", 300
    )
    assert schedule["next_run_at"] == (start + timedelta(seconds=300)).isoformat()

    due = start + timedelta(seconds=301)
    monkeypatch.setattr(job_queue, "_now", lambda: due)
    assert store.enqueue_due_sync_jobs() == 1
    assert store.enqueue_due_sync_jobs() == 0

    job = store.list_jobs(store.SEED_USER_ID, queue="sync")[0]
    assert job["type"] == "sync"
    assert job["payload"] == {"platform": "medium", "scheduled": True}
    advanced = store.list_sync_schedules(store.SEED_USER_ID)[0]
    assert advanced["next_run_at"] > due.isoformat()


def test_sync_schedule_is_user_scoped_and_deletable(store):
    store.upsert_sync_schedule(store.SEED_USER_ID, "hashnode", 900)
    assert [item["platform"] for item in store.list_sync_schedules(store.SEED_USER_ID)] == [
        "hashnode"
    ]
    assert store.delete_sync_schedule(store.SEED_USER_ID, "hashnode")
    assert store.list_sync_schedules(store.SEED_USER_ID) == []
