from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from backend.schemas.remote_articles import RemoteArticleIdentity
from backend.store.backends.sqlite import SQLiteStore
from backend.store.schema import SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[3]


def _store(tmp_path) -> SQLiteStore:
    return SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))


def _cover_asset_id(store: SQLiteStore, article_id: str) -> int:
    store.store_asset(
        store.SEED_USER_ID, article_id, "cover.png", b"cover", "image/png",
    )
    return store._con.execute(
        "SELECT id FROM article_assets WHERE article_id=? AND filename='cover.png'",
        (article_id,),
    ).fetchone()[0]


def test_remote_identity_and_sync_metadata_round_trip(tmp_path):
    store = _store(tmp_path)
    try:
        article = store.create_article(store.SEED_USER_ID, "Remote article")
        cover_asset_id = _cover_asset_id(store, article["id"])
        identity = store.upsert_remote_article_identity(
            store.SEED_USER_ID,
            article["id"],
            "Hashnode",
            "remote-123",
            remote_content_fingerprint="sha256:content-v1",
            subtitle="A durable subtitle",
            cover_asset_id=cover_asset_id,
            last_sync_status="partial",
            last_sync_result={"articlesUpdated": 1, "imagesFailed": 1},
            last_sync_error="one image was unavailable",
            remote_created_at="2026-08-01T10:00:00+00:00",
            remote_updated_at="2026-08-19T12:00:00+00:00",
            last_sync_started_at="2026-08-20T07:59:00+00:00",
            last_synced_at="2026-08-20T08:00:00+00:00",
        )

        assert identity["platform"] == "hashnode"
        assert identity["remote_content_fingerprint"] == "sha256:content-v1"
        assert identity["subtitle"] == "A durable subtitle"
        assert identity["cover_asset_id"] == cover_asset_id
        assert identity["last_sync_status"] == "partial"
        assert identity["last_sync_result"] == {
            "articlesUpdated": 1,
            "imagesFailed": 1,
        }
        assert identity["last_sync_error"] == "one image was unavailable"
        assert identity["remote_created_at"] == "2026-08-01T10:00:00+00:00"
        assert identity["remote_updated_at"] == "2026-08-19T12:00:00+00:00"
        assert identity["last_sync_started_at"] == "2026-08-20T07:59:00+00:00"
        assert identity["last_synced_at"] == "2026-08-20T08:00:00+00:00"

        api_model = RemoteArticleIdentity.model_validate(identity)
        payload = api_model.model_dump(by_alias=True, mode="json")
        assert payload["articleId"] == article["id"]
        assert payload["remoteId"] == "remote-123"
        assert payload["lastSyncStatus"] == "partial"
        assert payload["lastSyncResult"]["imagesFailed"] == 1
    finally:
        store.close()


def test_remote_identity_is_stable_and_unique_per_user_platform_remote_id(tmp_path):
    store = _store(tmp_path)
    try:
        first = store.create_article(store.SEED_USER_ID, "First")
        second = store.create_article(store.SEED_USER_ID, "Second")
        store.upsert_remote_article_identity(
            store.SEED_USER_ID, first["id"], "hashnode", "same-id",
            subtitle="Before",
        )
        with pytest.raises(sqlite3.IntegrityError):
            with store._con:
                store._con.execute(
                    """INSERT INTO remote_article_identities
                       (user_id, platform, remote_id, article_id, created_at, updated_at)
                       VALUES (?,?,?,?,?,?)""",
                    (
                        store.SEED_USER_ID,
                        "hashnode",
                        "same-id",
                        second["id"],
                        "2026-08-20T08:00:00+00:00",
                        "2026-08-20T08:00:00+00:00",
                    ),
                )
        updated = store.upsert_remote_article_identity(
            store.SEED_USER_ID, first["id"], "hashnode", "same-id",
            subtitle="After",
        )
        assert updated["article_id"] == first["id"]
        assert updated["subtitle"] == "After"

        with pytest.raises(ValueError, match="already mapped"):
            store.upsert_remote_article_identity(
                store.SEED_USER_ID, second["id"], "hashnode", "same-id",
            )

        other_user = store.create_user("remote-owner@example.com", "hash")
        other_article = store.create_article(other_user["id"], "Other user's copy")
        other = store.upsert_remote_article_identity(
            other_user["id"], other_article["id"], "hashnode", "same-id",
        )
        assert other["article_id"] == other_article["id"]
        assert store._con.execute(
            """SELECT COUNT(*) FROM remote_article_identities
               WHERE platform='hashnode' AND remote_id='same-id'"""
        ).fetchone()[0] == 2
    finally:
        store.close()


def test_remote_identity_enforces_article_and_cover_ownership(tmp_path):
    store = _store(tmp_path)
    try:
        seed_article = store.create_article(store.SEED_USER_ID, "Seed article")
        other_user = store.create_user("other-owner@example.com", "hash")
        other_article = store.create_article(other_user["id"], "Other article")
        other_cover = store.store_asset(
            other_user["id"], other_article["id"], "cover.png", b"other", "image/png",
        )
        assert other_cover
        other_cover_id = store._con.execute(
            "SELECT id FROM article_assets WHERE article_id=?",
            (other_article["id"],),
        ).fetchone()[0]

        with pytest.raises(KeyError, match="not found for user"):
            store.upsert_remote_article_identity(
                store.SEED_USER_ID, other_article["id"], "hashnode", "foreign-article",
            )
        with pytest.raises(ValueError, match="must belong"):
            store.upsert_remote_article_identity(
                store.SEED_USER_ID,
                seed_article["id"],
                "hashnode",
                "foreign-cover",
                cover_asset_id=other_cover_id,
            )

        with pytest.raises(sqlite3.IntegrityError):
            with store._con:
                store._con.execute(
                    """INSERT INTO remote_article_identities
                       (user_id, platform, remote_id, article_id, created_at, updated_at)
                       VALUES (?,?,?,?,?,?)""",
                    (
                        store.SEED_USER_ID,
                        "hashnode",
                        "foreign-direct",
                        other_article["id"],
                        "2026-08-20T08:00:00+00:00",
                        "2026-08-20T08:00:00+00:00",
                    ),
                )
    finally:
        store.close()


def test_remote_identity_foreign_key_deletion_behavior(tmp_path):
    store = _store(tmp_path)
    try:
        article = store.create_article(store.SEED_USER_ID, "Delete behavior")
        cover_asset_id = _cover_asset_id(store, article["id"])
        store.upsert_remote_article_identity(
            store.SEED_USER_ID,
            article["id"],
            "hashnode",
            "delete-test",
            cover_asset_id=cover_asset_id,
        )

        with store._con:
            store._con.execute("DELETE FROM article_assets WHERE id=?", (cover_asset_id,))
        without_cover = store.get_remote_article_identity(
            store.SEED_USER_ID, "hashnode", "delete-test",
        )
        assert without_cover["cover_asset_id"] is None

        assert store.delete_articles(store.SEED_USER_ID, [article["id"]]) == []
        assert store.get_remote_article_identity(
            store.SEED_USER_ID, "hashnode", "delete-test",
        ) is None

        other_user = store.create_user("deleted-owner@example.com", "hash")
        other_article = store.create_article(other_user["id"], "User cascade")
        store.upsert_remote_article_identity(
            other_user["id"], other_article["id"], "hashnode", "user-delete",
        )
        with store._con:
            store._con.execute("DELETE FROM users WHERE id=?", (other_user["id"],))
        assert store._con.execute(
            "SELECT COUNT(*) FROM remote_article_identities WHERE remote_id='user-delete'"
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_v7_database_migrates_without_changing_native_articles(tmp_path):
    database = tmp_path / "bloghub.db"
    blobs = tmp_path / "blobs"
    store = SQLiteStore(str(database), str(blobs))
    store.update_article_title(store.SEED_USER_ID, "art_001", "Preserved native article")
    with store._con:
        store._con.execute("DROP TABLE remote_article_identities")
        store._con.execute("PRAGMA user_version = 7")
    store.close()

    migrated = SQLiteStore(str(database), str(blobs))
    try:
        assert migrated.schema_version == SCHEMA_VERSION == 8
        assert migrated.get_article(migrated.SEED_USER_ID, "art_001")["title"] == (
            "Preserved native article"
        )
        assert migrated._con.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name='remote_article_identities'"""
        ).fetchone()
        assert migrated.list_article_remote_identities(
            migrated.SEED_USER_ID, "art_001",
        ) == []
    finally:
        migrated.close()


def test_remote_article_typescript_contract_matches_api_model():
    source = (ROOT / "contracts" / "remote-articles.ts").read_text(encoding="utf-8")
    body = re.search(
        r"export interface RemoteArticleIdentity\s*\{(?P<body>.*?)\}",
        source,
        re.DOTALL,
    ).group("body")
    typescript_fields = {
        line.strip().split(":", 1)[0].rstrip("?")
        for line in body.splitlines()
        if ":" in line
    }
    model_fields = {
        field.alias or name
        for name, field in RemoteArticleIdentity.model_fields.items()
    }
    assert typescript_fields == model_fields
