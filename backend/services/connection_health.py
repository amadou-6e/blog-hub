"""Platform-neutral connection-health transitions and cache policy."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Protocol


HEALTH_PROTOCOL_VERSION = 1
USER_FRESHNESS_SECONDS = 5 * 60
IDLE_CHECK_SECONDS = 15 * 60

_STATUSES = {
    "connected",
    "verification_stale",
    "reauthentication_required",
    "temporarily_blocked",
    "rate_limited",
    "unavailable",
    "unknown",
}
_SAFE_DIAGNOSTIC_KEYS = {
    "http_status", "challenge", "login_controls_visible", "selector",
    "operation", "retry_after_seconds",
}


class ConnectionHealthStore(Protocol):
    def get_connection_health(self, user_id: str, platform: str) -> dict | None: ...

    def upsert_connection_health(
        self, user_id: str, platform: str, status: str, **kwargs,
    ) -> dict: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_diagnostics(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        key: item for key, item in value.items()
        if key in _SAFE_DIAGNOSTIC_KEYS
        and isinstance(item, (str, int, float, bool, type(None)))
    }


def _retry_seconds(value: object, default: int) -> int:
    try:
        return min(30 * 24 * 60 * 60, max(60, int(value or default)))
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_identifier(value: object, default: str, limit: int) -> str:
    candidate = str(value or "")[:limit]
    if re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", candidate):
        return candidate
    return default


def record_evidence(
    store: ConnectionHealthStore,
    user_id: str,
    platform: str,
    evidence: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Validate extension evidence and persist its normalized transition."""
    current = now or _now()
    if evidence.get("protocol_version", HEALTH_PROTOCOL_VERSION) != HEALTH_PROTOCOL_VERSION:
        evidence = {
            "status": "unknown",
            "reason": "unsupported_health_protocol",
            "source": "extension_contract",
            "authoritative": False,
        }
    status = str(evidence.get("status") or "unknown")
    if status not in _STATUSES:
        status = "unknown"
    authoritative = bool(evidence.get("authoritative"))
    reason = _safe_identifier(
        evidence.get("reason"), "unclassified_evidence", 128,
    )
    source = _safe_identifier(evidence.get("source"), "unknown", 64)
    if status == "connected" and not authoritative:
        status = "verification_stale"
        reason = "credential_hint_only"

    stale_at = None
    next_check_at = current + timedelta(seconds=IDLE_CHECK_SECONDS)
    retry_at = None
    verified_at = current if authoritative else None
    if status == "connected":
        stale_at = current + timedelta(seconds=USER_FRESHNESS_SECONDS)
    elif status == "temporarily_blocked":
        retry_seconds = _retry_seconds(evidence.get("retry_after_seconds"), 300)
        retry_at = current + timedelta(seconds=retry_seconds)
        next_check_at = retry_at
    elif status == "rate_limited":
        retry_seconds = _retry_seconds(evidence.get("retry_after_seconds"), 900)
        retry_at = current + timedelta(seconds=retry_seconds)
        next_check_at = retry_at
    elif status == "unavailable":
        retry_at = current + timedelta(seconds=60)
        next_check_at = retry_at
    elif status == "reauthentication_required":
        next_check_at = None

    return store.upsert_connection_health(
        user_id,
        platform,
        status,
        reason=reason,
        source=source,
        authoritative=authoritative,
        verified_at=verified_at,
        stale_at=stale_at,
        next_check_at=next_check_at,
        retry_at=retry_at,
        diagnostics=_safe_diagnostics(evidence.get("diagnostics")),
    )


def record_operation_result(
    store: ConnectionHealthStore,
    user_id: str,
    platform: str,
    result: dict,
    *,
    now: datetime | None = None,
) -> dict | None:
    evidence = result.get("connection_health")
    if not isinstance(evidence, dict):
        if not result.get("success"):
            return None
        evidence = {
            "protocol_version": HEALTH_PROTOCOL_VERSION,
            "status": "connected",
            "reason": "remote_operation_succeeded",
            "source": "backend_operation_bridge",
            "authoritative": True,
        }
    return record_evidence(store, user_id, platform, evidence, now=now)


def record_unavailable(
    store: ConnectionHealthStore,
    user_id: str,
    platform: str,
    *,
    source: str = "runner_transport",
    now: datetime | None = None,
) -> dict:
    return record_evidence(store, user_id, platform, {
        "protocol_version": HEALTH_PROTOCOL_VERSION,
        "status": "unavailable",
        "reason": "runner_unavailable",
        "source": source,
        "authoritative": False,
    }, now=now)


def needs_user_refresh(health: dict | None, *, now: datetime | None = None) -> bool:
    if health is None or health.get("status") in {"unknown", "verification_stale"}:
        return True
    stale_at = _datetime(health.get("stale_at"))
    return stale_at is not None and stale_at <= (now or _now())


def remote_operations_allowed(
    health: dict | None, *, now: datetime | None = None,
) -> bool:
    if health is None:
        return True
    if health.get("status") == "reauthentication_required":
        return False
    retry_at = _datetime(health.get("retry_at"))
    return retry_at is None or retry_at <= (now or _now())
