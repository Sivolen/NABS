"""
Which stored configurations the Restore Engine still needs.

A job references two rows of `Configs`: the target configuration and the pre-restore
copy. Deleting them while the job is unfinished (or ended in an unclear state) would
destroy what is needed to finish, roll back or investigate it, so the retention cleanup
and the manual delete must leave them alone.
"""

import json
import logging
from typing import Set

from sqlalchemy.exc import ProgrammingError

from app import db

logger = logging.getLogger(__name__)

# These states no longer need their configurations. `failed` is handled separately because
# it can mean either "blocked before touching the device" or "apply/persist failed after changes".
# `unknown` and `rollback_failed` deliberately stay protected until an operator checks the device.
RELEASED_JOB_STATUSES = ("success", "failed_rollback_confirmed", "cancelled")


def _diagnostics_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def get_restore_protected_config_ids() -> Set[int]:
    """
    Ids of configs referenced by restore jobs that are not finished cleanly.
    An installation that has not created the restore tables yet has none.
    Any other database error is raised: the callers then do NOT delete anything.
    """
    from app.models import RestoreJob  # lazy: older installations may lack the table

    try:
        # Read status and diagnostics as well as both config ids. A plain status filter would
        # incorrectly release configs for a `failed` job that already touched the device.
        rows = (
            db.session.query(
                RestoreJob.target_config_id,
                RestoreJob.pre_restore_config_id,
                RestoreJob.status,
                RestoreJob.diagnostics,
            )
            .filter(~RestoreJob.status.in_(RELEASED_JOB_STATUSES))
            .all()
        )
    except ProgrammingError as error:
        db.session.rollback()
        if "restore_jobs" in str(error) and "does not exist" in str(error).lower():
            return set()
        raise
    protected: Set[int] = set()
    released = set(RELEASED_JOB_STATUSES)
    for target_id, pre_restore_id, status, raw_diagnostics in rows:
        status = str(status or "")
        diagnostics = _diagnostics_dict(raw_diagnostics)
        if status in released:
            continue
        if status == "failed" and diagnostics.get("device_touched") is False:
            continue
        manual_resolution = diagnostics.get("manual_resolution")
        if not isinstance(manual_resolution, dict):
            manual_resolution = {}
        if (
            status == "resolved_manual"
            and manual_resolution.get("resolution")
            in {"target_confirmed", "pre_restore_confirmed"}
            and manual_resolution.get("device_identity_confirmed") is True
        ):
            continue
        for config_id in (target_id, pre_restore_id):
            if config_id is not None:
                protected.add(config_id)
    return protected
