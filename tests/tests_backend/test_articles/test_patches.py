"""
Tests for /api/articles/{article_id}/patches endpoints.
"""
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_article(client) -> str:
    r = client.post("/api/articles", json={
        "title": "Patch Article",
        "content": "B " * 300,
    })
    assert r.status_code == 201
    return r.json()["id"]


def _add_comment(client, article_id: str, text: str = "Fix this") -> str:
    r = client.post(f"/api/articles/{article_id}/comments", json={"text": text})
    assert r.status_code == 201
    return r.json()["id"]


def _add_patch_via_regenerate(client, article_id: str, comment_id: str) -> dict:
    """Force a patch by adding an unresolved comment and regenerating."""
    r = client.post(f"/api/articles/{article_id}/regenerate")
    assert r.status_code == 202
    patches = client.get(f"/api/articles/{article_id}/patches").json()
    return patches[0] if patches else None


# ── list ──────────────────────────────────────────────────────────────────────

def test_list_patches_empty(client):
    aid = _create_article(client)
    r = client.get(f"/api/articles/{aid}/patches")
    assert r.status_code == 200
    assert r.json()["patches"] == []


def test_list_patches_unknown_article(client):
    r = client.get("/api/articles/no-such/patches")
    assert r.status_code == 404


def test_list_patches_after_regenerate(client):
    aid = _create_article(client)
    _add_comment(client, aid, "Review me")
    client.post(f"/api/articles/{aid}/regenerate")
    r = client.get(f"/api/articles/{aid}/patches")
    assert r.status_code == 200
    patches = r.json()["patches"]
    assert len(patches) == 1
    assert "id" in patches[0]
    assert "label" in patches[0]


def test_list_patches_state_default_pending(client):
    aid = _create_article(client)
    _add_comment(client, aid, "Needs improvement")
    client.post(f"/api/articles/{aid}/regenerate")
    patches = client.get(f"/api/articles/{aid}/patches").json()["patches"]
    assert patches[0]["state"] == "pending"


# ── accept ────────────────────────────────────────────────────────────────────

def test_accept_patch_200(client):
    aid = _create_article(client)
    _add_comment(client, aid, "Fix this paragraph")
    client.post(f"/api/articles/{aid}/regenerate")
    patches = client.get(f"/api/articles/{aid}/patches").json()["patches"]
    pid = patches[0]["id"]

    r = client.post(f"/api/articles/{aid}/patches/{pid}/accept")
    assert r.status_code == 200
    assert r.json()["state"] == "accepted"


def test_accept_patch_persists(client):
    aid = _create_article(client)
    _add_comment(client, aid, "Please revise")
    client.post(f"/api/articles/{aid}/regenerate")
    patches = client.get(f"/api/articles/{aid}/patches").json()["patches"]
    pid = patches[0]["id"]

    client.post(f"/api/articles/{aid}/patches/{pid}/accept")
    updated = client.get(f"/api/articles/{aid}/patches").json()["patches"]
    assert updated[0]["state"] == "accepted"


def test_accept_unknown_patch_404(client):
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/patches/ghost-pid/accept")
    assert r.status_code == 404


# ── reject ────────────────────────────────────────────────────────────────────

def test_reject_patch_200(client):
    aid = _create_article(client)
    _add_comment(client, aid, "I disagree with this part")
    client.post(f"/api/articles/{aid}/regenerate")
    patches = client.get(f"/api/articles/{aid}/patches").json()["patches"]
    pid = patches[0]["id"]

    r = client.post(f"/api/articles/{aid}/patches/{pid}/reject")
    assert r.status_code == 200
    assert r.json()["state"] == "rejected"


def test_reject_unknown_patch_404(client):
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/patches/no-patch/reject")
    assert r.status_code == 404


# ── regenerate ────────────────────────────────────────────────────────────────

def test_regenerate_202(client):
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/regenerate")
    assert r.status_code == 202


def test_regenerate_unknown_article(client):
    r = client.post("/api/articles/no-article/regenerate")
    assert r.status_code == 404


def test_regenerate_creates_patch_per_open_comment(client):
    aid = _create_article(client)
    _add_comment(client, aid, "Comment one")
    _add_comment(client, aid, "Comment two")
    client.post(f"/api/articles/{aid}/regenerate")
    patches = client.get(f"/api/articles/{aid}/patches").json()["patches"]
    assert len(patches) == 2


def test_regenerate_skips_resolved_comments(client):
    aid = _create_article(client)
    cid = _add_comment(client, aid, "Already handled")
    # Resolve the comment
    client.patch(f"/api/articles/{aid}/comments/{cid}", json={"resolved": True})
    client.post(f"/api/articles/{aid}/regenerate")
    patches = client.get(f"/api/articles/{aid}/patches").json()["patches"]
    assert len(patches) == 0
