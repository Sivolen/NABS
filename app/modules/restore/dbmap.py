"""Pure mapping between storage records and database columns (no database imports)."""

import json
from typing import Any, Dict, Optional

from app.modules.restore.storage import JobRecord, UserProfileRecord

JSON_FIELDS = ("diagnostics", "precheck_result")
# column -> max length (the models use String columns of these sizes)
MAX_LENGTHS = {"summary": 500, "stage": 60, "rollback_details": 4000}
JOB_FIELDS = tuple(JobRecord.__dataclass_fields__)


def dumps_json(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def loads_json(text: Optional[str], default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


def fields_to_columns(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Record fields -> column values (JSON encoding, length limits, unknown names refused)."""
    values: Dict[str, Any] = {}
    for name, value in fields.items():
        if name not in JOB_FIELDS:
            raise KeyError(f"unknown restore job field {name!r}")
        if name in JSON_FIELDS:
            value = dumps_json(value)
        elif name in MAX_LENGTHS and isinstance(value, str):
            value = value[: MAX_LENGTHS[name]]
        values[name] = value
    return values


def row_to_record(row: Any) -> JobRecord:
    """A RestoreJob row (or any object with the same attributes) -> JobRecord."""
    data: Dict[str, Any] = {}
    for name in JOB_FIELDS:
        value = getattr(row, name, None)
        if name == "diagnostics":
            value = loads_json(value, {})
        elif name == "precheck_result":
            value = loads_json(value, None)
        data[name] = value
    data["status"] = data["status"] or "created"
    return JobRecord(**data)


PROFILE_FIELDS = tuple(UserProfileRecord.__dataclass_fields__)
# record field -> column name (the model calls the YAML id `profile_key`)
PROFILE_COLUMN = {
    "key": "profile_key",
    "platforms": "platforms",
    "last_validation": "last_validation",
}
PROFILE_JSON = ("platforms", "last_validation")


def profile_fields_to_columns(fields: Dict[str, Any]) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for name, value in fields.items():
        if name not in PROFILE_FIELDS:
            raise KeyError(f"unknown restore profile field {name!r}")
        if name in PROFILE_JSON:
            value = dumps_json(value)
        values[PROFILE_COLUMN.get(name, name)] = value
    return values


def row_to_profile_record(row: Any) -> UserProfileRecord:
    data: Dict[str, Any] = {}
    for name in PROFILE_FIELDS:
        value = getattr(row, PROFILE_COLUMN.get(name, name), None)
        if name == "platforms":
            value = loads_json(value, [])
        elif name == "last_validation":
            value = loads_json(value, [])
        elif name in ("name", "description", "vendor"):
            value = value or ""
        data[name] = value
    return UserProfileRecord(**data)


def resolve_platform(connection_driver, custom_drivers_switch, custom_drivers_by_id):
    """
    The platform of a device, as the backupers see it.

    A device either uses a NAPALM driver (`connection_driver` is its name, e.g. "ios") or,
    when `custom_drivers_switch` is on, a NABS custom driver: then `connection_driver`
    holds the id of a Custom_Drivers row and the platform is that row's `drivers_platform`
    (a Netmiko device type such as "cisco_ios").

    Returns (platform, netmiko_device_type); (None, None) when it cannot be determined.
    """
    if custom_drivers_switch:
        try:
            custom_id = int(str(connection_driver).strip())
        except (TypeError, ValueError):
            return None, None
        row = custom_drivers_by_id.get(custom_id)
        platform = (row or {}).get("drivers_platform") or None
        return platform, platform
    return (connection_driver or None), None
