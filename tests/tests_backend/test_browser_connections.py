from __future__ import annotations

import backend.routers.connections as connections_router
import backend.services.cli_runner as runner
import backend.store as store


def test_hashnode_browser_login_persists_only_profile_references(client, monkeypatch):
    monkeypatch.setattr(
        connections_router.runner,
        "start_hashnode_browser_login",
        lambda *_args: {
            "session_id": "pbs_session",
            "organization_id": "o_org",
            "app_url": "http://localhost:8083/browser-session/pbs_session",
        },
    )
    monkeypatch.setattr(
        connections_router.runner,
        "complete_hashnode_browser_login",
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
        "start_hashnode_browser_login",
        lambda *_args: {
            "session_id": "pbs_session",
            "organization_id": "o_org",
            "app_url": "http://localhost:8083/browser-session/pbs_session",
        },
    )
    monkeypatch.setattr(
        connections_router.runner,
        "complete_hashnode_browser_login",
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
        "start_hashnode_browser_login",
        lambda profile_id: reused.append(profile_id) or {
            "session_id": "pbs_retry",
            "organization_id": "o_org",
            "app_url": "http://localhost:8083/browser-session/pbs_retry",
        },
    )

    started = client.post("/api/connections/hashnode/browser-connection")

    assert started.status_code == 201
    assert reused == ["bp_identity"]
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
        "delete_hashnode_browser_profile",
        lambda profile_id: deleted.append(profile_id),
    )
    response = client.delete("/api/connections/hashnode/browser-connection")
    assert response.status_code == 200
    assert deleted == ["bp_profile"]
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

    def unavailable(_profile_id):
        raise runner.RunnerUnavailable("Skyvern unavailable")

    monkeypatch.setattr(
        connections_router.runner, "delete_hashnode_browser_profile", unavailable,
    )

    response = client.delete("/api/connections/hashnode/browser-connection")

    assert response.status_code == 503
    assert response.json()["detail"] == "Skyvern unavailable"
    persisted = store.get_browser_connection("user_seed", "hashnode")
    assert persisted["skyvern_profile_id"] == "bp_profile"
