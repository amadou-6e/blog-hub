"""Tests for GET /api/agent/providers."""

import pytest
from fastapi.testclient import TestClient

import backend.store as store
from backend.store.backends.sqlite import SQLiteStore

_UID = SQLiteStore.SEED_USER_ID


class TestGetProviders:

    def test_response_shape(self, client: TestClient):
        r = client.get("/api/agent/providers")
        assert r.status_code == 200
        body = r.json()
        assert "providers" in body
        for p in body["providers"]:
            assert "id" in p
            assert "label" in p
            assert "configured" in p

    def test_returns_two_providers(self, client: TestClient):
        providers = client.get("/api/agent/providers").json()["providers"]
        ids = {p["id"] for p in providers}
        assert ids == {"claude", "codex"}

    def test_no_connections_both_not_configured(self, client: TestClient, monkeypatch):
        # Bypass env-var-based secret detection so we see the true "no creds" state
        monkeypatch.setattr(store, "list_connections", lambda user_id: [])
        providers = client.get("/api/agent/providers").json()["providers"]
        for p in providers:
            assert p["configured"] is False

    def test_connected_anthropic_returns_configured_true(self, client: TestClient):
        store.save_connection(_UID, "anthropic", token="test-token", status="connected")
        providers = {p["id"]: p for p in client.get("/api/agent/providers").json()["providers"]}
        assert providers["claude"]["configured"] is True

    def test_connected_openai_returns_configured_true(self, client: TestClient):
        store.save_connection(_UID, "openai", token="test-token", status="connected")
        providers = {p["id"]: p for p in client.get("/api/agent/providers").json()["providers"]}
        assert providers["codex"]["configured"] is True

    def test_disconnected_keeps_configured_false(self, client: TestClient):
        store.save_connection(_UID, "anthropic", token="x", status="disconnected")
        providers = {p["id"]: p for p in client.get("/api/agent/providers").json()["providers"]}
        assert providers["claude"]["configured"] is False
