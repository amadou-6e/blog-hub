#!/usr/bin/env python3
"""Run an independent BlogHub background worker."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=os.environ.get("BLOGHUB_DB_PATH", str(ROOT / "data" / "bloghub.db")),
    )
    parser.add_argument(
        "--blobs",
        default=os.environ.get("BLOGHUB_BLOBS_DIR", str(ROOT / "data" / "blobs")),
    )
    parser.add_argument("--queues", default="default,agents,publishing,sync")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--lease-seconds", type=int, default=30)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    os.environ["BLOGHUB_DB_PATH"] = args.database
    os.environ["BLOGHUB_BLOBS_DIR"] = args.blobs
    import backend.store as global_store
    from backend.workers.handlers import HANDLERS
    from backend.workers.worker import DurableWorker

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    store = global_store._backend
    worker = DurableWorker(
        store, HANDLERS, worker_id=args.worker_id,
        queues=tuple(item.strip() for item in args.queues.split(",") if item.strip()),
        lease_seconds=args.lease_seconds, poll_seconds=args.poll_seconds,
    )

    def stop(_signum, _frame):
        worker.stop()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        if args.once:
            worker.run_once()
        else:
            worker.run_forever()
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
