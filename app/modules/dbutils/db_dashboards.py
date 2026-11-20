"""Read-only aggregates for the dashboard, scoped to the device list."""

from calendar import month_abbr
from collections import Counter
from datetime import date

from sqlalchemy import func, select

from app import db
from app.modules.access import parse_id, role_of
from app.models import (
    AssociatingDevice,
    Configs,
    Devices,
    DeviceValidation,
    GroupPermission,
)


def _visible_devices(session_obj):
    devices = select(Devices.id)
    if session_obj.get("user") and role_of(session_obj) == "sadmin":
        return devices
    user_id = parse_id(session_obj.get("user_id")) if session_obj.get("user") else None
    if user_id is None:
        return devices.where(False)
    memberships = (
        select(AssociatingDevice.device_id)
        .join(
            GroupPermission,
            GroupPermission.user_group_id == AssociatingDevice.user_group_id,
        )
        .where(GroupPermission.user_id == user_id)
    )
    return devices.where(Devices.id.in_(memberships))


def _visible_snapshots(visible, year):
    # Configs.timestamp is stored as YYYY-MM-DD HH:MM. Grouping the prefix leaves
    # blank or legacy values out of the chart without trying to cast them to dates.
    month_key = func.substr(Configs.timestamp, 1, 7)
    return dict(
        db.session.query(month_key, func.count(Configs.id))
        .filter(
            Configs.device_id.in_(visible),
            Configs.timestamp >= f"{year}-01-01",
            Configs.timestamp < f"{year + 1}-01-01",
        )
        .group_by(month_key)
        .all()
    )


def _validation_summary(visible):
    latest = (
        select(func.max(DeviceValidation.id))
        .where(DeviceValidation.device_id.in_(visible))
        .group_by(DeviceValidation.device_id)
    )
    return dict(
        db.session.query(DeviceValidation.status, func.count(DeviceValidation.id))
        .filter(DeviceValidation.id.in_(latest))
        .group_by(DeviceValidation.status)
        .all()
    )


def _top(values):
    counts = Counter(
        value.strip() if value and value.strip() else "Unknown" for value in values
    )
    return sorted(
        counts.items(), key=lambda item: (-item[1], item[0].casefold(), item[0])
    )[:5]


def get_dashboard_summary(session_obj, year=None):
    """Return fleet counts, devices needing attention and recent activity."""
    visible = _visible_devices(session_obj)
    year = year or date.today().year
    latest_config = (
        db.session.query(
            Configs.device_id,
            func.max(Configs.id).label("config_id"),
            func.max(Configs.timestamp).label("saved_at"),
        )
        .filter(Configs.device_id.in_(visible))
        .group_by(Configs.device_id)
        .subquery()
    )
    devices = (
        db.session.query(
            Devices.id,
            Devices.device_hostname,
            Devices.device_ip,
            Devices.device_vendor,
            Devices.device_model,
            Devices.is_enabled,
            Devices.connection_status,
            Devices.timestamp,
            latest_config.c.config_id,
            latest_config.c.saved_at,
        )
        .outerjoin(latest_config, latest_config.c.device_id == Devices.id)
        .filter(Devices.id.in_(visible))
        .order_by(Devices.timestamp.desc().nulls_last(), Devices.id)
        .all()
    )
    disabled = covered = missing = errors = 0
    issues = []
    for device in devices:
        if not device.is_enabled:
            disabled += 1
            continue
        status = (device.connection_status or "").strip()
        has_backup = device.config_id is not None
        has_error = bool(status and status != "Ok")
        covered += has_backup
        missing += not has_backup
        errors += has_error
        if has_error or not has_backup:
            issues.append(
                {
                    "id": device.id,
                    "name": device.device_hostname
                    or device.device_ip
                    or f"Device #{device.id}",
                    "ip": device.device_ip,
                    "error": status if has_error else None,
                    "has_backup": has_backup,
                    "saved_at": device.saved_at,
                    "checked_at": device.timestamp if status else None,
                }
            )

    validation = _validation_summary(visible)
    monthly_counts = _visible_snapshots(visible, year)
    months = [
        {
            "name": month_abbr[month],
            "count": monthly_counts.get(f"{year}-{month:02d}", 0),
        }
        for month in range(1, 13)
    ]
    return {
        "total": len(devices),
        "enabled": len(devices) - disabled,
        "covered": covered,
        "missing": missing,
        "errors": errors,
        "disabled": disabled,
        "issues": issues,
        "vendors": _top(device.device_vendor for device in devices),
        "models": _top(device.device_model for device in devices),
        "validation": validation,
        "not_validated": len(devices) - sum(validation.values()),
        "months": months,
        "year": year,
        "snapshot_total": sum(month["count"] for month in months),
    }
