"""
Tests for /api/platforms — backend/routers/platforms.py
"""

import pytest
from fastapi.testclient import TestClient

# ─── GET /api/platforms ───────────────────────────────────────────────────────


class TestPlatforms:

    def test_returns_three_platforms(self, client: TestClient):
        r = client.get("/api/platforms")
        assert r.status_code == 200
        assert len(r.json()["platforms"]) == 3

    def test_platform_ids(self, client: TestClient):
        ids = {p["id"] for p in client.get("/api/platforms").json()["platforms"]}
        assert ids == {"medium", "hashnode", "devto"}

    def test_platform_shape(self, client: TestClient):
        p = client.get("/api/platforms").json()["platforms"][0]
        assert "id" in p
        assert "connected" in p
        assert "label" in p
        assert "username" in p

    def test_connected_count(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        import backend.store.backends.sqlite as _sqlite_mod
        # Suppress env-based auto-detection so only DB-saved connections appear.
        monkeypatch.setattr(_sqlite_mod.SQLiteStore, "_connection_has_env_secret",
                            staticmethod(lambda conn_id: False))
        connected = [p for p in client.get("/api/platforms").json()["platforms"] if p["connected"]]
        assert len(connected) == 0  # no connections saved after reset
