import re
import psutil
from functools import lru_cache
from netmiko.ssh_dispatcher import CLASS_MAPPER


# Checking ipaddresses
def check_ip(ipaddress: int | str) -> bool:
    """
    Check ip address
    """
    pattern = (
        r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1"
        "[0-9]"
        "{2}|2[0-4]["
        "0-9"
        "]|25[0-5])$"
    )
    return True if re.findall(pattern, ipaddress) else False


# The function needed for delete blank line on device config
def clear_line_feed_on_device_config(config: str) -> str:
    """
    The function needed for replace double line feed on device config
    """
    # Pattern for replace
    # pattern = r"^\n"
    # pattern = r"\n\s*\n"
    # pattern = r"^\n\n"
    # pattern = r"^\s*$"
    # pattern = r"\n\n"
    pattern = r"(\n){2,}"
    if re.match(r"^\n", config):
        # Remove first line
        config = re.sub(r"^\n", "", config)
    # Return changed config with delete free space
    return re.sub(pattern, "\n", str(config))


# The function needed replace ntp clock period on cisco switch, but he's always changing
def clear_clock_period_on_device_config(config: str) -> str:
    """
    The function needed replace ntp clock period on cisco switch, but he's always changing
    """
    # pattern for replace
    pattern = r"ntp\sclock-period\s[0-9]{1,30}\n"
    # Returning changed config or if this command not found return original file
    return re.sub(pattern, "", str(config))


# The function needed replace ntp clock period on cisco switch, but he's always changing
def clear_config_patterns(config: str, patterns: list) -> str:
    """
    Clears the given patterns from the config string.
    """
    for pattern in patterns:
        config = re.sub(pattern, "", str(config))
    return config


def is_incomplete_config(
    candidate_config: str,
    reference_config: str | None,
    min_ratio: float = 0.5,
    min_reference_lines: int = 20,
) -> bool:
    """
    Heuristic check for a truncated/glitched device response
    (e.g. Eltex MES / Cisco SG350 sometimes return only a couple of
    prompt/banner lines instead of the full running-config when the
    device CLI is slow/overloaded).

    Instead of a fixed absolute line-count threshold (which is fragile:
    different devices have very different config sizes), the candidate
    is compared to the LAST KNOWN GOOD config for that same device.
    If it is drastically shorter, it's treated as suspicious/incomplete.

    parm:
        candidate_config: newly fetched config
        reference_config: last config stored in DB for this device (or None)
        min_ratio: candidate must have at least this fraction of the
            reference config's line count to be considered plausible
        min_reference_lines: only apply the check if the reference config
            itself has at least this many lines (avoids false positives
            on devices that legitimately have a tiny config)
    return:
        bool - True if candidate looks like a truncated/glitched read
    """
    if not reference_config or not candidate_config:
        return False
    ref_lines = len(reference_config.splitlines())
    if ref_lines < min_reference_lines:
        # Not enough signal from the reference to judge reliably
        return False
    cand_lines = len(candidate_config.splitlines())
    return cand_lines < ref_lines * min_ratio


def get_server_params() -> dict:
    """
    This function gets the server parameters
    """
    memory = psutil.virtual_memory()
    disk_usage = psutil.disk_usage("/")

    return {
        "cpu_percent": psutil.cpu_percent(),
        "cpu_freq": psutil.cpu_freq(),
        "cpu_count": psutil.cpu_count(),
        "memory_total": int(memory.total / 1024 / 1024),
        "memory_used": int(memory.used / 1024 / 1024),
        "memory_free": int(memory.free / 1024 / 1024),
        "disk_total": int(disk_usage.total / 1024 / 1024 / 1024),
        "disk_used": int(disk_usage.used / 1024 / 1024 / 1024),
        "disk_free": int(disk_usage.free / 1024 / 1024 / 1024),
    }


@lru_cache(maxsize=1)
def get_netmiko_drivers():
    """Returns the current list of Netmiko drivers (SSH only)."""
    try:
        # Filter only SSH drivers
        return sorted([d for d in CLASS_MAPPER.keys() if d.endswith("_ssh")])
    except ImportError:
        # fallback in case netmiko is missing
        return ["cisco_ios_ssh", "huawei_vrp_ssh", "juniper_junos_ssh"]
