from __future__ import annotations

import sqlite3

import pytest

from backend.store.backends.sqlite import SQLiteStore
from backend.store.migrations import (
    LATEST_SCHEMA_VERSION,
    Migration,
    MigrationError,
    SEED_USER_ID,
    run_migrations,
)


LEGACY_SCHEMA = """
CREATE TABLE articles (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    word_count INTEGER NOT NULL DEFAULT 0,
    gate TEXT NOT NULL DEFAULT 'pending',
    source TEXT NOT NULL DEFAULT 'native',
    source_platform TEXT,
    canonical_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE connections (
    platform TEXT PRIMARY KEY,
    token TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'connected',
    username TEXT,
    connected_at TEXT NOT NULL,
    error_message TEXT
);
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    article_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
"""


def test_fresh_database_is_migrated_to_latest_schema(tmp_path):
    store = SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))
    try:
        assert store.schema_version == LATEST_SCHEMA_VERSION
        applied = store._con.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [(row[0], row[1]) for row in applied] == [
            (1, "create_current_schema"),
            (2, "add_query_indexes"),
            (3, "add_agent_session_persistence"),
        ]
        tables = {
            row[0]
            for row in store._con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "users",
            "sessions",
            "articles",
            "connections",
            "jobs",
            "article_assets",
            "article_comments",
            "article_patches",
            "article_chat_log",
            "agent_sessions",
            "agent_session_events",
            "agent_session_messages",
            "agent_tool_calls",
            "agent_approvals",
            "agent_checkpoints",
            "agent_session_outputs",
        } <= tables
    finally:
        store.close()


def test_legacy_database_is_upgraded_without_losing_data(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(LEGACY_SCHEMA)
    connection.execute(
        """INSERT INTO articles
           (id, title, body, word_count, gate, source, created_at, updated_at)
           VALUES ('legacy-article', 'Legacy', '# Legacy', 2, 'pending',
                   'native', '2026-01-01T00:00:00+00:00',
                   '2026-01-01T00:00:00+00:00')"""
    )
    connection.execute(
        """INSERT INTO connections
           (platform, token, status, connected_at)
           VALUES ('openai', 'legacy-token', 'connected',
                   '2026-01-01T00:00:00+00:00')"""
    )
    connection.execute(
        """INSERT INTO jobs
           (job_id, kind, article_id, status, created_at)
           VALUES ('job-legacy', 'generate', 'legacy-article', 'done',
                   '2026-01-01T00:00:00+00:00')"""
    )
    connection.commit()
    connection.close()

    store = SQLiteStore(str(database), str(tmp_path / "blobs"))
    try:
        assert store.schema_version == LATEST_SCHEMA_VERSION
        article = store._con.execute(
            "SELECT title, body, user_id, body_path FROM articles WHERE id='legacy-article'"
        ).fetchone()
        assert tuple(article) == ("Legacy", "# Legacy", SEED_USER_ID, None)
        job = store._con.execute(
            "SELECT error, user_id FROM jobs WHERE job_id='job-legacy'"
        ).fetchone()
        assert tuple(job) == (None, SEED_USER_ID)
        saved_connection = store._con.execute(
            "SELECT token, user_id FROM connections WHERE platform='openai'"
        ).fetchone()
        assert tuple(saved_connection) == ("legacy-token", SEED_USER_ID)
        primary_key = [
            row[1]
            for row in sorted(
                store._con.execute("PRAGMA table_info(connections)").fetchall(),
                key=lambda row: row[5],
            )
            if row[5]
        ]
        assert primary_key == ["platform", "user_id"]
    finally:
        store.close()


def test_unversioned_auth_database_is_adopted_idempotently(tmp_path):
    database = tmp_path / "auth-era.db"
    blobs = tmp_path / "blobs"
    store = SQLiteStore(str(database), str(blobs))
    store.update_article_title(store.SEED_USER_ID, "art_001", "Preserved auth-era title")
    store.close()

    connection = sqlite3.connect(database)
    connection.execute("DROP TABLE schema_migrations")
    connection.execute("PRAGMA user_version = 0")
    connection.commit()
    connection.close()

    reopened = SQLiteStore(str(database), str(blobs))
    try:
        assert reopened.schema_version == LATEST_SCHEMA_VERSION
        article = reopened.get_article(reopened.SEED_USER_ID, "art_001")
        assert article is not None
        assert article["title"] == "Preserved auth-era title"
        assert reopened._con.execute(
            "SELECT COUNT(*) FROM users WHERE id=?", (SEED_USER_ID,)
        ).fetchone()[0] == 1
    finally:
        reopened.close()


def test_failed_migration_rolls_back_schema_and_version():
    connection = sqlite3.connect(":memory:")

    def fail(con):
        con.execute("CREATE TABLE should_rollback (id INTEGER)")
        raise RuntimeError("deliberate failure")

    with pytest.raises(MigrationError, match="deliberate failure"):
        run_migrations(connection, (Migration(1, "fails", fail),))

    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name='should_rollback'"
    ).fetchone() is None
    assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 0


def test_database_newer_than_application_is_rejected():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE schema_migrations "
        "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (99, 'future', '2026-01-01T00:00:00Z')"
    )
    connection.commit()

    with pytest.raises(MigrationError, match="newer than this BlogHub build"):
        run_migrations(connection)
