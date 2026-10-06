"""
TZ 3.1 / 3.3: a configuration can only be deleted through the device it belongs to.

Layer 1 - the database function: one DELETE restricted by BOTH config_id and device_id.
Layer 2 - the views (the comparison page and the config page): authorization first,
          the client ids are never trusted, and a refused request changes nothing.
"""

import unittest
from unittest.mock import MagicMock, patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.dbutils import db_utils  # noqa: E402
from app.views import config as config_view  # noqa: E402
from app.views import diff as diff_view  # noqa: E402
from view_test_support import flashed, logged_in, make_test_app  # noqa: E402

GROUP_LOOKUP = "app.modules.dbutils.db_users_permission.check_allowed_device"


class TestDeleteConfigForDevice(unittest.TestCase):
    """The database function (Configs / db are mocked, as in the other db tests)."""

    def setUp(self):
        # the delete first asks the Restore Engine whether a job still needs the config;
        # these tests are about the ownership check, so nothing is protected here
        patcher = patch(
            "app.modules.dbutils.db_utils.get_restore_protected_config_ids",
            return_value=set(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("app.modules.dbutils.db_utils.db")
    @patch("app.modules.dbutils.db_utils.Configs")
    def test_deletes_own_config_with_one_query_on_both_ids(self, configs, db):
        configs.query.filter_by.return_value.delete.return_value = 1
        self.assertTrue(db_utils.delete_config_for_device("7", "3"))
        configs.query.filter_by.assert_called_once_with(id=7, device_id=3)
        db.session.commit.assert_called_once()
        db.session.rollback.assert_not_called()

    @patch("app.modules.dbutils.db_utils.db")
    @patch("app.modules.dbutils.db_utils.Configs")
    def test_config_of_another_device_is_not_deleted(self, configs, db):
        # the id was swapped on the client: the row exists, but for another device,
        # so the DELETE ... WHERE id=999 AND device_id=3 matches nothing
        configs.query.filter_by.return_value.delete.return_value = 0
        self.assertFalse(db_utils.delete_config_for_device(999, 3))
        configs.query.filter_by.assert_called_once_with(id=999, device_id=3)
        db.session.commit.assert_not_called()
        db.session.rollback.assert_called_once()

    @patch("app.modules.dbutils.db_utils.db")
    @patch("app.modules.dbutils.db_utils.Configs")
    def test_nonexistent_config(self, configs, db):
        configs.query.filter_by.return_value.delete.return_value = 0
        self.assertFalse(db_utils.delete_config_for_device(123456, 3))
        db.session.commit.assert_not_called()

    @patch("app.modules.dbutils.db_utils.db")
    @patch("app.modules.dbutils.db_utils.Configs")
    def test_invalid_ids_do_not_reach_the_database(self, configs, db):
        for config_id, device_id in (
            ("abc", 3),
            (None, 3),
            (7, None),
            (7, "x"),
            ("", ""),
        ):
            self.assertFalse(db_utils.delete_config_for_device(config_id, device_id))
        configs.query.filter_by.assert_not_called()
        db.session.commit.assert_not_called()

    @patch("app.modules.dbutils.db_utils.db")
    @patch("app.modules.dbutils.db_utils.Configs")
    def test_more_than_one_row_is_rolled_back(self, configs, db):
        configs.query.filter_by.return_value.delete.return_value = 2
        self.assertFalse(db_utils.delete_config_for_device(7, 3))
        db.session.commit.assert_not_called()
        db.session.rollback.assert_called_once()

    @patch("app.modules.dbutils.db_utils.db")
    @patch("app.modules.dbutils.db_utils.Configs")
    def test_database_error_is_rolled_back_and_returns_false(self, configs, db):
        configs.query.filter_by.return_value.delete.side_effect = RuntimeError("boom")
        self.assertFalse(db_utils.delete_config_for_device(7, 3))
        db.session.rollback.assert_called_once()
        db.session.commit.assert_not_called()


class ViewTestBase(unittest.TestCase):
    """The REAL diff_page view behind the REAL decorators; only the database is mocked."""

    def setUp(self):
        self.flask_app = make_test_app(
            [
                (
                    "/diff_page/<device_id>",
                    "diff_page",
                    diff_view.diff_page,
                    ["GET", "POST"],
                )
            ]
        )
        self.client = self.flask_app.test_client()
        patches = {
            "check_if_previous_configuration_exists": True,
            "get_all_cfg_timestamp_for_device": [],
            "get_last_config_for_device": {
                "last_config": "x",
                "id": 9,
                "timestamp": "t",
            },
            "get_last_env_for_device": {},
        }
        for name, value in patches.items():
            p = patch(f"app.views.diff.{name}", return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.delete = patch("app.views.diff.delete_config_for_device").start()
        self.addCleanup(patch.stopall)

    def post(self, device="3", config="7"):
        return self.client.post(f"/diff_page/{device}", data={"del_config_btn": config})


class TestDiffPageConfigDeletion(ViewTestBase):
    def test_authorized_user_deletes_a_config_of_the_device(self):
        logged_in(self.client, "admin", [10])
        self.delete.return_value = True
        with patch(GROUP_LOOKUP, return_value=True):
            response = self.post("3", "7")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/diff_page/3"))
        self.delete.assert_called_once_with(config_id=7, device_id=3)
        self.assertIn("Config deleted", flashed(self.client))

    def test_sadmin_deletes_without_group_membership(self):
        logged_in(self.client, "sadmin", [])
        self.delete.return_value = True
        response = self.post("3", "7")
        self.assertEqual(response.status_code, 302)
        self.delete.assert_called_once_with(config_id=7, device_id=3)

    def test_swapped_config_id_is_always_scoped_to_the_url_device(self):
        # the user may use device 3; the form carries the id of a config of device 4.
        # The view must ask the database for (config 999, device 3) - never for device 4 -
        # and a "not found for this device" answer must be a plain failure.
        logged_in(self.client, "admin", [10])
        self.delete.return_value = False
        with patch(GROUP_LOOKUP, return_value=True):
            response = self.post("3", "999")
        self.assertEqual(response.status_code, 302)
        self.delete.assert_called_once_with(config_id=999, device_id=3)
        self.assertIn("Delete error", flashed(self.client))
        self.assertNotIn("Config deleted", flashed(self.client))

    def test_nonexistent_config(self):
        logged_in(self.client, "admin", [10])
        self.delete.return_value = False
        with patch(GROUP_LOOKUP, return_value=True):
            response = self.post("3", "424242")
        self.assertEqual(response.status_code, 302)
        self.assertIn("Delete error", flashed(self.client))

    def test_user_without_rights_for_the_device_changes_nothing(self):
        logged_in(self.client, "admin", [10])
        with patch(GROUP_LOOKUP, return_value=False):
            response = self.post("3", "7")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/devices"))
        self.delete.assert_not_called()

    def test_user_without_any_groups_changes_nothing(self):
        logged_in(self.client, "user", [])
        response = self.post("3", "7")
        self.assertEqual(response.status_code, 302)
        self.delete.assert_not_called()

    def test_not_logged_in_is_sent_to_login(self):
        response = self.post("3", "7")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        self.delete.assert_not_called()

    def test_malformed_config_id_never_reaches_the_database(self):
        logged_in(self.client, "sadmin", [])
        for bad in (
            "abc",
            "1; DROP TABLE configs",
            "-1",
            "0",
            " ",
            "7.5",
            "99999999999999",
        ):
            response = self.post("3", bad)
            self.assertEqual(response.status_code, 302, bad)
        self.delete.assert_not_called()

    def test_malformed_device_id_in_the_url_is_a_refusal_not_a_500(self):
        logged_in(self.client, "sadmin", [])
        for bad in ("abc", "0", "-5", "1;2"):
            response = self.post(bad, "7")
            self.assertEqual(response.status_code, 302, bad)
        self.delete.assert_not_called()

    def test_session_without_allowed_devices_is_a_refusal_not_a_500(self):
        with self.client.session_transaction() as session:
            session["user"] = "x"
            session["rights"] = "admin"  # no "allowed_devices" key at all
        response = self.post("3", "7")
        self.assertEqual(response.status_code, 302)
        self.delete.assert_not_called()

    def test_the_handler_refuses_on_its_own_even_without_the_decorator(self):
        # defence in depth: handle_config_deletion() does not rely on the decorator
        from flask import session

        with self.flask_app.test_request_context("/diff_page/3", method="POST"):
            session["user"] = "u"
            session["rights"] = "user"
            session["allowed_devices"] = [10]
            with patch(GROUP_LOOKUP, return_value=False):
                response = diff_view.handle_config_deletion("7", "u", "3")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/devices"))
        self.delete.assert_not_called()

    def test_error_inside_the_delete_is_handled(self):
        logged_in(self.client, "sadmin", [])
        self.delete.side_effect = RuntimeError("db down")
        response = self.post("3", "7")
        self.assertEqual(response.status_code, 302)
        self.assertIn("Server error", flashed(self.client))


class TestConfigPageConfigDeletion(unittest.TestCase):
    """The same rules on the config page (it had the same unscoped delete)."""

    def setUp(self):
        self.flask_app = make_test_app(
            [
                (
                    "/config_page/<device_id>",
                    "config",
                    config_view.config,
                    ["GET", "POST"],
                )
            ]
        )
        self.client = self.flask_app.test_client()
        self.delete = patch("app.views.config.delete_config_for_device").start()
        self.addCleanup(patch.stopall)

    def post(self, device="3", config="7"):
        return self.client.post(
            f"/config_page/{device}", data={"del_config_btn": config}
        )

    def test_deletes_with_the_device_from_the_url(self):
        logged_in(self.client, "admin", [10])
        self.delete.return_value = True
        with patch(GROUP_LOOKUP, return_value=True):
            response = self.post("3", "7")
        self.assertEqual(response.status_code, 302)
        self.delete.assert_called_once_with(config_id=7, device_id=3)
        self.assertIn("Config has been deleted", flashed(self.client))

    def test_foreign_config_is_a_failure(self):
        logged_in(self.client, "admin", [10])
        self.delete.return_value = False
        with patch(GROUP_LOOKUP, return_value=True):
            self.post("3", "999")
        self.delete.assert_called_once_with(config_id=999, device_id=3)
        self.assertIn("Delete config error", flashed(self.client))

    def test_no_rights_for_the_device(self):
        logged_in(self.client, "user", [10])
        with patch(GROUP_LOOKUP, return_value=False):
            response = self.post("3", "7")
        self.assertEqual(response.status_code, 302)
        self.delete.assert_not_called()

    def test_malformed_config_id(self):
        logged_in(self.client, "sadmin", [])
        for bad in ("abc", "-1", "0", "1 OR 1=1"):
            self.post("3", bad)
        self.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
