import difflib

from differently import TextDifferently


def diff_changed(config1: str, config2: str) -> bool:
    pairs = list(zip(config1, config2))
    for pair in pairs:
        line1 = pair[0].rstrip()
        line2 = pair[1].rstrip()
        if line1 != line2:
            return False
    return True


def diff_get_changed(config1: str, config2: str) -> str:
    diff_compare = difflib.Differ()
    diff_result = diff_compare.compare(config1.splitlines(), config2.splitlines())
    delta = "".join(
        x
        for x in diff_result
        if x.startswith("- ") or x.startswith("+ ") or x.startswith("? ")
    )
    return delta


def diff_get_context_changed(
    config1: str, config2: str, previous_config_date: str, last_config_date: str
) -> list:
    difference = difflib.context_diff(
        config1,
        config2,
        fromfile="Previous config",
        tofile="Last config",
        fromfiledate=previous_config_date,
        tofiledate=last_config_date,
    )
    return [line for line in difference]


def diff_get_change_state(config1: str, config2: str) -> bool:
    return True if config1 == config2 else False


def diff(file_one: str, file_two: str) -> TextDifferently:
    return TextDifferently(file_one, file_two)
