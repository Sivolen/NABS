import os
import unittest
from app.modules.differ import diff_changed, get_diff_summary

os.environ["FLASK_ENV"] = "testing"


class TestDiffer(unittest.TestCase):
    def test_diff_changed_same_configs(self):
        config1 = "line1\nline2\nline3"
        config2 = "line1\nline2\nline3"
        self.assertTrue(diff_changed(config1, config2))

    def test_diff_changed_different_configs(self):
        config1 = "line1\nline2\nline3"
        config2 = "line1\nline2\nline3\nline4"
        self.assertFalse(diff_changed(config1, config2))

    def test_diff_changed_different_spaces(self):
        config1 = "line1\nline2  \nline3"
        config2 = "line1\nline2\nline3"
        self.assertTrue(diff_changed(config1, config2))  # rstrip() убирает пробелы

    def test_get_diff_summary_limit(self):
        old = "line1\nline2\nline3\nline4\nline5"
        new = "line1\nline2\nline3\nline4\nline5\nline6"
        diff, truncated = get_diff_summary(old, new, max_lines=2)
        self.assertTrue(truncated)
        self.assertIn("... (truncated", diff)

    def test_get_diff_summary_no_truncation(self):
        old = "line1\nline2\nline3"
        new = "line1\nline2\nline3\nline4"
        diff, truncated = get_diff_summary(old, new, max_lines=10)
        self.assertFalse(truncated)
        self.assertNotIn("truncated", diff)


if __name__ == "__main__":
    unittest.main()
