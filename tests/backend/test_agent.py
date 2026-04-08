"""
pytest tests for /api/agent — providers, platforms, generate.

All tests use the TestClient (sync) and monkeypatch to avoid real CLI runner
calls. FastAPI's TestClient runs BackgroundTasks synchronously, so
post-generation assertions work without any special handling.
"""

import pytest
from fastapi.testclient import TestClient

import backend.store as store
import backend.services.cli_runner as cli_runner
import backend.services.agent_service as agent_service

# ─── GET /api/agent/providers ─────────────────────────────────────────────────


class TestGetProviders:

    def test_response_shape(self, client: TestClient):
        r = client.get("/api/agent/providers")
        assert r.status_code == 200
        body = r.json()
        assert "providers" in body
        for p in body["providers"]:
            assert "id" in p
            assert "label" in p
            assert "configured" in p

    def test_returns_two_providers(self, client: TestClient):
        providers = client.get("/api/agent/providers").json()["providers"]
        ids = {p["id"] for p in providers}
        assert ids == {"claude", "codex"}

    def test_no_connections_both_not_configured(self, client: TestClient, monkeypatch):
        # Bypass env-var-based secret detection so we see the true "no creds" state
        monkeypatch.setattr(store, "list_connections", lambda: [])
        providers = client.get("/api/agent/providers").json()["providers"]
        for p in providers:
            assert p["configured"] is False

    def test_connected_anthropic_returns_configured_true(self, client: TestClient):
        store.save_connection("anthropic", token="test-token", status="connected")
        providers = {p["id"]: p for p in client.get("/api/agent/providers").json()["providers"]}
        assert providers["claude"]["configured"] is True

    def test_connected_openai_returns_configured_true(self, client: TestClient):
        store.save_connection("openai", token="test-token", status="connected")
        providers = {p["id"]: p for p in client.get("/api/agent/providers").json()["providers"]}
        assert providers["codex"]["configured"] is True

    def test_disconnected_keeps_configured_false(self, client: TestClient):
        store.save_connection("anthropic", token="x", status="disconnected")
        providers = {p["id"]: p for p in client.get("/api/agent/providers").json()["providers"]}
        assert providers["claude"]["configured"] is False


# ─── GET /api/agent/platforms ─────────────────────────────────────────────────


class TestGetAgentPlatforms:

    def test_response_shape(self, client: TestClient):
        r = client.get("/api/agent/platforms")
        assert r.status_code == 200
        body = r.json()
        assert "platforms" in body
        for p in body["platforms"]:
            assert "id" in p
            assert "label" in p
            assert "status" in p
            assert "session_expires_at" in p

    def test_returns_three_blog_platforms(self, client: TestClient):
        platforms = client.get("/api/agent/platforms").json()["platforms"]
        ids = {p["id"] for p in platforms}
        assert ids == {"medium", "hashnode", "devto"}

    def test_all_status_values_are_valid(self, client: TestClient):
        platforms = client.get("/api/agent/platforms").json()["platforms"]
        valid = {"connected", "expired", "not_configured"}
        for p in platforms:
            assert p["status"] in valid, f"Unexpected status {p['status']} for {p['id']}"

    def test_session_expires_at_always_null(self, client: TestClient):
        platforms = client.get("/api/agent/platforms").json()["platforms"]
        for p in platforms:
            assert p["session_expires_at"] is None

    def test_no_connections_all_not_configured(self, client: TestClient, monkeypatch):
        # Bypass env-var-based secret detection by stubbing list_connections
        monkeypatch.setattr(store, "list_connections", lambda: [])
        platforms = {p["id"]: p for p in client.get("/api/agent/platforms").json()["platforms"]}
        for pid in ("medium", "hashnode", "devto"):
            assert platforms[pid]["status"] == "not_configured"

    def test_connected_medium_shows_connected(self, client: TestClient):
        store.save_connection("medium", token="tok", status="connected")
        platforms = {p["id"]: p for p in client.get("/api/agent/platforms").json()["platforms"]}
        assert platforms["medium"]["status"] == "connected"

    def test_does_not_include_ai_providers(self, client: TestClient):
        platforms = client.get("/api/agent/platforms").json()["platforms"]
        ids = {p["id"] for p in platforms}
        assert "anthropic" not in ids
        assert "openai" not in ids


# ─── POST /api/agent/generate ─────────────────────────────────────────────────


def _seed_provider(client: TestClient) -> None:
    """Save a connected anthropic credential so generate requests pass the provider check."""
    store.save_connection("anthropic", token="test-anthropic-token", status="connected")


def _valid_body(**overrides) -> dict:
    base = {
        "brief": "A practical guide to zero-downtime Postgres migrations using pg_repack.",
        "skill": "tutorial",
        "provider": "claude",
        "wordCount": 1500,
        "destinations": ["medium"],
    }
    base.update(overrides)
    return base


def _mock_runner_success(monkeypatch,
                         markdown: str = "# Generated Title\n\nArticle body text here."):
    monkeypatch.setattr(
        cli_runner,
        "run_task",
        lambda **kwargs: {
            "exit_code": 0,
            "stdout": markdown,
            "stderr": "",
            "truncated": False
        },
    )


def _mock_runner_unavailable(monkeypatch):

    def _raise(**kwargs):
        raise cli_runner.RunnerUnavailable("CLI runner not reachable")

    monkeypatch.setattr(cli_runner, "run_task", _raise)


def _mock_runner_fail(monkeypatch, stderr: str = "code generation failed"):
    monkeypatch.setattr(
        cli_runner,
        "run_task",
        lambda **kwargs: {
            "exit_code": 1,
            "stdout": "",
            "stderr": stderr,
            "truncated": False
        },
    )


class TestPostGenerate:

    def test_returns_202(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body())
        assert r.status_code == 202

    def test_response_shape(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        body = client.post("/api/agent/generate", json=_valid_body()).json()
        assert "jobId" in body
        assert "articleId" in body
        assert body["status"] == "running"

    def test_article_created_in_store(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        article_id = client.post("/api/agent/generate", json=_valid_body()).json()["articleId"]
        assert store.get_article(article_id) is not None

    def test_background_task_writes_body(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch, markdown="# My Article\n\nFull article body content.")
        r = client.post("/api/agent/generate", json=_valid_body())
        article_id = r.json()["articleId"]
        article = store.get_article(article_id)
        assert "Full article body content" in article["body"]

    def test_background_task_extracts_title(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch, markdown="# Extracted Title\n\nBody content.")
        r = client.post("/api/agent/generate", json=_valid_body())
        article_id = r.json()["articleId"]
        article = store.get_article(article_id)
        assert article["title"] == "Extracted Title"

    def test_background_task_sets_job_done(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body())
        body = r.json()
        job = store.get_job(body["jobId"])
        assert job["status"] == "done"

    def test_runner_unavailable_sets_job_error(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_unavailable(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body())
        job_id = r.json()["jobId"]
        job = store.get_job(job_id)
        assert job["status"] == "error"
        assert job["error"] is not None
        assert len(job["error"]) > 0

    def test_runner_nonzero_exit_sets_job_error(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_fail(monkeypatch, stderr="generation aborted")
        r = client.post("/api/agent/generate", json=_valid_body())
        job_id = r.json()["jobId"]
        job = store.get_job(job_id)
        assert job["status"] == "error"
        assert "generation aborted" in job["error"]

    def test_provider_not_configured_returns_400(self, client: TestClient, monkeypatch):
        # Bypass env-var-based secret detection so the router sees no configured provider
        monkeypatch.setattr(
            store, "list_connections", lambda: [
                {
                    "id": "anthropic",
                    "label": "Claude",
                    "type": "ai",
                    "auth_method": "token",
                    "status": "disconnected",
                    "username": None,
                    "connected_at": None,
                    "error_message": None
                },
                {
                    "id": "openai",
                    "label": "OpenAI",
                    "type": "ai",
                    "auth_method": "token",
                    "status": "disconnected",
                    "username": None,
                    "connected_at": None,
                    "error_message": None
                },
            ])
        _mock_runner_success(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body())
        assert r.status_code == 400

    def test_unknown_provider_returns_422(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body(provider="gpt5"))
        assert r.status_code == 422

    def test_brief_too_short_returns_422(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body(brief="too short"))
        assert r.status_code == 422

    def test_codex_provider_uses_openai_runner(self, client: TestClient, monkeypatch):
        store.save_connection("openai", token="tok", status="connected")
        captured = {}

        def fake_run(**kwargs):
            captured["provider"] = kwargs.get("provider")
            return {"exit_code": 0, "stdout": "# T\n\nBody", "stderr": "", "truncated": False}

        monkeypatch.setattr(cli_runner, "run_task", fake_run)
        client.post("/api/agent/generate", json=_valid_body(provider="codex"))
        assert captured.get("provider") == "openai"

    def test_destinations_stored_as_pending(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body(destinations=["medium"]))
        article_id = r.json()["articleId"]
        article = store.get_article(article_id)
        assert article["destinations"]["medium"]["status"] == "pending"

    def test_context_text_appended_to_prompt(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        captured = {}

        def fake_run(**kwargs):
            captured["article_md"] = kwargs.get("article_md", "")
            return {"exit_code": 0, "stdout": "# T\n\nBody", "stderr": "", "truncated": False}

        monkeypatch.setattr(cli_runner, "run_task", fake_run)
        client.post("/api/agent/generate", json=_valid_body(contextText="extra context here"))
        assert "extra context here" in captured.get("article_md", "")

    def test_job_exists_in_store_after_202(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body())
        job_id = r.json()["jobId"]
        job = store.get_job(job_id)
        assert job is not None
        assert job["article_id"] == r.json()["articleId"]
