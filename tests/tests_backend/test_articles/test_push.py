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
