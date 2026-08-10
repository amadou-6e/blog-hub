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


def test_local_mode_starts_local_runner(monkeypatch):
    handle = start.RunnerHandle(kind="local", process=SimpleNamespace())
    health = {"status": "ok", "providers": {"openai": "available"}}
    monkeypatch.setattr(start, "runner_health", lambda url: None)
    monkeypatch.setattr(start, "start_local_runner", lambda url: handle)
    monkeypatch.setattr(
        start,
        "wait_for_runner",
        lambda url, process=None: health,
    )

    result_handle, result_health = start.ensure_runner(
        start.DEFAULT_RUNNER_URL, "local"
    )

    assert result_handle is handle
    assert result_health == health


def test_common_startup_requires_compose_without_local_fallback(monkeypatch):
    monkeypatch.setattr(start, "find_compose_command", lambda: None)
    monkeypatch.setattr(
        start,
        "ensure_runner",
        lambda *args: (_ for _ in ()).throw(AssertionError("local fallback used")),
    )

    assert start.main([]) == 1


def test_compose_discovery_uses_windows_docker_from_wsl(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0 if command[0] == "docker.exe" else 1)

    monkeypatch.setattr(start.subprocess, "run", run)

    assert start.find_compose_command() == ["docker.exe", "compose"]
    assert calls[-1] == ["docker.exe", "compose", "version"]


def test_runner_orchestrator_rejects_implicit_local_fallback(monkeypatch):
    monkeypatch.setattr(start, "runner_health", lambda url: None)
    monkeypatch.setattr(
        start,
        "start_local_runner",
        lambda *args: (_ for _ in ()).throw(AssertionError("local fallback used")),
    )

    try:
        start.ensure_runner(start.DEFAULT_RUNNER_URL, "auto")
    except start.LauncherError as exc:
        assert "--runner local" in str(exc)
    else:
        raise AssertionError("implicit local fallback was accepted")


def test_common_startup_runs_complete_compose_stack(monkeypatch):
    command = ["docker", "compose"]
    calls = []
    monkeypatch.setattr(start, "find_compose_command", lambda: command)
    monkeypatch.setattr(
        start,
        "run_compose_stack",
        lambda compose, port: calls.append((compose, port)) or 0,
    )

    assert start.main(["--port", "8090"]) == 0
    assert calls == [(command, 8090)]


def test_compose_stack_passes_port_to_compose(monkeypatch):
    calls = []
    monkeypatch.setattr(
        start.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs))
        or SimpleNamespace(returncode=0),
    )

    assert start.run_compose_stack(["docker", "compose"], 8090) == 0
    command, kwargs = calls[0]
    assert command == ["docker", "compose", "up", "--build"]
    assert kwargs["env"]["BLOGHUB_PORT"] == "8090"
    assert kwargs["cwd"] == start.ROOT


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

    assert start.main(["--runner", "external"]) == 1
    assert backend_started == []
