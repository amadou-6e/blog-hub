from __future__ import annotations

import pytest

from backend.services import connection_auth
from backend.store.backends.sqlite import SQLiteStore
from backend.store.crypto import configure_key_provider


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "BLOGHUB_CREDENTIAL_KEY_FILE", str(tmp_path / "credential-keys.json")
    )
    configure_key_provider(None)
    instance = SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))
    yield instance
    instance.close()
    configure_key_provider(None)


def test_anthropic_callback_flow_connects_without_persisting_callback(
    store, monkeypatch,
):
    monkeypatch.setattr(
        connection_auth.runner,
        "login",
        lambda provider: {
            "available": True,
            "url": "https://claude.example/authorize?state=temporary",
        },
    )
    submitted = []
    monkeypatch.setattr(
        connection_auth.runner,
        "submit_login_callback",
        lambda provider, callback: submitted.append((provider, callback)) or {
            "status": "submitted"
        },
    )
    statuses = iter(
        [
            {"status": "pending"},
            {"status": "connected", "username": "writer@example.com"},
        ]
    )
    monkeypatch.setattr(connection_auth.runner, "login_status", lambda provider: next(statuses))

    started = connection_auth.start(store, store.SEED_USER_ID, "anthropic")
    assert started["flow_type"] == "browser_callback"
    callback = "http://localhost:54322/callback?code=secret-code&state=secret-state"
    connection_auth.submit_callback(store, store.SEED_USER_ID, started["flow_id"], callback)
    assert submitted == [("anthropic", callback)]
    database_dump = " ".join(
        str(value)
        for row in store._con.iterdump()
        for value in (row,)
    )
    assert "secret-code" not in database_dump
    assert "secret-state" not in database_dump
    assert connection_auth.status(store, store.SEED_USER_ID, started["flow_id"])["status"] == "waiting_for_authorization"
    completed = connection_auth.status(store, store.SEED_USER_ID, started["flow_id"])
    assert completed["status"] == "connected"
    assert completed["username"] == "writer@example.com"
    assert store.get_connection_token(store.SEED_USER_ID, "anthropic") == "web_session:anthropic"


def test_openai_device_code_flow_and_rate_limit_state(store, monkeypatch):
    monkeypatch.setattr(
        connection_auth.runner,
        "login",
        lambda provider: {
            "available": True,
            "url": "https://openai.example/device",
            "device_code": "ABCD-EFGH",
        },
    )
    monkeypatch.setattr(
        connection_auth.runner,
        "login_status",
        lambda provider: {
            "status": "rate_limited",
            "reason": "Too many requests",
            "error_code": "rate_limited",
        },
    )

    started = connection_auth.start(store, store.SEED_USER_ID, "openai")
    assert started["flow_type"] == "device_code"
    assert started["device_code"] == "ABCD-EFGH"
    failed = connection_auth.status(store, store.SEED_USER_ID, started["flow_id"])
    assert failed["status"] == "rate_limited"
    assert "Wait a few minutes" in failed["recovery"]


def test_cancel_stops_runner_without_logging_out_existing_session(store, monkeypatch):
    monkeypatch.setattr(
        connection_auth.runner,
        "login",
        lambda provider: {"available": True, "url": "https://openai.example/device"},
    )
    canceled = []
    monkeypatch.setattr(
        connection_auth.runner, "cancel_login", lambda provider: canceled.append(provider)
    )
    started = connection_auth.start(store, store.SEED_USER_ID, "openai")
    result = connection_auth.cancel(store, store.SEED_USER_ID, started["flow_id"])
    assert result["status"] == "canceled"
    assert canceled == ["openai"]


def test_provider_rejection_callback_becomes_explicit_state(store, monkeypatch):
    monkeypatch.setattr(
        connection_auth.runner,
        "login",
        lambda provider: {"available": True, "url": "https://claude.example/auth"},
    )
    canceled = []
    monkeypatch.setattr(
        connection_auth.runner, "cancel_login", lambda provider: canceled.append(provider)
    )
    started = connection_auth.start(store, store.SEED_USER_ID, "anthropic")

    rejected = connection_auth.submit_callback(
        store,
        store.SEED_USER_ID,
        started["flow_id"],
        "http://localhost:54322/callback?error=access_denied&state=temporary",
    )

    assert rejected["status"] == "rejected"
    assert rejected["error_code"] == "authorization_rejected"
    assert canceled == ["anthropic"]
