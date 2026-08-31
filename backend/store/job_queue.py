"""SQLite-backed durable job queue with leases and idempotent effects."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.store.agent_sessions import _sanitize

TERMINAL_JOB_STATUSES = {"completed", "failed", "canceled", "expired"}
CLAIMABLE_JOB_STATUSES = {"queued", "waiting"}


class JobLeaseLost(RuntimeError):
    """The worker no longer owns the job lease."""


class UncertainSideEffect(RuntimeError):
    """A worker died while an external side effect was in progress."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(value: datetime) -> str:
    return value.isoformat()


def _json(value: Any) -> str:
    return json.dumps(_sanitize(value), separators=(",", ":"), sort_keys=True)


def sync_job_idempotency_key(
    platform: str, when: datetime | None = None,
) -> str:
    when = when or _now()
    minute = when.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return f"sync:{platform}:{minute.isoformat()}"


def _loads(value: str | None) -> Any:
    return json.loads(value) if value else None


def _job_row(row: sqlite3.Row, *, attempts: list[sqlite3.Row] | None = None) -> dict:
    result = dict(row)
    result["type"] = result.pop("kind")
    result["payload"] = _loads(result.pop("payload_json")) or {}
    result["result"] = _loads(result.get("result"))
    result["checkpoint"] = _loads(result.pop("checkpoint_json"))
    result["error"] = result.pop("terminal_error") or result.pop("error")
    if attempts is not None:
        result["attempts"] = [dict(attempt) for attempt in attempts]
    return result


def _schedule_row(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["enabled"] = bool(result["enabled"])
    return result


class DurableJobStoreMixin:
    """Mixin requiring ``_con`` and ``_workspace_lock`` from SQLiteStore."""

    _con: sqlite3.Connection

    def create_job(
        self, user_id: str, job_type: str, article_id: str | None,
        payload: dict | None = None, *, queue: str = "default", priority: int = 0,
        idempotency_key: str | None = None, max_attempts: int = 3,
        timeout_seconds: int = 300, expires_in_seconds: int | None = None,
    ) -> dict:
        now = _now()
        safe_key = _sanitize(idempotency_key) if idempotency_key else None
        if safe_key:
            existing = self._con.execute(
                "SELECT * FROM jobs WHERE user_id=? AND kind=? AND idempotency_key=?",
                (user_id, _sanitize(job_type), safe_key),
            ).fetchone()
            if existing:
                return _job_row(existing)
        job_id = f"job_{uuid.uuid4().hex}"
        expires_at = (
            _ts(now + timedelta(seconds=expires_in_seconds))
            if expires_in_seconds is not None else None
        )
        values = (
            job_id, _sanitize(job_type), article_id, "queued", _json(payload or {}),
            _sanitize(queue), int(priority), safe_key, max(1, int(max_attempts)),
            _ts(now), max(1, int(timeout_seconds)), _ts(now), _ts(now), expires_at,
            user_id,
        )
        try:
            with self._workspace_lock.acquire():
                with self._con:
                    self._con.execute(
                        """INSERT INTO jobs
                           (job_id, kind, article_id, status, payload_json, queue,
                            priority, idempotency_key, max_attempts, available_at,
                            timeout_seconds, created_at, updated_at, expires_at, user_id)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        values,
                    )
        except sqlite3.IntegrityError:
            if not safe_key:
                raise
            existing = self._con.execute(
                "SELECT * FROM jobs WHERE user_id=? AND kind=? AND idempotency_key=?",
                (user_id, _sanitize(job_type), safe_key),
            ).fetchone()
            if existing is None:
                raise
            return _job_row(existing)
        return self.get_job(user_id, job_id)  # type: ignore[return-value]

    def find_job_by_idempotency_key(
        self, user_id: str, job_type: str, idempotency_key: str | None,
    ) -> dict | None:
        if not idempotency_key:
            return None
        row = self._con.execute(
            "SELECT * FROM jobs WHERE user_id=? AND kind=? AND idempotency_key=?",
            (user_id, _sanitize(job_type), _sanitize(idempotency_key)),
        ).fetchone()
        return _job_row(row) if row else None

    def get_job(self, user_id: str, job_id: str) -> dict | None:
        row = self._con.execute(
            "SELECT * FROM jobs WHERE job_id=? AND user_id=?", (job_id, user_id)
        ).fetchone()
        if row is None:
            return None
        attempts = self._con.execute(
            "SELECT * FROM job_attempts WHERE job_id=? ORDER BY attempt", (job_id,)
        ).fetchall()
        return _job_row(row, attempts=attempts)

    def get_job_for_worker(self, job_id: str) -> dict | None:
        row = self._con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return _job_row(row) if row else None

    def list_jobs(
        self, user_id: str, *, status: str | None = None, queue: str | None = None,
        article_id: str | None = None, active: bool | None = None,
        limit: int = 50, offset: int = 0,
    ) -> list[dict]:
        clauses = ["user_id=?"]
        params: list[Any] = [user_id]
        if status:
            clauses.append("status=?")
            params.append(status)
        if queue:
            clauses.append("queue=?")
            params.append(queue)
        if article_id:
            clauses.append("article_id=?")
            params.append(_sanitize(article_id))
        if active is True:
            clauses.append("status IN ('queued','running','waiting')")
        elif active is False:
            clauses.append("status IN ('completed','failed','canceled','expired')")
        params.extend([max(1, min(limit, 200)), max(0, offset)])
        rows = self._con.execute(
            "SELECT * FROM jobs WHERE " + " AND ".join(clauses) +
            " ORDER BY created_at DESC LIMIT ? OFFSET ?", params,
        ).fetchall()
        return [_job_row(row) for row in rows]

    def _recover_orphans_in_transaction(self, now: datetime) -> dict[str, int]:
        now_s = _ts(now)
        expired = self._con.execute(
            """UPDATE jobs SET status='expired', completed_at=?, updated_at=?,
               claimed_by=NULL, lease_expires_at=NULL
               WHERE status IN ('queued','waiting') AND expires_at IS NOT NULL
                 AND expires_at <= ?""", (now_s, now_s, now_s),
        ).rowcount
        rows = self._con.execute(
            """SELECT * FROM jobs WHERE status='running'
               AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?""",
            (now_s,),
        ).fetchall()
        recovered = 0
        failed = 0
        canceled = 0
        for row in rows:
            self._con.execute(
                """UPDATE job_attempts SET status='orphaned', finished_at=?,
                   error='Worker lease expired' WHERE job_id=? AND attempt=?
                   AND status='running'""",
                (now_s, row["job_id"], row["attempt_count"]),
            )
            self._con.execute(
                "UPDATE job_effects SET status='uncertain' "
                "WHERE job_id=? AND status='running'", (row["job_id"],),
            )
            if row["cancel_requested_at"]:
                status = "canceled"
                available_at = None
                completed_at = now_s
                canceled += 1
            elif row["attempt_count"] >= row["max_attempts"]:
                status = "failed"
                available_at = None
                completed_at = now_s
                failed += 1
            else:
                status = "waiting"
                available_at = now_s
                completed_at = None
                recovered += 1
            self._con.execute(
                """UPDATE jobs SET status=?, available_at=?, completed_at=?,
                   claimed_by=NULL, lease_expires_at=NULL, heartbeat_at=NULL,
                   updated_at=?, terminal_error=? WHERE job_id=?""",
                (status, available_at, completed_at, now_s,
                 "Worker lease expired" if status == "failed" else None,
                 row["job_id"]),
            )
        return {
            "recovered": recovered, "failed": failed,
            "canceled": canceled, "expired": expired,
        }

    def recover_orphaned_jobs(self) -> dict[str, int]:
        with self._workspace_lock.acquire():
            with self._con:
                return self._recover_orphans_in_transaction(_now())

    def claim_job(
        self, worker_id: str, *, queues: tuple[str, ...] = ("default",),
        lease_seconds: int = 30,
    ) -> dict | None:
        if not queues:
            return None
        now = _now()
        now_s = _ts(now)
        placeholders = ",".join("?" for _ in queues)
        with self._workspace_lock.acquire():
            with self._con:
                self._recover_orphans_in_transaction(now)
                row = self._con.execute(
                    f"""SELECT * FROM jobs
                        WHERE status IN ('queued','waiting')
                          AND queue IN ({placeholders})
                          AND cancel_requested_at IS NULL
                          AND available_at IS NOT NULL AND available_at <= ?
                          AND (expires_at IS NULL OR expires_at > ?)
                          AND attempt_count < max_attempts
                        ORDER BY priority DESC, created_at ASC LIMIT 1""",
                    (*queues, now_s, now_s),
                ).fetchone()
                if row is None:
                    return None
                attempt = row["attempt_count"] + 1
                lease_expires = _ts(now + timedelta(seconds=max(1, lease_seconds)))
                cursor = self._con.execute(
                    """UPDATE jobs SET status='running', attempt_count=?, claimed_by=?,
                       lease_expires_at=?, heartbeat_at=?, updated_at=?
                       WHERE job_id=? AND status IN ('queued','waiting')""",
                    (attempt, worker_id, lease_expires, now_s, now_s, row["job_id"]),
                )
                if cursor.rowcount != 1:
                    return None
                self._con.execute(
                    """INSERT INTO job_attempts
                       (job_id, attempt, worker_id, status, started_at, heartbeat_at)
                       VALUES (?,?,?,'running',?,?)""",
                    (row["job_id"], attempt, worker_id, now_s, now_s),
                )
        return self.get_job_for_worker(row["job_id"])

    def heartbeat_job(
        self, job_id: str, worker_id: str, *, lease_seconds: int = 30,
    ) -> bool:
        now = _now()
        now_s = _ts(now)
        with self._con:
            cursor = self._con.execute(
                """UPDATE jobs SET heartbeat_at=?, lease_expires_at=?, updated_at=?
                   WHERE job_id=? AND status='running' AND claimed_by=?""",
                (now_s, _ts(now + timedelta(seconds=max(1, lease_seconds))),
                 now_s, job_id, worker_id),
            )
            if cursor.rowcount:
                self._con.execute(
                    """UPDATE job_attempts SET heartbeat_at=? WHERE job_id=?
                       AND attempt=(SELECT attempt_count FROM jobs WHERE job_id=?)""",
                    (now_s, job_id, job_id),
                )
        return cursor.rowcount == 1

    def checkpoint_job(
        self, job_id: str, worker_id: str, checkpoint: dict,
    ) -> dict:
        now_s = _ts(_now())
        with self._con:
            cursor = self._con.execute(
                """UPDATE jobs SET checkpoint_json=?, updated_at=?
                   WHERE job_id=? AND status='running' AND claimed_by=?""",
                (_json(checkpoint), now_s, job_id, worker_id),
            )
        if cursor.rowcount != 1:
            raise JobLeaseLost(f"Worker {worker_id} no longer owns job {job_id}")
        return checkpoint

    def is_job_cancel_requested(self, job_id: str, worker_id: str) -> bool:
        row = self._con.execute(
            "SELECT status, claimed_by, cancel_requested_at FROM jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if row is None or row["status"] != "running" or row["claimed_by"] != worker_id:
            raise JobLeaseLost(f"Worker {worker_id} no longer owns job {job_id}")
        return row["cancel_requested_at"] is not None

    def request_job_cancellation(self, user_id: str, job_id: str) -> dict | None:
        now_s = _ts(_now())
        with self._con:
            row = self._con.execute(
                "SELECT * FROM jobs WHERE job_id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
            if row is None:
                return None
            if row["status"] in TERMINAL_JOB_STATUSES:
                return _job_row(row)
            if row["status"] in CLAIMABLE_JOB_STATUSES:
                self._con.execute(
                    """UPDATE jobs SET status='canceled', cancel_requested_at=?,
                       completed_at=?, updated_at=? WHERE job_id=?""",
                    (now_s, now_s, now_s, job_id),
                )
            else:
                self._con.execute(
                    "UPDATE jobs SET cancel_requested_at=?, updated_at=? WHERE job_id=?",
                    (now_s, now_s, job_id),
                )
        return self.get_job(user_id, job_id)

    def complete_job(
        self, user_id: str, job_id: str, result: dict | None = None,
        error: str | None = None, *, worker_id: str | None = None,
    ) -> None:
        if error:
            self.fail_job(job_id, worker_id, error, retryable=False)
            return
        now_s = _ts(_now())
        owner_clause = " AND claimed_by=?" if worker_id else ""
        params: list[Any] = [
            _json(result) if result is not None else None, now_s, now_s, job_id,
        ]
        if worker_id:
            params.append(worker_id)
        with self._con:
            cursor = self._con.execute(
                """UPDATE jobs SET status='completed', result=?, error=NULL,
                   terminal_error=NULL, completed_at=?, updated_at=?, claimed_by=NULL,
                   lease_expires_at=NULL WHERE job_id=?""" + owner_clause,
                params,
            )
            if worker_id and cursor.rowcount != 1:
                raise JobLeaseLost(f"Worker {worker_id} no longer owns job {job_id}")
            row = self._con.execute(
                "SELECT attempt_count FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row and row["attempt_count"]:
                self._con.execute(
                    """UPDATE job_attempts SET status='completed', finished_at=?
                       WHERE job_id=? AND attempt=?""",
                    (now_s, job_id, row["attempt_count"]),
                )

    def fail_job(
        self, job_id: str, worker_id: str | None, error: str, *,
        retryable: bool = True, backoff_base_seconds: int = 2,
    ) -> str:
        now = _now()
        now_s = _ts(now)
        with self._con:
            row = self._con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Job {job_id} not found")
            if worker_id and row["claimed_by"] != worker_id:
                raise JobLeaseLost(f"Worker {worker_id} no longer owns job {job_id}")
            canceled = row["cancel_requested_at"] is not None
            can_retry = retryable and not canceled and row["attempt_count"] < row["max_attempts"]
            if canceled:
                status = "canceled"
                available_at = None
            elif can_retry:
                status = "waiting"
                delay = min(3600, max(0, backoff_base_seconds) * (2 ** max(0, row["attempt_count"] - 1)))
                available_at = _ts(now + timedelta(seconds=delay))
            else:
                status = "failed"
                available_at = None
            terminal = status in TERMINAL_JOB_STATUSES
            self._con.execute(
                """UPDATE jobs SET status=?, available_at=?, terminal_error=?, error=?,
                   completed_at=?, updated_at=?, claimed_by=NULL, lease_expires_at=NULL
                   WHERE job_id=?""",
                (status, available_at, _sanitize(error), _sanitize(error),
                 now_s if terminal else None, now_s, job_id),
            )
            if row["attempt_count"]:
                self._con.execute(
                    """UPDATE job_attempts SET status=?, finished_at=?, error=?
                       WHERE job_id=? AND attempt=?""",
                    (status, now_s, _sanitize(error), job_id, row["attempt_count"]),
                )
        return status

    def defer_job(self, job_id: str, worker_id: str, error: str) -> None:
        """Park work that requires explicit operator reconciliation."""
        now_s = _ts(_now())
        with self._con:
            row = self._con.execute(
                "SELECT attempt_count, claimed_by FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or row["claimed_by"] != worker_id:
                raise JobLeaseLost(f"Worker {worker_id} no longer owns job {job_id}")
            self._con.execute(
                """UPDATE jobs SET status='waiting', available_at=NULL,
                   terminal_error=?, error=?, updated_at=?, claimed_by=NULL,
                   lease_expires_at=NULL WHERE job_id=?""",
                (_sanitize(error), _sanitize(error), now_s, job_id),
            )
            self._con.execute(
                """UPDATE job_attempts SET status='waiting', finished_at=?, error=?
                   WHERE job_id=? AND attempt=?""",
                (now_s, _sanitize(error), job_id, row["attempt_count"]),
            )

    def retry_job(
        self, user_id: str, job_id: str, *, idempotency_key: str | None = None,
    ) -> dict | None:
        now_s = _ts(_now())
        safe_key = _sanitize(idempotency_key) if idempotency_key else None
        with self._workspace_lock.acquire():
            with self._con:
                row = self._con.execute(
                    "SELECT status FROM jobs WHERE job_id=? AND user_id=?",
                    (job_id, user_id),
                ).fetchone()
                if row is None:
                    return None
                if safe_key:
                    repeated = self._con.execute(
                        "SELECT 1 FROM job_retry_requests "
                        "WHERE job_id=? AND user_id=? AND idempotency_key=?",
                        (job_id, user_id, safe_key),
                    ).fetchone()
                    if repeated:
                        return self.get_job(user_id, job_id)
                if row["status"] in {"queued", "running"}:
                    raise ValueError("This job is already active")
                if row["status"] == "completed":
                    raise ValueError("A completed job cannot be retried")
                if safe_key:
                    self._con.execute(
                        "INSERT INTO job_retry_requests "
                        "(job_id, user_id, idempotency_key, created_at) "
                        "VALUES (?,?,?,?)",
                        (job_id, user_id, safe_key, now_s),
                    )
                self._con.execute(
                    """UPDATE jobs SET status='queued', available_at=?,
                       completed_at=NULL, cancel_requested_at=NULL,
                       terminal_error=NULL, error=NULL, claimed_by=NULL,
                       lease_expires_at=NULL, updated_at=?,
                       max_attempts=CASE WHEN attempt_count >= max_attempts
                                         THEN attempt_count + 1 ELSE max_attempts END
                       WHERE job_id=? AND user_id=?""",
                    (now_s, now_s, job_id, user_id),
                )
        return self.get_job(user_id, job_id)

    def begin_job_effect(
        self, job_id: str, worker_id: str, effect_key: str,
    ) -> tuple[Any, bool]:
        safe_key = _sanitize(effect_key)
        with self._workspace_lock.acquire():
            with self._con:
                job = self._con.execute(
                    "SELECT * FROM jobs WHERE job_id=? AND status='running' AND claimed_by=?",
                    (job_id, worker_id),
                ).fetchone()
                if job is None:
                    raise JobLeaseLost(f"Worker {worker_id} no longer owns job {job_id}")
                effect = self._con.execute(
                    "SELECT * FROM job_effects WHERE job_id=? AND effect_key=?",
                    (job_id, safe_key),
                ).fetchone()
                if effect:
                    if effect["status"] == "completed":
                        return _loads(effect["result_json"]), False
                    raise UncertainSideEffect(
                        f"Effect {effect_key} was started but not durably completed"
                    )
                self._con.execute(
                    """INSERT INTO job_effects
                       (job_id, effect_key, status, attempt, started_at)
                       VALUES (?,?,'running',?,?)""",
                    (job_id, safe_key, job["attempt_count"], _ts(_now())),
                )
        return None, True

    def complete_job_effect(
        self, job_id: str, worker_id: str, effect_key: str, result: Any,
    ) -> None:
        safe_key = _sanitize(effect_key)
        with self._con:
            job = self._con.execute(
                "SELECT 1 FROM jobs WHERE job_id=? AND status='running' AND claimed_by=?",
                (job_id, worker_id),
            ).fetchone()
            if job is None:
                raise JobLeaseLost(f"Worker {worker_id} no longer owns job {job_id}")
            cursor = self._con.execute(
                """UPDATE job_effects SET status='completed', result_json=?, completed_at=?
                   WHERE job_id=? AND effect_key=? AND status='running'""",
                (_json(result), _ts(_now()), job_id, safe_key),
            )
            if cursor.rowcount != 1:
                raise UncertainSideEffect(f"Effect {effect_key} cannot be completed")

    def abort_job_effect(
        self, job_id: str, worker_id: str, effect_key: str,
    ) -> None:
        """Release an effect after a failure known to precede its side effect."""
        safe_key = _sanitize(effect_key)
        with self._con:
            job = self._con.execute(
                "SELECT 1 FROM jobs WHERE job_id=? AND status='running' AND claimed_by=?",
                (job_id, worker_id),
            ).fetchone()
            if job is None:
                raise JobLeaseLost(f"Worker {worker_id} no longer owns job {job_id}")
            self._con.execute(
                """DELETE FROM job_effects WHERE job_id=? AND effect_key=?
                   AND status='running'""",
                (job_id, safe_key),
            )

    def queue_metrics(self) -> dict:
        rows = self._con.execute(
            "SELECT queue, status, COUNT(*) AS count FROM jobs GROUP BY queue, status"
        ).fetchall()
        depth: dict[str, dict[str, int]] = {}
        for row in rows:
            depth.setdefault(row["queue"], {})[row["status"]] = row["count"]
        oldest = self._con.execute(
            "SELECT MIN(created_at) FROM jobs WHERE status IN ('queued','waiting')"
        ).fetchone()[0]
        attempts = self._con.execute(
            "SELECT COUNT(*), COALESCE(AVG(attempt_count), 0) FROM jobs"
        ).fetchone()
        return {
            "queues": depth,
            "oldest_queued_at": oldest,
            "total_jobs": attempts[0],
            "average_attempts": attempts[1],
        }

    def upsert_sync_schedule(
        self, user_id: str, platform: str, interval_seconds: int,
        *, enabled: bool = True,
    ) -> dict:
        if platform not in {"hashnode", "medium"}:
            raise ValueError("Scheduled sync supports Hashnode and Medium")
        interval = max(60, int(interval_seconds))
        now = _now()
        now_s = _ts(now)
        schedule_id = f"sync_{user_id}_{platform}"
        next_run = _ts(now + timedelta(seconds=interval))
        with self._workspace_lock.acquire():
            with self._con:
                self._con.execute(
                    """INSERT INTO sync_schedules
                       (id, user_id, platform, interval_seconds, enabled,
                        next_run_at, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(user_id, platform) DO UPDATE SET
                         interval_seconds=excluded.interval_seconds,
                         enabled=excluded.enabled,
                         next_run_at=excluded.next_run_at,
                         updated_at=excluded.updated_at""",
                    (schedule_id, user_id, platform, interval, int(enabled),
                     next_run, now_s, now_s),
                )
        row = self._con.execute(
            "SELECT * FROM sync_schedules WHERE user_id=? AND platform=?",
            (user_id, platform),
        ).fetchone()
        return _schedule_row(row)

    def list_sync_schedules(self, user_id: str) -> list[dict]:
        rows = self._con.execute(
            "SELECT * FROM sync_schedules WHERE user_id=? ORDER BY platform",
            (user_id,),
        ).fetchall()
        return [_schedule_row(row) for row in rows]

    def delete_sync_schedule(self, user_id: str, platform: str) -> bool:
        with self._con:
            cursor = self._con.execute(
                "DELETE FROM sync_schedules WHERE user_id=? AND platform=?",
                (user_id, platform),
            )
        return cursor.rowcount == 1

    def enqueue_due_sync_jobs(self) -> int:
        """Atomically turn due schedules into idempotent queue entries."""
        now = _now()
        now_s = _ts(now)
        enqueued = 0
        with self._workspace_lock.acquire():
            with self._con:
                rows = self._con.execute(
                    """SELECT * FROM sync_schedules
                       WHERE enabled=1 AND next_run_at <= ?
                       ORDER BY next_run_at""",
                    (now_s,),
                ).fetchall()
                for row in rows:
                    due_at = datetime.fromisoformat(row["next_run_at"])
                    key = sync_job_idempotency_key(row["platform"], now)
                    cursor = self._con.execute(
                        """INSERT OR IGNORE INTO jobs
                           (job_id, kind, status, payload_json, queue, priority,
                            idempotency_key, max_attempts, available_at,
                            timeout_seconds, created_at, updated_at, user_id)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"job_{uuid.uuid4().hex}", "sync", "queued",
                         _json({"platform": row["platform"], "scheduled": True}),
                         "sync", 0, key, 4, now_s, 900, now_s, now_s,
                         row["user_id"]),
                    )
                    enqueued += cursor.rowcount
                    interval = timedelta(seconds=row["interval_seconds"])
                    next_run = due_at + interval
                    while next_run <= now:
                        next_run += interval
                    self._con.execute(
                        """UPDATE sync_schedules
                           SET next_run_at=?, last_enqueued_at=?, updated_at=?
                           WHERE id=? AND next_run_at=?""",
                        (_ts(next_run), now_s, now_s, row["id"], row["next_run_at"]),
                    )
        return enqueued
