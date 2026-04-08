"""Tests for POST /api/articles/import."""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


class TestImportArticle:

    @pytest.fixture(autouse=True)
    def clean_connections(self, client):
        """Clear platform connections before/after each test.
        Only deletes platforms that TestImportArticle actually writes (medium, hashnode).
        """
        for platform in ("medium", "hashnode"):
            client.delete(f"/api/connections/{platform}")
        yield
        for platform in ("medium", "hashnode"):
            client.delete(f"/api/connections/{platform}")

    # ── upload source ────────────────────────────────────────────────────────

    def test_upload_source_returns_201(self, client: TestClient):
        r = client.post("/api/articles/import",
                        json={
                            "source": "upload",
                            "title": "My Uploaded Article",
                            "filename": "article.md",
                            "content": "# My Uploaded Article\n\nSome content here.",
                        })
        assert r.status_code == 201

    def test_upload_response_shape(self, client: TestClient):
        r = client.post("/api/articles/import",
                        json={
                            "source": "upload",
                            "title": "Shape Test",
                            "content": "# Shape Test\n\nContent.",
                        }).json()
        assert "id" in r
        assert r["title"] == "Shape Test"

    def test_upload_article_appears_in_list(self, client: TestClient):
        new_id = client.post("/api/articles/import",
                             json={
                                 "source": "upload",
                                 "title": "Listing Test",
                                 "content": "# Listing Test\n\nContent.",
                             }).json()["id"]
        ids = [i["id"] for i in client.get("/api/articles").json()["items"]]
        assert new_id in ids

    def test_upload_source_field_set_to_upload(self, client: TestClient):
        new_id = client.post("/api/articles/import",
                             json={
                                 "source": "upload",
                                 "title": "Source Field",
                                 "content": "# Source Field\n\nContent.",
                             }).json()["id"]
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == new_id)
        assert item["source"] == "upload"

    def test_upload_missing_content_returns_422(self, client: TestClient):
        r = client.post("/api/articles/import", json={
            "source": "upload",
            "title": "No content",
        })
        assert r.status_code == 422

    def test_upload_timeline_contains_upload_event(self, client: TestClient):
        new_id = client.post("/api/articles/import",
                             json={
                                 "source": "upload",
                                 "title": "Timeline Upload",
                                 "filename": "blog.md",
                                 "content": "# Timeline Upload\n\nContent.",
                             }).json()["id"]
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == new_id)
        events = [e["event"] for e in item["recentTimeline"]]
        assert any("upload" in e.lower() or "blog.md" in e.lower() for e in events)

    # ── platform source ──────────────────────────────────────────────────────

    def test_platform_source_returns_201(self, client: TestClient):
        client.put("/api/connections/medium", json={"token": "tok"})
        r = client.post("/api/articles/import",
                        json={
                            "source": "platform",
                            "platform": "medium",
                            "draft_id": "med-draft-001",
                            "title": "How I built a distributed cache from scratch",
                        })
        assert r.status_code == 201

    def test_platform_source_article_body_stored(self, client: TestClient):
        client.put("/api/connections/medium", json={"token": "tok"})
        new_id = client.post("/api/articles/import",
                             json={
                                 "source": "platform",
                                 "platform": "medium",
                                 "draft_id": "med-draft-001",
                                 "title": "How I built a distributed cache from scratch",
                             }).json()["id"]
        ids = [i["id"] for i in client.get("/api/articles").json()["items"]]
        assert new_id in ids

    def test_platform_source_platform_field_recorded(self, client: TestClient):
        client.put("/api/connections/medium", json={"token": "tok"})
        new_id = client.post("/api/articles/import",
                             json={
                                 "source": "platform",
                                 "platform": "medium",
                                 "draft_id": "med-draft-001",
                                 "title": "How I built a distributed cache from scratch",
                             }).json()["id"]
        item = next(i for i in client.get("/api/articles").json()["items"] if i["id"] == new_id)
        assert item["source"] == "platform"
        assert item.get("sourcePlatform") == "medium"

    def test_platform_source_disconnected_returns_404(self, client: TestClient):
        r = client.post("/api/articles/import",
                        json={
                            "source": "platform",
                            "platform": "medium",
                            "draft_id": "med-draft-001",
                            "title": "Cache article",
                        })
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "platform_not_connected"

    def test_platform_source_unknown_draft_returns_404(self, client: TestClient):
        client.put("/api/connections/medium", json={"token": "tok"})
        r = client.post("/api/articles/import",
                        json={
                            "source": "platform",
                            "platform": "medium",
                            "draft_id": "med-does-not-exist",
                            "title": "Ghost draft",
                        })
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "draft_not_found"

    def test_platform_source_missing_platform_returns_422(self, client: TestClient):
        r = client.post("/api/articles/import",
                        json={
                            "source": "platform",
                            "draft_id": "med-draft-001",
                            "title": "Missing platform field",
                        })
        assert r.status_code == 422

    def test_invalid_source_returns_422(self, client: TestClient):
        r = client.post("/api/articles/import",
                        json={
                            "source": "ftp",
                            "title": "Bad source",
                            "content": "some content",
                        })
        assert r.status_code == 422

    # ── deduplication ────────────────────────────────────────────────────────

    def test_duplicate_platform_import_merges_into_existing(self, client: TestClient):
        """Importing the same draft twice should return the same article id."""
        client.put("/api/connections/medium", json={"token": "tok"})
        payload = {
            "source": "platform",
            "platform": "medium",
            "draft_id": "med-draft-001",
            "title": "How I built a distributed cache from scratch",
        }
        id1 = client.post("/api/articles/import", json=payload).json()["id"]
        id2 = client.post("/api/articles/import", json=payload).json()["id"]
        assert id1 == id2

    def test_canonical_url_dedup_merges_across_platforms(self, client: TestClient):
        """med-post-003 and the matching Hashnode draft share the same canonical_url;
        importing both should resolve to one article."""
        from backend.routers.connections import _MOCK_DRAFTS

        hn_draft = {
            "id": "hn-dedup-test",
            "title": "Postgres full-text search vs Elasticsearch",
            "word_count": 2300,
            "updated_at": "2026-03-20T09:00:00+00:00",
            "status": "published",
            "canonical_url": "https://acisse.dev/blog/postgres-fts-vs-elasticsearch",
            "body": "# Postgres FTS\n\nContent.",
        }

        client.put("/api/connections/medium", json={"token": "tok"})
        client.put("/api/connections/hashnode", json={"token": "tok"})

        id_medium = client.post("/api/articles/import",
                                json={
                                    "source": "platform",
                                    "platform": "medium",
                                    "draft_id": "med-post-003",
                                    "title": "Postgres full-text search vs Elasticsearch",
                                }).json()["id"]

        # Patch the Hashnode fetcher so it returns our fake draft (avoids real API call)
        with patch("backend.routers.connections._fetch_hashnode_drafts", return_value=[hn_draft]):
            id_hashnode = client.post("/api/articles/import",
                                      json={
                                          "source": "platform",
                                          "platform": "hashnode",
                                          "draft_id": "hn-dedup-test",
                                          "title": "Postgres full-text search vs Elasticsearch",
                                      }).json()["id"]

        assert id_medium == id_hashnode
