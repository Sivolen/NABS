"""Inventory grouping, not proof of restore support or device capabilities.

Rules describe product families. Actual restore support still requires profile
compatibility and the worker's device-side precheck. Unknown models stay unknown.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DeviceFamily:
    key: str
    label: str
    source: str


# Specific model patterns precede driver fallbacks. Keep this catalog independent
# of adapters so unsupported inventory can still be grouped and explained.
MODEL_RULES = (
    (r"^(?:cisco )?(?:n[235679]k-|nexus )", "cisco_nxos", "Cisco Nexus"),
    (
        r"^(?:cisco )?(?:sg[235]\d\d|cbs[23]\d\d|sf[235]\d\d)",
        "cisco_small_business",
        "Cisco Small Business",
    ),
    (
        r"^(?:cisco )?(?:ws-c|c[139]\d{3}|[1234]9[012]\d|asr\d|isr\d)",
        "cisco_ios",
        "Cisco IOS / IOS XE",
    ),
    (r"^(?:huawei )?(?:cloudengine )?ce\d", "huawei_ce", "Huawei CloudEngine CE"),
    (
        r"^(?:huawei )?(?:cloudengine )?s\d{4}",
        "huawei_campus",
        "Huawei campus switches",
    ),
    (r"^(?:huawei )?ar\d", "huawei_ar", "Huawei AR routers"),
    (r"^(?:huawei )?ac\d", "huawei_ac", "Huawei wireless controllers"),
    (r"^(?:eltex )?mes\d", "eltex_mes", "Eltex MES"),
    (r"^(?:eltex )?esr-?\d", "eltex_esr", "Eltex ESR"),
    (r"^(?:d-link )?dgs-", "dlink", "D-Link switches"),
    (
        r"^(?:mikrotik )?(?:chr(?: |$)|routerboard|rb\d|ccr\d|crs\d)",
        "mikrotik",
        "MikroTik RouterOS",
    ),
    (r"^(?:hp |hpe )?(?:bladesystem |vc flexfabric )", "hpe", "HPE infrastructure"),
    (r"^(?:apc )?(?:smart-ups |symmetra )", "apc", "APC power equipment"),
)
DRIVER_RULES = {
    "ios": ("cisco_ios", "Cisco IOS / IOS XE"),
    "cisco_ios": ("cisco_ios", "Cisco IOS / IOS XE"),
    "cisco_xe": ("cisco_ios", "Cisco IOS / IOS XE"),
    "nxos": ("cisco_nxos", "Cisco Nexus"),
    "nxos_ssh": ("cisco_nxos", "Cisco Nexus"),
    "cisco_nxos": ("cisco_nxos", "Cisco Nexus"),
    "cisco_s300": ("cisco_small_business", "Cisco Small Business"),
    "mikrotik_routeros": ("mikrotik", "MikroTik RouterOS"),
    "routeros": ("mikrotik", "MikroTik RouterOS"),
    "eltex_mes": ("eltex_mes", "Eltex MES"),
    "eltex_esr": ("eltex_esr", "Eltex ESR"),
    "dlink_ds": ("dlink", "D-Link switches"),
}


def identify_family(model: Optional[str], driver: Optional[str]) -> DeviceFamily:
    normalized = " ".join((model or "").lower().split())
    for pattern, key, label in MODEL_RULES:
        if re.match(pattern, normalized):
            return DeviceFamily(key, label, "model")
    platform = (driver or "").strip().lower()
    if platform.endswith("_ssh"):
        platform = platform[:-4]
    if platform in DRIVER_RULES:
        key, label = DRIVER_RULES[platform]
        return DeviceFamily(key, label, "driver")
    return DeviceFamily("unknown", "Family not determined", "unknown")


# Restrictions belong to a mechanism, including user copies of built-in profiles.
# A campus S model is NOT a promise of VRP5/reboot support; device-side checks
# remain required to establish the exact software and restoration mechanism.
ADAPTER_FAMILIES = {
    "cisco_ios": frozenset({"cisco_ios"}),
    "huawei_ce": frozenset({"huawei_ce"}),
    "huawei_s": frozenset({"huawei_campus"}),
}
