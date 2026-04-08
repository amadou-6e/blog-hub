"""Tests for GET /api/agent/platforms."""

from fastapi.testclient import TestClient

import backend.store as store
from backend.store.backends.sqlite import SQLiteStore

_UID = SQLiteStore.SEED_USER_ID


class TestGetAgentPlatforms:

    def test_response_shape(self, client: TestClient):
        r = client.get("/api/agent/platforms")
        assert r.status_code == 200
        body = r.json()
        assert "platforms" in body
        for p in body["platforms"]:
            assert "id" in p
            assert "label" in p
            assert "status" in p
            assert "session_expires_at" in p

    def test_returns_three_blog_platforms(self, client: TestClient):
        platforms = client.get("/api/agent/platforms").json()["platforms"]
        ids = {p["id"] for p in platforms}
        assert ids == {"medium", "hashnode", "devto"}

    def test_all_status_values_are_valid(self, client: TestClient):
        platforms = client.get("/api/agent/platforms").json()["platforms"]
        valid = {"connected", "expired", "not_configured"}
        for p in platforms:
            assert p["status"] in valid, f"Unexpected status {p['status']} for {p['id']}"

    def test_session_expires_at_always_null(self, client: TestClient):
        platforms = client.get("/api/agent/platforms").json()["platforms"]
        for p in platforms:
            assert p["session_expires_at"] is None

    def test_no_connections_all_not_configured(self, client: TestClient, monkeypatch):
        # Bypass env-var-based secret detection by stubbing list_connections
        monkeypatch.setattr(store, "list_connections", lambda user_id: [])
        platforms = {p["id"]: p for p in client.get("/api/agent/platforms").json()["platforms"]}
        for pid in ("medium", "hashnode", "devto"):
            assert platforms[pid]["status"] == "not_configured"

    def test_connected_medium_shows_connected(self, client: TestClient):
        store.save_connection(_UID, "medium", token="tok", status="connected")
        platforms = {p["id"]: p for p in client.get("/api/agent/platforms").json()["platforms"]}
        assert platforms["medium"]["status"] == "connected"

    def test_does_not_include_ai_providers(self, client: TestClient):
        platforms = client.get("/api/agent/platforms").json()["platforms"]
        ids = {p["id"] for p in platforms}
        assert "anthropic" not in ids
        assert "openai" not in ids
