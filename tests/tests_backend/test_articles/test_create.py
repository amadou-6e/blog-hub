"""Tests for POST /api/articles."""

from fastapi.testclient import TestClient


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
