"""
Smoke tests: confirm every documented API path returns a known status code
and that the OpenAPI schema loads without error.
"""
import pytest


# ── Schema ────────────────────────────────────────────────────────────────────

def test_openapi_json_returns_200(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200


def test_openapi_json_has_paths(client):
    schema = client.get("/openapi.json").json()
    assert "paths" in schema
    assert len(schema["paths"]) > 0


def test_openapi_info(client):
    info = client.get("/openapi.json").json().get("info", {})
    assert "title" in info
    assert "version" in info


# ── Core paths smoke test ─────────────────────────────────────────────────────

def test_articles_endpoint_exists(client):
    r = client.get("/api/articles")
    assert r.status_code == 200


def test_connections_endpoint_exists(client):
    r = client.get("/api/connections")
    assert r.status_code == 200


def test_agent_providers_endpoint_exists(client):
    r = client.get("/api/agent/providers")
    assert r.status_code == 200


def test_agent_platforms_endpoint_exists(client):
    r = client.get("/api/agent/platforms")
    assert r.status_code == 200


def test_platforms_endpoint_exists(client):
    r = client.get("/api/platforms")
    assert r.status_code == 200


# ── Method not allowed ────────────────────────────────────────────────────────

def test_delete_articles_without_ids_rejected(client):
    """DELETE /api/articles requires a body with ids."""
    r = client.request("DELETE", "/api/articles", json={})
    assert r.status_code in (400, 422)


def test_post_connections_not_allowed(client):
    """POST /api/connections is not defined; expect 404 or 405."""
    r = client.post("/api/connections", json={})
    assert r.status_code in (404, 405, 422)
