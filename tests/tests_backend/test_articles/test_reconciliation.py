"""Remote reconciliation API and state transition tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

import backend.store as store
from backend.services import reconciliation
from backend.services.reconciliation import RemoteArticle
from backend.store.schema import SEED_USER_ID


def _link(platform: str = "devto", remote_id: str = "42") -> None:
    store.merge_platform_into_article(
        SEED_USER_ID,
        "art_001",
        platform,
        "draft",
        f"https://example.test/{remote_id}",
        remote_id,
        "Linked test destination",
    )
    store.save_connection(SEED_USER_ID, platform, token="secret")


def _remote(platform: str, remote_id: str, title: str, content: str) -> RemoteArticle:
    return RemoteArticle(
        platform=platform,
        remote_id=remote_id,
        title=title,
        content=content,
        canonical_url=None,
        remote_url=f"https://example.test/{remote_id}",
        status="draft",
        updated_at="2026-08-18T12:00:00+00:00",
        metadata={},
    )


def test_refresh_detects_remote_change_and_persists_immutable_snapshots():
    _link()
    article = store.get_article(SEED_USER_ID, "art_001")
    assert article is not None
    first = reconciliation.refresh(
        store,
        SEED_USER_ID,
        "art_001",
        "devto",
        fetcher=lambda *_: _remote("devto", "42", article["title"], article["body"]),
    )
    second = reconciliation.refresh(
        store,
        SEED_USER_ID,
        "art_001",
        "devto",
        fetcher=lambda *_: _remote("devto", "42", article["title"], article["body"] + "\nRemote edit."),
    )

    assert first["sync_state"] == "in_sync"
    assert second["sync_state"] == "remote_ahead"
    assert first["id"] != second["id"]
    assert store.get_latest_remote_snapshot(
        SEED_USER_ID, "art_001", "devto"
    )["id"] == second["id"]


def test_refresh_detects_true_two_sided_conflict():
    _link()
    article = store.get_article(SEED_USER_ID, "art_001")
    assert article is not None
    reconciliation.refresh(
        store,
        SEED_USER_ID,
        "art_001",
        "devto",
        fetcher=lambda *_: _remote("devto", "42", article["title"], article["body"]),
    )
    store.update_article_body(SEED_USER_ID, "art_001", article["body"] + "\nLocal edit.")
    result = reconciliation.refresh(
        store,
        SEED_USER_ID,
        "art_001",
        "devto",
        fetcher=lambda *_: _remote("devto", "42", article["title"], article["body"] + "\nRemote edit."),
    )
    assert result["sync_state"] == "conflict"


def test_successful_missing_lookup_is_remote_deletion():
    _link()
    result = reconciliation.refresh(
        store,
        SEED_USER_ID,
        "art_001",
        "devto",
        fetcher=lambda *_: None,
    )
    assert result["availability"] == "deleted"
    assert result["sync_state"] == "remote_deleted"


def test_provider_failure_is_inaccessible_not_deleted():
    _link()

    def fail(*_):
        raise reconciliation.ReconciliationError("provider timed out")

    result = reconciliation.refresh(
        store, SEED_USER_ID, "art_001", "devto", fetcher=fail
    )
    assert result["availability"] == "inaccessible"
    assert result["sync_state"] == "inaccessible"


def test_api_refresh_and_use_remote_resolution(client: TestClient, monkeypatch):
    _link()
    article = store.get_article(SEED_USER_ID, "art_001")
    assert article is not None
    monkeypatch.setattr(
        reconciliation,
        "fetch_remote_article",
        lambda *_: _remote("devto", "42", "Remote title", "Remote body"),
    )

    refreshed = client.post("/api/articles/art_001/reconciliation/devto/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["sync_state"] == "conflict"

    current = client.get("/api/articles/art_001").json()
    resolved = client.post(
        "/api/articles/art_001/reconciliation/devto/resolve",
        json={"action": "use_remote", "base_revision_id": current["revision_id"]},
    )
    assert resolved.status_code == 200
    assert resolved.json()["sync_state"] == "in_sync"
    updated = client.get("/api/articles/art_001").json()
    assert updated["title"] == "Remote title"
    assert updated["content"] == "Remote body"


def test_push_is_blocked_until_remote_conflict_is_resolved(client: TestClient, monkeypatch):
    _link()
    monkeypatch.setattr(
        reconciliation,
        "fetch_remote_article",
        lambda *_: _remote("devto", "42", "Remote title", "Remote body"),
    )
    assert client.post(
        "/api/articles/art_001/reconciliation/devto/refresh"
    ).json()["sync_state"] == "conflict"

    blocked = client.post(
        "/api/articles/art_001/push", json={"platforms": ["devto"]}
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "remote_conflict"

    current = client.get("/api/articles/art_001").json()
    resolved = client.post(
        "/api/articles/art_001/reconciliation/devto/resolve",
        json={"action": "keep_local", "base_revision_id": current["revision_id"]},
    )
    assert resolved.status_code == 200
    assert resolved.json()["sync_state"] == "local_ahead"


def test_reconciliation_is_scoped_to_article_owner(anon_client: TestClient):
    response = anon_client.post("/api/articles/art_001/reconciliation/devto/refresh")
    assert response.status_code == 401
