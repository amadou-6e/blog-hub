"""
Tests for GET /api/connections/{conn_id}/drafts
and GET /api/connections/{conn_id}/drafts/{draft_id}.
"""
import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

_KNOWN_PLATFORMS = ["medium", "hashnode", "devto"]


def _save_connection(client, conn_id: str, token: str = "tok_test") -> None:
    r = client.put(f"/api/connections/{conn_id}", json={"token": token})
    assert r.status_code == 200, r.text


# ── GET /connections/{id}/drafts — without token ──────────────────────────────

def test_list_drafts_no_token_medium(client):
    """Endpoint returns 404 when no token is stored for the platform."""
    r = client.get("/api/connections/medium/drafts")
    assert r.status_code == 404


def test_list_drafts_with_token_medium(client):
    """Medium returns mock data when a token is stored."""
    _save_connection(client, "medium")
    r = client.get("/api/connections/medium/drafts")
    assert r.status_code == 200
    body = r.json()
    assert "drafts" in body
    assert isinstance(body["drafts"], list)
    assert len(body["drafts"]) > 0


def test_list_drafts_unknown_platform(client):
    r = client.get("/api/connections/bogus/drafts")
    assert r.status_code == 404


# ── GET /connections/{id}/drafts — pagination ────────────────────────────────

def test_list_drafts_pagination_defaults(client):
    _save_connection(client, "medium")
    r = client.get("/api/connections/medium/drafts")
    body = r.json()
    assert "drafts" in body
    # Default page size should be ≤ 50
    assert len(body["drafts"]) <= 50


def test_list_drafts_page_param(client):
    _save_connection(client, "medium")
    r = client.get("/api/connections/medium/drafts?page=1&per_page=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body["drafts"]) <= 2


def test_list_drafts_page_size_zero_rejected(client):
    _save_connection(client, "medium")
    r = client.get("/api/connections/medium/drafts?per_page=0")
    # Either 200 (clamped) or 422 validation error; must not 500
    assert r.status_code in (200, 400, 422)


# ── Draft object shape ────────────────────────────────────────────────────────

def test_draft_shape_medium(client):
    _save_connection(client, "medium")
    r = client.get("/api/connections/medium/drafts")
    drafts = r.json()["drafts"]
    assert drafts, "Expected at least one mock draft for medium"
    d = drafts[0]
    assert "id" in d
    assert "title" in d
    assert "snippet" in d
    assert "status" in d
    assert "updated_at" in d


# ── GET /connections/{id}/drafts/{draft_id} ──────────────────────────────────

def test_get_draft_by_id_medium(client):
    """Fetch the first medium mock draft by ID."""
    _save_connection(client, "medium")
    drafts = client.get("/api/connections/medium/drafts").json()["drafts"]
    assert drafts
    first_id = drafts[0]["id"]
    r = client.get(f"/api/connections/medium/drafts/{first_id}")
    assert r.status_code == 200
    article = r.json()
    assert article["id"] == first_id
    assert "title" in article


def test_get_draft_not_found(client):
    r = client.get("/api/connections/medium/drafts/nonexistent-id-xyz")
    assert r.status_code == 404


def test_get_draft_unknown_platform(client):
    r = client.get("/api/connections/bogus/drafts/some-id")
    assert r.status_code == 404


# ── Status filter ─────────────────────────────────────────────────────────────

def test_list_drafts_status_filter_draft(client):
    _save_connection(client, "medium")
    r = client.get("/api/connections/medium/drafts?status=draft")
    # status param not supported — endpoint ignores it and returns all; must not 500
    assert r.status_code in (200, 422)


def test_list_drafts_status_filter_published(client):
    _save_connection(client, "medium")
    r = client.get("/api/connections/medium/drafts?status=published")
    assert r.status_code in (200, 422)
