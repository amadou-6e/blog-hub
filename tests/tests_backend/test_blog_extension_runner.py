from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException


RUNNER = Path(__file__).resolve().parents[2] / "cli-runner"
if str(RUNNER) not in sys.path:
    sys.path.insert(0, str(RUNNER))
from blog_extensions.profile_sessions import clear_profile_session

spec = importlib.util.spec_from_file_location(
    "blog_extension_runner_under_test", RUNNER / "main.py"
)
runner_main = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = runner_main
spec.loader.exec_module(runner_main)


def test_runner_discovers_builtin_extension_capabilities():
    payload = runner_main.browser_extensions()

    by_platform = {item["platform"]: item for item in payload["extensions"]}
    assert by_platform["hashnode"]["capabilities"] == [
        "create_draft", "list_articles", "publish",
    ]
    assert by_platform["medium"]["capabilities"] == [
        "create_draft", "get_article", "list_articles", "publish", "update_article",
    ]


def test_login_dispatch_uses_extension_login_url(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        runner_main,
        "start_browser_login",
        lambda platform, profile_id, login_url: seen.update(
            platform=platform, profile_id=profile_id, login_url=login_url
        ) or {"session_id": "pbs_test"},
    )

    result = runner_main.browser_login("medium")

    assert result == {"session_id": "pbs_test"}
    assert seen["login_url"] == "https://medium.com/m/signin"


def test_login_status_includes_live_authentication_without_finalizing(monkeypatch):
    monkeypatch.setattr(
        runner_main,
        "get_browser_login",
        lambda *_args: {"session_id": "pbs_test", "status": "running"},
    )
    monkeypatch.setattr(
        runner_main,
        "get_live_browser_probe",
        lambda *_args: {
            "url": "https://medium.com/",
            "cookies": [
                {"name": "uid", "domain": ".medium.com", "expires": -1, "present": True},
                {"name": "sid", "domain": ".medium.com", "expires": -1, "present": True},
            ],
        },
    )

    result = runner_main.browser_login_status("medium", "pbs_test")

    assert result["status"] == "running"
    assert result["live_authentication"] == {
        "status": "authenticated",
        "authenticated": True,
        "url": "https://medium.com/",
    }
    assert result["connection_health"] == {
        "protocol_version": 1,
        "status": "connected",
        "reason": "authentication_verified",
        "source": "live_browser_probe",
        "authoritative": True,
    }


def test_login_status_preserves_unknown_probe_state(monkeypatch):
    monkeypatch.setattr(
        runner_main,
        "get_browser_login",
        lambda *_args: {"session_id": "pbs_test", "status": "running"},
    )
    monkeypatch.setattr(
        runner_main,
        "get_live_browser_probe",
        lambda *_args: (_ for _ in ()).throw(
            runner_main.SkyvernUnavailable("probe failed")
        ),
    )

    result = runner_main.browser_login_status("medium", "pbs_test")

    assert result["live_authentication"] == {
        "status": "unknown", "authenticated": None, "url": None,
    }


def test_browser_login_screenshot_returns_non_cacheable_png(monkeypatch):
    screenshot = b"\x89PNG\r\n\x1a\ncurrent-frame"
    monkeypatch.setattr(
        runner_main, "capture_browser_screenshot", lambda *_args: screenshot,
    )

    response = runner_main.browser_login_screenshot("medium", "pbs_test")

    assert response.body == screenshot
    assert response.media_type == "image/png"
    assert response.headers["cache-control"] == "no-store"


def test_profile_logout_uses_extension_session_domains(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(runner_main, "profile_directory", lambda *_args: tmp_path)
    monkeypatch.setattr(
        runner_main,
        "clear_profile_session",
        lambda profile_dir, domains: seen.update(
            profile_dir=profile_dir, domains=domains
        ) or 2,
    )

    result = runner_main.browser_profile_logout(
        "medium",
        "bp_profile",
        runner_main.BrowserProfileSessionRequest(organization_id="o_org"),
    )

    assert result == {"status": "disconnected", "cookies_removed": 2}
    assert seen == {"profile_dir": tmp_path, "domains": ("medium.com",)}


def test_profile_logout_treats_missing_local_profile_as_already_logged_out(
    tmp_path,
):
    assert clear_profile_session(
        tmp_path / "missing-profile", ("medium.com",),
    ) == 0


def test_public_operation_requires_explicit_approval():
    request = runner_main.BrowserOperationRequest(
        organization_id="o_test",
        profile_id="bp_test",
        article=runner_main.BrowserArticleRequest(title="Title", body="Body"),
    )

    with pytest.raises(HTTPException) as exc_info:
        runner_main.browser_operation("hashnode", "publish", request)

    assert exc_info.value.status_code == 409
    assert "approval" in exc_info.value.detail


def test_medium_publish_requires_explicit_approval():
    request = runner_main.BrowserOperationRequest(
        organization_id="o_test", profile_id="bp_test"
    )

    with pytest.raises(HTTPException) as exc_info:
        runner_main.browser_operation("medium", "publish", request)

    assert exc_info.value.status_code == 409
    assert "approval" in exc_info.value.detail


def test_generic_operation_passes_normalized_article_to_runtime(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(runner_main, "profile_directory", lambda *_args: tmp_path)
    monkeypatch.setattr(
        runner_main,
        "execute_operation",
        lambda extension, **kwargs: seen.update(extension=extension, **kwargs)
        or {"success": True, "status": "draft"},
    )
    request = runner_main.BrowserOperationRequest(
        organization_id="o_test",
        profile_id="bp_test",
        article=runner_main.BrowserArticleRequest(
            title="Title", body="Body", tags=["one", "two"]
        ),
    )

    result = runner_main.browser_operation("hashnode", "create_draft", request)

    assert result["success"] is True
    assert seen["operation"].value == "create_draft"
    assert seen["request"].article.tags == ("one", "two")
    assert seen["extension"].manifest.platform == "hashnode"


def test_adapter_exception_is_sanitized_at_runner_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_main, "profile_directory", lambda *_args: tmp_path)

    def fail(*_args, **_kwargs):
        raise RuntimeError(
            "Playwright failed with Cookie: session=browser-secret; theme=dark"
        )

    monkeypatch.setattr(runner_main, "execute_operation", fail)
    request = runner_main.BrowserOperationRequest(
        organization_id="o_test", profile_id="bp_test"
    )

    result = runner_main.browser_operation("hashnode", "create_draft", request)

    assert result["success"] is False
    assert "browser-secret" not in result["error"]
    assert "[redacted]" in result["error"]
    assert result["connection_health"]["status"] == "unknown"
