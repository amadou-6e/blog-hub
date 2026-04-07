"""
HTTP client for the CLI runner service.

The runner is a Docker container exposing a REST API at CLI_RUNNER_URL
(default http://localhost:8001). This module is the only place in the
backend that communicates with it.

When the runner is unreachable, all functions raise RunnerUnavailable.
Callers convert that to an appropriate HTTP response (503).
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

CLI_RUNNER_URL = os.environ.get("CLI_RUNNER_URL", "http://localhost:8001").rstrip("/")

_TIMEOUT = httpx.Timeout(connect=3.0, read=70.0, write=10.0, pool=5.0)


class RunnerUnavailable(Exception):
    """Raised when the CLI runner is not reachable or returns an unexpected error."""


# ── Internal helper ────────────────────────────────────────────────────────────

def _client() -> httpx.Client:
    return httpx.Client(base_url=CLI_RUNNER_URL, timeout=_TIMEOUT)


def _post(path: str, **json_kwargs) -> dict:
    try:
        with _client() as c:
            resp = c.post(path, json=json_kwargs or None)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise RunnerUnavailable("CLI runner not reachable at " + CLI_RUNNER_URL)
    except httpx.HTTPStatusError as exc:
        raise RunnerUnavailable(f"Runner error {exc.response.status_code}: {exc.response.text}")


def _get(path: str) -> dict:
    try:
        with _client() as c:
            resp = c.get(path)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise RunnerUnavailable("CLI runner not reachable at " + CLI_RUNNER_URL)
    except httpx.HTTPStatusError as exc:
        raise RunnerUnavailable(f"Runner error {exc.response.status_code}: {exc.response.text}")


# ── Public interface ───────────────────────────────────────────────────────────

def health() -> dict:
    """
    Returns { status, providers }.
    Raises RunnerUnavailable if the runner is down.
    """
    return _get("/health")


def login(provider: str) -> dict:
    """
    Start browser login for a provider.

    Returns one of:
      { available: True,  url: "https://...", poll_url: "/auth/{p}/status" }
      { available: False, reason: "..." }

    Raises RunnerUnavailable on network error.
    """
    return _post(f"/auth/{provider}/login")


def login_status(provider: str) -> dict:
    """
    Poll login completion.

    Returns one of:
      { status: "connected", username: "..." }
      { status: "pending" }
      { status: "error",   reason:   "..." }
    """
    return _get(f"/auth/{provider}/status")


def logout(provider: str) -> dict:
    """Clear CLI credentials for a provider. Returns { status: "disconnected" }."""
    return _post(f"/auth/{provider}/logout")


_TASK_TIMEOUT = httpx.Timeout(connect=3.0, read=200.0, write=10.0, pool=5.0)


def run_task(
    provider: str,
    task: str,
    article_md: str,
    context_md: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> dict:
    """
    Execute a CLI task against article content.

    Returns { exit_code, stdout, stderr, truncated }.
    Raises RunnerUnavailable on network error or 503 from runner.
    """
    payload: dict = {
        "provider":   provider,
        "task":       task,
        "article_md": article_md,
        "args":       extra_args or [],
    }
    if context_md is not None:
        payload["context_md"] = context_md

    try:
        with _client() as c:
            resp = c.post("/tasks/run", json=payload, timeout=_TASK_TIMEOUT)
            if resp.status_code == 503:
                raise RunnerUnavailable(resp.json().get("detail", "provider not authenticated"))
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise RunnerUnavailable("CLI runner not reachable at " + CLI_RUNNER_URL)
    except httpx.HTTPStatusError as exc:
        raise RunnerUnavailable(f"Runner error {exc.response.status_code}: {exc.response.text}")
