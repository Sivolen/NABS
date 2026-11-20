"""
Huawei CloudEngine adapter (CE6800 / CE8800 / CE9800 / CE12800 / CE16800). Netmiko transport.

STATUS: NOT VERIFIED ON HARDWARE (`verified = False`), off unless
RESTORE_ENABLE_UNVERIFIED_ADAPTERS is set. Written from the CloudEngine command reference
(V300R024C00 and the CE12800/CE16800 references); the commands differ between series and
releases, so every point in the list at the end of this file has to be settled on a device.

Mechanism (two-phase validation mode, where a change is first a CANDIDATE and only `commit`
makes it run):
  precheck   upload the target file (SFTP), `load configuration file <f> replace` loads it into
             the candidate, `display configuration replace failed` and
             `display configuration candidate changes` say what would happen, then
             `clear configuration candidate` throws it away: nothing is committed
  apply      upload the rollback file (the NABS copy of the configuration before) and the target,
             load the target, `commit trial <seconds>`: the new configuration RUNS, and the
             device reverts to the previous one BY ITSELF unless it is confirmed in time
  verify     a NEW ssh session, then the running configuration compared with the target
  persist    `commit` (confirms the trial) and `save`
  rollback   `abort trial` while the trial is open, otherwise load the rollback file + `commit`

So unlike the Cisco adapter there is a device-side revert timer: if the session is lost or the
restore is not confirmed, the device returns to the previous configuration. (According to the
reference a trial that is not made persistent ends with its session; this is an open point.)
"""

import re
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.modules.restore.adapters import huawei_common as hw
from app.modules.restore.adapters.base import (
    ActionResult,
    AdapterError,
    CandidateCleanupUncertain,
    AdapterTimeout,
    ConnectionLost,
    Credentials,
    DeviceInfo,
    RestoreAdapter,
    RestoreContext,
    translate_exception,
)

SPACE_MARGIN_BYTES = 65536


def trial_seconds(ctx: RestoreContext) -> int:
    """Budget verification plus both final commit/save operations and a safety margin.

    The trial must remain active until `persist_config` has confirmed and saved the result,
    not merely until the read-back verification completes. Keep the value within the device's
    supported range; hardware acceptance must still confirm the valid minimum/maximum per VRP.
    """
    limits = ctx.profile.limits
    required = int(limits["verify_timeout"] + 2 * limits["operation_timeout"] + 60)
    return max(120, min(65535, required))


class HuaweiCeAdapter(RestoreAdapter):
    type = "huawei_ce"
    verified = False

    def __init__(
        self,
        ignore_patterns: Sequence[str] = (),
        connection_factory: Optional[Callable[..., Any]] = None,
        sftp_factory: Optional[Callable[[Any], Any]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._ignore = tuple(ignore_patterns)
        self._factory = connection_factory
        self._sftp = sftp_factory
        self._sleep = sleep
        self._conn: Any = None
        self._device: Optional[DeviceInfo] = None
        self._credentials: Optional[Credentials] = None
        self._timeout = 10
        self._device_files: List[str] = []
        self._keep_files = False
        self._trial_active = False

    @classmethod
    def create(cls, ignore_patterns=()) -> "HuaweiCeAdapter":
        return cls(ignore_patterns=ignore_patterns)

    def __repr__(self) -> str:
        return f"<HuaweiCeAdapter connected={self._conn is not None}>"

    # ---------------------------------------------------------------- session
    def connect(
        self, device: DeviceInfo, credentials: Credentials, connect_timeout: int
    ) -> None:
        self._disconnect()
        self._device, self._credentials, self._timeout = (
            device,
            credentials,
            connect_timeout,
        )
        self._conn = hw.open_connection(
            self._factory, device, credentials, connect_timeout
        )
        self._trial_active = False  # a trial belongs to a session: a new one has none

    def _disconnect(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass

    def finalize(self, outcome_status: str) -> tuple[str, ...]:
        """Remove target/rollback files only when the final device state is known safe."""
        if outcome_status not in {"success", "failed_rollback_confirmed"}:
            return ()
        if self._conn is None:
            self._keep_files = True
            return tuple(
                self._device_files
                or ["device session unavailable; temporary files may remain"]
            )
        errors = []
        for name in list(self._device_files):
            if hw.delete_file(self._conn, name, self._timeout):
                self._device_files.remove(name)
            else:
                errors.append(name)
        self._keep_files = bool(errors)
        return tuple(errors)

    def close(self) -> tuple[str, ...]:
        if self._keep_files:
            self._disconnect()
            return ()  # deliberately retained for unknown/failed rollback
        if self._conn is not None:
            for name in list(self._device_files):
                if hw.delete_file(self._conn, name, self._timeout):
                    self._device_files.remove(name)
        errors = tuple(self._device_files)
        self._disconnect()
        return errors

    def _require(self) -> Any:
        if self._conn is None:
            raise ConnectionLost("not connected")
        return self._conn

    # --------------------------------------------------------------- commands
    def _show(self, command: str, ctx: RestoreContext) -> str:
        return hw.show(
            self._require(),
            command,
            hw.bounded_timeout(ctx, ctx.profile.limits["operation_timeout"]),
        )

    def _config_view(
        self, ctx: RestoreContext, commands: List[str], rules=()
    ) -> Dict[str, str]:
        """
        system-view, the commands, return. {command: output}. The view is always left, also
        after an error, so that the session is not left in a configuration view.
        """
        conn = self._require()
        timeout = ctx.profile.limits["operation_timeout"]
        outputs: Dict[str, str] = {}
        hw.show(conn, "system-view", timeout)
        try:
            # the prompt of the view says whether the device is in two-phase mode ([~...] / [*...])
            entered = conn.find_prompt()
            for command in commands:
                outputs[command] = hw.run_interactive(conn, command, rules, timeout)
        except Exception as error:
            if isinstance(error, AdapterError):
                raise
            raise translate_exception(error) from None
        finally:
            try:
                hw.show(conn, "return", timeout)
            except AdapterError:
                pass
        outputs["__prompt__"] = entered
        return outputs

    def _upload(self, ctx: RestoreContext, name: str, text: str) -> None:
        self._device_files.append(name)
        hw.sftp_put(self._require(), text, name, self._sftp)
        listing = self._show(f"dir {name}", ctx)
        if name not in listing or hw.ERROR_RE.search(listing):
            raise AdapterError(
                "the uploaded file is not in the root directory of the device storage"
                " (check 'ssh user ... sftp-directory')"
            )

    @staticmethod
    def _names(ctx: RestoreContext):
        job = int(ctx.job_id)
        return f"nabs-restore-{job}-target.cfg", f"nabs-restore-{job}-pre.cfg"

    # ---------------------------------------------------------------- handlers
    def check_platform_support(self, ctx: RestoreContext) -> ActionResult:
        info = hw.parse_display_version(self._show("display version", ctx))
        if info is None:
            return ActionResult.unknown("the platform could not be recognised")
        if info.family == "s":
            return ActionResult.failure(
                f"{info.model} is an S-series switch: use the Huawei S-series profile"
            )
        if info.family != "ce":
            return ActionResult.failure(
                f"unsupported Huawei platform: {info.model or 'unknown'}"
            )
        ctx.scratch["huawei_platform"] = info
        return ActionResult.success(
            f"{info.model} {info.software or ''}".strip(),
            details={"model": info.model, "software": info.software},
        )

    def check_connectivity(self, ctx: RestoreContext) -> ActionResult:
        conn = self._require()
        try:
            prompt = conn.find_prompt().strip()
        except Exception as error:
            raise translate_exception(error) from None
        if not re.match(r"^<[^<>]+>$", prompt):
            return ActionResult.failure("the session is not in the user view")
        outputs = self._config_view(ctx, [])
        mode = outputs["__prompt__"].strip().split("\n")[-1].strip()
        if not re.match(r"^\[[~*]", mode):
            return ActionResult.failure(
                "the device is not in two-phase validation mode (the system view prompt has no"
                " ~ or *): the restore needs it for the trial and the commit"
            )
        if not mode.startswith("[~"):
            return ActionResult.failure(
                "the device already has uncommitted configuration"
            )
        return ActionResult.success("two-phase validation mode")

    def fetch_current_config(self, ctx: RestoreContext) -> ActionResult:
        text = self._show("display current-configuration", ctx).replace("\r\n", "\n")
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if len(lines) < 5 or lines[-1].lower() != "return":
            return ActionResult.failure(
                "the running configuration looks incomplete (no final 'return')"
            )
        ctx.scratch["huawei_current_text"] = text
        ctx.scratch["huawei_current_lines"] = len(lines)
        ctx.scratch["huawei_sftp_enabled"] = any(
            ln == "sftp server enable" for ln in lines
        )
        return ActionResult.success(f"{len(lines)} lines", payload=text.rstrip() + "\n")

    def check_rollback_available(self, ctx: RestoreContext) -> ActionResult:
        free = hw.parse_free_bytes(self._show("dir", ctx))
        if free is None:
            return ActionResult.unknown(
                "the free space of the device storage could not be read"
            )
        needed = (
            2
            * (len(ctx.scratch.get("huawei_current_text", "")) + len(ctx.target_config))
            + SPACE_MARGIN_BYTES
        )
        if free < needed:
            return ActionResult.failure(
                f"not enough free space: {free} bytes free, about {needed} needed for the"
                " rollback file and the target file"
            )
        return ActionResult.success(
            "the rollback file and the target file fit", details={"free": free}
        )

    def _clear_candidate(self, conn, timeout: int) -> None:
        try:
            output = hw.show(conn, "clear configuration candidate", timeout)
            clean = conn.find_prompt().strip().startswith("[~")
        except Exception:
            raise CandidateCleanupUncertain(
                "candidate cleanup could not be verified; inspect the device"
            ) from None
        if hw.ERROR_RE.search(output) or not clean:
            raise CandidateCleanupUncertain(
                "candidate cleanup could not be verified; inspect the device"
            )

    def validate_target_config(self, ctx: RestoreContext) -> ActionResult:
        target_text = ctx.target_config.replace("\r\n", "\n")
        reason = hw.check_target_text(
            target_text,
            int(ctx.scratch.get("huawei_current_lines") or 0),
            ctx.scratch.get("huawei_current_text", ""),
            ctx.device.ip,
        )
        if reason:
            return ActionResult.failure(reason)
        if ctx.scratch.get("huawei_sftp_enabled") is False:
            return ActionResult.failure(
                "the SFTP server is not enabled on the device: the running configuration has no"
                " 'sftp server enable' line (needed to upload the file for the replace)"
            )
        target, _pre = self._names(ctx)
        try:
            self._upload(ctx, target, target_text)
        except (ConnectionLost, AdapterTimeout):
            raise
        except AdapterError as error:
            return ActionResult.failure(
                f"the target file could not be uploaded to the device ({error}); check"
                " 'sftp server enable', the user's service type (ssh user ... service-type"
                " sftp) and its sftp-directory"
            )
        # a dry run: load it into the CANDIDATE only, look, and throw the candidate away
        timeout = ctx.profile.limits["operation_timeout"]
        conn = self._require()
        added = removed = 0
        failed_commands = 0
        warnings: List[str] = []
        attempted_load = False
        hw.show(conn, "system-view", timeout)
        try:
            if not conn.find_prompt().strip().startswith("[~"):
                return ActionResult.failure(
                    "the candidate is not clean; resolve pending changes first"
                )
            attempted_load = True
            loaded = hw.run_interactive(
                conn,
                f"load configuration file {target} replace",
                [(r"continue|replace", "y")],
                timeout,
            )
            if hw.ERROR_RE.search(loaded):
                return ActionResult.failure(
                    "the device refused to load the target file"
                )
            failures = hw.show(conn, "display configuration replace failed", timeout)
            failed_commands = len(
                re.findall(r"^\s*Command\s*:", failures, re.MULTILINE)
            )
            changes = hw.show(conn, "display configuration candidate changes", timeout)
            added = sum(1 for ln in changes.split("\n") if re.match(r"^\+\s", ln))
            removed = sum(1 for ln in changes.split("\n") if re.match(r"^-\s", ln))
        finally:
            try:
                if attempted_load:
                    self._clear_candidate(conn, timeout)
            finally:
                try:
                    hw.show(conn, "return", timeout)
                except AdapterError:
                    pass
        if failed_commands:
            return ActionResult.failure(
                f"the device cannot replace {failed_commands} command(s) of the stored"
                " configuration (see 'display configuration replace failed' on the device)"
            )
        risky = [
            ln
            for ln in hw.removed_lines(
                ctx.scratch.get("huawei_current_text", ""), target_text
            )
            if hw.RISKY_REMOVAL_RE.match(ln)
        ]
        if risky:
            warnings.append(
                f"the restore removes or changes {len(risky)} line(s) that can affect remote"
                " access (users, SSH/SFTP, vty, default route, SNMP)"
            )
        return ActionResult.success(
            f"+{added} / -{removed} lines differ (device view)",
            details={"added": added, "removed": removed},
            warnings=tuple(warnings),
        )

    def apply_saved_config(self, ctx: RestoreContext) -> ActionResult:
        timeout = ctx.profile.limits["operation_timeout"]
        target, pre = self._names(ctx)
        pre_text = ctx.scratch.get("pre_restore_config")
        if not pre_text:
            return ActionResult.failure(
                "there is no stored copy of the current configuration"
            )
        # 1. both files on the device: the rollback file and the target
        try:
            self._upload(ctx, pre, pre_text)
            self._upload(ctx, target, ctx.target_config.replace("\r\n", "\n"))
        except (ConnectionLost, AdapterTimeout):
            raise
        except AdapterError as error:
            return ActionResult.failure(
                f"the files could not be uploaded ({error}); nothing was changed"
            )
        ctx.scratch["device_pre_file"] = pre
        self._keep_files = True  # from here on the files are the evidence

        trial_requested = False
        conn = self._require()
        hw.show(conn, "system-view", timeout)
        try:
            if not conn.find_prompt().strip().startswith("[~"):
                return ActionResult.failure(
                    "the candidate is not clean; resolve pending changes first"
                )
            loaded = hw.run_interactive(
                conn,
                f"load configuration file {target} replace",
                [(r"continue|replace", "y")],
                timeout,
            )
            failures = hw.show(conn, "display configuration replace failed", timeout)
            failed = len(re.findall(r"^\s*Command\s*:", failures, re.MULTILINE))
            if hw.ERROR_RE.search(loaded) or failed:
                self._clear_candidate(conn, timeout)
                return ActionResult.failure(
                    "the device could not load the target as a replacement"
                    + (f" ({failed} command(s) failed)" if failed else "")
                    + "; nothing was committed"
                )
            seconds = trial_seconds(ctx)
            trial_requested = True
            out = hw.run_interactive(
                conn, f"commit trial {seconds}", [(r"continue", "y")], timeout
            )
            if hw.ERROR_RE.search(out):
                self._clear_candidate(conn, timeout)
                return ActionResult.failure(
                    "the device refused the trial commit; nothing was committed"
                )
            self._trial_active = True
        except AdapterError as error:
            if trial_requested and isinstance(error, (ConnectionLost, AdapterTimeout)):
                raise
            return ActionResult.unknown(
                "the candidate or trial state could not be verified; inspect the device"
            )
        finally:
            try:
                hw.show(conn, "return", timeout)
            except AdapterError:
                pass
        return ActionResult.success(
            f"loaded and running on trial for {seconds} s (not yet verified); the device reverts"
            " by itself unless it is confirmed in the last step"
        )

    def verify_management_access(self, ctx: RestoreContext) -> ActionResult:
        attempts = int(ctx.params.get("attempts", 3))
        wait = int(ctx.params.get("wait_seconds", 10))
        if self._device is None or self._credentials is None:
            raise ConnectionLost("not connected")
        for attempt in range(1, attempts + 1):
            remaining = hw.remaining_verify_seconds(ctx)
            if remaining is not None and remaining <= 0:
                return ActionResult.failure(
                    "verification timed out while waiting for management access"
                )
            self._sleep(min(wait, remaining) if remaining is not None else wait)
            remaining = hw.remaining_verify_seconds(ctx)
            if remaining is not None and remaining <= 0:
                return ActionResult.failure(
                    "verification timed out while waiting for management access"
                )
            fresh = None
            try:
                connect_timeout = self._timeout
                if remaining is not None:
                    connect_timeout = max(1, min(connect_timeout, int(remaining)))
                fresh = hw.open_connection(
                    self._factory, self._device, self._credentials, connect_timeout
                )
                if fresh.find_prompt().strip():
                    return ActionResult.success(
                        f"a new SSH session works (attempt {attempt})"
                    )
            except Exception:  # any failure just means "not reachable (yet)"
                pass
            finally:
                if fresh is not None:
                    try:
                        fresh.disconnect()
                    except Exception:
                        pass
        return ActionResult.failure(
            f"a new SSH session could not be opened after {attempts} attempt(s)"
        )

    def _compare(self, running: str, expected: str, mode: str):
        a = hw.normalize_config(running, self._ignore, mode)
        b = hw.normalize_config(expected, self._ignore, mode)
        if a == b:
            return True, 0, 0
        sa, sb = hw.line_set(a), hw.line_set(b)
        return False, len(sb - sa), len(sa - sb)

    def verify_running_config(self, ctx: RestoreContext) -> ActionResult:
        mode = str(ctx.params.get("compare", "normalized"))
        running = self._show("display current-configuration", ctx)
        same, missing, extra = self._compare(running, ctx.target_config, mode)
        if same:
            return ActionResult.success("the running configuration matches the target")
        return ActionResult.failure(
            f"the running configuration differs from the target ({missing} line(s) missing,"
            f" {extra} unexpected)",
            details={"missing": missing, "unexpected": extra},
        )

    def persist_config(self, ctx: RestoreContext) -> ActionResult:
        """Confirm the trial (commit) and save."""
        timeout = ctx.profile.limits["operation_timeout"]
        conn = self._require()
        if not self._trial_active:
            return ActionResult.failure("there is no trial in progress to confirm")
        hw.show(conn, "system-view", timeout)
        try:
            if not conn.find_prompt().strip().startswith("[~"):
                return ActionResult.failure(
                    "the candidate is not clean; refusing to confirm the trial"
                )
            out = hw.run_interactive(
                conn, "commit", [(r"continue|commit", "y")], timeout
            )
        finally:
            try:
                hw.show(conn, "return", timeout)
            except AdapterError:
                pass
        if hw.ERROR_RE.search(out):
            return ActionResult.failure(
                "the commit was refused: the device reverts to the previous configuration by itself"
            )
        self._trial_active = False
        saved = hw.run_interactive(
            conn, "save", [(r"save|continue|sure", "y")], timeout
        )
        if hw.ERROR_RE.search(saved) or "success" not in saved.lower():
            return ActionResult.failure(
                "the configuration is committed and running but could not be saved to the startup file"
            )
        return ActionResult.success("committed and saved")

    # ---------------------------------------------------------------- rollback
    def rollback(self, ctx: RestoreContext) -> ActionResult:
        timeout = ctx.profile.limits["operation_timeout"]
        conn = self._require()
        if self._trial_active:
            hw.show(conn, "system-view", timeout)
            try:
                out = hw.run_interactive(
                    conn, "abort trial", [(r"rolled back|continue", "y")], timeout
                )
            finally:
                try:
                    hw.show(conn, "return", timeout)
                except AdapterError:
                    pass
            self._trial_active = False
            if hw.ERROR_RE.search(out):
                return ActionResult.failure("the device refused to abort the trial")
            return ActionResult.success("trial aborted (not yet verified)")
        # no trial in this session (a new session, or it was already confirmed)
        expected = ctx.scratch.get("pre_restore_config")
        running = self._show("display current-configuration", ctx)
        if expected and self._compare(running, expected, "normalized")[0]:
            mode = self._config_view(ctx, [])["__prompt__"].strip()
            if not mode.startswith("[~"):
                return ActionResult.failure(
                    "the running configuration is restored but candidate state is uncertain"
                )
            return ActionResult.success(
                "the device is already at the previous configuration"
            )
        pre = ctx.scratch.get("device_pre_file")
        if not pre or not hw.SAFE_FILE_RE.match(pre):
            return ActionResult.failure("there is no rollback file on the device")
        hw.show(conn, "system-view", timeout)
        try:
            if not conn.find_prompt().strip().startswith("[~"):
                return ActionResult.failure(
                    "the candidate is not clean; refusing to load the rollback file"
                )
            loaded = hw.run_interactive(
                conn,
                f"load configuration file {pre} replace",
                [(r"continue|replace", "y")],
                timeout,
            )
            if hw.ERROR_RE.search(loaded):
                self._clear_candidate(conn, timeout)
                return ActionResult.failure(
                    "the device could not load the rollback file"
                )
            out = hw.run_interactive(
                conn, "commit", [(r"continue|commit", "y")], timeout
            )
        finally:
            try:
                hw.show(conn, "return", timeout)
            except AdapterError:
                pass
        if hw.ERROR_RE.search(out):
            return ActionResult.failure("the rollback commit was refused")
        return ActionResult.success("rollback file committed (not yet verified)")

    def verify_rollback(self, ctx: RestoreContext) -> ActionResult:
        expected = ctx.scratch.get("pre_restore_config")
        if not expected:
            return ActionResult.unknown("there is no stored copy to compare with")
        running = self._show("display current-configuration", ctx)
        same, missing, extra = self._compare(running, expected, "normalized")
        if same:
            return ActionResult.success("the previous configuration is confirmed")
        return ActionResult.failure(
            f"the previous configuration is not restored ({missing} line(s) missing,"
            f" {extra} unexpected)",
            details={"missing": missing, "unexpected": extra},
        )


# OPEN POINTS - to settle on hardware before this adapter may be called supported
#  1. The commands per series and release: `load configuration file <f> replace`, `commit trial`,
#     `abort trial`, `display configuration candidate changes`, `display configuration replace
#     failed` are documented for V300R024C00 / CE12800 / CE16800; check CE6863 and CE88xx on the
#     releases in use.
#  2. Two-phase validation mode is required: how it is enabled and whether it is the default.
#  3. SFTP: `sftp server enable`, the user's service type and sftp-directory; the upload lands in
#     the directory the load command reads from.
#  4. What exactly ends a trial that is not persistent (the end of the session?) and whether the
#     revert timer works when the management session is lost.
#  5. Prompts and result texts of load / commit trial / abort trial / commit / save.
#  6. Whether a candidate left by a crashed session can block other administrators.
