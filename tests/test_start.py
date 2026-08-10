from __future__ import annotations

from types import SimpleNamespace

import start


def test_local_runner_environment_creates_persistent_config_dirs(tmp_path):
    env = start.local_runner_environment(
        {"BLOGHUB_AGENT_CONFIG_DIR": str(tmp_path / "agent-config")}
    )

    assert env["RUNNER_HOME"] == str((tmp_path / "agent-config" / "home").resolve())
    assert env["CLAUDE_CONFIG_DIR"].endswith("agent-config/claude")
    assert env["CODEX_CONFIG_DIR"].endswith("agent-config/codex")
    assert all(
        start.Path(env[name]).is_dir()
        for name in ("RUNNER_HOME", "CLAUDE_CONFIG_DIR", "CODEX_CONFIG_DIR")
    )


def test_auto_mode_reuses_a_healthy_runner(monkeypatch):
    health = {"status": "ok", "providers": {"openai": "available"}}
    monkeypatch.setattr(start, "runner_health", lambda url: health)
    monkeypatch.setattr(
        start, "start_local_runner", lambda url: (_ for _ in ()).throw(AssertionError())
    )

    handle, result = start.ensure_runner(start.DEFAULT_RUNNER_URL, "auto")

    assert handle.kind == "external"
    assert result == health


def test_auto_mode_falls_back_to_local_runner(monkeypatch):
    handle = start.RunnerHandle(kind="local", process=SimpleNamespace())
    health = {"status": "ok", "providers": {"openai": "available"}}
    monkeypatch.setattr(start, "runner_health", lambda url: None)
    monkeypatch.setattr(start, "find_compose_command", lambda: None)
    monkeypatch.setattr(start, "start_local_runner", lambda url: handle)
    monkeypatch.setattr(
        start,
        "wait_for_runner",
        lambda url, process=None: health,
    )

    result_handle, result_health = start.ensure_runner(
        start.DEFAULT_RUNNER_URL, "auto"
    )

    assert result_handle is handle
    assert result_health == health


def test_main_fails_before_backend_when_runner_has_no_provider(monkeypatch):
    health = {
        "status": "ok",
        "providers": {"anthropic": "missing", "openai": "missing"},
    }
    monkeypatch.setattr(
        start,
        "ensure_runner",
        lambda url, mode: (start.RunnerHandle(kind="external"), health),
    )
    backend_started = []
    monkeypatch.setattr(
        start.subprocess,
        "run",
        lambda *args, **kwargs: backend_started.append(args) or SimpleNamespace(returncode=0),
    )

    assert start.main([]) == 1
    assert backend_started == []
