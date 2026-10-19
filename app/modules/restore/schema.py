"""
Restore profile: parsing and validation of YAML profiles (schema_version 1).

Two different questions are answered by two different functions:
  * validate_profile_data()/parse_profile_yaml() - is the document well-formed and
    does it respect the safety rules (structure, known actions, step order, limits)?
  * check_adapter_capabilities() - does the named adapter REALLY implement every
    action the profile uses? A profile that names an unimplemented action is
    syntactically fine but must never be runnable.

Nothing here touches the database, a device or the network.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

import yaml

from app.modules.restore.actions import (
    ACTIONS,
    KNOWN_ADAPTER_TYPES,
    KNOWN_ROLLBACK_STRATEGIES,
    KNOWN_STRATEGIES,
    PHASES,
)

SUPPORTED_SCHEMA_VERSIONS: Tuple[int, ...] = (1,)
MAX_YAML_BYTES = 64 * 1024
MAX_YAML_DEPTH = 8
MAX_STEPS = 30

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
PLATFORM_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,49}$")
DEVICE_TYPE_RE = re.compile(r"^[a-z0-9_]{1,50}$")
# secrets must never be stored in a profile: reject suspicious KEY names anywhere
SECRET_KEY_RE = re.compile(
    r"(pass(word|wd)?|secret|token|private[_-]?key|api[_-]?key|credential)", re.I
)
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

LIMIT_RANGES: Dict[str, Tuple[int, int, int]] = {
    # name: (default, min, max) in seconds
    "connect_timeout": (10, 1, 120),
    "operation_timeout": (120, 1, 3600),
    "verify_timeout": (60, 1, 1200),
    "reconnect_timeout": (60, 0, 600),
}


@dataclass(frozen=True)
class Issue:
    level: str  # "error" | "warning"
    path: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.path or '<root>'}: {self.message}"


@dataclass(frozen=True)
class Step:
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    required: bool = True


@dataclass(frozen=True)
class RestoreProfile:
    schema_version: int
    id: str
    name: str
    description: str
    vendor: str
    platforms: Tuple[str, ...]
    models: Tuple[str, ...]
    os_versions: Tuple[str, ...]
    profile_version: int
    builtin: bool
    adapter_type: str
    adapter_device_type: Optional[str]
    strategy: str
    require_precheck: bool
    require_pre_restore_backup: bool
    require_confirmation: bool
    require_target_validation: bool
    steps: Tuple[Step, ...]
    rollback_strategy: str
    mark_unknown_if_connection_lost: bool
    limits: Dict[str, int]
    warnings: Tuple[str, ...]
    # the restore interrupts service (e.g. reboots the device): the UI says so loudly and asks
    # the user to type the device name to confirm
    disruptive: bool = False


@dataclass
class ValidationResult:
    profile: Optional[RestoreProfile]
    issues: List[Issue]

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return self.profile is not None and not self.errors


# --------------------------------------------------------------------------- YAML
class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that also rejects duplicate keys and non-string keys."""


def _construct_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"mapping keys must be strings, got {key!r} (quote it)",
                key_node.start_mark,
            )
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _yaml_error_issue(error: yaml.YAMLError) -> Issue:
    mark = getattr(error, "problem_mark", None) or getattr(error, "context_mark", None)
    where = f" (line {mark.line + 1})" if mark is not None else ""
    problem = getattr(error, "problem", None) or "invalid YAML"
    return Issue("error", "", "yaml_syntax", f"{problem}{where}")


def _depth(value: Any, level: int = 1) -> int:
    if isinstance(value, dict):
        return max([level] + [_depth(v, level + 1) for v in value.values()])
    if isinstance(value, list):
        return max([level] + [_depth(v, level + 1) for v in value])
    return level


def parse_profile_yaml(text: Any, allow_builtin: bool = False) -> ValidationResult:
    """
    Parse and validate YAML text. Never raises for bad input: every problem is an
    Issue. allow_builtin must be True ONLY for the files shipped with the application.
    """
    if not isinstance(text, str):
        return ValidationResult(
            None, [Issue("error", "", "type", "profile must be YAML text")]
        )
    if len(text.encode("utf-8", errors="replace")) > MAX_YAML_BYTES:
        return ValidationResult(
            None,
            [
                Issue(
                    "error", "", "too_large", f"profile exceeds {MAX_YAML_BYTES} bytes"
                )
            ],
        )
    try:
        # aliases/anchors are not needed by a profile and make "YAML bombs" possible
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, (yaml.AliasEvent,)) or getattr(event, "anchor", None):
                return ValidationResult(
                    None,
                    [
                        Issue(
                            "error",
                            "",
                            "yaml_alias",
                            "YAML anchors/aliases are not allowed",
                        )
                    ],
                )
        data = yaml.load(text, Loader=_StrictLoader)  # nosec B506: safe loader subclass
    except yaml.YAMLError as error:
        return ValidationResult(None, [_yaml_error_issue(error)])
    return validate_profile_data(data, allow_builtin=allow_builtin)


# ------------------------------------------------------------------- validation
class _Ctx:
    def __init__(self) -> None:
        self.issues: List[Issue] = []

    def error(self, path: str, code: str, message: str) -> None:
        self.issues.append(Issue("error", path, code, message))

    def warn(self, path: str, code: str, message: str) -> None:
        self.issues.append(Issue("warning", path, code, message))

    # -- typed readers: return None (and record an error) when invalid
    def mapping(self, value: Any, path: str, allowed: Set[str]) -> Optional[dict]:
        if not isinstance(value, dict):
            self.error(path, "type", "must be a mapping")
            return None
        for key in value:
            if SECRET_KEY_RE.search(key):
                self.error(
                    f"{path}.{key}" if path else key,
                    "secret_key",
                    "profiles must not contain passwords, keys or tokens",
                )
            elif key not in allowed:
                self.error(
                    f"{path}.{key}" if path else key, "unknown_key", "unknown field"
                )
        return value

    def text(
        self,
        parent: dict,
        key: str,
        path: str,
        *,
        required: bool = True,
        max_len: int = 100,
        pattern: Optional["re.Pattern"] = None,
        default: Optional[str] = None,
    ) -> Optional[str]:
        full = f"{path}.{key}" if path else key
        if key not in parent or parent[key] is None:
            if required:
                self.error(full, "missing", "required field is missing")
            return default
        value = parent[key]
        if not isinstance(value, str) or not value.strip():
            self.error(full, "type", "must be a non-empty string")
            return default
        if len(value) > max_len or CONTROL_CHARS_RE.search(value):
            self.error(
                full, "value", f"too long (max {max_len}) or has control characters"
            )
            return default
        if pattern is not None and not pattern.match(value):
            self.error(full, "format", f"does not match {pattern.pattern}")
            return default
        return value

    def integer(
        self,
        parent: dict,
        key: str,
        path: str,
        minimum: int,
        maximum: int,
        default: int,
    ) -> int:
        full = f"{path}.{key}" if path else key
        if key not in parent or parent[key] is None:
            return default
        value = parent[key]
        if isinstance(value, bool) or not isinstance(value, int):
            self.error(full, "type", "must be an integer")
            return default
        if not minimum <= value <= maximum:
            self.error(full, "range", f"must be between {minimum} and {maximum}")
            return default
        return value

    def boolean(self, parent: dict, key: str, path: str, default: bool) -> bool:
        full = f"{path}.{key}" if path else key
        if key not in parent or parent[key] is None:
            return default
        if not isinstance(parent[key], bool):
            self.error(full, "type", "must be true or false")
            return default
        return parent[key]

    def string_list(
        self,
        parent: dict,
        key: str,
        path: str,
        *,
        required: bool,
        max_items: int,
        max_len: int,
        pattern: Optional["re.Pattern"] = None,
    ) -> Tuple[str, ...]:
        full = f"{path}.{key}" if path else key
        if key not in parent or parent[key] is None:
            if required:
                self.error(full, "missing", "required field is missing")
            return ()
        value = parent[key]
        if not isinstance(value, list) or (required and not value):
            self.error(full, "type", "must be a non-empty list of strings")
            return ()
        if len(value) > max_items:
            self.error(full, "range", f"at most {max_items} items")
            return ()
        out: List[str] = []
        for index, item in enumerate(value):
            item_path = f"{full}[{index}]"
            if (
                not isinstance(item, str)
                or not item.strip()
                or len(item) > max_len
                or CONTROL_CHARS_RE.search(item)
                or (pattern is not None and not pattern.match(item))
            ):
                self.error(item_path, "value", "invalid value")
                continue
            out.append(item)
        return tuple(out)


def _validate_steps(ctx: _Ctx, raw: Any, flags: Dict[str, Any]) -> Tuple[Step, ...]:
    path = "restore.steps"
    if not isinstance(raw, list) or not raw:
        ctx.error(path, "type", "must be a non-empty list of steps")
        return ()
    if len(raw) > MAX_STEPS:
        ctx.error(path, "range", f"at most {MAX_STEPS} steps")
        return ()
    steps: List[Step] = []
    for index, item in enumerate(raw):
        item_path = f"{path}[{index}]"
        mapping = ctx.mapping(item, item_path, {"action", "params", "required"})
        if mapping is None:
            continue
        action = ctx.text(mapping, "action", item_path, max_len=60)
        if action is None:
            continue
        spec = ACTIONS.get(action)
        if spec is None:
            ctx.error(
                f"{item_path}.action",
                "unknown_action",
                f"action {action!r} is not in the list of allowed actions",
            )
            continue
        params: Dict[str, Any] = {}
        if "params" in mapping and mapping["params"] is not None:
            raw_params = ctx.mapping(
                mapping["params"], f"{item_path}.params", set(spec.params)
            )
            for name, value in (raw_params or {}).items():
                pspec = spec.params.get(name)
                if pspec is None:
                    continue  # already reported as unknown/secret
                pp = f"{item_path}.params.{name}"
                if pspec.type is int:
                    params[name] = ctx.integer(
                        raw_params,
                        name,
                        f"{item_path}.params",
                        pspec.minimum,
                        pspec.maximum,
                        pspec.default,
                    )
                elif pspec.type is str:
                    if value not in (pspec.choices or ()):
                        ctx.error(pp, "value", f"must be one of {list(pspec.choices)}")
                    else:
                        params[name] = value
                elif pspec.type is bool:
                    params[name] = ctx.boolean(
                        raw_params, name, f"{item_path}.params", bool(pspec.default)
                    )
        required = ctx.boolean(mapping, "required", item_path, True)
        if not required and not spec.skippable:
            ctx.error(
                f"{item_path}.required",
                "not_skippable",
                f"action {action!r} is a safety-critical step and cannot be optional",
            )
            required = True
        elif not required:
            ctx.warn(
                f"{item_path}.required",
                "skippable_step",
                f"{action!r} is optional: the operation continues without its result",
            )
        steps.append(Step(action=action, params=params, required=required))

    _validate_step_order(ctx, steps, flags)
    return tuple(steps)


def _validate_step_order(ctx: _Ctx, steps: List[Step], flags: Dict[str, Any]) -> None:
    path = "restore.steps"
    names = [s.action for s in steps]
    if len(set(names)) != len(names):
        ctx.error(path, "duplicate_action", "an action may appear only once")

    last_phase = -1
    for index, step in enumerate(steps):
        phase = PHASES.index(ACTIONS[step.action].phase)
        if phase < last_phase:
            ctx.error(
                f"{path}[{index}]",
                "order",
                f"{step.action!r} ({ACTIONS[step.action].phase}) is placed after a later"
                f" phase; order must be {' -> '.join(PHASES)}",
            )
        last_phase = max(last_phase, phase)

    def position(name: str) -> int:
        return names.index(name) if name in names else -1

    apply_at = position("apply_saved_config")
    if apply_at == -1:
        ctx.error(
            path, "missing_apply", "the profile must contain 'apply_saved_config'"
        )
        return
    if not any(ACTIONS[n].phase == "verify" for n in names[apply_at + 1 :]):
        ctx.error(
            path,
            "missing_verify",
            "at least one verify step must follow 'apply_saved_config': sent commands"
            " are not proof of success",
        )

    def require_before(name: str, why: str) -> None:
        at = position(name)
        if at == -1 or at > apply_at:
            ctx.error(
                path, "missing_step", f"{why}: add {name!r} before 'apply_saved_config'"
            )
        elif not steps[at].required:
            ctx.error(path, "step_optional", f"{name!r} must be required ({why})")

    if flags["require_precheck"]:
        require_before("check_platform_support", "require_precheck is true")
    if flags["require_pre_restore_backup"]:
        require_before("save_pre_restore_backup", "require_pre_restore_backup is true")
    if flags["require_target_validation"]:
        require_before("validate_target_config", "require_target_validation is true")
    if flags["rollback_strategy"] != "none":
        require_before("check_rollback_available", "a rollback strategy is declared")
    backup_at = position("save_pre_restore_backup")
    if backup_at != -1:
        fetch_at = position("fetch_current_config")
        if fetch_at == -1 or fetch_at > backup_at or not steps[fetch_at].required:
            ctx.error(
                path,
                "missing_step",
                "'save_pre_restore_backup' needs a required 'fetch_current_config' before it",
            )


def validate_profile_data(data: Any, allow_builtin: bool = False) -> ValidationResult:
    ctx = _Ctx()
    if _depth(data) > MAX_YAML_DEPTH:
        return ValidationResult(
            None,
            [Issue("error", "", "too_deep", f"nesting deeper than {MAX_YAML_DEPTH}")],
        )
    root = ctx.mapping(
        data,
        "",
        {
            "schema_version",
            "id",
            "name",
            "description",
            "vendor",
            "platforms",
            "compatibility",
            "profile_version",
            "builtin",
            "adapter",
            "restore",
            "failure",
            "limits",
            "warnings",
        },
    )
    if root is None:
        return ValidationResult(None, ctx.issues)

    version = root.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        ctx.error("schema_version", "missing", "schema_version must be an integer")
        version = 0
    elif version not in SUPPORTED_SCHEMA_VERSIONS:
        ctx.error(
            "schema_version",
            "unsupported_schema",
            f"schema version {version} is not supported (supported:"
            f" {list(SUPPORTED_SCHEMA_VERSIONS)})",
        )

    profile_id = ctx.text(root, "id", "", max_len=63, pattern=ID_RE)
    name = ctx.text(root, "name", "", max_len=100)
    description = ctx.text(
        root, "description", "", required=False, max_len=500, default=""
    )
    vendor = ctx.text(root, "vendor", "", max_len=50)
    platforms = ctx.string_list(
        root,
        "platforms",
        "",
        required=True,
        max_items=20,
        max_len=50,
        pattern=PLATFORM_RE,
    )
    profile_version = ctx.integer(root, "profile_version", "", 1, 10**6, 0)
    if "profile_version" not in root:
        ctx.error("profile_version", "missing", "required field is missing")

    builtin = ctx.boolean(root, "builtin", "", False)
    if builtin and not allow_builtin:
        ctx.error(
            "builtin",
            "builtin_forbidden",
            "'builtin: true' is accepted only for profiles shipped with NABS",
        )
        builtin = False

    models: Tuple[str, ...] = ()
    os_versions: Tuple[str, ...] = ()
    if root.get("compatibility") is not None:
        compat = ctx.mapping(
            root["compatibility"], "compatibility", {"models", "os_versions"}
        )
        if compat is not None:
            models = ctx.string_list(
                compat,
                "models",
                "compatibility",
                required=False,
                max_items=50,
                max_len=100,
            )
            os_versions = ctx.string_list(
                compat,
                "os_versions",
                "compatibility",
                required=False,
                max_items=50,
                max_len=100,
            )

    # adapter
    adapter_type: Optional[str] = None
    device_type: Optional[str] = None
    adapter = ctx.mapping(root.get("adapter"), "adapter", {"type", "device_type"})
    if adapter is not None:
        adapter_type = ctx.text(adapter, "type", "adapter", max_len=30)
        if adapter_type is not None and adapter_type not in KNOWN_ADAPTER_TYPES:
            ctx.error(
                "adapter.type",
                "unknown_adapter",
                f"unknown adapter type {adapter_type!r} (known: {list(KNOWN_ADAPTER_TYPES)})",
            )
        device_type = ctx.text(
            adapter,
            "device_type",
            "adapter",
            required=False,
            max_len=50,
            pattern=DEVICE_TYPE_RE,
            default=None,
        )

    # restore + failure
    disruptive = False
    flags: Dict[str, Any] = {}
    strategy = None
    steps: Tuple[Step, ...] = ()
    restore = ctx.mapping(
        root.get("restore"),
        "restore",
        {
            "strategy",
            "require_precheck",
            "require_pre_restore_backup",
            "require_confirmation",
            "require_target_validation",
            "steps",
            "disruptive",
        },
    )
    failure = ctx.mapping(
        root.get("failure"),
        "failure",
        {"rollback_strategy", "mark_unknown_if_connection_lost"},
    )
    rollback = "none"
    mark_unknown = True
    if failure is not None:
        rollback = (
            ctx.text(failure, "rollback_strategy", "failure", max_len=30) or "none"
        )
        if rollback not in KNOWN_ROLLBACK_STRATEGIES:
            ctx.error(
                "failure.rollback_strategy",
                "value",
                f"must be one of {list(KNOWN_ROLLBACK_STRATEGIES)}",
            )
            rollback = "none"
        mark_unknown = ctx.boolean(
            failure, "mark_unknown_if_connection_lost", "failure", True
        )
        if not mark_unknown:
            ctx.error(
                "failure.mark_unknown_if_connection_lost",
                "unsafe_setting",
                "must be true: a lost connection must never be reported as success/failure",
            )
            mark_unknown = True
        if rollback == "none":
            ctx.warn(
                "failure.rollback_strategy",
                "no_rollback",
                "no rollback: a failed restore cannot be undone automatically",
            )

    require = {
        "require_precheck": True,
        "require_pre_restore_backup": True,
        "require_confirmation": True,
        "require_target_validation": True,
    }
    if restore is not None:
        strategy = ctx.text(restore, "strategy", "restore", max_len=30)
        if strategy is not None and strategy not in KNOWN_STRATEGIES:
            ctx.error(
                "restore.strategy",
                "unknown_strategy",
                f"unknown strategy {strategy!r} (known: {list(KNOWN_STRATEGIES)})",
            )
        for key in require:
            require[key] = ctx.boolean(restore, key, "restore", True)
        for key in ("require_precheck", "require_confirmation"):
            if not require[key]:
                ctx.error(
                    f"restore.{key}",
                    "unsafe_setting",
                    "must be true: this safety requirement cannot be disabled",
                )
                require[key] = True
        for key, what in (
            (
                "require_pre_restore_backup",
                "no pre-restore backup: the current state cannot be recovered",
            ),
            (
                "require_target_validation",
                "the target configuration will not be validated",
            ),
        ):
            if not require[key]:
                ctx.warn(f"restore.{key}", "disabled_safety", what)
        disruptive = ctx.boolean(restore, "disruptive", "restore", False)
        flags = dict(require, rollback_strategy=rollback)
        steps = _validate_steps(ctx, restore.get("steps"), flags)

    # limits
    limits: Dict[str, int] = {}
    raw_limits = root.get("limits")
    limits_map = (
        ctx.mapping(raw_limits, "limits", set(LIMIT_RANGES))
        if raw_limits is not None
        else {}
    )
    for key, (default, low, high) in LIMIT_RANGES.items():
        limits[key] = ctx.integer(limits_map or {}, key, "limits", low, high, default)

    warnings = ctx.string_list(
        root, "warnings", "", required=False, max_items=20, max_len=500
    )

    if ctx.issues and any(i.level == "error" for i in ctx.issues):
        return ValidationResult(None, ctx.issues)

    profile = RestoreProfile(
        schema_version=version,
        id=profile_id,
        name=name,
        description=description or "",
        vendor=vendor,
        platforms=platforms,
        models=models,
        os_versions=os_versions,
        profile_version=profile_version,
        builtin=builtin,
        adapter_type=adapter_type,
        adapter_device_type=device_type,
        strategy=strategy,
        require_precheck=require["require_precheck"],
        require_pre_restore_backup=require["require_pre_restore_backup"],
        require_confirmation=require["require_confirmation"],
        require_target_validation=require["require_target_validation"],
        steps=steps,
        rollback_strategy=rollback,
        mark_unknown_if_connection_lost=mark_unknown,
        limits=limits,
        warnings=warnings,
        disruptive=disruptive,
    )
    return ValidationResult(profile, ctx.issues)


# ------------------------------------------------------------------ capabilities
def check_adapter_capabilities(
    profile: RestoreProfile, adapters: Mapping[str, Set[str]]
) -> List[Issue]:
    """
    adapters: {adapter type: set of action names the adapter REALLY implements}.
    A profile whose adapter is not registered, or that uses an action the adapter does
    not implement, is reported as an error and must be blocked from running.
    """
    supported = adapters.get(profile.adapter_type)
    if supported is None:
        return [
            Issue(
                "error",
                "adapter.type",
                "adapter_not_implemented",
                f"adapter {profile.adapter_type!r} is not implemented in this NABS",
            )
        ]
    return [
        Issue(
            "error",
            f"restore.steps[{i}].action",
            "action_not_supported",
            f"adapter {profile.adapter_type!r} does not implement {step.action!r}",
        )
        for i, step in enumerate(profile.steps)
        if step.action not in supported
    ]


# ------------------------------------------------------------------------ export
def profile_to_dict(profile: RestoreProfile) -> Dict[str, Any]:
    adapter: Dict[str, Any] = {"type": profile.adapter_type}
    if profile.adapter_device_type:
        adapter["device_type"] = profile.adapter_device_type
    data: Dict[str, Any] = {
        "schema_version": profile.schema_version,
        "id": profile.id,
        "name": profile.name,
    }
    if profile.description:
        data["description"] = profile.description
    data.update({"vendor": profile.vendor, "platforms": list(profile.platforms)})
    if profile.models or profile.os_versions:
        compat: Dict[str, Any] = {}
        if profile.models:
            compat["models"] = list(profile.models)
        if profile.os_versions:
            compat["os_versions"] = list(profile.os_versions)
        data["compatibility"] = compat
    data.update(
        {
            "profile_version": profile.profile_version,
            "builtin": profile.builtin,
            "adapter": adapter,
            "restore": {
                "strategy": profile.strategy,
                "require_precheck": profile.require_precheck,
                "require_pre_restore_backup": profile.require_pre_restore_backup,
                "require_confirmation": profile.require_confirmation,
                "require_target_validation": profile.require_target_validation,
                **({"disruptive": True} if profile.disruptive else {}),
                "steps": [
                    dict(
                        {"action": s.action},
                        **({"params": dict(s.params)} if s.params else {}),
                        **({} if s.required else {"required": False}),
                    )
                    for s in profile.steps
                ],
            },
            "failure": {
                "rollback_strategy": profile.rollback_strategy,
                "mark_unknown_if_connection_lost": profile.mark_unknown_if_connection_lost,
            },
            "limits": dict(profile.limits),
        }
    )
    if profile.warnings:
        data["warnings"] = list(profile.warnings)
    return data


def dump_profile_yaml(profile: RestoreProfile) -> str:
    """Canonical YAML of a validated profile (used for export)."""
    return yaml.safe_dump(
        profile_to_dict(profile), sort_keys=False, allow_unicode=True, width=100
    )
