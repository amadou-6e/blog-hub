"""Focused API coverage for Overview card context actions."""

from fastapi.testclient import TestClient

import backend.store as store


def test_duplicate_is_idempotent_and_creates_an_independent_draft(client: TestClient):
    original = client.get("/api/articles/art_001").json()
    headers = {"Idempotency-Key": "duplicate-art-001-once"}

    first = client.post("/api/articles/art_001/duplicate", headers=headers)
    repeated = client.post("/api/articles/art_001/duplicate", headers=headers)

    assert first.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json() == first.json()
    duplicate_id = first.json()["article"]["id"]
    duplicate = client.get(f"/api/articles/{duplicate_id}").json()
    assert duplicate["title"] == f"Copy of {original['title']}"
    assert duplicate["content"] == original["content"]
    assert duplicate["word_count"] == original["word_count"]
    assert duplicate["gate"] == "pending"
    assert all(item["status"] == "none" for item in duplicate["destinations"].values())
    ids = [item["id"] for item in client.get("/api/articles").json()["items"]]
    assert ids.count(duplicate_id) == 1


def test_duplicate_requires_an_idempotency_key(client: TestClient):
    response = client.post("/api/articles/art_001/duplicate")

    assert response.status_code == 422


def test_duplicate_unknown_article_returns_structured_404(client: TestClient):
    response = client.post(
        "/api/articles/missing/duplicate", headers={"Idempotency-Key": "missing"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "not_found"


def test_archive_removes_article_from_active_list_but_retains_history(client: TestClient):
    response = client.post("/api/articles/art_004/archive")

    assert response.status_code == 200
    assert response.json() == {"id": "art_004", "archived": True}
    ids = [item["id"] for item in client.get("/api/articles").json()["items"]]
    assert "art_004" not in ids
    archived = store.get_article("user_seed", "art_004")
    assert archived is not None
    assert any(entry["event"] == "Article archived" for entry in archived["recent_timeline"])


def test_archive_unknown_or_already_archived_article_returns_404(client: TestClient):
    assert client.post("/api/articles/art_004/archive").status_code == 200
    assert client.post("/api/articles/art_004/archive").status_code == 404
    assert client.post("/api/articles/missing/archive").status_code == 404


def test_delete_single_article_and_report_not_found(client: TestClient):
    assert client.delete("/api/articles/art_004").status_code == 204
    missing = client.delete("/api/articles/art_004")

    assert missing.status_code == 404
    assert missing.json()["detail"]["error"] == "not_found"


def test_delete_published_article_returns_structured_conflict(client: TestClient):
    response = client.delete("/api/articles/art_003")

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "has_published_destinations"
    assert client.get("/api/articles/art_003").status_code == 200
