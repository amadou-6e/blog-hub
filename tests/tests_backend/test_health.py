"""
Tests for /health — backend/main.py
"""

from fastapi.testclient import TestClient


# ─── /health ──────────────────────────────────────────────────────────────────


class TestHealth:

    def test_health_ok(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
