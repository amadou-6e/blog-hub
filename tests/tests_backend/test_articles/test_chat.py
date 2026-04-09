"""
Tests for /api/articles/{article_id}/chat endpoints.
"""
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_article(client) -> str:
    r = client.post("/api/articles", json={
        "title": "Chat Article",
        "content": "C " * 300,
    })
    assert r.status_code == 201
    return r.json()["id"]


def _chat(client, article_id: str, command: str) -> dict:
    r = client.post(f"/api/articles/{article_id}/chat", json={"command": command})
    assert r.status_code == 200
    return r.json()


# ── GET /chat (history) ───────────────────────────────────────────────────────

def test_get_chat_empty(client):
    aid = _create_article(client)
    r = client.get(f"/api/articles/{aid}/chat")
    assert r.status_code == 200
    assert r.json()["messages"] == []


def test_get_chat_unknown_article(client):
    r = client.get("/api/articles/ghost/chat")
    assert r.status_code == 404


def test_get_chat_after_command(client):
    aid = _create_article(client)
    _chat(client, aid, "help")
    r = client.get(f"/api/articles/{aid}/chat")
    msgs = r.json()["messages"]
    # user + bot = 2 messages
    assert len(msgs) == 2
    roles = [m["role"] for m in msgs]
    assert "user" in roles
    assert "bot" in roles


def test_get_chat_message_fields(client):
    aid = _create_article(client)
    _chat(client, aid, "help")
    msgs = client.get(f"/api/articles/{aid}/chat").json()["messages"]
    for m in msgs:
        assert "role" in m
        assert "text" in m
        assert "createdAt" in m


# ── POST /chat (commands) ─────────────────────────────────────────────────────

def test_chat_unknown_article_404(client):
    r = client.post("/api/articles/no-article/chat", json={"command": "help"})
    assert r.status_code == 404


def test_chat_command_required(client):
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/chat", json={})
    assert r.status_code == 422


def test_chat_help_command(client):
    aid = _create_article(client)
    reply = _chat(client, aid, "help")["reply"]
    assert "help" in reply.lower()
    assert "destinations" in reply.lower()


def test_chat_question_mark(client):
    aid = _create_article(client)
    reply = _chat(client, aid, "?")["reply"]
    assert "help" in reply.lower()


def test_chat_destinations_status(client):
    aid = _create_article(client)
    reply = _chat(client, aid, "destinations status")["reply"]
    # Either shows destinations or says none linked
    assert isinstance(reply, str)
    assert len(reply) > 0


def test_chat_comment_list_empty(client):
    aid = _create_article(client)
    reply = _chat(client, aid, "comment list")["reply"]
    assert "no open comments" in reply.lower() or "no comments" in reply.lower()


def test_chat_comment_list_shows_comments(client):
    aid = _create_article(client)
    client.post(f"/api/articles/{aid}/comments", json={"text": "Revisit this"})
    reply = _chat(client, aid, "comment list")["reply"]
    assert "Revisit this" in reply


def test_chat_patch_apply_valid(client):
    aid = _create_article(client)
    client.post(f"/api/articles/{aid}/comments", json={"text": "Needs improvement"})
    client.post(f"/api/articles/{aid}/regenerate")
    patches = client.get(f"/api/articles/{aid}/patches").json()["patches"]
    pid = patches[0]["id"]
    reply = _chat(client, aid, f"patch apply {pid}")["reply"]
    assert "accepted" in reply.lower()


def test_chat_patch_apply_invalid(client):
    aid = _create_article(client)
    reply = _chat(client, aid, "patch apply not-a-real-id")["reply"]
    assert "not found" in reply.lower()


def test_chat_unknown_command(client):
    aid = _create_article(client)
    reply = _chat(client, aid, "do something weird")["reply"]
    assert "unknown command" in reply.lower()


def test_chat_history_accumulates_across_calls(client):
    aid = _create_article(client)
    _chat(client, aid, "help")
    _chat(client, aid, "comment list")
    msgs = client.get(f"/api/articles/{aid}/chat").json()["messages"]
    # 2 commands × 2 messages each = 4 messages
    assert len(msgs) == 4
