from __future__ import annotations

import backend.store as global_store
from backend.routers import connections
from backend.services import cli_runner
from backend.services.image_ingest import ImageIngestReason, IngestedImage
from backend.services.medium_sync import sync_medium_browser_records
from backend.store.backends.sqlite import SQLiteStore


def _store(tmp_path) -> SQLiteStore:
    return SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))


def _retrieval(*, body: str = "# Medium story\n\nBody.\n", cover: str | None = None):
    return {
        "success": True,
        "articles": [{
            "platform": "medium",
            "remote_id": "medium-story-1",
            "title": "Medium story",
            "body": body,
            "status": "published",
            "subtitle": "A synchronized subtitle",
            "canonical_url": "https://example.com/medium-story",
            "cover_url": cover,
            "created_at": "2026-08-20T08:00:00Z",
            "updated_at": "2026-08-21T09:00:00Z",
            "metadata": {"url": "https://medium.com/@writer/medium-story-1"},
        }],
        "diagnostics": {"errors": []},
    }


def _valid_image(_url: str) -> IngestedImage:
    return IngestedImage(
        ok=True,
        content_type="image/jpeg",
        image_bytes=b"full-image",
        thumbnail_bytes=b"thumbnail",
        thumbnail_format="PNG",
    )


def test_medium_sync_is_idempotent_and_creates_revision_only_for_content_change(tmp_path):
    store = _store(tmp_path)
    try:
        first = sync_medium_browser_records(
            store.SEED_USER_ID, _retrieval(), store=store,
        )
        second = sync_medium_browser_records(
            store.SEED_USER_ID, _retrieval(), store=store,
        )
        changed = sync_medium_browser_records(
            store.SEED_USER_ID,
            _retrieval(body="# Medium story\n\nChanged body.\n"),
            store=store,
        )

        assert first["imported"] == 1
        assert second["unchanged"] == 1
        assert changed["updated"] == 1
        article_id = first["articles"][0]["articleId"]
        assert changed["articles"][0]["articleId"] == article_id
        revisions = store.list_article_revisions(store.SEED_USER_ID, article_id)
        assert len(revisions) == 2
        assert all(item["source"] == "remote-sync" for item in revisions)
        identity = store.get_remote_article_identity(
            store.SEED_USER_ID, "medium", "medium-story-1",
        )
        assert identity["subtitle"] == "A synchronized subtitle"
        assert identity["remote_content_fingerprint"].startswith("sha256:")
        assert identity["last_sync_status"] == "succeeded"
    finally:
        store.close()


def test_medium_cover_is_local_and_failure_preserves_text_sync(tmp_path):
    store = _store(tmp_path)
    try:
        success = sync_medium_browser_records(
            store.SEED_USER_ID,
            _retrieval(cover="https://cdn.example/medium.jpg"),
            store=store,
            image_fetcher=_valid_image,
        )
        article_id = success["articles"][0]["articleId"]
        article = store.get_article(store.SEED_USER_ID, article_id)
        assert article["preview_image_url"].startswith(
            f"/api/articles/{article_id}/assets/"
        )

        changed = _retrieval(cover="https://cdn.example/new-medium.jpg")
        changed["articles"][0]["updated_at"] = "2026-08-22T09:00:00Z"
        partial = sync_medium_browser_records(
            store.SEED_USER_ID,
            changed,
            store=store,
            image_fetcher=lambda _url: IngestedImage(
                ok=False, reason=ImageIngestReason.HTTP_ERROR,
            ),
        )
        assert partial["status"] == "partial"
        assert partial["imagesFailed"] == 1
        assert store.get_article(
            store.SEED_USER_ID, article_id,
        )["preview_image_url"] == article["preview_image_url"]
    finally:
        store.close()


def test_medium_sync_reports_article_detail_failure_and_isolates_users(tmp_path):
    store = _store(tmp_path)
    try:
        retrieval = _retrieval()
        retrieval["diagnostics"]["errors"] = [{
            "source": "article_detail",
            "remote_id": "unreadable-story",
            "error": "article_retrieval_failed",
        }]
        first = sync_medium_browser_records(
            store.SEED_USER_ID, retrieval, store=store,
        )
        other = store.create_user("medium-sync@example.com", "hash")
        second = sync_medium_browser_records(other["id"], _retrieval(), store=store)

        assert first["status"] == "partial"
        assert first["failed"] == 1
        assert first["articles"][0]["remoteId"] == "unreadable-story"
        first_identity = store.get_remote_article_identity(
            store.SEED_USER_ID, "medium", "medium-story-1",
        )
        second_identity = store.get_remote_article_identity(
            other["id"], "medium", "medium-story-1",
        )
        assert first_identity["article_id"] != second_identity["article_id"]
    finally:
        store.close()


def test_medium_runner_hydrates_listings_and_keeps_partial_failures(monkeypatch):
    calls = []

    def operation(_platform, operation_name, **kwargs):
        calls.append((operation_name, kwargs.get("remote_id")))
        if operation_name == "list_articles":
            return {
                "success": True,
                "articles": [
                    {
                        "platform": "medium",
                        "remote_id": "one",
                        "title": "One",
                        "subtitle": "Listing excerpt",
                        "cover_url": "https://cdn.example/listing.jpg",
                    },
                    {"platform": "medium", "remote_id": "two", "title": "Two"},
                ],
                "diagnostics": {"errors": []},
            }
        if kwargs["remote_id"] == "two":
            return {"success": False, "error": "content_missing"}
        return {"success": True, "article": {
            "platform": "medium",
            "remote_id": "one",
            "title": "One",
            "body": "Hydrated body",
            "status": "draft",
            "subtitle": None,
            "cover_url": None,
            "metadata": {"url": "https://medium.com/p/one/edit"},
        }}

    monkeypatch.setattr(cli_runner, "browser_operation", operation)
    result = cli_runner.medium_browser_articles(
        organization_id="org", profile_id="profile",
    )

    assert result["success"] is True
    assert result["articles"][0]["body"] == "Hydrated body"
    assert result["articles"][0]["subtitle"] == "Listing excerpt"
    assert result["articles"][0]["cover_url"] == "https://cdn.example/listing.jpg"
    assert result["diagnostics"]["errors"] == [{
        "source": "article_detail",
        "remote_id": "two",
        "error": "content_missing",
    }]
    assert calls == [("list_articles", None), ("get_article", "one"), ("get_article", "two")]


def test_medium_manual_sync_endpoint_imports_into_overview(client, monkeypatch):
    user_id = global_store._backend.SEED_USER_ID
    global_store.start_browser_connection(
        user_id,
        "medium",
        session_id="medium_sync",
        organization_id="org_medium",
        app_url="http://localhost/browser",
        profile_id="profile_medium",
    )
    global_store.update_browser_connection(
        user_id, "medium", "connected", profile_id="profile_medium",
    )
    retrieval = _retrieval()
    monkeypatch.setattr(
        connections.runner, "medium_browser_articles", lambda **_kwargs: retrieval,
    )
    monkeypatch.setattr(
        connections,
        "sync_medium_browser_records",
        lambda received_user_id, received: sync_medium_browser_records(
            received_user_id, received, store=global_store,
        ),
    )

    response = client.post("/api/connections/medium/sync")

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] == 1
    article_id = payload["articles"][0]["articleId"]
    overview = client.get("/api/articles").json()["items"]
    article = next(item for item in overview if item["id"] == article_id)
    assert article["sourcePlatform"] == "medium"
    assert article["destinations"]["medium"]["status"] == "published"


def test_medium_manual_sync_requires_connected_browser(client):
    response = client.post("/api/connections/medium/sync")
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "medium_browser_connection_required"
