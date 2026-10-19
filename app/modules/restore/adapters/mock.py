"""
Scriptable in-memory adapter for tests of the engine (no equipment involved).

It is NOT registered in production: adapters.adapter_classes() returns it only with
include_mock=True, so a profile naming adapter type "mock" can never run for real.
"""

from typing import Any, Dict, List, Optional

from app.modules.restore.adapters.base import (
    ActionResult,
    Credentials,
    DeviceInfo,
    RestoreAdapter,
    RestoreContext,
)


def normalize_config(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip())


class MockAdapter(RestoreAdapter):
    type = "mock"

    def __init__(
        self,
        running_config: str = "",
        script: Optional[Dict[str, Any]] = None,
        apply_effect_before_error: bool = False,
    ) -> None:
        """
        script: {handler name: ActionResult | Exception instance | callable(ctx)}
          overrides the default behaviour of that handler (exceptions are raised).
        apply_effect_before_error: if apply is scripted to raise, still change the
          config first (a device that applied the config and then dropped the session).
        """
        self.running_config = running_config
        self.saved_config = running_config
        self.script = dict(script or {})
        self.apply_effect_before_error = apply_effect_before_error
        self.calls: List[str] = []
        self.params: Dict[
            str, Dict[str, Any]
        ] = {}  # handler name -> params it received
        self.connected = False
        self.closed = False

    def _scripted(self, name: str, ctx=None):
        self.calls.append(name)
        if ctx is not None:
            self.params[name] = dict(ctx.params)
        behaviour = self.script.get(name)
        if behaviour is None:
            return None
        if isinstance(behaviour, BaseException):
            raise behaviour
        if callable(behaviour):
            return behaviour(ctx)
        return behaviour

    def connect(
        self, device: DeviceInfo, credentials: Credentials, connect_timeout: int
    ) -> None:
        self._scripted("connect")
        self.connected = True

    def close(self) -> None:
        self.calls.append("close")
        self.connected = False
        self.closed = True

    def check_platform_support(self, ctx: RestoreContext) -> ActionResult:
        return self._scripted("check_platform_support", ctx) or ActionResult.success(
            "supported"
        )

    def check_connectivity(self, ctx: RestoreContext) -> ActionResult:
        scripted = self._scripted("check_connectivity", ctx)
        if scripted:
            return scripted
        if self.connected:
            return ActionResult.success("connected")
        return ActionResult.failure("not connected")

    def fetch_current_config(self, ctx: RestoreContext) -> ActionResult:
        return self._scripted("fetch_current_config", ctx) or ActionResult.success(
            "read", payload=self.running_config
        )

    def check_rollback_available(self, ctx: RestoreContext) -> ActionResult:
        return self._scripted("check_rollback_available", ctx) or ActionResult.success(
            "available"
        )

    def validate_target_config(self, ctx: RestoreContext) -> ActionResult:
        scripted = self._scripted("validate_target_config", ctx)
        if scripted:
            return scripted
        if not ctx.target_config.strip():
            return ActionResult.failure("target configuration is empty")
        return ActionResult.success("valid")

    def apply_saved_config(self, ctx: RestoreContext) -> ActionResult:
        try:
            scripted = self._scripted("apply_saved_config", ctx)
        except Exception:
            if self.apply_effect_before_error:
                self.running_config = ctx.target_config
            raise
        if scripted:
            if scripted.ok:
                self.running_config = ctx.target_config
            return scripted
        self.running_config = ctx.target_config
        # commands accepted is NOT success: the engine must still verify
        return ActionResult.success("commands accepted")

    def verify_management_access(self, ctx: RestoreContext) -> ActionResult:
        return self._scripted("verify_management_access", ctx) or ActionResult.success(
            "reachable"
        )

    def verify_running_config(self, ctx: RestoreContext) -> ActionResult:
        scripted = self._scripted("verify_running_config", ctx)
        if scripted:
            return scripted
        if normalize_config(self.running_config) == normalize_config(ctx.target_config):
            return ActionResult.success("running config matches the target")
        return ActionResult.failure("running config differs from the target")

    def persist_config(self, ctx: RestoreContext) -> ActionResult:
        scripted = self._scripted("persist_config", ctx)
        if scripted:
            return scripted
        self.saved_config = self.running_config
        return ActionResult.success("saved")

    def rollback(self, ctx: RestoreContext) -> ActionResult:
        scripted = self._scripted("rollback", ctx)
        if scripted:
            return scripted
        self.running_config = ctx.scratch["pre_restore_config"]
        return ActionResult.success("rollback commands accepted")

    def verify_rollback(self, ctx: RestoreContext) -> ActionResult:
        scripted = self._scripted("verify_rollback", ctx)
        if scripted:
            return scripted
        same = normalize_config(self.running_config) == normalize_config(
            ctx.scratch["pre_restore_config"]
        )
        if same:
            return ActionResult.success("previous configuration confirmed")
        return ActionResult.failure("previous configuration not restored")
