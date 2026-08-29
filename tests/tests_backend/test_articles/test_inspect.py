"""Tests for POST /api/articles/:id/inspect."""

from fastapi.testclient import TestClient


class TestInspectArticle:

    def test_returns_202_with_job_id(self, client: TestClient):
        r = client.post("/api/articles/art_001/inspect")
        assert r.status_code == 202
        assert "jobId" in r.json()

    def test_inspect_unknown_returns_404(self, client: TestClient):
        r = client.post("/api/articles/art_unknown/inspect")
        assert r.status_code == 404

    def test_repeated_idempotency_key_returns_the_same_job(self, client: TestClient):
        headers = {"Idempotency-Key": "overview-inspect-art-001"}
        first = client.post("/api/articles/art_001/inspect", headers=headers)
        second = client.post("/api/articles/art_001/inspect", headers=headers)

        assert first.status_code == second.status_code == 202
        assert second.json()["jobId"] == first.json()["jobId"]

    def test_gate_pass_for_long_article(self, client: TestClient, run_jobs):
        # art_001 word_count=1820 → expect pass
        client.post("/api/articles/art_001/inspect")
        run_jobs()
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == "art_001")
        assert item["gate"] == "pass"

    def test_gate_warn_for_short_article(self, client: TestClient, run_jobs):
        # Create a short article
        new_id = client.post("/api/articles", json={"title": "Short"}).json()["id"]
        # word_count defaults to 0 < 500 → warn
        client.post(f"/api/articles/{new_id}/inspect")
        run_jobs()
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == new_id)
        assert item["gate"] == "warn"

    def test_timeline_updated_after_inspect(self, client: TestClient, run_jobs):
        client.post("/api/articles/art_001/inspect")
        run_jobs()
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == "art_001")
        events = [e["event"] for e in item["recentTimeline"]]
        assert any("inspection" in e.lower() for e in events)

    def test_job_status_done_after_inspect(self, client: TestClient, run_jobs):
        job_id = client.post("/api/articles/art_001/inspect").json()["jobId"]
        run_jobs()
        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["status"] == "completed"
        assert job["result"]["gate"] in ("pass", "warn", "fail")
