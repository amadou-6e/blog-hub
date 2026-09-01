from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.services.connection_health import (
    needs_user_refresh,
    record_evidence,
    record_operation_result,
    remote_operations_allowed,
)
from backend.store.backends.sqlite import SQLiteStore


def _store(tmp_path) -> SQLiteStore:
    return SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))


def test_live_success_is_fresh_then_becomes_stale(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    try:
        health = record_evidence(store, store.SEED_USER_ID, "medium", {
            "protocol_version": 1,
            "status": "connected",
            "reason": "remote_operation_succeeded",
            "source": "remote_operation",
            "authoritative": True,
        }, now=now)

        assert health["status"] == "connected"
        assert health["verified_at"] == now.isoformat()
        assert not needs_user_refresh(health, now=now + timedelta(minutes=4))
        assert needs_user_refresh(health, now=now + timedelta(minutes=5))
        assert remote_operations_allowed(health, now=now)
    finally:
        store.close()


def test_cookie_hint_does_not_claim_a_verified_connection(tmp_path):
    store = _store(tmp_path)
    try:
        health = record_evidence(store, store.SEED_USER_ID, "medium", {
            "protocol_version": 1,
            "status": "connected",
            "reason": "authentication_verified",
            "source": "stored_profile",
            "authoritative": False,
        })

        assert health["status"] == "verification_stale"
        assert health["reason"] == "credential_hint_only"
        assert health["verified_at"] is None
        assert needs_user_refresh(health)
    finally:
        store.close()


def test_health_input_is_bounded_and_does_not_persist_secrets(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    try:
        health = record_evidence(store, store.SEED_USER_ID, "hashnode", {
            "protocol_version": 1,
            "status": "rate_limited",
            "reason": "Cookie: secret=value",
            "source": "https://secret.example/token",
            "authoritative": True,
            "retry_after_seconds": "not-a-number",
            "diagnostics": {
                "http_status": 429,
                "operation": "list_articles",
                "cookie": "secret=value",
                "url": "https://secret.example/token",
            },
        }, now=now)

        assert health["reason"] == "unclassified_evidence"
        assert health["source"] == "unknown"
        assert health["diagnostics"] == {
            "http_status": 429, "operation": "list_articles",
        }
        assert health["retry_at"] == (now + timedelta(minutes=15)).isoformat()
        assert "secret" not in str(health)
    finally:
        store.close()


def test_unsupported_protocol_degrades_to_unknown(tmp_path):
    store = _store(tmp_path)
    try:
        health = record_evidence(store, store.SEED_USER_ID, "medium", {
            "protocol_version": 99,
            "status": "connected",
            "reason": "remote_operation_succeeded",
            "source": "remote_operation",
            "authoritative": True,
        })

        assert health["status"] == "unknown"
        assert health["reason"] == "unsupported_health_protocol"
        assert health["authoritative"] is False
    finally:
        store.close()


def test_verification_claim_is_atomic_and_reclaimable_after_expiry(tmp_path):
    database = tmp_path / "bloghub.db"
    blobs = tmp_path / "blobs"
    first = SQLiteStore(str(database), str(blobs))
    second = SQLiteStore(str(database), str(blobs))
    now = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    try:
        assert first.claim_connection_health_verification(
            first.SEED_USER_ID, "medium", lease_seconds=60, now=now,
        )
        assert not second.claim_connection_health_verification(
            second.SEED_USER_ID, "medium", lease_seconds=60, now=now,
        )
        assert second.claim_connection_health_verification(
            second.SEED_USER_ID, "medium", lease_seconds=60,
            now=now + timedelta(seconds=61),
        )
    finally:
        first.close()
        second.close()


def test_reauthentication_blocks_remote_operations_until_success(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    try:
        expired = record_evidence(store, store.SEED_USER_ID, "medium", {
            "protocol_version": 1,
            "status": "reauthentication_required",
            "reason": "remote_authentication_required",
            "source": "remote_operation",
            "authoritative": True,
        }, now=now)
        assert not remote_operations_allowed(expired, now=now)

        connected = record_evidence(store, store.SEED_USER_ID, "medium", {
            "protocol_version": 1,
            "status": "connected",
            "reason": "remote_operation_succeeded",
            "source": "remote_operation",
            "authoritative": True,
        }, now=now + timedelta(minutes=1))
        assert remote_operations_allowed(connected, now=now + timedelta(minutes=1))
    finally:
        store.close()


def test_successful_legacy_operation_clears_verification_lease(tmp_path):
    store = _store(tmp_path)
    try:
        assert store.claim_connection_health_verification(
            store.SEED_USER_ID, "hashnode",
        )

        health = record_operation_result(
            store, store.SEED_USER_ID, "hashnode", {"success": True},
        )

        assert health is not None
        assert health["status"] == "connected"
        assert health["source"] == "backend_operation_bridge"
        assert health["verification_lease_until"] is None
    finally:
        store.close()
