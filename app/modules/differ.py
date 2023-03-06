import difflib

from differently import TextDifferently


def diff_changed(config1: str, config2: str) -> bool:
    if config1 == config2:
        return True
    lines1 = config1.splitlines()
    lines2 = config2.splitlines()
    if len(lines1) != len(lines2):
        return False
    for line1, line2 in zip(lines1, lines2):
        if line1.rstrip() != line2.rstrip():
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
