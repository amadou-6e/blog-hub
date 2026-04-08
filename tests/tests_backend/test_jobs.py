"""
Tests for /api/jobs — backend/routers/jobs.py
"""

import pytest
from fastapi.testclient import TestClient

# ─── GET /api/jobs/:jobId ─────────────────────────────────────────────────────


class TestJobs:

    def test_unknown_job_returns_404(self, client: TestClient):
        r = client.get("/api/jobs/job_does_not_exist")
        assert r.status_code == 404

    @pytest.mark.integration
    def test_job_shape(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/push", json={}).json()["jobId"]
        job = client.get(f"/api/jobs/{job_id}").json()
        assert set(job.keys()) >= {"jobId", "type", "status", "articleId"}

    @pytest.mark.integration
    def test_push_job_type(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/push", json={}).json()["jobId"]
        assert client.get(f"/api/jobs/{job_id}").json()["type"] == "push"

    def test_inspect_job_type(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/inspect").json()["jobId"]
        assert client.get(f"/api/jobs/{job_id}").json()["type"] == "inspect"
