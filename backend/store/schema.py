"""Apply BlogHub's current SQLite schema and additive migrations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SEED_USER_ID = "user_seed"
SEED_USER_EMAIL = "seed@example.com"
SEED_USER_HASH = "$2b$12$BJsbJlf3SZUMUISLA8oASeFn.Q3U.Ar6TqoIFtu0F9OlYyev.DZLC"

# Bump for every released schema shape. Idempotent additions migrate in place;
# destructive changes require an explicit migration and recovery plan.
SCHEMA_VERSION = 11

_SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "sql" / "schema.sql"


def _add_column(
    connection: sqlite3.Connection, table: str, name: str, definition: str,
) -> None:
    columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
    if name not in columns:
        connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')


def _upgrade_jobs(
    connection: sqlite3.Connection, *, normalize_legacy_statuses: bool = False,
) -> None:
    columns = (
        ("payload_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("queue", "TEXT NOT NULL DEFAULT 'default'"),
        ("priority", "INTEGER NOT NULL DEFAULT 0"),
        ("idempotency_key", "TEXT"),
        ("max_attempts", "INTEGER NOT NULL DEFAULT 3"),
        ("attempt_count", "INTEGER NOT NULL DEFAULT 0"),
        ("available_at", "TEXT"),
        ("claimed_by", "TEXT"),
        ("lease_expires_at", "TEXT"),
        ("heartbeat_at", "TEXT"),
        ("timeout_seconds", "INTEGER NOT NULL DEFAULT 300"),
        ("cancel_requested_at", "TEXT"),
        ("checkpoint_json", "TEXT"),
        ("updated_at", "TEXT"),
        ("terminal_error", "TEXT"),
        ("expires_at", "TEXT"),
    )
    for name, definition in columns:
        _add_column(connection, "jobs", name, definition)
    if normalize_legacy_statuses:
        connection.execute(
            """UPDATE jobs SET
               status=CASE status WHEN 'done' THEN 'completed'
                                  WHEN 'error' THEN 'failed'
                                  WHEN 'running' THEN 'queued'
                                  WHEN 'pending' THEN 'queued'
                                  ELSE status END,
               available_at=COALESCE(available_at, created_at),
               updated_at=COALESCE(updated_at, created_at),
               terminal_error=COALESCE(terminal_error, error)"""
        )


def apply_schema(connection: sqlite3.Connection) -> None:
    """Create the current schema. Idempotent."""
    previous_version = connection.execute("PRAGMA user_version").fetchone()[0]
    jobs_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
    ).fetchone()
    if jobs_exists:
        _upgrade_jobs(
            connection, normalize_legacy_statuses=previous_version < SCHEMA_VERSION,
        )
    connection.executescript(_SCHEMA_SQL_PATH.read_text(encoding="utf-8"))
    _upgrade_jobs(connection)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
