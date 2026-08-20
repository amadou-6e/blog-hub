from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from backend.services.hashnode_sync import (
    sync_hashnode_articles,
    sync_hashnode_browser_records,
)
from backend.services.image_ingest import (
    ImageIngestReason,
    IngestedImage,
)
from backend.store.backends.sqlite import SQLiteStore
from blogs.hashnode.client import HashnodeRemoteArticle


class FakeHashnodeClient:
    def __init__(self, drafts=(), published=()):
        self.drafts = drafts
        self.published = published

    def list_drafts(self):
        if isinstance(self.drafts, Exception):
            raise self.drafts
        return list(self.drafts)

    def list_published_articles(self):
        if isinstance(self.published, Exception):
            raise self.published
        return list(self.published)


def _store(tmp_path) -> SQLiteStore:
    return SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))


def _remote(
    remote_id: str,
    *,
    published: bool = False,
    body: str | None = None,
    cover: str | None = None,
    updated_at: datetime | None = None,
) -> HashnodeRemoteArticle:
    return HashnodeRemoteArticle(
        article_id=remote_id,
        title=f"Remote {remote_id}",
        url=(
            f"https://writer.hashnode.dev/{remote_id}"
            if published
            else f"https://writer.hashnode.dev/preview/{remote_id}"
        ),
        canonical_url=f"https://example.com/{remote_id}",
        subtitle=f"Subtitle {remote_id}",
        body_markdown=body or f"# Remote {remote_id}\n\nBody for {remote_id}.\n",
        published=published,
        updated_at=updated_at or datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc),
        cover_image_url=cover,
        raw={"id": remote_id},
    )


def _valid_image(_url: str) -> IngestedImage:
    return IngestedImage(
        ok=True,
        content_type="image/jpeg",
        image_bytes=b"full-image",
        thumbnail_bytes=b"thumbnail",
        thumbnail_format="PNG",
    )


def _failed_image(_url: str) -> IngestedImage:
    return IngestedImage(ok=False, reason=ImageIngestReason.HTTP_ERROR)


def test_sync_imports_all_drafts_and_publications_and_is_idempotent(tmp_path):
    store = _store(tmp_path)
    try:
        drafts = [_remote("draft-1", cover="https://cdn.example/draft.jpg"), _remote("draft-2")]
        published = [_remote("post-1", published=True), _remote("post-2", published=True)]
        client = FakeHashnodeClient(drafts=drafts, published=published)

        first = sync_hashnode_articles(
            store.SEED_USER_ID,
            "pat",
            store=store,
            client=client,
            image_fetcher=_valid_image,
        )

        assert first["status"] == "succeeded"
        assert first["fetched"] == 4
        assert first["imported"] == 4
        assert first["imagesDownloaded"] == 1
        identities = [
            store.get_remote_article_identity(store.SEED_USER_ID, "hashnode", item.article_id)
            for item in drafts + published
        ]
        assert all(identity is not None for identity in identities)
        for identity in identities:
            revisions = store.list_article_revisions(
                store.SEED_USER_ID, identity["article_id"],
            )
            assert len(revisions) == 1
            assert revisions[0]["source"] == "remote-sync"

        cover_identity = identities[0]
        cover_article = store.get_article(store.SEED_USER_ID, cover_identity["article_id"])
        assert cover_article["preview_image_url"] == (
            f"/api/articles/{cover_identity['article_id']}/assets/"
            f"{cover_identity['cover_asset_id']}"
        )
        before_assets = store._con.execute("SELECT COUNT(*) FROM article_assets").fetchone()[0]

        second = sync_hashnode_articles(
            store.SEED_USER_ID,
            "pat",
            store=store,
            client=client,
            image_fetcher=lambda _url: (_ for _ in ()).throw(
                AssertionError("unchanged cover should not be downloaded")
            ),
        )

        assert second["status"] == "succeeded"
        assert second["unchanged"] == 4
        assert second["imported"] == second["updated"] == 0
        assert store._con.execute("SELECT COUNT(*) FROM article_assets").fetchone()[0] == before_assets
        for identity in identities:
            assert len(store.list_article_revisions(
                store.SEED_USER_ID, identity["article_id"],
            )) == 1
    finally:
        store.close()


def test_changed_markdown_adds_one_revision_without_changing_local_identity(tmp_path):
    store = _store(tmp_path)
    try:
        original = _remote("changing")
        first = sync_hashnode_articles(
            store.SEED_USER_ID, "pat", store=store,
            client=FakeHashnodeClient(drafts=[original]),
        )
        article_id = first["articles"][0]["articleId"]
        changed = replace(
            original,
            body_markdown="# Remote changing\n\nChanged body.\n",
            updated_at=datetime(2026, 8, 21, 9, 0, tzinfo=timezone.utc),
        )

        second = sync_hashnode_articles(
            store.SEED_USER_ID, "pat", store=store,
            client=FakeHashnodeClient(drafts=[changed]),
        )

        assert second["updated"] == 1
        assert second["articles"][0]["revisionCreated"] is True
        identity = store.get_remote_article_identity(
            store.SEED_USER_ID, "hashnode", "changing",
        )
        assert identity["article_id"] == article_id
        revisions = store.list_article_revisions(store.SEED_USER_ID, article_id)
        assert len(revisions) == 2
        assert revisions[0]["source"] == "remote-sync"
        assert store.get_current_article_revision(
            store.SEED_USER_ID, article_id,
        )["content"] == changed.body_markdown
    finally:
        store.close()


def test_metadata_updates_without_creating_a_content_revision(tmp_path):
    store = _store(tmp_path)
    try:
        draft = _remote("promoted")
        first = sync_hashnode_articles(
            store.SEED_USER_ID, "pat", store=store,
            client=FakeHashnodeClient(drafts=[draft]),
        )
        article_id = first["articles"][0]["articleId"]
        published = replace(
            draft,
            published=True,
            url="https://writer.hashnode.dev/promoted",
            subtitle="Now published",
            updated_at=datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
        )

        second = sync_hashnode_articles(
            store.SEED_USER_ID, "pat", store=store,
            client=FakeHashnodeClient(published=[published]),
        )

        assert second["metadataUpdated"] == 1
        assert second["articles"][0]["revisionCreated"] is False
        assert len(store.list_article_revisions(store.SEED_USER_ID, article_id)) == 1
        article = store.get_article(store.SEED_USER_ID, article_id)
        assert article["destinations"]["hashnode"]["status"] == "published"
        assert article["destinations"]["hashnode"]["url"] == published.url
        identity = store.get_remote_article_identity(
            store.SEED_USER_ID, "hashnode", "promoted",
        )
        assert identity["subtitle"] == "Now published"
        assert identity["remote_updated_at"] == published.updated_at.isoformat()
    finally:
        store.close()


def test_failed_cover_preserves_last_good_asset_and_reports_partial_sync(tmp_path):
    store = _store(tmp_path)
    try:
        original = _remote("covered", cover="https://cdn.example/cover-v1.jpg")
        first = sync_hashnode_articles(
            store.SEED_USER_ID, "pat", store=store,
            client=FakeHashnodeClient(drafts=[original]), image_fetcher=_valid_image,
        )
        article_id = first["articles"][0]["articleId"]
        first_identity = store.get_remote_article_identity(
            store.SEED_USER_ID, "hashnode", "covered",
        )
        changed_cover = replace(
            original,
            cover_image_url="https://cdn.example/cover-v2.jpg",
            updated_at=datetime(2026, 8, 23, 11, 0, tzinfo=timezone.utc),
        )

        second = sync_hashnode_articles(
            store.SEED_USER_ID, "pat", store=store,
            client=FakeHashnodeClient(drafts=[changed_cover]), image_fetcher=_failed_image,
        )

        assert second["status"] == "partial"
        assert second["imagesFailed"] == 1
        identity = store.get_remote_article_identity(
            store.SEED_USER_ID, "hashnode", "covered",
        )
        assert identity["cover_asset_id"] == first_identity["cover_asset_id"]
        assert identity["last_sync_status"] == "partial"
        assert identity["last_sync_error"] == "http_error"
        assert store.get_article(store.SEED_USER_ID, article_id)["preview_image_url"] is not None
    finally:
        store.close()


def test_partial_provider_failure_preserves_successful_source_and_is_structured(tmp_path):
    store = _store(tmp_path)
    try:
        result = sync_hashnode_articles(
            store.SEED_USER_ID,
            "pat",
            store=store,
            client=FakeHashnodeClient(
                drafts=RuntimeError("draft endpoint unavailable"),
                published=[_remote("available", published=True)],
            ),
        )

        assert result["status"] == "partial"
        assert result["imported"] == 1
        assert result["sourceErrors"] == [
            {"source": "drafts", "error": "article_sync_failed"}
        ]
        assert store.get_remote_article_identity(
            store.SEED_USER_ID, "hashnode", "available",
        ) is not None
    finally:
        store.close()


def test_same_remote_id_is_isolated_per_user(tmp_path):
    store = _store(tmp_path)
    try:
        other = store.create_user("hashnode-sync@example.com", "hash")
        client = FakeHashnodeClient(drafts=[_remote("shared")])
        first = sync_hashnode_articles(
            store.SEED_USER_ID, "pat", store=store, client=client,
        )
        second = sync_hashnode_articles(
            other["id"], "pat", store=store, client=client,
        )

        assert first["articles"][0]["articleId"] != second["articles"][0]["articleId"]
        assert store.get_remote_article_identity(
            store.SEED_USER_ID, "hashnode", "shared",
        )["article_id"] == first["articles"][0]["articleId"]
        assert store.get_remote_article_identity(
            other["id"], "hashnode", "shared",
        )["article_id"] == second["articles"][0]["articleId"]
    finally:
        store.close()


def test_manual_sync_endpoint_requires_pat_and_returns_typed_result(client, monkeypatch):
    missing = client.post("/api/connections/hashnode/sync")
    assert missing.status_code == 409
    assert missing.json()["detail"]["error"] == "hashnode_connection_required"

    from backend.routers import connections
    import backend.store as global_store

    global_store.save_connection(
        global_store._backend.SEED_USER_ID, "hashnode", "pat-token",
    )
    remote = _remote(
        "endpoint-import",
        published=True,
        cover="https://cdn.example/endpoint-cover.jpg",
    )

    def run_test_sync(user_id: str, token: str):
        assert token == "pat-token"
        return sync_hashnode_articles(
            user_id,
            token,
            store=global_store,
            client=FakeHashnodeClient(published=[remote]),
            image_fetcher=_valid_image,
        )

    monkeypatch.setattr(connections, "sync_hashnode_articles", run_test_sync)

    response = client.post("/api/connections/hashnode/sync")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["fetched"] == payload["imported"] == 1
    assert payload["imagesDownloaded"] == 1
    assert payload["articles"][0]["remoteId"] == "endpoint-import"
    assert payload["startedAt"].endswith("Z")
    assert payload["completedAt"].endswith("Z")

    article_id = payload["articles"][0]["articleId"]
    summary = next(
        item for item in client.get("/api/articles").json()["items"]
        if item["id"] == article_id
    )
    assert summary["title"] == remote.title
    assert summary["source"] == "remote"
    assert summary["sourcePlatform"] == "hashnode"
    assert summary["destinations"]["hashnode"]["status"] == "published"
    assert summary["previewImageUrl"].startswith(
        f"/api/articles/{article_id}/assets/"
    )
    assert client.get(summary["previewImageUrl"]).content == b"thumbnail"


def test_concurrent_first_sync_does_not_create_duplicate_articles(tmp_path):
    import threading

    store = _store(tmp_path)
    try:
        results: list[tuple[str, bool]] = []
        errors: list[Exception] = []
        barrier = threading.Barrier(5)

        def worker():
            barrier.wait()
            try:
                article, created = store.get_or_create_remote_article(
                    store.SEED_USER_ID,
                    "hashnode",
                    "draft-1",
                    title="Remote draft-1",
                    body="# Remote draft-1\n\nBody for draft-1.\n",
                )
                results.append((article["id"], created))
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, errors
        assert len(results) == 5
        article_ids = {article_id for article_id, _ in results}
        assert len(article_ids) == 1, f"expected one article id, got {article_ids}"
        assert sum(1 for _, created in results if created) == 1

        _, total = store.list_articles(store.SEED_USER_ID, q="Remote draft-1")
        assert total == 1
        identity = store.get_remote_article_identity(
            store.SEED_USER_ID, "hashnode", "draft-1",
        )
        assert identity is not None
        assert identity["article_id"] in article_ids
    finally:
        store.close()


def test_sync_reports_revision_conflict_on_concurrent_user_edit(tmp_path):
    store = _store(tmp_path)
    try:
        remote_v1 = _remote("draft-1")
        first = sync_hashnode_articles(
            store.SEED_USER_ID,
            "pat",
            store=store,
            client=FakeHashnodeClient(drafts=[remote_v1], published=[]),
            image_fetcher=_valid_image,
        )
        assert first["articles"][0]["status"] == "succeeded"
        article_id = first["articles"][0]["articleId"]

        real_get_current = store.get_current_article_revision

        def racing_get_current(user_id: str, aid: str):
            current = real_get_current(user_id, aid)
            if aid == article_id:
                # Simulate a user's in-editor save landing between the sync's
                # read of the current revision and its own write.
                store.save_article_revision(
                    user_id,
                    aid,
                    title="User's local title",
                    content="User's local edit, not from Hashnode.",
                    source="user",
                    description="Concurrent user edit",
                )
            return current

        store.get_current_article_revision = racing_get_current

        remote_v2 = _remote(
            "draft-1", body="# Remote draft-1\n\nChanged remote content.\n",
        )
        second = sync_hashnode_articles(
            store.SEED_USER_ID,
            "pat",
            store=store,
            client=FakeHashnodeClient(drafts=[remote_v2], published=[]),
            image_fetcher=_valid_image,
        )

        article_result = second["articles"][0]
        assert article_result["status"] == "failed"
        assert article_result["error"] == "revision_conflict"

        del store.get_current_article_revision
        current = store.get_current_article_revision(store.SEED_USER_ID, article_id)
        assert current["content"] == "User's local edit, not from Hashnode."
    finally:
        store.close()
def test_browser_records_use_the_same_idempotent_sync_pipeline(tmp_path):
    store = _store(tmp_path)
    retrieval = {
        "articles": [{
            "remote_id": "browser-draft",
            "title": "Browser draft",
            "body_markdown": "# Browser draft\n\nRetrieved content.\n",
            "subtitle": "Retrieved without GraphQL",
            "canonical_url": None,
            "url": None,
            "published": False,
            "updated_at": "2026-08-20T08:00:00Z",
            "created_at": "2026-08-19T08:00:00Z",
            "cover_image_url": None,
        }],
        "errors": [],
    }
    try:
        first = sync_hashnode_browser_records(
            store.SEED_USER_ID, retrieval, store=store,
        )
        second = sync_hashnode_browser_records(
            store.SEED_USER_ID, retrieval, store=store,
        )

        assert first["imported"] == 1
        assert second["unchanged"] == 1
        article_id = first["articles"][0]["articleId"]
        identity = store.get_remote_article_identity(
            store.SEED_USER_ID, "hashnode", "browser-draft",
        )
        assert identity["article_id"] == article_id
        assert identity["remote_created_at"] == "2026-08-19T08:00:00Z"
        assert len(store.list_article_revisions(store.SEED_USER_ID, article_id)) == 1
    finally:
        store.close()


def test_browser_record_failures_are_partial_and_article_scoped(tmp_path):
    store = _store(tmp_path)
    try:
        result = sync_hashnode_browser_records(
            store.SEED_USER_ID,
            {
                "articles": [],
                "errors": [{
                    "source": "drafts",
                    "remote_id": "unreadable-draft",
                    "error": "article_retrieval_failed",
                }],
            },
            store=store,
        )

        assert result["status"] == "partial"
        assert result["failed"] == 1
        assert result["articles"][0]["remoteId"] == "unreadable-draft"
        assert result["articles"][0]["error"] == "article_retrieval_failed"
    finally:
        store.close()


def test_manual_endpoint_prefers_connected_browser_profile(client, monkeypatch):
    from backend.routers import connections
    import backend.store as global_store

    user_id = global_store._backend.SEED_USER_ID
    global_store.start_browser_connection(
        user_id,
        "hashnode",
        session_id="bs_test",
        organization_id="o_test",
        app_url="http://localhost/browser",
        profile_id="bp_test",
    )
    global_store.update_browser_connection(
        user_id, "hashnode", "connected", profile_id="bp_test",
    )
    global_store.save_connection(user_id, "hashnode", "pro-token")
    retrieval = {"articles": [], "errors": []}
    called = []

    def retrieve(**kwargs):
        called.append(kwargs)
        return retrieval

    monkeypatch.setattr(connections.runner, "hashnode_browser_articles", retrieve)
    monkeypatch.setattr(
        connections,
        "sync_hashnode_browser_records",
        lambda received_user_id, received: {
            "status": "succeeded",
            "startedAt": "2026-08-20T08:00:00Z",
            "completedAt": "2026-08-20T08:00:01Z",
            "fetched": 0,
            "imported": 0,
            "updated": 0,
            "metadataUpdated": 0,
            "unchanged": 0,
            "failed": 0,
            "imagesDownloaded": 0,
            "imagesFailed": 0,
            "sourceErrors": [],
            "articles": [],
        },
    )
    monkeypatch.setattr(
        connections,
        "sync_hashnode_articles",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Pro API should not run when browser login is connected")
        ),
    )

    response = client.post("/api/connections/hashnode/sync")

    assert response.status_code == 200
    assert called == [{"organization_id": "o_test", "profile_id": "bp_test"}]
