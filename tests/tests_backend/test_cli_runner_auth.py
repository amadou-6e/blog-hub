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


def test_runner_redacts_browser_adapter_credentials():
    runner = _runner_module()
    reason = runner._safe_reason(
        "request failed Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature "
        "Cookie: session=browser-secret; csrf=private api_key=sk-adapter-secret123"
    )
    assert "eyJhbGci" not in reason
    assert "browser-secret" not in reason
    assert "private" not in reason
    assert "sk-adapter" not in reason
    assert "[redacted]" in reason


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


def test_runner_normalizes_claude_text_tools_and_permission_requests():
    runner = _runner_module()
    started = runner._normalize_chat_event("anthropic", {
        "type": "stream_event", "event": {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "id": "read-1", "name": "Read"},
        },
    })
    delta = runner._normalize_chat_event("anthropic", {
        "type": "stream_event", "event": {
            "type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"},
        },
    })
    result = runner._normalize_chat_event("anthropic", {
        "type": "result", "result": "Hello", "session_id": "native-1",
        "permission_denials": [{"tool_name": "Edit", "path": "article.md"}],
    })

    assert started[0]["name"] == "Read"
    assert delta == [{"type": "assistant_delta", "text": "Hello"}]
    assert {event["type"] for event in result} == {
        "assistant_message", "approval_required", "checkpoint"
    }


def test_runner_normalizes_codex_tool_and_message_events():
    runner = _runner_module()
    tool = {"id": "cmd-1", "type": "command_execution", "command": "cat article.md"}
    assert runner._normalize_chat_event(
        "openai", {"type": "item.started", "item": tool}
    )[0]["type"] == "tool_started"
    assert runner._normalize_chat_event("openai", {
        "type": "item.completed", "item": {"type": "agent_message", "text": "Done"},
    }) == [{"type": "assistant_message", "text": "Done"}]


def test_codex_receives_article_from_audited_runner_tool_without_shell_requirement():
    runner = _runner_module()
    prompt = runner._chat_prompt(
        "openai", "/tmp/chat/article.md", "# Synthetic\n\nSafe content.",
        [{"role": "user", "content": "Review it"}],
    )
    assert "audited read_article tool" in prompt
    assert "# Synthetic" in prompt
    assert "Do not invoke command execution" in prompt
    assert "<!-- bloghub-agent: COMMAND -->" in prompt
    assert "BLOGHUB_ARTICLE_START" in prompt
    assert "all other article prose" in prompt
