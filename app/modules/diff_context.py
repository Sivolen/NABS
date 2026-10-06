"""
Settings of the "Show changed context" button on the diff page.

The diff itself is drawn in the browser (static/js/diff_context.js), so the server
only decides WHICH delimiters belong to the device vendor and passes them to the page.

config.py options (all optional - a config.py created before this feature
keeps working with the defaults below):

    USE_CONFIG_BLOCK_CONTEXT = True
    DIFF_CONTEXT_LINES = 3
    MAX_BLOCK_CONTEXT_LINES = 30
    CONFIG_BLOCK_DELIMITERS = {"huawei": ["#"], "cisco": ["!"]}
"""

import re

DEFAULT_USE_BLOCK_CONTEXT = True
DEFAULT_CONTEXT_LINES = 3
DEFAULT_MAX_BLOCK_LINES = 30  # 0 = never cut a block
# Only rules confirmed on real backup configs. Other vendors (Arista, Juniper,
# MikroTik ...) are added in config.py after checking their configs.
DEFAULT_BLOCK_DELIMITERS = {
    "huawei": ["#"],
    "cisco": ["!"],
}


def _read_config(name: str, default):
    """Returns config.<name> or `default` if config.py has no such option."""
    try:
        import config
    except ImportError:
        return default
    return getattr(config, name, default)


def normalize_delimiters(value) -> list:
    """
    "#" -> ["#"]; ["#", " ## "] -> ["#", "##"]; None / junk -> [].
    Delimiters are compared with line.strip(), so they are stripped here too.
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    result = []
    for item in value:
        if isinstance(item, str) and item.strip() and item.strip() not in result:
            result.append(item.strip())
    return result


def get_block_delimiters(vendor, mapping=None) -> list:
    """
    Delimiters for a vendor, case-insensitive: "Huawei" finds the "huawei" key.
    Falls back to a whole word of the vendor name ("Cisco Systems" -> "cisco").
    Returns [] if the vendor has no delimiters.
    """
    if not vendor or not isinstance(vendor, str):
        return []
    if mapping is None:
        mapping = _read_config("CONFIG_BLOCK_DELIMITERS", DEFAULT_BLOCK_DELIMITERS)
    if not isinstance(mapping, dict):
        return []

    normalized = {
        str(key).strip().lower(): value
        for key, value in mapping.items()
        if str(key).strip()
    }
    name = vendor.strip().lower()
    if name in normalized:
        return normalize_delimiters(normalized[name])
    for word in re.split(r"[^0-9a-z]+", name):
        if word and word in normalized:
            return normalize_delimiters(normalized[word])
    return []


def get_diff_context_settings(vendor) -> dict:
    """
    Data for diff_page.js:
        enabled       - block context is allowed at all (USE_CONFIG_BLOCK_CONTEXT)
        delimiters    - delimiter lines of this vendor ([] = use N lines)
        context_lines - N for the "N lines around a change" mode
        max_block_lines - a block longer than this is cut around the change (0 = never)
    """
    enabled = bool(_read_config("USE_CONFIG_BLOCK_CONTEXT", DEFAULT_USE_BLOCK_CONTEXT))
    try:
        context_lines = int(_read_config("DIFF_CONTEXT_LINES", DEFAULT_CONTEXT_LINES))
    except (TypeError, ValueError):
        context_lines = DEFAULT_CONTEXT_LINES
    if context_lines < 0:
        context_lines = DEFAULT_CONTEXT_LINES

    try:
        max_block_lines = int(
            _read_config("MAX_BLOCK_CONTEXT_LINES", DEFAULT_MAX_BLOCK_LINES)
        )
    except (TypeError, ValueError):
        max_block_lines = DEFAULT_MAX_BLOCK_LINES
    if max_block_lines < 0:
        max_block_lines = DEFAULT_MAX_BLOCK_LINES

    return {
        "enabled": enabled,
        "delimiters": get_block_delimiters(vendor) if enabled else [],
        "context_lines": context_lines,
        "max_block_lines": max_block_lines,
    }
