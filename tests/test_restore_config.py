"""
TZ 9: the unfinished restore_config() route. Restoring a configuration is NOT implemented
here; a request must get a clear "not available" answer - never an HTTP 500 - and must not
change anything.
"""

import unittest
from unittest.mock import MagicMock, patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.views import restore_config as restore_view  # noqa: E402
from view_test_support import flashed, logged_in, make_test_app  # noqa: E402


class TestRestoreConfig(unittest.TestCase):
    def setUp(self):
        self.flask_app = make_test_app(
            [
                (
                    "/restore_config/",
                    "restore_config",
                    restore_view.restore_config,
                    ["GET", "POST"],
                )
            ]
        )
        self.flask_app.config[
            "PROPAGATE_EXCEPTIONS"
        ] = False  # a 500 must show up as a 500
        self.client = self.flask_app.test_client()
        # anything that could change data: a device connection or the database
        self.db = patch("app.modules.dbutils.db_utils.db", MagicMock()).start()
        self.addCleanup(patch.stopall)
        logged_in(self.client, "sadmin", [])

    def assert_nothing_changed(self):
        self.db.session.add.assert_not_called()
        self.db.session.commit.assert_not_called()
        self.db.session.delete.assert_not_called()

    def test_get_is_not_a_500(self):
        response = self.client.get("/restore_config/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/devices"))
        self.assertIn(restore_view.RESTORE_UNAVAILABLE, flashed(self.client))
        self.assert_nothing_changed()

    def test_post_is_not_a_500_and_does_nothing(self):
        response = self.client.post(
            "/restore_config/", data={"config_id": "5", "device_id": "3"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(restore_view.RESTORE_UNAVAILABLE, flashed(self.client))
        self.assert_nothing_changed()

    def test_a_json_client_gets_501_with_a_message(self):
        response = self.client.post(
            "/restore_config/", json={"config_id": 5, "device_id": 3}
        )
        self.assertEqual(response.status_code, 501)
        body = response.get_json()
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["message"], restore_view.RESTORE_UNAVAILABLE)
        self.assert_nothing_changed()

    def test_an_ajax_get_asking_for_json_gets_501(self):
        response = self.client.get(
            "/restore_config/", headers={"Accept": "application/json"}
        )
        self.assertEqual(response.status_code, 501)

    def test_odd_requests_are_never_a_500(self):
        # 501 (JSON clients) is the deliberate "not implemented" answer; 500 is the bug
        for kwargs in (
            {"data": "not a form"},
            {"data": {"config_id": "abc"}},
            {"json": {}},
            {"data": b"\xff\xfe", "content_type": "application/octet-stream"},
            {"content_type": "application/json", "data": "{broken json"},
        ):
            response = self.client.post("/restore_config/", **kwargs)
            self.assertIn(response.status_code, (302, 501), kwargs)
        self.assert_nothing_changed()

    def test_the_request_body_is_never_parsed(self):
        # a broken JSON body would be a 400 if the view tried to read it
        response = self.client.post(
            "/restore_config/", data="{broken json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 501)

    def test_not_logged_in_is_sent_to_login(self):
        anonymous = self.flask_app.test_client()
        response = anonymous.get("/restore_config/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_every_role_gets_the_same_harmless_answer(self):
        for role in ("sadmin", "admin", "user"):
            client = self.flask_app.test_client()
            logged_in(client, role, [10])
            self.assertEqual(client.get("/restore_config/").status_code, 302, role)

    def test_a_session_without_a_valid_role_is_refused_not_a_500(self):
        with self.client.session_transaction() as session:
            session["rights"] = ""
        response = self.client.get("/restore_config/")
        self.assertLess(response.status_code, 500)
        self.assertIn(b"Access dined", response.data)

    def test_the_route_still_exists_for_a_future_implementation(self):
        routes = (nabs_test_stubs.ROOT / "app" / "routes.py").read_text()
        self.assertIn('"/restore_config/"', routes)
        source = (
            nabs_test_stubs.ROOT / "app" / "views" / "restore_config.py"
        ).read_text()
        for forbidden in (
            "configure replace",
            "no ",
            "netmiko",
            "napalm",
            "send_config",
            "db.session",
        ):
            self.assertNotIn(
                forbidden,
                source.replace(
                    "# Restoring a configuration on a device is NOT implemented", ""
                ),
            )


if __name__ == "__main__":
    unittest.main()
