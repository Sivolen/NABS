"""
Restore Service: the single entry point for starting and managing restore jobs.

Every public method re-checks, on the server and on every call, that the current user
may restore AND may work with the job's device. It is the same whether the caller is a
web view, a background job or (later) a bulk operation. Nothing here talks to a device:
long operations are only requested (`requested_action`) and carried out by the worker.
"""

import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Tuple

from app.modules.access import can_access_device, parse_id, role_of
from app.modules.restore import states as st
from app.modules.restore.engine import RestoreEngine
from app.modules.restore.profiles import SOURCES, ProfileProvider
from app.modules.restore.schema import parse_profile_yaml
from app.modules.restore.storage import ConfigStore, DeviceProvider, JobRecord, JobStore

# Restoring is high risk: a plain `user` role may never do it, whatever its groups.
RESTORE_ROLES = ("sadmin", "admin")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

FORBIDDEN = "forbidden"
NOT_FOUND = "not_found"
INVALID = "invalid"
CONFLICT = "conflict"


class ServiceError(Exception):
    def __init__(
        self, code: str, message: str, details: Optional[List[Dict[str, str]]] = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        # e.g. validation issues: [{"level", "path", "message"}], safe to show
        self.details = details or []


class AssignmentProvider(Protocol):
    def get_assigned(self, device_id: int) -> Optional[Tuple[str, str]]:
        """(profile source, profile key) assigned to the device, if any."""


def can_resolve_manually(job: JobRecord) -> bool:
    return job.status in (st.UNKNOWN, st.ROLLBACK_FAILED) or (
        job.status == st.FAILED
        and (job.diagnostics or {}).get("device_touched") is True
    )


def job_to_view(job: JobRecord) -> Dict[str, Any]:
    """What may be sent to the browser: never the profile text, secrets or worker ids."""
    return {
        "id": job.id,
        "device_id": job.device_id,
        "target_config_id": job.target_config_id,
        "profile": {
            "source": job.profile_source,
            "key": job.profile_key,
            "version": job.profile_version,
        },
        "initiator": job.initiator,
        "status": job.status,
        "status_label": st.LABELS.get(job.status, job.status),
        "terminal": st.is_terminal(job.status),
        "can_resolve_manually": can_resolve_manually(job),
        "stage": job.stage,
        "requested_action": job.requested_action,
        "summary": job.summary,
        "disruptive": bool((job.precheck_result or {}).get("disruptive")),
        "precheck_status": job.precheck_status,
        "precheck": job.precheck_result,
        "fingerprint": (job.precheck_result or {}).get("fingerprint"),
        "pre_restore_config_id": job.pre_restore_config_id,
        "rollback_status": job.rollback_status,
        "rollback_details": job.rollback_details,
        "confirmed_by": job.confirmed_by,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "diagnostics": job.diagnostics,
    }


class RestoreService:
    def __init__(
        self,
        store: JobStore,
        configs: ConfigStore,
        devices: DeviceProvider,
        profiles: ProfileProvider,
        assignments: AssignmentProvider,
        engine: RestoreEngine,
        access: Callable[[Mapping, Any], bool] = can_access_device,
    ) -> None:
        self.store = store
        self.configs = configs
        self.devices = devices
        self.profiles = profiles
        self.assignments = assignments
        self.engine = engine
        self._access = access

    # ------------------------------------------------------------ authorization
    @staticmethod
    def _user(session_obj: Mapping) -> str:
        return str(session_obj.get("user") or "")

    def _require_role(self, session_obj: Mapping) -> str:
        user = self._user(session_obj)
        if not user or role_of(session_obj) not in RESTORE_ROLES:
            raise ServiceError(
                FORBIDDEN, "You are not allowed to restore configurations"
            )
        return user

    def _require_device(self, session_obj: Mapping, device_id: int) -> None:
        if not self._access(session_obj, device_id):
            raise ServiceError(FORBIDDEN, "You have no access to this device")

    def _load_authorized_job(self, session_obj: Mapping, job_id) -> JobRecord:
        """Role + device access are checked on EVERY call, not only at creation."""
        self._require_role(session_obj)
        parsed = parse_id(job_id)
        job = self.store.get_job(parsed) if parsed else None
        if job is None:
            raise ServiceError(NOT_FOUND, "Restore job not found")
        self._require_device(session_obj, job.device_id)
        return job

    # ------------------------------------------------------------------- create
    def create_job(
        self,
        session_obj: Mapping,
        device_id,
        config_id,
        client_token: str,
        profile_ref: Optional[Mapping[str, str]] = None,
    ) -> Tuple[JobRecord, bool]:
        """
        Creates a job in state `created`. Returns (job, created). A repeated request
        with the same client_token returns the existing job (created=False): a double
        click or a page refresh can never create a second job.
        """
        user = self._require_role(session_obj)
        device_id_int = parse_id(device_id)
        config_id_int = parse_id(config_id)
        if device_id_int is None or config_id_int is None:
            raise ServiceError(INVALID, "Invalid device or configuration id")
        if not isinstance(client_token, str) or not TOKEN_RE.match(client_token):
            raise ServiceError(INVALID, "Invalid request token")
        self._require_device(session_obj, device_id_int)
        if self.devices.get_device(device_id_int) is None:
            raise ServiceError(NOT_FOUND, "Device not found")

        # the configuration must exist AND belong to this very device
        config = self.configs.get_config(config_id_int)
        if config is None or config.device_id != device_id_int:
            raise ServiceError(
                INVALID, "The configuration does not belong to this device"
            )

        source, key = self._resolve_profile_ref(device_id_int, profile_ref)
        profile_text = self.profiles.get(source, key)
        if profile_text is None:
            raise ServiceError(NOT_FOUND, "Restore profile not found")
        parsed = parse_profile_yaml(
            profile_text.content, allow_builtin=source == "builtin"
        )
        if not parsed.ok:
            raise ServiceError(INVALID, f"The profile is invalid: {parsed.errors[0]}")

        job, created = self.store.create_job(
            {
                "client_token": client_token,
                "device_id": device_id_int,
                "target_config_id": config_id_int,
                "profile_source": source,
                "profile_key": key,
                "profile_version": parsed.profile.profile_version,
                "profile_sha256": profile_text.sha256,
                "profile_content": profile_text.content,
                "initiator": user,
                "status": st.CREATED,
            }
        )
        if not created and (
            job.initiator != user
            or job.device_id != device_id_int
            or job.target_config_id != config_id_int
        ):
            # somebody reused another request's token
            raise ServiceError(CONFLICT, "This request token is already in use")
        return job, created

    def _resolve_profile_ref(
        self, device_id: int, profile_ref: Optional[Mapping[str, str]]
    ) -> Tuple[str, str]:
        if profile_ref is None:
            assigned = self.assignments.get_assigned(device_id)
            if assigned is None:
                raise ServiceError(
                    INVALID, "No restore profile is assigned to this device"
                )
            return assigned
        source = profile_ref.get("source")
        key = profile_ref.get("key")
        if source not in SOURCES or not isinstance(key, str) or not key:
            raise ServiceError(INVALID, "Invalid profile reference")
        return source, key

    def prepare_new(self, session_obj: Mapping, device_id, config_id) -> Dict[str, Any]:
        """
        What the "restore" page shows BEFORE anything is created: the device, the chosen
        configuration and the assigned profile. Same checks as create_job; changes nothing.
        """
        self._require_role(session_obj)
        device_id_int = parse_id(device_id)
        config_id_int = parse_id(config_id)
        if device_id_int is None or config_id_int is None:
            raise ServiceError(INVALID, "Invalid device or configuration id")
        self._require_device(session_obj, device_id_int)
        device = self.devices.get_device(device_id_int)
        if device is None:
            raise ServiceError(NOT_FOUND, "Device not found")
        config = self.configs.get_config(config_id_int)
        if config is None or config.device_id != device_id_int:
            raise ServiceError(
                INVALID, "The configuration does not belong to this device"
            )
        return {
            "device": {
                "id": device.device_id,
                "hostname": device.hostname,
                "ip": device.ip,
                "driver": device.driver,
                "model": device.model,
            },
            "config": {
                "id": config.id,
                "timestamp": config.timestamp,
                "lines": len((config.text or "").splitlines()),
            },
            "assigned": self.assignments.get_assigned(device_id_int),
        }

    # ------------------------------------------------------------ job lifecycle
    def request_precheck(self, session_obj: Mapping, job_id) -> JobRecord:
        """Asks the worker to run the precheck (no device access in the web request)."""
        job = self._load_authorized_job(session_obj, job_id)
        if job.status not in (st.CREATED, st.AWAITING_CONFIRMATION):
            raise ServiceError(CONFLICT, "A precheck cannot be started in this state")
        self.store.update(job.id, requested_action="precheck")
        self.store.add_event(
            job.id,
            "precheck",
            "precheck_requested",
            "info",
            f"Precheck requested by {self._user(session_obj)}",
        )
        return self.store.get_job(job.id)

    def confirm(
        self,
        session_obj: Mapping,
        job_id,
        fingerprint,
        typed_name: Optional[str] = None,
    ) -> JobRecord:
        job = self._load_authorized_job(session_obj, job_id)
        if (job.precheck_result or {}).get("disruptive"):
            # a restore that reboots the device needs more than a tick: the name of the device
            device = self.devices.get_device(job.device_id)
            expected = (
                ((device.hostname or device.ip) if device else "").strip().lower()
            )
            if not expected or (typed_name or "").strip().lower() != expected:
                raise ServiceError(
                    INVALID,
                    "This restore reboots the device: type the device name exactly to confirm",
                )
        ok, reason = self.engine.confirm(
            job.id, self._user(session_obj), str(fingerprint or "")
        )
        if not ok:
            raise ServiceError(CONFLICT, reason)
        return self.store.get_job(job.id)

    def cancel(self, session_obj: Mapping, job_id) -> JobRecord:
        job = self._load_authorized_job(session_obj, job_id)
        if not self.engine.cancel(job.id, self._user(session_obj)):
            raise ServiceError(CONFLICT, "The job can no longer be cancelled")
        return self.store.get_job(job.id)

    def resolve_unknown(
        self, session_obj: Mapping, job_id, resolution: str, note: str, typed_name: str
    ) -> JobRecord:
        """Record a human inspection; release protected configs only on explicit confirmation.

        `leave_open` adds an audit note but keeps the job unknown and its configurations
        protected. The two resolving choices require a meaningful note and typing the device
        hostname/IP to reduce the chance of resolving the wrong job.
        """
        job = self._load_authorized_job(session_obj, job_id)
        if not can_resolve_manually(job):
            raise ServiceError(CONFLICT, "This job cannot be resolved manually")
        choices = {"target_confirmed", "pre_restore_confirmed", "leave_open"}
        if resolution not in choices:
            raise ServiceError(INVALID, "Choose a valid manual resolution")
        note = note.strip() if isinstance(note, str) else ""
        typed_name = typed_name.strip() if isinstance(typed_name, str) else ""
        if len(note) < 20 or len(note) > 1000:
            raise ServiceError(
                INVALID, "Enter an inspection note of 20 to 1000 characters"
            )
        device = self.devices.get_device(job.device_id)
        expected_name = (
            ((device.hostname or device.ip) if device else "").strip().lower()
        )
        if not expected_name or typed_name.lower() != expected_name:
            raise ServiceError(
                INVALID,
                "Type the device hostname or IP exactly to confirm the manual inspection",
            )

        user = self._user(session_obj)
        diagnostics = dict(job.diagnostics or {})
        record = {
            "resolution": resolution,
            "note": note,
            "operator": user,
            "at": datetime.now(timezone.utc).isoformat(),
            "device_identity_confirmed": True,
        }
        if resolution == "leave_open":
            raw_checks = diagnostics.get("manual_checks")
            checks = list(raw_checks) if isinstance(raw_checks, list) else []
            checks.append(record)
            diagnostics["manual_checks"] = checks[-20:]
            summary = "Manual inspection recorded; the result remains unknown and configurations stay protected."
            if not self.store.transition(
                job.id,
                job.status,
                {job.status},
                diagnostics=diagnostics,
                summary=summary,
            ):
                raise ServiceError(
                    CONFLICT, "The job was already resolved; reload the page"
                )
            self.store.add_event(
                job.id,
                "manual_resolution",
                "manual_inspection_recorded",
                "warning",
                f"Manual inspection recorded by {user}; job remains unresolved",
                {"resolution": resolution, "note": note, "operator": user},
            )
            return self.store.get_job(job.id)

        diagnostics["manual_resolution"] = record
        if resolution == "target_confirmed":
            summary = "An operator manually confirmed that the device is running the target configuration."
        else:
            summary = "An operator manually confirmed that the pre-restore configuration is running."
        transitioned = self.store.transition(
            job.id,
            st.RESOLVED_MANUAL,
            {job.status},
            finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
            stage="manual_resolution",
            summary=summary,
            diagnostics=diagnostics,
        )
        if not transitioned:
            raise ServiceError(
                CONFLICT,
                "The job changed while it was being resolved; reload and try again",
            )
        self.store.add_event(
            job.id,
            "manual_resolution",
            "manually_resolved",
            "warning",
            f"Operator {user} manually resolved the job: {resolution}",
            {"resolution": resolution, "note": note, "operator": user},
        )
        return self.store.get_job(job.id)

    # -------------------------------------------------------------------- reads
    def get_job_view(self, session_obj: Mapping, job_id) -> Dict[str, Any]:
        job = self._load_authorized_job(session_obj, job_id)
        view = job_to_view(job)
        view["events"] = self.store.list_events(job.id)
        return view

    def list_jobs_for_device(
        self, session_obj: Mapping, device_id
    ) -> List[Dict[str, Any]]:
        self._require_role(session_obj)
        parsed = parse_id(device_id)
        if parsed is None:
            raise ServiceError(INVALID, "Invalid device id")
        self._require_device(session_obj, parsed)
        return [job_to_view(j) for j in self.store.list_jobs_for_device(parsed)]
