import unittest
from app.utils import (
    check_ip,
    clear_line_feed_on_device_config,
    clear_clock_period_on_device_config,
    clear_config_patterns,
)


class TestUtils(unittest.TestCase):
    def test_check_ip_valid(self):
        self.assertTrue(check_ip("192.168.1.1"))
        self.assertTrue(check_ip("10.0.0.1"))
        self.assertTrue(check_ip("255.255.255.255"))

    def test_check_ip_invalid(self):
        self.assertFalse(check_ip("256.1.1.1"))
        self.assertFalse(check_ip("192.168.1"))
        self.assertFalse(check_ip("not an ip"))

    def test_clear_line_feed(self):
        config = "line1\n\nline2\n\n\nline3"
        expected = "line1\nline2\nline3"
        self.assertEqual(clear_line_feed_on_device_config(config), expected)

    def test_clear_clock_period(self):
        config = "ntp clock-period 12345\nsome other line\nntp clock-period 67890\n"
        expected = "some other line\n"
        self.assertEqual(clear_clock_period_on_device_config(config), expected)

    def test_clear_config_patterns(self):
        config = "! No configuration change since last restart\nntp clock-period 12345\nkeep this"
        patterns = [
            r"! No configuration change since last restart\s*",
            r"ntp\sclock-period\s[0-9]{1,30}\n",
        ]
        expected = "keep this"
        self.assertEqual(clear_config_patterns(config, patterns).strip(), expected)


if __name__ == "__main__":
    unittest.main()
