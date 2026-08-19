"""Durable state for approval-gated browser publishing runs."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrowserPublishStoreMixin:
    def create_browser_publish_run(
        self, user_id: str, article_id: str, *, platform: str
    ) -> dict:
        if self.get_article(user_id, article_id) is None:
            raise KeyError("Article not found")
        revision = self.get_current_article_revision(user_id, article_id)
        if revision is None:
            raise KeyError("Article revision not found")
        run_id = f"bpr_{uuid.uuid4().hex}"
        self._con.execute(
            """INSERT INTO browser_publish_runs
               (id, user_id, article_id, article_revision_id, platform,
                status, created_at)
               VALUES (?, ?, ?, ?, ?, 'awaiting_approval', ?)""",
            (run_id, user_id, article_id, revision["id"], platform, _now()),
        )
        self._con.commit()
        return self.get_browser_publish_run(user_id, run_id)

    def get_browser_publish_run(self, user_id: str, run_id: str) -> dict | None:
        row = self._con.execute(
            "SELECT * FROM browser_publish_runs WHERE id=? AND user_id=?",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json") or "null")
        return result

    def approve_browser_publish_run(self, user_id: str, run_id: str) -> dict:
        with self._workspace_lock.acquire():
            row = self._con.execute(
                "SELECT status FROM browser_publish_runs WHERE id=? AND user_id=?",
                (run_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError("Browser publish run not found")
            if row["status"] != "awaiting_approval":
                raise ValueError(f"Browser publish run is {row['status']}")
            self._con.execute(
                """UPDATE browser_publish_runs
                   SET status='running', approved_at=? WHERE id=? AND user_id=?""",
                (_now(), run_id, user_id),
            )
            self._con.commit()
        return self.get_browser_publish_run(user_id, run_id)

    def complete_browser_publish_run(
        self, user_id: str, run_id: str, *, result: dict | None = None,
        error: str | None = None,
    ) -> dict:
        status = "failed" if error else "completed"
        self._con.execute(
            """UPDATE browser_publish_runs
               SET status=?, result_json=?, error=?, completed_at=?
               WHERE id=? AND user_id=?""",
            (status, json.dumps(result) if result is not None else None,
             error, _now(), run_id, user_id),
        )
        self._con.commit()
        return self.get_browser_publish_run(user_id, run_id)

    def recover_browser_publish_runs(self) -> int:
        """Mark interrupted writes unknown; replaying an external write is unsafe."""
        cursor = self._con.execute(
            """UPDATE browser_publish_runs
               SET status='unknown', error='Runner stopped before upload could be verified',
                   completed_at=?
               WHERE status='running'""",
            (_now(),),
        )
        self._con.commit()
        return cursor.rowcount
