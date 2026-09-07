from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import Event

import pytest

import backend.store as store
from backend.routers import connections
from backend.services import cli_runner as runner

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli-runner"))
from blog_extensions.profile_sessions import ProfileBusy, local_profile_lease, clear_context_session


@pytest.mark.parametrize("completion_fails", [False, True])
def test_cancel_verifying_shared_profile_defers_logout_until_lease_released(
    client, monkeypatch, tmp_path, completion_fails,
):
    profile = tmp_path / "o_org/profiles/bp_shared"
    profile.mkdir(parents=True)
    for platform in ("hashnode", "medium"):
        store.start_browser_connection(
            "user_seed", platform, session_id=f"pbs_{platform}",
            organization_id="o_org", profile_id="bp_shared",
            app_url="http://localhost/login",
        )
    store.update_browser_connection("user_seed", "hashnode", "connected")
    secondary = store.get_browser_connection("user_seed", "hashnode")
    entered, release = Event(), Event()
    calls = []
    cookies = [
        {"name": "sid", "domain": ".medium.com", "path": "/"},
        {"name": "sid", "domain": ".hashnode.com", "path": "/"},
        {"name": "sid", "domain": "identity.test", "path": "/"},
    ]

    class Context:
        def cookies(self):
            return list(cookies)

        def clear_cookies(self, **cookie):
            cookies.remove(cookie)

    def complete(*args, **kwargs):
        with local_profile_lease(profile):
            entered.set()
            assert release.wait(10)
        if completion_fails:
            raise runner.RunnerUnavailable("verification failed")
        return {"authenticated": True, "organization_id": "o_org", "profile_id": "bp_shared"}

    def logout(platform, organization, profile_id):
        assert release.is_set(), "Cancel must not attempt logout during verification"
        with local_profile_lease(profile):
            clear_context_session(Context(), ("medium.com",))
            calls.append((platform, organization, profile_id))

    monkeypatch.setattr(runner, "complete_browser_login", complete)
    monkeypatch.setattr(runner, "get_browser_login", lambda *args: {"status": "running"})
    monkeypatch.setattr(runner, "logout_browser_profile", logout)
    monkeypatch.setattr(runner, "delete_browser_profile", lambda *args: pytest.fail("shared profile deletion"))
    monkeypatch.setattr(runner, "cancel_browser_login", lambda *args: pytest.fail("close during verification"))
    monkeypatch.setattr(runner, "start_browser_login", lambda *args: pytest.fail("auth before cleanup"))

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/api/connections/medium/browser-connection/complete")
        try:
            assert entered.wait(10)
            canceled = client.delete("/api/connections/medium/browser-connection")
            assert canceled.status_code == 200
            assert canceled.json()["status"] == "disconnected"
            assert calls == []
            public = client.get("/api/connections/medium/browser-connection").json()
            assert public["status"] == "disconnected"
            assert public["browserSession"] is None
            assert public["error"] is None
            assert public["durableConnection"]["profileSaved"] is True
            assert client.post("/api/connections/medium/browser-connection").status_code == 409
        finally:
            release.set()
        late = future.result(timeout=10)

    assert late.status_code == 200, late.text
    assert late.json()["status"] == "disconnected"
    persisted = store.get_browser_connection("user_seed", "medium")
    assert persisted["status"] == "disconnected"
    assert persisted["skyvern_profile_id"] == "bp_shared"
    assert persisted["skyvern_session_id"] is None
    assert persisted["error"] is None
    assert calls == [("medium", "o_org", "bp_shared")]
    assert [cookie["domain"] for cookie in cookies] == [".hashnode.com", "identity.test"]
    assert store.get_browser_connection("user_seed", "hashnode") == secondary


def test_failed_deferred_logout_keeps_auth_blocked(client, monkeypatch):
    store.start_browser_connection(
        "user_seed", "medium", session_id="pbs_test", organization_id="o_org",
        profile_id="bp_shared", app_url="http://localhost/login",
    )

    def complete(*args, **kwargs):
        assert client.delete("/api/connections/medium/browser-connection").status_code == 200
        return {"authenticated": True, "organization_id": "o_org", "profile_id": "bp_shared"}

    def busy(*args):
        raise runner.RunnerBusy()

    monkeypatch.setattr(runner, "complete_browser_login", complete)
    monkeypatch.setattr(runner, "logout_browser_profile", busy)
    monkeypatch.setattr(runner, "get_browser_login", lambda *args: {"status": "closed"})
    assert client.post("/api/connections/medium/browser-connection/complete").status_code == 409
    assert store.get_browser_connection("user_seed", "medium")["status"] == "disconnected"
    assert client.post("/api/connections/medium/browser-connection").status_code == 409


@pytest.mark.parametrize("remote_status", ["closed", "completed"])
def test_connect_recovers_lost_callback_only_after_profile_lease_released(
    client, monkeypatch, tmp_path, remote_status,
):
    profile = tmp_path / "o_org/profiles/bp_shared"
    profile.mkdir(parents=True)
    store.start_browser_connection(
        "user_seed", "medium", session_id="pbs_old", organization_id="o_org",
        profile_id="bp_shared", app_url="http://localhost/login",
    )
    store.update_browser_connection("user_seed", "medium", "verifying")
    assert client.delete("/api/connections/medium/browser-connection").status_code == 200
    pending = store.get_browser_connection("user_seed", "medium")
    calls = []

    def logout(*args):
        try:
            with local_profile_lease(profile):
                calls.append("logout")
        except ProfileBusy:
            raise runner.RunnerBusy() from None

    def start(platform, profile_id):
        assert calls == ["logout"]
        assert profile_id == "bp_shared"
        calls.append("start")
        return {"session_id": "pbs_new", "organization_id": "o_org", "app_url": "http://localhost/new"}

    monkeypatch.setattr(runner, "get_browser_login", lambda *args: {"status": remote_status})
    monkeypatch.setattr(runner, "logout_browser_profile", logout)
    monkeypatch.setattr(runner, "start_browser_login", start)
    monkeypatch.setattr(runner, "delete_browser_profile", lambda *args: pytest.fail("must retain shared profile"))
    # No completion callback will arrive, as after a backend restart.
    with local_profile_lease(profile):
        assert client.post("/api/connections/medium/browser-connection").status_code == 409
    assert store.get_browser_connection("user_seed", "medium") == pending
    assert calls == []
    restarted = client.post("/api/connections/medium/browser-connection")
    assert restarted.status_code == 201, restarted.text
    assert calls == ["logout", "start"]
    current = store.get_browser_connection("user_seed", "medium")
    assert current["skyvern_session_id"] == "pbs_new"
    assert current["skyvern_profile_id"] == "bp_shared"
    assert current["error"] is None


@pytest.mark.parametrize("status", ["running", "created", "unknown", None, "probe_error"])
def test_recovery_does_not_infer_closed_session(client, monkeypatch, status):
    store.start_browser_connection(
        "user_seed", "medium", session_id="pbs_old", organization_id="o_org",
        profile_id="bp_shared", app_url="http://localhost/login",
    )
    store.update_browser_connection("user_seed", "medium", "verifying")
    assert client.delete("/api/connections/medium/browser-connection").status_code == 200
    pending = store.get_browser_connection("user_seed", "medium")

    def probe(*args):
        if status == "probe_error":
            raise runner.RunnerUnavailable("probe failed")
        return {"status": status}

    monkeypatch.setattr(runner, "get_browser_login", probe)
    monkeypatch.setattr(runner, "logout_browser_profile", lambda *args: pytest.fail("unconfirmed close"))
    monkeypatch.setattr(runner, "start_browser_login", lambda *args: pytest.fail("unconfirmed close"))
    response = client.post("/api/connections/medium/browser-connection")
    assert response.status_code == (503 if status == "probe_error" else 409)
    assert store.get_browser_connection("user_seed", "medium") == pending
