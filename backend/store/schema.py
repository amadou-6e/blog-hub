"""Apply BlogHub's current SQLite schema and additive migrations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SEED_USER_ID = "user_seed"
SEED_USER_EMAIL = "seed@example.com"
SEED_USER_HASH = "$2b$12$BJsbJlf3SZUMUISLA8oASeFn.Q3U.Ar6TqoIFtu0F9OlYyev.DZLC"

# Bump for every released schema shape. Idempotent additions migrate in place;
# destructive changes require an explicit migration and recovery plan.
SCHEMA_VERSION = 9

_SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "sql" / "schema.sql"


def apply_schema(connection: sqlite3.Connection) -> None:
    """Create the current schema. Idempotent."""
    connection.executescript(_SCHEMA_SQL_PATH.read_text(encoding="utf-8"))
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
