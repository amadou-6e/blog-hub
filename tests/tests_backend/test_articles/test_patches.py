"""Tests for GET /patches + accept/reject on /api/articles/{id}/patches"""

import pytest
from fastapi.testclient import TestClient

import backend.store as store
from backend.store.backends.sqlite import SQLiteStore


class TestPatches:

    def _first_article_id(self, client: TestClient) -> str:
        return client.get("/api/articles").json()["items"][0]["id"]

    def _add_patch(self, article_id: str) -> dict:
        article = store.get_article(SQLiteStore.SEED_USER_ID, article_id)
        removed = article["body"][:40]
        return store.add_patch(
            SQLiteStore.SEED_USER_ID,
            article_id=article_id,
            label="Test patch",
            removed=removed,
            added="new text here",
        )

    # ── List ──────────────────────────────────────────────────────────────────

    def test_list_empty_on_seed_article(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.get(f"/api/articles/{aid}/patches")
        assert r.status_code == 200
        assert r.json() == {"patches": []}

    def test_list_unknown_article_404(self, client: TestClient):
        r = client.get("/api/articles/no_such_id/patches")
        assert r.status_code == 404

    def test_list_returns_created_patches(self, client: TestClient):
        aid = self._first_article_id(client)
        self._add_patch(aid)
        patches = client.get(f"/api/articles/{aid}/patches").json()["patches"]
        assert len(patches) == 1
        p = patches[0]
        assert p["label"] == "Test patch"
        assert p["removed"]
        assert p["added"] == "new text here"
        assert p["state"] == "pending"
        assert "id" in p
        assert "createdAt" in p
        assert p["baseRevisionId"].startswith("rev_")

    # ── Accept ────────────────────────────────────────────────────────────────

    def test_accept_transitions_state(self, client: TestClient):
        aid = self._first_article_id(client)
        pid = self._add_patch(aid)["id"]
        r = client.post(f"/api/articles/{aid}/patches/{pid}/accept")
        assert r.status_code == 200
        assert r.json()["state"] == "accepted"
        assert "new text here" in client.get(f"/api/articles/{aid}").json()["content"]

    def test_accept_reflected_in_list(self, client: TestClient):
        aid = self._first_article_id(client)
        pid = self._add_patch(aid)["id"]
        client.post(f"/api/articles/{aid}/patches/{pid}/accept")
        patches = client.get(f"/api/articles/{aid}/patches").json()["patches"]
        assert patches[0]["state"] == "accepted"

    def test_accept_unknown_patch_404(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.post(f"/api/articles/{aid}/patches/no_pid/accept")
        assert r.status_code == 404

    # ── Reject ────────────────────────────────────────────────────────────────

    def test_reject_transitions_state(self, client: TestClient):
        aid = self._first_article_id(client)
        pid = self._add_patch(aid)["id"]
        r = client.post(f"/api/articles/{aid}/patches/{pid}/reject")
        assert r.status_code == 200
        assert r.json()["state"] == "rejected"

    def test_reject_unknown_patch_404(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.post(f"/api/articles/{aid}/patches/no_pid/reject")
        assert r.status_code == 404

    def test_patch_shape(self, client: TestClient):
        aid = self._first_article_id(client)
        pid = self._add_patch(aid)["id"]
        r = client.post(f"/api/articles/{aid}/patches/{pid}/accept")
        body = r.json()
        assert "id" in body
        assert "articleId" in body
        assert "label" in body
        assert "removed" in body
        assert "added" in body
        assert "state" in body
        assert "createdAt" in body
        assert "baseRevisionId" in body
