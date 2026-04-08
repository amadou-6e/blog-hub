"""Tests for GET /api/articles — list, filter, paginate, sort."""

import pytest
from fastapi.testclient import TestClient


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
