"""Tests for GET/POST/PATCH/DELETE /api/articles/{id}/comments"""

import pytest
from fastapi.testclient import TestClient


class TestComments:

    def _first_article_id(self, client: TestClient) -> str:
        return client.get("/api/articles").json()["items"][0]["id"]

    # ── List ──────────────────────────────────────────────────────────────────

    def test_list_empty_on_seed_article(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.get(f"/api/articles/{aid}/comments")
        assert r.status_code == 200
        assert r.json() == {"comments": []}

    def test_list_unknown_article_404(self, client: TestClient):
        r = client.get("/api/articles/no_such_id/comments")
        assert r.status_code == 404

    # ── Create ────────────────────────────────────────────────────────────────

    def test_create_returns_201_and_shape(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.post(f"/api/articles/{aid}/comments",
                        json={
                            "author": "Alice",
                            "text": "Great intro!"
                        })
        assert r.status_code == 201
        body = r.json()
        assert body["author"] == "Alice"
        assert body["text"] == "Great intro!"
        assert body["resolved"] is False
        assert body["hasPatch"] is False
        assert body["articleId"] == aid
        assert "id" in body
        assert "createdAt" in body

    def test_create_unknown_article_404(self, client: TestClient):
        r = client.post("/api/articles/no_such_id/comments",
                        json={
                            "author": "Bob",
                            "text": "hello"
                        })
        assert r.status_code == 404

    def test_create_persisted_in_list(self, client: TestClient):
        aid = self._first_article_id(client)
        client.post(f"/api/articles/{aid}/comments", json={"author": "Alice", "text": "First"})
        client.post(f"/api/articles/{aid}/comments", json={"author": "Bob", "text": "Second"})
        comments = client.get(f"/api/articles/{aid}/comments").json()["comments"]
        assert len(comments) == 2
        assert comments[0]["author"] == "Alice"
        assert comments[1]["author"] == "Bob"

    # ── Patch / Resolve ───────────────────────────────────────────────────────

    def test_resolve_comment(self, client: TestClient):
        aid = self._first_article_id(client)
        cid = client.post(f"/api/articles/{aid}/comments",
                          json={
                              "author": "Alice",
                              "text": "Fix this"
                          }).json()["id"]
        r = client.patch(f"/api/articles/{aid}/comments/{cid}", json={"resolved": True})
        assert r.status_code == 200
        assert r.json()["resolved"] is True

    def test_edit_comment_text(self, client: TestClient):
        aid = self._first_article_id(client)
        cid = client.post(f"/api/articles/{aid}/comments", json={
            "author": "Alice",
            "text": "old"
        }).json()["id"]
        r = client.patch(f"/api/articles/{aid}/comments/{cid}", json={"text": "new text"})
        assert r.status_code == 200
        assert r.json()["text"] == "new text"

    def test_patch_unknown_comment_404(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.patch(f"/api/articles/{aid}/comments/no_cid", json={"resolved": True})
        assert r.status_code == 404

    # ── Delete ────────────────────────────────────────────────────────────────

    def test_delete_removes_comment(self, client: TestClient):
        aid = self._first_article_id(client)
        cid = client.post(f"/api/articles/{aid}/comments",
                          json={
                              "author": "Alice",
                              "text": "to delete"
                          }).json()["id"]
        r = client.delete(f"/api/articles/{aid}/comments/{cid}")
        assert r.status_code == 204
        comments = client.get(f"/api/articles/{aid}/comments").json()["comments"]
        assert all(c["id"] != cid for c in comments)

    def test_delete_unknown_comment_404(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.delete(f"/api/articles/{aid}/comments/no_cid")
        assert r.status_code == 404
