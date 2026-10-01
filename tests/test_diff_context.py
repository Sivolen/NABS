import os
import unittest
from unittest.mock import patch

from app.modules.diff_context import (
    DEFAULT_BLOCK_DELIMITERS,
    get_block_delimiters,
    get_diff_context_settings,
    normalize_delimiters,
)

os.environ["FLASK_ENV"] = "testing"

MODULE = "app.modules.diff_context"


def fake_config(**options):
    """Replaces config.py options; a missing option gives the default."""

    def read(name, default):
        return options.get(name, default)

    return patch(f"{MODULE}._read_config", side_effect=read)


class TestNormalizeDelimiters(unittest.TestCase):
    def test_string_becomes_list(self):
        self.assertEqual(normalize_delimiters("#"), ["#"])

    def test_list_is_stripped_and_deduplicated(self):
        self.assertEqual(normalize_delimiters([" ## ", "#", "#", ""]), ["##", "#"])

    def test_junk_gives_empty_list(self):
        self.assertEqual(normalize_delimiters(None), [])
        self.assertEqual(normalize_delimiters(5), [])
        self.assertEqual(normalize_delimiters([None, 1, "  "]), [])


class TestGetBlockDelimiters(unittest.TestCase):
    MAPPING = {"huawei": ["#"], "Cisco": "!", "arista": ["!"], "juniper": ["##"]}

    def test_vendor_is_case_insensitive(self):
        self.assertEqual(get_block_delimiters("Huawei", self.MAPPING), ["#"])
        self.assertEqual(get_block_delimiters("HUAWEI", self.MAPPING), ["#"])
        # the key in config.py is case-insensitive as well
        self.assertEqual(get_block_delimiters("cisco", self.MAPPING), ["!"])

    def test_vendor_with_extra_words(self):
        vendor = "Cisco Systems, Inc."
        self.assertEqual(get_block_delimiters(vendor, self.MAPPING), ["!"])

    def test_unknown_or_empty_vendor(self):
        self.assertEqual(get_block_delimiters("Eltex", self.MAPPING), [])
        self.assertEqual(get_block_delimiters(None, self.MAPPING), [])
        self.assertEqual(get_block_delimiters("", self.MAPPING), [])
        self.assertEqual(get_block_delimiters("Vendor not defined", self.MAPPING), [])

    def test_bad_mapping_does_not_crash(self):
        self.assertEqual(get_block_delimiters("Huawei", "oops"), [])

    def test_new_vendor_needs_only_config(self):
        mapping = dict(self.MAPPING, mikrotik=["# ---"])
        self.assertEqual(get_block_delimiters("MikroTik", mapping), ["# ---"])

    def test_default_mapping_from_config_when_not_given(self):
        with fake_config(CONFIG_BLOCK_DELIMITERS={"huawei": ["#", "##"]}):
            self.assertEqual(get_block_delimiters("Huawei"), ["#", "##"])


class TestGetDiffContextSettings(unittest.TestCase):
    def test_defaults_for_config_without_new_options(self):
        with fake_config():
            settings = get_diff_context_settings("Huawei")
        self.assertEqual(
            settings,
            {
                "enabled": True,
                "delimiters": ["#"],
                "context_lines": 3,
                "max_block_lines": 30,
            },
        )

    def test_vendor_without_delimiters_uses_lines(self):
        with fake_config():
            settings = get_diff_context_settings("Eltex")
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["delimiters"], [])

    def test_global_switch_disables_blocks(self):
        with fake_config(USE_CONFIG_BLOCK_CONTEXT=False, DIFF_CONTEXT_LINES=5):
            settings = get_diff_context_settings("Huawei")
        self.assertEqual(
            settings,
            {
                "enabled": False,
                "delimiters": [],
                "context_lines": 5,
                "max_block_lines": 30,
            },
        )

    def test_invalid_context_lines_fall_back(self):
        for bad in ("many", None, -2):
            with fake_config(DIFF_CONTEXT_LINES=bad):
                self.assertEqual(get_diff_context_settings("Cisco")["context_lines"], 3)

    def test_max_block_lines(self):
        with fake_config(MAX_BLOCK_CONTEXT_LINES=50):
            self.assertEqual(get_diff_context_settings("Huawei")["max_block_lines"], 50)
        # 0 is valid: never cut a block
        with fake_config(MAX_BLOCK_CONTEXT_LINES=0):
            self.assertEqual(get_diff_context_settings("Huawei")["max_block_lines"], 0)

    def test_invalid_max_block_lines_fall_back(self):
        for bad in ("many", None, -1):
            with fake_config(MAX_BLOCK_CONTEXT_LINES=bad):
                settings = get_diff_context_settings("Cisco")
                self.assertEqual(settings["max_block_lines"], 30)

    def test_default_mapping_has_only_confirmed_vendors(self):
        self.assertEqual(
            DEFAULT_BLOCK_DELIMITERS, {"huawei": ["#"], "cisco": ["!"]}
        )

    def test_vendor_spelling_uses_one_rule(self):
        with fake_config():
            for vendor in ("Huawei", "HUAWEI", "huawei", " huawei "):
                self.assertEqual(get_block_delimiters(vendor), ["#"], vendor)
            for vendor in ("Cisco", "CISCO", "cisco", "Cisco Systems, Inc."):
                self.assertEqual(get_block_delimiters(vendor), ["!"], vendor)

    def test_unconfirmed_vendors_use_lines_until_added_to_config(self):
        with fake_config():
            self.assertEqual(get_block_delimiters("Arista"), [])
            self.assertEqual(get_block_delimiters("Juniper"), [])
        with fake_config(CONFIG_BLOCK_DELIMITERS={"arista": ["!"]}):
            self.assertEqual(get_block_delimiters("Arista"), ["!"])


if __name__ == "__main__":
    unittest.main()
