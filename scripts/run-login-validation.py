#!/usr/bin/env python3
"""Run the disposable login stack without exporting credentials or raw logs."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import struct
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "validation/compose.yml"
HEX_ID = re.compile(r"(?:sha256:)?[0-9a-f]{12,64}\Z")
JUNIT_REPORTS = ("login.xml", "restart-prepare.xml", "restart-after.xml")
VERSION_KEYS = ("python", "fastapi", "skyvern", "patchright", "playwright", "pytest",
                "chromium_patchright", "chromium_playwright", "chromium_skyvern")
EXCEPTION_NAMES = frozenset({
    "AssertionError", "TimeoutError", "HTTPStatusError", "ConnectError", "ReadTimeout",
    "ConnectTimeout", "RuntimeError", "ValueError", "TypeError", "KeyError",
    "PermissionError", "FileNotFoundError", "ConnectionError", "Error",
})
VERSION_PROBE = '''
import importlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
versions = {"python": platform.python_version()}
for name in ("fastapi", "skyvern", "patchright", "playwright", "pytest"):
    try:
        versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        versions[name] = None
def browser_version(executable):
    try:
        output = subprocess.run([executable, "--version"], capture_output=True,
                                text=True, timeout=10, check=True).stdout
        match = re.search(r"\\b[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+\\b", output)
        return match.group(0) if match else None
    except Exception:
        return None
for name in ("patchright", "playwright"):
    try:
        module = importlib.import_module(name + ".sync_api")
        with module.sync_playwright() as runtime:
            versions["chromium_" + name] = browser_version(runtime.chromium.executable_path)
    except Exception:
        versions["chromium_" + name] = None
versions["chromium_skyvern"] = browser_version(os.environ.get("CHROME_EXECUTABLE_PATH", ""))
print(json.dumps(versions))
'''


class ValidationError(Exception):
    """Only fixed, credential-free messages may cross the process boundary."""


class BrowserRuntimeMismatch(ValidationError):
    message = "Browser runtime mismatch: runner and Skyvern require identical, known Patchright and Chromium versions."

    def __init__(self):
        super().__init__(self.message)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def environment() -> dict[str, str]:
    blocked = ("COMPOSE_", "BLOGHUB_", "SKYVERN_", "CLI_RUNNER_", "OPENAI_",
               "ANTHROPIC_", "GEMINI_", "GOOGLE_", "HASHNODE_", "MEDIUM_", "DEVTO_")
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(blocked)}
    env.update(COMPOSE_DISABLE_ENV_FILE="1", COMPOSE_ANSI="never")
    return env


class Commands:
    def __init__(self, docker: str):
        self.docker = docker
        self.env = environment()

    def run(self, args: list[str], *, timeout: int = 60, capture: bool = True,
            check: bool = True) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(
                args, cwd=ROOT, env=self.env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise ValidationError("Command timed out; raw output suppressed.") from None
        except OSError:
            raise ValidationError("Command could not start; raw output suppressed.") from None
        if check and result.returncode:
            raise ValidationError("Command failed; raw output suppressed.")
        return result

    def docker_path(self, path: Path) -> str:
        # Windows Docker CLI needs Windows paths even when Python/Git run in WSL.
        if os.name != "nt" and Path(self.docker).name.lower() == "docker.exe":
            return self.run(["wslpath", "-w", str(path.resolve())]).stdout.strip()
        return str(path.resolve())


def validate_isolation(config: dict) -> None:
    if "tests" not in config.get("services", {}):
        raise ValidationError("Compose must declare the tests service.")
    for service in config["services"].values():
        if any(service.get(key) for key in (
            "ports", "container_name", "privileged", "network_mode", "pid", "ipc",
            "devices", "external_links", "volumes_from", "env_file", "secrets",
        )):
            raise ValidationError("Compose contains a non-isolated service setting.")
        if any(volume.get("type") != "volume" for volume in service.get("volumes", [])):
            raise ValidationError("Host mounts are not allowed in validation services.")
    if any(not network.get("internal") or network.get("external")
           for network in config.get("networks", {}).values()):
        raise ValidationError("Validation networks must be internal and project-owned.")
    if any(volume.get("external") or volume.get("driver_opts")
           for volume in config.get("volumes", {}).values()):
        raise ValidationError("Validation volumes must be project-owned local volumes.")


def image_override(config: dict, project: str) -> tuple[dict, dict[str, str]]:
    replacements = {}
    for service in config["services"].values():
        if service.get("build"):
            original = service.get("image")
            if not original:
                raise ValidationError("Built validation services must declare an image.")
            replacements.setdefault(original, f"{project}-image-{len(replacements)}:local")
    overrides, images = {}, {}
    for name, service in config["services"].items():
        original = service.get("image")
        if not original:
            raise ValidationError("Validation services must declare an image.")
        images[name] = replacements.get(original, original)
        if original in replacements:
            overrides[name] = {"image": replacements[original]}
    return {"services": overrides}, images


def test_names() -> set[str]:
    names = set()
    for filename in ("test_login.py", "test_restart.py"):
        path = ROOT / "validation" / filename
        if path.is_file():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names.update(node.name for node in ast.walk(tree)
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and node.name.startswith("test_"))
    return names


def sanitized_junit(source: Path, destination: Path) -> dict[str, int]:
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 8 * 1024 * 1024:
        raise ValidationError("JUnit report missing or exceeds the artifact limit.")
    raw = source.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValidationError("JUnit report contains unsupported XML declarations.")
    try:
        document = ET.fromstring(raw)
    except ET.ParseError:
        raise ValidationError("JUnit report is not valid XML.") from None
    names = test_names()
    counts = dict(tests=0, failures=0, errors=0, skipped=0)
    suite = ET.Element("testsuite", name="local-login")
    for item in document.iter("testcase"):
        name = item.get("name", "")
        # Parametrized names and arbitrary report properties may contain secrets.
        name = name if name in names else "redacted-test"
        try:
            duration = float(item.get("time", "0"))
        except ValueError:
            duration = 0
        duration = duration if math.isfinite(duration) and 0 <= duration < 86400 else 0
        case = ET.SubElement(suite, "testcase", name=name,
                             classname="validation.test_login", time=f"{duration:.3f}")
        counts["tests"] += 1
        for tag, counter in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
            problem = item.find(tag)
            if problem is not None:
                kind = problem.get("type", "").rsplit(".", 1)[-1]
                if kind not in EXCEPTION_NAMES:
                    matches = re.findall(r"(?:^|\n)(?:E\s+)?(?:[a-zA-Z_]+\.)*([A-Za-z]+(?:Error|Timeout))\b",
                                         problem.get("message", "") + "\n" + (problem.text or ""))
                    kind = next((name for name in reversed(matches) if name in EXCEPTION_NAMES), "")
                attributes = {"message": f"{tag}; raw diagnostics omitted"}
                if kind:
                    attributes["type"] = kind
                sanitized_problem = ET.SubElement(case, tag, **attributes)
                if tag in {"failure", "error"}:
                    locations = re.findall(
                        r"(?m)^[ \t]*(?:/app/)?(validation/(?:test_login|test_restart)\.py:[0-9]+)(?=[: \t\r\n]|$)",
                        problem.text or "",
                    )
                    if locations:
                        sanitized_problem.text = "\n".join(dict.fromkeys(locations))
                counts[counter] += 1
                break
    if not counts["tests"]:
        raise ValidationError("JUnit report contains no test cases.")
    suite.attrib.update({key: str(value) for key, value in counts.items()})
    ET.ElementTree(suite).write(destination, encoding="utf-8", xml_declaration=True)
    return counts


def sanitized_restart(source: Path, destination: Path) -> dict:
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 4096:
        raise ValidationError("Restart metadata missing or oversized.")
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValidationError("Restart metadata must be an object.")
    timestamp = value.get("verifiedAt")
    if (value.get("status") != "connected" or not isinstance(timestamp, str)
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", timestamp)):
        raise ValidationError("Restart metadata does not match the safe contract.")
    safe = {"status": "connected", "verifiedAt": timestamp}
    destination.write_text(json.dumps(safe, indent=2) + "\n", encoding="utf-8")
    return safe


def collect_screenshots(source: Path, destination: Path) -> list[str]:
    allowed = {"login-confirmation.png", "connected-after-restart.png"}
    allowed.update(f"{name}-tab-{index}.png" for name in test_names() for index in range(8))
    saved = []
    for name in sorted(allowed):
        path = source / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            continue
        payload = path.read_bytes()
        if len(payload) < 33 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
            continue
        width, height = struct.unpack(">II", payload[16:24])
        if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 32_000_000):
            continue
        # Playwright emits bitmap PNGs. Reject text-bearing ancillary chunks and
        # trailing payloads instead of exporting arbitrary metadata alongside pixels.
        offset, finished = 8, False
        while offset + 12 <= len(payload):
            length = struct.unpack(">I", payload[offset:offset + 4])[0]
            kind = payload[offset + 4:offset + 8]
            if kind not in {b"IHDR", b"IDAT", b"IEND", b"PLTE", b"tRNS",
                            b"sRGB", b"gAMA", b"cHRM", b"pHYs"}:
                break
            offset += length + 12
            if kind == b"IEND":
                finished = length == 0 and offset == len(payload)
                break
        if finished:
            shutil.copyfile(path, destination / name)
            saved.append(name)
    return saved


def positive(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def remaining(deadline: float) -> int:
    seconds = int(deadline - time.monotonic())
    if seconds < 1:
        raise ValidationError("Startup/test deadline exceeded.")
    return seconds


def wait_container(command: Commands, container: str, deadline: float) -> tuple[int, bool]:
    if not HEX_ID.fullmatch(container):
        raise ValidationError("Cannot identify a project-owned test container.")
    while True:
        state = json.loads(command.run(
            [command.docker, "inspect", "--format", "{{json .State}}", container],
            timeout=min(10, remaining(deadline)),
        ).stdout)
        if state.get("Status") in {"exited", "dead"}:
            code = int(state.get("ExitCode", 1))
            oom = bool(state.get("OOMKilled"))
            return (code if state["Status"] == "exited" and not oom else 1), oom
        time.sleep(min(2, remaining(deadline)))


def restart_phase(command: Commands, compose: list[str], project: str,
                  phase: str, deadline: float) -> tuple[int, bool]:
    container = command.run([
        *compose, "run", "--detach", "--no-deps", "--name", f"{project}-{phase}",
        "tests", "python", "-m", "pytest", "-o", "addopts=", "-q",
        f"validation/test_restart.py::test_{phase.replace('-', '_')}",
        f"--junitxml=/results/restart-{'prepare' if phase == 'prepare-restart' else 'after'}.xml",
    ], timeout=remaining(deadline)).stdout.strip()
    return wait_container(command, container, deadline)


def restart_services(command: Commands, compose: list[str], deadline: float) -> None:
    services = ("backend", "runner", "skyvern")
    command.run([*compose, "restart", "--no-deps", *services],
                capture=False, timeout=remaining(deadline))
    pending = set()
    for service in services:
        ids = command.run([*compose, "ps", "--all", "--quiet", service],
                          timeout=min(10, remaining(deadline))).stdout.split()
        if len(ids) != 1 or not HEX_ID.fullmatch(ids[0]):
            raise ValidationError("Cannot identify a restarted service.")
        pending.add(ids[0])
    while pending:
        for container in tuple(pending):
            state = json.loads(command.run(
                [command.docker, "inspect", "--format", "{{json .State}}", container],
                timeout=min(10, remaining(deadline)),
            ).stdout)
            if state.get("Status") in {"exited", "dead"}:
                raise ValidationError("A restarted service exited before becoming healthy.")
            if state.get("Health", {}).get("Status") == "healthy":
                pending.remove(container)
        if pending:
            time.sleep(min(2, remaining(deadline)))


def component_versions(command: Commands, compose: list[str], deadline: float) -> dict:
    versions = {}
    for service in ("runner", "skyvern"):
        raw = json.loads(command.run(
            [*compose, "exec", "-T", service, "python", "-c", VERSION_PROBE],
            timeout=min(90, remaining(deadline)),
        ).stdout)
        if not isinstance(raw, dict):
            raise ValidationError("Component version probe returned an invalid result.")
        versions[service] = {
            name: value if isinstance(value := raw.get(name), str)
            and re.fullmatch(r"[0-9][0-9A-Za-z.+-]{0,79}", value) else None
            for name in VERSION_KEYS
        }
    return versions


def validate_browser_runtime(versions: dict) -> None:
    runner, skyvern = versions.get("runner", {}), versions.get("skyvern", {})
    patchright = runner.get("patchright")
    chromium = runner.get("chromium_patchright")
    if (not patchright or patchright != skyvern.get("patchright")
            or not chromium or chromium != skyvern.get("chromium_skyvern")):
        raise BrowserRuntimeMismatch()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", help="Docker executable; auto-detects docker or docker.exe")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "tests/results/local-login")
    parser.add_argument("--build-timeout", type=positive, default=3600, help="build limit in seconds")
    parser.add_argument("--timeout", type=positive, default=1200, help="startup and test limit in seconds")
    args = parser.parse_args(argv)
    candidates = [args.docker] if args.docker else list(dict.fromkeys(
        path for name in ("docker", "docker.exe") if (path := shutil.which(name))
    ))
    if not candidates:
        print("Docker with Compose v2 is required.", file=sys.stderr)
        return 1
    docker = candidates[0]
    command = Commands(docker)
    project = "bloghub-login-" + secrets.token_hex(8)
    report = {"suite": "local-login", "project": project, "started_at": now(),
              "status": "failed", "phase": "preflight", "image_ids": {},
              "cleanup": "not_needed", "python": sys.version.split()[0]}
    output = args.results_dir.resolve() / project
    compose, images, owned_images = [], {}, set()
    primary_container = None
    touched = False
    interrupted = False
    exit_code = 1
    previous_handlers = {}

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.signal(sig, interrupt)

    staging_parent = ROOT / "tests/results"
    staging_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".login-stage-", dir=staging_parent) as temporary:
        staging = Path(temporary)
        try:
            # Record the original worktree state before creating output files.
            revision = command.run(["git", "rev-parse", "HEAD"]).stdout.strip()
            if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
                raise ValidationError("Cannot identify the Git revision.")
            report["revision"] = revision
            report["dirty"] = bool(command.run(["git", "status", "--porcelain"]).stdout.strip())
            output.mkdir(parents=True, exist_ok=False)
            print(f"Local login validation: {project}", flush=True)
            for candidate in candidates:
                try:
                    command.run([candidate, "compose", "version"], timeout=15)
                    command.run([candidate, "info", "--format", "{{.ServerVersion}}"], timeout=15)
                except ValidationError:
                    continue
                docker = command.docker = candidate
                break
            else:
                raise ValidationError("No working Docker engine with Compose v2 found.")
            empty_env = staging / "empty.env"
            empty_env.write_text("", encoding="ascii")
            compose = [docker, "compose", "--project-name", project,
                       "--project-directory", command.docker_path(ROOT / "validation"),
                       "--env-file", command.docker_path(empty_env),
                       "-f", command.docker_path(COMPOSE_FILE)]
            config = json.loads(command.run([*compose, "config", "--format", "json"]).stdout)
            validate_isolation(config)
            # Reject explicit volume/network names that bypass the random project.
            for kind in ("volumes", "networks"):
                if any(value.get("name") != f"{project}_{key}"
                       for key, value in config.get(kind, {}).items()):
                    raise ValidationError("Compose resource names must use the random project.")
            override, images = image_override(config, project)
            owned_images = {value["image"] for value in override["services"].values()}
            override_file = staging / "images.json"
            override_file.write_text(json.dumps(override), encoding="utf-8")
            compose += ["-f", command.docker_path(override_file)]

            report["phase"] = "build"
            print("Building isolated images (raw build output suppressed)...", flush=True)
            touched = True
            command.run([*compose, "build"], capture=False, timeout=args.build_timeout)
            report["phase"] = "startup"
            print("Starting the disposable stack...", flush=True)
            deadline = time.monotonic() + args.timeout
            command.run([*compose, "up", "--detach", "--no-build", "tests"],
                        capture=False, timeout=args.timeout)
            containers = command.run([*compose, "ps", "--all", "--quiet", "tests"]).stdout.split()
            if len(containers) != 1 or not HEX_ID.fullmatch(containers[0]):
                raise ValidationError("Cannot identify the project-owned test container.")
            container = containers[0]
            primary_container = container
            report["phase"] = "tests"
            print("Running real local login tests...", flush=True)
            test_exit, oom = wait_container(command, container, deadline)
            report["test_exit_code"] = test_exit
            report["oom_killed"] = oom
            report["phase_exit_codes"] = {"login": test_exit}
            exit_code = int(test_exit != 0)

            report["phase"] = "component_versions"
            report["component_versions"] = component_versions(command, compose, deadline)
            validate_browser_runtime(report["component_versions"])

            report["phase"] = "restart_prepare"
            print("Preparing mandatory restart coverage...", flush=True)
            prepare_exit, oom = restart_phase(command, compose, project, "prepare-restart", deadline)
            report["phase_exit_codes"]["restart_prepare"] = prepare_exit
            report["oom_killed"] |= oom
            if prepare_exit:
                exit_code = 1
                raise ValidationError("Restart preparation failed.")
            report["phase"] = "restart_health"
            print("Restarting backend, runner, and Skyvern; preserving fixture and Postgres...", flush=True)
            restart_services(command, compose, deadline)
            report["phase"] = "restart_after"
            after_exit, oom = restart_phase(command, compose, project, "after-restart", deadline)
            report["phase_exit_codes"]["restart_after"] = after_exit
            report["oom_killed"] |= oom
            exit_code = int(exit_code != 0 or after_exit != 0)
            report["status"] = "passed" if exit_code == 0 else "failed"
        except KeyboardInterrupt:
            interrupted = True
            report["status"] = "interrupted"
            exit_code = 130
            print("Interrupted; collecting safe results and removing the project.", flush=True)
        except (ValidationError, ValueError, OSError) as error:
            # Never print exception strings: Docker/XML errors can embed credentials.
            exit_code = 1
            report["error_type"] = type(error).__name__
            if isinstance(error, BrowserRuntimeMismatch):
                print(BrowserRuntimeMismatch.message, file=sys.stderr)
            print(f"Validation failed during {report['phase']}; raw diagnostics suppressed.", file=sys.stderr)
        finally:
            for sig in previous_handlers:
                signal.signal(sig, signal.SIG_IGN)
            if touched:
                try:
                    for service, image in images.items():
                        result = command.run([docker, "image", "inspect", "--format", "{{.Id}}", image],
                                             check=False, timeout=10)
                        image_id = result.stdout.strip()
                        if HEX_ID.fullmatch(image_id):
                            report["image_ids"][service] = image_id
                    ids = ([primary_container] if primary_container else command.run(
                        [*compose, "ps", "--all", "--quiet", "tests"], check=False,
                    ).stdout.split())
                    if len(ids) == 1 and HEX_ID.fullmatch(ids[0]):
                        raw_results = staging / "results"
                        raw_results.mkdir()
                        command.run([docker, "cp", f"{ids[0]}:/results/.", command.docker_path(raw_results)])
                        report["junit_reports"] = {}
                        report["artifacts"] = "sanitized_junit"
                        for filename in JUNIT_REPORTS:
                            try:
                                raw_xml = raw_results / filename
                                counts = sanitized_junit(raw_xml, output / filename)
                                report["junit_reports"][filename] = counts
                                if counts["failures"] or counts["errors"] or counts["skipped"]:
                                    exit_code = 130 if interrupted else 1
                            except (ValidationError, ValueError, OSError):
                                report["artifacts"] = "incomplete"
                                exit_code = 130 if interrupted else 1
                        try:
                            raw_restart = raw_results / "restart.json"
                            sanitized_restart(raw_restart, output / "restart.json")
                        except (ValidationError, ValueError, OSError):
                            report["artifacts"] = "incomplete"
                            exit_code = 130 if interrupted else 1
                        report["screenshots"] = collect_screenshots(raw_results, output)
                    else:
                        report["artifacts"] = "unavailable"
                        exit_code = 130 if interrupted else 1
                except (ValidationError, ValueError, OSError):
                    report["artifacts"] = "unavailable"
                    exit_code = 130 if interrupted else 1
                finally:
                    print("Removing project containers, network, and volumes...", flush=True)
                    try:
                        result = command.run([*compose, "down", "--volumes", "--remove-orphans", "--timeout", "20"],
                                             capture=False, check=False, timeout=180)
                        report["cleanup"] = "complete" if result.returncode == 0 else "failed"
                    except ValidationError:
                        report["cleanup"] = "failed"
                    if report["cleanup"] != "complete":
                        exit_code = 130 if interrupted else 1
                        print(f"Cleanup failed for {project}; see the documented recovery command.", file=sys.stderr)
                    # Delete only unique tags created by this run, never prune or force.
                    try:
                        result = command.run([docker, "image", "rm", *sorted(owned_images)],
                                             capture=False, check=False, timeout=120)
                        report["image_cleanup"] = "complete" if result.returncode == 0 else "incomplete"
                    except ValidationError:
                        report["image_cleanup"] = "incomplete"
            report["finished_at"] = now()
            if exit_code and report["status"] == "passed":
                report["status"] = "failed"
            try:
                output.mkdir(parents=True, exist_ok=True)
                (output / "metadata.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                print(f"Sanitized results: {output}", flush=True)
            except OSError:
                print("Could not write validation metadata.", file=sys.stderr)
                exit_code = 130 if interrupted else 1
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
