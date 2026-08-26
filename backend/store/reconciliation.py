"""Immutable local-versus-remote reconciliation observations."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row) -> dict:
    result = dict(row)
    result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
    return result


class ReconciliationStoreMixin:
    def record_reconciliation_observation(
        self,
        user_id: str,
        article_id: str,
        platform: str,
        remote_id: str,
        **values,
    ) -> dict:
        identity = self.get_remote_article_identity(user_id, platform, remote_id)
        if identity is None or identity["article_id"] != article_id:
            raise KeyError("remote article identity not found")
        observation_id = f"recon_{uuid.uuid4().hex[:12]}"
        with self._workspace_lock.acquire(), self._con:
            self._con.execute(
                """INSERT INTO remote_reconciliation_observations (
                       id, user_id, article_id, platform, remote_id,
                       local_revision_id, baseline_fingerprint, local_fingerprint,
                       remote_fingerprint, availability, sync_state, remote_title,
                       remote_content, canonical_url, remote_url, remote_status,
                       remote_updated_at, metadata_json, error, observed_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    observation_id,
                    user_id,
                    article_id,
                    platform,
                    remote_id,
                    values.get("local_revision_id"),
                    values.get("baseline_fingerprint"),
                    values["local_fingerprint"],
                    values.get("remote_fingerprint"),
                    values.get("availability", "available"),
                    values["sync_state"],
                    values.get("remote_title"),
                    values.get("remote_content"),
                    values.get("canonical_url"),
                    values.get("remote_url"),
                    values.get("remote_status"),
                    values.get("remote_updated_at"),
                    json.dumps(values.get("metadata") or {}, sort_keys=True),
                    values.get("error"),
                    values.get("observed_at") or _now(),
                ),
            )
        return self.get_reconciliation_observation(
            user_id, article_id, observation_id,
        )  # type: ignore[return-value]

    def get_reconciliation_observation(
        self, user_id: str, article_id: str, observation_id: str,
    ) -> dict | None:
        row = self._con.execute(
            """SELECT * FROM remote_reconciliation_observations
               WHERE id=? AND user_id=? AND article_id=?""",
            (observation_id, user_id, article_id),
        ).fetchone()
        return _row(row) if row else None

    def get_latest_reconciliation_observation(
        self, user_id: str, article_id: str, platform: str,
    ) -> dict | None:
        row = self._con.execute(
            """SELECT * FROM remote_reconciliation_observations
               WHERE user_id=? AND article_id=? AND platform=?
               ORDER BY observed_at DESC, rowid DESC LIMIT 1""",
            (user_id, article_id, platform),
        ).fetchone()
        return _row(row) if row else None

    def list_latest_reconciliation_observations(
        self, user_id: str, article_id: str,
    ) -> list[dict]:
        rows = self._con.execute(
            """SELECT observation.*
               FROM remote_reconciliation_observations observation
               WHERE observation.user_id=? AND observation.article_id=?
                 AND observation.rowid = (
                   SELECT latest.rowid
                   FROM remote_reconciliation_observations latest
                   WHERE latest.user_id=observation.user_id
                     AND latest.article_id=observation.article_id
                     AND latest.platform=observation.platform
                   ORDER BY latest.observed_at DESC, latest.rowid DESC LIMIT 1
                 )
               ORDER BY observation.platform""",
            (user_id, article_id),
        ).fetchall()
        return [_row(row) for row in rows]

    def has_unresolved_reconciliation(
        self, user_id: str, article_id: str, platforms: list[str] | None = None,
    ) -> bool:
        latest = self.list_latest_reconciliation_observations(user_id, article_id)
        selected = set(platforms or [])
        return any(
            item["sync_state"] == "conflict"
            and (not selected or item["platform"] in selected)
            for item in latest
        )
