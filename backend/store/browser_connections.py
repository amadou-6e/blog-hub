"""Durable references to provider browser profiles owned by Skyvern."""
from __future__ import annotations

from datetime import datetime, timezone

from backend.store.crypto import decrypt_token, encrypt_token, needs_reencryption


BROWSER_CONNECTION_STATUSES = {
    "disconnected",
    "waiting_for_login",
    "verifying",
    "connected",
    "expired",
    "failed",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _browser_connection_row(row) -> dict:
    result = dict(row)
    if result.get("app_url"):
        result["app_url"] = decrypt_token(result["app_url"])
    return result


class BrowserConnectionStoreMixin:
    def get_browser_connection(self, user_id: str, platform: str) -> dict | None:
        row = self._con.execute(
            "SELECT * FROM browser_connections WHERE user_id=? AND platform=?",
            (user_id, platform),
        ).fetchone()
        return _browser_connection_row(row) if row else None

    def get_reusable_browser_profile(
        self, user_id: str, platform: str,
    ) -> dict | None:
        row = self._con.execute(
            """SELECT skyvern_organization_id, skyvern_profile_id
               FROM browser_connections
               WHERE user_id=? AND skyvern_profile_id IS NOT NULL
               ORDER BY CASE WHEN platform=? THEN 0 ELSE 1 END,
                        CASE WHEN status='connected' THEN 0 ELSE 1 END,
                        updated_at DESC
               LIMIT 1""",
            (user_id, platform),
        ).fetchone()
        if row is None:
            return None
        return {
            "organization_id": row["skyvern_organization_id"],
            "profile_id": row["skyvern_profile_id"],
        }

    def start_browser_connection(
        self,
        user_id: str,
        platform: str,
        *,
        session_id: str,
        organization_id: str,
        app_url: str,
        profile_id: str | None = None,
    ) -> dict:
        now = _now()
        with self._workspace_lock.acquire():
            with self._con:
                self._con.execute(
                    """INSERT INTO browser_connections
                       (user_id, platform, status, skyvern_session_id,
                        skyvern_organization_id, skyvern_profile_id, app_url,
                        created_at, updated_at)
                       VALUES (?, ?, 'waiting_for_login', ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(user_id, platform) DO UPDATE SET
                         status='waiting_for_login',
                         skyvern_session_id=excluded.skyvern_session_id,
                         skyvern_organization_id=excluded.skyvern_organization_id,
                         skyvern_profile_id=excluded.skyvern_profile_id,
                         app_url=excluded.app_url,
                         error=NULL,
                         verified_at=NULL,
                         updated_at=excluded.updated_at""",
                    (
                        user_id,
                        platform,
                        session_id,
                        organization_id,
                        profile_id,
                        encrypt_token(app_url),
                        now,
                        now,
                    ),
                )
        return self.get_browser_connection(user_id, platform)  # type: ignore[return-value]

    def reencrypt_browser_connection_credentials(self) -> int:
        """Move plaintext and retired-key browser stream URLs to the active key."""
        rows = self._con.execute(
            """SELECT user_id, platform, app_url FROM browser_connections
               WHERE app_url IS NOT NULL AND app_url <> ''"""
        ).fetchall()
        replacements = []
        for row in rows:
            if needs_reencryption(row["app_url"]):
                replacements.append((
                    encrypt_token(decrypt_token(row["app_url"])),
                    row["user_id"],
                    row["platform"],
                ))
        if replacements:
            with self._con:
                self._con.executemany(
                    """UPDATE browser_connections SET app_url=?
                       WHERE user_id=? AND platform=?""",
                    replacements,
                )
        return len(replacements)

    def update_browser_connection(
        self,
        user_id: str,
        platform: str,
        status: str,
        *,
        profile_id: str | None = None,
        error: str | None = None,
    ) -> dict:
        if status not in BROWSER_CONNECTION_STATUSES:
            raise ValueError(f"Unsupported browser connection status: {status}")
        now = _now()
        verified_at = now if status == "connected" else None
        with self._workspace_lock.acquire():
            with self._con:
                row = self._con.execute(
                    "SELECT 1 FROM browser_connections WHERE user_id=? AND platform=?",
                    (user_id, platform),
                ).fetchone()
                if row is None:
                    raise KeyError("Browser connection not found")
                self._con.execute(
                    """UPDATE browser_connections
                       SET status=?,
                           skyvern_profile_id=COALESCE(?, skyvern_profile_id),
                           error=?,
                           verified_at=COALESCE(?, verified_at),
                           updated_at=?
                       WHERE user_id=? AND platform=?""",
                    (
                        status,
                        profile_id,
                        error,
                        verified_at,
                        now,
                        user_id,
                        platform,
                    ),
                )
        return self.get_browser_connection(user_id, platform)  # type: ignore[return-value]

    def delete_browser_connection(self, user_id: str, platform: str) -> bool:
        with self._workspace_lock.acquire():
            with self._con:
                cursor = self._con.execute(
                    "DELETE FROM browser_connections WHERE user_id=? AND platform=?",
                    (user_id, platform),
                )
        return cursor.rowcount > 0

    def disconnect_browser_connection(
        self, user_id: str, platform: str,
    ) -> dict | None:
        now = _now()
        with self._workspace_lock.acquire():
            with self._con:
                cursor = self._con.execute(
                    """UPDATE browser_connections
                       SET status='disconnected', skyvern_session_id=NULL,
                           app_url=NULL, error=NULL, verified_at=NULL, updated_at=?
                       WHERE user_id=? AND platform=?""",
                    (now, user_id, platform),
                )
        if cursor.rowcount == 0:
            return None
        return self.get_browser_connection(user_id, platform)
