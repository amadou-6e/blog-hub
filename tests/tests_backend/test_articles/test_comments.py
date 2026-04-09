"""
Tests for /api/articles/{article_id}/comments endpoints.
"""
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_article(client) -> str:
    r = client.post("/api/articles", json={
        "title": "Test Article",
        "content": "A " * 300,
    })
    assert r.status_code == 201
    return r.json()["id"]


def _add_comment(client, article_id: str, text: str = "Needs work", author: str = "alice", anchor: str = "") -> dict:
    payload = {"text": text, "author": author}
    if anchor:
        payload["anchor"] = anchor
    r = client.post(f"/api/articles/{article_id}/comments", json=payload)
    assert r.status_code == 201
    return r.json()


# ── list ──────────────────────────────────────────────────────────────────────

def test_list_comments_empty(client):
    aid = _create_article(client)
    r = client.get(f"/api/articles/{aid}/comments")
    assert r.status_code == 200
    assert r.json()["comments"] == []


def test_list_comments_unknown_article(client):
    r = client.get("/api/articles/no-such-id/comments")
    assert r.status_code == 404


def test_list_comments_returns_created(client):
    aid = _create_article(client)
    _add_comment(client, aid, "First comment")
    _add_comment(client, aid, "Second comment")
    r = client.get(f"/api/articles/{aid}/comments")
    assert r.status_code == 200
    data = r.json()["comments"]
    assert len(data) == 2
    texts = {c["text"] for c in data}
    assert texts == {"First comment", "Second comment"}


def test_list_comments_scoped_to_article(client):
    aid1 = _create_article(client)
    aid2 = _create_article(client)
    _add_comment(client, aid1, "Only in article 1")
    r = client.get(f"/api/articles/{aid2}/comments")
    assert r.json()["comments"] == []


# ── add ───────────────────────────────────────────────────────────────────────

def test_add_comment_201(client):
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/comments", json={"text": "Great post"})
    assert r.status_code == 201


def test_add_comment_returns_fields(client):
    aid = _create_article(client)
    c = _add_comment(client, aid, "Review this section", author="bob", anchor="para-3")
    assert c["text"] == "Review this section"
    assert c["author"] == "bob"
    assert c["anchor"] == "para-3"
    assert c["resolved"] is False
    assert "id" in c


def test_add_comment_unknown_article_404(client):
    r = client.post("/api/articles/ghost/comments", json={"text": "hi"})
    assert r.status_code == 404


def test_add_comment_text_required(client):
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/comments", json={"author": "eve"})
    assert r.status_code == 422


def test_add_comment_default_author(client):
    aid = _create_article(client)
    c = _add_comment(client, aid, "Anonymous")
    assert "author" in c


# ── update ────────────────────────────────────────────────────────────────────

def test_update_comment_text(client):
    aid = _create_article(client)
    c = _add_comment(client, aid, "Original text")
    cid = c["id"]
    r = client.patch(f"/api/articles/{aid}/comments/{cid}", json={"text": "Updated text"})
    assert r.status_code == 200
    assert r.json()["text"] == "Updated text"


def test_update_comment_resolved(client):
    aid = _create_article(client)
    c = _add_comment(client, aid, "Fix this")
    cid = c["id"]
    r = client.patch(f"/api/articles/{aid}/comments/{cid}", json={"resolved": True})
    assert r.status_code == 200
    assert r.json()["resolved"] is True


def test_update_comment_persists(client):
    aid = _create_article(client)
    c = _add_comment(client, aid, "Original")
    cid = c["id"]
    client.patch(f"/api/articles/{aid}/comments/{cid}", json={"resolved": True})
    comments = client.get(f"/api/articles/{aid}/comments").json()["comments"]
    resolved = [x for x in comments if x["id"] == cid]
    assert resolved[0]["resolved"] is True


def test_update_comment_unknown(client):
    aid = _create_article(client)
    r = client.patch(f"/api/articles/{aid}/comments/not-a-cid", json={"resolved": True})
    assert r.status_code == 404


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_comment_204(client):
    aid = _create_article(client)
    c = _add_comment(client, aid, "Delete me")
    cid = c["id"]
    r = client.delete(f"/api/articles/{aid}/comments/{cid}")
    assert r.status_code == 204


def test_delete_comment_removes_from_list(client):
    aid = _create_article(client)
    c = _add_comment(client, aid, "To be removed")
    cid = c["id"]
    client.delete(f"/api/articles/{aid}/comments/{cid}")
    comments = client.get(f"/api/articles/{aid}/comments").json()["comments"]
    ids = [x["id"] for x in comments]
    assert cid not in ids


def test_delete_comment_unknown_404(client):
    aid = _create_article(client)
    r = client.delete(f"/api/articles/{aid}/comments/ghost-cid")
    assert r.status_code == 404
