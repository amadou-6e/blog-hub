from __future__ import annotations

import backend.routers.connections as connections_router
import backend.services.cli_runner as runner
import backend.store as store


def test_browser_extension_capabilities_are_exposed_to_the_ui(client, monkeypatch):
    monkeypatch.setattr(
        connections_router.runner,
        "browser_extensions",
        lambda: [{
            "id": "bloghub.hashnode",
            "platform": "hashnode",
            "capabilities": ["create_draft", "publish"],
        }],
    )

    response = client.get("/api/connections/browser-extensions")

    assert response.status_code == 200
    assert response.json()["extensions"][0]["platform"] == "hashnode"
    assert "publish" in response.json()["extensions"][0]["capabilities"]


def test_browser_connection_distinguishes_live_login_from_saved_profile(
    client, monkeypatch,
):
    store.start_browser_connection(
        "user_seed", "medium", session_id="pbs_medium",
        organization_id="o_org", app_url="http://localhost/login",
    )
    monkeypatch.setattr(
        connections_router.runner,
        "get_browser_login",
        lambda platform, session_id: {
            "status": "running",
            "live_authentication": {
                "status": "authenticated",
                "authenticated": True,
                "url": "https://medium.com/",
            },
        },
    )

    response = client.get("/api/connections/medium/browser-connection")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "waiting_for_login"
    assert payload["loginPhase"] == "signed_in_pending_save"
    assert payload["browserSession"] == {
        "status": "running",
        "authenticationStatus": "authenticated",
        "authenticated": True,
        "currentUrl": "https://medium.com/",
    }
    assert payload["durableConnection"] == {
        "status": "waiting_for_login", "profileSaved": False,
    }


def test_browser_connection_reports_unknown_when_live_probe_is_unavailable(
    client, monkeypatch,
):
    store.start_browser_connection(
        "user_seed", "medium", session_id="pbs_medium",
        organization_id="o_org", app_url="http://localhost/login",
    )
    monkeypatch.setattr(
        connections_router.runner,
        "get_browser_login",
        lambda *_args: (_ for _ in ()).throw(
            runner.RunnerUnavailable("probe unavailable")
        ),
    )

    payload = client.get(
        "/api/connections/medium/browser-connection"
    ).json()

    assert payload["loginPhase"] == "waiting_for_login"
    assert payload["browserSession"]["authenticationStatus"] == "unknown"
    assert payload["browserSession"]["authenticated"] is None


def test_active_browser_connection_exports_screenshot(client, monkeypatch):
    screenshot = b"\x89PNG\r\n\x1a\ncurrent-frame"
    store.start_browser_connection(
        "user_seed", "medium", session_id="pbs_medium",
        organization_id="o_org", app_url="http://localhost/login",
    )
    seen = []
    monkeypatch.setattr(
        connections_router.runner,
        "capture_browser_screenshot",
        lambda platform, session_id: seen.append((platform, session_id)) or screenshot,
    )

    response = client.get(
        "/api/connections/medium/browser-connection/screenshot"
    )

    assert response.status_code == 200
    assert response.content == screenshot
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        'attachment; filename="bloghub-medium-browser.png"'
    )
    assert seen == [("medium", "pbs_medium")]


def test_browser_screenshot_requires_owned_active_session(client, monkeypatch):
    other = store.create_user("other@example.com", "password-hash")
    store.start_browser_connection(
        other["id"], "medium", session_id="pbs_foreign",
        organization_id="o_other", app_url="http://localhost/foreign",
    )
    called = []
    monkeypatch.setattr(
        connections_router.runner,
        "capture_browser_screenshot",
        lambda *_args: called.append(True) or b"unexpected",
    )

    response = client.get(
        "/api/connections/medium/browser-connection/screenshot"
    )

    assert response.status_code == 409
    assert called == []


def test_hashnode_browser_login_persists_only_profile_references(client, monkeypatch):
    monkeypatch.setattr(
        connections_router.runner,
        "start_browser_login",
        lambda *_args, **_kwargs: {
            "session_id": "pbs_session",
            "organization_id": "o_org",
            "app_url": "http://localhost:8083/browser-session/pbs_session",
        },
    )
    monkeypatch.setattr(
        connections_router.runner,
        "complete_browser_login",
        lambda *args, **kwargs: {
            "authenticated": True,
            "profile_id": "bp_profile",
            "organization_id": "o_org",
        },
    )

    started = client.post("/api/connections/hashnode/browser-connection")
    assert started.status_code == 201
    assert started.json()["status"] == "waiting_for_login"
    assert started.json()["authorizationUrl"].endswith("pbs_session")

    completed = client.post(
        "/api/connections/hashnode/browser-connection/complete"
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "connected"
    assert "profile_id" not in completed.json()
    persisted = store.get_browser_connection("user_seed", "hashnode")
    assert persisted["skyvern_profile_id"] == "bp_profile"
    schedules = store.list_sync_schedules("user_seed")
    assert [
        (item["platform"], item["interval_seconds"], item["enabled"])
        for item in schedules
    ] == [("hashnode", 60, True)]
    jobs = store.list_jobs("user_seed", queue="sync")
    assert len(jobs) == 1
    assert jobs[0]["payload"] == {
        "platform": "hashnode",
        "scheduled": False,
        "trigger": "browser_connection",
    }

    retried = client.post(
        "/api/connections/hashnode/browser-connection/complete"
    )
    assert retried.status_code == 200
    assert len(store.list_sync_schedules("user_seed")) == 1
    assert len(store.list_jobs("user_seed", queue="sync")) == 1
    raw_url = store._backend._con.execute(
        """SELECT app_url FROM browser_connections
           WHERE user_id='user_seed' AND platform='hashnode'"""
    ).fetchone()[0]
    assert raw_url.startswith("enc:v1:")
    assert "pbs_session" not in raw_url


def test_hashnode_browser_login_rejects_unverified_profile(client, monkeypatch):
    monkeypatch.setattr(
        connections_router.runner,
        "start_browser_login",
        lambda *_args, **_kwargs: {
            "session_id": "pbs_session",
            "organization_id": "o_org",
            "app_url": "http://localhost:8083/browser-session/pbs_session",
        },
    )
    monkeypatch.setattr(
        connections_router.runner,
        "complete_browser_login",
        lambda *args, **kwargs: {
            "authenticated": False,
            "profile_id": "bp_failed",
            "organization_id": "o_org",
        },
    )
    client.post("/api/connections/hashnode/browser-connection")
    completed = client.post(
        "/api/connections/hashnode/browser-connection/complete"
    )
    assert completed.json()["status"] == "failed"
    assert "not completed" in completed.json()["error"]
    persisted = store.get_browser_connection("user_seed", "hashnode")
    assert persisted["skyvern_profile_id"] == "bp_failed"


def test_verifying_browser_login_can_be_canceled_immediately(client, monkeypatch):
    store.start_browser_connection(
        "user_seed", "medium", session_id="pbs_verifying",
        organization_id="o_org", app_url="http://localhost/login",
    )
    store.update_browser_connection("user_seed", "medium", "verifying")
    canceled = []
    monkeypatch.setattr(
        connections_router.runner,
        "cancel_browser_login",
        lambda *args: canceled.append(args),
    )

    response = client.delete("/api/connections/medium/browser-connection")

    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"
    assert store.get_browser_connection("user_seed", "medium") is None
    assert canceled == []


def test_canceled_login_discards_a_late_completion_result(client, monkeypatch):
    store.start_browser_connection(
        "user_seed", "medium", session_id="pbs_late",
        organization_id="o_org", app_url="http://localhost/login",
    )
    deleted_profiles = []

    def complete_after_cancel(*_args, **_kwargs):
        store.delete_browser_connection("user_seed", "medium")
        return {
            "authenticated": True,
            "profile_id": "bp_late",
            "organization_id": "o_org",
        }

    monkeypatch.setattr(
        connections_router.runner, "complete_browser_login", complete_after_cancel,
    )
    monkeypatch.setattr(
        connections_router.runner,
        "delete_browser_profile",
        lambda platform, profile_id: deleted_profiles.append((platform, profile_id)),
    )

    response = client.post("/api/connections/medium/browser-connection/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"
    assert deleted_profiles == [("medium", "bp_late")]
    assert store.get_browser_connection("user_seed", "medium") is None


def test_hashnode_browser_retry_reuses_provider_session_profile(client, monkeypatch):
    store.start_browser_connection(
        "user_seed", "hashnode", session_id="pbs_previous",
        organization_id="o_org", app_url="http://localhost/previous",
        profile_id="bp_identity",
    )
    store.update_browser_connection("user_seed", "hashnode", "failed")
    reused = []
    monkeypatch.setattr(
        connections_router.runner,
        "start_browser_login",
        lambda platform, profile_id: reused.append((platform, profile_id)) or {
            "session_id": "pbs_retry",
            "organization_id": "o_org",
            "app_url": "http://localhost:8083/browser-session/pbs_retry",
        },
    )

    started = client.post("/api/connections/hashnode/browser-connection")

    assert started.status_code == 201
    assert reused == [("hashnode", "bp_identity")]
    persisted = store.get_browser_connection("user_seed", "hashnode")
    assert persisted["skyvern_profile_id"] == "bp_identity"


def test_hashnode_browser_disconnect_deletes_remote_profile(client, monkeypatch):
    store.start_browser_connection(
        "user_seed", "hashnode", session_id="pbs_session",
        organization_id="o_org", app_url="http://localhost/login",
    )
    store.update_browser_connection(
        "user_seed", "hashnode", "connected", profile_id="bp_profile"
    )
    store.upsert_sync_schedule("user_seed", "hashnode", 900)
    deleted = []
    monkeypatch.setattr(
        connections_router.runner,
        "delete_browser_profile",
        lambda platform, profile_id: deleted.append((platform, profile_id)),
    )
    response = client.delete("/api/connections/hashnode/browser-connection")
    assert response.status_code == 200
    assert deleted == [("hashnode", "bp_profile")]
    assert store.get_browser_connection("user_seed", "hashnode") is None
    assert store.list_sync_schedules("user_seed") == []


def test_hashnode_browser_disconnect_retains_profile_when_remote_cleanup_fails(
    client, monkeypatch,
):
    store.start_browser_connection(
        "user_seed", "hashnode", session_id="pbs_session",
        organization_id="o_org", app_url="http://localhost/login",
    )
    store.update_browser_connection(
        "user_seed", "hashnode", "connected", profile_id="bp_profile"
    )

    def unavailable(_platform, _profile_id):
        raise runner.RunnerUnavailable("Skyvern unavailable")

    monkeypatch.setattr(
        connections_router.runner, "delete_browser_profile", unavailable,
    )

    response = client.delete("/api/connections/hashnode/browser-connection")

    assert response.status_code == 503
    assert response.json()["detail"] == "Skyvern unavailable"
    persisted = store.get_browser_connection("user_seed", "hashnode")
    assert persisted["skyvern_profile_id"] == "bp_profile"


def test_medium_browser_login_uses_same_profile_reference_flow(client, monkeypatch):
    started_platforms = []
    completed_platforms = []
    monkeypatch.setattr(
        connections_router.runner,
        "start_browser_login",
        lambda platform, profile_id=None: started_platforms.append((platform, profile_id)) or {
            "session_id": "pbs_medium",
            "organization_id": "o_org",
            "app_url": "http://localhost:8083/browser-session/pbs_medium",
        },
    )
    monkeypatch.setattr(
        connections_router.runner,
        "complete_browser_login",
        lambda platform, *args, **kwargs: completed_platforms.append(platform) or {
            "authenticated": True,
            "profile_id": "bp_medium",
            "organization_id": "o_org",
        },
    )

    started = client.post("/api/connections/medium/browser-connection")
    assert started.status_code == 201
    assert started.json()["platform"] == "medium"
    assert started.json()["authorizationUrl"].endswith("pbs_medium")

    completed = client.post("/api/connections/medium/browser-connection/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "connected"
    assert started_platforms == [("medium", None)]
    assert completed_platforms == ["medium"]
    persisted = store.get_browser_connection("user_seed", "medium")
    assert persisted["skyvern_profile_id"] == "bp_medium"
    assert store.list_sync_schedules("user_seed")[0]["platform"] == "medium"
    jobs = store.list_jobs("user_seed", queue="sync")
    assert len(jobs) == 1
    assert jobs[0]["payload"]["platform"] == "medium"
