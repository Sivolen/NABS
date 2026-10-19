"""
Catalog of the actions a restore profile may reference.

A profile is DATA: it can only name actions from this catalog and pass the
parameters declared here. What an action really does is implemented in code
(the engine or a platform adapter). Being listed here does NOT mean a platform
supports the action: that is checked separately against the adapter
(schema.check_adapter_capabilities).
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# The order in which phases may appear in a profile (a step can never go back)
PHASES: Tuple[str, ...] = ("precheck", "prepare", "apply", "verify", "persist")


@dataclass(frozen=True)
class ParamSpec:
    type: type  # str, int or bool
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    choices: Optional[Tuple[str, ...]] = None
    default: object = None


@dataclass(frozen=True)
class ActionSpec:
    name: str
    phase: str
    # changes the device: the engine must have finished prechecks/backup first
    mutating: bool = False
    # may be marked `required: false` in a profile (an explicit, visible choice)
    skippable: bool = False
    params: Dict[str, ParamSpec] = field(default_factory=dict)


def _specs(*items: ActionSpec) -> Dict[str, ActionSpec]:
    return {item.name: item for item in items}


ACTIONS: Dict[str, ActionSpec] = _specs(
    ActionSpec("check_platform_support", "precheck"),
    ActionSpec("check_connectivity", "precheck"),
    ActionSpec("fetch_current_config", "precheck", skippable=True),
    ActionSpec("check_rollback_available", "precheck", skippable=True),
    ActionSpec("save_pre_restore_backup", "prepare"),
    ActionSpec("validate_target_config", "prepare"),
    ActionSpec("apply_saved_config", "apply", mutating=True),
    ActionSpec(
        "verify_management_access",
        "verify",
        params={
            "attempts": ParamSpec(int, 1, 5, default=3),
            "wait_seconds": ParamSpec(int, 0, 300, default=10),
        },
    ),
    ActionSpec(
        "verify_running_config",
        "verify",
        params={
            "compare": ParamSpec(
                str, choices=("exact", "normalized"), default="normalized"
            ),
        },
    ),
    # make the restored state survive a reload (platform specific, e.g. VRP "save")
    ActionSpec("persist_config", "persist", mutating=True),
)

# Adapter types the schema accepts. Being listed here does NOT make a type usable: only
# adapters that are implemented AND enabled are in the registry (adapters/__init__.py).
KNOWN_ADAPTER_TYPES: Tuple[str, ...] = ("cisco_ios", "huawei_ce", "huawei_s", "mock")
KNOWN_STRATEGIES: Tuple[str, ...] = ("platform_specific",)
KNOWN_ROLLBACK_STRATEGIES: Tuple[str, ...] = ("none", "platform_specific")

# Actions carried out by the engine itself (not by a platform adapter): the pre-restore
# backup goes through the existing NABS configuration storage.
ENGINE_ACTIONS: Tuple[str, ...] = ("save_pre_restore_backup",)
