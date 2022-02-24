import difflib

from differently import TextDifferently


def diff_get_changed(config1: str, config2: str) -> str:
    diff_compare = difflib.Differ()
    diff_result = diff_compare.compare(config1.splitlines(), config2.splitlines())
    delta = "".join(
        x
        for x in diff_result
        if x.startswith("- ") or x.startswith("+ ") or x.startswith("? ")
    )
    return delta


def diff_get_context_changed(config1: str, config2: str) -> list:
    difference = difflib.context_diff(
        config1,
        config2,
        fromfile="Previous config",
        tofile="Last config",
        fromfiledate="2021-02-19",
        tofiledate="2021-02-20",
    )
    return [line for line in difference]


def diff_get_change_state(config1: str, config2: str) -> bool:
    return True if config1 == config2 else False


def diff(file_one: str, file_two: str) -> TextDifferently:
    return TextDifferently(file_one, file_two)
