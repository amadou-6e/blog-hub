"""Applies BlogHub's SQLite schema, defined in sql/schema.sql.

BlogHub does not migrate schemas in place. When the schema changes, delete
the runtime database and let it be recreated fresh from sql/schema.sql
instead of writing an upgrade path for the old shape.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SEED_USER_ID = "user_seed"
SEED_USER_EMAIL = "seed@example.com"
SEED_USER_HASH = "$2b$12$BJsbJlf3SZUMUISLA8oASeFn.Q3U.Ar6TqoIFtu0F9OlYyev.DZLC"

# Bump when sql/schema.sql changes in a way that isn't safe to layer onto an
# existing database (e.g. a dropped/renamed column). Operators reset by
# deleting the database file; there is no in-place upgrade path.
SCHEMA_VERSION = 1

_SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "sql" / "schema.sql"


def apply_schema(connection: sqlite3.Connection) -> None:
    """Create the current schema. Idempotent."""
    connection.executescript(_SCHEMA_SQL_PATH.read_text(encoding="utf-8"))
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
