from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import struct

import pytest


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


class FakeWebSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def send(self, message):
        self.sent.append(message)

    def recv(self, timeout=None):
        return next(self.messages)


def _png(width=1920, height=1200, payload=b""):
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + struct.pack(">II", width, height)
        + payload
    )


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


def test_live_browser_probe_returns_only_sanitized_evidence(monkeypatch):
    seen = {}
    socket = FakeWebSocket([
        '{"kind":"login-state","url":"https://user:password@medium.com/?secret=1#fragment",'
        '"cookies":[{"name":"sid","domain":".medium.com","expires":1999999999,'
        '"present":true,"value":"must-not-escape"}]}'
    ])
    monkeypatch.setattr(skyvern_browser, "_api_key", lambda: "local-api-key")

    def connect(url, **kwargs):
        seen.update(url=url, kwargs=kwargs)
        return socket

    monkeypatch.setattr(
        skyvern_browser, "websocket_connect", connect,
    )

    probe = skyvern_browser.get_live_browser_probe("pbs_session123")

    assert probe == {
        "url": "https://medium.com/",
        "cookies": [{
            "name": "sid", "domain": ".medium.com",
            "expires": 1999999999, "present": True,
        }],
    }
    assert socket.sent == ['{"kind":"get-login-state"}']
    assert "apikey=local-api-key" in seen["url"]
    assert "token=" not in seen["url"]
    assert "local-api-key" not in repr(probe)
    assert "must-not-escape" not in repr(probe)


def test_browser_screenshot_exports_a_bounded_png(monkeypatch):
    screenshot = _png(payload=b"current-frame")
    socket = FakeWebSocket([
        json.dumps({"status": "running"}),
        json.dumps({
            "status": "running",
            "format": "png",
            "screenshot": base64.b64encode(screenshot).decode(),
        }),
    ])
    seen = {}
    monkeypatch.setattr(
        skyvern_browser,
        "get_browser_login",
        lambda *_args: {"status": "running"},
    )
    monkeypatch.setattr(skyvern_browser, "_api_key", lambda: "local-api-key")

    def connect(url, **kwargs):
        seen.update(url=url, kwargs=kwargs)
        return socket

    monkeypatch.setattr(skyvern_browser, "websocket_connect", connect)

    assert skyvern_browser.capture_browser_screenshot("pbs_session123") == screenshot
    assert "/v1/stream/browser_sessions/pbs_session123" in seen["url"]
    assert "apikey=local-api-key" in seen["url"]
    assert seen["kwargs"]["max_size"] == skyvern_browser._SCREENSHOT_MAX_BYTES * 2


def test_browser_screenshot_rejects_malformed_png(monkeypatch):
    socket = FakeWebSocket([json.dumps({
        "status": "running",
        "format": "png",
        "screenshot": base64.b64encode(b"not-a-png").decode(),
    })])
    monkeypatch.setattr(
        skyvern_browser,
        "get_browser_login",
        lambda *_args: {"status": "running"},
    )
    monkeypatch.setattr(skyvern_browser, "_api_key", lambda: "key")
    monkeypatch.setattr(
        skyvern_browser, "websocket_connect", lambda *_args, **_kwargs: socket,
    )

    with pytest.raises(
        skyvern_browser.SkyvernUnavailable, match="invalid screenshot"
    ):
        skyvern_browser.capture_browser_screenshot("pbs_session123")


def test_browser_screenshot_rejects_oversized_dimensions(monkeypatch):
    socket = FakeWebSocket([json.dumps({
        "status": "running",
        "format": "png",
        "screenshot": base64.b64encode(_png(width=5000, height=1200)).decode(),
    })])
    monkeypatch.setattr(
        skyvern_browser,
        "get_browser_login",
        lambda *_args: {"status": "running"},
    )
    monkeypatch.setattr(skyvern_browser, "_api_key", lambda: "key")
    monkeypatch.setattr(
        skyvern_browser, "websocket_connect", lambda *_args, **_kwargs: socket,
    )

    with pytest.raises(
        skyvern_browser.SkyvernUnavailable, match="dimensions exceed"
    ):
        skyvern_browser.capture_browser_screenshot("pbs_session123")


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
