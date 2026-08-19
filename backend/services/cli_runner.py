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
from typing import Iterator, Optional

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


def submit_login_callback(provider: str, callback: str) -> dict:
    """Forward a loopback callback without logging or persisting its payload."""
    return _post(f"/auth/{provider}/submit-code", code=callback)


def cancel_login(provider: str) -> dict:
    """Cancel an in-progress login without deleting an existing credential."""
    return _post(f"/auth/{provider}/cancel")


def logout(provider: str) -> dict:
    """Clear CLI credentials for a provider. Returns { status: "disconnected" }."""
    return _post(f"/auth/{provider}/logout")


_TASK_TIMEOUT = httpx.Timeout(connect=3.0, read=200.0, write=10.0, pool=5.0)

def api_key_from_connection_token(token: str | None) -> str | None:
    """Return a real API key, leaving persisted CLI sessions to the runner."""
    if not token or token == "cli_session" or token.startswith("web_session:"):
        return None
    return token


def stream_chat(
    *, provider: str, session_id: str, article_md: str,
    messages: list[dict[str, str]], model: str | None = None,
    api_key: str | None = None,
) -> Iterator[dict]:
    payload = {
        "provider": provider, "session_id": session_id,
        "article_md": article_md, "messages": messages,
        "model": model, "api_key": api_key,
    }
    try:
        with _client() as client:
            with client.stream(
                "POST", "/chat/stream", json=payload,
                timeout=httpx.Timeout(connect=3, read=300, write=10, pool=5),
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        yield __import__("json").loads(line)
    except (httpx.ConnectError, httpx.HTTPStatusError, httpx.ReadTimeout) as exc:
        raise RunnerUnavailable(f"Chat runner unavailable: {exc}") from exc


def cancel_chat(session_id: str) -> None:
    _post(f"/chat/{session_id}/cancel")


def hashnode_browser_upload(
    *, organization_id: str, profile_id: str, title: str, article_md: str,
    publish: bool = False,
) -> dict:
    """Create or publish a Hashnode article through the browser runner."""
    payload = {
        "organization_id": organization_id, "profile_id": profile_id,
        "title": title, "article_md": article_md, "publish": publish,
    }
    try:
        with _client() as client:
            response = client.post(
                "/browser/hashnode/upload", json=payload,
                timeout=httpx.Timeout(connect=3, read=300, write=30, pool=5),
            )
            response.raise_for_status()
            return response.json()
    except (httpx.ConnectError, httpx.HTTPStatusError, httpx.ReadTimeout) as exc:
        raise RunnerUnavailable(f"Browser runner unavailable: {exc}") from exc


def start_hashnode_browser_login(profile_id: str | None = None) -> dict:
    if profile_id:
        return _post("/browser/hashnode/login", profile_id=profile_id)
    return _post("/browser/hashnode/login")


def get_hashnode_browser_login(session_id: str) -> dict:
    return _get(f"/browser/hashnode/login/{session_id}")


def cancel_hashnode_browser_login(session_id: str) -> None:
    try:
        with _client() as client:
            response = client.delete(f"/browser/hashnode/login/{session_id}")
            response.raise_for_status()
    except (httpx.ConnectError, httpx.HTTPStatusError, httpx.ReadTimeout) as exc:
        raise RunnerUnavailable(f"Browser login runner unavailable: {exc}") from exc


def complete_hashnode_browser_login(
    session_id: str,
    profile_name: str,
    *,
    profile_id: str | None = None,
    organization_id: str | None = None,
) -> dict:
    try:
        with _client() as client:
            response = client.post(
                f"/browser/hashnode/login/{session_id}/complete",
                json={
                    "profile_name": profile_name,
                    "profile_id": profile_id,
                    "organization_id": organization_id,
                },
                timeout=httpx.Timeout(connect=3, read=180, write=10, pool=5),
            )
            response.raise_for_status()
            return response.json()
    except (httpx.ConnectError, httpx.HTTPStatusError, httpx.ReadTimeout) as exc:
        raise RunnerUnavailable(f"Browser login runner unavailable: {exc}") from exc


def delete_hashnode_browser_profile(profile_id: str) -> None:
    try:
        with _client() as client:
            response = client.delete(f"/browser/hashnode/profiles/{profile_id}")
            response.raise_for_status()
    except (httpx.ConnectError, httpx.HTTPStatusError, httpx.ReadTimeout) as exc:
        raise RunnerUnavailable(f"Browser login runner unavailable: {exc}") from exc


def run_task(
    provider: str,
    task: str,
    article_md: str,
    context_md: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
    api_key: Optional[str] = None,
) -> dict:
    """
    Execute a CLI task against article content.

    Returns { exit_code, stdout, stderr, truncated }.
    Raises RunnerUnavailable on network error or 503 from runner.

    api_key: when provided, injected as the provider credential in the
    cli-runner subprocess env. Never logged or written to disk.
    """
    payload: dict = {
        "provider":   provider,
        "task":       task,
        "article_md": article_md,
        "args":       extra_args or [],
    }
    if context_md is not None:
        payload["context_md"] = context_md
    if api_key is not None:
        payload["api_key"] = api_key

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
