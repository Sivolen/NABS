"""Read-only, queued platform inspection. Never uploads or applies configuration."""

import json
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert

from app import db
from app.models import RestoreInspection
from app.modules.backup_lock import device_backup_lock
from app.modules.restore.adapters.base import device_identity
from app.modules.restore.compat import normalize_platform

FACTS_TTL = timedelta(hours=24)
# Fixed commands only. Recognizing an inventory family does not register a probe.
PROBES = {
    "ios": ("cisco_ios", "show version", "cisco"),
    "cisco_ios": ("cisco_ios", "show version", "cisco"),
    "cisco_xe": ("cisco_xe", "show version", "cisco"),
    "nxos": ("cisco_nxos", "show version", "cisco"),
    "cisco_nxos": ("cisco_nxos", "show version", "cisco"),
    "huawei": ("huawei", "display version", "huawei"),
    "huawei_vrp": ("huawei", "display version", "huawei"),
}


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def probe_for(device):
    return PROBES.get(normalize_platform(device.driver))


def _specific_model(saved, detected):
    # Version banners may contain only the series while inventory has a full SKU.
    if saved and detected and saved.lower().startswith(detected.lower()):
        return saved
    return detected or saved


def specific_model(stored, observed):
    """Do not replace a full inventory SKU with a shorter CLI family name."""
    current = (stored or "").strip().lower()
    for prefix in ("huawei ", "cisco ", "cloudengine "):
        if current.startswith(prefix):
            current = current[len(prefix) :]
    if current and observed and current.startswith(observed.lower()):
        return stored
    return observed or stored


def inspect_platform(device, credentials, connection_factory=None):
    probe = probe_for(device)
    if probe is None:
        raise ValueError("No read-only software probe is implemented for this platform")
    if not credentials or not credentials.username or not credentials.password:
        raise ValueError("No usable device credentials are assigned")
    if connection_factory is None:
        from netmiko import ConnectHandler

        connection_factory = ConnectHandler
    device_type, command, parser = probe
    conn = connection_factory(
        device_type=device_type,
        host=device.ip,
        port=device.port or 22,
        username=credentials.username,
        password=credentials.password,
        conn_timeout=15,
        auth_timeout=15,
        banner_timeout=15,
        timeout=15,
    )
    try:
        output = conn.send_command(command, read_timeout=30)
        if parser == "huawei":
            from app.modules.restore.adapters.huawei_common import parse_display_version

            info = parse_display_version(output)
            if info is None or not (info.software or info.vrp_version):
                raise ValueError("The device software could not be recognized")
            return {
                "model": _specific_model(device.model, info.model),
                "os_version": info.software or info.vrp_version,
                "os_generation": info.vrp_version,
                "family": info.family,
            }
        from app.modules.restore.adapters.cisco_ios import parse_show_version

        info = parse_show_version(output)
        version = info.version if info else None
        if info and info.family == "nxos" and not version:
            match = re.search(r"(?:NXOS:|system:)\s*version\s+(\S+)", output, re.I)
            version = match.group(1) if match else None
        if info is None or not version:
            raise ValueError("The device software could not be recognized")
        return {
            "model": _specific_model(device.model, info.model),
            "os_version": version,
            "family": info.family,
        }
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


class DbInspectionStore:
    def request(self, device, user):
        values = dict(
            device_id=device.device_id,
            status="queued",
            identity=device_identity(device),
            requested_by=user,
            requested_at=now_utc(),
            completed_at=None,
            model=None,
            os_version=None,
            facts=None,
            message="Waiting for the restore worker",
        )
        statement = insert(RestoreInspection).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[RestoreInspection.device_id],
            set_={k: v for k, v in values.items() if k != "device_id"},
            where=~RestoreInspection.status.in_(["queued", "running"]),
        )
        try:
            db.session.execute(statement)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return self.get(device.device_id)

    def get(self, device_id):
        row = (
            RestoreInspection.query.populate_existing()
            .filter_by(device_id=device_id)
            .first()
        )
        result = (
            None
            if row is None
            else {
                key: getattr(row, key)
                for key in (
                    "device_id",
                    "status",
                    "identity",
                    "requested_at",
                    "completed_at",
                    "model",
                    "os_version",
                    "message",
                )
            }
        )
        if result is not None:
            try:
                facts = json.loads(row.facts or "{}")
            except (TypeError, ValueError):
                facts = {}
            result["os_generation"] = (
                facts.get("os_generation") if isinstance(facts, dict) else None
            )
        db.session.commit()
        return result

    def pending(self):
        rows = (
            RestoreInspection.query.filter_by(status="queued")
            .order_by(RestoreInspection.requested_at)
            .all()
        )
        result = [
            {"device_id": row.device_id, "identity": row.identity} for row in rows
        ]
        db.session.commit()
        return result

    def claim(self, task):
        changed = RestoreInspection.query.filter_by(**task, status="queued").update(
            {"status": "running", "message": "Reading device software"},
            synchronize_session=False,
        )
        db.session.commit()
        return changed == 1

    def finish(self, task, facts=None, message=None):
        values = dict(
            status="ready" if facts else "failed",
            completed_at=now_utc(),
            message=message or "Device software detected",
            facts=json.dumps(facts) if facts else None,
            model=(facts or {}).get("model"),
            os_version=(facts or {}).get("os_version"),
        )
        RestoreInspection.query.filter_by(**task, status="running").update(
            values, synchronize_session=False
        )
        db.session.commit()

    def recover(self):
        RestoreInspection.query.filter_by(status="running").update(
            {
                "status": "failed",
                "completed_at": now_utc(),
                "message": "The worker restarted during inspection; request a new check",
            },
            synchronize_session=False,
        )
        db.session.commit()

    def enrich(self, device):
        row = self.get(device.device_id)
        if (
            row
            and row["status"] == "ready"
            and row["identity"] == device_identity(device)
            and row["completed_at"]
            and timedelta(0) <= now_utc() - row["completed_at"] <= FACTS_TTL
        ):
            return replace(
                device,
                model=row["model"] or device.model,
                os_version=row["os_version"],
                os_generation=row.get("os_generation"),
            )
        return device


class InspectionWorker:
    def __init__(self, store, devices, probe=inspect_platform):
        self.store, self.devices, self.probe = store, devices, probe

    def start(self):
        self.store.recover()

    def run_once(self):
        # One inspection per tick leaves confirmed restore work priority.
        for task in self.store.pending():
            with device_backup_lock(task["device_id"]) as acquired:
                if not acquired or not self.store.claim(task):
                    continue
                try:
                    device = self.devices.get_device(task["device_id"])
                    if device is None or device_identity(device) != task["identity"]:
                        self.store.finish(
                            task,
                            message="The device connection settings changed; request a new check",
                        )
                        return 1
                    credentials = self.devices.get_credentials(device.device_id)
                    facts = self.probe(device, credentials)
                    platform = normalize_platform(device.driver)
                    expected = {
                        "ios": {"ios", "iosxe"},
                        "cisco_ios": {"ios", "iosxe"},
                        "cisco_xe": {"ios", "iosxe"},
                        "nxos": {"nxos"},
                        "cisco_nxos": {"nxos"},
                    }.get(platform)
                    if expected and facts.get("family") not in expected:
                        self.store.finish(
                            task,
                            message="The detected operating system does not match the configured driver; review device settings",
                        )
                        return 1
                    self.store.finish(task, facts=facts)
                except Exception as error:
                    # Exception text and command output can contain credentials.
                    self.store.finish(
                        task,
                        message=f"Software inspection failed ({type(error).__name__}); check device access and platform settings",
                    )
                return 1
        return 0
