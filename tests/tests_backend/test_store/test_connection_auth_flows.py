from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import backend.store.connection_auth as connection_auth
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


def test_auth_flow_secrets_are_encrypted_and_survive_restart(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "BLOGHUB_CREDENTIAL_KEY_FILE", str(tmp_path / "credential-keys.json")
    )
    configure_key_provider(None)
    database = tmp_path / "bloghub.db"
    blobs = tmp_path / "blobs"
    first = SQLiteStore(str(database), str(blobs))
    flow = first.create_connection_auth_flow(
        first.SEED_USER_ID,
        "openai",
        "device_code",
        authorization_url="https://provider.example/device",
        device_code="ABCD-EFGH",
    )
    raw = first._con.execute(
        """SELECT authorization_url_secret, device_code_secret
           FROM connection_auth_flows WHERE id=?""",
        (flow["id"],),
    ).fetchone()
    assert raw[0].startswith("enc:v1:")
    assert raw[1].startswith("enc:v1:")
    assert "provider.example" not in raw[0]
    assert "ABCD-EFGH" not in raw[1]
    first.close()

    reopened = SQLiteStore(str(database), str(blobs))
    restored = reopened.get_connection_auth_flow(reopened.SEED_USER_ID, flow["id"])
    assert restored["authorization_url"] == "https://provider.example/device"
    assert restored["device_code"] == "ABCD-EFGH"
    assert restored["status"] == "waiting_for_authorization"
    reopened.close()
    configure_key_provider(None)


def test_new_flow_cancels_previous_flow_for_same_provider(store):
    first = store.create_connection_auth_flow(
        store.SEED_USER_ID,
        "anthropic",
        "browser_callback",
        authorization_url="https://provider.example/first",
    )
    second = store.create_connection_auth_flow(
        store.SEED_USER_ID,
        "anthropic",
        "browser_callback",
        authorization_url="https://provider.example/second",
    )
    assert store.get_connection_auth_flow(store.SEED_USER_ID, first["id"])["status"] == "canceled"
    assert store.get_latest_connection_auth_flow(
        store.SEED_USER_ID, "anthropic", active_only=True
    )["id"] == second["id"]


def test_expired_flow_becomes_timed_out_with_connection_state(store, monkeypatch):
    start = datetime(2026, 8, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(connection_auth, "_now", lambda: start)
    flow = store.create_connection_auth_flow(
        store.SEED_USER_ID,
        "openai",
        "device_code",
        authorization_url="https://provider.example/device",
        ttl_seconds=30,
    )
    monkeypatch.setattr(
        connection_auth, "_now", lambda: start + timedelta(seconds=31)
    )
    expired = store.get_connection_auth_flow(store.SEED_USER_ID, flow["id"])
    connection = next(
        item for item in store.list_connections(store.SEED_USER_ID)
        if item["id"] == "openai"
    )
    assert expired["status"] == "timed_out"
    assert expired["error_code"] == "authorization_timeout"
    assert connection["status"] == "timed_out"


def test_flow_is_scoped_to_its_owner(store):
    flow = store.create_connection_auth_flow(
        store.SEED_USER_ID,
        "openai",
        "device_code",
        authorization_url="https://provider.example/device",
    )
    assert store.get_connection_auth_flow("another-user", flow["id"]) is None
