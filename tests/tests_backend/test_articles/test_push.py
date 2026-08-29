"""Tests for POST /api/articles/:id/push."""

import pytest
from fastapi.testclient import TestClient
from backend.services.push import PushPlatformResult


class TestPushArticle:

    @pytest.mark.integration
    def test_returns_202_with_job_id(self, client: TestClient):
        r = client.post("/api/articles/art_001/push", json={})
        assert r.status_code == 202
        body = r.json()
        assert "jobId" in body
        assert body["status"] == "queued"

    def test_push_unknown_article_returns_404(self, client: TestClient):
        r = client.post("/api/articles/art_unknown/push", json={})
        assert r.status_code == 404

    def test_repeated_idempotency_key_returns_the_same_job(self, client: TestClient):
        headers = {"Idempotency-Key": "overview-push-art-001"}
        first = client.post("/api/articles/art_001/push", json={}, headers=headers)
        second = client.post("/api/articles/art_001/push", json={}, headers=headers)

        assert first.status_code == second.status_code == 202
        assert second.json()["jobId"] == first.json()["jobId"]
        assert second.json()["pollUrl"] == f"/api/jobs/{first.json()['jobId']}"

    @pytest.mark.integration
    def test_destinations_updated_after_push(self, client: TestClient, run_jobs):
        client.post("/api/articles/art_001/push", json={})
        run_jobs()
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == "art_001")
        # After push all destinations should be draft (in-memory backend resolves immediately)
        for dest in item["destinations"].values():
            assert dest["status"] == "draft"

    @pytest.mark.integration
    def test_job_retrievable_after_push(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/push", json={}).json()["jobId"]
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        assert r.json()["jobId"] == job_id
        assert r.json()["type"] == "push"

    @pytest.mark.integration
    def test_push_job_result_contains_per_platform_status(self, client: TestClient, run_jobs):
        job_id = client.post("/api/articles/art_001/push", json={}).json()["jobId"]
        run_jobs()
        job = client.get(f"/api/jobs/{job_id}").json()
        assert set(job["result"].keys()) == {"medium", "hashnode", "devto"}
        assert job["result"]["devto"]["status"] == "draft"

    def test_push_persists_platform_url_from_orchestrator(
        self, client: TestClient, monkeypatch, run_jobs,
    ):
        from backend.workers import handlers

        def fake_push(article, platforms, *, get_connection_token):
            return {
                "medium":
                    PushPlatformResult(
                        platform="medium",
                        success=True,
                        status="draft",
                        label="Draft",
                        url="https://medium.example/draft",
                    ),
                "hashnode":
                    PushPlatformResult(
                        platform="hashnode",
                        success=True,
                        status="draft",
                        label="Draft",
                        url="https://hashnode.example/preview/123",
                        draft_id="h-123",
                    ),
                "devto":
                    PushPlatformResult(
                        platform="devto",
                        success=True,
                        status="draft",
                        label="Draft",
                        url="https://dev.to/example/draft",
                        draft_id="42",
                    ),
            }

        monkeypatch.setattr(handlers, "push_article_to_platforms", fake_push)

        client.post("/api/articles/art_001/push", json={})
        run_jobs()
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == "art_001")
        assert item["destinations"]["hashnode"]["url"] == "https://hashnode.example/preview/123"
        assert item["destinations"]["devto"]["url"] == "https://dev.to/example/draft"


def test_devto_retry_updates_linked_article_instead_of_creating(monkeypatch):
    from backend.services import push

    article = {
        "id": "art_test",
        "title": "Retryable",
        "body": "# Retryable\n\nBody",
        "destinations": {"devto": {"draft_id": "42", "url": "https://dev.to/test"}},
    }
    calls = []

    class FakeClient:
        def __init__(self, _token):
            pass

        def update_article(self, article_id, payload):
            calls.append((article_id, payload.title))
            return type("Result", (), {
                "article_id": article_id,
                "url": "https://dev.to/test",
            })()

        def publish_article(self, _payload):
            raise AssertionError("retry created a duplicate article")

    monkeypatch.setattr(push, "DevToClient", FakeClient)
    result = push.push_article_to_platforms(
        article, ["devto"], get_connection_token=lambda _: "secret",
    )["devto"]

    assert calls == [(42, "Retryable")]
    assert result.draft_id == "42"
