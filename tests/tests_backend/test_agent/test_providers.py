"""
Tests for GET /api/agent/providers and GET /api/agent/platforms.
"""
import pytest


def test_providers_returns_list(client):
    r = client.get("/api/agent/providers")
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    assert isinstance(body["providers"], list)


def test_providers_shape(client):
    r = client.get("/api/agent/providers")
    providers = r.json()["providers"]
    for p in providers:
        assert "id" in p
        assert "label" in p
        assert "configured" in p
        assert isinstance(p["configured"], bool)


def test_platforms_returns_list(client):
    r = client.get("/api/agent/platforms")
    assert r.status_code == 200
    body = r.json()
    assert "platforms" in body
    assert isinstance(body["platforms"], list)


def test_platforms_shape(client):
    r = client.get("/api/agent/platforms")
    platforms = r.json()["platforms"]
    for p in platforms:
        assert "id" in p
        assert "label" in p
        # platforms have either 'connected' or 'status' field
        assert "connected" in p or "status" in p


def test_providers_known_ids_present(client):
    """At least claude or codex should appear in providers."""
    r = client.get("/api/agent/providers")
    ids = {p["id"] for p in r.json()["providers"]}
    assert ids & {"claude", "codex", "openai"}, f"Expected a known AI provider id, got {ids}"


def test_platforms_known_ids_present(client):
    """Medium, hashnode, or devto should appear."""
    r = client.get("/api/agent/platforms")
    ids = {p["id"] for p in r.json()["platforms"]}
    assert ids & {"medium", "hashnode", "devto"}, f"Expected a known blog platform id, got {ids}"
