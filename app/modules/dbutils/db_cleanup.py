"""
Automatic cleanup of old device configurations (retention policy).

The retention period is taken from ``CONFIG_RETENTION_DAYS`` in config.py.
The function is executed once a day by the standalone scheduler
(scheduler_runner.py, job ``config_cleanup_job``).

Rules:
    * configs older than the cutoff date are deleted;
    * the latest config of every device is NEVER deleted, even if it is older
      than the retention period;
    * configs with an unparsable timestamp are skipped (and logged);
    * deletion is done with a few bulk DELETE statements, not row by row.
"""

import logging
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Tuple

from app import db
from app.models import Configs

DEFAULT_CONFIG_RETENTION_DAYS = 365

# Configs.timestamp is stored as a string, e.g. "2026-09-29 14:32"
TIMESTAMP_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")

# Max number of ids in a single "DELETE ... WHERE id IN (...)" statement
DELETE_CHUNK_SIZE = 5000

# Do not flood the scheduler log if a lot of timestamps are broken
MAX_INVALID_TIMESTAMP_WARNINGS = 20

# The cleanup runs inside the scheduler process, whose root logger writes to
# logs/nabs-scheduler.log
cleanup_logger = logging.getLogger("scheduler.config_cleanup")


def get_retention_days() -> int:
    """
    Returns CONFIG_RETENTION_DAYS from config.py.

    Falls back to 365 days if the option is missing (config.py created before
    this option appeared) or contains an invalid value.
    """
    try:
        from config import CONFIG_RETENTION_DAYS
    except ImportError:
        return DEFAULT_CONFIG_RETENTION_DAYS

    try:
        days = int(CONFIG_RETENTION_DAYS)
    except (TypeError, ValueError):
        days = 0

    if days <= 0:
        cleanup_logger.warning(
            "Invalid CONFIG_RETENTION_DAYS value %r, using default %d days",
            CONFIG_RETENTION_DAYS,
            DEFAULT_CONFIG_RETENTION_DAYS,
        )
        return DEFAULT_CONFIG_RETENTION_DAYS
    return days


def parse_config_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Converts a stored timestamp string to datetime, None if it is invalid."""
    if not isinstance(value, str):
        return None
    for timestamp_format in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value.strip(), timestamp_format)
        except ValueError:
            continue
    return None


def select_configs_to_delete(
    rows: Iterable[Tuple[int, Optional[int], str, Optional[str]]],
    cutoff: datetime,
    log: logging.Logger = cleanup_logger,
) -> Tuple[List[int], dict]:
    """
    Decides which configs must be deleted. Pure function, does not touch the DB.

    Args:
        rows: (config_id, device_id, device_ip, timestamp) for every config.
        cutoff: configs with timestamp < cutoff are considered old.
        log: logger for warnings about invalid timestamps.

    Returns:
        (ids_to_delete, stats) where stats contains:
            found     - number of old configs (older than cutoff);
            preserved - number of old configs kept because they are the latest
                        config of their device;
            invalid   - number of configs skipped because of a broken timestamp.
    """
    latest_by_device = {}  # device key -> (timestamp, config_id) of the latest
    old_configs = []  # config ids older than cutoff
    invalid = 0

    for config_id, device_id, device_ip, raw_timestamp in rows:
        timestamp = parse_config_timestamp(raw_timestamp)
        if timestamp is None:
            invalid += 1
            if invalid <= MAX_INVALID_TIMESTAMP_WARNINGS:
                log.warning(
                    'Invalid config timestamp for config ID %s: "%s"',
                    config_id,
                    raw_timestamp,
                )
            continue

        # Configs without device_id are grouped by IP address
        device_key = device_id if device_id is not None else ("ip", device_ip)
        current_latest = latest_by_device.get(device_key)
        if current_latest is None or (timestamp, config_id) > current_latest:
            latest_by_device[device_key] = (timestamp, config_id)

        if timestamp < cutoff:
            old_configs.append(config_id)

    if invalid > MAX_INVALID_TIMESTAMP_WARNINGS:
        log.warning(
            "... and %d more configs with invalid timestamp",
            invalid - MAX_INVALID_TIMESTAMP_WARNINGS,
        )

    protected_ids = {config_id for _, config_id in latest_by_device.values()}
    ids_to_delete = [
        config_id for config_id in old_configs if config_id not in protected_ids
    ]
    stats = {
        "found": len(old_configs),
        "preserved": len(old_configs) - len(ids_to_delete),
        "invalid": invalid,
    }
    return ids_to_delete, stats


def cleanup_old_configs(
    retention_days: Optional[int] = None, now: Optional[datetime] = None
) -> Optional[dict]:
    """
    Deletes configs older than the retention period, keeping the latest config
    of every device.

    Never raises: any error is logged, the transaction is rolled back and None
    is returned, so the scheduler (and the backup job) keep working.

    Returns:
        dict with keys found / deleted / preserved / invalid, or None on error.
    """
    log = cleanup_logger
    log.info("Starting old configs cleanup")
    try:
        if retention_days is None:
            retention_days = get_retention_days()
        log.info("Retention period: %d days", retention_days)

        now = now or datetime.now()
        cutoff = (now - timedelta(days=retention_days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        log.info("Cutoff: %s", cutoff.strftime("%Y-%m-%d %H:%M"))

        # Only small columns are loaded here, not the config texts
        rows = db.session.query(
            Configs.id, Configs.device_id, Configs.device_ip, Configs.timestamp
        ).all()
        ids_to_delete, stats = select_configs_to_delete(rows, cutoff, log)
        log.info("Found %d old configs", stats["found"])

        deleted = 0
        for start in range(0, len(ids_to_delete), DELETE_CHUNK_SIZE):
            chunk = ids_to_delete[start : start + DELETE_CHUNK_SIZE]
            deleted += Configs.query.filter(Configs.id.in_(chunk)).delete(
                synchronize_session=False
            )
        db.session.commit()

        stats["deleted"] = deleted
        log.info("Deleted configs: %d", deleted)
        log.info("Preserved %d latest configs", stats["preserved"])
        log.info("Cleanup completed")
        return stats
    except Exception as error:
        db.session.rollback()
        log.error("Config cleanup failed: %s", error, exc_info=True)
        return None
