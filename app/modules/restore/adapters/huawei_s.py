"""
Huawei S-series adapter (S5700 / S5720 / S6700 / S6720, VRP5). Netmiko transport.

THIS RESTORE REBOOTS THE SWITCH. The Huawei guides for these series describe restoring a
configuration as: put the file on the device, make it the startup file with
`startup saved-configuration <file>`, and reboot; the configuration takes effect only after the
restart. No online replace of the running configuration was found for them.

STATUS: NOT VERIFIED ON HARDWARE (`verified = False`), off unless
RESTORE_ENABLE_UNVERIFIED_ADAPTERS is set. Written from the S-series V200R011C10 / V200R019C10
guides; the prompts of `reboot` differ between software versions (see the open points).

  precheck   upload the target file (SFTP), check that the device sees it; nothing else changes
  apply      upload the rollback file (the NABS copy of the configuration before) and the target,
             `startup saved-configuration <target>`, `reboot`. THE QUESTIONS OF `reboot` ARE
             ANSWERED STRICTLY: "save the current configuration" is answered N (a Y would write
             the running configuration over the target file and the restore would do nothing);
             an unknown question, or a version that saves the running configuration over the
             next-startup file without asking, aborts BEFORE the reboot
  verify     wait for the device (new SSH sessions), then `display startup` must show the target
             as the file it booted from, and the running configuration must match the target
  persist    move the restored configuration back to the original startup file name
  rollback   `startup saved-configuration <rollback file>` and a second reboot

There is no device-side revert timer. A restore ends either verified, rolled back and verified,
or `unknown` (for example when the device does not come back).
"""

import re
import time
from typing import Any, Callable, List, Optional, Sequence

from app.modules.restore.adapters import huawei_common as hw
from app.modules.restore.adapters.base import (
    ActionResult,
    AdapterError,
    AdapterTimeout,
    ConnectionLost,
    Credentials,
    DeviceInfo,
    RestoreAdapter,
    RestoreContext,
    translate_exception,
)

SPACE_MARGIN_BYTES = 65536
# the question that offers to SAVE the running configuration before the reboot: always "n"
SAVE_QUESTION_RE = re.compile(
    r"(configuration has been modified|save the (current )?configuration|saved to the next startup)",
    re.IGNORECASE,
)
# the question that really starts the reboot
REBOOT_QUESTION_RE = re.compile(r"(continue|reboot|restart)", re.IGNORECASE)
RECONNECT_POLL_SECONDS = 15


class HuaweiSAdapter(RestoreAdapter):
    type = "huawei_s"
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

    @classmethod
    def create(cls, ignore_patterns=()) -> "HuaweiSAdapter":
        return cls(ignore_patterns=ignore_patterns)

    def __repr__(self) -> str:
        return f"<HuaweiSAdapter connected={self._conn is not None}>"

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

    def _disconnect(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass

    def finalize(self, outcome_status: str) -> tuple[str, ...]:
        """Remove temporary files only after restore/rollback has been positively verified."""
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

    def _wait_for_device(self, ctx: RestoreContext) -> None:
        """Wait (up to reconnect_timeout) for a NEW session; the old one died with the reboot."""
        if self._conn is not None:
            try:
                if self._conn.find_prompt().strip():
                    return
            except Exception:
                self._disconnect()
        if self._device is None or self._credentials is None:
            raise ConnectionLost("not connected")
        waited = 0.0
        started = time.monotonic()
        limit = int(ctx.profile.limits["reconnect_timeout"])
        while True:
            elapsed = time.monotonic() - started
            remaining = min(limit - waited, limit - elapsed)
            if remaining <= 0:
                raise ConnectionLost(
                    "the device did not come back within reconnect_timeout"
                )
            connect_timeout = max(1, min(self._timeout, int(remaining)))
            try:
                self._conn = hw.open_connection(
                    self._factory, self._device, self._credentials, connect_timeout
                )
                return
            except AdapterError:
                pass
            elapsed = time.monotonic() - started
            remaining = min(limit - waited, limit - elapsed)
            if remaining <= 0:
                raise ConnectionLost(
                    "the device did not come back within reconnect_timeout"
                )
            pause = min(RECONNECT_POLL_SECONDS, remaining)
            self._sleep(pause)
            waited += pause

    # --------------------------------------------------------------- commands
    def _show(self, command: str, ctx: RestoreContext) -> str:
        return hw.show(
            self._require(),
            command,
            hw.bounded_timeout(ctx, ctx.profile.limits["operation_timeout"]),
        )

    @staticmethod
    def _names(ctx: RestoreContext):
        job = int(ctx.job_id)
        return f"nabs-restore-{job}-target.cfg", f"nabs-restore-{job}-pre.cfg"

    def _upload(self, ctx: RestoreContext, name: str, text: str) -> None:
        self._device_files.append(name)
        hw.sftp_put(self._require(), text, name, self._sftp)
        listing = self._show(f"dir {name}", ctx)
        if name not in listing or hw.ERROR_RE.search(listing):
            raise AdapterError(
                "the uploaded file is not in the root directory of the device storage"
                " (check 'ssh user ... sftp-directory')"
            )

    def _set_startup(self, ctx: RestoreContext, name: str) -> Optional[str]:
        """`startup saved-configuration <name>`; None on success, else the reason."""
        timeout = ctx.profile.limits["operation_timeout"]
        out = hw.run_interactive(
            self._require(),
            f"startup saved-configuration {name}",
            [(r"continue|sure|change", "y")],
            timeout,
        )
        if hw.ERROR_RE.search(out):
            return "the device refused to use the file as the startup file"
        _current, nxt = hw.parse_startup(self._show("display startup", ctx))
        if hw.basename(nxt) != name.lower():
            return "the next startup file was not changed as expected"
        return None

    def _reboot(self, ctx: RestoreContext) -> Optional[str]:
        """
        Reboot with strict answers. None when the reboot was confirmed (the session then dies),
        otherwise the reason it was NOT done (the device was answered 'n').
        Each question is judged on its own text: the output of the previous answer is not mixed in.
        """
        conn = self._require()
        timeout = ctx.profile.limits["operation_timeout"]
        try:
            chunk = hw._send(conn, "reboot", timeout)
            for _ in range(hw.MAX_QUESTIONS):
                question = chunk[-600:]
                if not hw.QUESTION_RE.search(question):
                    return "the device did not ask to confirm the reboot"
                saves = bool(SAVE_QUESTION_RE.search(question))
                reboots = bool(REBOOT_QUESTION_RE.search(question))
                if saves and reboots:
                    # ONE question that both saves the running configuration over the file we are
                    # about to boot and reboots: there is no safe answer
                    hw._send(conn, "n", timeout, cmd_verify=False)
                    return (
                        "this software version would save the running configuration over the"
                        " next-startup file when rebooting, which would undo the restore"
                    )
                if saves:
                    chunk = hw._send(
                        conn, "n", timeout, cmd_verify=False
                    )  # never save over it
                    continue
                if reboots:
                    conn.write_channel("y\n")  # the answer after which the session dies
                    self._sleep(3)
                    self._disconnect()
                    return None
                hw._send(conn, "n", timeout, cmd_verify=False)
                return (
                    "the device asked an unexpected question: "
                    + " ".join(question.split())[-160:]
                )
        except AdapterError:
            raise
        except Exception as error:
            raise translate_exception(error) from None
        return "too many questions from the device"

    # ---------------------------------------------------------------- handlers
    def check_platform_support(self, ctx: RestoreContext) -> ActionResult:
        info = hw.parse_display_version(self._show("display version", ctx))
        if info is None:
            return ActionResult.unknown("the platform could not be recognised")
        if info.family == "ce":
            return ActionResult.failure(
                f"{info.model} is a CloudEngine switch: use the Huawei CloudEngine profile"
            )
        if info.family != "s":
            return ActionResult.failure(
                f"unsupported Huawei platform: {info.model or 'unknown'}"
            )
        ctx.scratch["huawei_platform"] = info
        return ActionResult.success(
            f"{info.model} {info.software or ''}".strip(),
            details={"model": info.model, "software": info.software},
        )

    def check_connectivity(self, ctx: RestoreContext) -> ActionResult:
        try:
            prompt = self._require().find_prompt().strip()
        except AdapterError:
            raise
        except Exception as error:
            raise translate_exception(error) from None
        if re.match(r"^<[^<>]+>$", prompt):
            return ActionResult.success("user view")
        return ActionResult.failure("the session is not in the user view")

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
        current, nxt = hw.parse_startup(self._show("display startup", ctx))
        if not current or not nxt:
            return ActionResult.unknown(
                "the startup files of the device could not be read"
            )
        needed = (
            2
            * (len(ctx.scratch.get("huawei_current_text", "")) + len(ctx.target_config))
            + SPACE_MARGIN_BYTES
        )
        if free < needed:
            return ActionResult.failure(
                f"not enough free space: {free} bytes free, about {needed} needed"
            )
        original_startup = hw.basename(nxt)
        if hw.SAFE_FILE_RE.fullmatch(original_startup):
            return ActionResult.failure(
                "the next startup file is a temporary NABS restore file; inspect and resolve "
                "the previous restore manually before starting another restore"
            )
        ctx.scratch["huawei_orig_startup"] = original_startup
        warnings = []
        if hw.basename(current) != hw.basename(nxt):
            warnings.append(
                f"the device will boot from {nxt}, not from the file it booted from ({current})"
            )
        return ActionResult.success(
            f"startup file {hw.basename(nxt)}; the rollback file and the target fit",
            details={"free": free},
            warnings=tuple(warnings),
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
                " 'sftp server enable' line (needed to upload the restore file)"
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
        compared = self._show(f"compare configuration {target}", ctx)
        if hw.ERROR_RE.search(compared):
            return ActionResult.failure(
                "the device could not read the target file as a configuration"
            )
        current = ctx.scratch.get("huawei_current_text", "")
        removed = hw.removed_lines(current, target_text)
        added = [
            ln
            for ln in hw.normalize_config(target_text).split("\n")
            if ln not in hw.line_set(hw.normalize_config(current))
        ]
        warnings: List[str] = [
            "the device will REBOOT: it is unreachable for several minutes and traffic through"
            " it is interrupted"
        ]
        risky = [ln for ln in removed if hw.RISKY_REMOVAL_RE.match(ln)]
        if risky:
            warnings.append(
                f"the restore removes or changes {len(risky)} line(s) that can affect remote"
                " access (users, SSH/SFTP, vty, default route, SNMP)"
            )
        return ActionResult.success(
            f"+{len(added)} / -{len(removed)} lines differ",
            details={"added": len(added), "removed": len(removed)},
            warnings=tuple(warnings),
        )

    def apply_saved_config(self, ctx: RestoreContext) -> ActionResult:
        target, pre = self._names(ctx)
        pre_text = ctx.scratch.get("pre_restore_config")
        if not pre_text:
            return ActionResult.failure(
                "there is no stored copy of the current configuration"
            )
        _current, nxt = hw.parse_startup(self._show("display startup", ctx))
        original = hw.basename(nxt)
        if not original:
            return ActionResult.failure(
                "the current startup file could not be read; nothing was changed"
            )
        ctx.scratch["huawei_orig_startup"] = original
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
        self._keep_files = True

        problem = self._set_startup(ctx, target)
        if problem:
            self._set_startup(ctx, original)  # best effort: put the startup file back
            return ActionResult.failure(f"{problem}; the reboot was not started")
        try:
            refused = self._reboot(ctx)
        except hw.UnexpectedPrompt as error:
            refused = f"unexpected question: {error}"
        if refused:
            self._set_startup(ctx, original)
            return ActionResult.failure(
                f"{refused}; the reboot was not started and the startup file was put back"
            )
        return ActionResult.success(
            "reboot confirmed (the device goes offline; not yet verified)"
        )

    def verify_management_access(self, ctx: RestoreContext) -> ActionResult:
        """Waits for the rebooted device. The new session REPLACES the dead one."""
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
                    old, self._conn = self._conn, fresh
                    if old is not None:
                        try:
                            old.disconnect()
                        except Exception:
                            pass
                    return ActionResult.success(
                        f"the device is back, a new SSH session works (attempt {attempt})"
                    )
            except Exception:  # not reachable (yet)
                pass
            finally:
                if fresh is not None and fresh is not self._conn:
                    try:
                        fresh.disconnect()
                    except Exception:
                        pass
        return ActionResult.failure(
            f"the device did not come back within {attempts} attempt(s)"
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
        target, _pre = self._names(ctx)
        current, _next = hw.parse_startup(self._show("display startup", ctx))
        if hw.basename(current) != target.lower():
            return ActionResult.failure(
                f"the device did not boot from the restore file (it booted from {hw.basename(current) or 'unknown'}):"
                " the reboot did not happen or the file was not used"
            )
        running = self._show("display current-configuration", ctx)
        same, missing, extra = self._compare(running, ctx.target_config, mode)
        if same:
            return ActionResult.success(
                "booted from the restore file and the configuration matches"
            )
        return ActionResult.failure(
            f"the running configuration differs from the target ({missing} line(s) missing,"
            f" {extra} unexpected)",
            details={"missing": missing, "unexpected": extra},
        )

    def persist_config(self, ctx: RestoreContext) -> ActionResult:
        """Move the restored configuration back to the original startup file name."""
        timeout = ctx.profile.limits["operation_timeout"]
        original = ctx.scratch.get("huawei_orig_startup")
        target, _pre = self._names(ctx)
        if not original or original == target.lower():
            return ActionResult.success(
                "nothing to move: the device boots from the restore file"
            )
        conn = self._require()
        try:
            out = hw.run_interactive(
                conn,
                f"save {original}",
                [(r"save|sure|overwrite|continue", "y")],
                timeout,
            )
        except hw.UnexpectedPrompt as error:
            return ActionResult.failure(
                f"unexpected question while saving to {original} ({error}); the device boots from {target}"
            )
        if hw.ERROR_RE.search(out) or "success" not in out.lower():
            return ActionResult.failure(
                f"the configuration could not be saved to {original}; the device boots from {target}"
            )
        problem = self._set_startup(ctx, original)
        if problem:
            return ActionResult.failure(f"{problem}; the device boots from {target}")
        return ActionResult.success(
            f"saved to {original}, which is the startup file again"
        )

    # ---------------------------------------------------------------- rollback
    def rollback(self, ctx: RestoreContext) -> ActionResult:
        pre = ctx.scratch.get("device_pre_file")
        if not pre or not hw.SAFE_FILE_RE.match(pre):
            return ActionResult.failure("there is no rollback file on the device")
        self._wait_for_device(ctx)
        problem = self._set_startup(ctx, pre)
        if problem:
            return ActionResult.failure(problem)
        try:
            refused = self._reboot(ctx)
        except hw.UnexpectedPrompt as error:
            refused = f"unexpected question: {error}"
        if refused:
            return ActionResult.failure(
                f"{refused}; the rollback reboot was not started"
            )
        return ActionResult.success("rollback reboot confirmed (not yet verified)")

    def verify_rollback(self, ctx: RestoreContext) -> ActionResult:
        expected = ctx.scratch.get("pre_restore_config")
        if not expected:
            return ActionResult.unknown("there is no stored copy to compare with")
        self._wait_for_device(ctx)
        running = self._show("display current-configuration", ctx)
        same, missing, extra = self._compare(running, expected, "normalized")
        if same:
            # The rollback file was selected as startup for the recovery reboot. Restore the
            # original startup filename before calling the rollback confirmed: otherwise the
            # next ordinary reboot would depend on a temporary nabs-restore file that cleanup
            # is about to delete.
            finalized = self.persist_config(ctx)
            if not finalized.ok:
                return ActionResult.failure(
                    "the previous running configuration matches, but the original startup "
                    f"file could not be restored: {finalized.message}"
                )
            current, nxt = hw.parse_startup(self._show("display startup", ctx))
            original = ctx.scratch.get("huawei_orig_startup")
            if not original or hw.basename(nxt) != original.lower():
                return ActionResult.failure(
                    "the previous running configuration matches, but the original startup "
                    "file could not be confirmed"
                )
            return ActionResult.success(
                "the previous configuration is confirmed and the original startup file is restored"
            )
        return ActionResult.failure(
            f"the previous configuration is not restored ({missing} line(s) missing,"
            f" {extra} unexpected)",
            details={"missing": missing, "unexpected": extra},
        )


# OPEN POINTS - to settle on hardware before this adapter may be called supported
#  1. The questions and the order of `reboot` on each software version, and whether any version
#     saves the running configuration over the next-startup file without asking (the adapter
#     refuses to reboot in that case).
#  2. `startup saved-configuration` with a user file name: whether the file must be in the root of
#     the storage, whether a startup file without local users is refused, and its output text.
#  3. `display startup` output on stacks and chassis (several member lines).
#  4. SFTP: `sftp server enable`, the user's service type and sftp-directory.
#  5. `save <file>` and `delete <file>` prompts and result texts.
#  6. How long the device is unreachable, and `reconnect_timeout` / `verify_management_access`
#     (attempts x wait_seconds) values that cover it.
