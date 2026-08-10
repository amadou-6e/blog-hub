"""Provider-neutral orchestration for browser and device-code agent login."""
from __future__ import annotations

import os
from urllib.parse import parse_qs, urlparse

import backend.services.cli_runner as runner

SUPPORTED_AGENT_PROVIDERS = {"anthropic", "openai"}
AUTH_TIMEOUT_SECONDS = max(30, int(os.environ.get("AGENT_AUTH_TIMEOUT_SECONDS", "300")))

_RECOVERY = {
    "expired": "Start a new login because the authorization request expired.",
    "rejected": "Start again and approve access on the provider page.",
    "timed_out": "Start a new login and finish authorization within five minutes.",
    "rate_limited": "Wait a few minutes before trying to connect again.",
    "failed": "Retry login. If it fails again, verify the CLI runner is available.",
    "canceled": "Start a new login when you are ready to continue.",
}


class ConnectionAuthError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _classify_failure(reason: str | None) -> tuple[str, str]:
    message = (reason or "Provider login failed").strip()[:500]
    lowered = message.lower()
    if "rate limit" in lowered or "too many requests" in lowered or "429" in lowered:
        return "rate_limited", "rate_limited"
    if "expired" in lowered:
        return "expired", "authorization_expired"
    if any(item in lowered for item in ("rejected", "denied", "access_denied")):
        return "rejected", "authorization_rejected"
    if "timed out" in lowered or "timeout" in lowered:
        return "timed_out", "authorization_timeout"
    return "failed", "provider_error"


def response_for(flow: dict) -> dict:
    status = flow["status"]
    return {
        "flow_id": flow["id"],
        "provider": flow["provider"],
        "flow_type": flow["flow_type"],
        "status": status,
        "authorization_url": flow.get("authorization_url"),
        "device_code": flow.get("device_code"),
        "username": flow.get("username"),
        "error_code": flow.get("error_code"),
        "error_message": flow.get("error_message"),
        "recovery": _RECOVERY.get(status),
        "expires_at": flow["expires_at"],
        "created_at": flow["created_at"],
        "updated_at": flow["updated_at"],
    }


def start(storage, user_id: str, provider: str) -> dict:
    if provider not in SUPPORTED_AGENT_PROVIDERS:
        raise ConnectionAuthError(
            f"{provider} does not support agent web login", status_code=404
        )
    try:
        result = runner.login(provider)
    except runner.RunnerUnavailable as exc:
        result = {"available": False, "reason": str(exc)}

    device_code = result.get("device_code")
    flow_type = "device_code" if device_code else "browser_callback"
    if result.get("available") and result.get("url"):
        flow = storage.create_connection_auth_flow(
            user_id,
            provider,
            flow_type,
            authorization_url=result["url"],
            device_code=device_code,
            ttl_seconds=AUTH_TIMEOUT_SECONDS,
        )
        return response_for(flow)

    status, error_code = _classify_failure(result.get("reason"))
    flow = storage.create_connection_auth_flow(
        user_id,
        provider,
        flow_type,
        authorization_url=None,
        ttl_seconds=AUTH_TIMEOUT_SECONDS,
        status=status,
        error_code=error_code,
        error_message=(result.get("reason") or "Browser login is unavailable")[:500],
    )
    return response_for(flow)


def status(storage, user_id: str, flow_id: str) -> dict:
    flow = storage.get_connection_auth_flow(user_id, flow_id)
    if flow is None:
        raise ConnectionAuthError("Authentication flow not found", status_code=404)
    if flow["status"] != "waiting_for_authorization":
        return response_for(flow)

    try:
        provider_status = runner.login_status(flow["provider"])
    except runner.RunnerUnavailable as exc:
        provider_status = {"status": "error", "reason": str(exc)}

    current = provider_status.get("status", "error")
    if current in {"pending", "waiting_for_authorization"}:
        return response_for(flow)
    if current == "connected":
        username = provider_status.get("username")
        storage.save_connection(
            user_id,
            flow["provider"],
            token=f"web_session:{flow['provider']}",
            status="connected",
            username=username,
        )
        flow = storage.update_connection_auth_flow(
            user_id, flow_id, "connected", username=username
        )
        return response_for(flow)

    if current in {"expired", "rejected", "timed_out", "rate_limited", "failed"}:
        normalized = current
        error_code = provider_status.get("error_code") or current
    else:
        normalized, error_code = _classify_failure(provider_status.get("reason"))
    flow = storage.update_connection_auth_flow(
        user_id,
        flow_id,
        normalized,
        error_code=error_code,
        error_message=(provider_status.get("reason") or "Provider login failed")[:500],
    )
    return response_for(flow)


def submit_callback(storage, user_id: str, flow_id: str, callback: str) -> dict:
    flow = storage.get_connection_auth_flow(user_id, flow_id)
    if flow is None:
        raise ConnectionAuthError("Authentication flow not found", status_code=404)
    if flow["status"] != "waiting_for_authorization":
        raise ConnectionAuthError("Authentication flow is no longer active", status_code=409)
    if flow["flow_type"] != "browser_callback":
        raise ConnectionAuthError("This provider uses device-code login", status_code=409)
    parsed = urlparse(callback.strip())
    query = parse_qs(parsed.query)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.path != "/callback"
    ):
        raise ConnectionAuthError("Callback must use the provider loopback URL")
    if query.get("error"):
        provider_error = query["error"][0]
        status, error_code = _classify_failure(provider_error)
        if provider_error == "access_denied":
            status, error_code = "rejected", "authorization_rejected"
        try:
            runner.cancel_login(flow["provider"])
        except runner.RunnerUnavailable:
            pass
        flow = storage.update_connection_auth_flow(
            user_id,
            flow_id,
            status,
            error_code=error_code,
            error_message="Authorization was not completed by the provider",
        )
        return response_for(flow)
    if not query.get("code") or not query.get("state"):
        raise ConnectionAuthError("Callback URL is missing code or state")
    try:
        runner.submit_login_callback(flow["provider"], callback.strip())
    except runner.RunnerUnavailable as exc:
        raise ConnectionAuthError(str(exc), status_code=502) from exc
    return response_for(flow)


def cancel(storage, user_id: str, flow_id: str) -> dict:
    flow = storage.get_connection_auth_flow(user_id, flow_id)
    if flow is None:
        raise ConnectionAuthError("Authentication flow not found", status_code=404)
    if flow["status"] == "waiting_for_authorization":
        try:
            runner.cancel_login(flow["provider"])
        except runner.RunnerUnavailable:
            pass
        flow = storage.update_connection_auth_flow(user_id, flow_id, "canceled")
    return response_for(flow)
