"""Persist normalized health for browser and API blog connections."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


CONNECTION_HEALTH_STATUSES = {
    "connected",
    "verification_stale",
    "reauthentication_required",
    "temporarily_blocked",
    "rate_limited",
    "unavailable",
    "unknown",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | str | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return value.astimezone(timezone.utc).isoformat()


def _health_row(row) -> dict:
    result = dict(row)
    result["authoritative"] = bool(result["authoritative"])
    try:
        result["diagnostics"] = json.loads(result.pop("diagnostics_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        result["diagnostics"] = {}
    return result


class ConnectionHealthStoreMixin:
    def get_connection_health(self, user_id: str, platform: str) -> dict | None:
        with self._workspace_lock.acquire():
            row = self._con.execute(
                "SELECT * FROM connection_health WHERE user_id=? AND platform=?",
                (user_id, platform),
            ).fetchone()
        return _health_row(row) if row else None

    def upsert_connection_health(
        self,
        user_id: str,
        platform: str,
        status: str,
        *,
        reason: str,
        source: str,
        authoritative: bool,
        verified_at: datetime | str | None = None,
        stale_at: datetime | str | None = None,
        next_check_at: datetime | str | None = None,
        retry_at: datetime | str | None = None,
        diagnostics: dict | None = None,
    ) -> dict:
        if status not in CONNECTION_HEALTH_STATUSES:
            raise ValueError(f"Unsupported connection health status: {status}")
        now = _now().isoformat()
        safe_diagnostics = json.dumps(
            diagnostics or {}, separators=(",", ":"), sort_keys=True,
        )
        with self._workspace_lock.acquire():
            with self._con:
                self._con.execute(
                    """INSERT INTO connection_health
                       (user_id, platform, status, reason, source, authoritative,
                        verified_at, stale_at, next_check_at, retry_at,
                        diagnostics_json, verification_lease_until, created_at,
                        updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)
                       ON CONFLICT(user_id, platform) DO UPDATE SET
                         status=excluded.status,
                         reason=excluded.reason,
                         source=excluded.source,
                         authoritative=excluded.authoritative,
                         verified_at=COALESCE(excluded.verified_at,
                                              connection_health.verified_at),
                         stale_at=excluded.stale_at,
                         next_check_at=excluded.next_check_at,
                         retry_at=excluded.retry_at,
                         diagnostics_json=excluded.diagnostics_json,
                         verification_lease_until=NULL,
                         updated_at=excluded.updated_at""",
                    (
                        user_id, platform, status, reason, source,
                        int(authoritative), _timestamp(verified_at),
                        _timestamp(stale_at), _timestamp(next_check_at),
                        _timestamp(retry_at), safe_diagnostics, now, now,
                    ),
                )
        return self.get_connection_health(user_id, platform)  # type: ignore[return-value]

    def claim_connection_health_verification(
        self,
        user_id: str,
        platform: str,
        *,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> bool:
        current = now or _now()
        lease_until = current + timedelta(seconds=max(30, int(lease_seconds)))
        now_s = current.isoformat()
        with self._workspace_lock.acquire():
            with self._con:
                self._con.execute(
                    """INSERT INTO connection_health
                       (user_id, platform, status, reason, source, authoritative,
                        diagnostics_json, created_at, updated_at)
                       VALUES (?,?,'unknown','verification_pending','scheduler',
                               0,'{}',?,?)
                       ON CONFLICT(user_id, platform) DO NOTHING""",
                    (user_id, platform, now_s, now_s),
                )
                cursor = self._con.execute(
                    """UPDATE connection_health
                       SET verification_lease_until=?, updated_at=?
                       WHERE user_id=? AND platform=?
                         AND (verification_lease_until IS NULL
                              OR verification_lease_until <= ?)""",
                    (lease_until.isoformat(), now_s, user_id, platform, now_s),
                )
        return cursor.rowcount == 1

    def release_connection_health_verification(
        self, user_id: str, platform: str,
    ) -> bool:
        with self._workspace_lock.acquire():
            with self._con:
                cursor = self._con.execute(
                    """UPDATE connection_health
                       SET verification_lease_until=NULL, updated_at=?
                       WHERE user_id=? AND platform=?
                         AND verification_lease_until IS NOT NULL""",
                    (_now().isoformat(), user_id, platform),
                )
        return cursor.rowcount == 1

    def delete_connection_health(self, user_id: str, platform: str) -> bool:
        with self._workspace_lock.acquire():
            with self._con:
                cursor = self._con.execute(
                    "DELETE FROM connection_health WHERE user_id=? AND platform=?",
                    (user_id, platform),
                )
        return cursor.rowcount == 1
