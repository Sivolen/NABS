"""
Server-side authorization helpers.

Why this module exists: ids that come from the client (device_id in a URL or JSON
body, config_id in a form) must never be trusted on their own. Every handler has to
check that the *current user* may touch the *target device*, and that the object it
is about to change really belongs to that device.

The decision logic is pure (it only needs a session-like mapping), so it can be
tested without Flask, a database or a browser. The database lookup of "which user
groups own this device" is injected and defaults to check_allowed_device().
"""

from typing import Callable, Mapping, Optional

ADMIN_ROLES = ("sadmin", "admin")

# ids are PostgreSQL integers; anything bigger cannot be a real row id
MAX_ID = 2**31 - 1


def parse_id(value) -> Optional[int]:
    """
    Strict positive integer id: 5, "5", " 5 " -> 5.
    None for everything else: None, "", "abc", "5; DROP", "1.5", "-3", "0", True, 2**40.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        if not text.isascii() or not text.isdigit():
            return None
        number = int(text)
    else:
        return None
    return number if 0 < number <= MAX_ID else None


def role_of(session_obj: Mapping) -> str:
    return str(session_obj.get("rights") or "")


def has_admin_role(session_obj: Mapping) -> bool:
    """sadmin or admin (the same rule the UI uses to show the management buttons)."""
    return role_of(session_obj) in ADMIN_ROLES


def _default_group_lookup(groups: list, device_id: int) -> bool:
    # imported lazily: pulls in the models / the database
    from app.modules.dbutils.db_users_permission import check_allowed_device

    return check_allowed_device(groups_id=groups, device_id=device_id)


def can_access_device(
    session_obj: Mapping,
    device_id,
    group_lookup: Optional[Callable[[list, int], bool]] = None,
) -> bool:
    """
    True if the user may work with this device:
      - the id must be a valid positive integer;
      - the user must be logged in (a session without a user is never allowed);
      - sadmin may use every device;
      - everybody else only the devices of the user groups from the session.
    Any error while checking is treated as "denied".
    """
    parsed = parse_id(device_id)
    if parsed is None:
        return False
    if not session_obj.get("user"):
        return False
    if role_of(session_obj) == "sadmin":
        return True
    groups = session_obj.get("allowed_devices")
    if not groups or not isinstance(groups, (list, tuple)):
        return False
    lookup = group_lookup or _default_group_lookup
    try:
        return bool(lookup(list(groups), parsed))
    except Exception:
        return False
