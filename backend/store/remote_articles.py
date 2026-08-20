"""Durable identity and synchronization metadata for remote articles."""
from __future__ import annotations

import json
from datetime import datetime, timezone


REMOTE_SYNC_STATUSES = {"succeeded", "partial", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _remote_article_row(row) -> dict:
    result = dict(row)
    result["last_sync_result"] = (
        json.loads(result.pop("last_sync_result_json"))
        if result.get("last_sync_result_json")
        else None
    )
    return result


class RemoteArticleStoreMixin:
    """Mixin requiring the SQLite connection and workspace lock from SQLiteStore."""

    def get_remote_article_identity(
        self, user_id: str, platform: str, remote_id: str,
    ) -> dict | None:
        platform = platform.strip().lower()
        remote_id = remote_id.strip()
        row = self._con.execute(
            """SELECT * FROM remote_article_identities
               WHERE user_id=? AND platform=? AND remote_id=?""",
            (user_id, platform, remote_id),
        ).fetchone()
        return _remote_article_row(row) if row else None

    def list_article_remote_identities(
        self, user_id: str, article_id: str,
    ) -> list[dict]:
        rows = self._con.execute(
            """SELECT * FROM remote_article_identities
               WHERE user_id=? AND article_id=?
               ORDER BY platform, remote_id""",
            (user_id, article_id),
        ).fetchall()
        return [_remote_article_row(row) for row in rows]

    def upsert_remote_article_identity(
        self,
        user_id: str,
        article_id: str,
        platform: str,
        remote_id: str,
        *,
        remote_content_fingerprint: str | None = None,
        subtitle: str | None = None,
        cover_asset_id: int | None = None,
        last_sync_status: str | None = None,
        last_sync_result: dict | None = None,
        last_sync_error: str | None = None,
        remote_created_at: str | None = None,
        remote_updated_at: str | None = None,
        last_sync_started_at: str | None = None,
        last_synced_at: str | None = None,
    ) -> dict:
        platform = platform.strip().lower()
        remote_id = remote_id.strip()
        if not platform or not remote_id:
            raise ValueError("platform and remote_id are required")
        if last_sync_status is not None and last_sync_status not in REMOTE_SYNC_STATUSES:
            raise ValueError(f"Unsupported remote sync status: {last_sync_status}")

        now = _now()
        with self._workspace_lock.acquire():
            article = self._con.execute(
                "SELECT id FROM articles WHERE id=? AND user_id=?",
                (article_id, user_id),
            ).fetchone()
            if article is None:
                raise KeyError(f"Article {article_id} not found for user")
            if cover_asset_id is not None:
                cover = self._con.execute(
                    "SELECT id FROM article_assets WHERE id=? AND article_id=?",
                    (cover_asset_id, article_id),
                ).fetchone()
                if cover is None:
                    raise ValueError("cover asset must belong to the mapped article")

            existing = self._con.execute(
                """SELECT article_id FROM remote_article_identities
                   WHERE user_id=? AND platform=? AND remote_id=?""",
                (user_id, platform, remote_id),
            ).fetchone()
            if existing is not None and existing["article_id"] != article_id:
                raise ValueError("remote article identity is already mapped to another article")

            with self._con:
                self._con.execute(
                    """INSERT INTO remote_article_identities
                       (user_id, platform, remote_id, article_id,
                        remote_content_fingerprint, subtitle, cover_asset_id,
                        last_sync_status, last_sync_result_json, last_sync_error,
                        remote_created_at, remote_updated_at,
                        last_sync_started_at, last_synced_at, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(user_id, platform, remote_id) DO UPDATE SET
                         remote_content_fingerprint=excluded.remote_content_fingerprint,
                         subtitle=excluded.subtitle,
                         cover_asset_id=excluded.cover_asset_id,
                         last_sync_status=excluded.last_sync_status,
                         last_sync_result_json=excluded.last_sync_result_json,
                         last_sync_error=excluded.last_sync_error,
                         remote_created_at=excluded.remote_created_at,
                         remote_updated_at=excluded.remote_updated_at,
                         last_sync_started_at=excluded.last_sync_started_at,
                         last_synced_at=excluded.last_synced_at,
                         updated_at=excluded.updated_at""",
                    (
                        user_id,
                        platform,
                        remote_id,
                        article_id,
                        remote_content_fingerprint,
                        subtitle,
                        cover_asset_id,
                        last_sync_status,
                        json.dumps(last_sync_result, sort_keys=True)
                        if last_sync_result is not None else None,
                        last_sync_error,
                        remote_created_at,
                        remote_updated_at,
                        last_sync_started_at,
                        last_synced_at,
                        now,
                        now,
                    ),
                )
        return self.get_remote_article_identity(
            user_id, platform, remote_id,
        )  # type: ignore[return-value]
