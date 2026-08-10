from __future__ import annotations

from backend.store.backends.sqlite import SQLiteStore
from backend.store.schema import SCHEMA_VERSION, SEED_USER_ID


def test_fresh_database_has_current_schema_and_seed_user(tmp_path):
    store = SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))
    try:
        assert store.schema_version == SCHEMA_VERSION
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
            "article_destinations",
            "article_timeline",
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
        assert store._con.execute(
            "SELECT COUNT(*) FROM users WHERE id=?", (SEED_USER_ID,)
        ).fetchone()[0] == 1
    finally:
        store.close()


def test_reopening_an_existing_database_is_idempotent(tmp_path):
    database = tmp_path / "bloghub.db"
    blobs = tmp_path / "blobs"
    store = SQLiteStore(str(database), str(blobs))
    store.update_article_title(store.SEED_USER_ID, "art_001", "Preserved title")
    store.close()

    reopened = SQLiteStore(str(database), str(blobs))
    try:
        assert reopened.schema_version == SCHEMA_VERSION
        article = reopened.get_article(reopened.SEED_USER_ID, "art_001")
        assert article is not None
        assert article["title"] == "Preserved title"
        assert reopened._con.execute(
            "SELECT COUNT(*) FROM users WHERE id=?", (SEED_USER_ID,)
        ).fetchone()[0] == 1
    finally:
        reopened.close()
