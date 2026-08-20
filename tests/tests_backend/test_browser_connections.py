from __future__ import annotations

import backend.routers.connections as connections_router
import backend.services.cli_runner as runner
import backend.store as store


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
