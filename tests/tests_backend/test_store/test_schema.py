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
            "article_revisions",
            "connections",
            "connection_auth_flows",
            "jobs",
            "article_assets",
            "article_comments",
            "article_patches",
            "article_patch_revisions",
            "article_chat_log",
            "agent_sessions",
            "agent_session_events",
            "agent_session_messages",
            "agent_tool_calls",
            "agent_approvals",
            "agent_checkpoints",
            "agent_session_outputs",
            "browser_publish_runs",
            "browser_connections",
            "remote_article_identities",
            "remote_reconciliation_observations",
        } <= tables
        assert store._con.execute(
            "SELECT COUNT(*) FROM users WHERE id=?", (SEED_USER_ID,)
        ).fetchone()[0] == 1
        publish_columns = {
            row[1]
            for row in store._con.execute(
                "PRAGMA table_info(browser_publish_runs)"
            )
        }
        assert "mode" in publish_columns
        remote_identity_columns = {
            row[1]
            for row in store._con.execute(
                "PRAGMA table_info(remote_article_identities)"
            )
        }
        assert {
            "user_id",
            "platform",
            "remote_id",
            "article_id",
            "remote_content_fingerprint",
            "subtitle",
            "cover_asset_id",
            "last_sync_status",
            "last_sync_result_json",
            "remote_created_at",
            "remote_updated_at",
            "last_sync_started_at",
            "last_synced_at",
        } <= remote_identity_columns
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
