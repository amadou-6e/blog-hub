"""Verified SQLite and blob backups for BlogHub."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


MANIFEST_NAME = "manifest.json"
DATABASE_NAME = "bloghub.sqlite3"
BLOBS_NAME = "blobs"
BACKUP_FORMAT_VERSION = 1


class BackupError(RuntimeError):
    """Raised when a backup cannot be created, verified, or restored."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rename_verified_bundle(source: Path, target: Path) -> None:
    for attempt in range(5):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_blob_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise BackupError(f"Blob path escapes the workspace: {relative}") from exc
    return candidate


def _referenced_blobs(connection: sqlite3.Connection) -> list[str]:
    paths: list[str] = []
    article_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(articles)").fetchall()
    }
    if "body_path" in article_columns:
        paths.extend(
            row[0]
            for row in connection.execute(
                "SELECT body_path FROM articles WHERE body_path IS NOT NULL"
            )
        )
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='article_assets'"
    ).fetchone():
        paths.extend(
            row[0]
            for row in connection.execute("SELECT asset_path FROM article_assets")
        )
    return sorted(set(paths))


def _database_summary(database_path: Path, blobs_path: Path) -> dict:
    connection = sqlite3.connect(database_path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise BackupError(f"SQLite integrity check failed: {integrity}")
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise BackupError(
                f"SQLite foreign-key check found {len(foreign_key_errors)} violation(s)"
            )
        missing = [
            path
            for path in _referenced_blobs(connection)
            if not _safe_blob_path(blobs_path, path).is_file()
        ]
        if missing:
            raise BackupError(
                "Backup is missing referenced blob files: " + ", ".join(missing[:5])
            )
        counts = {}
        tables = (
            "users",
            "articles",
            "article_assets",
            "remote_article_identities",
            "remote_reconciliation_observations",
            "article_revisions",
            "connections",
            "jobs",
            "sessions",
        )
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for table in tables:
            if table in existing:
                counts[table] = connection.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
        return {
            "schema_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "counts": counts,
            "referenced_blob_count": len(_referenced_blobs(connection)),
        }
    finally:
        connection.close()


def verify_backup(bundle_path: str | Path) -> dict:
    """Verify a backup bundle and return its manifest."""
    bundle = Path(bundle_path).resolve()
    manifest_path = bundle / MANIFEST_NAME
    database_path = bundle / DATABASE_NAME
    blobs_path = bundle / BLOBS_NAME
    if not manifest_path.is_file() or not database_path.is_file():
        raise BackupError(f"Not a complete BlogHub backup: {bundle}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError(f"Invalid backup manifest: {exc}") from exc
    if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        raise BackupError(
            f"Unsupported backup format: {manifest.get('format_version')!r}"
        )
    actual_hash = _sha256(database_path)
    if actual_hash != manifest.get("database_sha256"):
        raise BackupError("Backup database checksum does not match its manifest")
    summary = _database_summary(database_path, blobs_path)
    if summary != manifest.get("summary"):
        raise BackupError("Backup contents do not match the recorded summary")
    return manifest


def create_backup(
    source: sqlite3.Connection,
    blobs_dir: str | Path,
    backup_dir: str | Path,
    *,
    retain: int = 14,
    now: datetime | None = None,
) -> Path:
    """Create and verify an atomic backup bundle from an open SQLite connection."""
    if retain < 1:
        raise ValueError("retain must be at least 1")
    created_at = (now or _utc_now()).astimezone(timezone.utc)
    root = Path(backup_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    name = created_at.strftime("bloghub-%Y%m%dT%H%M%S.%fZ")
    final = root / name
    if final.exists():
        final = root / f"{name}-{uuid.uuid4().hex[:8]}"
    temporary = root / f".{final.name}.tmp-{uuid.uuid4().hex[:8]}"
    temporary.mkdir()
    try:
        database_path = temporary / DATABASE_NAME
        destination = sqlite3.connect(database_path)
        try:
            source.backup(destination)
        finally:
            destination.close()

        source_blobs = Path(blobs_dir).resolve()
        target_blobs = temporary / BLOBS_NAME
        if source_blobs.exists():
            shutil.copytree(source_blobs, target_blobs)
        else:
            target_blobs.mkdir()

        summary = _database_summary(database_path, target_blobs)
        manifest = {
            "format_version": BACKUP_FORMAT_VERSION,
            "created_at": created_at.isoformat(),
            "database_file": DATABASE_NAME,
            "blobs_directory": BLOBS_NAME,
            "database_sha256": _sha256(database_path),
            "summary": summary,
        }
        (temporary / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        verify_backup(temporary)
        _rename_verified_bundle(temporary, final)
        prune_backups(root, retain=retain)
        return final
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _backup_bundles(backup_dir: Path) -> list[Path]:
    if not backup_dir.exists():
        return []
    return sorted(
        (
            path
            for path in backup_dir.iterdir()
            if path.is_dir() and (path / MANIFEST_NAME).is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )


def prune_backups(backup_dir: str | Path, *, retain: int) -> list[Path]:
    if retain < 1:
        raise ValueError("retain must be at least 1")
    removed = _backup_bundles(Path(backup_dir).resolve())[retain:]
    for path in removed:
        shutil.rmtree(path)
    return removed


def create_backup_if_due(
    source: sqlite3.Connection,
    blobs_dir: str | Path,
    backup_dir: str | Path,
    *,
    interval: timedelta,
    retain: int = 14,
    now: datetime | None = None,
) -> Path | None:
    if interval.total_seconds() <= 0:
        raise ValueError("interval must be positive")
    current_time = (now or _utc_now()).astimezone(timezone.utc)
    bundles = _backup_bundles(Path(backup_dir).resolve())
    if bundles:
        manifest = verify_backup(bundles[0])
        last_created = datetime.fromisoformat(manifest["created_at"])
        if current_time - last_created < interval:
            return None
    return create_backup(
        source, blobs_dir, backup_dir, retain=retain, now=current_time
    )


def restore_backup(
    bundle_path: str | Path,
    database_path: str | Path,
    blobs_dir: str | Path,
) -> None:
    """Restore a verified bundle. The BlogHub process must be stopped first."""
    bundle = Path(bundle_path).resolve()
    verify_backup(bundle)
    target_database = Path(database_path).resolve()
    target_blobs = Path(blobs_dir).resolve()
    target_database.parent.mkdir(parents=True, exist_ok=True)
    target_blobs.parent.mkdir(parents=True, exist_ok=True)

    suffix = uuid.uuid4().hex[:8]
    staged_database = target_database.with_name(f".{target_database.name}.restore-{suffix}")
    staged_blobs = target_blobs.with_name(f".{target_blobs.name}.restore-{suffix}")
    rollback_database = target_database.with_name(f".{target_database.name}.rollback-{suffix}")
    rollback_blobs = target_blobs.with_name(f".{target_blobs.name}.rollback-{suffix}")
    shutil.copy2(bundle / DATABASE_NAME, staged_database)
    shutil.copytree(bundle / BLOBS_NAME, staged_blobs)

    moved_database = False
    moved_blobs = False
    try:
        for sidecar in (
            Path(f"{target_database}-wal"),
            Path(f"{target_database}-shm"),
        ):
            sidecar.unlink(missing_ok=True)
        if target_database.exists():
            os.replace(target_database, rollback_database)
            moved_database = True
        if target_blobs.exists():
            os.replace(target_blobs, rollback_blobs)
            moved_blobs = True
        os.replace(staged_database, target_database)
        os.replace(staged_blobs, target_blobs)
        rollback_database.unlink(missing_ok=True)
        if rollback_blobs.exists():
            shutil.rmtree(rollback_blobs)
    except Exception:
        target_database.unlink(missing_ok=True)
        if target_blobs.exists():
            shutil.rmtree(target_blobs)
        if moved_database and rollback_database.exists():
            os.replace(rollback_database, target_database)
        if moved_blobs and rollback_blobs.exists():
            os.replace(rollback_blobs, target_blobs)
        raise
    finally:
        staged_database.unlink(missing_ok=True)
        if staged_blobs.exists():
            shutil.rmtree(staged_blobs)
