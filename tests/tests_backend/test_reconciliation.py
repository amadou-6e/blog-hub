from __future__ import annotations

import backend.store as global_store
from backend.services.hashnode_sync import RemoteSyncArticle, _fingerprint, sync_browser_records
from backend.services import reconciliation
from backend.store.article_revisions import RevisionConflict
from backend.store.backends.sqlite import SQLiteStore


def _store(tmp_path) -> SQLiteStore:
    return SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))


def _retrieval(body: str) -> dict:
    return {
        "success": True,
        "articles": [{
            "platform": "medium",
            "remote_id": "remote-1",
            "title": "Remote title",
            "body": body,
            "status": "draft",
            "updated_at": "2026-08-23T08:00:00Z",
            "metadata": {"url": "https://medium.com/p/remote-1/edit"},
        }],
        "diagnostics": {"errors": []},
    }


def _conflict(store: SQLiteStore) -> tuple[str, dict]:
    first = sync_browser_records(
        store.SEED_USER_ID,
        _retrieval("# Remote title\n\nShared baseline.\n"),
        platform="medium",
        store=store,
    )
    article_id = first["articles"][0]["articleId"]
    current = store.get_current_article_revision(store.SEED_USER_ID, article_id)
    store.save_article_revision(
        store.SEED_USER_ID,
        article_id,
        title="Local title",
        content="# Local title\n\nLocal edit.\n",
        source="user",
        expected_revision_id=current["id"],
    )
    result = sync_browser_records(
        store.SEED_USER_ID,
        _retrieval("# Remote title\n\nRemote edit.\n"),
        platform="medium",
        store=store,
    )
    return article_id, result


def test_two_sided_change_records_conflict_without_overwriting_local_revision(tmp_path):
    store = _store(tmp_path)
    try:
        article_id, result = _conflict(store)

        assert result["status"] == "partial"
        assert result["conflicts"] == 1
        assert result["articles"][0]["error"] == "remote_content_conflict"
        current = store.get_current_article_revision(store.SEED_USER_ID, article_id)
        assert current["title"] == "Local title"
        assert current["content"] == "# Local title\n\nLocal edit.\n"
        observation = store.get_latest_reconciliation_observation(
            store.SEED_USER_ID, article_id, "medium",
        )
        assert observation["sync_state"] == "conflict"
        assert observation["remote_content"] == "# Remote title\n\nRemote edit.\n"
        assert store.has_unresolved_reconciliation(
            store.SEED_USER_ID, article_id, ["medium"],
        ) is True
    finally:
        store.close()


def test_use_remote_creates_revision_and_resolves_conflict(tmp_path):
    store = _store(tmp_path)
    try:
        article_id, _ = _conflict(store)
        current = store.get_current_article_revision(store.SEED_USER_ID, article_id)

        resolved = reconciliation.resolve(
            store,
            store.SEED_USER_ID,
            article_id,
            "medium",
            "use_remote",
            current["id"],
        )

        assert resolved["sync_state"] == "in_sync"
        latest = store.get_current_article_revision(store.SEED_USER_ID, article_id)
        assert latest["content"] == "# Remote title\n\nRemote edit.\n"
        assert latest["source"] == "remote-sync"
        assert len(store.list_article_revisions(store.SEED_USER_ID, article_id)) == 3
        assert not store.has_unresolved_reconciliation(
            store.SEED_USER_ID, article_id, ["medium"],
        )
    finally:
        store.close()


def test_keep_local_resolves_without_creating_revision(tmp_path):
    store = _store(tmp_path)
    try:
        article_id, _ = _conflict(store)
        current = store.get_current_article_revision(store.SEED_USER_ID, article_id)
        before = store.list_article_revisions(store.SEED_USER_ID, article_id)

        resolved = reconciliation.resolve(
            store,
            store.SEED_USER_ID,
            article_id,
            "medium",
            "keep_local",
            current["id"],
        )

        assert resolved["sync_state"] == "local_ahead"
        assert store.list_article_revisions(store.SEED_USER_ID, article_id) == before
    finally:
        store.close()


def test_use_remote_rejects_stale_editor_revision(tmp_path):
    store = _store(tmp_path)
    try:
        article_id, _ = _conflict(store)
        stale = store.list_article_revisions(store.SEED_USER_ID, article_id)[-1]
        try:
            reconciliation.resolve(
                store,
                store.SEED_USER_ID,
                article_id,
                "medium",
                "use_remote",
                stale["id"],
            )
        except RevisionConflict:
            pass
        else:
            raise AssertionError("stale conflict resolution should fail")
    finally:
        store.close()


def test_push_endpoint_blocks_only_selected_platform_with_conflict(client):
    user_id = global_store._backend.SEED_USER_ID
    article_id = "art_001"
    revision = global_store.get_current_article_revision(user_id, article_id)
    global_store.upsert_remote_article_identity(
        user_id,
        article_id,
        "medium",
        "remote-push-conflict",
        remote_content_fingerprint="sha256:baseline",
    )
    global_store.record_reconciliation_observation(
        user_id,
        article_id,
        "medium",
        "remote-push-conflict",
        local_revision_id=revision["id"],
        local_fingerprint="sha256:local",
        remote_fingerprint="sha256:remote",
        availability="available",
        sync_state="conflict",
    )

    blocked = client.post(
        f"/api/articles/{article_id}/push", json={"platforms": ["medium"]},
    )
    unrelated = client.post(
        f"/api/articles/{article_id}/push", json={"platforms": ["devto"]},
    )

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error"] == "remote_content_conflict"
    assert unrelated.status_code == 202


def test_observations_are_user_scoped(tmp_path):
    store = _store(tmp_path)
    try:
        article_id, _ = _conflict(store)
        other = store.create_user("reconciliation@example.com", "hash")
        assert store.list_latest_reconciliation_observations(
            other["id"], article_id,
        ) == []
        assert store.get_latest_reconciliation_observation(
            other["id"], article_id, "medium",
        ) is None
    finally:
        store.close()


def test_reconciliation_api_lists_and_resolves_remote_conflict(client):
    user_id = global_store._backend.SEED_USER_ID
    article_id = "art_001"
    revision = global_store.get_current_article_revision(user_id, article_id)
    global_store.upsert_remote_article_identity(
        user_id, article_id, "medium", "api-conflict",
        remote_content_fingerprint="sha256:baseline",
    )
    remote_fingerprint = _fingerprint(RemoteSyncArticle(
        article_id="api-conflict",
        title="Accepted remote",
        body_markdown="# Accepted remote\n\nRemote body.\n",
        published=False,
    ))
    global_store.record_reconciliation_observation(
        user_id,
        article_id,
        "medium",
        "api-conflict",
        local_revision_id=revision["id"],
        baseline_fingerprint="sha256:baseline",
        local_fingerprint="sha256:local",
        remote_fingerprint=remote_fingerprint,
        availability="available",
        sync_state="conflict",
        remote_title="Accepted remote",
        remote_content="# Accepted remote\n\nRemote body.\n",
    )

    listed = client.get(f"/api/articles/{article_id}/reconciliation")
    assert listed.status_code == 200
    assert listed.json()["comparisons"][0]["syncState"] == "conflict"

    resolved = client.post(
        f"/api/articles/{article_id}/reconciliation/medium/resolve",
        json={"action": "use_remote", "base_revision_id": revision["id"]},
    )
    assert resolved.status_code == 200
    assert resolved.json()["syncState"] == "in_sync"
    article = client.get(f"/api/articles/{article_id}").json()
    assert article["title"] == "Accepted remote"
    assert article["content"] == "# Accepted remote\n\nRemote body.\n"


def test_refresh_marks_missing_medium_article_deleted(client, monkeypatch):
    from backend.routers import reconciliation as reconciliation_router

    user_id = global_store._backend.SEED_USER_ID
    article_id = "art_001"
    global_store.upsert_remote_article_identity(
        user_id, article_id, "medium", "deleted-medium",
        remote_content_fingerprint="sha256:baseline",
    )
    global_store.start_browser_connection(
        user_id,
        "medium",
        session_id="reconciliation_refresh",
        organization_id="org",
        app_url="http://localhost/browser",
        profile_id="profile",
    )
    global_store.update_browser_connection(
        user_id, "medium", "connected", profile_id="profile",
    )
    monkeypatch.setattr(
        reconciliation_router.runner,
        "medium_browser_articles",
        lambda **_kwargs: {
            "success": True, "articles": [], "diagnostics": {"errors": []},
        },
    )
    monkeypatch.setattr(
        reconciliation_router,
        "sync_medium_browser_records",
        lambda *_args, **_kwargs: {
            "status": "succeeded", "articles": [],
        },
    )

    response = client.post(
        f"/api/articles/{article_id}/reconciliation/medium/refresh",
    )

    assert response.status_code == 200
    assert response.json()["availability"] == "deleted"
    assert response.json()["syncState"] == "remote_deleted"
