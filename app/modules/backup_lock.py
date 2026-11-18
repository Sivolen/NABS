"""Coordinate poll attempts across web workers and the scheduler on this host."""

from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from fasteners import InterProcessLock

_LOCK_DIR = Path(__file__).resolve().parents[2] / "logs" / "backup-locks"
_active_devices = set()
_active_guard = Lock()


@contextmanager
def device_backup_lock(device_id):
    with _active_guard:
        already_active = device_id in _active_devices
        if not already_active:
            _active_devices.add(device_id)
    if already_active:
        yield False
        return

    try:
        _LOCK_DIR.mkdir(parents=True, exist_ok=True)
        lock = InterProcessLock(str(_LOCK_DIR / f"{device_id}.lock"))
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()
    finally:
        with _active_guard:
            _active_devices.remove(device_id)
