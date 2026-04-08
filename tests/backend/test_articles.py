"""
pytest tests for /api/articles — mirrors the Playwright [contract] tests.
"""

import pytest
from fastapi.testclient import TestClient
from backend.services.push import PushPlatformResult

# ─── GET /api/articles ────────────────────────────────────────────────────────


class TestListArticles:

    def test_returns_all_seed_articles(self, client: TestClient):
        r = client.get("/api/articles")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 6
        assert len(body["items"]) == 6

    def test_response_shape(self, client: TestClient):
        item = client.get("/api/articles").json()["items"][0]
        assert "id" in item
        assert "title" in item
        assert "updatedAt" in item
        assert "wordCount" in item
        assert "gate" in item
        assert "destinations" in item
        assert "recentTimeline" in item

    def test_destinations_have_three_platforms(self, client: TestClient):
        item = client.get("/api/articles").json()["items"][0]
        dests = item["destinations"]
        assert set(dests.keys()) == {"medium", "hashnode", "devto"}

    def test_platform_summary_shape(self, client: TestClient):
        item = client.get("/api/articles").json()["items"][0]
        dest = item["destinations"]["medium"]
        assert "status" in dest
        assert "label" in dest
        assert "url" in dest
        assert "error" in dest

    def test_recent_timeline_max_5(self, client: TestClient):
        for item in client.get("/api/articles").json()["items"]:
            assert len(item["recentTimeline"]) <= 5

    def test_timeline_event_shape(self, client: TestClient):
        events = client.get("/api/articles").json()["items"][0]["recentTimeline"]
        for e in events:
            assert "timestamp" in e
            assert "event" in e

    # ── filters ──

    def test_filter_by_q(self, client: TestClient):
        r = client.get("/api/articles", params={"q": "postgres"})
        items = r.json()["items"]
        assert all("postgres" in i["title"].lower() for i in items)
        assert len(items) >= 1

    def test_filter_by_q_no_match(self, client: TestClient):
        r = client.get("/api/articles", params={"q": "xyznosuchterm"})
        assert r.json()["total"] == 0

    def test_filter_by_gate_pass(self, client: TestClient):
        r = client.get("/api/articles", params={"gate": "pass"})
        for item in r.json()["items"]:
            assert item["gate"] == "pass"

    def test_filter_by_gate_fail(self, client: TestClient):
        r = client.get("/api/articles", params={"gate": "fail"})
        for item in r.json()["items"]:
            assert item["gate"] == "fail"

    def test_filter_by_status_error(self, client: TestClient):
        r = client.get("/api/articles", params={"status": "error"})
        items = r.json()["items"]
        assert len(items) >= 1
        for item in items:
            statuses = [d["status"] for d in item["destinations"].values()]
            assert "error" in statuses

    def test_filter_by_status_and_platform(self, client: TestClient):
        r = client.get("/api/articles", params={"status": "error", "platform": "devto"})
        items = r.json()["items"]
        for item in items:
            assert item["destinations"]["devto"]["status"] == "error"

    def test_filter_by_status_published(self, client: TestClient):
        r = client.get("/api/articles", params={"status": "published"})
        items = r.json()["items"]
        assert len(items) >= 1

    # ── pagination ──

    def test_pagination_page_size(self, client: TestClient):
        r = client.get("/api/articles", params={"pageSize": 2})
        body = r.json()
        assert len(body["items"]) == 2
        assert body["total"] == 6
        assert body["pageSize"] == 2

    def test_pagination_page_2(self, client: TestClient):
        r1 = client.get("/api/articles", params={"pageSize": 2, "page": 1}).json()["items"]
        r2 = client.get("/api/articles", params={"pageSize": 2, "page": 2}).json()["items"]
        ids1 = {i["id"] for i in r1}
        ids2 = {i["id"] for i in r2}
        assert ids1.isdisjoint(ids2), "Pages must not overlap"

    def test_pagination_beyond_last_page_returns_empty(self, client: TestClient):
        r = client.get("/api/articles", params={"page": 999, "pageSize": 20})
        assert r.json()["items"] == []

    # ── sorting ──

    def test_sort_by_title_asc(self, client: TestClient):
        items = client.get("/api/articles", params={
            "sortBy": "title",
            "sortDir": "asc"
        }).json()["items"]
        titles = [i["title"] for i in items]
        assert titles == sorted(titles, key=str.lower)

    def test_sort_by_title_desc(self, client: TestClient):
        items = client.get("/api/articles", params={
            "sortBy": "title",
            "sortDir": "desc"
        }).json()["items"]
        titles = [i["title"] for i in items]
        assert titles == sorted(titles, key=str.lower, reverse=True)

    def test_default_sort_is_updated_at_desc(self, client: TestClient):
        items = client.get("/api/articles").json()["items"]
        timestamps = [i["updatedAt"] for i in items]
        assert timestamps == sorted(timestamps, reverse=True)


# ─── POST /api/articles ───────────────────────────────────────────────────────


class TestCreateArticle:

    def test_creates_article_returns_201(self, client: TestClient):
        r = client.post("/api/articles", json={"title": "My new article"})
        assert r.status_code == 201

    def test_response_contains_id_title_createdAt(self, client: TestClient):
        r = client.post("/api/articles", json={"title": "Test"}).json()
        assert "id" in r
        assert r["title"] == "Test"
        assert "createdAt" in r

    def test_new_article_appears_in_list(self, client: TestClient):
        new_id = client.post("/api/articles", json={"title": "Brand new"}).json()["id"]
        ids = [i["id"] for i in client.get("/api/articles").json()["items"]]
        assert new_id in ids

    def test_new_article_gate_is_pending(self, client: TestClient):
        new_id = client.post("/api/articles", json={"title": "Pending article"}).json()["id"]
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == new_id)
        assert item["gate"] == "pending"

    def test_new_article_all_destinations_none(self, client: TestClient):
        new_id = client.post("/api/articles", json={"title": "Fresh"}).json()["id"]
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == new_id)
        for dest in item["destinations"].values():
            assert dest["status"] == "none"

    def test_new_article_timeline_has_created_event(self, client: TestClient):
        new_id = client.post("/api/articles", json={"title": "With timeline"}).json()["id"]
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == new_id)
        events = [e["event"] for e in item["recentTimeline"]]
        assert any("created" in e.lower() for e in events)

    def test_empty_title_rejected(self, client: TestClient):
        r = client.post("/api/articles", json={"title": ""})
        assert r.status_code == 422


# ─── DELETE /api/articles ─────────────────────────────────────────────────────


class TestDeleteArticles:

    def test_delete_non_published_returns_204(self, client: TestClient):
        # art_004 has all-none/draft destinations — not published
        r = client.request("DELETE", "/api/articles", json={"ids": ["art_004"]})
        assert r.status_code == 204

    def test_deleted_article_removed_from_list(self, client: TestClient):
        client.request("DELETE", "/api/articles", json={"ids": ["art_004"]})
        ids = [i["id"] for i in client.get("/api/articles").json()["items"]]
        assert "art_004" not in ids

    def test_delete_published_without_force_returns_409(self, client: TestClient):
        # art_003 is fully published
        r = client.request("DELETE", "/api/articles", json={"ids": ["art_003"]})
        assert r.status_code == 409
        assert "blocked_ids" in r.json()["detail"]

    def test_delete_published_with_force_succeeds(self, client: TestClient):
        r = client.request("DELETE", "/api/articles", json={"ids": ["art_003"], "force": True})
        assert r.status_code == 204
        ids = [i["id"] for i in client.get("/api/articles").json()["items"]]
        assert "art_003" not in ids

    def test_delete_multiple_ids(self, client: TestClient):
        r = client.request("DELETE", "/api/articles", json={"ids": ["art_004", "art_005"]})
        assert r.status_code == 204
        ids = [i["id"] for i in client.get("/api/articles").json()["items"]]
        assert "art_004" not in ids
        assert "art_005" not in ids

    def test_delete_unknown_id_is_ignored(self, client: TestClient):
        r = client.request("DELETE", "/api/articles", json={"ids": ["art_does_not_exist"]})
        assert r.status_code == 204

    def test_delete_mix_published_and_unpublished_blocks_all(self, client: TestClient):
        # art_003 published, art_004 not — without force, 409
        r = client.request("DELETE", "/api/articles", json={"ids": ["art_003", "art_004"]})
        assert r.status_code == 409


# ─── POST /api/articles/:id/push ─────────────────────────────────────────────


class TestPushArticle:

    def test_returns_202_with_job_id(self, client: TestClient):
        r = client.post("/api/articles/art_001/push", json={})
        assert r.status_code == 202
        body = r.json()
        assert "jobId" in body
        # In-memory backend resolves push synchronously → status is "done"
        assert body["status"] == "done"

    def test_push_unknown_article_returns_404(self, client: TestClient):
        r = client.post("/api/articles/art_unknown/push", json={})
        assert r.status_code == 404

    def test_destinations_updated_after_push(self, client: TestClient):
        client.post("/api/articles/art_001/push", json={})
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == "art_001")
        # After push all destinations should be draft (in-memory backend resolves immediately)
        for dest in item["destinations"].values():
            assert dest["status"] == "draft"

    def test_job_retrievable_after_push(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/push", json={}).json()["jobId"]
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        assert r.json()["jobId"] == job_id
        assert r.json()["type"] == "push"

    def test_push_job_result_contains_per_platform_status(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/push", json={}).json()["jobId"]
        job = client.get(f"/api/jobs/{job_id}").json()
        assert set(job["result"].keys()) == {"medium", "hashnode", "devto"}
        assert job["result"]["devto"]["status"] == "draft"

    def test_push_persists_platform_url_from_orchestrator(self, client: TestClient, monkeypatch):
        from backend.routers import articles as articles_router

        def fake_push(article, platforms, *, get_connection_token):
            return {
                "medium": PushPlatformResult(
                    platform="medium",
                    success=True,
                    status="draft",
                    label="Draft",
                    url="https://medium.example/draft",
                ),
                "hashnode": PushPlatformResult(
                    platform="hashnode",
                    success=True,
                    status="draft",
                    label="Draft",
                    url="https://hashnode.example/preview/123",
                    draft_id="h-123",
                ),
                "devto": PushPlatformResult(
                    platform="devto",
                    success=True,
                    status="draft",
                    label="Draft",
                    url="https://dev.to/example/draft",
                    draft_id="42",
                ),
            }

        monkeypatch.setattr(articles_router, "push_article_to_platforms", fake_push)

        client.post("/api/articles/art_001/push", json={})
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == "art_001")
        assert item["destinations"]["hashnode"]["url"] == "https://hashnode.example/preview/123"
        assert item["destinations"]["devto"]["url"] == "https://dev.to/example/draft"


# ─── POST /api/articles/:id/inspect ──────────────────────────────────────────


class TestInspectArticle:

    def test_returns_202_with_job_id(self, client: TestClient):
        r = client.post("/api/articles/art_001/inspect")
        assert r.status_code == 202
        assert "jobId" in r.json()

    def test_inspect_unknown_returns_404(self, client: TestClient):
        r = client.post("/api/articles/art_unknown/inspect")
        assert r.status_code == 404

    def test_gate_pass_for_long_article(self, client: TestClient):
        # art_001 word_count=1820 → expect pass
        client.post("/api/articles/art_001/inspect")
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == "art_001")
        assert item["gate"] == "pass"

    def test_gate_warn_for_short_article(self, client: TestClient):
        # Create a short article
        new_id = client.post("/api/articles", json={"title": "Short"}).json()["id"]
        # word_count defaults to 0 < 500 → warn
        client.post(f"/api/articles/{new_id}/inspect")
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == new_id)
        assert item["gate"] == "warn"

    def test_timeline_updated_after_inspect(self, client: TestClient):
        client.post("/api/articles/art_001/inspect")
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == "art_001")
        events = [e["event"] for e in item["recentTimeline"]]
        assert any("inspection" in e.lower() for e in events)

    def test_job_status_done_after_inspect(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/inspect").json()["jobId"]
        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["status"] == "done"
        assert job["result"]["gate"] in ("pass", "warn", "fail")


# ─── GET /api/jobs/:jobId ─────────────────────────────────────────────────────


class TestJobs:

    def test_unknown_job_returns_404(self, client: TestClient):
        r = client.get("/api/jobs/job_does_not_exist")
        assert r.status_code == 404

    def test_job_shape(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/push", json={}).json()["jobId"]
        job = client.get(f"/api/jobs/{job_id}").json()
        assert set(job.keys()) >= {"jobId", "type", "status", "articleId"}

    def test_push_job_type(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/push", json={}).json()["jobId"]
        assert client.get(f"/api/jobs/{job_id}").json()["type"] == "push"

    def test_inspect_job_type(self, client: TestClient):
        job_id = client.post("/api/articles/art_001/inspect").json()["jobId"]
        assert client.get(f"/api/jobs/{job_id}").json()["type"] == "inspect"


# ─── GET /api/platforms ───────────────────────────────────────────────────────


class TestPlatforms:

    def test_returns_three_platforms(self, client: TestClient):
        r = client.get("/api/platforms")
        assert r.status_code == 200
        assert len(r.json()["platforms"]) == 3

    def test_platform_ids(self, client: TestClient):
        ids = {p["id"] for p in client.get("/api/platforms").json()["platforms"]}
        assert ids == {"medium", "hashnode", "devto"}

    def test_platform_shape(self, client: TestClient):
        p = client.get("/api/platforms").json()["platforms"][0]
        assert "id" in p
        assert "connected" in p
        assert "label" in p
        assert "username" in p

    def test_connected_count(self, client: TestClient):
        connected = [p for p in client.get("/api/platforms").json()["platforms"] if p["connected"]]
        assert len(connected) == 3  # all seeded as connected


# ─── /health ──────────────────────────────────────────────────────────────────


class TestHealth:

    def test_health_ok(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
