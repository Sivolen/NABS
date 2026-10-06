"""
TZ 3.2: every route that changes or exposes data of a device checks that the CURRENT
user may use THAT device (and the role, where the UI already restricts the action).
The REAL view functions run behind the REAL decorators; only the database is mocked.
A refused request must not call any function that changes data.
"""

import io
import unittest
from unittest.mock import patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.views import device_setting as device_setting_view  # noqa: E402
from app.views import device_status as device_status_view  # noqa: E402
from app.views import device_validation as validation_view  # noqa: E402
from app.views import devices as devices_view  # noqa: E402
from app.views import diff_configs as diff_configs_view  # noqa: E402
from app.views import previous_config as previous_config_view  # noqa: E402
from view_test_support import flashed, logged_in, make_test_app  # noqa: E402

GROUP_LOOKUP = "app.modules.dbutils.db_users_permission.check_allowed_device"


def own_device():  # the user's groups contain the device
    return patch(GROUP_LOOKUP, return_value=True)


def foreign_device():  # the device belongs to other groups
    return patch(GROUP_LOOKUP, return_value=False)


class TestDevicesPageGuards(unittest.TestCase):
    """add / edit / delete a device: admin+ only, and only devices of the user's groups."""

    def setUp(self):
        self.flask_app = make_test_app(
            [("/devices", "devices", devices_view.devices, ["GET", "POST"])]
        )
        self.client = self.flask_app.test_client()
        self.add = patch("app.views.devices.add_device").start()
        self.update = patch("app.views.devices.update_device").start()
        self.delete = patch("app.views.devices.delete_device").start()
        self.switch = patch("app.views.devices.update_driver_switch_status").start()
        self.profile = patch("app.views.devices.get_credentials").start()
        self.group_ok = patch("app.views.devices.is_group_allowed_for_user").start()
        self.profile.return_value = {"credentials_user_group": 10}
        self.group_ok.return_value = True
        self.addCleanup(patch.stopall)

    def assert_nothing_changed(self):
        for mock in (self.add, self.update, self.delete, self.switch):
            mock.assert_not_called()

    ADD = {
        "add_device_btn": "1",
        "device_group": "1",
        "add_hostname": "sw1",
        "add_ipaddress": "10.0.0.1",
        "add_platform": "huawei_vrp",
        "add_port": "22",
        "add_credentials_profile": "5",
    }
    EDIT = {
        "edit_device_btn": "3",
        "device-group": "1",
        "hostname": "sw1",
        "ipaddress": "10.0.0.1",
        "platform": "huawei_vrp",
        "port": "22",
        "credentials_profile": "5",
        "user-group": "10",
    }

    # ---- delete
    def test_plain_user_cannot_delete_a_device(self):
        logged_in(self.client, "user", [10])
        with own_device():
            response = self.client.post("/devices", data={"del_device_btn": "3"})
        self.assertEqual(response.status_code, 302)
        self.assert_nothing_changed()
        self.assertIn("You are not allowed to do this", flashed(self.client))

    def test_admin_cannot_delete_a_device_of_other_groups(self):
        logged_in(self.client, "admin", [10])
        with foreign_device():
            self.client.post("/devices", data={"del_device_btn": "3"})
        self.assert_nothing_changed()

    def test_admin_deletes_own_device(self):
        logged_in(self.client, "admin", [10])
        self.delete.return_value = True
        with own_device():
            self.client.post("/devices", data={"del_device_btn": "3"})
        self.delete.assert_called_once_with(device_id=3)

    def test_sadmin_deletes_any_device(self):
        logged_in(self.client, "sadmin", [])
        self.delete.return_value = True
        self.client.post("/devices", data={"del_device_btn": "3"})
        self.delete.assert_called_once_with(device_id=3)

    def test_malformed_device_id_is_refused(self):
        logged_in(self.client, "sadmin", [])
        for bad in ("abc", "0", "-1", "3 OR 1=1"):
            response = self.client.post("/devices", data={"del_device_btn": bad})
            self.assertEqual(response.status_code, 302, bad)
        self.assert_nothing_changed()

    # ---- edit
    def test_plain_user_cannot_edit_a_device(self):
        logged_in(self.client, "user", [10])
        with own_device():
            self.client.post("/devices", data=self.EDIT)
        self.assert_nothing_changed()

    def test_admin_cannot_edit_a_device_of_other_groups(self):
        logged_in(self.client, "admin", [10])
        with foreign_device():
            self.client.post("/devices", data=self.EDIT)
        self.assert_nothing_changed()  # not even the driver switch is touched

    def test_admin_cannot_attach_credentials_of_a_foreign_group(self):
        logged_in(self.client, "admin", [10])
        self.group_ok.return_value = False
        with own_device():
            self.client.post("/devices", data=self.EDIT)
        self.assert_nothing_changed()

    def test_unknown_credentials_profile_is_refused(self):
        logged_in(self.client, "admin", [10])
        self.profile.return_value = None
        with own_device():
            self.client.post("/devices", data=self.EDIT)
        self.assert_nothing_changed()

    # ---- add
    def test_plain_user_cannot_add_a_device(self):
        logged_in(self.client, "user", [10])
        self.client.post("/devices", data=self.ADD)
        self.assert_nothing_changed()

    def test_admin_cannot_add_a_device_with_foreign_credentials(self):
        logged_in(self.client, "admin", [10])
        self.group_ok.return_value = False
        self.client.post("/devices", data=self.ADD)
        self.assert_nothing_changed()

    def test_not_logged_in(self):
        response = self.client.post("/devices", data={"del_device_btn": "3"})
        self.assertIn("/login", response.headers["Location"])
        self.assert_nothing_changed()


class TestUploadConfigGuards(unittest.TestCase):
    def setUp(self):
        self.flask_app = make_test_app(
            [
                (
                    "/upload_config/",
                    "upload_config_route",
                    devices_view.upload_config_route,
                    ["POST"],
                )
            ]
        )
        self.client = self.flask_app.test_client()
        self.process = patch("app.views.devices.process_uploaded_config").start()
        self.process.return_value = ({"status": "ok"}, 200)
        self.addCleanup(patch.stopall)

    def upload(self, device_id="3"):
        return self.client.post(
            "/upload_config/",
            data={
                "device_id": device_id,
                "config_file": (io.BytesIO(b"sysname x"), "c.txt"),
            },
            content_type="multipart/form-data",
        )

    def test_anonymous_upload_is_refused(self):
        response = self.upload()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        self.process.assert_not_called()

    def test_upload_for_a_foreign_device_is_refused(self):
        logged_in(self.client, "admin", [10])
        with foreign_device():
            response = self.upload("3")
        self.assertEqual(response.status_code, 403)
        self.process.assert_not_called()

    def test_malformed_device_id(self):
        logged_in(self.client, "sadmin", [])
        for bad in ("abc", "0", "-1"):
            self.assertEqual(self.upload(bad).status_code, 400, bad)
        self.process.assert_not_called()

    def test_upload_for_own_device_is_processed(self):
        logged_in(self.client, "user", [10])
        with own_device():
            self.upload("3")
        self.process.assert_called_once()


class TestAjaxReadGuards(unittest.TestCase):
    """The AJAX endpoints that take a device_id from the request body."""

    def setUp(self):
        self.flask_app = make_test_app(
            [
                (
                    "/previous_config/",
                    "previous_config",
                    previous_config_view.previous_config,
                    ["POST"],
                ),
                (
                    "/diff_configs/",
                    "diff_configs",
                    diff_configs_view.diff_configs,
                    ["POST"],
                ),
                (
                    "/device_settings/",
                    "device_settings",
                    device_setting_view.device_settings,
                    ["POST"],
                ),
            ]
        )
        self.client = self.flask_app.test_client()
        self.previous = patch("app.views.previous_config.get_previous_config").start()
        self.last = patch(
            "app.views.previous_config.get_last_config_for_device"
        ).start()
        self.previous.return_value = {
            "id": 1,
            "device_config": "a\nb",
            "timestamp": "t",
        }
        self.last.return_value = {"last_config": "a\nc"}
        self.setting = patch("app.views.device_setting.get_device_setting").start()
        self.addCleanup(patch.stopall)

    def test_previous_config_of_a_foreign_device_is_refused(self):
        logged_in(self.client, "admin", [10])
        with foreign_device():
            response = self.client.post(
                "/previous_config/", json={"device_id": 3, "date": "t"}
            )
        self.assertEqual(response.status_code, 403)
        self.previous.assert_not_called()

    def test_previous_config_of_own_device(self):
        logged_in(self.client, "admin", [10])
        with own_device():
            response = self.client.post(
                "/previous_config/", json={"device_id": "3", "date": "t"}
            )
        self.assertEqual(response.status_code, 200)
        self.previous.assert_called_once_with(device_id=3, db_timestamp="t")

    def test_previous_config_bad_requests(self):
        logged_in(self.client, "sadmin", [])
        for body in (
            {},
            {"device_id": "x", "date": "t"},
            {"device_id": 3},
            {"date": "t"},
        ):
            self.assertEqual(
                self.client.post("/previous_config/", json=body).status_code, 400, body
            )
        self.previous.assert_not_called()

    def test_previous_config_anonymous(self):
        response = self.client.post(
            "/previous_config/", json={"device_id": 3, "date": "t"}
        )
        self.assertEqual(response.status_code, 302)
        self.previous.assert_not_called()

    def test_diff_configs_of_a_foreign_device_is_refused(self):
        logged_in(self.client, "user", [10])
        with patch(
            "app.views.diff_configs.get_previous_config"
        ) as previous, foreign_device():
            response = self.client.post(
                "/diff_configs/", json={"device_id": 3, "date": "t"}
            )
        self.assertEqual(response.status_code, 403)
        previous.assert_not_called()

    def test_diff_configs_bad_request(self):
        logged_in(self.client, "sadmin", [])
        self.assertEqual(
            self.client.post("/diff_configs/", json={"date": "t"}).status_code, 400
        )

    def test_device_settings_of_a_foreign_device_are_refused(self):
        logged_in(self.client, "admin", [10])
        with foreign_device():
            response = self.client.post("/device_settings/", json={"device_id": 3})
        self.assertEqual(response.status_code, 403)
        self.setting.assert_not_called()


class TestDeviceStatusGuard(unittest.TestCase):
    def setUp(self):
        self.flask_app = make_test_app(
            [
                (
                    "/device_status/",
                    "device_status",
                    device_status_view.device_status,
                    ["POST"],
                )
            ]
        )
        self.client = self.flask_app.test_client()
        self.backup = patch("app.views.device_status.run_backup_config_on_db").start()
        patch("app.views.device_status.get_device_id", return_value=(3,)).start()
        patch(
            "app.views.device_status.get_device_is_enabled", return_value=True
        ).start()
        self.addCleanup(patch.stopall)

    def test_status_of_a_foreign_device_does_not_start_a_backup(self):
        logged_in(self.client, "user", [10])
        with foreign_device():
            response = self.client.post("/device_status/", json={"device": "10.0.0.1"})
        self.assertEqual(response.status_code, 403)
        self.backup.assert_not_called()


class TestValidationGuards(unittest.TestCase):
    def setUp(self):
        v = validation_view
        self.flask_app = make_test_app(
            [
                (
                    "/api/validation_run/<device_id>",
                    "api_validation_run",
                    v.api_validation_run,
                    ["POST"],
                ),
                (
                    "/api/validation_disable/<device_id>",
                    "api_validation_disable",
                    v.api_validation_disable,
                    ["POST"],
                ),
                (
                    "/api/validation_enable/<device_id>",
                    "api_validation_enable",
                    v.api_validation_enable,
                    ["POST"],
                ),
                (
                    "/api/validation_status/<device_id>",
                    "api_validation_status",
                    v.api_validation_status,
                    ["GET"],
                ),
                (
                    "/api/validation_history/<device_id>",
                    "api_validation_history",
                    v.api_validation_history,
                    ["GET"],
                ),
            ]
        )
        self.client = self.flask_app.test_client()
        self.run = patch("app.views.device_validation.run_validation").start()
        self.disable = patch("app.views.device_validation.disable_validation").start()
        self.enable = patch("app.views.device_validation.enable_validation").start()
        patch(
            "app.views.device_validation.get_last_config_for_device",
            return_value={"last_config": "x"},
        ).start()
        self.status = patch(
            "app.views.device_validation.get_device_validation_status",
            return_value=None,
        ).start()
        self.history = patch(
            "app.views.device_validation.get_device_validation_history", return_value=[]
        ).start()
        self.addCleanup(patch.stopall)

    def test_foreign_device_changes_nothing(self):
        logged_in(self.client, "admin", [10])
        with foreign_device():
            for action in ("run", "disable", "enable"):
                response = self.client.post(f"/api/validation_{action}/3")
                self.assertEqual(response.status_code, 403, action)
            self.assertEqual(
                self.client.get("/api/validation_status/3").status_code, 403
            )
            self.assertEqual(
                self.client.get("/api/validation_history/3").status_code, 403
            )
        self.run.assert_not_called()
        self.disable.assert_not_called()
        self.enable.assert_not_called()
        self.status.assert_not_called()
        self.history.assert_not_called()

    def test_own_device_works(self):
        logged_in(self.client, "admin", [10])
        with own_device():
            self.assertEqual(self.client.post("/api/validation_run/3").status_code, 200)
            self.assertEqual(
                self.client.post("/api/validation_disable/3").status_code, 200
            )
            self.assertEqual(
                self.client.post("/api/validation_enable/3").status_code, 200
            )
            self.assertEqual(
                self.client.get("/api/validation_status/3").status_code, 200
            )
        self.run.assert_called_once()
        self.disable.assert_called_once()
        self.enable.assert_called_once()

    def test_malformed_device_id(self):
        logged_in(self.client, "sadmin", [])
        for bad in ("abc", "0", "-1"):
            self.assertEqual(
                self.client.post(f"/api/validation_run/{bad}").status_code, 403, bad
            )
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
