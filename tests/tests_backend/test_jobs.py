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


class TestSyncSchedules:

    def test_create_list_and_delete_schedule(self, client: TestClient):
        created = client.put(
            "/api/jobs/sync-schedules",
            json={"platform": "medium", "intervalSeconds": 900},
        )
        assert created.status_code == 200
        assert created.json()["platform"] == "medium"
        assert created.json()["interval_seconds"] == 900

        schedules = client.get("/api/jobs/sync-schedules").json()["schedules"]
        assert [item["platform"] for item in schedules] == ["medium"]

        assert client.delete("/api/jobs/sync-schedules/medium").status_code == 204
        assert client.get("/api/jobs/sync-schedules").json()["schedules"] == []

    def test_schedule_rejects_unsupported_platform(self, client: TestClient):
        response = client.put(
            "/api/jobs/sync-schedules",
            json={"platform": "devto", "intervalSeconds": 900},
        )
        assert response.status_code == 422

    def test_schedule_enforces_minimum_interval(self, client: TestClient):
        response = client.put(
            "/api/jobs/sync-schedules",
            json={"platform": "hashnode", "intervalSeconds": 60},
        )
        assert response.status_code == 422
