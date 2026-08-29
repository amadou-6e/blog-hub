"""
Tests for /api/jobs — backend/routers/jobs.py
"""

import pytest
from fastapi.testclient import TestClient
import backend.store as store

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

    def test_article_active_jobs_are_discoverable(self, client: TestClient):
        target = client.post(
            "/api/articles/art_001/inspect",
            headers={"Idempotency-Key": "recover-inspection"},
        ).json()
        client.post(
            "/api/articles/art_002/inspect",
            headers={"Idempotency-Key": "other-inspection"},
        )

        response = client.get(
            "/api/jobs", params={"article_id": "art_001", "active": True}
        )

        assert response.status_code == 200
        assert [job["jobId"] for job in response.json()["jobs"]] == [target["jobId"]]
        assert response.json()["jobs"][0]["operation"] == "inspect"

    def test_job_response_drives_polling_and_timeout(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/inspect").json()["jobId"]
        job = client.get(f"/api/jobs/{job_id}").json()

        assert job["pollUrl"] == f"/api/jobs/{job_id}"
        assert job["pollAfterMs"] == 2000
        assert job["timeoutSeconds"] == 60
        assert job["retryable"] is False

    def test_cancel_and_idempotent_retry_are_durable(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/inspect").json()["jobId"]
        canceled = client.post(f"/api/jobs/{job_id}/cancel")
        assert canceled.json()["status"] == "canceled"
        assert canceled.json()["retryable"] is True

        assert client.post(f"/api/jobs/{job_id}/retry").status_code == 400
        headers = {"Idempotency-Key": "retry-canceled-inspection"}
        first = client.post(f"/api/jobs/{job_id}/retry", headers=headers)
        second = client.post(f"/api/jobs/{job_id}/retry", headers=headers)

        assert first.status_code == second.status_code == 202
        assert first.json()["status"] == "queued"
        assert second.json()["jobId"] == job_id

    def test_worker_backoff_is_exposed_as_retrying(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/inspect").json()["jobId"]
        claimed = store._backend.claim_job("test-worker", queues=("default",))
        assert claimed["job_id"] == job_id
        store._backend.fail_job(
            job_id, "test-worker", "temporary outage", backoff_base_seconds=60
        )

        response = client.get(f"/api/jobs/{job_id}")
        assert response.json()["status"] == "retrying"
        assert response.json()["error"] == "temporary outage"

    def test_parked_job_is_exposed_as_needing_explicit_retry(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/inspect").json()["jobId"]
        claimed = store._backend.claim_job("test-worker", queues=("default",))
        assert claimed["job_id"] == job_id
        store._backend.defer_job(
            job_id, "test-worker", "Remote result requires reconciliation"
        )

        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "parked"
        assert response.json()["retryable"] is True
        active = client.get("/api/jobs?article_id=art_001&active=true").json()["jobs"]
        assert active[0]["status"] == "parked"


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
