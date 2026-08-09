"""Durable agent-session operations shared by the SQLite store."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

_ACTIVE = {"running", "waiting_for_input", "waiting_for_approval", "waiting_for_resume"}
_TERMINAL = {"completed", "failed", "canceled", "expired"}
_STATUSES = _ACTIVE | _TERMINAL
_SENSITIVE_KEYS = {
    "authorization", "cookie", "password", "secret", "token", "access_token",
    "refresh_token", "api_key", "apikey", "client_secret", "credential",
}
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"),
    re.compile(r"(?i)((?:cookie|api[-_]?key|access[-_]?token|refresh[-_]?token|client[-_]?secret|token)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\b(?:sk[-_]|ghp_|github_pat_)[A-Za-z0-9_-]{8,}\b"),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(value: datetime) -> str:
    return value.isoformat()


def _loads(value: str | None) -> Any:
    return json.loads(value) if value else None


def _sanitize(value: Any, key: str | None = None) -> Any:
    if key:
        normalized = key.lower().replace("-", "_")
        if normalized in _SENSITIVE_KEYS or normalized.endswith(
            ("_token", "_secret", "_password", "_cookie", "_credential", "_api_key")
        ):
            return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _sanitize(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        result = value
        for pattern in _SECRET_PATTERNS:
            replacement = r"\1[REDACTED]" if pattern.groups else "[REDACTED]"
            result = pattern.sub(replacement, result)
        return result
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _json(value: Any) -> str:
    return json.dumps(_sanitize(value), separators=(",", ":"), sort_keys=True)


def _row(row: sqlite3.Row) -> dict:
    result = dict(row)
    for field in ("metadata_json", "data_json", "arguments_json", "result_json",
                  "request_json", "response_json", "state_json"):
        if field in result:
            result[field.removesuffix("_json")] = _loads(result.pop(field))
    return result


class AgentSessionStoreMixin:
    """Mixin requiring ``_con`` and ``_workspace_lock`` from SQLiteStore."""

    _con: sqlite3.Connection

    def _owned_session(self, user_id: str, session_id: str) -> sqlite3.Row | None:
        return self._con.execute(
            "SELECT * FROM agent_sessions WHERE id=? AND user_id=?",
            (session_id, user_id),
        ).fetchone()

    def _require_session(self, user_id: str, session_id: str) -> sqlite3.Row:
        row = self._owned_session(user_id, session_id)
        if row is None:
            raise KeyError(f"Agent session {session_id} not found")
        return row

    def _event(self, session_id: str, kind: str, data: Any = None) -> None:
        self._con.execute(
            "INSERT INTO agent_session_events (session_id, kind, data_json, created_at) "
            "VALUES (?,?,?,?)",
            (session_id, kind, _json(data or {}), _ts(_now())),
        )

    def _touch_session(self, session_id: str) -> None:
        now = _ts(_now())
        self._con.execute(
            "UPDATE agent_sessions SET updated_at=?, last_activity_at=?, version=version+1 "
            "WHERE id=?", (now, now, session_id),
        )

    def create_agent_session(
        self, user_id: str, *, provider: str, model: str | None = None,
        article_id: str | None = None, workspace_id: str = "default",
        title: str | None = None, metadata: dict | None = None,
        expires_in_days: int = 30,
    ) -> dict:
        if article_id:
            article = self._con.execute(
                "SELECT 1 FROM articles WHERE id=? AND user_id=?", (article_id, user_id)
            ).fetchone()
            if article is None:
                raise KeyError(f"Article {article_id} not found")
        session_id = f"session_{uuid.uuid4().hex}"
        now = _now()
        expires_at = now + timedelta(days=expires_in_days) if expires_in_days > 0 else None
        with self._workspace_lock.acquire():
            with self._con:
                self._con.execute(
                    """INSERT INTO agent_sessions
                       (id, user_id, article_id, workspace_id, provider, model, title,
                        status, metadata_json, created_at, updated_at, last_activity_at,
                        expires_at)
                       VALUES (?,?,?,?,?,?,?,'running',?,?,?,?,?)""",
                    (session_id, user_id, article_id, _sanitize(workspace_id),
                     _sanitize(provider), _sanitize(model), _sanitize(title),
                     _json(metadata or {}), _ts(now), _ts(now), _ts(now),
                     _ts(expires_at) if expires_at else None),
                )
                self._event(session_id, "created", {"status": "running"})
        return self.get_agent_session(user_id, session_id)  # type: ignore[return-value]

    def list_agent_sessions(
        self, user_id: str, *, article_id: str | None = None,
        status: str | None = None, include_archived: bool = False,
        limit: int = 50, offset: int = 0,
    ) -> list[dict]:
        clauses = ["s.user_id=?"]
        params: list[Any] = [user_id]
        if article_id:
            clauses.append("s.article_id=?")
            params.append(article_id)
        if status:
            clauses.append("s.status=?")
            params.append(status)
        if not include_archived:
            clauses.append("s.archived_at IS NULL")
        params.extend([max(1, min(limit, 200)), max(0, offset)])
        rows = self._con.execute(
            """SELECT s.*,
                      (SELECT COUNT(*) FROM agent_session_messages m
                       WHERE m.session_id=s.id) AS message_count,
                      (SELECT COUNT(*) FROM agent_approvals a
                       WHERE a.session_id=s.id AND a.status='pending') AS pending_approval_count
               FROM agent_sessions s WHERE """ + " AND ".join(clauses) +
            " ORDER BY s.last_activity_at DESC LIMIT ? OFFSET ?", params,
        ).fetchall()
        return [_row(row) for row in rows]

    def get_agent_session(self, user_id: str, session_id: str) -> dict | None:
        session = self._owned_session(user_id, session_id)
        if session is None:
            return None
        result = _row(session)
        child_queries = {
            "events": ("SELECT * FROM agent_session_events WHERE session_id=? ORDER BY id",),
            "messages": ("SELECT * FROM agent_session_messages WHERE session_id=? ORDER BY sequence",),
            "tool_calls": ("SELECT * FROM agent_tool_calls WHERE session_id=? ORDER BY created_at",),
            "approvals": ("SELECT * FROM agent_approvals WHERE session_id=? ORDER BY requested_at",),
            "checkpoints": ("SELECT * FROM agent_checkpoints WHERE session_id=? ORDER BY sequence",),
            "outputs": ("SELECT * FROM agent_session_outputs WHERE session_id=? ORDER BY created_at",),
        }
        for name, (query,) in child_queries.items():
            result[name] = [_row(row) for row in self._con.execute(query, (session_id,))]
        return result

    def add_agent_message(
        self, user_id: str, session_id: str, role: str, content: str,
        metadata: dict | None = None,
    ) -> dict:
        if role not in {"user", "assistant", "system", "tool"}:
            raise ValueError(f"Unsupported message role: {role}")
        self._require_session(user_id, session_id)
        message_id = f"message_{uuid.uuid4().hex}"
        now = _ts(_now())
        with self._workspace_lock.acquire():
            with self._con:
                sequence = self._con.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_session_messages "
                    "WHERE session_id=?", (session_id,),
                ).fetchone()[0]
                self._con.execute(
                    """INSERT INTO agent_session_messages
                       (id, session_id, sequence, role, content, metadata_json, created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (message_id, session_id, sequence, role, _sanitize(content),
                     _json(metadata or {}), now),
                )
                self._touch_session(session_id)
                self._event(session_id, "message_added", {"message_id": message_id, "role": role})
        row = self._con.execute(
            "SELECT * FROM agent_session_messages WHERE id=?", (message_id,)
        ).fetchone()
        return _row(row)

    def record_agent_tool_call(
        self, user_id: str, session_id: str, *, idempotency_key: str,
        name: str, arguments: dict | None = None,
    ) -> tuple[dict, bool]:
        self._require_session(user_id, session_id)
        safe_idempotency_key = _sanitize(idempotency_key)
        existing = self._con.execute(
            "SELECT * FROM agent_tool_calls WHERE session_id=? AND idempotency_key=?",
            (session_id, safe_idempotency_key),
        ).fetchone()
        if existing:
            return _row(existing), False
        tool_id = f"tool_{uuid.uuid4().hex}"
        with self._workspace_lock.acquire():
            try:
                with self._con:
                    self._con.execute(
                        """INSERT INTO agent_tool_calls
                           (id, session_id, idempotency_key, name, arguments_json, created_at)
                           VALUES (?,?,?,?,?,?)""",
                        (tool_id, session_id, safe_idempotency_key, _sanitize(name),
                         _json(arguments or {}), _ts(_now())),
                    )
                    self._touch_session(session_id)
                    self._event(session_id, "tool_call_recorded", {"tool_call_id": tool_id})
            except sqlite3.IntegrityError:
                existing = self._con.execute(
                    "SELECT * FROM agent_tool_calls WHERE session_id=? AND idempotency_key=?",
                    (session_id, safe_idempotency_key),
                ).fetchone()
                if existing is None:
                    raise
                return _row(existing), False
        row = self._con.execute("SELECT * FROM agent_tool_calls WHERE id=?", (tool_id,)).fetchone()
        return _row(row), True

    def claim_agent_tool_call(self, user_id: str, session_id: str, tool_call_id: str) -> bool:
        self._require_session(user_id, session_id)
        with self._con:
            cursor = self._con.execute(
                "UPDATE agent_tool_calls SET status='running', started_at=? "
                "WHERE id=? AND session_id=? AND status='pending'",
                (_ts(_now()), tool_call_id, session_id),
            )
        return cursor.rowcount == 1

    def complete_agent_tool_call(
        self, user_id: str, session_id: str, tool_call_id: str,
        *, result: Any = None, error: str | None = None,
    ) -> dict:
        self._require_session(user_id, session_id)
        status = "failed" if error else "completed"
        with self._con:
            cursor = self._con.execute(
                """UPDATE agent_tool_calls SET status=?, result_json=?, error=?, completed_at=?
                   WHERE id=? AND session_id=? AND status IN ('pending','running')""",
                (status, _json(result) if result is not None else None,
                 _sanitize(error) if error else None, _ts(_now()), tool_call_id, session_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Tool call is missing or already completed")
            self._touch_session(session_id)
            self._event(session_id, "tool_call_completed", {"tool_call_id": tool_call_id, "status": status})
        row = self._con.execute("SELECT * FROM agent_tool_calls WHERE id=?", (tool_call_id,)).fetchone()
        return _row(row)

    def add_agent_checkpoint(
        self, user_id: str, session_id: str, state: dict,
    ) -> dict:
        self._require_session(user_id, session_id)
        checkpoint_id = f"checkpoint_{uuid.uuid4().hex}"
        with self._workspace_lock.acquire():
            with self._con:
                sequence = self._con.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_checkpoints "
                    "WHERE session_id=?", (session_id,),
                ).fetchone()[0]
                self._con.execute(
                    "INSERT INTO agent_checkpoints "
                    "(id, session_id, sequence, state_json, created_at) VALUES (?,?,?,?,?)",
                    (checkpoint_id, session_id, sequence, _json(state), _ts(_now())),
                )
                self._touch_session(session_id)
        row = self._con.execute(
            "SELECT * FROM agent_checkpoints WHERE id=?", (checkpoint_id,)
        ).fetchone()
        return _row(row)

    def request_agent_approval(
        self, user_id: str, session_id: str, request: dict,
        tool_call_id: str | None = None,
    ) -> dict:
        self._require_session(user_id, session_id)
        if tool_call_id:
            tool = self._con.execute(
                "SELECT 1 FROM agent_tool_calls WHERE id=? AND session_id=?",
                (tool_call_id, session_id),
            ).fetchone()
            if tool is None:
                raise KeyError(f"Tool call {tool_call_id} not found in agent session")
        approval_id = f"approval_{uuid.uuid4().hex}"
        now = _ts(_now())
        with self._con:
            self._con.execute(
                """INSERT INTO agent_approvals
                   (id, session_id, tool_call_id, request_json, requested_at)
                   VALUES (?,?,?,?,?)""",
                (approval_id, session_id, tool_call_id, _json(request), now),
            )
            self._set_agent_status(user_id, session_id, "waiting_for_approval")
            self._event(session_id, "approval_requested", {"approval_id": approval_id})
        row = self._con.execute("SELECT * FROM agent_approvals WHERE id=?", (approval_id,)).fetchone()
        return _row(row)

    def resolve_agent_approval(
        self, user_id: str, session_id: str, approval_id: str, *, approved: bool,
        response: dict | None = None,
    ) -> dict:
        self._require_session(user_id, session_id)
        status = "approved" if approved else "denied"
        with self._con:
            cursor = self._con.execute(
                """UPDATE agent_approvals
                   SET status=?, response_json=?, resolved_at=?, resolved_by=?
                   WHERE id=? AND session_id=? AND status='pending'""",
                (status, _json(response or {}), _ts(_now()), user_id, approval_id, session_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Approval is missing or already resolved")
            self._set_agent_status(user_id, session_id, "waiting_for_resume")
            self._event(session_id, "approval_resolved", {"approval_id": approval_id, "status": status})
        row = self._con.execute("SELECT * FROM agent_approvals WHERE id=?", (approval_id,)).fetchone()
        return _row(row)

    def add_agent_output(
        self, user_id: str, session_id: str, *, kind: str, reference: str,
        metadata: dict | None = None,
    ) -> dict:
        self._require_session(user_id, session_id)
        output_id = f"output_{uuid.uuid4().hex}"
        with self._con:
            self._con.execute(
                """INSERT INTO agent_session_outputs
                   (id, session_id, kind, reference, metadata_json, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (output_id, session_id, _sanitize(kind), _sanitize(reference),
                 _json(metadata or {}), _ts(_now())),
            )
            self._touch_session(session_id)
        row = self._con.execute(
            "SELECT * FROM agent_session_outputs WHERE id=?", (output_id,)
        ).fetchone()
        return _row(row)

    def _set_agent_status(
        self, user_id: str, session_id: str, status: str, error: str | None = None,
    ) -> None:
        if status not in _STATUSES:
            raise ValueError(f"Unsupported agent session status: {status}")
        now = _ts(_now())
        completed = now if status in _TERMINAL else None
        cursor = self._con.execute(
            """UPDATE agent_sessions SET status=?, error=?, updated_at=?,
               last_activity_at=?, completed_at=?, version=version+1
               WHERE id=? AND user_id=?""",
            (status, _sanitize(error) if error else None, now, now, completed,
             session_id, user_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"Agent session {session_id} not found")

    def update_agent_session_status(
        self, user_id: str, session_id: str, status: str, error: str | None = None,
    ) -> dict:
        with self._con:
            self._set_agent_status(user_id, session_id, status, error)
            self._event(session_id, "status_changed", {"status": status})
        return self.get_agent_session(user_id, session_id)  # type: ignore[return-value]

    def resume_agent_session(self, user_id: str, session_id: str) -> dict:
        row = self._require_session(user_id, session_id)
        if row["archived_at"] or row["status"] not in {
            "waiting_for_input", "waiting_for_resume", "failed"
        }:
            raise ValueError(f"Session in status {row['status']} cannot be resumed")
        return self.update_agent_session_status(user_id, session_id, "running")

    def cancel_agent_session(self, user_id: str, session_id: str) -> dict:
        row = self._require_session(user_id, session_id)
        if row["status"] in _TERMINAL:
            return self.get_agent_session(user_id, session_id)  # type: ignore[return-value]
        return self.update_agent_session_status(user_id, session_id, "canceled")

    def archive_agent_session(self, user_id: str, session_id: str) -> dict:
        row = self._require_session(user_id, session_id)
        if row["status"] in _ACTIVE:
            raise ValueError("Active sessions must be completed or canceled before archiving")
        with self._con:
            self._con.execute(
                "UPDATE agent_sessions SET archived_at=?, updated_at=?, version=version+1 "
                "WHERE id=? AND user_id=?", (_ts(_now()), _ts(_now()), session_id, user_id),
            )
            self._event(session_id, "archived")
        return self.get_agent_session(user_id, session_id)  # type: ignore[return-value]

    def delete_agent_session(self, user_id: str, session_id: str) -> bool:
        row = self._require_session(user_id, session_id)
        if row["status"] in _ACTIVE:
            raise ValueError("Active sessions must be canceled before deletion")
        with self._con:
            cursor = self._con.execute(
                "DELETE FROM agent_sessions WHERE id=? AND user_id=?", (session_id, user_id)
            )
        return cursor.rowcount == 1

    def export_agent_session(self, user_id: str, session_id: str) -> dict:
        session = self.get_agent_session(user_id, session_id)
        if session is None:
            raise KeyError(f"Agent session {session_id} not found")
        return {"format": "bloghub-agent-session", "version": 1, "session": session}

    def recover_agent_sessions(self) -> int:
        now = _ts(_now())
        with self._con:
            rows = self._con.execute(
                "SELECT id FROM agent_sessions WHERE status='running'"
            ).fetchall()
            for row in rows:
                self._con.execute(
                    "UPDATE agent_tool_calls SET status='interrupted' "
                    "WHERE session_id=? AND status='running'", (row["id"],),
                )
                self._con.execute(
                    "UPDATE agent_sessions SET status='waiting_for_resume', updated_at=?, "
                    "version=version+1 WHERE id=?", (now, row["id"]),
                )
                self._event(row["id"], "interrupted", {"recovered_at": now})
        return len(rows)

    def cleanup_agent_sessions(self, retention_days: int = 90) -> dict[str, int]:
        now = _now()
        now_s = _ts(now)
        cutoff = _ts(now - timedelta(days=max(1, retention_days)))
        with self._con:
            expired = self._con.execute(
                """UPDATE agent_sessions SET status='expired', completed_at=?,
                   updated_at=?, version=version+1
                   WHERE status IN ('running','waiting_for_input','waiting_for_approval',
                                    'waiting_for_resume')
                     AND expires_at IS NOT NULL AND expires_at < ?""",
                (now_s, now_s, now_s),
            ).rowcount
            deleted = self._con.execute(
                """DELETE FROM agent_sessions
                   WHERE status IN ('completed','failed','canceled','expired')
                     AND COALESCE(archived_at, completed_at, updated_at) < ?""",
                (cutoff,),
            ).rowcount
        return {"expired": expired, "deleted": deleted}
