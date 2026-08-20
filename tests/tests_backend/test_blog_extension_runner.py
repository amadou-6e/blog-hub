from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException


RUNNER = Path(__file__).resolve().parents[2] / "cli-runner"
if str(RUNNER) not in sys.path:
    sys.path.insert(0, str(RUNNER))
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
    assert by_platform["hashnode"]["capabilities"] == ["create_draft", "publish"]
    assert by_platform["medium"]["capabilities"] == []


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


def test_unsupported_operation_is_rejected_before_browser_launch():
    request = runner_main.BrowserOperationRequest(
        organization_id="o_test", profile_id="bp_test"
    )

    with pytest.raises(HTTPException) as exc_info:
        runner_main.browser_operation("medium", "publish", request)

    assert exc_info.value.status_code == 409
    assert "does not support" in exc_info.value.detail


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
