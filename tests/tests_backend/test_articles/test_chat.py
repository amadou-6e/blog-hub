"""Tests for GET/POST /api/articles/{id}/chat"""

import pytest
from fastapi.testclient import TestClient

import backend.store as store
from backend.store.backends.sqlite import SQLiteStore

_UID = SQLiteStore.SEED_USER_ID


class TestChat:

    def _first_article_id(self, client: TestClient) -> str:
        return client.get("/api/articles").json()["items"][0]["id"]

    # ── GET ───────────────────────────────────────────────────────────────────

    def test_get_empty_on_fresh_article(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.get(f"/api/articles/{aid}/chat")
        assert r.status_code == 200
        assert r.json()["messages"] == []

    def test_get_unknown_article_404(self, client: TestClient):
        r = client.get("/api/articles/no_such_id/chat")
        assert r.status_code == 404

    # ── POST ──────────────────────────────────────────────────────────────────

    def test_help_command(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.post(f"/api/articles/{aid}/chat", json={"command": "help"})
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "destinations status" in reply
        assert "comment list" in reply
        assert "inspect" in reply

    def test_unknown_command_returns_error_text(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.post(f"/api/articles/{aid}/chat", json={"command": "bogus xyz"})
        assert r.status_code == 200
        assert "Unknown command" in r.json()["reply"]

    def test_destinations_status_lists_platforms(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.post(f"/api/articles/{aid}/chat", json={"command": "destinations status"})
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "medium" in reply
        assert "hashnode" in reply
        assert "devto" in reply

    def test_comment_list_empty(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.post(f"/api/articles/{aid}/chat", json={"command": "comment list"})
        assert r.status_code == 200
        assert "No comments" in r.json()["reply"]

    def test_comment_list_shows_added_comment(self, client: TestClient):
        aid = self._first_article_id(client)
        store.add_comment(_UID, aid, author="Alice", text="Please elaborate here")
        r = client.post(f"/api/articles/{aid}/chat", json={"command": "comment list"})
        assert r.status_code == 200
        assert "Alice" in r.json()["reply"]
        assert "Please elaborate here" in r.json()["reply"]

    def test_patch_apply_via_chat(self, client: TestClient):
        aid = self._first_article_id(client)
        pid = store.add_patch(_UID, aid, label="Fix", removed="old", added="new")["id"]
        r = client.post(f"/api/articles/{aid}/chat", json={"command": f"patch apply {pid}"})
        assert r.status_code == 200
        assert "applied" in r.json()["reply"].lower()
        updated = store.list_patches(_UID, aid)
        assert updated[0]["state"] == "accepted"

    def test_patch_apply_unknown_id(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.post(f"/api/articles/{aid}/chat", json={"command": "patch apply no_pid"})
        assert r.status_code == 200
        assert "not found" in r.json()["reply"].lower()

    def test_inspect_command(self, client: TestClient):
        aid = self._first_article_id(client)
        r = client.post(f"/api/articles/{aid}/chat", json={"command": "inspect"})
        assert r.status_code == 200
        reply = r.json()["reply"]
        assert "word_count" in reply
        assert "Gate" in reply

    # ── Persistence ───────────────────────────────────────────────────────────

    def test_messages_persist_across_calls(self, client: TestClient):
        aid = self._first_article_id(client)
        client.post(f"/api/articles/{aid}/chat", json={"command": "help"})
        client.post(f"/api/articles/{aid}/chat", json={"command": "inspect"})
        r = client.get(f"/api/articles/{aid}/chat")
        messages = r.json()["messages"]
        # 2 user + 2 bot = 4 messages
        assert len(messages) == 4
        roles = [m["role"] for m in messages]
        assert roles == ["user", "bot", "user", "bot"]

    def test_post_unknown_article_404(self, client: TestClient):
        r = client.post("/api/articles/no_such_id/chat", json={"command": "help"})
        assert r.status_code == 404
