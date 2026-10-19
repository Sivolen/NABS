"""
Pieces shared by the Huawei adapters (CloudEngine: huawei_ce, S-series: huawei_s).

NOT VERIFIED ON HARDWARE, like the Cisco adapter: written from Huawei's documentation
(CloudEngine 9800/8800/6800 V300R024C00 command reference, S-series V200R011C10 / V200R019C10
guides) and tested against a simulated device only.
"""

import os
import re
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

from app.modules.restore.adapters.base import (
    AdapterConnectionError,
    AdapterError,
    AdapterTimeout,
    AuthenticationFailed,
    ConnectionLost,
    Credentials,
    DeviceInfo,
    translate_exception,
)

# Huawei prompts: <HUAWEI> (user view), [HUAWEI] / [~HUAWEI] / [*HUAWEI] (system view; the ~/*
# of a CloudEngine in two-phase mode say "committed" / "uncommitted"), and Y/N questions
PROMPT_BODY = r"<[^<>\r\n]+>|\[[~*]?[^\[\]\r\n]+\]"
QUESTION_BODY = r"\[Y/N\]\s*:?|\(y/n\)\s*\[[yn]\]\s*:?"
DONE_PATTERN = rf"(?:{PROMPT_BODY}|{QUESTION_BODY})\s*$"
QUESTION_RE = re.compile(rf"(?:{QUESTION_BODY})\s*$", re.IGNORECASE)
PROMPT_LINE_RE = re.compile(rf"^(?:{PROMPT_BODY})\s*$")
MAX_QUESTIONS = 4

SAFE_FILE_RE = re.compile(r"^nabs-restore-\d+-(target|pre)\.cfg$")

ERROR_RE = re.compile(
    r"(^\s*Error\b|^\s*Info: .*(fail|error)|unrecognized command|wrong parameter|too many parameters"
    r"|incomplete command|ambiguous command|\bfailed\b|does not exist|not exist)",
    re.IGNORECASE | re.MULTILINE,
)

# lines a restore must not take away without the operator noticing (warnings)
RISKY_REMOVAL_RE = re.compile(
    r"^\s*(local-user |ssh user |ssh server|stelnet server|sftp server|user-interface vty|"
    r"authentication-mode|protocol inbound|ip route-static 0\.0\.0\.0|snmp-agent|aaa$)",
    re.IGNORECASE,
)

DEVICE_TYPES = ("huawei", "huawei_vrp")


class UnexpectedPrompt(AdapterError):
    """The device asked a question the adapter has no safe answer for (it answered 'n')."""


@dataclass(frozen=True)
class PlatformInfo:
    family: str  # "ce" | "s" | "other"
    vrp_version: Optional[str]
    model: Optional[str]
    software: Optional[str]


def normalize_platform(platform: Optional[str]) -> str:
    text = (platform or "").strip().lower()
    return text[: -len("_ssh")] if text.endswith("_ssh") else text


def parse_display_version(text: str) -> Optional[PlatformInfo]:
    m = re.search(
        r"VRP\s*\(R\)\s*software,\s*Version\s+([\w.]+)(?:\s*\(\s*(\S+)\s+(V\d+R\d+C\d+\w*)\s*\))?",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    model = m.group(2)
    upper = (model or "").upper()
    if upper.startswith("CE"):
        family = "ce"
    elif re.match(r"^S\d", upper):
        family = "s"
    else:
        family = "other"
    return PlatformInfo(family, m.group(1), model, m.group(3))


def parse_free_bytes(text: str) -> Optional[int]:
    m = re.search(
        r"([\d,]+)\s*(KB|MB|GB)?\s*total\s*\(\s*([\d,]+)\s*(KB|MB|GB)?\s*free\s*\)",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    units = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}
    unit = units.get((m.group(4) or m.group(2) or "KB").upper(), 1024)
    return int(m.group(3).replace(",", "")) * unit


def parse_startup(text: str) -> Tuple[Optional[str], Optional[str]]:
    """(current startup file, next startup file) as written by `display startup`."""
    current = re.search(
        r"^\s*Startup saved-configuration file:\s*(\S+)", text, re.I | re.M
    )
    nxt = re.search(
        r"^\s*Next startup saved-configuration file:\s*(\S+)", text, re.I | re.M
    )
    return (current.group(1) if current else None, nxt.group(1) if nxt else None)


def basename(path: Optional[str]) -> str:
    return re.split(r"[/:]", path or "")[-1].strip().lower()


def clean_output(text: str) -> str:
    """Drop the prompt line(s) at the end of an output."""
    lines = text.replace("\r\n", "\n").split("\n")
    while lines and (not lines[-1].strip() or PROMPT_LINE_RE.match(lines[-1].strip())):
        lines.pop()
    return "\n".join(lines)


def normalize_config(
    text: str, ignore_patterns: Sequence[str] = (), mode: str = "normalized"
) -> str:
    """
    exact:      only trailing whitespace and blank lines are ignored
    normalized: also `!` comment lines (software version, time of the last change), the bare
                `#` separators and NABS clear_patterns
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
        if mode == "normalized" and (
            line.lstrip().startswith("!") or line.strip() == "#"
        ):
            continue
        out.append(line)
    return "\n".join(out)


def diff_view(text: str) -> str:
    return normalize_config(text, (), "normalized") + "\n"


def line_set(text: str) -> set:
    return set(text.split("\n"))


# ------------------------------------------------------------------------------ commands
def _send(conn: Any, command: str, timeout: int, **extra: Any) -> str:
    return conn.send_command(
        command,
        expect_string=DONE_PATTERN,
        read_timeout=timeout,
        strip_prompt=False,
        **extra,
    )


def bounded_timeout(ctx: Any, fallback: int) -> int:
    """Clamp a command timeout to the remaining aggregate verification budget."""
    deadline = getattr(ctx, "scratch", {}).get("_restore_verify_deadline")
    if deadline is None:
        return max(1, int(fallback))
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AdapterTimeout("the configured verification timeout expired")
    return max(1, min(int(fallback), int(remaining)))


def remaining_verify_seconds(ctx: Any) -> Optional[float]:
    deadline = getattr(ctx, "scratch", {}).get("_restore_verify_deadline")
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


def show(conn: Any, command: str, timeout: int) -> str:
    try:
        return clean_output(_send(conn, command, timeout))
    except AdapterError:
        raise
    except Exception as error:
        raise translate_exception(error) from None


def run_interactive(
    conn: Any, command: str, rules: Sequence[Tuple[str, str]], timeout: int
) -> str:
    """
    Send a command and answer its Y/N questions ONLY as `rules` say ((regex, reply), first
    match wins). A question without a rule is answered 'n' and raises UnexpectedPrompt: an
    unknown question is never confirmed.
    """
    try:
        out = _send(conn, command, timeout)
        for _ in range(MAX_QUESTIONS):
            tail = out[-500:]
            if not QUESTION_RE.search(tail):
                return clean_output(out)
            reply = next(
                (
                    a
                    for pattern, a in rules
                    if re.search(pattern, tail, re.IGNORECASE | re.DOTALL)
                ),
                None,
            )
            if reply is None:
                _send(conn, "n", timeout, cmd_verify=False)
                raise UnexpectedPrompt(" ".join(tail.split())[-200:])
            out += _send(conn, reply, timeout, cmd_verify=False)
        raise UnexpectedPrompt("too many questions from the device")
    except AdapterError:
        raise
    except Exception as error:
        raise translate_exception(error) from None


def delete_file(conn: Any, name: str, timeout: int) -> bool:
    """Delete one of OUR files; return False unless the command was safely accepted.

    Only the exact per-job filename format is allowed. A failed cleanup is surfaced to the
    caller so the job journal can record it; callers must not claim that the file was removed.
    """
    if not SAFE_FILE_RE.fullmatch(name):
        return False
    try:
        output = run_interactive(
            conn, f"delete {name}", [(r"delete|recycled|continue", "y")], timeout
        )
        if ERROR_RE.search(output):
            return False
        # A delete prompt can return to the CLI without a success message. Verify absence
        # rather than treating a returned prompt as proof that the file was removed.
        listing = show(conn, f"dir {name}", timeout)
        return name not in listing
    except AdapterError:
        return False


# -------------------------------------------------------------------------------- transfer
def default_sftp(conn: Any):
    return conn.remote_conn_pre.open_sftp()


def sftp_put(
    conn: Any,
    text: str,
    remote_name: str,
    factory: Optional[Callable[[Any], Any]] = None,
) -> None:
    """Upload text as a file into the SFTP root of the account (a temp file, mode 0600)."""
    body = text if text.endswith("\n") else text + "\n"
    fd, path = tempfile.mkstemp(prefix="nabs-restore-", suffix=".cfg")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
        client = (factory or default_sftp)(conn)
        try:
            client.put(path, remote_name)
            size = client.stat(remote_name).st_size
        finally:
            try:
                client.close()
            except Exception:
                pass
    except AdapterError:
        raise
    except Exception as error:
        translated = translate_exception(error)
        if isinstance(translated, (ConnectionLost, AdapterTimeout)):
            raise translated from None
        detail = " ".join(str(error).split())[:200]
        raise AdapterError(
            f"{type(error).__name__}: {detail}" if detail else type(error).__name__
        ) from None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if size != len(body.encode("utf-8")):
        raise AdapterError("the uploaded file has a different size than the original")


def open_connection(
    factory: Optional[Callable[..., Any]],
    device: DeviceInfo,
    credentials: Credentials,
    timeout: int,
) -> Any:
    if factory is None:
        from netmiko import ConnectHandler  # lazy: only a real connection needs it

        factory = ConnectHandler
    try:
        return factory(
            device_type=(
                device.netmiko_device_type
                if normalize_platform(device.netmiko_device_type) in DEVICE_TYPES
                else "huawei"
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
        translated = translate_exception(error)
        if isinstance(translated, AuthenticationFailed):
            raise translated from None
        raise AdapterConnectionError(
            f"cannot connect ({type(error).__name__})"
        ) from None


# ------------------------------------------------------------------------ text checks
def check_target_text(
    target_text: str, current_lines: int, current_text: str, ip: str
) -> Optional[str]:
    """A reason to refuse the stored configuration, or None (shared by both adapters)."""
    lines = [ln for ln in target_text.splitlines() if ln.strip()]
    if not lines or lines[-1].strip().lower() != "return":
        return (
            "the stored configuration does not end with 'return': it looks incomplete"
            " (the last command of the custom driver must print the whole configuration)"
        )
    if current_lines and len(lines) < 0.5 * current_lines:
        return (
            f"the stored configuration has {len(lines)} lines but the device has"
            f" {current_lines}: it looks partial, and replacing would delete the rest"
        )
    pattern = re.compile(
        rf"^\s*ip address {re.escape(ip)}(\s|$)", re.IGNORECASE | re.MULTILINE
    )
    if (
        current_text
        and pattern.search(current_text)
        and not pattern.search(target_text)
    ):
        return (
            f"the restore would remove the management address {ip} of this device:"
            " the connection would be lost"
        )
    return None


def removed_lines(current_text: str, target_text: str) -> List[str]:
    target = line_set(normalize_config(target_text))
    return [ln for ln in normalize_config(current_text).split("\n") if ln not in target]
