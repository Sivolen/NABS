#!/usr/bin/env python
"""
Restore worker for NABS (standalone systemd service, see
supervisor/nabs-restore-worker.service). It is the only process that connects to
devices to restore configurations. A PostgreSQL advisory lock guarantees that only one
worker runs, so recover_interrupted() can safely mark jobs left by a dead worker.
"""

import argparse
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text

from app import app, db

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "nabs-restore-worker.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("nabs.restore.worker")

ADVISORY_LOCK_KEY = 7270011  # one restore worker per database


def run_inspection_only(worker, should_stop, sleep=time.sleep):
    """This loop has no restore engine and never reads or executes restore jobs."""
    worker.start()
    while not should_stop():
        if worker.run_once() == 0:
            sleep(3)


def main() -> int:
    parser = argparse.ArgumentParser(description="NABS background operations")
    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help="Read software information only; never execute restore jobs",
    )
    args = parser.parse_args()
    from app.modules.restore.adapters import create_adapter
    from app.modules.restore.settings import unverified_adapters_enabled

    try:
        from config import clear_patterns
    except ImportError:
        clear_patterns = []
    from app.modules.restore.db_store import DbConfigStore, DbDeviceProvider, DbJobStore
    from app.modules.restore.engine import RestoreEngine
    from app.modules.restore.worker import RestoreWorker
    from app.modules.restore.inspection import DbInspectionStore, InspectionWorker

    def adapter_factory(adapter_type):
        # the mock is never registered here; unverified adapters only when enabled
        return create_adapter(
            adapter_type,
            include_unverified=unverified_adapters_enabled(),
            ignore_patterns=clear_patterns,
        )

    stop = {"now": False}
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.__setitem__("now", True))

    with app.app_context():
        lock_connection = db.engine.connect()  # held for the whole life of the process
        got = lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY}
        ).scalar()
        if not got:
            log.error("another restore worker is already running; exiting")
            return 1
        if args.inspect_only:
            log.info(
                "read-only software inspection worker started; restore execution disabled"
            )
            run_inspection_only(
                InspectionWorker(DbInspectionStore(), DbDeviceProvider()),
                lambda: stop["now"],
            )
            log.info("read-only inspection worker stopped")
            return 0
        store = DbJobStore()
        engine = RestoreEngine(
            store, DbConfigStore(), DbDeviceProvider(), adapter_factory
        )
        worker = RestoreWorker(
            engine,
            store,
            f"{socket.gethostname()}:{os.getpid()}",
            inspections=InspectionWorker(DbInspectionStore(), DbDeviceProvider()),
        )
        log.info("restore worker started")
        worker.run_forever(lambda: stop["now"])
        log.info("restore worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
