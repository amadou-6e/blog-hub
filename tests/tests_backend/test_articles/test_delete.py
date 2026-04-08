"""Tests for DELETE /api/articles."""

from fastapi.testclient import TestClient


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
