"""Cross-process shared-profile ownership, without a running browser stack."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

RUNNER = Path(__file__).resolve().parents[2] / "cli-runner"
sys.path.insert(0, str(RUNNER))

import skyvern_browser as skyvern
from blog_extensions import profile_sessions as leases
from blog_extensions import runtime
from blog_extensions.contracts import Capability, OperationRequest


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(skyvern, "SKYVERN_BROWSER_SESSION_ROOT", tmp_path)
    directory = skyvern.profile_directory("o_test", "bp_shared")
    directory.mkdir(parents=True)
    (directory / ".skyvern_session_cookies.json").write_text('[{"name":"sid"}]')
    return directory


@pytest.fixture
def api(monkeypatch):
    calls = []

    def request(method, path, payload=None):
        calls.append((method, path, payload))
        return {"browser_session_id": "pbs_test", "organization_id": "o_test"}

    monkeypatch.setattr(skyvern, "_request", request)
    return calls


def child(code, root):
    return subprocess.run(
        [sys.executable, "-c", code, str(root)],
        env={**os.environ, "PYTHONPATH": str(RUNNER)},
        text=True, capture_output=True, timeout=15,
    )


def test_flock_excludes_an_independent_process_and_releases(profile):
    code = """
import sys
from pathlib import Path
from blog_extensions.profile_sessions import local_profile_lease, ProfileBusy
try:
    with local_profile_lease(Path(sys.argv[1])):
        print('acquired')
except ProfileBusy:
    print('busy')
"""
    with leases.local_profile_lease(profile):
        result = child(code, profile)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "busy"
    assert child(code, profile).stdout.strip() == "acquired"


def test_session_marker_survives_creator_process_exit(profile, api):
    result = child("""
import sys
from pathlib import Path
import skyvern_browser as skyvern
skyvern.SKYVERN_BROWSER_SESSION_ROOT = Path(sys.argv[1])
skyvern._request = lambda *args: {'browser_session_id': 'pbs_test', 'organization_id': 'o_test'}
skyvern.start_browser_login('medium', 'bp_shared')
""", profile.parents[2])
    assert result.returncode == 0, result.stderr
    with pytest.raises(leases.ProfileBusy):
        skyvern.start_browser_login("hashnode", "bp_shared")
    with pytest.raises(leases.ProfileBusy):
        leases.clear_profile_session(profile, ("medium.com",))
    assert not api
    skyvern.close_browser_login("pbs_test")
    with leases.local_profile_lease(profile):
        pass


def test_second_platform_session_cannot_share_profile(profile, api):
    skyvern.start_browser_login("medium", "bp_shared")
    with pytest.raises(leases.ProfileBusy):
        skyvern.start_browser_login("hashnode", "bp_shared")
    assert len(api) == 1
    skyvern.start_browser_login("hashnode", "bp_other")
    assert len(api) == 2


def test_runner_lock_prevents_skyvern_start_and_delete(profile, api):
    with leases.local_profile_lease(profile):
        with pytest.raises(leases.ProfileBusy):
            skyvern.start_browser_login("medium", "bp_shared")
        with pytest.raises(leases.ProfileBusy):
            skyvern.delete_browser_profile("bp_shared")
    assert not api


@pytest.mark.parametrize("failure", ["timeout", "invalid_identifiers"])
def test_ambiguous_start_retains_lease_and_cookie_snapshot(profile, monkeypatch, failure):
    snapshot = profile / ".skyvern_session_cookies.json"
    original = snapshot.read_bytes()

    def fail(*args):
        if failure == "timeout":
            raise skyvern.SkyvernUnavailable("timeout")
        return {}

    monkeypatch.setattr(skyvern, "_request", fail)
    with pytest.raises(skyvern.SkyvernUnavailable):
        skyvern.start_browser_login("medium", "bp_shared")
    with pytest.raises(leases.ProfileBusy):
        leases.clear_profile_session(profile, ("medium.com",))
    assert snapshot.read_bytes() == original
    marker = profile.parents[2] / ".profile-leases/bp_shared.json"
    assert json.loads(marker.read_text()) == {"session_id": None}


def test_failed_close_and_unrelated_close_do_not_release(profile, api, monkeypatch):
    skyvern.start_browser_login("medium", "bp_shared")
    skyvern.close_browser_login("pbs_other")
    with pytest.raises(leases.ProfileBusy):
        leases.clear_profile_session(profile, ("medium.com",))

    def fail(*args):
        raise skyvern.SkyvernUnavailable("close failed")

    monkeypatch.setattr(skyvern, "_request", fail)
    with pytest.raises(skyvern.SkyvernUnavailable):
        skyvern.close_browser_login("pbs_test")
    with pytest.raises(leases.ProfileBusy):
        with leases.local_profile_lease(profile):
            pass


def test_successful_close_releases_and_keeps_lock_inode(profile, api):
    skyvern.start_browser_login("medium", "bp_shared")
    lock = profile.parents[2] / ".profile-leases/bp_shared.lock"
    inode = lock.stat().st_ino
    skyvern.close_browser_login("pbs_test")
    skyvern.start_browser_login("hashnode", "bp_shared")
    assert lock.stat().st_ino == inode


def test_corrupt_marker_fails_closed(profile):
    with leases.local_profile_lease(profile) as marker:
        marker.write_text("{")
    with pytest.raises(leases.ProfileBusy):
        leases.clear_profile_session(profile, ("medium.com",))


def test_runtime_busy_does_not_launch_browser(profile, api, monkeypatch):
    monkeypatch.setitem(
        sys.modules, "patchright.sync_api", SimpleNamespace(
            sync_playwright=lambda: pytest.fail("busy profile must not launch Playwright"),
        ),
    )
    skyvern.start_browser_login("medium", "bp_shared")
    extension = SimpleNamespace(manifest=SimpleNamespace(capabilities=(Capability.LIST_ARTICLES,)))
    with pytest.raises(leases.ProfileBusy):
        runtime.execute_operation(
            extension, profile_dir=profile, operation=Capability.LIST_ARTICLES,
            request=OperationRequest(),
        )


def test_runtime_error_closes_context_and_releases_lease(profile, monkeypatch):
    from contextlib import contextmanager

    closed = []

    def fail(*args):
        raise RuntimeError("adapter failed")

    context = SimpleNamespace(pages=[object()], close=lambda: closed.append(True))

    @contextmanager
    def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a, **kw: context))

    monkeypatch.setitem(sys.modules, "patchright.sync_api", SimpleNamespace(sync_playwright=playwright))
    extension = SimpleNamespace(
        manifest=SimpleNamespace(capabilities=(Capability.LIST_ARTICLES,)),
        operations=SimpleNamespace(execute=fail),
    )
    with pytest.raises(RuntimeError, match="adapter failed"):
        runtime.execute_operation(
            extension, profile_dir=profile, operation=Capability.LIST_ARTICLES,
            request=OperationRequest(),
        )
    assert closed == [True]
    with leases.local_profile_lease(profile):
        pass


def test_logout_holds_lease_until_snapshot_update_finishes(profile, monkeypatch):
    from contextlib import contextmanager

    phases = []

    def check(phase):
        with pytest.raises(leases.ProfileBusy):
            with leases.local_profile_lease(profile):
                pass
        phases.append(phase)

    context = SimpleNamespace(close=lambda: check("close"))

    def launch(*args, **kwargs):
        check("launch")
        return context

    @contextmanager
    def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))

    monkeypatch.setitem(sys.modules, "patchright.sync_api", SimpleNamespace(sync_playwright=playwright))
    monkeypatch.setattr(leases, "clear_context_session", lambda *args: check("cookies") or 2)
    monkeypatch.setattr(leases, "_clear_cookie_snapshot", lambda *args: check("snapshot"))
    assert leases.clear_profile_session(profile, ("medium.com",)) == 2
    assert phases == ["launch", "cookies", "close", "snapshot"]
    with leases.local_profile_lease(profile):
        pass


def test_crash_during_create_keeps_pending_marker(profile, api):
    result = child("""
import os, sys
from pathlib import Path
import skyvern_browser as skyvern
skyvern.SKYVERN_BROWSER_SESSION_ROOT = Path(sys.argv[1])
skyvern._request = lambda *args: os._exit(17)
skyvern.start_browser_login('medium', 'bp_shared')
""", profile.parents[2])
    assert result.returncode == 17
    with pytest.raises(leases.ProfileBusy):
        skyvern.start_browser_login("medium", "bp_shared")
    assert not api


@pytest.fixture
def runner_main():
    spec = importlib.util.spec_from_file_location("lease_runner_under_test", RUNNER / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("action", ["login", "logout", "delete", "operation"])
def test_runner_busy_contract_is_explicit_and_non_destructive(profile, api, runner_main, action):
    skyvern.start_browser_login("medium", "bp_shared")
    snapshot = profile / ".skyvern_session_cookies.json"
    original = snapshot.read_bytes()
    if action == "login":
        result = runner_main.browser_login("hashnode", runner_main.HashnodeBrowserLoginRequest(profile_id="bp_shared"))
    elif action == "logout":
        result = runner_main.browser_profile_logout("medium", "bp_shared", runner_main.BrowserProfileSessionRequest(organization_id="o_test"))
    elif action == "delete":
        result = runner_main.browser_profile_delete("medium", "bp_shared")
    else:
        result = runner_main.browser_operation("medium", "list_articles", runner_main.BrowserOperationRequest(organization_id="o_test", profile_id="bp_shared"))
    assert result == {"status": "busy", "success": False, "error": "Browser profile is busy"}
    assert snapshot.read_bytes() == original
    assert len(api) == 1


@pytest.mark.parametrize("method,path,payload,code", [
    ("POST", "/browser/medium/login", {"profile_id": "bp_shared"}, 201),
    ("POST", "/browser/medium/profiles/bp_shared/logout", {"organization_id": "o_test"}, 200),
    ("DELETE", "/browser/medium/profiles/bp_shared", None, 200),
    ("POST", "/browser/medium/operations/list_articles", {"organization_id": "o_test", "profile_id": "bp_shared"}, 200),
])
def test_http_busy_is_a_normal_payload_not_an_auth_failure(profile, api, runner_main, method, path, payload, code):
    from fastapi.testclient import TestClient

    skyvern.start_browser_login("medium", "bp_shared")
    response = TestClient(runner_main.app).request(method, path, json=payload)
    assert response.status_code == code
    assert response.json() == {"status": "busy", "success": False, "error": "Browser profile is busy"}
    assert len(api) == 1
