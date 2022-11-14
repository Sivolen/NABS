import re


# Checking ipaddresses
def check_ip(ipaddress: int or str) -> bool:
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
    The function needed for replace dubl line feed on device config
    """
    # Pattern for replace
    # pattern = r"^\n"
    # pattern = r"\n\s*\n"
    # pattern = r"^\n\n"
    # pattern = r"^\s*$"
    pattern = r"\n\n"

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
