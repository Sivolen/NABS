"""
Restore Engine: the lifecycle of one restore job, identical for every platform.

    run_precheck() -> awaiting_confirmation | failed(blocked)
    confirm()      -> queued          (bound to a fingerprint of what the user saw)
    execute()      -> success | failed | failed_rollback_confirmed | rollback_failed
                      | unknown | cancelled
    recover_interrupted() after a restart: claimed jobs become `unknown`, never resumed

The engine contains NO vendor commands: everything that talks to equipment is an
adapter method (adapters/base.py). It never retries an apply, never reports success
without a positive read-back from the adapter, and answers "unknown" whenever the
outcome cannot be established (lost session, unverifiable state).

Known limit: a blocking adapter call cannot be interrupted by the engine; adapters
must honour profile.limits themselves. The engine records how long each step took.
"""

import difflib
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.modules.restore import states as st
from app.modules.restore.actions import ACTIONS, ENGINE_ACTIONS, PHASES
from app.modules.restore.adapters.base import (
    ACTION_HANDLERS,
    ActionResult,
    AdapterError,
    AdapterTimeout,
    ConnectionLost,
    RestoreAdapter,
    RestoreContext,
    UnsupportedOperation,
    Verdict,
)
from app.modules.restore.compat import check_compatibility
from app.modules.restore.schema import (
    RestoreProfile,
    check_adapter_capabilities,
    parse_profile_yaml,
)
from app.modules.restore.storage import (
    ConfigStore,
    DeviceProvider,
    JobRecord,
    JobStore,
)

log = logging.getLogger("nabs.restore")

# actions the engine itself implements (the rest are adapter methods)
ENGINE_IMPLEMENTED_ACTIONS = frozenset(ENGINE_ACTIONS)

CONFIRMATION_TTL_SECONDS = 15 * 60
RECONNECT_INTERVAL_SECONDS = 5
MAX_DIFF_LINES = 3000
MAX_TEXT = 500

_APPLY_PHASE = PHASES.index("apply")
_DEVICE_TOUCHED = set(st.DEVICE_TOUCHED_STATES)


def _naive_utc(moment: datetime) -> datetime:
    """Naive UTC, whatever the input: databases return naive values, tests aware ones."""
    if moment.tzinfo is not None:
        return moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def normalize_config(text: str) -> str:
    """Ignore trailing whitespace and blank lines when comparing configurations."""
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip())


def config_sha256(text: str) -> str:
    return hashlib.sha256(normalize_config(text).encode("utf-8")).hexdigest()


def compute_fingerprint(
    device_id: int,
    target_config_id: int,
    target_sha256: str,
    profile_sha256: str,
    current_sha256: Optional[str],
    precheck_status: str,
) -> str:
    payload = json.dumps(
        [
            device_id,
            target_config_id,
            target_sha256,
            profile_sha256,
            current_sha256,
            precheck_status,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_diff(current: str, target: str) -> Dict[str, Any]:
    """Informational text diff (NOT a plan of commands, never turned into `no ...`)."""
    lines = list(
        difflib.unified_diff(
            normalize_config(current).splitlines(),
            normalize_config(target).splitlines(),
            "current",
            "target",
            lineterm="",
            n=3,
        )
    )
    added = sum(1 for x in lines if x.startswith("+") and not x.startswith("+++"))
    removed = sum(1 for x in lines if x.startswith("-") and not x.startswith("---"))
    truncated = len(lines) > MAX_DIFF_LINES
    return {
        "lines": lines[:MAX_DIFF_LINES],
        "added": added,
        "removed": removed,
        "truncated": truncated,
        "identical": not lines,
    }


class _Run:
    """Per-operation helper: journal writes with secrets scrubbed out."""

    def __init__(self, engine: "RestoreEngine", job_id: int) -> None:
        self.engine = engine
        self.job_id = job_id
        self.secrets: List[str] = []

    def scrub(self, value: Any) -> Any:
        if isinstance(value, str):
            text = value[:MAX_TEXT]
            for secret in self.secrets:
                if secret:
                    text = text.replace(secret, "***")
            return text
        if isinstance(value, dict):
            return {str(k): self.scrub(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.scrub(v) for v in value]
        return value

    def event(
        self,
        stage: Optional[str],
        event_type: str,
        message: str,
        level: str = "info",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        store = self.engine.store
        store.add_event(
            self.job_id,
            stage,
            event_type,
            level,
            self.scrub(message),
            self.scrub(details) if details else None,
        )
        fields: Dict[str, Any] = {"heartbeat_at": self.engine._now()}
        if stage:
            fields["stage"] = stage
        store.update(self.job_id, **fields)


class RestoreEngine:
    def __init__(
        self,
        store: JobStore,
        configs: ConfigStore,
        devices: DeviceProvider,
        adapter_factory: Callable[[str], Optional[RestoreAdapter]],
        *,
        now: Optional[Callable[[], datetime]] = None,
        timestamp: Optional[Callable[[], str]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        monotonic: Optional[Callable[[], float]] = None,
        confirmation_ttl: int = CONFIRMATION_TTL_SECONDS,
    ) -> None:
        import time

        self.store = store
        self.configs = configs
        self.devices = devices
        self.adapter_factory = adapter_factory
        # NAIVE UTC: the restore tables hold naive UTC (see models._restore_now)
        self._now = now or (lambda: datetime.now(timezone.utc).replace(tzinfo=None))
        # same format as the rest of NABS writes into Configs.timestamp
        self._timestamp = timestamp or (
            lambda: datetime.now().strftime("%Y-%m-%d %H:%M")
        )
        self._sleep = sleep or time.sleep
        self._monotonic = monotonic or time.monotonic
        self.confirmation_ttl = confirmation_ttl

    # ------------------------------------------------------------------ helpers
    def _move(self, job_id: int, new: str, expected, **fields: Any) -> bool:
        allowed = {e for e in expected if st.can_transition(e, new)}
        if not allowed:
            raise st.InvalidTransition(f"no state in {set(expected)} leads to {new}")
        return self.store.transition(job_id, new, allowed, **fields)

    def _finish(
        self,
        run: _Run,
        new: str,
        expected,
        summary: str,
        level: str = "info",
        diagnostics: Optional[Dict[str, Any]] = None,
        **fields: Any,
    ) -> bool:
        summary = run.scrub(summary)
        moved = self._move(
            run.job_id,
            new,
            expected,
            finished_at=self._now(),
            summary=summary,
            **fields,
        )
        if moved:
            if diagnostics:
                job = self.store.get_job(run.job_id)
                merged = dict(job.diagnostics if job else {})
                merged.update(run.scrub(diagnostics))
                self.store.update(run.job_id, diagnostics=merged)
            run.event(
                None, "finished", f"{st.LABELS[new]}: {summary}", level, {"status": new}
            )
        return moved

    @staticmethod
    def _params_for(
        action: str, step_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Defaults declared for the action, overridden by the profile's values."""
        spec = ACTIONS.get(action)
        values = {n: p.default for n, p in (spec.params if spec else {}).items()}
        values.update(step_params or {})
        return values

    def _call(
        self,
        run: _Run,
        adapter: RestoreAdapter,
        method: str,
        ctx: RestoreContext,
        params: Optional[Dict[str, Any]] = None,
    ) -> ActionResult:
        """Run one adapter method; every failure mode becomes an ActionResult."""
        ctx.params = dict(params) if params is not None else self._params_for(method)
        started = self._monotonic()
        try:
            result = getattr(adapter, method)(ctx)
            if not isinstance(result, ActionResult):
                result = ActionResult.failure("adapter returned an invalid result")
        except UnsupportedOperation:
            result = ActionResult.failure(
                f"{method} is not supported by this adapter",
                details={"unsupported": True},
            )
        except (ConnectionLost, AdapterTimeout) as error:
            result = ActionResult.unknown(
                f"connection lost or timed out during {method}: {run.scrub(str(error))}",
                details={"connection_lost": True},
            )
        except AdapterError as error:
            result = ActionResult.failure(f"{method}: {run.scrub(str(error))}")
        except Exception as error:  # an adapter bug must not kill the engine
            log.exception("adapter %s crashed in %s", type(adapter).__name__, method)
            result = ActionResult.failure(
                f"unexpected adapter error in {method}: {type(error).__name__}"
            )
        run.event(
            None,
            "adapter_call",
            f"{method}: {result.verdict.value} {result.message}".strip(),
            "info" if result.ok else "warning",
            {"seconds": round(self._monotonic() - started, 2), **result.details},
        )
        return result

    @staticmethod
    def _load_profile(job: JobRecord) -> Tuple[Optional[RestoreProfile], List[str]]:
        if (
            hashlib.sha256(job.profile_content.encode("utf-8")).hexdigest()
            != job.profile_sha256
        ):
            return None, ["profile snapshot does not match its checksum"]
        result = parse_profile_yaml(
            job.profile_content, allow_builtin=job.profile_source == "builtin"
        )
        if not result.ok:
            return None, [str(i) for i in result.errors[:5]]
        return result.profile, [i.message for i in result.warnings]

    # ----------------------------------------------------------------- precheck
    def run_precheck(self, job_id: int) -> Optional[Dict[str, Any]]:
        """
        Returns the precheck result, or None if the job was not in a state that
        allows a precheck (e.g. a repeated request). Re-running it invalidates an
        earlier confirmation.
        """
        moved = self._move(
            job_id,
            st.PRECHECK_RUNNING,
            {st.CREATED, st.AWAITING_CONFIRMATION},
            stage="precheck",
            precheck_status=None,
            confirmed_fingerprint=None,
            confirmed_by=None,
            confirmed_at=None,
        )
        if not moved:
            return None
        run = _Run(self, job_id)
        run.event("precheck", "precheck_started", "Precheck started")
        holder: List[Optional[RestoreAdapter]] = [None]
        try:
            job = self.store.get_job(job_id)
            result = self._precheck(run, job, holder)
        except Exception as error:
            log.exception("precheck of job %s crashed", job_id)
            result = {
                "status": "blocked",
                "checks": [
                    {
                        "name": "internal",
                        "status": "failed",
                        "message": f"internal error: {type(error).__name__}",
                    }
                ],
                "warnings": [],
                "diff": None,
                "fingerprint": None,
            }
        finally:
            close_errors = self._close(holder[0])
            if close_errors:
                message = (
                    "Temporary device files could not be cleaned up after precheck: "
                    + ", ".join(close_errors)
                )
                result.setdefault("warnings", []).append(message)
                result.setdefault("checks", []).append(
                    {
                        "name": "cleanup",
                        "status": "warning",
                        "message": message,
                    }
                )
                if result.get("status") != "blocked":
                    result["status"] = "warning"
                    if result.get("target_sha256"):
                        job_for_fingerprint = self.store.get_job(job_id)
                        result["fingerprint"] = compute_fingerprint(
                            job_for_fingerprint.device_id,
                            job_for_fingerprint.target_config_id,
                            result["target_sha256"],
                            job_for_fingerprint.profile_sha256,
                            result.get("current_sha256"),
                            result["status"],
                        )

        status = result["status"]
        if status == "blocked":
            first = next((c for c in result["checks"] if c["status"] == "failed"), None)
            reason = first["message"] if first else "blocked"
            self._finish(
                run,
                st.FAILED,
                {st.PRECHECK_RUNNING},
                f"Blocked by the precheck: {reason}. Nothing was changed.",
                "warning",
                precheck_status=status,
                precheck_result=result,
                diagnostics={"device_touched": False},
            )
        else:
            self._move(
                job_id,
                st.AWAITING_CONFIRMATION,
                {st.PRECHECK_RUNNING},
                stage="awaiting_confirmation",
                precheck_status=status,
                precheck_result=result,
                summary="Waiting for the user's confirmation",
            )
            run.event(
                "awaiting_confirmation",
                "precheck_done",
                f"Precheck finished: {status}",
                "info" if status == "ready" else "warning",
            )
        return result

    @staticmethod
    def _close(adapter: Optional[RestoreAdapter]) -> tuple[str, ...]:
        if adapter is not None:
            try:
                return tuple(adapter.close() or ())
            except Exception:  # closing must never mask the real result
                log.warning("adapter close failed", exc_info=True)
                return (
                    "adapter close raised an exception; cleanup could not be confirmed",
                )
        return ()

    def _record_cleanup_errors(self, run: _Run, job_id: int, errors) -> None:
        errors = tuple(str(item) for item in errors if item)
        if not errors:
            return
        message = "Temporary device files could not be cleaned up: " + ", ".join(errors)
        run.event("cleanup", "cleanup_incomplete", message, "warning")
        current = self.store.get_job(job_id)
        if current is not None:
            diagnostics = dict(current.diagnostics or {})
            previous = list(diagnostics.get("cleanup_errors") or [])
            diagnostics["cleanup_errors"] = list(dict.fromkeys(previous + list(errors)))
            summary = current.summary or ""
            if message not in summary:
                summary = (summary + " " + message).strip()
            self.store.update(job_id, diagnostics=diagnostics, summary=summary)

    def _precheck(
        self, run: _Run, job: JobRecord, holder: List[Optional[RestoreAdapter]]
    ) -> Dict[str, Any]:
        checks: List[Dict[str, str]] = []
        warnings: List[str] = []

        def ok(name: str, message: str = "") -> None:
            checks.append({"name": name, "status": "ok", "message": message})

        def warn(name: str, message: str) -> None:
            checks.append({"name": name, "status": "warning", "message": message})
            warnings.append(message)

        def fail(name: str, message: str) -> None:
            checks.append({"name": name, "status": "failed", "message": message})

        def failed() -> bool:
            return any(c["status"] == "failed" for c in checks)

        meta = {"disruptive": False}

        def outcome(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
            status = "blocked" if failed() else ("warning" if warnings else "ready")
            data: Dict[str, Any] = {
                "disruptive": meta["disruptive"],
                "status": status,
                "checks": checks,
                "warnings": warnings,
                "diff": None,
                "fingerprint": None,
            }
            data.update(extra or {})
            if status != "blocked" and data.get("target_sha256"):
                data["fingerprint"] = compute_fingerprint(
                    job.device_id,
                    job.target_config_id,
                    data["target_sha256"],
                    job.profile_sha256,
                    data.get("current_sha256"),
                    status,
                )
            return data

        # 1. device
        device = self.devices.get_device(job.device_id)
        if device is None:
            fail("device", "the device does not exist")
            return outcome()
        ok("device", device.ip)

        # 2. target configuration: must exist, be non-empty and belong to THIS device
        target = self.configs.get_config(job.target_config_id)
        if target is None:
            fail("target_config", "the selected configuration no longer exists")
        elif target.device_id != job.device_id:
            fail("target_config", "the configuration does not belong to this device")
        elif not target.text or not target.text.strip():
            fail("target_config", "the selected configuration is empty")
        else:
            ok("target_config", f"configuration #{target.id}")

        # 3. profile (checksum of the snapshot + full validation)
        profile, notes = self._load_profile(job)
        if profile is None:
            fail("profile", "; ".join(notes))
        else:
            ok("profile", f"{profile.id} v{profile.profile_version}")
            if profile.disruptive:
                meta["disruptive"] = True
                warn(
                    "disruptive",
                    "THIS RESTORE INTERRUPTS SERVICE: the device will be rebooted and"
                    " unreachable for several minutes. Do it in a maintenance window.",
                )
            for note in notes:
                warn("profile", note)
            for text in profile.warnings:
                warn("profile", text)

        # 4. compatibility with the device
        if profile is not None:
            compat = check_compatibility(
                profile,
                device.driver,
                device.model,
                device.os_version,
                device.os_generation,
            )
            if compat.allowed:
                ok("compatibility", compat.reason)
            else:
                fail("compatibility", f"{compat.status}: {compat.reason}")

        # 5. credentials
        credentials = self.devices.get_credentials(job.device_id)
        if credentials is None or not credentials.username or not credentials.password:
            fail("credentials", "no usable credentials are assigned to the device")
        else:
            run.secrets.append(credentials.password)
            ok("credentials")

        # 6. adapter and its capabilities
        adapter = None
        if profile is not None:
            adapter = self.adapter_factory(profile.adapter_type)
            if adapter is None:
                fail(
                    "adapter",
                    f"adapter {profile.adapter_type!r} is not available (not implemented,"
                    " or switched off because it is not verified on hardware)",
                )
            else:
                holder[0] = adapter
                issues = check_adapter_capabilities(
                    profile,
                    {
                        profile.adapter_type: set(adapter.supported_actions())
                        | set(ENGINE_IMPLEMENTED_ACTIONS)
                    },
                )
                for issue in issues:
                    fail("adapter", issue.message)
                if (
                    profile.rollback_strategy != "none"
                    and not adapter.supports_rollback()
                ):
                    fail(
                        "adapter",
                        "the profile declares a rollback but the adapter cannot do it",
                    )
                if not issues:
                    ok("adapter", profile.adapter_type)

        if failed() or profile is None or adapter is None or target is None:
            return outcome()

        # 7. connect
        try:
            adapter.connect(device, credentials, profile.limits["connect_timeout"])
            ok("connect")
        except Exception as error:  # any failure to connect blocks the restore
            fail("connect", f"cannot connect: {run.scrub(str(error))}")
            return outcome()

        # 8. the profile's check and preparation steps, in the profile's order
        ctx = RestoreContext(job.id, device, profile, target.text)
        rollback_ok: Optional[bool] = None
        for step in profile.steps:
            spec = ACTIONS[step.action]
            if PHASES.index(spec.phase) >= _APPLY_PHASE:
                continue
            if step.action == "save_pre_restore_backup":
                result = self._save_pre_restore_backup(run, job, device, ctx)
            else:
                result = self._call(
                    run,
                    adapter,
                    ACTION_HANDLERS[step.action],
                    ctx,
                    self._params_for(step.action, step.params),
                )
            if step.action == "fetch_current_config" and result.ok:
                if result.payload is None:
                    result = ActionResult.failure(
                        "the adapter returned no configuration"
                    )
                else:
                    ctx.scratch["current_config"] = result.payload
            if step.action == "check_rollback_available":
                rollback_ok = result.ok
            for text in result.warnings:
                warn(step.action, text)
            if result.ok:
                ok(step.action, result.message)
            elif step.required:
                reason = (
                    "could not be determined"
                    if result.verdict is Verdict.UNKNOWN
                    else "failed"
                )
                fail(step.action, f"{reason}: {result.message}")
                break
            else:
                warn(step.action, f"optional step did not pass: {result.message}")

        if failed():
            return outcome()

        # 9. informational diff
        current = ctx.scratch.get("current_config")
        extra: Dict[str, Any] = {
            "target_sha256": config_sha256(target.text),
            "current_sha256": config_sha256(current) if current is not None else None,
            "pre_restore_config_id": ctx.scratch.get("pre_restore_config_id"),
            "rollback_available": rollback_ok,
        }
        if current is None:
            warn(
                "diff", "the current configuration is unavailable: no diff can be shown"
            )
        else:
            diff = build_diff(
                adapter.normalize_for_diff(current),
                adapter.normalize_for_diff(target.text),
            )
            extra["diff"] = diff
            if diff["identical"]:
                warn("diff", "the device already has this configuration")
        if profile.rollback_strategy == "none":
            warn("rollback", "no rollback is available for this operation")
        return outcome(extra)

    def _save_pre_restore_backup(
        self, run: _Run, job: JobRecord, device, ctx: RestoreContext
    ) -> ActionResult:
        current = ctx.scratch.get("current_config")
        if current is None or not current.strip():
            return ActionResult.failure("there is no current configuration to back up")
        config_id = self.configs.save_pre_restore_config(
            device.device_id, device.ip, current, self._timestamp()
        )
        if not config_id:
            return ActionResult.failure("the pre-restore copy could not be saved")
        ctx.scratch["pre_restore_config_id"] = config_id
        ctx.scratch["pre_restore_config"] = current
        self.store.update(job.id, pre_restore_config_id=config_id)
        return ActionResult.success(f"saved as configuration #{config_id}")

    # ------------------------------------------------------ confirm / cancel
    def confirm(self, job_id: int, user: str, fingerprint: str) -> Tuple[bool, str]:
        """
        The user confirms exactly what the precheck showed: the fingerprint binds the
        device, the target configuration, the profile and the precheck outcome.
        """
        job = self.store.get_job(job_id)
        if job is None:
            return False, "job not found"
        if job.status != st.AWAITING_CONFIRMATION or job.precheck_status not in (
            "ready",
            "warning",
        ):
            return False, "the job is not waiting for confirmation"
        expected = (job.precheck_result or {}).get("fingerprint")
        if (
            not expected
            or not fingerprint
            or not hmac.compare_digest(str(expected), str(fingerprint))
        ):
            return False, "the confirmation does not match the precheck result"
        moved = self._move(
            job_id,
            st.QUEUED,
            {st.AWAITING_CONFIRMATION},
            stage="queued",
            confirmed_fingerprint=fingerprint,
            confirmed_by=user,
            confirmed_at=self._now(),
            summary="Confirmed, waiting to start",
        )
        if not moved:
            return False, "the job was already confirmed or changed"
        _Run(self, job_id).event(
            "queued",
            "confirmed",
            f"Confirmed by {user}",
            details={"fingerprint": fingerprint},
        )
        return True, "ok"

    def cancel(self, job_id: int, user: str) -> bool:
        """Only before any change: the CAS fails once a worker has claimed the job."""
        run = _Run(self, job_id)
        moved = self._move(
            job_id,
            st.CANCELLED,
            st.CANCELLABLE_STATES,
            finished_at=self._now(),
            summary=f"Cancelled by {user} before any change",
        )
        if moved:
            run.event(None, "cancelled", f"Cancelled by {user}")
        return moved

    # ------------------------------------------------------------------ execute
    def execute(self, job_id: int, worker_id: str = "worker") -> bool:
        """
        Run a confirmed job. Returns False if there was nothing to do: the job is not
        queued, was claimed by someone else, or its confirmation expired. The atomic
        queued -> running claim guarantees one execution per job.
        """
        job = self.store.get_job(job_id)
        if job is None or job.status != st.QUEUED:
            return False
        run = _Run(self, job_id)
        try:
            age = self._confirmation_age(job)
        except Exception as error:  # nothing has been touched yet: cancel, never loop
            log.exception("cannot judge the confirmation of job %s", job_id)
            self._finish(
                run,
                st.CANCELLED,
                {st.QUEUED},
                f"Internal error ({type(error).__name__}) before the start; nothing was"
                " changed. Run the precheck again.",
                "error",
            )
            return False
        # an age far below zero means the stored time cannot be trusted (clock or time
        # zone confusion): treated like an expired confirmation, never as a fresh one
        if age is None or age > self.confirmation_ttl or age < -300:
            self._finish(
                run,
                st.CANCELLED,
                {st.QUEUED},
                "The confirmation expired or its time is not valid. Nothing was changed;"
                " run the precheck again.",
                "warning",
            )
            return False
        if not self._move(
            job_id,
            st.RUNNING,
            {st.QUEUED},
            worker_id=worker_id,
            started_at=self._now(),
            stage="starting",
        ):
            return False
        run.event("starting", "claimed", f"Started by {worker_id}")
        holder: List[Optional[RestoreAdapter]] = [None]
        try:
            self._execute_claimed(run, job_id, holder)
        except Exception as error:
            log.exception("restore job %s crashed", job_id)
            self._finish(
                run,
                st.UNKNOWN,
                _DEVICE_TOUCHED,
                f"Internal error ({type(error).__name__}) during the restore; the"
                " result is unknown - check the device manually.",
                "error",
            )
        finally:
            adapter = holder[0]
            if adapter is not None:
                try:
                    final_job = self.store.get_job(job_id)
                    final_status = (
                        final_job.status if final_job is not None else st.UNKNOWN
                    )
                    cleanup_errors = adapter.finalize(final_status)
                    if cleanup_errors:
                        self._record_cleanup_errors(run, job_id, cleanup_errors)
                except Exception:
                    # Cleanup reporting must not mask the restore outcome. The files are
                    # deliberately retained by adapters when the outcome is not known safe.
                    log.exception(
                        "could not finalize temporary files for restore job %s", job_id
                    )
                close_errors = self._close(adapter)
                if close_errors:
                    try:
                        self._record_cleanup_errors(run, job_id, close_errors)
                    except Exception:
                        log.exception(
                            "could not record adapter close errors for restore job %s",
                            job_id,
                        )
        return True

    def _confirmation_age(self, job: JobRecord) -> Optional[float]:
        if job.confirmed_at is None:
            return None
        return (_naive_utc(self._now()) - _naive_utc(job.confirmed_at)).total_seconds()

    def _execute_claimed(
        self, run: _Run, job_id: int, holder: List[Optional[RestoreAdapter]]
    ) -> None:
        job = self.store.get_job(job_id)

        def stop_clean(message: str, **diag: Any) -> None:
            """Failure before the device was touched."""
            self._finish(
                run,
                st.FAILED,
                {st.RUNNING},
                f"{message} No changes were made to the device.",
                "error",
                diagnostics={"device_touched": False, **diag},
            )

        profile, _notes = self._load_profile(job)
        precheck = job.precheck_result or {}
        if profile is None:
            return stop_clean("The profile snapshot is invalid.")
        if not job.confirmed_fingerprint or job.confirmed_fingerprint != precheck.get(
            "fingerprint"
        ):
            return stop_clean("The confirmation does not match the precheck.")
        device = self.devices.get_device(job.device_id)
        credentials = self.devices.get_credentials(job.device_id)
        if device is None or credentials is None or not credentials.password:
            return stop_clean("The device or its credentials are no longer available.")
        run.secrets.append(credentials.password)
        target = self.configs.get_config(job.target_config_id)
        if (
            target is None
            or target.device_id != job.device_id
            or config_sha256(target.text) != precheck.get("target_sha256")
        ):
            return stop_clean("The target configuration was removed or changed.")

        pre_text: Optional[str] = None
        if job.pre_restore_config_id:
            pre = self.configs.get_config(job.pre_restore_config_id)
            if pre is not None and pre.device_id == job.device_id:
                pre_text = pre.text
        if profile.require_pre_restore_backup and not pre_text:
            return stop_clean("The pre-restore copy is missing.")

        adapter = self.adapter_factory(profile.adapter_type)
        holder[0] = adapter
        if adapter is None:
            return stop_clean("The platform adapter is not available.")
        try:
            adapter.connect(device, credentials, profile.limits["connect_timeout"])
        except Exception as error:
            return stop_clean(f"Cannot connect: {run.scrub(str(error))}.")

        ctx = RestoreContext(job.id, device, profile, target.text)
        if pre_text is not None:
            ctx.scratch["pre_restore_config"] = pre_text

        # the device must still look exactly like it did when the user confirmed
        expected_sha = precheck.get("current_sha256")
        if expected_sha:
            now = self._call(run, adapter, "fetch_current_config", ctx)
            if not now.ok or now.payload is None:
                return stop_clean("The current configuration could not be read.")
            if config_sha256(now.payload) != expected_sha:
                return stop_clean(
                    "The device configuration changed after the precheck; run the"
                    " precheck again."
                )

        steps = [
            s
            for s in profile.steps
            if PHASES.index(ACTIONS[s.action].phase) >= _APPLY_PHASE
        ]
        notes: List[str] = []
        verifying = False
        for step in steps:
            spec = ACTIONS[step.action]
            method = ACTION_HANDLERS[step.action]
            run.event(spec.phase, "step_started", step.action)

            if spec.phase == "apply":
                # from here the device may change: recorded BEFORE the call
                self.store.update(job_id, diagnostics={"device_touched": True})
                result = self._call(
                    run,
                    adapter,
                    method,
                    ctx,
                    self._params_for(step.action, step.params),
                )
                if result.details.get("connection_lost"):
                    outcome = self._recover_session(
                        run, adapter, device, credentials, profile, ctx, notes
                    )
                    if outcome == "unknown":
                        return self._unknown_after_loss(run, "the apply")
                    if outcome == "mismatch":
                        return self._rollback(
                            run,
                            ctx,
                            adapter,
                            profile,
                            "The configuration did not match after the connection"
                            " was lost during the apply.",
                        )
                elif result.verdict is Verdict.UNKNOWN:
                    return self._finish(
                        run,
                        st.UNKNOWN,
                        {st.RUNNING},
                        f"The apply result cannot be determined: {result.message}",
                        "error",
                        diagnostics={"device_touched": True},
                    )
                elif not result.ok:
                    return self._after_failed_apply(
                        run, adapter, ctx, profile, precheck, result.message
                    )
                if not self._move(
                    job_id, st.VERIFYING, {st.RUNNING}, stage="verifying"
                ):
                    return None
                verifying = True
                continue

            if not verifying:  # defensive: a profile without apply cannot get here
                return stop_clean("The profile has no apply step.")

            step_params = self._params_for(step.action, step.params)
            if spec.phase == "verify":
                ctx.scratch.setdefault(
                    "_restore_verify_deadline",
                    time.monotonic() + int(profile.limits["verify_timeout"]),
                )
                if time.monotonic() >= ctx.scratch["_restore_verify_deadline"]:
                    ctx.scratch.pop("_restore_verify_deadline", None)
                    return self._rollback(
                        run,
                        ctx,
                        adapter,
                        profile,
                        f"The verification timeout expired before {step.action}.",
                    )
            else:
                ctx.scratch.pop("_restore_verify_deadline", None)
            result = self._call(run, adapter, method, ctx, step_params)
            if result.details.get("connection_lost") and spec.phase == "verify":
                if self._reconnect(run, adapter, device, credentials, profile):
                    notes.append(f"{step.action}: connection was re-established once")
                    result = self._call(run, adapter, method, ctx, step_params)
            if result.ok:
                continue
            if (
                result.details.get("connection_lost")
                or result.verdict is Verdict.UNKNOWN
            ):
                return self._finish(
                    run,
                    st.UNKNOWN,
                    {st.VERIFYING},
                    f"{step.action} could not be completed or verified:"
                    f" {result.message}. The configuration may be applied;"
                    " check the device manually.",
                    "error",
                    diagnostics={"device_touched": True},
                )
            if spec.phase == "persist":
                return self._finish(
                    run,
                    st.FAILED,
                    {st.VERIFYING},
                    "The configuration is applied and verified, but the last step (saving or"
                    f" finalizing it) failed: {result.message}. Check the device.",
                    "error",
                    diagnostics={"device_touched": True, "applied_not_persisted": True},
                )
            if not step.required:
                notes.append(f"{step.action} (optional) did not pass: {result.message}")
                continue
            return self._rollback(
                run, ctx, adapter, profile, f"{step.action} failed: {result.message}."
            )

        self._finish(
            run,
            st.SUCCESS,
            {st.VERIFYING},
            "The configuration was restored and verified.",
            diagnostics={"device_touched": True, "notes": notes},
        )

    # ------------------------------------------------------ failure handling
    def _reconnect(self, run, adapter, device, credentials, profile) -> bool:
        """New session within reconnect_timeout. Read-only use afterwards."""
        timeout = profile.limits["reconnect_timeout"]
        if timeout <= 0:
            return False
        deadline = self._monotonic() + timeout
        while True:
            self._close(adapter)
            try:
                adapter.connect(device, credentials, profile.limits["connect_timeout"])
                run.event("recovery", "reconnected", "Session re-established")
                return True
            except Exception:  # any failure just means "not reconnected yet"
                pass
            if self._monotonic() + RECONNECT_INTERVAL_SECONDS > deadline:
                run.event(
                    "recovery", "reconnect_failed", "Could not reconnect", "error"
                )
                return False
            self._sleep(RECONNECT_INTERVAL_SECONDS)

    def _recover_session(
        self, run, adapter, device, credentials, profile, ctx, notes
    ) -> str:
        """
        The session dropped during the apply. NEVER re-apply. Reconnect and read the
        state back: "verified" | "mismatch" | "unknown".
        """
        run.event(
            "apply",
            "connection_lost",
            "Connection lost during the apply; no automatic retry",
            "error",
        )
        if not self._reconnect(run, adapter, device, credentials, profile):
            return "unknown"
        check = self._call(run, adapter, "verify_running_config", ctx)
        if check.ok:
            notes.append(
                "connection was lost during the apply; the result was verified after reconnecting"
            )
            return "verified"
        if check.verdict is Verdict.FAILED and not check.details.get("connection_lost"):
            return "mismatch"
        return "unknown"

    def _unknown_after_loss(self, run: _Run, what: str) -> None:
        self._finish(
            run,
            st.UNKNOWN,
            {st.RUNNING},
            f"The connection was lost during {what} and could not be restored; the"
            " result is unknown. No automatic retry or rollback was attempted -"
            " check the device manually.",
            "error",
            diagnostics={"device_touched": True, "connection_lost": True},
        )

    def _after_failed_apply(
        self, run, adapter, ctx, profile, precheck, message: str
    ) -> None:
        reason = f"The apply failed: {message}."
        expected_sha = precheck.get("current_sha256")
        now = self._call(run, adapter, "fetch_current_config", ctx)
        current_sha = (
            config_sha256(now.payload) if now.ok and now.payload is not None else None
        )
        if current_sha and expected_sha and current_sha == expected_sha:
            return self._finish(
                run,
                st.FAILED,
                {st.RUNNING},
                f"{reason} The device configuration was verified unchanged.",
                "error",
                diagnostics={"device_touched": False},
            )
        if self._rollback_available(adapter, ctx, profile):
            return self._rollback(run, ctx, adapter, profile, reason)
        if current_sha is None or not expected_sha:
            return self._finish(
                run,
                st.UNKNOWN,
                {st.RUNNING},
                f"{reason} The device state could not be verified and no rollback is"
                " available; check the device manually.",
                "error",
                diagnostics={"device_touched": True},
            )
        return self._finish(
            run,
            st.FAILED,
            {st.RUNNING},
            f"{reason} The device configuration differs from the original and no"
            " rollback is available; check the device manually.",
            "error",
            diagnostics={"device_touched": True},
        )

    @staticmethod
    def _rollback_available(adapter, ctx, profile) -> bool:
        return bool(
            profile.rollback_strategy != "none"
            and adapter.supports_rollback()
            and ctx.scratch.get("pre_restore_config")
        )

    def _rollback(self, run, ctx, adapter, profile, reason: str) -> None:
        ctx.scratch.pop("_restore_verify_deadline", None)
        if not self._rollback_available(adapter, ctx, profile):
            return self._finish(
                run,
                st.FAILED,
                {st.RUNNING, st.VERIFYING},
                f"{reason} Automatic rollback is not available: the device may be in a"
                " changed state - check it manually.",
                "error",
                diagnostics={"device_touched": True, "rollback": "unavailable"},
            )
        self._move(
            run.job_id,
            st.ROLLBACK_RUNNING,
            {st.RUNNING, st.VERIFYING},
            stage="rollback",
            rollback_status="running",
        )
        run.event("rollback", "rollback_started", reason, "warning")
        result = self._call(run, adapter, "rollback", ctx)
        if result.details.get("connection_lost"):
            return self._finish(
                run,
                st.UNKNOWN,
                {st.ROLLBACK_RUNNING},
                f"{reason} The connection was lost during the rollback; its result is"
                " unknown. Check the device manually.",
                "error",
                rollback_status="unknown",
                rollback_details=result.message,
                diagnostics={"device_touched": True},
            )
        if not result.ok:
            return self._finish(
                run,
                st.ROLLBACK_FAILED,
                {st.ROLLBACK_RUNNING},
                f"{reason} The rollback failed: {result.message}. The device needs"
                " manual attention.",
                "error",
                rollback_status="failed",
                rollback_details=result.message,
                diagnostics={"device_touched": True},
            )
        check = self._call(run, adapter, "verify_rollback", ctx)
        if check.ok:
            return self._finish(
                run,
                st.FAILED_ROLLBACK_CONFIRMED,
                {st.ROLLBACK_RUNNING},
                f"{reason} The previous configuration was restored and confirmed.",
                "warning",
                rollback_status="confirmed",
                rollback_details=check.message,
                diagnostics={"device_touched": True},
            )
        if check.verdict is Verdict.UNKNOWN:
            return self._finish(
                run,
                st.UNKNOWN,
                {st.ROLLBACK_RUNNING},
                f"{reason} The rollback could not be verified; check the device manually.",
                "error",
                rollback_status="unknown",
                rollback_details=check.message,
                diagnostics={"device_touched": True},
            )
        return self._finish(
            run,
            st.ROLLBACK_FAILED,
            {st.ROLLBACK_RUNNING},
            f"{reason} The rollback was sent but the previous configuration is not"
            " confirmed. The device needs manual attention.",
            "error",
            rollback_status="failed",
            rollback_details=check.message,
            diagnostics={"device_touched": True},
        )

    # ----------------------------------------------------------------- restart
    def recover_interrupted(
        self, stale_after_seconds: Optional[int] = None
    ) -> List[int]:
        """
        Call when a worker starts. Jobs a dead worker had claimed (running, verifying,
        rollback_running) become `unknown`: they are NEVER resumed. Queued jobs stay
        queued (nothing was started). stale_after_seconds=None marks every such job -
        the caller must guarantee that no other worker is alive.
        """
        marked: List[int] = []
        for job in self.store.list_jobs(st.INTERRUPTED_ON_RESTART):
            if stale_after_seconds is not None and job.heartbeat_at is not None:
                age = (
                    _naive_utc(self._now()) - _naive_utc(job.heartbeat_at)
                ).total_seconds()
                if age < stale_after_seconds:
                    continue
            run = _Run(self, job.id)
            if self._finish(
                run,
                st.UNKNOWN,
                {job.status},
                "The application restarted while this operation was running; the"
                " result is unknown and it was not resumed. Check the device manually.",
                "error",
                diagnostics={"device_touched": True, "interrupted": True},
            ):
                marked.append(job.id)
        return marked
