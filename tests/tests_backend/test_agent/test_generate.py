"""
Tests for POST /api/agent/generate (async article generation job).
"""
import pytest


def _create_article(client) -> str:
    r = client.post("/api/articles",
                    json={
                        "title": "My gen article",
                        "content": "placeholder " * 200,
                    })
    assert r.status_code == 201
    return r.json()["id"]


# ── Field validation ───────────────────────────────────────────────────────────


def test_generate_missing_body(client):
    r = client.post("/api/agent/generate")
    # Must return 422 (validation error) not 500
    assert r.status_code == 422


def test_generate_empty_prompt_rejected(client):
    r = client.post("/api/agent/generate",
                    json={
                        "prompt": "",
                        "skill": "deep-dive",
                        "provider": "claude",
                        "word_count": 1000,
                        "destinations": ["medium"],
                    })
    assert r.status_code in (400, 422)


def test_generate_unknown_skill_rejected(client):
    r = client.post("/api/agent/generate",
                    json={
                        "prompt": "Write about Redis",
                        "skill": "not_a_real_skill",
                        "provider": "claude",
                        "word_count": 1000,
                        "destinations": ["medium"],
                    })
    assert r.status_code in (400, 422)


def test_generate_unknown_provider_rejected(client):
    r = client.post("/api/agent/generate",
                    json={
                        "prompt": "Write about Redis",
                        "skill": "deep-dive",
                        "provider": "gpt-99",
                        "word_count": 1000,
                        "destinations": ["medium"],
                    })
    assert r.status_code in (400, 422)


# ── Accepted response ─────────────────────────────────────────────────────────


def test_generate_valid_request_accepted(client):
    r = client.post("/api/agent/generate",
                    json={
                        "prompt": "Write about zero-downtime Postgres migrations",
                        "skill": "deep-dive",
                        "provider": "claude",
                        "word_count": 1500,
                        "destinations": ["medium"],
                    })
    # 202 accepted (async) or 400/422 if no provider configured — never 500
    assert r.status_code in (202, 400, 422, 503)


def test_generate_response_has_job_id(client):
    r = client.post("/api/agent/generate",
                    json={
                        "prompt": "A tutorial about Docker networking",
                        "skill": "tutorial",
                        "provider": "claude",
                        "word_count": 1200,
                        "destinations": ["medium", "hashnode"],
                    })
    if r.status_code == 202:
        body = r.json()
        assert "job_id" in body or "id" in body
