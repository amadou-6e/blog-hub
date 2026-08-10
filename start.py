"""Start the BlogHub backend and the CLI runner as one development stack."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_RUNNER_URL = "http://127.0.0.1:8001"


class LauncherError(RuntimeError):
    pass


@dataclass
class RunnerHandle:
    kind: str
    process: subprocess.Popen | None = None


def find_free_port(start: int = 8082, end: int = 8090) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise LauncherError(f"No free backend port found in range {start}-{end - 1}")


def runner_health(runner_url: str, *, timeout: float = 0.75) -> dict | None:
    try:
        with urlopen(f"{runner_url.rstrip('/')}/health", timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return None


def available_providers(health: dict | None) -> list[str]:
    providers = (health or {}).get("providers", {})
    return sorted(name for name, status in providers.items() if status == "available")


def wait_for_runner(
    runner_url: str,
    *,
    process: subprocess.Popen | None = None,
    timeout: float = 15.0,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = runner_health(runner_url)
        if health:
            return health
        if process is not None and process.poll() is not None:
            raise LauncherError(
                f"CLI runner exited during startup with code {process.returncode}"
            )
        time.sleep(0.25)
    raise LauncherError(f"CLI runner did not become healthy at {runner_url}")


def find_compose_command() -> list[str] | None:
    for command in (["docker", "compose"], ["docker-compose"]):
        try:
            result = subprocess.run(
                [*command, "version"],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return command
    return None


def run_compose_stack(compose_command: list[str], port: int) -> int:
    env = dict(os.environ)
    env["BLOGHUB_PORT"] = str(port)
    result = subprocess.run(
        [*compose_command, "up", "--build"],
        cwd=ROOT,
        env=env,
        check=False,
    )
    return result.returncode


def local_runner_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    config_root = Path(
        env.get("BLOGHUB_AGENT_CONFIG_DIR", ROOT / "data" / "agent-config")
    ).resolve()
    defaults = {
        "RUNNER_HOME": config_root / "home",
        "CLAUDE_CONFIG_DIR": config_root / "claude",
        "CODEX_CONFIG_DIR": config_root / "codex",
    }
    for name, default in defaults.items():
        path = Path(env.get(name, default)).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    return env


def start_local_runner(runner_url: str) -> RunnerHandle:
    parsed = urlparse(runner_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise LauncherError(
            "A local runner requires CLI_RUNNER_URL to use http://localhost"
        )
    port = parsed.port or 8001
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--app-dir",
            str(ROOT / "cli-runner"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=local_runner_environment(),
    )
    return RunnerHandle(kind="local", process=process)


def stop_runner(handle: RunnerHandle | None) -> None:
    if handle is None:
        return
    if handle.kind == "local" and handle.process is not None:
        if handle.process.poll() is None:
            handle.process.terminate()
            try:
                handle.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                handle.process.kill()
                handle.process.wait(timeout=5)


def ensure_runner(runner_url: str, mode: str) -> tuple[RunnerHandle | None, dict | None]:
    if mode == "off":
        return None, None

    health = runner_health(runner_url)
    if health:
        return RunnerHandle(kind="external"), health
    if mode == "external":
        raise LauncherError(f"No CLI runner is reachable at {runner_url}")
    if mode != "local":
        raise LauncherError("Local runner startup requires --runner local")

    handle = start_local_runner(runner_url)
    try:
        return handle, wait_for_runner(runner_url, process=handle.process)
    except LauncherError:
        stop_runner(handle)
        raise


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, help="backend port (default: first free from 8082)")
    parser.add_argument(
        "--runner",
        choices=("auto", "compose", "docker", "local", "external", "off"),
        default=os.environ.get("BLOGHUB_RUNNER_MODE", "auto"),
        help="stack mode; auto, compose, and docker use Docker Compose (default: auto)",
    )
    parser.add_argument("--reload", action="store_true", help="reload a local backend")
    return parser.parse_known_args(argv)


def main(argv: list[str] | None = None) -> int:
    args, uvicorn_args = parse_args(list(argv if argv is not None else sys.argv[1:]))
    runner_url = os.environ.get("CLI_RUNNER_URL", DEFAULT_RUNNER_URL).rstrip("/")
    handle: RunnerHandle | None = None
    try:
        if args.runner in {"auto", "compose", "docker"}:
            if uvicorn_args:
                raise LauncherError(
                    "Uvicorn arguments are only supported with local, external, or off mode"
                )
            compose_command = find_compose_command()
            if not compose_command:
                raise LauncherError(
                    "Docker Compose is required for common startup. Install Docker Desktop "
                    "and enable integration for this WSL distribution"
                )
            port = args.port or 8082
            print(f"\n  BlogHub stack: http://127.0.0.1:{port}/screens/settings/v2.html")
            print("  Runtime:       Docker Compose (backend + cli-runner)\n")
            return run_compose_stack(compose_command, port)

        handle, health = ensure_runner(runner_url, args.runner)
        providers = available_providers(health)
        if args.runner != "off" and not providers:
            raise LauncherError(
                "CLI runner is healthy, but neither claude nor codex is installed"
            )

        port = args.port or find_free_port()
        page_url = f"http://127.0.0.1:{port}/screens/settings/v2.html"
        runner_summary = "disabled" if args.runner == "off" else ", ".join(providers)
        print(f"\n  CLI runner: {runner_url} ({runner_summary})")
        print(f"  BlogHub:    {page_url}\n")

        backend_env = dict(os.environ)
        backend_env["CLI_RUNNER_URL"] = runner_url
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        if args.reload:
            command.append("--reload")
        command.extend(uvicorn_args)
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=backend_env,
            check=False,
        )
        return result.returncode
    except LauncherError as exc:
        print(f"BlogHub startup failed: {exc}", file=sys.stderr)
        print(
            "Use --runner local only for explicit host-CLI troubleshooting, or "
            "--runner off when agent features are intentionally disabled.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        stop_runner(handle)


if __name__ == "__main__":
    raise SystemExit(main())
