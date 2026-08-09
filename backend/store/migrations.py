"""Ordered, transactional SQLite schema migrations for BlogHub."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence


SEED_USER_ID = "user_seed"
SEED_USER_EMAIL = "seed@example.com"
SEED_USER_HASH = "$2b$12$BJsbJlf3SZUMUISLA8oASeFn.Q3U.Ar6TqoIFtu0F9OlYyev.DZLC"


class MigrationError(RuntimeError):
    """Raised when the database cannot be migrated safely."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


_TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL
)
"""


_CURRENT_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS users (
        id            TEXT PRIMARY KEY,
        email         TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        is_active     INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token       TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at  TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        remember_me INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS articles (
        id              TEXT PRIMARY KEY,
        title           TEXT NOT NULL,
        body            TEXT NOT NULL DEFAULT '',
        body_path       TEXT,
        word_count      INTEGER NOT NULL DEFAULT 0,
        gate            TEXT NOT NULL DEFAULT 'pending',
        source          TEXT NOT NULL DEFAULT 'native',
        source_platform TEXT,
        canonical_url   TEXT,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        user_id         TEXT REFERENCES users(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS article_destinations (
        article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
        platform    TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'none',
        label       TEXT,
        url         TEXT,
        draft_id    TEXT,
        error       TEXT,
        PRIMARY KEY (article_id, platform)
    )""",
    """CREATE TABLE IF NOT EXISTS article_timeline (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
        timestamp   TEXT NOT NULL,
        event       TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS connections (
        platform      TEXT NOT NULL,
        token         TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'connected',
        username      TEXT,
        connected_at  TEXT NOT NULL,
        error_message TEXT,
        user_id       TEXT REFERENCES users(id) ON DELETE CASCADE,
        PRIMARY KEY (platform, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS jobs (
        job_id       TEXT PRIMARY KEY,
        kind         TEXT NOT NULL,
        article_id   TEXT,
        status       TEXT NOT NULL DEFAULT 'pending',
        result       TEXT,
        error        TEXT,
        created_at   TEXT NOT NULL,
        completed_at TEXT,
        user_id      TEXT REFERENCES users(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS article_assets (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
        filename    TEXT NOT NULL,
        asset_path  TEXT NOT NULL,
        mime_type   TEXT,
        created_at  TEXT NOT NULL,
        UNIQUE(article_id, filename)
    )""",
    """CREATE TABLE IF NOT EXISTS article_comments (
        id          TEXT PRIMARY KEY,
        article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
        author      TEXT NOT NULL,
        text        TEXT NOT NULL,
        anchor      TEXT,
        resolved    INTEGER NOT NULL DEFAULT 0,
        has_patch   INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS article_patches (
        id          TEXT PRIMARY KEY,
        article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
        comment_id  TEXT REFERENCES article_comments(id) ON DELETE SET NULL,
        label       TEXT NOT NULL,
        removed     TEXT NOT NULL,
        added       TEXT NOT NULL,
        state       TEXT NOT NULL DEFAULT 'pending',
        created_at  TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS article_chat_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
        role        TEXT NOT NULL,
        text        TEXT NOT NULL,
        created_at  TEXT NOT NULL
    )""",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(connection, table):
        return set()
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _primary_key(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [row[1] for row in sorted(rows, key=lambda row: row[5]) if row[5]]


def _add_column(
    connection: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    if column not in _columns(connection, table):
        connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')


def _create_current_schema(connection: sqlite3.Connection) -> None:
    for statement in _CURRENT_SCHEMA:
        connection.execute(statement)

    _add_column(connection, "jobs", "error", "TEXT")
    _add_column(connection, "articles", "body_path", "TEXT")
    _add_column(connection, "article_comments", "anchor", "TEXT")
    _add_column(
        connection,
        "articles",
        "user_id",
        "TEXT REFERENCES users(id) ON DELETE CASCADE",
    )
    _add_column(
        connection,
        "connections",
        "user_id",
        "TEXT REFERENCES users(id) ON DELETE CASCADE",
    )
    _add_column(
        connection,
        "jobs",
        "user_id",
        "TEXT REFERENCES users(id) ON DELETE CASCADE",
    )

    connection.execute(
        "INSERT OR IGNORE INTO users "
        "(id, email, password_hash, created_at, is_active) VALUES (?,?,?,?,1)",
        (SEED_USER_ID, SEED_USER_EMAIL, SEED_USER_HASH, _utc_now()),
    )
    for table in ("articles", "connections", "jobs"):
        connection.execute(
            f'UPDATE "{table}" SET user_id=? WHERE user_id IS NULL', (SEED_USER_ID,)
        )

    if _primary_key(connection, "connections") != ["platform", "user_id"]:
        connection.execute("ALTER TABLE connections RENAME TO connections_legacy")
        connection.execute(_CURRENT_SCHEMA[5])
        connection.execute(
            """INSERT INTO connections
               (platform, token, status, username, connected_at, error_message, user_id)
               SELECT platform, token, status, username, connected_at, error_message,
                      COALESCE(user_id, ?)
               FROM connections_legacy""",
            (SEED_USER_ID,),
        )
        connection.execute("DROP TABLE connections_legacy")


def _create_indexes(connection: sqlite3.Connection) -> None:
    statements = (
        "CREATE INDEX IF NOT EXISTS idx_articles_user_updated "
        "ON articles(user_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_user_status ON jobs(user_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_article_timeline_article "
        "ON article_timeline(article_id)",
        "CREATE INDEX IF NOT EXISTS idx_article_comments_article "
        "ON article_comments(article_id)",
        "CREATE INDEX IF NOT EXISTS idx_article_patches_article "
        "ON article_patches(article_id)",
        "CREATE INDEX IF NOT EXISTS idx_article_chat_article "
        "ON article_chat_log(article_id, id)",
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "create_current_schema", _create_current_schema),
    Migration(2, "add_query_indexes", _create_indexes),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def current_version(connection: sqlite3.Connection) -> int:
    if not _table_exists(connection, "schema_migrations"):
        return 0
    row = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0])


def run_migrations(
    connection: sqlite3.Connection,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> int:
    """Apply pending migrations in order and return the resulting schema version."""
    versions = [migration.version for migration in migrations]
    if versions != sorted(set(versions)) or any(version < 1 for version in versions):
        raise MigrationError("Migration versions must be unique, positive, and ordered")

    connection.execute(_TRACKING_DDL)
    connection.commit()
    applied = {
        int(row[0]): row[1]
        for row in connection.execute("SELECT version, name FROM schema_migrations")
    }
    latest_known = versions[-1] if versions else 0
    unknown = sorted(version for version in applied if version > latest_known)
    if unknown:
        raise MigrationError(
            f"Database schema version {unknown[-1]} is newer than this BlogHub build "
            f"(latest supported: {latest_known})"
        )

    for migration in migrations:
        if migration.version in applied:
            if applied[migration.version] != migration.name:
                raise MigrationError(
                    f"Migration {migration.version} name mismatch: database has "
                    f"'{applied[migration.version]}', code has '{migration.name}'"
                )
            continue
        try:
            connection.execute("BEGIN IMMEDIATE")
            migration.apply(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?,?,?)",
                (migration.version, migration.name, _utc_now()),
            )
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) failed: {exc}"
            ) from exc

    return current_version(connection)
