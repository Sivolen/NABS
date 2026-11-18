"""
Restore worker: the only place where restore jobs touch devices.

One worker process (a systemd service, plus a database advisory lock) takes:
  * jobs with requested_action == "precheck"  -> engine.run_precheck()
  * jobs in state `queued` (confirmed)        -> engine.execute()
one at a time, so at most one restore runs on the system. At start it calls
engine.recover_interrupted(): jobs claimed by a dead worker become `unknown` and are
never resumed.
"""

import logging
import time
from typing import Callable, Optional

from app.modules.backup_lock import device_backup_lock
from app.modules.restore import states as st
from app.modules.restore.engine import RestoreEngine
from app.modules.restore.storage import JobStore

log = logging.getLogger("nabs.restore.worker")


class RestoreWorker:
    def __init__(
        self,
        engine: RestoreEngine,
        store: JobStore,
        worker_id: str,
        poll_seconds: float = 3.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.engine = engine
        self.store = store
        self.worker_id = worker_id
        self.poll_seconds = poll_seconds
        self._sleep = sleep

    def start(self) -> list:
        """Call once at startup, only when no other worker is alive."""
        marked = self.engine.recover_interrupted()
        if marked:
            log.warning("jobs marked unknown after a restart: %s", marked)
        return marked

    def run_once(self) -> int:
        """Process everything that is pending now; returns the number of jobs handled."""
        handled = 0
        # confirmed jobs first: their confirmation expires
        for job in sorted(self.store.list_jobs([st.QUEUED]), key=lambda j: j.id):
            # Share the backup lock before claiming the job. A busy device stays
            # queued; the next poll retries without applying anything twice.
            with device_backup_lock(job.device_id) as acquired:
                if acquired:
                    handled += self._safely(
                        lambda j=job: self.engine.execute(j.id, self.worker_id), job.id
                    )
        for job in sorted(self.store.list_requested("precheck"), key=lambda j: j.id):
            with device_backup_lock(job.device_id) as acquired:
                if acquired and self.store.claim_requested_action(job.id, "precheck"):
                    handled += self._safely(
                        lambda j=job: self.engine.run_precheck(j.id), job.id
                    )
        return handled

    @staticmethod
    def _safely(action: Callable[[], object], job_id: int) -> int:
        try:
            action()
            return 1
        except Exception:  # one broken job must not stop the worker
            log.exception("restore job %s: unexpected error in the worker", job_id)
            return 0

    def run_forever(self, should_stop: Optional[Callable[[], bool]] = None) -> None:
        self.start()
        while not (should_stop and should_stop()):
            if self.run_once() == 0:
                self._sleep(self.poll_seconds)
