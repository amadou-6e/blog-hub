"""Tests for POST /api/agent/generate."""

import pytest
from fastapi.testclient import TestClient

import backend.store as store
import backend.services.cli_runner as cli_runner
from backend.store.backends.sqlite import SQLiteStore

_UID = SQLiteStore.SEED_USER_ID

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _seed_provider(client: TestClient) -> None:
    """Save a connected anthropic credential so generate requests pass the provider check."""
    store.save_connection(_UID, "anthropic", token="test-anthropic-token", status="connected")


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


# ─── Tests ────────────────────────────────────────────────────────────────────


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
        assert body["status"] == "queued"

    def test_article_created_in_store(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        article_id = client.post("/api/agent/generate", json=_valid_body()).json()["articleId"]
        assert store.get_article(_UID, article_id) is not None

    def test_worker_writes_body(self, client: TestClient, monkeypatch, run_jobs):
        _seed_provider(client)
        _mock_runner_success(monkeypatch, markdown="# My Article\n\nFull article body content.")
        r = client.post("/api/agent/generate", json=_valid_body())
        run_jobs()
        article_id = r.json()["articleId"]
        article = store.get_article(_UID, article_id)
        assert "Full article body content" in article["body"]

    def test_worker_extracts_title(self, client: TestClient, monkeypatch, run_jobs):
        _seed_provider(client)
        _mock_runner_success(monkeypatch, markdown="# Extracted Title\n\nBody content.")
        r = client.post("/api/agent/generate", json=_valid_body())
        run_jobs()
        article_id = r.json()["articleId"]
        article = store.get_article(_UID, article_id)
        assert article["title"] == "Extracted Title"

    def test_worker_sets_job_completed(self, client: TestClient, monkeypatch, run_jobs):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body())
        run_jobs()
        job = store.get_job(_UID, r.json()["jobId"])
        assert job["status"] == "completed"

    def test_runner_unavailable_sets_job_failed(
        self, client: TestClient, monkeypatch, run_jobs,
    ):
        _seed_provider(client)
        _mock_runner_unavailable(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body())
        run_jobs(force_retries=True)
        job = store.get_job(_UID, r.json()["jobId"])
        assert job["status"] == "failed"
        assert job["error"] is not None
        assert len(job["error"]) > 0

    def test_runner_nonzero_exit_sets_job_failed(
        self, client: TestClient, monkeypatch, run_jobs,
    ):
        _seed_provider(client)
        _mock_runner_fail(monkeypatch, stderr="generation aborted")
        r = client.post("/api/agent/generate", json=_valid_body())
        run_jobs(force_retries=True)
        job = store.get_job(_UID, r.json()["jobId"])
        assert job["status"] == "failed"
        assert "generation aborted" in job["error"]

    def test_provider_not_configured_returns_400(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(
            store, "list_connections", lambda user_id: [
                {
                    "id": "anthropic",
                    "label": "Claude",
                    "type": "ai",
                    "auth_method": "token",
                    "status": "disconnected",
                    "username": None,
                    "connected_at": None,
                    "error_message": None,
                },
                {
                    "id": "openai",
                    "label": "OpenAI",
                    "type": "ai",
                    "auth_method": "token",
                    "status": "disconnected",
                    "username": None,
                    "connected_at": None,
                    "error_message": None,
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

    def test_codex_provider_uses_openai_runner(
        self, client: TestClient, monkeypatch, run_jobs,
    ):
        store.save_connection(_UID, "openai", token="tok", status="connected")
        captured = {}

        def fake_run(**kwargs):
            captured["provider"] = kwargs.get("provider")
            return {"exit_code": 0, "stdout": "# T\n\nBody", "stderr": "", "truncated": False}

        monkeypatch.setattr(cli_runner, "run_task", fake_run)
        client.post("/api/agent/generate", json=_valid_body(provider="codex"))
        run_jobs()
        assert captured.get("provider") == "openai"

    def test_destinations_stored_as_pending(
        self, client: TestClient, monkeypatch, run_jobs,
    ):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body(destinations=["medium"]))
        run_jobs()
        article_id = r.json()["articleId"]
        article = store.get_article(_UID, article_id)
        assert article["destinations"]["medium"]["status"] == "pending"

    def test_context_text_appended_to_prompt(
        self, client: TestClient, monkeypatch, run_jobs,
    ):
        _seed_provider(client)
        captured = {}

        def fake_run(**kwargs):
            captured["article_md"] = kwargs.get("article_md", "")
            return {"exit_code": 0, "stdout": "# T\n\nBody", "stderr": "", "truncated": False}

        monkeypatch.setattr(cli_runner, "run_task", fake_run)
        client.post("/api/agent/generate", json=_valid_body(contextText="extra context here"))
        run_jobs()
        assert "extra context here" in captured.get("article_md", "")

    def test_job_exists_in_store_after_202(self, client: TestClient, monkeypatch):
        _seed_provider(client)
        _mock_runner_success(monkeypatch)
        r = client.post("/api/agent/generate", json=_valid_body())
        job_id = r.json()["jobId"]
        job = store.get_job(_UID, job_id)
        assert job is not None
        assert job["article_id"] == r.json()["articleId"]
