from __future__ import annotations

from fastapi.testclient import TestClient


def _article(client: TestClient, article_id: str = "art_001") -> dict:
    response = client.get(f"/api/articles/{article_id}")
    assert response.status_code == 200
    return response.json()


def test_article_read_includes_current_revision(client: TestClient):
    article = _article(client)

    assert article["revision_id"].startswith("rev_")
    assert article["revision_number"] == 1


def test_save_creates_an_immutable_revision(client: TestClient):
    original = _article(client)
    response = client.patch(
        "/api/articles/art_001",
        json={
            "title": "Revised title",
            "content": original["content"] + "\nA saved line.\n",
            "base_revision_id": original["revision_id"],
        },
    )

    assert response.status_code == 200
    saved = response.json()
    assert saved["revision_number"] == 2
    revisions = client.get("/api/articles/art_001/revisions").json()["revisions"]
    assert [item["revision_number"] for item in revisions] == [2, 1]
    initial = client.get(
        f"/api/articles/art_001/revisions/{original['revision_id']}"
    ).json()
    assert initial["title"] == original["title"]
    assert initial["content"] == original["content"]


def test_stale_save_returns_current_content_without_overwriting(client: TestClient):
    original = _article(client)
    first = client.patch(
        "/api/articles/art_001",
        json={
            "content": "first writer",
            "base_revision_id": original["revision_id"],
        },
    )
    assert first.status_code == 200

    stale = client.patch(
        "/api/articles/art_001",
        json={
            "content": "stale second writer",
            "base_revision_id": original["revision_id"],
        },
    )

    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "revision_conflict"
    assert detail["current"]["content"] == "first writer"
    assert _article(client)["content"] == "first writer"


def test_manual_checkpoint_creates_revision_even_without_changes(client: TestClient):
    current = _article(client)
    response = client.post(
        "/api/articles/art_001/checkpoints",
        json={
            "base_revision_id": current["revision_id"],
            "description": "Before structural edit",
        },
    )

    assert response.status_code == 201
    assert response.json()["revision_number"] == 2
    assert response.json()["description"] == "Before structural edit"


def test_restore_creates_a_new_head_and_preserves_intervening_history(client: TestClient):
    original = _article(client)
    changed = client.patch(
        "/api/articles/art_001",
        json={
            "title": "Changed",
            "content": "replacement body",
            "base_revision_id": original["revision_id"],
        },
    ).json()

    restored = client.post(
        f"/api/articles/art_001/revisions/{original['revision_id']}/restore",
        json={"base_revision_id": changed["revision_id"]},
    )

    assert restored.status_code == 200
    assert restored.json()["revision_number"] == 3
    assert restored.json()["restored_from_id"] == original["revision_id"]
    assert _article(client)["content"] == original["content"]
    assert len(client.get("/api/articles/art_001/revisions").json()["revisions"]) == 3


def test_revision_diff_compares_with_current_head(client: TestClient):
    original = _article(client)
    client.patch(
        "/api/articles/art_001",
        json={
            "content": original["content"] + "\nnew ending\n",
            "base_revision_id": original["revision_id"],
        },
    )

    response = client.get(
        f"/api/articles/art_001/revisions/{original['revision_id']}/diff"
    )

    assert response.status_code == 200
    assert "+new ending" in response.json()["diff"]
