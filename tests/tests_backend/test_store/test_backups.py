from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from backend.store.backups import BackupError, restore_backup, verify_backup
from backend.store.backends.sqlite import SQLiteStore
from backend.store.schema import SCHEMA_VERSION


def _store(tmp_path):
    return SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))


def test_online_backup_contains_database_and_referenced_blobs(tmp_path):
    store = _store(tmp_path)
    try:
        store.store_asset(
            store.SEED_USER_ID,
            "art_001",
            "diagram.png",
            b"png-content",
            "image/png",
        )
        bundle = store.create_backup(str(tmp_path / "backups"))
        manifest = verify_backup(bundle)

        assert manifest["summary"]["schema_version"] == SCHEMA_VERSION
        assert manifest["summary"]["counts"]["articles"] == 6
        assert manifest["summary"]["counts"]["article_assets"] == 1
        assert manifest["summary"]["counts"]["article_revisions"] == 6
        assert manifest["summary"]["referenced_blob_count"] == 7
        assert (
            bundle / "blobs" / "articles" / "art_001" / "body.md"
        ).is_file()
        assert (
            bundle / "blobs" / "articles" / "art_001" / "assets" / "diagram.png"
        ).read_bytes() == b"png-content"
    finally:
        store.close()


def test_backup_reads_committed_wal_content(tmp_path):
    store = _store(tmp_path)
    try:
        store.update_article_title(store.SEED_USER_ID, "art_001", "In the WAL")
        bundle = store.create_backup(str(tmp_path / "backups"))
        restored = sqlite3.connect(bundle / "bloghub.sqlite3")
        try:
            title = restored.execute(
                "SELECT title FROM articles WHERE id='art_001'"
            ).fetchone()[0]
            assert title == "In the WAL"
        finally:
            restored.close()
    finally:
        store.close()


def test_tampered_backup_fails_verification(tmp_path):
    store = _store(tmp_path)
    try:
        bundle = store.create_backup(str(tmp_path / "backups"))
    finally:
        store.close()
    with (bundle / "bloghub.sqlite3").open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(BackupError, match="checksum"):
        verify_backup(bundle)


def test_restore_round_trip_recovers_database_and_blobs(tmp_path):
    store = _store(tmp_path)
    store.update_article_title(store.SEED_USER_ID, "art_001", "Before backup")
    store.store_asset(
        store.SEED_USER_ID,
        "art_001",
        "cover.png",
        b"original-cover",
        "image/png",
    )
    bundle = store.create_backup(str(tmp_path / "backups"))
    store.update_article_title(store.SEED_USER_ID, "art_001", "After backup")
    asset = tmp_path / "blobs" / "articles" / "art_001" / "assets" / "cover.png"
    asset.write_bytes(b"changed-cover")
    store.close()

    restore_backup(bundle, tmp_path / "bloghub.db", tmp_path / "blobs")

    restored = sqlite3.connect(tmp_path / "bloghub.db")
    try:
        assert restored.execute(
            "SELECT title FROM articles WHERE id='art_001'"
        ).fetchone()[0] == "Before backup"
    finally:
        restored.close()
    assert asset.read_bytes() == b"original-cover"


def test_retention_keeps_only_newest_bundles(tmp_path):
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"
    try:
        for offset in range(3):
            from backend.store.backups import create_backup

            create_backup(
                store._con,
                tmp_path / "blobs",
                backup_dir,
                retain=2,
                now=datetime(2026, 1, 1, offset, tzinfo=timezone.utc),
            )
        bundles = sorted(path.name for path in backup_dir.iterdir() if path.is_dir())
        assert bundles == [
            "bloghub-20260101T010000.000000Z",
            "bloghub-20260101T020000.000000Z",
        ]
    finally:
        store.close()


def test_scheduled_backup_runs_only_when_due(tmp_path):
    from backend.store.backups import create_backup_if_due

    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    try:
        first = create_backup_if_due(
            store._con,
            tmp_path / "blobs",
            backup_dir,
            interval=timedelta(hours=24),
            now=start,
        )
        not_due = create_backup_if_due(
            store._con,
            tmp_path / "blobs",
            backup_dir,
            interval=timedelta(hours=24),
            now=start + timedelta(hours=23),
        )
        due = create_backup_if_due(
            store._con,
            tmp_path / "blobs",
            backup_dir,
            interval=timedelta(hours=24),
            now=start + timedelta(hours=24),
        )
        assert first is not None
        assert not_due is None
        assert due is not None
    finally:
        store.close()


def test_backup_waits_for_workspace_file_operations(tmp_path):
    writer = _store(tmp_path)
    backup_reader = _store(tmp_path)
    started = threading.Event()

    def run_backup():
        started.set()
        return backup_reader.create_backup(str(tmp_path / "backups"))

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with writer._workspace_lock.acquire():
                future = executor.submit(run_backup)
                assert started.wait(timeout=1)
                time.sleep(0.05)
                assert not future.done()
            assert verify_backup(future.result(timeout=5))
    finally:
        backup_reader.close()
        writer.close()
