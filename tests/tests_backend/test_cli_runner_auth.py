from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _runner_module():
    path = Path(__file__).resolve().parents[2] / "cli-runner" / "main.py"
    spec = importlib.util.spec_from_file_location("bloghub_cli_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runner_redacts_callback_secrets_and_device_codes():
    runner = _runner_module()
    reason = runner._safe_reason(
        "failed https://localhost/callback?code=secret&state=temporary ABCD-EFGH"
    )
    assert "secret" not in reason
    assert "temporary" not in reason
    assert "ABCD-EFGH" not in reason


def test_runner_normalizes_actionable_failure_states():
    runner = _runner_module()
    assert runner._failure_status("access denied")[0] == "rejected"
    assert runner._failure_status("429 too many requests")[0] == "rate_limited"
    assert runner._failure_status("authorization expired")[0] == "expired"
    assert runner._failure_status("login timed out")[0] == "timed_out"


def test_task_request_accepts_an_ephemeral_api_key():
    runner = _runner_module()
    request = runner.TaskRequest(
        provider="openai", task="generate", article_md="prompt", api_key="secret"
    )
    assert request.api_key == "secret"
