"""Durable provider-neutral authentication flows for agent connections."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from backend.store.crypto import CredentialDecryptionError, decrypt_token, encrypt_token

AUTH_FLOW_STATUSES = {
    "waiting_for_authorization",
    "connected",
    "expired",
    "rejected",
    "timed_out",
    "rate_limited",
    "failed",
    "canceled",
}
ACTIVE_AUTH_FLOW_STATUSES = {"waiting_for_authorization"}
TERMINAL_AUTH_FLOW_STATUSES = AUTH_FLOW_STATUSES - ACTIVE_AUTH_FLOW_STATUSES


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(value: datetime) -> str:
    return value.isoformat()


def _decrypt_ephemeral(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return decrypt_token(value)
    except CredentialDecryptionError:
        return None


def _flow_row(row) -> dict:
    result = dict(row)
    result["authorization_url"] = _decrypt_ephemeral(
        result.pop("authorization_url_secret")
    )
    result["device_code"] = _decrypt_ephemeral(result.pop("device_code_secret"))
    return result


class ConnectionAuthStoreMixin:
    """Mixin requiring the SQLite connection and workspace lock from SQLiteStore."""

    def create_connection_auth_flow(
        self,
        user_id: str,
        provider: str,
        flow_type: str,
        *,
        authorization_url: str | None,
        device_code: str | None = None,
        ttl_seconds: int = 300,
        status: str = "waiting_for_authorization",
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict:
        if status not in AUTH_FLOW_STATUSES:
            raise ValueError(f"Unsupported authentication status: {status}")
        now = _now()
        now_s = _ts(now)
        flow_id = f"auth_{uuid.uuid4().hex}"
        expires_at = _ts(now + timedelta(seconds=max(1, ttl_seconds)))
        completed_at = now_s if status in TERMINAL_AUTH_FLOW_STATUSES else None
        with self._workspace_lock.acquire():
            with self._con:
                self._con.execute(
                    """UPDATE connection_auth_flows
                       SET status='canceled', completed_at=?, updated_at=?
                       WHERE user_id=? AND provider=?
                         AND status='waiting_for_authorization'""",
                    (now_s, now_s, user_id, provider),
                )
                self._con.execute(
                    """INSERT INTO connection_auth_flows
                       (id, user_id, provider, flow_type, status,
                        authorization_url_secret, device_code_secret,
                        error_code, error_message, created_at, updated_at,
                        expires_at, completed_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        flow_id,
                        user_id,
                        provider,
                        flow_type,
                        status,
                        encrypt_token(authorization_url) if authorization_url else None,
                        encrypt_token(device_code) if device_code else None,
                        error_code,
                        error_message,
                        now_s,
                        now_s,
                        expires_at,
                        completed_at,
                    ),
                )
                self._set_connection_auth_state(
                    user_id, provider, status, error_message=error_message
                )
        return self.get_connection_auth_flow(user_id, flow_id)  # type: ignore[return-value]

    def get_connection_auth_flow(self, user_id: str, flow_id: str) -> dict | None:
        self.expire_connection_auth_flows(user_id=user_id)
        row = self._con.execute(
            "SELECT * FROM connection_auth_flows WHERE id=? AND user_id=?",
            (flow_id, user_id),
        ).fetchone()
        return _flow_row(row) if row else None

    def get_latest_connection_auth_flow(
        self, user_id: str, provider: str, *, active_only: bool = False,
    ) -> dict | None:
        self.expire_connection_auth_flows(user_id=user_id)
        active_clause = " AND status='waiting_for_authorization'" if active_only else ""
        row = self._con.execute(
            """SELECT * FROM connection_auth_flows
               WHERE user_id=? AND provider=?""" + active_clause +
            " ORDER BY created_at DESC LIMIT 1",
            (user_id, provider),
        ).fetchone()
        return _flow_row(row) if row else None

    def list_active_connection_auth_flows(self, user_id: str) -> list[dict]:
        self.expire_connection_auth_flows(user_id=user_id)
        rows = self._con.execute(
            """SELECT * FROM connection_auth_flows
               WHERE user_id=? AND status='waiting_for_authorization'
               ORDER BY created_at DESC""",
            (user_id,),
        ).fetchall()
        return [_flow_row(row) for row in rows]

    def update_connection_auth_flow(
        self,
        user_id: str,
        flow_id: str,
        status: str,
        *,
        username: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict:
        if status not in AUTH_FLOW_STATUSES:
            raise ValueError(f"Unsupported authentication status: {status}")
        now_s = _ts(_now())
        completed_at = now_s if status in TERMINAL_AUTH_FLOW_STATUSES else None
        with self._workspace_lock.acquire():
            with self._con:
                row = self._con.execute(
                    "SELECT provider FROM connection_auth_flows WHERE id=? AND user_id=?",
                    (flow_id, user_id),
                ).fetchone()
                if row is None:
                    raise KeyError(f"Authentication flow {flow_id} not found")
                self._con.execute(
                    """UPDATE connection_auth_flows
                       SET status=?, username=?, error_code=?, error_message=?,
                           updated_at=?, completed_at=?
                       WHERE id=? AND user_id=?""",
                    (
                        status,
                        username,
                        error_code,
                        error_message,
                        now_s,
                        completed_at,
                        flow_id,
                        user_id,
                    ),
                )
                self._set_connection_auth_state(
                    user_id,
                    row["provider"],
                    status,
                    username=username,
                    error_message=error_message,
                )
        return self.get_connection_auth_flow(user_id, flow_id)  # type: ignore[return-value]

    def expire_connection_auth_flows(self, *, user_id: str | None = None) -> int:
        now_s = _ts(_now())
        user_clause = " AND user_id=?" if user_id else ""
        params = (now_s, user_id) if user_id else (now_s,)
        with self._workspace_lock.acquire():
            rows = self._con.execute(
                """SELECT id, user_id, provider FROM connection_auth_flows
                   WHERE status='waiting_for_authorization' AND expires_at <= ?"""
                + user_clause,
                params,
            ).fetchall()
            if not rows:
                return 0
            with self._con:
                for row in rows:
                    self._con.execute(
                        """UPDATE connection_auth_flows
                           SET status='timed_out', error_code='authorization_timeout',
                               error_message='Authorization timed out', updated_at=?,
                               completed_at=? WHERE id=?""",
                        (now_s, now_s, row["id"]),
                    )
                    self._set_connection_auth_state(
                        row["user_id"],
                        row["provider"],
                        "timed_out",
                        error_message="Authorization timed out",
                    )
        return len(rows)

    def delete_connection_auth_flows(self, user_id: str, provider: str) -> int:
        with self._con:
            cursor = self._con.execute(
                "DELETE FROM connection_auth_flows WHERE user_id=? AND provider=?",
                (user_id, provider),
            )
        return cursor.rowcount

    def _set_connection_auth_state(
        self,
        user_id: str,
        provider: str,
        status: str,
        *,
        username: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self._con.execute(
            """INSERT INTO connections
               (platform, token, status, username, connected_at, error_message, user_id)
               VALUES (?, '', ?, ?, '', ?, ?)
               ON CONFLICT(platform, user_id) DO UPDATE SET
                   status=excluded.status,
                   username=COALESCE(excluded.username, connections.username),
                   error_message=excluded.error_message""",
            (provider, status, username, error_message, user_id),
        )
