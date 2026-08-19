from __future__ import annotations

import backend.services.browser_publish as browser_publish
import backend.store as store


def _connect() -> None:
    store.start_browser_connection(
        "user_seed", "hashnode", session_id="pbs_test",
        organization_id="o_test", app_url="http://localhost/login",
    )
    store.update_browser_connection(
        "user_seed", "hashnode", "connected", profile_id="bp_test"
    )


def test_browser_publish_requires_approval_and_completes(client, monkeypatch):
    _connect()
    seen = {}

    def upload(**kwargs):
        seen.update(kwargs)
        return {
            "success": True, "method": "deterministic",
            "url": "https://hashnode.com/draft/example", "draft_id": "example",
        }

    monkeypatch.setattr(browser_publish.runner, "hashnode_browser_upload", upload)
    created = client.post(
        "/api/articles/art_001/browser-publish/hashnode",
    )
    assert created.status_code == 201
    assert created.json()["status"] == "awaiting_approval"
    run_id = created.json()["id"]

    approved = client.post(f"/api/articles/art_001/browser-publish/{run_id}/approve")
    assert approved.status_code == 202
    persisted = client.get(
        f"/api/articles/art_001/browser-publish/{run_id}"
    ).json()
    assert persisted["status"] == "completed"
    assert persisted["result"]["method"] == "deterministic"
    assert persisted["mode"] == "draft"
    assert seen["publish"] is False
    assert seen["profile_id"] == "bp_test"
    assert seen["organization_id"] == "o_test"


def test_public_publish_mode_is_durable_and_updates_destination(client, monkeypatch):
    _connect()
    seen = {}
    monkeypatch.setattr(
        browser_publish.runner,
        "hashnode_browser_upload",
        lambda **kwargs: seen.update(kwargs) or {
            "success": True,
            "method": "deterministic",
            "status": "published",
            "url": "https://example.hashnode.dev/test",
            "draft_id": "public_test",
        },
    )

    run = client.post(
        "/api/articles/art_001/browser-publish/hashnode",
        json={"mode": "publish"},
    ).json()
    assert run["mode"] == "publish"

    client.post(f"/api/articles/art_001/browser-publish/{run['id']}/approve")

    assert seen["publish"] is True
    article = client.get("/api/articles/art_001").json()
    assert article["destinations"]["hashnode"]["status"] == "published"
    assert article["destinations"]["hashnode"]["url"] == (
        "https://example.hashnode.dev/test"
    )


def test_browser_publish_cannot_be_approved_twice(client, monkeypatch):
    _connect()
    monkeypatch.setattr(
        browser_publish.runner, "hashnode_browser_upload",
        lambda **_kwargs: {"success": True, "method": "deterministic"},
    )
    run = client.post(
        "/api/articles/art_001/browser-publish/hashnode",
    ).json()
    assert client.post(
        f"/api/articles/art_001/browser-publish/{run['id']}/approve"
    ).status_code == 202
    duplicate = client.post(
        f"/api/articles/art_001/browser-publish/{run['id']}/approve"
    )
    assert duplicate.status_code == 409


def test_browser_publish_requires_connected_browser_profile(client):
    response = client.post(
        "/api/articles/art_001/browser-publish/hashnode",
    )
    assert response.status_code == 409


def test_manual_handoff_is_retained_on_failed_browser_login(client, monkeypatch):
    _connect()
    monkeypatch.setattr(
        browser_publish.runner, "hashnode_browser_upload",
        lambda **_kwargs: {
            "success": False,
            "error": "Hashnode browser session is not authenticated",
            "manual_handoff": {
                "reason": "hashnode_login_required",
                "url": "https://hashnode.com/signin",
            },
        },
    )
    run = client.post(
        "/api/articles/art_001/browser-publish/hashnode",
    ).json()
    client.post(f"/api/articles/art_001/browser-publish/{run['id']}/approve")
    persisted = client.get(
        f"/api/articles/art_001/browser-publish/{run['id']}"
    ).json()
    assert persisted["status"] == "failed"
    assert persisted["result"]["manual_handoff"]["reason"] == "hashnode_login_required"


def test_approved_run_uploads_the_revision_captured_at_request(client, monkeypatch):
    _connect()
    article = client.get("/api/articles/art_001").json()
    seen = {}
    monkeypatch.setattr(
        browser_publish.runner, "hashnode_browser_upload",
        lambda **kwargs: seen.update(kwargs) or {"success": True, "method": "deterministic"},
    )
    run = client.post(
        "/api/articles/art_001/browser-publish/hashnode",
    ).json()
    client.patch("/api/articles/art_001", json={
        "content": article["content"] + "\n\nNewer editor text.",
        "base_revision_id": article["revision_id"],
    })
    client.post(f"/api/articles/art_001/browser-publish/{run['id']}/approve")
    assert seen["article_md"] == article["content"]


def test_interrupted_external_write_is_not_replayed(client):
    _connect()
    run = client.post(
        "/api/articles/art_001/browser-publish/hashnode",
    ).json()
    store.approve_browser_publish_run("user_seed", run["id"])
    assert store.recover_browser_publish_runs() == 1
    recovered = store.get_browser_publish_run("user_seed", run["id"])
    assert recovered["status"] == "unknown"
    assert "verified" in recovered["error"]
