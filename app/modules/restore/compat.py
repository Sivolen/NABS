"""Compatibility of a restore profile with a device (pure logic, no database)."""

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Optional

from app.modules.restore.schema import RestoreProfile
from app.modules.restore.families import ADAPTER_FAMILIES, identify_family

COMPATIBLE = "compatible"
INCOMPATIBLE = "incompatible"
# the profile restricts models/versions but the device data needed to decide is missing
UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class Compatibility:
    status: str
    reason: str

    @property
    def allowed(self) -> bool:
        """Only a positively confirmed match may start a restore."""
        return self.status == COMPATIBLE


def normalize_platform(platform: Optional[str]) -> str:
    """
    NABS offers custom drivers only as Netmiko SSH device types (`cisco_ios_ssh`,
    `huawei_vrp_ssh`, ...), see get_netmiko_drivers(). The `_ssh` suffix names the
    transport, not the platform, so "cisco_ios_ssh" and "cisco_ios" are the same platform.
    (A `_telnet` type is a different transport and is NOT normalized: it never matches.)
    """
    text = (platform or "").strip().lower()
    return text[: -len("_ssh")] if text.endswith("_ssh") else text


def _matches(value: str, patterns) -> bool:
    return any(fnmatchcase(value.lower(), p.lower()) for p in patterns)


def check_compatibility(
    profile: RestoreProfile,
    driver: Optional[str],
    model: Optional[str] = None,
    os_version: Optional[str] = None,
    os_generation: Optional[str] = None,
) -> Compatibility:
    """
    driver is the device platform: a NAPALM driver name ("ios") or the Netmiko type of its
    custom driver ("cisco_ios_ssh"); see DeviceInfo.driver. Unknown model/OS
    version is never treated as a match when the profile restricts them.
    """
    if not driver:
        return Compatibility(INCOMPATIBLE, "the device has no driver (platform) set")
    if normalize_platform(driver) not in {
        normalize_platform(p) for p in profile.platforms
    }:
        return Compatibility(
            INCOMPATIBLE,
            f"platform {driver!r} is not in the profile platforms {list(profile.platforms)}",
        )
    family = identify_family(model, driver)
    accepted = ADAPTER_FAMILIES.get(profile.adapter_type)
    if accepted and family.key != "unknown" and family.key not in accepted:
        return Compatibility(
            INCOMPATIBLE,
            f"{family.label} cannot use the {profile.adapter_type} restore mechanism",
        )
    if (
        profile.adapter_type == "huawei_s"
        and os_generation
        and os_generation.split(".")[0] != "5"
    ):
        return Compatibility(
            INCOMPATIBLE,
            f"this reboot mechanism requires VRP5; detected VRP {os_generation}",
        )
    if profile.models:
        if not model:
            return Compatibility(
                UNVERIFIABLE, "device model is unknown, profile is model-restricted"
            )
        if not _matches(model, profile.models):
            return Compatibility(
                INCOMPATIBLE, f"model {model!r} is not supported by the profile"
            )
    if profile.os_versions:
        if not os_version:
            return Compatibility(
                UNVERIFIABLE, "OS version is unknown, profile is version-restricted"
            )
        if not _matches(os_version, profile.os_versions):
            return Compatibility(
                INCOMPATIBLE,
                f"OS version {os_version!r} is not supported by the profile",
            )
    return Compatibility(COMPATIBLE, "ok")
