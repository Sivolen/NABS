"""Create missing restore tables only; never alter or delete existing data.

Run with the NABS virtualenv from the repository root before starting web/worker.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("FLASK_ENV", "testing")

from app import app, db
from app.models import (
    RestoreProfile,
    DeviceRestoreProfile,
    RestoreJob,
    RestoreJobEvent,
    RestoreInspection,
)


def main():
    with app.app_context(), db.engine.begin() as connection:
        for model in (
            RestoreProfile,
            DeviceRestoreProfile,
            RestoreJob,
            RestoreJobEvent,
            RestoreInspection,
        ):
            model.__table__.create(connection, checkfirst=True)
    print("Restore tables ready; no device operations started.")


if __name__ == "__main__":
    main()
