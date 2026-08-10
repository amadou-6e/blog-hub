#!/usr/bin/env python3
"""Rotate BlogHub's local credential-encryption key."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.store.backends.sqlite import SQLiteStore  # noqa: E402
from backend.store.crypto import (  # noqa: E402
    get_key_provider,
    retire_inactive_file_keys,
    rotate_file_key,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("status", "migrate", "rotate", "retire"),
        help="inspect, migrate, rotate, or retire inactive local keys",
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("BLOGHUB_DB_PATH", str(ROOT / "data" / "bloghub.db")),
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="confirm irreversible retirement of inactive keys",
    )
    args = parser.parse_args()

    key_id, _ = get_key_provider().active_key()
    if args.command == "status":
        print(f"active key: {key_id}")
        print(f"available keys: {len(get_key_provider().keys())}")
        return 0

    if args.command == "retire":
        if not args.confirm:
            parser.error("retire requires --confirm after backup and connection verification")
        print(f"retired keys removed: {retire_inactive_file_keys()}")
        return 0

    store = SQLiteStore(args.database, str(Path(args.database).parent / "blobs"))
    if args.command == "migrate":
        print(f"re-encrypted credentials: {store.reencrypt_connection_credentials()}")
        return 0

    new_key_id = rotate_file_key()
    migrated = store.reencrypt_connection_credentials()
    print(f"active key: {new_key_id}")
    print(f"re-encrypted credentials: {migrated}")
    print("inactive keys retained; use 'retire --confirm' after verification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
