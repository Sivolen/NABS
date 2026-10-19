"""
Registry of platform adapters.

Only adapters that are really implemented are registered, and an adapter that has not
been proven on real equipment (`verified = False`) is registered only when the
administrator enables it (RESTORE_ENABLE_UNVERIFIED_ADAPTERS). A YAML profile alone never
makes a platform supported.
"""

from typing import Dict, FrozenSet, Iterable, Optional, Set, Type

from app.modules.restore.adapters.base import RestoreAdapter


def adapter_classes(
    include_mock: bool = False, include_unverified: bool = False
) -> Dict[str, Type[RestoreAdapter]]:
    classes: Dict[str, Type[RestoreAdapter]] = {}
    if include_mock:  # tests only
        from app.modules.restore.adapters.mock import MockAdapter

        classes[MockAdapter.type] = MockAdapter
    from app.modules.restore.adapters.cisco_ios import CiscoIosAdapter
    from app.modules.restore.adapters.huawei_ce import HuaweiCeAdapter
    from app.modules.restore.adapters.huawei_s import HuaweiSAdapter

    for cls in (CiscoIosAdapter, HuaweiCeAdapter, HuaweiSAdapter):
        if cls.verified or include_unverified:
            classes[cls.type] = cls
    return classes


def get_adapter_class(
    adapter_type: Optional[str],
    include_mock: bool = False,
    include_unverified: bool = False,
) -> Optional[Type[RestoreAdapter]]:
    return adapter_classes(include_mock, include_unverified).get(adapter_type or "")


def create_adapter(
    adapter_type: Optional[str],
    include_mock: bool = False,
    include_unverified: bool = False,
    ignore_patterns: Iterable[str] = (),
) -> Optional[RestoreAdapter]:
    cls = get_adapter_class(adapter_type, include_mock, include_unverified)
    return cls.create(ignore_patterns=tuple(ignore_patterns)) if cls else None


def adapter_capabilities(
    include_mock: bool = False,
    engine_actions: FrozenSet[str] = frozenset(),
    include_unverified: bool = False,
) -> Dict[str, Set[str]]:
    """
    {adapter type: actions it can run}, for schema.check_adapter_capabilities().
    engine_actions: actions the engine itself implements (added to every adapter).
    """
    return {
        name: set(cls.supported_actions()) | set(engine_actions)
        for name, cls in adapter_classes(include_mock, include_unverified).items()
    }
