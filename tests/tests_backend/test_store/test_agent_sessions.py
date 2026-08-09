from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import agent_service
from backend.store.backends.sqlite import SQLiteStore


@pytest.fixture
def store(tmp_path):
    instance = SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))
    yield instance
    instance.close()


def _create(store: SQLiteStore, **overrides) -> dict:
    values = {
        "provider": "openai",
        "model": "gpt-5",
        "article_id": "art_001",
        "title": "Persistent editing session",
        "metadata": {"source": "editor"},
    }
    values.update(overrides)
    return store.create_agent_session(store.SEED_USER_ID, **values)


def test_full_session_survives_store_restart(tmp_path):
    database = tmp_path / "bloghub.db"
    blobs = tmp_path / "blobs"
    first = SQLiteStore(str(database), str(blobs))
    session = _create(first)
    session_id = session["id"]
    first.add_agent_message(first.SEED_USER_ID, session_id, "user", "Improve the intro")
    tool, created = first.record_agent_tool_call(
        first.SEED_USER_ID, session_id,
        idempotency_key="replace-intro-v1", name="edit_article",
        arguments={"article_id": "art_001"},
    )
    assert created
    assert first.claim_agent_tool_call(first.SEED_USER_ID, session_id, tool["id"])
    first.complete_agent_tool_call(
        first.SEED_USER_ID, session_id, tool["id"], result={"changed": True}
    )
    first.add_agent_checkpoint(
        first.SEED_USER_ID, session_id, {"cursor": 4, "article_version": 2}
    )
    first.add_agent_output(
        first.SEED_USER_ID, session_id, kind="patch", reference="patch_123"
    )
    first.close()

    reopened = SQLiteStore(str(database), str(blobs))
    try:
        restored = reopened.get_agent_session(reopened.SEED_USER_ID, session_id)
        assert restored is not None
        assert restored["provider"] == "openai"
        assert restored["messages"][0]["content"] == "Improve the intro"
        assert restored["tool_calls"][0]["status"] == "completed"
        assert restored["checkpoints"][0]["state"]["article_version"] == 2
        assert restored["outputs"][0]["reference"] == "patch_123"
    finally:
        reopened.close()


def test_tool_calls_are_idempotent_and_claimed_once(store):
    session_id = _create(store)["id"]
    first, first_created = store.record_agent_tool_call(
        store.SEED_USER_ID, session_id,
        idempotency_key="internet-search-1", name="search", arguments={"q": "drawio"},
    )
    second, second_created = store.record_agent_tool_call(
        store.SEED_USER_ID, session_id,
        idempotency_key="internet-search-1", name="search", arguments={"q": "ignored"},
    )
    assert first_created is True
    assert second_created is False
    assert second["id"] == first["id"]
    assert second["arguments"] == {"q": "drawio"}
    assert store.claim_agent_tool_call(store.SEED_USER_ID, session_id, first["id"]) is True
    assert store.claim_agent_tool_call(store.SEED_USER_ID, session_id, first["id"]) is False


def test_approval_checkpoint_and_resume_lifecycle(store):
    session_id = _create(store)["id"]
    approval = store.request_agent_approval(
        store.SEED_USER_ID, session_id, {"operation": "write", "path": "article.md"}
    )
    waiting = store.get_agent_session(store.SEED_USER_ID, session_id)
    assert waiting["status"] == "waiting_for_approval"

    resolved = store.resolve_agent_approval(
        store.SEED_USER_ID, session_id, approval["id"], approved=True,
        response={"scope": "once"},
    )
    assert resolved["status"] == "approved"
    assert store.get_agent_session(store.SEED_USER_ID, session_id)["status"] == "waiting_for_resume"
    resumed = store.resume_agent_session(store.SEED_USER_ID, session_id)
    assert resumed["status"] == "running"

    canceled = store.cancel_agent_session(store.SEED_USER_ID, session_id)
    assert canceled["status"] == "canceled"
    archived = store.archive_agent_session(store.SEED_USER_ID, session_id)
    assert archived["archived_at"] is not None
    assert store.list_agent_sessions(store.SEED_USER_ID) == []
    assert len(store.list_agent_sessions(store.SEED_USER_ID, include_archived=True)) == 1


def test_interrupted_running_sessions_wait_for_explicit_resume(store):
    session_id = _create(store)["id"]
    tool, _ = store.record_agent_tool_call(
        store.SEED_USER_ID, session_id,
        idempotency_key="claimed-before-restart", name="write", arguments={},
    )
    assert store.claim_agent_tool_call(store.SEED_USER_ID, session_id, tool["id"])
    assert store.recover_agent_sessions() == 1
    recovered = store.get_agent_session(store.SEED_USER_ID, session_id)
    assert recovered["status"] == "waiting_for_resume"
    assert recovered["events"][-1]["kind"] == "interrupted"
    assert recovered["tool_calls"][0]["status"] == "interrupted"
    assert not store.claim_agent_tool_call(store.SEED_USER_ID, session_id, tool["id"])


def test_sessions_are_isolated_by_user(store):
    other_user = "user_other"
    store._con.execute(
        "INSERT INTO users (id, email, password_hash, created_at) VALUES (?,?,?,?)",
        (other_user, "other@example.com", "hash", datetime.now(timezone.utc).isoformat()),
    )
    store._con.commit()
    session_id = _create(store)["id"]

    assert store.get_agent_session(other_user, session_id) is None
    assert store.list_agent_sessions(other_user) == []
    with pytest.raises(KeyError):
        store.add_agent_message(other_user, session_id, "user", "not mine")


def test_session_payloads_are_scrubbed_before_sqlite(store):
    secret_values = [
        "sk-super-secret-key", "cookie-private", "bearer-private", "plain-private",
        "idempotency-private",
    ]
    session = store.create_agent_session(
        store.SEED_USER_ID, provider="openai",
        metadata={"api_key": secret_values[0], "nested": {"refresh_token": secret_values[3]}},
    )
    store.add_agent_message(
        store.SEED_USER_ID, session["id"], "user",
        "Authorization: Bearer bearer-private Cookie: cookie-private",
    )
    first, created = store.record_agent_tool_call(
        store.SEED_USER_ID, session["id"],
        idempotency_key=f"token={secret_values[4]}",
        name="call_provider", arguments={"provider_token": secret_values[3]},
    )
    second, created_again = store.record_agent_tool_call(
        store.SEED_USER_ID, session["id"],
        idempotency_key=f"token={secret_values[4]}",
        name="call_provider", arguments={},
    )
    assert created and not created_again and first["id"] == second["id"]

    dump = "\n".join(store._con.iterdump())
    assert "[REDACTED]" in dump
    for secret in secret_values:
        assert secret not in dump


def test_export_and_delete_include_no_orphans(store):
    session_id = _create(store)["id"]
    store.add_agent_message(store.SEED_USER_ID, session_id, "assistant", "Done")
    store.update_agent_session_status(store.SEED_USER_ID, session_id, "completed")
    exported = store.export_agent_session(store.SEED_USER_ID, session_id)
    assert exported["format"] == "bloghub-agent-session"
    json.dumps(exported)

    assert store.delete_agent_session(store.SEED_USER_ID, session_id)
    assert store.get_agent_session(store.SEED_USER_ID, session_id) is None
    assert store._con.execute(
        "SELECT COUNT(*) FROM agent_session_messages WHERE session_id=?", (session_id,)
    ).fetchone()[0] == 0


def test_retention_expires_active_and_deletes_old_terminal_sessions(store):
    expiring = _create(store, expires_in_days=1)["id"]
    old_terminal = _create(store)["id"]
    store.update_agent_session_status(store.SEED_USER_ID, old_terminal, "completed")
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    store._con.execute(
        "UPDATE agent_sessions SET expires_at=? WHERE id=?", (old, expiring)
    )
    store._con.execute(
        "UPDATE agent_sessions SET completed_at=?, updated_at=? WHERE id=?",
        (old, old, old_terminal),
    )
    store._con.commit()

    result = store.cleanup_agent_sessions(retention_days=90)
    assert result == {"expired": 1, "deleted": 1}
    assert store.get_agent_session(store.SEED_USER_ID, expiring)["status"] == "expired"
    assert store.get_agent_session(store.SEED_USER_ID, old_terminal) is None


def test_generation_worker_completes_durable_session(store, monkeypatch):
    user_id = store.SEED_USER_ID
    article = store.create_article(user_id, "Draft")
    job = store.create_job(user_id, "generate", article["id"])
    session = store.create_agent_session(
        user_id, provider="openai", article_id=article["id"], title="Generate article"
    )
    store.add_agent_message(user_id, session["id"], "user", "Write the article")
    monkeypatch.setattr(agent_service, "store", store)
    monkeypatch.setattr(
        agent_service.runner, "run_task",
        lambda **_kwargs: {
            "exit_code": 0,
            "stdout": "# Durable Article\n\nGenerated content survives restart.",
            "stderr": "",
        },
    )

    agent_service.run_generation(
        user_id=user_id, job_id=job["job_id"], article_id=article["id"],
        brief="Write the article", skill="tutorial", provider="codex",
        word_count=1000, context_text=None, destinations=[],
        session_id=session["id"],
    )

    persisted = store.get_agent_session(user_id, session["id"])
    assert persisted["status"] == "completed"
    assert persisted["messages"][-1]["role"] == "assistant"
    assert "Generated content survives restart" in persisted["messages"][-1]["content"]
    assert persisted["outputs"][0]["reference"] == article["id"]
    assert store.get_job(user_id, job["job_id"])["status"] == "done"
