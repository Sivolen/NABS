"""Restore Engine, stage 6: the profile pages and JSON endpoints (real views, real template)."""

import io
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.views import restore_profiles as view  # noqa: E402
from restore_test_support import profile_yaml  # noqa: E402
from test_restore_profile_service import ADMIN, SADMIN, Env, make_text  # noqa: E402
from view_test_support import flashed, logged_in, make_test_app  # noqa: E402

TEMPLATES = str(Path(__file__).resolve().parent.parent / "app" / "templates")
SECRET = "TOPSECRET-VALUE"


def make_ui_app():
    rules = [
        (
            "/restore_profiles/",
            "restore_profiles",
            view.restore_profiles,
            ["GET", "POST"],
        ),
        (
            "/restore_profiles/export/<source>/<key>",
            "export_restore_profile",
            view.export_restore_profile,
            ["GET"],
        ),
        (
            "/api/restore_profiles/validate",
            "api_restore_profile_validate",
            view.api_restore_profile_validate,
            ["POST"],
        ),
        (
            "/api/restore_profiles/import_preview",
            "api_restore_profile_import_preview",
            view.api_restore_profile_import_preview,
            ["POST"],
        ),
        (
            "/api/restore_profiles/assign_preview",
            "api_restore_profile_assign_preview",
            view.api_restore_profile_assign_preview,
            ["POST"],
        ),
        (
            "/api/restore_profiles/assign",
            "api_restore_profile_assign",
            view.api_restore_profile_assign,
            ["POST"],
        ),
        (
            "/api/restore_profiles/device/<device_id>",
            "api_restore_profile_device",
            view.api_restore_profile_device,
            ["GET"],
        ),
    ]
    flask_app = make_test_app(rules)
    flask_app.template_folder = TEMPLATES
    flask_app.jinja_env.globals.update(
        csrf_token=lambda: "tok", core_version="t", ui="t"
    )
    return flask_app


class UiCase(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.dir.cleanup)
        self.client = make_ui_app().test_client()
        patcher = patch.object(view, "_profile_service", lambda: self.env.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        devices = patch.object(
            view,
            "_devices_for_user",
            return_value=[
                {
                    "device_id": 1,
                    "hostname": "sw1",
                    "device_ip": "192.0.2.1",
                    "connection_driver": "mock_os",
                }
            ],
        )
        devices.start()
        self.addCleanup(devices.stop)
        logged_in(self.client, "admin", [5], user="anton")

    def post(self, **form):
        return self.client.post("/restore_profiles/", data=form)

    def add_user_profile(self, key="mine"):
        return self.env.service.create_profile(
            ADMIN, profile_yaml(lambda d: d.update(id=key, name="Mine"))
        )


class TestAccess(UiCase):
    def test_anonymous_goes_to_login(self):
        client = make_ui_app().test_client()
        response = client.get("/restore_profiles/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_plain_user_is_sent_away_and_nothing_changes(self):
        logged_in(self.client, "user", [5], user="bob")
        self.assertEqual(self.client.get("/restore_profiles/").status_code, 302)
        for form in (
            {"action": "create", "yaml_text": profile_yaml()},
            {"action": "copy", "source": "builtin", "key": "mock_builtin"},
            {"action": "delete", "source": "user", "key": "x"},
            {"action": "unassign", "device_id": "1"},
        ):
            response = self.post(**form)
            self.assertEqual(response.status_code, 302, form)
            self.assertIn("/devices", response.headers["Location"])
        self.assertEqual(self.env.repo.profiles, {})
        for url in ("/api/restore_profiles/validate", "/api/restore_profiles/assign"):
            self.assertEqual(
                self.client.post(
                    url,
                    json={
                        "text": "x",
                        "device_ids": [1],
                        "source": "builtin",
                        "key": "mock_builtin",
                    },
                ).status_code,
                403,
            )
        self.assertEqual(
            self.client.get("/api/restore_profiles/device/1").status_code, 403
        )
        self.assertEqual(
            self.client.get(
                "/restore_profiles/export/builtin/mock_builtin"
            ).status_code,
            302,
        )
        self.assertEqual(self.env.repo.assignments, {})


class TestPages(UiCase):
    def test_list_renders_both_kinds_and_filters(self):
        self.add_user_profile("mine")
        body = self.client.get("/restore_profiles/").get_data(as_text=True)
        self.assertIn("Mock built-in", body)
        self.assertIn("Mine", body)
        self.assertIn("built-in", body)
        only_user = self.client.get("/restore_profiles/?kind=user").get_data(
            as_text=True
        )
        self.assertNotIn("Mock built-in", only_user)
        self.assertIn(
            "Mine", self.client.get("/restore_profiles/?q=min").get_data(as_text=True)
        )

    def test_builtin_detail_is_read_only(self):
        body = self.client.get(
            "/restore_profiles/?source=builtin&key=mock_builtin"
        ).get_data(as_text=True)
        self.assertIn("read-only", body)
        self.assertIn("readonly", body)
        self.assertNotIn("Delete</button>", body)
        self.assertNotIn("bi-save", body)  # no Save button
        self.assertIn("schema_version", body)

    def test_user_detail_is_editable(self):
        self.add_user_profile("mine")
        body = self.client.get("/restore_profiles/?source=user&key=mine").get_data(
            as_text=True
        )
        self.assertIn("bi-save", body)
        self.assertIn("bi-trash", body)
        self.assertNotIn("readonly", body)

    def test_not_runnable_notice_without_an_implemented_adapter(self):
        env = Env(runnable=False)
        self.addCleanup(env.dir.cleanup)
        with patch.object(view, "_profile_service", lambda: env.service):
            body = self.client.get(
                "/restore_profiles/?source=builtin&key=mock_builtin"
            ).get_data(as_text=True)
        self.assertIn("cannot be used to restore anything yet", body)
        self.assertIn("not runnable", body)

    def test_unknown_profile_shows_the_list_with_a_message(self):
        response = self.client.get("/restore_profiles/?source=user&key=nope")
        self.assertEqual(response.status_code, 200)
        # the page itself shows (and so consumes) the flashed message
        self.assertIn("Profile not found", response.get_data(as_text=True))

    def test_names_are_escaped(self):
        self.env.service.create_profile(
            ADMIN,
            profile_yaml(
                lambda d: d.update(id="xss", name="<script>alert(1)</script>")
            ),
        )
        body = self.client.get("/restore_profiles/?source=user&key=xss").get_data(
            as_text=True
        )
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)

    def test_outdated_copies_are_announced(self):
        self.env.service.copy_profile(ADMIN, "builtin", "mock_builtin")
        self.env.write_builtin("mock_builtin", make_text(version=2))
        self.env.reload_builtin()
        body = self.client.get("/restore_profiles/").get_data(as_text=True)
        self.assertIn("older version of a built-in profile", body)
        self.assertIn("source updated", body)


class TestAssignDialog(UiCase):
    def body(self):
        return self.client.get(
            "/restore_profiles/?source=builtin&key=mock_builtin"
        ).get_data(as_text=True)

    def test_devices_are_a_checkbox_list_with_a_search_box_not_a_multi_select(self):
        body = self.body()
        self.assertNotIn("<select multiple", body)
        self.assertIn('id="assignSearch"', body)  # search at the top of the list
        self.assertIn('type="checkbox" value="1"', body)
        self.assertIn(
            'data-search="sw1 192.0.2.1 mock_os"', body
        )  # what the search matches
        self.assertIn("Select shown", body)
        self.assertIn('id="assignCount"', body)

    def test_the_script_reads_the_checkboxes(self):
        body = self.body()
        self.assertIn(".assign-check", body)
        self.assertNotIn("selectedOptions", body)

    def test_device_names_are_escaped(self):
        with patch.object(
            view,
            "_devices_for_user",
            return_value=[
                {
                    "device_id": 1,
                    "hostname": "<img src=x onerror=alert(1)>",
                    "device_ip": "1.1.1.1",
                    "connection_driver": "ios",
                }
            ],
        ):
            body = self.body()
        self.assertNotIn("<img src=x", body)
        self.assertIn("&lt;img src=x", body)

    def test_empty_device_list_says_so(self):
        with patch.object(view, "_devices_for_user", return_value=[]):
            self.assertIn("No devices available to you", self.body())


class TestActions(UiCase):
    def test_copy_then_redirect_to_the_copy(self):
        response = self.post(
            action="copy",
            source="builtin",
            key="mock_builtin",
            new_key="my_copy",
            new_name="My copy",
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("key=my_copy", response.headers["Location"])
        self.assertIn("my_copy", self.env.repo.profiles)

    def test_copy_with_a_taken_id_is_refused_with_a_message(self):
        response = self.post(
            action="copy", source="builtin", key="mock_builtin", new_key="mock_builtin"
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("mock_builtin" in m for m in flashed(self.client)))
        self.assertEqual(self.env.repo.profiles, {})

    def test_create_valid_and_invalid(self):
        self.assertEqual(
            self.post(
                action="create", yaml_text=profile_yaml(lambda d: d.update(id="fresh"))
            ).status_code,
            302,
        )
        self.assertIn("fresh", self.env.repo.profiles)
        bad = self.post(action="create", yaml_text="id: broken")
        self.assertEqual(bad.status_code, 400)
        self.assertIn(
            "id: broken", bad.get_data(as_text=True)
        )  # the text stays in the form
        self.assertNotIn("broken", self.env.repo.profiles)

    def test_update_saves_and_a_refused_save_keeps_the_users_text_and_shows_the_fields(
        self,
    ):
        self.add_user_profile("mine")
        sha = self.env.repo.profiles["mine"].content_sha256
        text = self.env.repo.profiles["mine"].content
        ok = self.post(
            action="update",
            source="user",
            key="mine",
            expected_sha256=sha,
            yaml_text=text.replace("Mine", "Renamed"),
        )
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(self.env.repo.profiles["mine"].profile_version, 2)

        broken = text.replace("apply_saved_config", "run_shell")
        sha = self.env.repo.profiles["mine"].content_sha256
        refused = self.post(
            action="update",
            source="user",
            key="mine",
            expected_sha256=sha,
            yaml_text=broken,
        )
        page = refused.get_data(as_text=True)
        self.assertEqual(refused.status_code, 400)
        self.assertIn("The profile was not saved", page)
        self.assertIn("restore.steps", page)  # the field path of the problem
        self.assertIn("run_shell", page)  # the user's text is still in the editor
        self.assertEqual(self.env.repo.profiles["mine"].profile_version, 2)

    def test_stale_save_is_a_conflict(self):
        self.add_user_profile("mine")
        text = self.env.repo.profiles["mine"].content
        response = self.post(
            action="update",
            source="user",
            key="mine",
            expected_sha256="stale",
            yaml_text=text,
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("changed by someone else", response.get_data(as_text=True))
        self.assertEqual(self.env.repo.profiles["mine"].profile_version, 1)

    def test_builtin_cannot_be_changed_or_deleted_through_the_ui(self):
        before = self.env.service.get_profile(ADMIN, "builtin", "mock_builtin")[
            "content"
        ]
        self.post(
            action="update",
            source="builtin",
            key="mock_builtin",
            expected_sha256="x",
            yaml_text=make_text(),
        )
        self.post(action="delete", source="builtin", key="mock_builtin")
        self.assertEqual(
            self.env.service.get_profile(ADMIN, "builtin", "mock_builtin")["content"],
            before,
        )
        self.assertEqual(self.env.repo.profiles, {})

    def test_delete_refused_while_assigned(self):
        self.add_user_profile("mine")
        self.env.service.assign(ADMIN, [1], "user", "mine")
        self.post(action="delete", source="user", key="mine")
        self.assertIn("mine", self.env.repo.profiles)
        self.assertIn("assigned to devices", "".join(flashed(self.client)))

    def test_import_upload(self):
        data = {
            "action": "import",
            "import_file": (
                io.BytesIO(profile_yaml(lambda d: d.update(id="imp")).encode()),
                "p.yaml",
            ),
        }
        response = self.client.post(
            "/restore_profiles/", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.env.repo.profiles["imp"].origin_kind, "import")
        self.assertEqual(self.env.repo.assignments, {})

    def test_import_rejects_bad_uploads(self):
        for payload in (
            b"\xff\xfe\x00bad",
            b"x" * 70000,
            profile_yaml(lambda d: d["adapter"].update(password=SECRET)).encode(),
        ):
            data = {"action": "import", "import_file": (io.BytesIO(payload), "p.yaml")}
            self.client.post(
                "/restore_profiles/", data=data, content_type="multipart/form-data"
            )
        self.assertEqual(self.env.repo.profiles, {})
        data = {"action": "import"}
        self.assertEqual(
            self.client.post(
                "/restore_profiles/", data=data, content_type="multipart/form-data"
            ).status_code,
            302,
        )
        self.assertIn("Choose a YAML file", flashed(self.client))

    def test_import_over_a_builtin_id_needs_another_id(self):
        data = {
            "action": "import",
            "import_file": (io.BytesIO(make_text().encode()), "p.yaml"),
        }
        self.client.post(
            "/restore_profiles/", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(self.env.repo.profiles, {})

    def test_unassign_and_unknown_action(self):
        self.add_user_profile("mine")
        self.env.service.assign(ADMIN, [1], "user", "mine")
        self.post(action="unassign", device_id="1", source="user", key="mine")
        self.assertEqual(self.env.repo.assignments, {})
        self.assertEqual(self.post(action="format_everything").status_code, 302)
        self.assertIn("Unknown action", flashed(self.client))


class TestExportAndApi(UiCase):
    def test_export_is_a_yaml_attachment(self):
        response = self.client.get("/restore_profiles/export/builtin/mock_builtin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "attachment; filename=mock_builtin.yaml",
            response.headers["Content-Disposition"],
        )
        self.assertEqual(response.get_data(as_text=True), make_text())

    def test_export_of_nothing_or_of_a_hostile_name(self):
        self.assertEqual(
            self.client.get("/restore_profiles/export/builtin/nope").status_code, 302
        )
        # a slash in the name never reaches the service: the route does not match
        self.assertEqual(
            self.client.get("/restore_profiles/export/user/..%2Fetc").status_code, 404
        )
        self.assertEqual(
            self.client.get("/restore_profiles/export/user/..%00x").status_code, 302
        )

    def test_validate_endpoint(self):
        good = self.client.post(
            "/api/restore_profiles/validate", json={"text": profile_yaml()}
        ).get_json()
        self.assertTrue(good["valid"])
        bad = self.client.post(
            "/api/restore_profiles/validate", json={"text": "id: x"}
        ).get_json()
        self.assertFalse(bad["valid"])
        self.assertTrue(all("path" in i for i in bad["issues"]))
        self.assertFalse(
            self.client.post("/api/restore_profiles/validate", json=["x"]).get_json()[
                "valid"
            ]
        )
        self.assertEqual(self.env.repo.profiles, {})

    def test_import_preview_endpoint_stores_nothing(self):
        info = self.client.post(
            "/api/restore_profiles/import_preview", json={"text": make_text()}
        ).get_json()
        self.assertEqual(info["conflict"], "builtin")
        self.assertFalse(info["can_import"])
        self.assertEqual(self.env.repo.profiles, {})

    def test_assign_endpoints(self):
        self.add_user_profile("mine")
        body = {"device_ids": [1, 2], "source": "user", "key": "mine"}
        preview = self.client.post(
            "/api/restore_profiles/assign_preview", json=body
        ).get_json()
        self.assertEqual([r["device_id"] for r in preview["compatible"]], [1])
        self.assertEqual([r["device_id"] for r in preview["incompatible"]], [2])
        self.assertEqual(self.env.repo.assignments, {})  # a preview assigns nothing
        done = self.client.post("/api/restore_profiles/assign", json=body).get_json()
        self.assertEqual(done["assigned"], [1])
        self.assertEqual(self.env.repo.assignments, {1: ("user", "mine")})

    def test_api_errors_use_status_codes(self):
        self.assertEqual(
            self.client.post(
                "/api/restore_profiles/assign",
                json={"device_ids": [], "source": "user", "key": "x"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/restore_profiles/assign_preview",
                json={"device_ids": [1], "source": "user", "key": "nope"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                "/api/restore_profiles/assign", data="not json"
            ).status_code,
            400,
        )

    def test_device_card_endpoint(self):
        card = self.client.get("/api/restore_profiles/device/1").get_json()
        self.assertIsNone(card["assigned"])
        self.assertEqual([s["key"] for s in card["suggestions"]], ["mock_builtin"])
        self.assertEqual(
            self.client.get("/api/restore_profiles/device/3").status_code, 403
        )  # another group
        self.assertEqual(
            self.client.get("/api/restore_profiles/device/abc").status_code, 403
        )

    def test_sadmin_may_assign_to_any_device(self):
        logged_in(self.client, "sadmin", [], user="root")
        done = self.client.post(
            "/api/restore_profiles/assign",
            json={"device_ids": [3], "source": "builtin", "key": "mock_builtin"},
        ).get_json()
        self.assertEqual(done["assigned"], [3])


class TestRegistration(unittest.TestCase):
    def test_routes_are_registered_and_the_menu_has_the_link(self):
        routes = (
            Path(__file__).resolve().parent.parent / "app" / "routes.py"
        ).read_text()
        for path in (
            "/restore_profiles/",
            "/restore_profiles/export/<source>/<key>",
            "/api/restore_profiles/assign",
        ):
            self.assertIn(f'"{path}"', routes)
        base = (Path(TEMPLATES) / "base.html").read_text()
        self.assertIn('href="/restore_profiles/"', base)

    def test_every_view_is_behind_check_auth(self):
        source = (
            Path(__file__).resolve().parent.parent
            / "app"
            / "views"
            / "restore_profiles.py"
        ).read_text()
        decorated = source.count("@check_auth")
        self.assertEqual(decorated, source.count("@app.route("))


if __name__ == "__main__":
    unittest.main()
