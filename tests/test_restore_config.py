"""
The old /restore_config/ URL. Restoring is done by the Restore pages now: this route only
forwards to the "new restore" page when it gets a device and a configuration, and never
starts or changes anything itself (no database, no device).
"""

import unittest
from unittest.mock import MagicMock, patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.views import restore_config as restore_view  # noqa: E402
from view_test_support import flashed, logged_in, make_test_app  # noqa: E402


class TestRestoreConfigCompatRoute(unittest.TestCase):
    def setUp(self):
        self.flask_app = make_test_app(
            [
                (
                    "/restore_config/",
                    "restore_config",
                    restore_view.restore_config,
                    ["GET", "POST"],
                ),
                ("/restore/new", "restore_new", lambda: "new page", ["GET", "POST"]),
            ]
        )
        self.flask_app.config[
            "PROPAGATE_EXCEPTIONS"
        ] = False  # a 500 must show up as a 500
        self.client = self.flask_app.test_client()
        self.db = patch("app.modules.dbutils.db_utils.db", MagicMock()).start()
        self.addCleanup(patch.stopall)
        logged_in(self.client, "sadmin", [])

    def assert_nothing_changed(self):
        self.db.session.add.assert_not_called()
        self.db.session.commit.assert_not_called()
        self.db.session.delete.assert_not_called()

    def test_without_ids_it_explains_where_to_start(self):
        for response in (
            self.client.get("/restore_config/"),
            self.client.post("/restore_config/"),
        ):
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers["Location"].endswith("/devices"))
        self.assertTrue(any("Restore" in m for m in flashed(self.client)))
        self.assert_nothing_changed()

    def test_with_ids_it_only_forwards_to_the_new_restore_page(self):
        response = self.client.post(
            "/restore_config/", data={"config_id": "5", "device_id": "3"}
        )
        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        self.assertIn("/restore/new", location)
        self.assertIn("device_id=3", location)
        self.assertIn("config_id=5", location)
        self.assert_nothing_changed()

    def test_odd_requests_are_never_a_500(self):
        for kwargs in (
            {"data": "not a form"},
            {"data": {"config_id": "abc"}},
            {"json": {}},
            {"data": b"\xff\xfe", "content_type": "application/octet-stream"},
            {"content_type": "application/json", "data": "{broken json"},
        ):
            self.assertEqual(
                self.client.post("/restore_config/", **kwargs).status_code, 302, kwargs
            )
        self.assert_nothing_changed()

    def test_not_logged_in_is_sent_to_login(self):
        response = self.flask_app.test_client().get("/restore_config/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_the_route_still_exists_and_has_no_device_or_database_code(self):
        routes = (nabs_test_stubs.ROOT / "app" / "routes.py").read_text()
        self.assertIn('"/restore_config/"', routes)
        source = (
            nabs_test_stubs.ROOT / "app" / "views" / "restore_config.py"
        ).read_text()
        for forbidden in (
            "netmiko",
            "napalm",
            "send_config",
            "db.session",
            "configure replace",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
