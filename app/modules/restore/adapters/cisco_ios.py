"""
Cisco IOS / IOS XE adapter. Transport: Netmiko over SSH.

STATUS: NOT VERIFIED ON HARDWARE (`verified = False`). It was written from Cisco's
"Configuration Replace and Configuration Rollback" documentation and the NAPALM IOS
notes, and tested against a simulated device built from the documented output formats,
never against a real one. It is therefore off unless RESTORE_ENABLE_UNVERIFIED_ADAPTERS
is set. Before it may be called supported, run it on every platform and software
version you intend to cover and settle the open points listed at the end of this file.

Devices that use a NABS custom driver are supported through the Netmiko device type of
that driver (cisco_ios_ssh, cisco_xe_ssh; the `_ssh` suffix is only the transport);
NAPALM devices through the driver name "ios".

Mechanism: the whole running configuration is replaced with `configure replace <file>
force`. Everything that decides success is read back from the device; the text printed
by `configure replace` is NOT trusted (it is known to report failure for a replace that
worked, and the other way round).

  precheck   show version / dir / show running-config; upload the target file and ask
             the device for the differences (`show archive config differences`), without
             changing anything
  apply      copy running-config -> <fs>nabs-restore-<job>-pre.cfg (the rollback source),
             upload the target, `configure replace <target> force`
  verify     a NEW ssh session, then the running config compared with the target
  rollback   `configure replace <pre> force`, then compared with the NABS pre-copy
  persist    `write memory` (the replace does not touch startup-config)

There is NO device-side revert timer: if the session is lost during the replace the
device does not roll back by itself, and the engine reports "unknown". Whether `time`
of `configure replace` can be used safely (its unit differs between software versions)
has to be established on hardware first.
"""

import os
import re
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.modules.restore.compat import normalize_platform
from app.modules.restore.adapters.base import (
    ActionResult,
    AdapterConnectionError,
    AdapterError,
    AdapterTimeout,
    AuthenticationFailed,
    ConnectionLost,
    Credentials,
    DeviceInfo,
    RestoreAdapter,
    RestoreContext,
    translate_exception,
)

FILE_PREFIX = "nabs-restore-"
SAFE_DEVICE_FILE_RE = re.compile(r"^nabs-restore-\d+-(target|pre)\.cfg$")
FILESYSTEM_RE = re.compile(r"^[a-z][a-z0-9]*:$")
PROMPT_RE = re.compile(r"(\[confirm\]|\]\?)\s*$")
# a command is finished when the device shows a prompt again or asks a question
DONE_PATTERN = r"(?:\[confirm\]|\]\?|[#>])\s*$"
VOLATILE_COMMENT_RE = re.compile(
    r"^!\s*(last configuration change|nvram config last updated|"
    r"no configuration change since last restart)",
    re.IGNORECASE,
)
MAX_PROMPTS = 3
SPACE_MARGIN_BYTES = 65536
DEVICE_TYPES = ("cisco_ios", "cisco_xe")

# lines that never matter when two configurations are compared
IGNORED_LINE_PREFIXES = (
    "!",
    "building configuration",
    "current configuration",
    "ntp clock-period",
)

# the output of a command that failed
ERROR_RE = re.compile(
    r"(% ?Invalid input|% ?Incomplete command|% ?Ambiguous command|%Error|^Error\b"
    r"|Rollback Failed|Unable to open|No such file|%Warning: Incomplete|\bfailed\b"
    r"|Error opening|Permission denied|% ?Bad IP address)",
    re.IGNORECASE | re.MULTILINE,
)

# lines a restore must not take away without the operator noticing (warnings)
RISKY_REMOVAL_RE = re.compile(
    r"^\s*(username\s|enable\s+(secret|password)|aaa\s|ip\s+ssh|line\s+vty|"
    r"transport\s+input|access-class|crypto\s+key|ip\s+domain|ip\s+scp|"
    r"ip\s+route\s+0\.0\.0\.0)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PlatformInfo:
    family: str  # "ios" | "iosxe" | "iosxr" | "nxos" | "asa"
    version: Optional[str]
    model: Optional[str] = None


@dataclass(frozen=True)
class DirInfo:
    filesystem: str  # e.g. "flash:"
    total: int
    free: int


@dataclass(frozen=True)
class DiffInfo:
    added: Tuple[str, ...]
    removed: Tuple[str, ...]

    @property
    def identical(self) -> bool:
        return not self.added and not self.removed


# ----------------------------------------------------------------------------- parsers
def parse_show_version(text: str) -> Optional[PlatformInfo]:
    low = text.lower()
    family: Optional[str] = None
    if "cisco ios xr" in low or "ios-xr" in low:
        family = "iosxr"
    elif "nx-os" in low or "nexus operating system" in low:
        family = "nxos"
    elif "adaptive security appliance" in low:
        family = "asa"
    elif "cisco ios xe software" in low:
        family = "iosxe"
    elif "cisco ios software" in low:
        family = "ios"
    if family is None:
        return None
    version_match = re.search(r"Version\s+([0-9][0-9A-Za-z.()\-]*)", text)
    model_match = re.search(
        r"^[Cc]isco\s+(\S+)\s+\(.*\)\s+processor", text, re.MULTILINE
    )
    return PlatformInfo(
        family,
        version_match.group(1) if version_match else None,
        model_match.group(1) if model_match else None,
    )


def parse_dir(text: str) -> Optional[DirInfo]:
    fs = re.search(r"Directory of\s+([A-Za-z0-9]+:)", text)
    sizes = re.search(r"(\d+)\s+bytes total\s+\((\d+)\s+bytes free\)", text)
    if not fs or not sizes:
        return None
    return DirInfo(fs.group(1), int(sizes.group(1)), int(sizes.group(2)))


def parse_diff(text: str) -> Optional[DiffInfo]:
    """`show archive config differences <from> <to>`: '+' only in <to>, '-' only in <from>."""
    if re.search(r"No changes were found", text, re.IGNORECASE):
        return DiffInfo((), ())
    if "!Contextual Config Diffs" not in text:
        return None
    section = text.split("!Contextual Config Diffs:", 1)[1]
    section = re.split(r"^!List of ", section, maxsplit=1, flags=re.MULTILINE)[0]
    added, removed = [], []
    for line in section.splitlines():
        if line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("-"):
            removed.append(line[1:])
    return DiffInfo(tuple(added), tuple(removed))


_HEADER_RE = re.compile(
    r"^(building configuration|current configuration|using \d+ out of \d+ bytes)", re.I
)


def strip_show_header(text: str) -> str:
    """Drop the lines `show running-config` prints before the configuration itself."""
    lines = text.replace("\r\n", "\n").split("\n")
    while lines and (not lines[0].strip() or _HEADER_RE.match(lines[0].strip())):
        lines.pop(0)
    return "\n".join(lines).rstrip() + "\n"


def target_for_device(text: str) -> str:
    """
    The stored text as a file for `configure replace`. A custom driver stores the output
    of its last command as it is, so the `Building configuration...` / `Current
    configuration : N bytes` lines can be in it; the device would reject them.
    """
    return strip_show_header(text)


def normalize_config(
    text: str, ignore_patterns: Sequence[str] = (), mode: str = "normalized"
) -> str:
    """
    exact:      only trailing whitespace and blank lines are ignored
    normalized: also comment lines, the volatile header lines and NABS clear_patterns
    """
    text = text.replace("\r\n", "\n")
    if mode == "normalized":
        for pattern in ignore_patterns:
            text = re.sub(pattern, "", text)
    out = []
    for line in text.split("\n"):
        line = line.rstrip()
        if not line.strip():
            continue
        if mode == "normalized" and line.lower().startswith(IGNORED_LINE_PREFIXES):
            continue
        out.append(line)
    return "\n".join(out)


def _line_set(text: str) -> set:
    return set(text.split("\n"))


_translate = translate_exception  # shared with the other adapters (see base.py)


# ------------------------------------------------------------------------------ adapter
class CiscoIosAdapter(RestoreAdapter):
    type = "cisco_ios"
    verified = False

    def __init__(
        self,
        ignore_patterns: Sequence[str] = (),
        connection_factory: Optional[Callable[..., Any]] = None,
        transfer: Optional[Callable[..., Dict[str, Any]]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._ignore = tuple(ignore_patterns)
        self._factory = connection_factory
        self._transfer = transfer
        self._sleep = sleep
        self._conn: Any = None
        self._device: Optional[DeviceInfo] = None
        self._credentials: Optional[Credentials] = None
        self._timeout = 10
        self._device_files: List[str] = []  # files this run created on the device
        self._keep_files = False  # after the apply they stay: they are the evidence

    @classmethod
    def create(cls, ignore_patterns=()) -> "CiscoIosAdapter":
        return cls(ignore_patterns=ignore_patterns)

    def __repr__(self) -> str:  # never show the credentials
        return f"<CiscoIosAdapter connected={self._conn is not None}>"

    # ---------------------------------------------------------------- session
    def _open(self, device: DeviceInfo, credentials: Credentials, timeout: int) -> Any:
        factory = self._factory
        if factory is None:
            from netmiko import ConnectHandler  # lazy: only a real connection needs it

            factory = ConnectHandler
        try:
            return factory(
                # the custom driver's own type (e.g. cisco_ios_ssh) is what the backups of this
                # device already connect with, so it is used as it is
                device_type=(
                    device.netmiko_device_type
                    if normalize_platform(device.netmiko_device_type) in DEVICE_TYPES
                    else "cisco_ios"
                ),
                host=device.ip,
                port=device.port or 22,
                username=credentials.username,
                password=credentials.password,
                timeout=timeout,
                conn_timeout=timeout,
                auth_timeout=timeout,
                banner_timeout=timeout,
            )
        except Exception as error:  # translated, never leaked with its text
            translated = _translate(error)
            if isinstance(translated, AuthenticationFailed):
                raise translated from None
            raise AdapterConnectionError(
                f"cannot connect ({type(error).__name__})"
            ) from None

    def connect(
        self, device: DeviceInfo, credentials: Credentials, connect_timeout: int
    ) -> None:
        self._disconnect()
        self._device, self._credentials, self._timeout = (
            device,
            credentials,
            connect_timeout,
        )
        self._conn = self._open(device, credentials, connect_timeout)

    def _disconnect(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # closing a dead session must never raise
                pass

    def finalize(self, outcome_status: str) -> tuple[str, ...]:
        """Clean device-side restore files after a known successful restore or rollback."""
        if outcome_status not in {"success", "failed_rollback_confirmed"}:
            return ()
        if self._conn is None:
            self._keep_files = True
            return tuple(
                self._device_files
                or ["device session unavailable; temporary files may remain"]
            )
        for name in list(self._device_files):
            self._delete_device_file(name)
        errors = tuple(self._device_files)
        self._keep_files = bool(errors)
        return errors

    def close(self) -> tuple[str, ...]:
        if self._keep_files:
            self._disconnect()
            return ()  # deliberately retained for unknown/failed rollback
        if self._conn is not None:
            for name in list(self._device_files):
                self._delete_device_file(name)
        errors = tuple(self._device_files)
        self._disconnect()
        return errors

    def _require(self) -> Any:
        if self._conn is None:
            raise ConnectionLost("not connected")
        return self._conn

    # --------------------------------------------------------------- commands
    def _show(self, command: str, ctx: RestoreContext) -> str:
        try:
            timeout = int(ctx.profile.limits["operation_timeout"])
            deadline = ctx.scratch.get("_restore_verify_deadline")
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AdapterTimeout("the configured verification timeout expired")
                timeout = max(1, min(timeout, int(remaining)))
            return self._require().send_command(command, read_timeout=timeout)
        except AdapterError:
            raise
        except Exception as error:
            raise _translate(error) from None

    def _run(self, command: str, timeout: int) -> str:
        """
        A command that may ask for confirmation (copy, write, configure replace).

        It waits until the device shows a prompt again (or asks a question). Netmiko's
        send_command_timing() would return after a short silence: `configure replace`
        prints one banner and then works silently for a long time.
        """
        conn = self._require()
        try:
            out = conn.send_command(
                command,
                expect_string=DONE_PATTERN,
                read_timeout=timeout,
                strip_prompt=False,
                strip_command=False,
            )
            for _ in range(MAX_PROMPTS):
                if not PROMPT_RE.search(out[-200:]):
                    break
                out += conn.send_command(
                    "\n",
                    expect_string=DONE_PATTERN,
                    read_timeout=timeout,
                    strip_prompt=False,
                    strip_command=False,
                    cmd_verify=False,
                )
            return out
        except AdapterError:
            raise
        except Exception as error:
            raise _translate(error) from None

    def _delete_device_file(self, name: str) -> bool:
        if not SAFE_DEVICE_FILE_RE.fullmatch(name.split(":")[-1].lstrip("/")):
            return False  # only files this adapter creates are ever deleted
        try:
            output = self._run(f"delete /force {name}", self._timeout)
            if ERROR_RE.search(output):
                return False
            listing = self._require().send_command(
                f"dir {name}", read_timeout=self._timeout
            )
            basename = name.split(":")[-1].lstrip("/")
            if ERROR_RE.search(listing):
                if not re.search(
                    r"no such file|does not exist|not found", listing, re.IGNORECASE
                ):
                    return False
            elif basename in listing:
                return False
        except AdapterError:
            return False
        except Exception:
            return False
        if name in self._device_files:
            self._device_files.remove(name)
        return True

    # ------------------------------------------------------------------ files
    def _file_names(self, ctx: RestoreContext) -> Tuple[str, str, str]:
        job = int(ctx.job_id)
        # the precheck and the execution run in different sessions and contexts: the
        # file system found by one is not known to the other, so ask the device again
        fs = ctx.scratch.get("cisco_fs", "")
        if not fs:
            info = parse_dir(self._show("dir", ctx))
            fs = info.filesystem if info else ""
            ctx.scratch["cisco_fs"] = fs
        if not FILESYSTEM_RE.match(fs):
            raise AdapterError("the device file system is not known")
        return fs, f"{FILE_PREFIX}{job}-target.cfg", f"{FILE_PREFIX}{job}-pre.cfg"

    def _upload(self, fs: str, name: str, text: str) -> None:
        transfer = self._transfer
        if transfer is None:
            from netmiko import file_transfer as transfer  # lazy
        fd, path = tempfile.mkstemp(prefix="nabs-restore-", suffix=".cfg")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text if text.endswith("\n") else text + "\n")
            self._device_files.append(f"{fs}{name}")
            result = transfer(
                self._require(),
                source_file=path,
                dest_file=name,
                file_system=fs,
                direction="put",
                overwrite_file=True,
            )
        except AdapterError:
            raise
        except Exception as error:
            translated = _translate(error)
            if isinstance(translated, (ConnectionLost, AdapterTimeout)):
                raise translated from None
            # the text of an SCP/transfer error comes from the device or the client and
            # carries no credentials; the engine scrubs the password from messages anyway
            detail = " ".join(str(error).split())[:200]
            raise AdapterError(
                f"{type(error).__name__}: {detail}" if detail else type(error).__name__
            ) from None
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if not (isinstance(result, dict) and result.get("file_verified")):
            raise AdapterError("the file was not transferred or its checksum differs")

    def normalize_for_diff(self, text: str) -> str:
        """
        No `show running-config` header, no always-changing timestamp comments and no bare
        `!` separator lines (they carry no meaning and shift with the capture).
        """
        lines = [
            ln
            for ln in strip_show_header(text).split("\n")
            if ln.strip() != "!" and not VOLATILE_COMMENT_RE.match(ln.strip())
        ]
        return "\n".join(lines).rstrip() + "\n"

    # ---------------------------------------------------------------- handlers
    def check_platform_support(self, ctx: RestoreContext) -> ActionResult:
        info = parse_show_version(self._show("show version", ctx))
        if info is None:
            return ActionResult.unknown("the platform could not be recognised")
        if info.family not in ("ios", "iosxe"):
            return ActionResult.failure(f"unsupported platform: {info.family}")
        device_type = ctx.profile.adapter_device_type
        if device_type and device_type not in DEVICE_TYPES:
            return ActionResult.failure(f"unsupported device_type {device_type!r}")
        ctx.scratch["cisco_platform"] = info
        return ActionResult.success(
            f"{info.family} {info.version or ''}".strip(),
            details={"family": info.family, "version": info.version},
        )

    def check_connectivity(self, ctx: RestoreContext) -> ActionResult:
        try:
            prompt = self._require().find_prompt()
        except AdapterError:
            raise
        except Exception as error:
            raise _translate(error) from None
        if prompt.endswith("#"):
            return ActionResult.success("privileged mode")
        if prompt.endswith(">"):
            return ActionResult.failure(
                "the account is not in privileged mode (privilege level 15 is required)"
            )
        return ActionResult.unknown("unrecognised prompt")

    def fetch_current_config(self, ctx: RestoreContext) -> ActionResult:
        text = strip_show_header(self._show("show running-config", ctx))
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if len(lines) < 5 or lines[-1].lower() != "end":
            return ActionResult.failure(
                "the running configuration looks incomplete (no final 'end')"
            )
        ctx.scratch["cisco_current_len"] = len(text)
        ctx.scratch["cisco_current_lines"] = len(
            lines
        )  # set here, not taken from the engine
        ctx.scratch["cisco_scp_enabled"] = any(
            ln == "ip scp server enable" for ln in lines
        )
        ctx.scratch["cisco_aaa_without_exec"] = "aaa new-model" in lines and not any(
            ln.startswith("aaa authorization exec") for ln in lines
        )
        return ActionResult.success(f"{len(lines)} lines", payload=text)

    def check_rollback_available(self, ctx: RestoreContext) -> ActionResult:
        info = parse_dir(self._show("dir", ctx))
        if info is None:
            return ActionResult.unknown("the device file system could not be read")
        needed = (
            2 * (ctx.scratch.get("cisco_current_len", 0) + len(ctx.target_config))
            + SPACE_MARGIN_BYTES
        )
        if info.free < needed:
            return ActionResult.failure(
                f"not enough free space on {info.filesystem}: {info.free} bytes free,"
                f" about {needed} needed for the rollback copy and the target file"
            )
        ctx.scratch["cisco_fs"] = info.filesystem
        return ActionResult.success(
            f"rollback copy fits on {info.filesystem}",
            details={"filesystem": info.filesystem, "free": info.free},
        )

    def validate_target_config(self, ctx: RestoreContext) -> ActionResult:
        target_text = target_for_device(ctx.target_config)
        lines = [ln for ln in target_text.splitlines() if ln.strip()]
        warnings: List[str] = []
        if not lines or lines[-1].strip().lower() != "end":
            return ActionResult.failure(
                "the stored configuration has no final 'end': configure replace would reject it"
            )
        if not any(ln.lower().startswith("version ") for ln in lines):
            warnings.append(
                "the stored configuration has no 'version' line: IOS may reject the replace"
            )
        # A custom driver may have stored the output of ANY command (for example a filtered
        # `show run | ...`): replacing a complete configuration with a partial one would
        # wipe the rest. A much shorter target than the current configuration is refused.
        current_lines = int(ctx.scratch.get("cisco_current_lines") or 0)
        if current_lines and len(lines) < 0.5 * current_lines:
            return ActionResult.failure(
                f"the stored configuration has {len(lines)} lines but the device has"
                f" {current_lines}: it looks partial, and replacing would delete the rest"
                " (check what the custom driver's last command returns)"
            )
        if ctx.scratch.get("cisco_scp_enabled") is False:
            return ActionResult.failure(
                "the SCP server is not enabled on the device: the running configuration has"
                " no 'ip scp server enable' line (needed to upload the file for the replace)"
            )
        fs, target, _pre = self._file_names(ctx)
        try:
            self._upload(fs, target, target_text)
        except AdapterError as error:
            if isinstance(error, (ConnectionLost, AdapterTimeout)):
                raise
            hint = (
                "; the device uses AAA but has no 'aaa authorization exec' line, which SCP needs"
                if ctx.scratch.get("cisco_aaa_without_exec")
                else "; check the SCP/AAA settings of the device (ip scp server enable,"
                " aaa authorization exec, privilege 15) and the free space"
            )
            return ActionResult.failure(
                f"the target file could not be uploaded to the device ({error}){hint}"
            )
        output = self._show(
            f"show archive config differences system:running-config {fs}{target}", ctx
        )
        if ERROR_RE.search(output):
            return ActionResult.failure(
                "the device could not compare the configurations"
            )
        diff = parse_diff(output)
        if diff is None:
            return ActionResult.unknown("the comparison output could not be understood")

        ip = ctx.device.ip
        ip_pattern = re.compile(
            rf"^\s*ip\s+address\s+{re.escape(ip)}(\s|$)", re.IGNORECASE
        )
        if any(ip_pattern.match(line) for line in diff.removed):
            return ActionResult.failure(
                f"the restore would remove the management address {ip} of this device:"
                " the connection would be lost"
            )
        risky = [ln for ln in diff.removed if RISKY_REMOVAL_RE.match(ln)]
        if risky:
            warnings.append(
                f"the restore removes or changes {len(risky)} line(s) that can affect remote"
                " access (users, AAA, SSH, vty, default route)"
            )
        if current_lines and len(diff.removed) >= 0.2 * current_lines:
            warnings.append(
                f"the restore removes {len(diff.removed)} of the {current_lines} lines the"
                " device has now: make sure the stored configuration is a complete"
                " running-config"
            )
        if diff.identical:
            warnings.append("the device already has this configuration")
        return ActionResult.success(
            f"+{len(diff.added)} / -{len(diff.removed)} lines differ",
            details={"added": len(diff.added), "removed": len(diff.removed)},
            warnings=tuple(warnings),
        )

    def apply_saved_config(self, ctx: RestoreContext) -> ActionResult:
        timeout = ctx.profile.limits["operation_timeout"]
        fs, target, pre = self._file_names(ctx)

        # 1. the rollback source, made by the device itself (exact, banners/certs intact)
        self._device_files.append(f"{fs}{pre}")
        out = self._run(f"copy running-config {fs}{pre}", timeout)
        if ERROR_RE.search(out) or "bytes copied" not in out.lower():
            return ActionResult.failure(
                "the rollback copy could not be made; nothing was changed"
            )
        # 2. the target file
        try:
            self._upload(fs, target, target_for_device(ctx.target_config))
        except (ConnectionLost, AdapterTimeout):
            raise
        except AdapterError as error:
            return ActionResult.failure(
                f"the target file could not be uploaded ({error});"
                " nothing was changed"
            )
        ctx.scratch["device_pre_file"] = f"{fs}{pre}"
        self._keep_files = True  # from here on both files are the evidence

        # 3. the replace
        return self._interpret_replace(
            self._run(f"configure replace {fs}{target} force", timeout)
        )

    @staticmethod
    def _interpret_replace(output: str) -> ActionResult:
        if ERROR_RE.search(output):
            return ActionResult.failure("the device reported an error for the replace")
        if "Rollback Done" in output or "Total number of passes" in output:
            return ActionResult.success("commands accepted (not yet verified)")
        return ActionResult.unknown(
            "the output of the replace could not be interpreted"
        )

    def verify_management_access(self, ctx: RestoreContext) -> ActionResult:
        attempts = int(ctx.params.get("attempts", 3))
        wait = int(ctx.params.get("wait_seconds", 10))
        if self._device is None or self._credentials is None:
            raise ConnectionLost("not connected")
        for attempt in range(1, attempts + 1):
            deadline = ctx.scratch.get("_restore_verify_deadline")
            remaining = deadline - time.monotonic() if deadline is not None else None
            if remaining is not None and remaining <= 0:
                return ActionResult.failure(
                    "verification timed out while waiting for management access"
                )
            self._sleep(min(wait, remaining) if remaining is not None else wait)
            remaining = deadline - time.monotonic() if deadline is not None else None
            if remaining is not None and remaining <= 0:
                return ActionResult.failure(
                    "verification timed out while waiting for management access"
                )
            fresh = None
            try:
                connect_timeout = self._timeout
                if remaining is not None:
                    connect_timeout = max(1, min(connect_timeout, int(remaining)))
                fresh = self._open(self._device, self._credentials, connect_timeout)
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

    def _compare(self, running: str, expected: str, mode: str) -> Tuple[bool, int, int]:
        a = normalize_config(running, self._ignore, mode)
        b = normalize_config(expected, self._ignore, mode)
        if a == b:
            return True, 0, 0
        sa, sb = _line_set(a), _line_set(b)
        return False, len(sb - sa), len(sa - sb)

    def verify_running_config(self, ctx: RestoreContext) -> ActionResult:
        mode = str(ctx.params.get("compare", "normalized"))
        running = strip_show_header(self._show("show running-config", ctx))
        same, missing, extra = self._compare(running, ctx.target_config, mode)
        if same:
            return ActionResult.success("the running configuration matches the target")
        # counts only: configuration lines may hold secrets and must not reach the journal
        return ActionResult.failure(
            f"the running configuration differs from the target ({missing} line(s)"
            f" missing, {extra} unexpected)",
            details={"missing": missing, "unexpected": extra},
        )

    def persist_config(self, ctx: RestoreContext) -> ActionResult:
        out = self._run("write memory", ctx.profile.limits["operation_timeout"])
        if ERROR_RE.search(out):
            return ActionResult.failure("the device reported an error while saving")
        if "[OK]" in out:
            return ActionResult.success("saved to startup-config")
        return ActionResult.unknown(
            "the result of 'write memory' could not be interpreted"
        )

    # ---------------------------------------------------------------- rollback
    def rollback(self, ctx: RestoreContext) -> ActionResult:
        pre = ctx.scratch.get("device_pre_file")
        if not pre or not SAFE_DEVICE_FILE_RE.match(pre.split(":")[-1].lstrip("/")):
            return ActionResult.failure("there is no rollback copy on the device")
        result = self._interpret_replace(
            self._run(
                f"configure replace {pre} force",
                ctx.profile.limits["operation_timeout"],
            )
        )
        if result.ok:
            return ActionResult.success("rollback commands accepted (not yet verified)")
        return result

    def verify_rollback(self, ctx: RestoreContext) -> ActionResult:
        expected = ctx.scratch.get("pre_restore_config")
        if not expected:
            return ActionResult.unknown("there is no stored copy to compare with")
        running = strip_show_header(self._show("show running-config", ctx))
        same, missing, extra = self._compare(running, expected, "normalized")
        if same:
            return ActionResult.success("the previous configuration is confirmed")
        return ActionResult.failure(
            f"the previous configuration is not restored ({missing} line(s) missing,"
            f" {extra} unexpected)",
            details={"missing": missing, "unexpected": extra},
        )


# OPEN POINTS - to settle on hardware before this adapter may be called supported
#  1. The exact output of `configure replace ... force` on each IOS / IOS XE release
#     (success and failure wording); the interpretation above follows the documentation.
#  2. Whether a stored (cleaned) configuration is accepted by `configure replace`:
#     banners, self-signed certificates and indentation are known trouble spots.
#  3. `show archive config differences` with `system:running-config` as the first file:
#     availability and output format per release.
#  4. SCP upload prerequisites (`ip scp server enable`, AAA) and `file prompt` behaviour.
#  5. The unit and behaviour of `configure replace ... time` (a device-side revert timer
#     would protect against a lost session; it is deliberately not used yet).
#  6. Behaviour of the session when the replace changes the management interface.
