"""BlogHub database migration, backup, verification, and restore commands."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DATABASE = Path(os.environ.get("BLOGHUB_DB_PATH", ROOT / "data" / "bloghub.db"))
BLOBS = Path(os.environ.get("BLOGHUB_BLOBS_DIR", ROOT / "data" / "blobs"))
BACKUPS = Path(os.environ.get("BLOGHUB_BACKUP_DIR", ROOT / "data" / "backups"))


def _status(_args: argparse.Namespace) -> int:
    # Imported lazily: touching backend.store opens (and, on a fresh file,
    # creates) the primary database, which `verify` below must not require.
    import backend.store as store
    from backend.store.schema import SCHEMA_VERSION

    connection = sqlite3.connect(DATABASE)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    print(f"database: {DATABASE.resolve()}")
    print(f"schema:   {store.schema_version()} / {SCHEMA_VERSION}")
    print(f"integrity: {integrity}")
    return 0


def _backup(args: argparse.Namespace) -> int:
    import backend.store as store

    if args.if_due_hours is None:
        bundle = store.create_backup(str(args.backup_dir), retain=args.retain)
    else:
        bundle = store.create_backup_if_due(
            timedelta(hours=args.if_due_hours),
            str(args.backup_dir),
            retain=args.retain,
        )
    if bundle is None:
        print("backup not due")
    else:
        print(bundle)
    return 0


def _verify(args: argparse.Namespace) -> int:
    from backend.store.backups import verify_backup

    manifest = verify_backup(args.bundle)
    print(f"verified: {Path(args.bundle).resolve()}")
    print(f"created:  {manifest['created_at']}")
    print(f"schema:   {manifest['summary']['schema_version']}")
    return 0


def _restore(args: argparse.Namespace) -> int:
    if not args.yes:
        raise SystemExit("restore requires --yes after BlogHub has been stopped")
    import backend.store as store
    from backend.store.backups import restore_backup

    store.close()
    restore_backup(args.bundle, DATABASE, BLOBS)
    print(f"restored: {Path(args.bundle).resolve()}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="show schema and integrity status")
    status.set_defaults(handler=_status)

    backup = commands.add_parser("backup", help="create an online verified backup")
    backup.add_argument("--backup-dir", type=Path, default=BACKUPS)
    backup.add_argument("--retain", type=int, default=14)
    backup.add_argument(
        "--if-due-hours",
        type=float,
        help="create a backup only when the newest backup is at least this old",
    )
    backup.set_defaults(handler=_backup)

    verify = commands.add_parser("verify", help="verify a backup bundle")
    verify.add_argument("bundle", type=Path)
    verify.set_defaults(handler=_verify)

    restore = commands.add_parser("restore", help="restore a verified backup")
    restore.add_argument("bundle", type=Path)
    restore.add_argument("--yes", action="store_true")
    restore.set_defaults(handler=_restore)
    return parser


def main() -> int:
    args = _parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

