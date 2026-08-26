from __future__ import annotations

import importlib.util
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[2] / "cli-runner"
spec = importlib.util.spec_from_file_location(
    "skyvern_browser_under_test", RUNNER / "skyvern_browser.py"
)
skyvern_browser = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(skyvern_browser)


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload
        self.content = b"" if payload is None else b"json"

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_start_login_uses_non_expiring_live_profile_session(monkeypatch):
    seen = {}

    def request(method, url, **kwargs):
        seen.update(method=method, url=url, payload=kwargs["json"])
        return FakeResponse({
            "browser_session_id": "pbs_session123",
            "organization_id": "o_org123",
            "app_url": "http://skyvern-ui:8080/browser-session/pbs_session123",
            "status": "created",
        })

    monkeypatch.setenv("SKYVERN_API_KEY", "local-key")
    monkeypatch.setattr(skyvern_browser.httpx, "request", request)
    result = skyvern_browser.start_hashnode_login()
    assert result["app_url"] == (
        "http://localhost:8083/browser-session/pbs_session123/stream"
        "?embed=true&purpose=hashnode-login"
    )
    assert seen["payload"]["generate_browser_profile"] is True
    assert seen["payload"]["needs_live_view"] is True
    assert seen["payload"]["url"] == "https://hashnode.com/login"
    assert seen["payload"]["timeout"] is None


def test_start_medium_login_uses_medium_signin_url(monkeypatch):
    seen = {}

    def request(method, url, **kwargs):
        seen.update(method=method, url=url, payload=kwargs["json"])
        return FakeResponse({
            "browser_session_id": "pbs_session123",
            "organization_id": "o_org123",
            "app_url": "http://skyvern-ui:8080/browser-session/pbs_session123",
            "status": "created",
        })

    monkeypatch.setenv("SKYVERN_API_KEY", "local-key")
    monkeypatch.setattr(skyvern_browser.httpx, "request", request)
    result = skyvern_browser.start_medium_login()
    assert result["app_url"] == (
        "http://localhost:8083/browser-session/pbs_session123/stream"
        "?embed=true&purpose=medium-login"
    )
    assert seen["payload"]["url"] == "https://medium.com/m/signin"


def test_start_login_reuses_identity_provider_profile(monkeypatch):
    seen = {}

    def request(method, url, **kwargs):
        seen.update(method=method, url=url, payload=kwargs["json"])
        return FakeResponse({
            "browser_session_id": "pbs_session123",
            "organization_id": "o_org123",
            "status": "created",
        })

    monkeypatch.setenv("SKYVERN_API_KEY", "local-key")
    monkeypatch.setattr(skyvern_browser.httpx, "request", request)

    skyvern_browser.start_hashnode_login("bp_identity123")

    assert seen["payload"]["browser_profile_id"] == "bp_identity123"
    assert seen["payload"]["generate_browser_profile"] is False


def test_finish_login_accepts_empty_close_response(monkeypatch, tmp_path):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        if url.endswith("/close"):
            return FakeResponse()
        return FakeResponse({
            "browser_profile_id": "bp_profile123",
            "organization_id": "o_org123",
        })

    monkeypatch.setenv("SKYVERN_API_KEY", "local-key")
    monkeypatch.setattr(skyvern_browser.httpx, "request", request)
    monkeypatch.setattr(skyvern_browser, "SKYVERN_BROWSER_SESSION_ROOT", tmp_path)
    result = skyvern_browser.finish_hashnode_login("pbs_session123", "BlogHub user")
    assert result["profile_id"] == "bp_profile123"
    assert result["profile_dir"] == str(
        tmp_path / "o_org123" / "profiles" / "bp_profile123"
    )
    assert [call[0] for call in calls] == ["POST", "POST"]


def test_finish_login_reuses_profile_without_creating_a_duplicate(monkeypatch, tmp_path):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        return FakeResponse()

    monkeypatch.setenv("SKYVERN_API_KEY", "local-key")
    monkeypatch.setattr(skyvern_browser.httpx, "request", request)
    monkeypatch.setattr(skyvern_browser, "SKYVERN_BROWSER_SESSION_ROOT", tmp_path)

    result = skyvern_browser.finish_hashnode_login(
        "pbs_session123",
        "BlogHub user",
        profile_id="bp_identity123",
        organization_id="o_org123",
    )

    assert result["profile_id"] == "bp_identity123"
    assert result["profile_dir"] == str(
        tmp_path / "o_org123" / "profiles" / "bp_identity123"
    )
    assert len(calls) == 1
    assert calls[0][1].endswith("/v1/browser_sessions/pbs_session123/close")


def test_profile_directory_rejects_path_components():
    try:
        skyvern_browser.profile_directory("o_org123", "../../cookies")
    except ValueError as exc:
        assert "Invalid" in str(exc)
    else:
        raise AssertionError("unsafe profile id was accepted")
