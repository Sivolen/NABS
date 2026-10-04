"""Tests of app/modules/access.py - parsing of client ids and the device access decision."""

import unittest

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.access import (  # noqa: E402
    can_access_device,
    has_admin_role,
    parse_id,
    role_of,
)


def make_session(rights="user", groups=(10,), user="someone"):
    data = {"rights": rights, "allowed_devices": list(groups)}
    if user is not None:
        data["user"] = user
    return data


class TestParseId(unittest.TestCase):
    def test_valid_ids(self):
        self.assertEqual(parse_id(5), 5)
        self.assertEqual(parse_id("5"), 5)
        self.assertEqual(parse_id(" 42 "), 42)
        self.assertEqual(parse_id(2**31 - 1), 2**31 - 1)

    def test_invalid_ids(self):
        bad = [
            None,
            "",
            " ",
            "abc",
            "5; DROP TABLE configs",
            "1.5",
            "-3",
            "0",
            0,
            -1,
            "٣",
            "5 5",
            True,
            False,
            2**31,
            2**40,
            [],
            {},
            1.0,
            b"5",
        ]
        for value in bad:
            self.assertIsNone(parse_id(value), repr(value))


class TestRoles(unittest.TestCase):
    def test_admin_roles(self):
        self.assertTrue(has_admin_role({"rights": "sadmin"}))
        self.assertTrue(has_admin_role({"rights": "admin"}))
        self.assertFalse(has_admin_role({"rights": "user"}))
        self.assertFalse(has_admin_role({"rights": ""}))
        self.assertFalse(has_admin_role({}))
        self.assertEqual(role_of({}), "")


class TestCanAccessDevice(unittest.TestCase):
    def test_sadmin_may_use_every_device_without_a_lookup(self):
        def lookup(groups, device_id):
            raise AssertionError("sadmin must not need the database lookup")

        self.assertTrue(can_access_device(make_session("sadmin", []), 5, lookup))

    def test_user_with_the_device_group(self):
        calls = []

        def lookup(groups, device_id):
            calls.append((groups, device_id))
            return True

        self.assertTrue(can_access_device(make_session("admin", [10, 11]), "5", lookup))
        self.assertEqual(calls, [([10, 11], 5)])

    def test_user_without_the_device_group(self):
        self.assertFalse(
            can_access_device(make_session("admin"), 5, lambda g, d: False)
        )

    def test_not_logged_in_is_never_allowed(self):
        self.assertFalse(can_access_device(make_session("sadmin", user=None), 5))
        self.assertFalse(can_access_device({}, 5, lambda g, d: True))

    def test_invalid_device_id_is_refused_without_a_lookup(self):
        def lookup(groups, device_id):
            raise AssertionError("lookup must not run for an invalid id")

        for value in (None, "abc", "0", "-1", "1;2", 2**40):
            self.assertFalse(
                can_access_device(make_session("sadmin"), value, lookup), value
            )
            self.assertFalse(
                can_access_device(make_session("admin"), value, lookup), value
            )

    def test_missing_or_empty_groups_are_refused(self):
        def lookup(groups, device_id):
            raise AssertionError("no groups - nothing to look up")

        for groups in ([], None, "10", 10):
            session_obj = {"user": "u", "rights": "user", "allowed_devices": groups}
            self.assertFalse(can_access_device(session_obj, 5, lookup), repr(groups))
        self.assertFalse(can_access_device({"user": "u", "rights": "user"}, 5, lookup))

    def test_an_error_in_the_lookup_is_a_refusal(self):
        def lookup(groups, device_id):
            raise RuntimeError("database is down")

        self.assertFalse(can_access_device(make_session("admin"), 5, lookup))


if __name__ == "__main__":
    unittest.main()
