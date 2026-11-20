"""
Platform adapter interface.

An adapter implements the REAL operations on one kind of equipment. A handler returns
Verdict.OK only with positive evidence (e.g. the config was read back and compared),
never merely because commands were sent without an exception. Whatever it cannot
establish is Verdict.UNKNOWN; an operation it does not implement raises
UnsupportedOperation, and the engine then refuses scenarios that need it.

supported_actions() is derived from the handlers a subclass really overrides, so the
declared capabilities cannot drift from the code.
"""

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json

from typing import Any, ClassVar, Dict, FrozenSet, Optional, Tuple

from app.modules.restore.schema import RestoreProfile

# profile action -> adapter method that implements it
ACTION_HANDLERS: Dict[str, str] = {
    "check_platform_support": "check_platform_support",
    "check_connectivity": "check_connectivity",
    "fetch_current_config": "fetch_current_config",
    "check_rollback_available": "check_rollback_available",
    "validate_target_config": "validate_target_config",
    "apply_saved_config": "apply_saved_config",
    "verify_management_access": "verify_management_access",
    "verify_running_config": "verify_running_config",
    "persist_config": "persist_config",
}


class AdapterError(Exception):
    """Base class of adapter errors."""


class CandidateCleanupUncertain(AdapterError):
    """The device may still hold configuration staged by a restore operation."""


class UnsupportedOperation(AdapterError):
    """The adapter does not implement this operation."""


class AdapterConnectionError(AdapterError):
    """Could not connect/log in (nothing has been changed yet)."""


class AuthenticationFailed(AdapterConnectionError):
    pass


class ConnectionLost(AdapterError):
    """The session dropped. During/after apply the result is UNKNOWN, never a retry."""


class AdapterTimeout(AdapterError):
    pass


class CommandRejected(AdapterError):
    """The device refused a command."""


def translate_exception(error: BaseException) -> "AdapterError":
    """Map a Netmiko / paramiko / socket exception to the adapter's own exceptions."""
    names = {cls.__name__ for cls in type(error).__mro__}
    if any("Authentication" in n for n in names):
        return AuthenticationFailed("authentication failed")
    if names & {"ReadTimeout", "NetmikoTimeoutException", "TimeoutError", "timeout"}:
        return AdapterTimeout(f"timed out ({type(error).__name__})")
    if isinstance(error, (OSError, EOFError)) or any(
        "SSH" in n or "Connection" in n for n in names
    ):
        return ConnectionLost(f"session lost ({type(error).__name__})")
    return AdapterError(f"{type(error).__name__}")


class Verdict(str, Enum):
    OK = "ok"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ActionResult:
    verdict: Verdict
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    payload: Optional[str] = None  # e.g. the current config text
    warnings: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.verdict is Verdict.OK

    @classmethod
    def success(cls, message="", **kw) -> "ActionResult":
        return cls(Verdict.OK, message, **kw)

    @classmethod
    def failure(cls, message, **kw) -> "ActionResult":
        return cls(Verdict.FAILED, message, **kw)

    @classmethod
    def unknown(cls, message, **kw) -> "ActionResult":
        return cls(Verdict.UNKNOWN, message, **kw)


@dataclass(frozen=True)
class DeviceInfo:
    device_id: int
    ip: str
    hostname: Optional[str]
    # platform id: the NAPALM driver name, or for a custom-driver device the Netmiko
    # device type of its custom driver (never the numeric custom driver id)
    driver: Optional[str]
    port: Optional[int] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    os_version: Optional[str] = None
    # Netmiko device type of a device that uses a NABS custom driver (None for NAPALM ones)
    netmiko_device_type: Optional[str] = None
    # Detected platform generation (for example VRP 5.170 vs 8.220).
    os_generation: Optional[str] = None


@dataclass(frozen=True)
class Credentials:
    """Device login. Its repr/str never contain the password (logs, tracebacks)."""

    username: Optional[str]
    password: Optional[str] = field(default=None, repr=False)

    def __repr__(self) -> str:
        return f"Credentials(username={self.username!r}, password=***)"

    __str__ = __repr__


def device_identity(device: DeviceInfo) -> str:
    data = [device.ip, device.port or 22, device.driver, device.netmiko_device_type]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()


@dataclass
class RestoreContext:
    job_id: int
    device: DeviceInfo
    profile: RestoreProfile
    target_config: str
    # data passed between steps (current config, pre-restore config, ...)
    scratch: Dict[str, Any] = field(default_factory=dict)
    # parameters of the step being run (defaults of the action + the profile's values)
    params: Dict[str, Any] = field(default_factory=dict)


class RestoreAdapter:
    type: ClassVar[str] = ""
    # False until the adapter has been proven on real equipment of the platforms it
    # claims; unverified adapters are off unless an administrator enables them
    verified: ClassVar[bool] = True

    def normalize_for_diff(self, text: str) -> str:
        """
        The text as it should be compared in the diff shown to the user: an adapter drops
        what only reflects HOW a configuration was captured (headers, timestamp comments)
        so that the diff shows real differences only. Default: unchanged.
        """
        return text

    @classmethod
    def create(cls, ignore_patterns=()) -> "RestoreAdapter":
        """Factory used by the worker (ignore_patterns: NABS `clear_patterns`)."""
        return cls()

    # ---- session
    def connect(
        self, device: DeviceInfo, credentials: Credentials, connect_timeout: int
    ) -> None:
        raise UnsupportedOperation("connect")

    def close(self) -> Tuple[str, ...]:
        return ()

    def finalize(self, outcome_status: str) -> Tuple[str, ...]:
        """Release device-side temporary files only after a known safe terminal outcome.

        Adapters that create remote rollback/target files override this method. Unknown or
        unsuccessful outcomes must preserve evidence for an operator; `close()` alone must
        never delete files needed to recover a device.
        """
        return ()

    def __enter__(self) -> "RestoreAdapter":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ---- profile actions (see ACTION_HANDLERS)
    def check_platform_support(self, ctx: RestoreContext) -> ActionResult:
        raise UnsupportedOperation("check_platform_support")

    def check_connectivity(self, ctx: RestoreContext) -> ActionResult:
        raise UnsupportedOperation("check_connectivity")

    def fetch_current_config(self, ctx: RestoreContext) -> ActionResult:
        raise UnsupportedOperation("fetch_current_config")

    def check_rollback_available(self, ctx: RestoreContext) -> ActionResult:
        raise UnsupportedOperation("check_rollback_available")

    def validate_target_config(self, ctx: RestoreContext) -> ActionResult:
        raise UnsupportedOperation("validate_target_config")

    def apply_saved_config(self, ctx: RestoreContext) -> ActionResult:
        raise UnsupportedOperation("apply_saved_config")

    def verify_management_access(self, ctx: RestoreContext) -> ActionResult:
        raise UnsupportedOperation("verify_management_access")

    def verify_running_config(self, ctx: RestoreContext) -> ActionResult:
        raise UnsupportedOperation("verify_running_config")

    def persist_config(self, ctx: RestoreContext) -> ActionResult:
        raise UnsupportedOperation("persist_config")

    # ---- rollback (run by the engine on failure, never as a profile step)
    def rollback(self, ctx: RestoreContext) -> ActionResult:
        raise UnsupportedOperation("rollback")

    def verify_rollback(self, ctx: RestoreContext) -> ActionResult:
        raise UnsupportedOperation("verify_rollback")

    # ---- capabilities
    @classmethod
    def _overridden(cls, method: str) -> bool:
        return getattr(cls, method) is not getattr(RestoreAdapter, method)

    @classmethod
    def supported_actions(cls) -> FrozenSet[str]:
        return frozenset(
            action
            for action, method in ACTION_HANDLERS.items()
            if cls._overridden(method)
        )

    @classmethod
    def supports_rollback(cls) -> bool:
        return cls._overridden("rollback") and cls._overridden("verify_rollback")
