import difflib
import re
from typing import Iterator

from differently import TextDifferently


# from io import StringIO


def diff_get_changed(config1, config2) -> str:
    diff_compare = difflib.Differ()
    diff_result = diff_compare.compare(config1, config2)
    delta = "".join(
        x
        for x in diff_result
        if x.startswith("- ") or x.startswith("+ ") or x.startswith("? ")
    )
    return delta


def diff_get_context_changed(config1, config2) -> list:
    difference = difflib.context_diff(config1, config2,
                                      fromfile="10.0.176.254.cfg",
                                      tofile="10.0.176.254.cfg",
                                      fromfiledate="2021-02-19",
                                      tofiledate="2021-02-20")
    # for line in diff:
    #     print(line, end="")
    return [line for line in difference]


def diff_get_change_state(config1: str, config2: str) -> True or False:
    return True if config1 == config2 else False


def diff(file_one: str, file_two: str):
    return TextDifferently(file_one, file_two)


def tokenize(s):
    return re.split("\s+", str(s))


def untokenize(ts):
    return " ".join(ts)


def equalize(s1, s2):
    l1 = tokenize(s1)
    l2 = tokenize(s2)
    res1 = []
    res2 = []
    prev = difflib.Match(0, 0, 0)
    for match in difflib.SequenceMatcher(a=l1, b=l2).get_matching_blocks():
        if prev.a + prev.size != match.a:
            for i in range(prev.a + prev.size, match.a):
                res2 += ["_" * len(l1[i])]
            res1 += l1[prev.a + prev.size: match.a]
        if prev.b + prev.size != match.b:
            for i in range(prev.b + prev.size, match.b):
                res1 += ["_" * len(l2[i])]
            res2 += l2[prev.b + prev.size: match.b]
        res1 += l1[match.a: match.a + match.size]
        res2 += l2[match.b: match.b + match.size]
        prev = match
    if untokenize(res1) == untokenize(res2):
        print("true")
    else:
        print("false")
    return untokenize(res1), untokenize(res2)


def insert_newlines(string, every=40, window=10):
    result = []
    from_str = string
    while len(from_str) > 0:
        cut_off = every
        if len(from_str) > every:
            while (from_str[cut_off - 1] != " ") and (cut_off > (every - window)):
                cut_off -= 1
        else:
            cut_off = len(from_str)
        part = from_str[:cut_off]
        result += [part]
        from_str = from_str[cut_off:]
    return result


def show_comparison(s1, s2, width=40, margin=10, sidebyside=True, compact=False):
    s1, s2 = equalize(s1, s2)

    if sidebyside:
        s1 = insert_newlines(s1, width, margin)
        s2 = insert_newlines(s2, width, margin)
        if compact:
            for i in range(0, len(s1)):
                lft = re.sub(" +", " ", s1[i].replace("_", "")).ljust(width)
                rgt = re.sub(" +", " ", s2[i].replace("_", "")).ljust(width)
                print(lft + " | " + rgt + " | ")
        else:
            for i in range(0, len(s1)):
                lft = s1[i].ljust(width)
                rgt = s2[i].ljust(width)
                print(lft + " | " + rgt + " | ")
    else:
        print(s1)
        print(s2)

# if __name__ == "__main__":
#     a = open("/home/agridnev/PycharmProjects/netbox_config_backup/configs/2022-02-01/10.255.100.1.cfg").readlines()
#     b = open("/home/agridnev/PycharmProjects/netbox_config_backup/configs/2022-02-09/10.255.100.1.cfg").readlines()
#     # test = (diff(a.read(), b.read()))
#     # print(test)
#
#     difference = difflib.context_diff(a, b,
#                                       fromfile="10.0.176.254.cfg",
#                                       tofile="10.0.176.254.cfg",
#                                       fromfiledate="2021-02-19", tofiledate="2021-02-20")
#
#     # for diff in difference:
#     #     print(diff, end="")
#
#     diff = difflib.unified_diff(a, b,
#                                 fromfile="original.txt", tofile="modified.txt",
#                                 fromfiledate="2020-02-19", tofiledate="2020-02-20"
#                                 )
#
#     # for line in diff:
#     #     print(line, end="")
#
#     print(diff_get_context_changed(config1=a, config2=b))
