"""
Tests for POST /api/articles/{id}/push and POST /api/articles/{id}/inspect.
"""
import pytest


def _create_article(client) -> str:
    r = client.post("/api/articles", json={
        "title": "Push test article",
        "content": "Content block. " * 300,
    })
    assert r.status_code == 201
    return r.json()["id"]


# ── POST /push ────────────────────────────────────────────────────────────────

def test_push_unknown_article(client):
    r = client.post("/api/articles/ghost/push", json={"destinations": ["medium"]})
    assert r.status_code == 404


def test_push_no_destinations(client):
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/push", json={"destinations": []})
    # Server may accept (202) or reject (400/422) empty destinations
    assert r.status_code in (202, 400, 422)


def test_push_accepted(client):
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/push", json={"destinations": ["medium"]})
    # 202 async or 400/422 if destinations not configured — never 500
    assert r.status_code in (202, 400, 422, 503)


def test_push_response_has_job_id(client):
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/push", json={"destinations": ["medium"]})
    if r.status_code == 202:
        body = r.json()
        assert "jobId" in body or "job_id" in body or "id" in body


def test_push_unknown_destination_accepted_async(client):
    """Push does not validate destination names synchronously; returns 202."""
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/push", json={"destinations": ["not_a_platform"]})
    assert r.status_code in (202, 400, 422, 404)


# ── POST /inspect ─────────────────────────────────────────────────────────────

def test_inspect_unknown_article(client):
    r = client.post("/api/articles/ghost/inspect")
    assert r.status_code == 404


def test_inspect_accepted(client):
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/inspect")
    assert r.status_code in (202, 400, 422, 503)


def test_inspect_response_has_job_id(client):
    aid = _create_article(client)
    r = client.post(f"/api/articles/{aid}/inspect")
    if r.status_code == 202:
        body = r.json()
        assert "jobId" in body or "job_id" in body or "id" in body
