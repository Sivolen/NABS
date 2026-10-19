"""Restore Engine, stage 7: the restore pages (real views, real templates, mock adapter)."""

import unittest
from pathlib import Path
from unittest.mock import patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from flask import render_template  # noqa: E402

from app.modules.restore import states as st  # noqa: E402
from app.modules.restore.adapters import base  # noqa: E402
from app.modules.restore.adapters.mock import MockAdapter  # noqa: E402
from app.modules.restore.profiles import ProfileText  # noqa: E402
from app.views import restore_config as restore_config_view  # noqa: E402
from app.views import restore_jobs as view  # noqa: E402
from restore_test_support import PRE, TARGET  # noqa: E402
from test_restore_profile_service import Env as ProfileEnv  # noqa: E402
from test_restore_service import (
    ADMIN,
    OTHER_GROUP_ADMIN,
    PLAIN_USER,
    ServiceEnv,
)  # noqa: E402
from view_test_support import flashed, logged_in, make_test_app  # noqa: E402

TEMPLATES = str(Path(__file__).resolve().parent.parent / "app" / "templates")


def make_ui_app():
    rules = [
        ("/restore/new", "restore_new", view.restore_new, ["GET", "POST"]),
        ("/restore/job/<job_id>", "restore_job", view.restore_job, ["GET"]),
        (
            "/restore/job/<job_id>/confirm",
            "restore_job_confirm",
            view.restore_job_confirm,
            ["POST"],
        ),
        (
            "/restore/job/<job_id>/cancel",
            "restore_job_cancel",
            view.restore_job_cancel,
            ["POST"],
        ),
        (
            "/restore/job/<job_id>/recheck",
            "restore_job_recheck",
            view.restore_job_recheck,
            ["POST"],
        ),
        (
            "/restore/device/<device_id>",
            "restore_device_jobs",
            view.restore_device_jobs,
            ["GET"],
        ),
        ("/api/restore/job/<job_id>", "api_restore_job", view.api_restore_job, ["GET"]),
        (
            "/restore_config/",
            "restore_config",
            restore_config_view.restore_config,
            ["GET", "POST"],
        ),
    ]
    flask_app = make_test_app(rules)
    flask_app.template_folder = TEMPLATES
    flask_app.jinja_env.globals.update(
        csrf_token=lambda: "tok", core_version="t", ui="t"
    )
    return flask_app


class UiCase(unittest.TestCase):
    token = "tok-aaaaaaaaaaaaaaaa"

    def setUp(self, adapter=None, target=TARGET):
        self.env = ServiceEnv(adapter=adapter)
        self.pe = ProfileEnv()
        self.addCleanup(self.pe.dir.cleanup)
        self.env.configs.add(10, 1, target)
        builtin = self.pe.service.builtin.get("builtin", "mock_builtin")
        self.env.profiles.items[("builtin", "mock_builtin")] = ProfileText(
            "builtin", "mock_builtin", builtin.version, builtin.content
        )
        # the profile service sees the same device the restore service uses
        self.pe.service.devices = self.env.devices
        self.pe.service._access = self.env.service._access
        self.env.assignments.assigned = None
        patcher = patch.object(
            view, "_services", lambda: (self.env.service, self.pe.service)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = make_ui_app().test_client()
        logged_in(self.client, "admin", [5], user="anton")

    # ---- helpers
    def start(self, token=None, profile="builtin:mock_builtin", config_id=10):
        return self.client.post(
            "/restore/new",
            data={
                "device_id": "1",
                "config_id": str(config_id),
                "client_token": token or self.token,
                "profile": profile,
            },
        )

    def job_id(self):
        return max(self.env.store.jobs)

    def page(self, job_id=None):
        return self.client.get(f"/restore/job/{job_id or self.job_id()}").get_data(
            as_text=True
        )

    def to_confirmation(self):
        self.assertEqual(self.start().status_code, 302)
        self.env.worker.run_once()
        job = self.env.store.jobs[self.job_id()]
        self.assertEqual(job.status, st.AWAITING_CONFIRMATION, job.summary)
        return job


class TestAccess(UiCase):
    URLS_GET = [
        "/restore/new?device_id=1&config_id=10",
        "/restore/job/1",
        "/restore/device/1",
    ]

    def test_anonymous_goes_to_login_everywhere(self):
        anon = make_ui_app().test_client()
        for url in self.URLS_GET:
            response = anon.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/login", response.headers["Location"])
        for url in (
            "/restore/new",
            "/restore/job/1/confirm",
            "/restore/job/1/cancel",
            "/restore/job/1/recheck",
        ):
            self.assertIn("/login", anon.post(url).headers["Location"])
        self.assertIn("/login", anon.get("/api/restore/job/1").headers["Location"])
        self.assertEqual(self.env.store.jobs, {})

    def test_plain_user_cannot_see_or_start_anything(self):
        job = self.to_confirmation()
        logged_in(self.client, "user", [5], user="bob")
        for url in self.URLS_GET:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response.headers["Location"].endswith("/devices"))
        self.assertEqual(self.start(token="tok-bbbbbbbbbbbbbbbb").status_code, 302)
        self.assertEqual(len(self.env.store.jobs), 1)
        for action in ("confirm", "cancel", "recheck"):
            self.client.post(
                f"/restore/job/{job.id}/{action}",
                data={
                    "acknowledge": "on",
                    "fingerprint": job.precheck_result["fingerprint"],
                },
            )
        self.assertEqual(self.env.store.jobs[job.id].status, st.AWAITING_CONFIRMATION)
        self.assertEqual(self.client.get(f"/api/restore/job/{job.id}").status_code, 403)

    def test_admin_of_another_group_cannot_touch_the_job_or_the_device(self):
        job = self.to_confirmation()
        logged_in(self.client, "admin", [9], user="eve")
        self.assertEqual(self.client.get(f"/restore/job/{job.id}").status_code, 302)
        self.assertEqual(
            self.client.get("/restore/new?device_id=1&config_id=10").status_code, 302
        )
        self.assertEqual(
            self.client.get("/api/restore/job/%d" % job.id).status_code, 403
        )
        self.client.post(
            f"/restore/job/{job.id}/confirm",
            data={
                "acknowledge": "on",
                "fingerprint": job.precheck_result["fingerprint"],
            },
        )
        self.assertEqual(self.env.store.jobs[job.id].status, st.AWAITING_CONFIRMATION)


class TestNewPage(UiCase):
    def test_get_shows_the_choice_and_creates_nothing(self):
        response = self.client.get("/restore/new?device_id=1&config_id=10")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("sw1", body)
        self.assertIn("#10", body)
        self.assertIn("Run precheck", body)
        self.assertIn('value="builtin:mock_builtin"', body)
        self.assertIn('name="client_token"', body)
        self.assertEqual(self.env.store.jobs, {})  # looking at the page starts nothing

    def test_every_visit_gets_a_fresh_token(self):
        first = self.client.get("/restore/new?device_id=1&config_id=10").get_data(
            as_text=True
        )
        second = self.client.get("/restore/new?device_id=1&config_id=10").get_data(
            as_text=True
        )
        import re

        tokens = [
            re.search(r'name="client_token" value="([^"]+)"', b).group(1)
            for b in (first, second)
        ]
        self.assertNotEqual(*tokens)
        self.assertGreaterEqual(len(tokens[0]), 16)

    def test_the_assigned_profile_is_preselected(self):
        self.env.assignments.assigned = ("builtin", "mock_builtin")
        body = self.client.get("/restore/new?device_id=1&config_id=10").get_data(
            as_text=True
        )
        self.assertIn("selected", body)
        self.assertIn("(assigned)", body)

    def test_no_usable_profile_means_no_form(self):
        self.pe.service._capabilities = (
            lambda: {}
        )  # nothing implemented, like production now
        body = self.client.get("/restore/new?device_id=1&config_id=10").get_data(
            as_text=True
        )
        self.assertIn("Restore is not available for this device", body)
        self.assertNotIn("Run precheck", body)
        self.assertNotIn(
            "<form", body.split("Restore is not available")[0].split("<h4")[-1]
        )

    def test_a_config_of_another_device_is_refused(self):
        self.env.configs.add(11, 2, TARGET)
        response = self.client.get("/restore/new?device_id=1&config_id=11")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.env.store.jobs, {})
        self.assertEqual(
            self.client.get("/restore/new?device_id=1&config_id=999").status_code, 302
        )
        self.assertEqual(
            self.client.get("/restore/new?device_id=abc&config_id=10").status_code, 302
        )


class TestStartAndFlow(UiCase):
    def test_post_creates_the_job_and_asks_the_worker_for_a_precheck_only(self):
        response = self.start()
        self.assertEqual(response.status_code, 302)
        job = self.env.store.jobs[self.job_id()]
        self.assertTrue(response.headers["Location"].endswith(f"/restore/job/{job.id}"))
        self.assertEqual((job.status, job.requested_action), (st.CREATED, "precheck"))
        self.assertEqual(
            self.env.adapter.calls, []
        )  # the web request touched no device
        self.assertNotIn("apply_saved_config", self.env.adapter.calls)

    def test_a_repeated_post_does_not_create_a_second_job(self):
        self.start()
        self.start()
        self.start()
        self.assertEqual(len(self.env.store.jobs), 1)
        self.env.worker.run_once()
        self.start()  # a refresh after the precheck: still the same job, nothing re-requested
        self.assertEqual(len(self.env.store.jobs), 1)
        self.assertEqual(
            self.env.store.jobs[self.job_id()].status, st.AWAITING_CONFIRMATION
        )

    def test_bad_profile_choice_creates_nothing(self):
        for choice in ("evil:x", "builtin:", "nocolon", "user:nope"):
            self.start(token=f"tok-{abs(hash(choice)) % 10**12:016d}", profile=choice)
        self.assertEqual(self.env.store.jobs, {})

    def test_a_refused_start_returns_to_the_form_with_the_reason(self):
        response = self.start(profile="evil:x")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/restore/new", response.headers["Location"])
        self.assertIn("device_id=1", response.headers["Location"])
        self.assertTrue(
            any("Invalid profile choice" in m for m in flashed(self.client))
        )
        self.assertEqual(self.env.store.jobs, {})

    def test_full_flow_to_success(self):
        job = self.to_confirmation()
        page = self.page()
        self.assertIn("Confirm and restore", page)
        self.assertIn(job.precheck_result["fingerprint"], page)
        self.assertIn("bi-check-circle-fill", page)  # passed checks
        self.assertIn("hostname new", page)  # the diff
        self.assertEqual(self.env.adapter.running_config, PRE)  # nothing applied yet
        self.assertNotIn("apply_saved_config", self.env.adapter.calls)

        response = self.client.post(
            f"/restore/job/{job.id}/confirm",
            data={
                "acknowledge": "on",
                "fingerprint": job.precheck_result["fingerprint"],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.env.store.jobs[job.id].status, st.QUEUED)
        self.assertNotIn(
            "apply_saved_config", self.env.adapter.calls
        )  # confirming does not apply
        self.env.worker.run_once()
        done = self.page()
        self.assertEqual(self.env.store.jobs[job.id].status, st.SUCCESS)
        self.assertIn("Restored and verified", done)
        self.assertIn('alert alert-success" id="summary"', done)
        self.assertNotIn("Confirm and restore", done)
        self.assertNotIn("setTimeout(poll", done)  # no polling once finished
        self.assertEqual(self.env.adapter.running_config, TARGET)
        self.assertEqual(self.env.adapter.calls.count("apply_saved_config"), 1)

    def test_confirmation_needs_the_checkbox_and_the_exact_fingerprint(self):
        job = self.to_confirmation()
        fingerprint = job.precheck_result["fingerprint"]
        for data in (
            {"fingerprint": fingerprint},
            {"acknowledge": "on", "fingerprint": "wrong"},
            {"acknowledge": "on"},
            {"acknowledge": "on", "fingerprint": ""},
        ):
            self.client.post(f"/restore/job/{job.id}/confirm", data=data)
            self.assertEqual(
                self.env.store.jobs[job.id].status, st.AWAITING_CONFIRMATION, data
            )
        self.assertTrue(any("Tick the box" in m for m in flashed(self.client)))

    def test_confirming_twice_runs_once(self):
        job = self.to_confirmation()
        data = {"acknowledge": "on", "fingerprint": job.precheck_result["fingerprint"]}
        self.client.post(f"/restore/job/{job.id}/confirm", data=data)
        self.client.post(f"/restore/job/{job.id}/confirm", data=data)
        self.env.worker.run_once()
        self.env.worker.run_once()
        self.assertEqual(self.env.adapter.calls.count("apply_saved_config"), 1)

    def test_recheck_voids_a_confirmation_state_and_cancel_stops_everything(self):
        job = self.to_confirmation()
        self.client.post(f"/restore/job/{job.id}/recheck")
        self.assertEqual(self.env.store.jobs[job.id].requested_action, "precheck")
        self.env.worker.run_once()
        self.assertEqual(self.env.store.jobs[job.id].status, st.AWAITING_CONFIRMATION)
        self.client.post(f"/restore/job/{job.id}/cancel")
        self.assertEqual(self.env.store.jobs[job.id].status, st.CANCELLED)
        self.env.worker.run_once()
        self.assertNotIn("apply_saved_config", self.env.adapter.calls)
        self.assertIn("Cancelled before any change", self.page())

    def test_cancel_is_refused_once_the_device_may_be_touched(self):
        job = self.to_confirmation()
        self.env.store.jobs[job.id].status = st.RUNNING
        self.client.post(f"/restore/job/{job.id}/cancel")
        self.assertEqual(self.env.store.jobs[job.id].status, st.RUNNING)


class TestPageContent(UiCase):
    def test_blocked_precheck_has_no_confirmation(self):
        self.env.configs.fail_save = True
        self.start()
        self.env.worker.run_once()
        page = self.page()
        self.assertIn("Blocked", page)
        self.assertIn("bi-x-circle-fill", page)
        self.assertNotIn("Confirm and restore", page)
        self.assertIn("Nothing was changed", page)

    def test_a_blocked_precheck_does_not_ask_to_read_warnings_before_confirming(self):
        from restore_test_support import profile_yaml

        text = profile_yaml(lambda d: d.update(warnings=["Profile warning text"]))
        self.env.profiles.items[("user", "mock_platform")] = ProfileText(
            "user", "mock_platform", 1, text
        )
        self.env.configs.fail_save = True
        self.start(profile="user:mock_platform")
        self.env.worker.run_once()
        page = self.page()
        self.assertIn("Blocked", page)
        self.assertNotIn("Read before confirming", page)  # nothing can be confirmed

    def test_warnings_are_shown_before_confirmation(self):
        def no_rollback(data):
            data["failure"]["rollback_strategy"] = "none"
            data["restore"]["steps"] = [
                s
                for s in data["restore"]["steps"]
                if s["action"] != "check_rollback_available"
            ]

        from restore_test_support import profile_yaml

        text = profile_yaml(no_rollback)
        self.env.profiles.items[("user", "mock_platform")] = ProfileText(
            "user", "mock_platform", 1, text
        )
        self.start(profile="user:mock_platform")
        self.env.worker.run_once()
        page = self.page()
        self.assertIn("Read before confirming", page)
        self.assertIn("no rollback", page.lower())
        self.assertIn("Confirm and restore", page)

    def test_identical_config_and_missing_diff_are_stated(self):
        self.env.adapter.running_config = TARGET
        self.start()
        self.env.worker.run_once()
        self.assertIn("already has exactly this configuration", self.page())

    def test_config_text_is_escaped_in_the_diff(self):
        self.env.configs.add(10, 1, "hostname <script>alert(1)</script>\n")
        self.start()
        self.env.worker.run_once()
        page = self.page()
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_unknown_result_is_not_dressed_up_as_success_or_failure(self):
        job = self.to_confirmation()
        record = self.env.store.jobs[job.id]
        record.status, record.summary = (
            st.UNKNOWN,
            "The connection was lost during the apply",
        )
        page = self.page()
        self.assertIn("could not be determined", page)
        self.assertIn("Check the device by hand", page)
        self.assertNotIn('alert alert-success" id="summary"', page)
        self.assertIn('alert alert-danger" id="summary"', page)

    def test_failed_rollback_is_loud_and_names_the_pre_restore_copy(self):
        job = self.to_confirmation()
        record = self.env.store.jobs[job.id]
        record.status, record.summary = st.ROLLBACK_FAILED, "rollback failed"
        record.rollback_status, record.rollback_details = "failed", "device refused"
        page = self.page()
        self.assertIn("The rollback did not succeed", page)
        self.assertIn(f"#{record.pre_restore_config_id}", page)
        self.assertIn("device refused", page)

    def test_confirmed_rollback_is_a_warning_not_a_success(self):
        script = {"verify_running_config": base.ActionResult.failure("differs")}
        self.setUp(adapter=MockAdapter(running_config=PRE, script=script))
        job = self.to_confirmation()
        self.client.post(
            f"/restore/job/{job.id}/confirm",
            data={
                "acknowledge": "on",
                "fingerprint": job.precheck_result["fingerprint"],
            },
        )
        self.env.worker.run_once()
        page = self.page(job.id)
        self.assertEqual(
            self.env.store.jobs[job.id].status, st.FAILED_ROLLBACK_CONFIRMED
        )
        self.assertIn("previous configuration was put back and confirmed", page)
        # judge the result block itself (the page also shows the earlier "Confirmed" flash)
        self.assertIn('alert alert-warning" id="summary"', page)
        self.assertNotIn('alert alert-success" id="summary"', page)
        self.assertIn("bg-warning", page.split('id="statusBadge"')[0][-80:])

    def test_the_page_never_shows_credentials_or_the_profile_text(self):
        from restore_test_support import PASSWORD

        job = self.to_confirmation()
        page = self.page(job.id)
        self.assertNotIn(PASSWORD, page)
        self.assertNotIn("schema_version", page)

    def test_polling_runs_while_active_and_the_journal_is_listed(self):
        self.start()
        page = self.page()
        self.assertIn("setTimeout(poll", page)
        self.assertIn("nabs-restore-worker", page)  # the worker hint while waiting
        self.env.worker.run_once()
        later = self.page()
        self.assertIn("Precheck finished", later)  # the journal
        self.assertIn("2026-10-05T12:00:00", later)  # with times

    def test_unknown_job_goes_back_with_a_message(self):
        response = self.client.get("/restore/job/999")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/restore/job/abc").status_code, 302)


class TestDisruptivePage(UiCase):
    def make_disruptive(self):
        job = self.to_confirmation()
        self.env.store.jobs[job.id].precheck_result["disruptive"] = True
        return job

    def test_the_page_warns_loudly_and_asks_for_the_name(self):
        job = self.make_disruptive()
        page = self.page(job.id)
        self.assertIn("REBOOTS the device", page)
        self.assertIn('id="disruptive"', page)
        self.assertIn('name="confirm_name"', page)
        self.assertIn("sw1", page)  # the name to type is shown

    def test_an_ordinary_job_has_no_banner_and_no_name_field(self):
        job = self.to_confirmation()
        page = self.page(job.id)
        self.assertNotIn('id="disruptive"', page)
        self.assertNotIn('name="confirm_name"', page)

    def test_confirming_without_or_with_the_wrong_name_changes_nothing(self):
        job = self.make_disruptive()
        data = {"acknowledge": "on", "fingerprint": job.precheck_result["fingerprint"]}
        self.client.post(f"/restore/job/{job.id}/confirm", data=data)
        self.client.post(
            f"/restore/job/{job.id}/confirm", data=dict(data, confirm_name="other")
        )
        self.assertEqual(self.env.store.jobs[job.id].status, st.AWAITING_CONFIRMATION)
        self.client.post(
            f"/restore/job/{job.id}/confirm", data=dict(data, confirm_name="sw1")
        )
        self.assertEqual(self.env.store.jobs[job.id].status, st.QUEUED)


class TestApiAndHistory(UiCase):
    def test_polling_endpoint(self):
        self.start()
        data = self.client.get(f"/api/restore/job/{self.job_id()}").get_json()
        self.assertEqual((data["status"], data["terminal"]), (st.CREATED, False))
        self.env.worker.run_once()
        data = self.client.get(f"/api/restore/job/{self.job_id()}").get_json()
        self.assertEqual(data["status"], st.AWAITING_CONFIRMATION)
        self.assertGreater(data["events"], 0)
        self.assertEqual(self.client.get("/api/restore/job/999").status_code, 404)

    def test_device_history(self):
        self.start()
        page = self.client.get("/restore/device/1").get_data(as_text=True)
        self.assertIn("Restore history", page)
        self.assertIn(f"/restore/job/{self.job_id()}", page)
        self.assertIn("anton", page)
        self.assertEqual(
            self.client.get("/restore/device/2").status_code, 302
        )  # no access
        logged_in(self.client, "user", [5], user="bob")
        self.assertEqual(self.client.get("/restore/device/1").status_code, 302)


class TestCompatRouteAndConfigPage(UiCase):
    def test_old_route_forwards_to_the_new_page(self):
        response = self.client.get("/restore_config/?device_id=1&config_id=10")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/restore/new", response.headers["Location"])
        self.assertEqual(self.env.store.jobs, {})

    def render_config_page(self, rights):
        flask_app = make_ui_app()
        with flask_app.test_request_context("/config_page/1"):
            from flask import session

            session["user"], session["rights"] = "u", rights
            return render_template(
                "config_page.html",
                config_id=42,
                ipaddress="192.0.2.1",
                last_config="x\n",
                timestamp="2026-10-05 12:00",
                config_timestamp_list=["2026-10-05 12:00"],
                check_previous_config=True,
                previous_configs_timestamp=[],
                device_environment={
                    "device_id": 1,
                    "device_hostname": "sw1",
                    "device_ip": "192.0.2.1",
                },
            )

    def test_restore_button_is_shown_to_admin_roles_only(self):
        for rights in ("admin", "sadmin"):
            html = self.render_config_page(rights)
            self.assertIn('id="restoreBtn"', html)
            self.assertIn(
                "/restore/new?device_id=1&amp;config_id=42",
                html.replace("&config_id", "&amp;config_id"),
            )
        self.assertNotIn('id="restoreBtn"', self.render_config_page("user"))

    def test_the_button_follows_the_selected_date(self):
        html = self.render_config_page("admin")
        self.assertIn("restoreBtn.href", html)
        self.assertIn('encodeURIComponent(result["config_id"])', html)


class TestRegistration(unittest.TestCase):
    def test_routes_registered_and_every_view_guarded(self):
        root = Path(__file__).resolve().parent.parent
        routes = (root / "app" / "routes.py").read_text()
        for path in (
            "/restore/new",
            "/restore/job/<job_id>",
            "/restore/job/<job_id>/confirm",
            "/restore/job/<job_id>/cancel",
            "/restore/job/<job_id>/recheck",
            "/restore/device/<device_id>",
            "/api/restore/job/<job_id>",
        ):
            self.assertIn(f'"{path}"', routes)
        source = (root / "app" / "views" / "restore_jobs.py").read_text()
        self.assertEqual(source.count("@check_auth"), source.count("@app.route("))

    def test_the_web_process_has_no_way_to_reach_a_device(self):
        source = (
            Path(__file__).resolve().parent.parent / "app" / "views" / "restore_jobs.py"
        ).read_text()
        self.assertIn("lambda adapter_type: None", source)
        for forbidden in (
            "netmiko",
            "napalm",
            "adapter_classes",
            "run_precheck",
            ".execute(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
