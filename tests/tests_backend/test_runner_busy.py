"""Busy is contention, never evidence that a saved profile must be replaced."""
import httpx
import pytest

from backend.services import cli_runner as runner
from backend.services import connection_health
from backend.routers import connections
import backend.store as store


BUSY = {"status": "busy", "success": False, "error": "Browser profile is busy"}


def mock_runner(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(runner, "_client", lambda: httpx.Client(
        base_url="http://runner", transport=transport,
    ))


CALLS = [
    lambda: runner.health(),
    lambda: runner.logout("openai"),
    lambda: runner.start_browser_login("medium", "bp_shared"),
    lambda: runner.get_browser_login("medium", "pbs_test"),
    lambda: runner.cancel_browser_login("medium", "pbs_test"),
    lambda: runner.complete_browser_login("medium", "pbs_test", "test"),
    lambda: runner.delete_browser_profile("medium", "bp_shared"),
    lambda: runner.logout_browser_profile("medium", "o_org", "bp_shared"),
    lambda: runner.browser_operation("medium", "list_articles", organization_id="o_org", profile_id="bp_shared"),
    lambda: runner.capture_browser_screenshot("medium", "pbs_test"),
]


@pytest.mark.parametrize("call", CALLS)
@pytest.mark.parametrize("status", [200, 201, 409])
def test_all_browser_clients_raise_typed_busy(monkeypatch, call, status):
    mock_runner(monkeypatch, lambda request: httpx.Response(status, json=BUSY))
    with pytest.raises(runner.RunnerBusy):
        call()


def seed(platform="medium", status="connected"):
    store.start_browser_connection(
        "user_seed", platform, session_id="pbs_test", organization_id="o_org",
        app_url="http://localhost/login", profile_id="bp_shared",
    )
    if status != "waiting_for_login":
        store.update_browser_connection("user_seed", platform, status)
    return store.get_browser_connection("user_seed", platform)


def assert_preserved(before, platform="medium"):
    after = store.get_browser_connection("user_seed", platform)
    for key in ("status", "skyvern_profile_id", "skyvern_session_id", "skyvern_organization_id", "error"):
        assert after[key] == before[key]


@pytest.mark.parametrize("method,path,state", [
    ("POST", "/browser-connection", "connected"),
    ("GET", "/browser-connection", "waiting_for_login"),
    ("POST", "/browser-connection/complete", "waiting_for_login"),
    ("DELETE", "/browser-connection", "connected"),
    ("DELETE", "/browser-connection", "waiting_for_login"),
    ("POST", "/sync", "connected"),
    ("GET", "/drafts", "connected"),
    ("GET", "/drafts/story1", "connected"),
    ("GET", "/browser-connection/screenshot", "waiting_for_login"),
])
def test_backend_returns_409_without_dropping_profile_or_health(client, monkeypatch, method, path, state):
    before = seed(status=state)
    connection_health.record_evidence(store, "user_seed", "medium", {
        "status": "connected", "reason": "authentication_verified",
        "source": "live_browser_probe", "authoritative": True,
    })
    health = store.get_connection_health("user_seed", "medium")
    calls = []

    def busy(request):
        calls.append(request)
        return httpx.Response(201, json=BUSY)

    mock_runner(monkeypatch, busy)
    response = client.request(method, "/api/connections/medium" + path)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": BUSY}
    assert_preserved(before)
    assert store.get_connection_health("user_seed", "medium") == health
    assert len(calls) == 1


@pytest.mark.parametrize("error", [runner.RunnerBusy(), runner.RunnerUnavailable("transport failed")])
def test_shared_profile_start_never_falls_back_on_busy_or_transport(client, monkeypatch, error):
    before = seed("hashnode")
    attempts = []

    def fail(platform, profile_id):
        attempts.append(profile_id)
        raise error

    monkeypatch.setattr(runner, "start_browser_login", fail)
    response = client.post("/api/connections/medium/browser-connection")
    assert response.status_code == (409 if isinstance(error, runner.RunnerBusy) else 503)
    assert attempts == ["bp_shared"]
    assert_preserved(before, "hashnode")
    assert store.get_browser_connection("user_seed", "medium") is None


@pytest.mark.parametrize("error", [runner.RunnerBusy(), runner.RunnerUnavailable("transport failed")])
def test_failed_cancel_prevents_replacement_session(client, monkeypatch, error):
    before = seed(status="waiting_for_login")

    def fail(*args):
        raise error

    monkeypatch.setattr(runner, "cancel_browser_login", fail)
    monkeypatch.setattr(runner, "start_browser_login", lambda *args: pytest.fail("must not create a second session"))
    response = client.post("/api/connections/medium/browser-connection")
    assert response.status_code == (409 if isinstance(error, runner.RunnerBusy) else 503)
    assert_preserved(before)


def test_busy_during_detail_hydration_is_not_swallowed(monkeypatch):
    def handle(request):
        if request.url.path.endswith("list_articles"):
            return httpx.Response(200, json={"success": True, "articles": [{"remote_id": "story1"}]})
        return httpx.Response(200, json=BUSY)

    mock_runner(monkeypatch, handle)
    with pytest.raises(runner.RunnerBusy):
        runner.medium_browser_articles(organization_id="o_org", profile_id="bp_shared")


@pytest.mark.parametrize("phase", ["cancel", "fresh_start"])
def test_ownership_mismatch_busy_keeps_saved_reference(client, monkeypatch, phase):
    before = seed("hashnode")
    attempts = []

    def start(platform, profile_id):
        attempts.append(profile_id)
        if profile_id is None:
            raise runner.RunnerBusy()
        return {"session_id": "pbs_new", "organization_id": "o_different", "app_url": "http://localhost/new"}

    def cancel(*args):
        if phase == "cancel":
            raise runner.RunnerBusy()

    monkeypatch.setattr(runner, "start_browser_login", start)
    monkeypatch.setattr(runner, "cancel_browser_login", cancel)
    response = client.post("/api/connections/medium/browser-connection")
    assert response.status_code == 409
    assert attempts == (["bp_shared"] if phase == "cancel" else ["bp_shared", None])
    assert_preserved(before, "hashnode")


def test_generated_profile_cleanup_busy_is_not_reported_as_success(monkeypatch):
    mock_runner(monkeypatch, lambda request: httpx.Response(200, json=BUSY))
    with pytest.raises(connections.HTTPException) as exc:
        connections._delete_generated_profile("medium", {}, {"profile_id": "bp_new"})
    assert exc.value.status_code == 409


@pytest.mark.parametrize("state", ["waiting_for_login", "failed"])
def test_reconnect_retains_interrupted_profile(client, monkeypatch, state):
    seed(status=state)
    calls = []

    def start(platform, profile_id):
        calls.append(profile_id)
        return {"session_id": "pbs_new", "organization_id": "o_org", "app_url": "http://localhost/new"}

    monkeypatch.setattr(runner, "cancel_browser_login", lambda *args: None)
    monkeypatch.setattr(runner, "start_browser_login", start)
    response = client.post("/api/connections/medium/browser-connection")
    assert response.status_code == 201
    assert calls == ["bp_shared"]
    assert store.get_browser_connection("user_seed", "medium")["skyvern_profile_id"] == "bp_shared"


def test_reconnect_during_verification_does_not_create_another_session(client, monkeypatch):
    before = seed(status="verifying")
    monkeypatch.setattr(runner, "start_browser_login", lambda *args: pytest.fail("verification in progress"))
    response = client.post("/api/connections/medium/browser-connection")
    assert response.status_code == 409
    assert_preserved(before)
