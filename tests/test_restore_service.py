"""Restore Engine, stage 4: service (authorization, idempotency) and worker."""

import unittest

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.access import can_access_device  # noqa: E402
from app.modules.restore import states as st  # noqa: E402
from app.modules.restore.adapters import base  # noqa: E402
from app.modules.restore.adapters.mock import MockAdapter  # noqa: E402
from app.modules.restore.profiles import ProfileText  # noqa: E402
from app.modules.restore.service import (  # noqa: E402
    CONFLICT,
    FORBIDDEN,
    INVALID,
    NOT_FOUND,
    RestoreService,
    ServiceError,
)
from app.modules.restore.worker import RestoreWorker  # noqa: E402
from restore_test_support import PASSWORD, PRE, TARGET, Env, profile_yaml  # noqa: E402

TOKEN = "tok-aaaaaaaaaaaaaaaa"
ADMIN = {"user": "anton", "rights": "admin", "allowed_devices": [5]}
SADMIN = {"user": "root", "rights": "sadmin"}
PLAIN_USER = {"user": "bob", "rights": "user", "allowed_devices": [5]}
OTHER_GROUP_ADMIN = {"user": "eve", "rights": "admin", "allowed_devices": [9]}
NOBODY = {"rights": "admin", "allowed_devices": [5]}


def group_lookup(groups, device_id):
    return 5 in groups and device_id == 1  # device 1 belongs to group 5 only


def access(session_obj, device_id):
    return can_access_device(session_obj, device_id, group_lookup=group_lookup)


class DictProfiles:
    def __init__(self, items=None):
        self.items = (
            items
            if items is not None
            else {
                ("user", "mock_platform"): ProfileText(
                    "user", "mock_platform", 1, profile_yaml()
                )
            }
        )

    def get(self, source, key):
        return self.items.get((source, key))


class Assignments:
    def __init__(self, assigned=("user", "mock_platform")):
        self.assigned = assigned

    def get_assigned(self, device_id):
        return self.assigned


class ServiceEnv(Env):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.store.jobs.clear()  # the service creates its own jobs
        self.profiles = DictProfiles()
        self.assignments = Assignments()
        self.service = RestoreService(
            self.store,
            self.configs,
            self.devices,
            self.profiles,
            self.assignments,
            self.engine,
            access=access,
        )
        self.worker = RestoreWorker(self.engine, self.store, "w1", sleep=lambda s: None)

    def create(self, session=ADMIN, token=TOKEN, **kw):
        return self.service.create_job(
            session,
            kw.get("device_id", 1),
            kw.get("config_id", 10),
            token,
            kw.get("profile_ref"),
        )


def code_of(callable_, *args, **kwargs):
    try:
        callable_(*args, **kwargs)
    except ServiceError as error:
        return error.code
    return None


class TestAuthorization(unittest.TestCase):
    def test_plain_user_cannot_restore_even_with_device_access(self):
        env = ServiceEnv()
        self.assertEqual(code_of(env.create, PLAIN_USER), FORBIDDEN)

    def test_admin_of_another_group_is_denied(self):
        env = ServiceEnv()
        self.assertEqual(code_of(env.create, OTHER_GROUP_ADMIN), FORBIDDEN)

    def test_anonymous_session_is_denied(self):
        env = ServiceEnv()
        self.assertEqual(code_of(env.create, NOBODY), FORBIDDEN)
        self.assertEqual(code_of(env.create, {}), FORBIDDEN)

    def test_admin_with_access_and_sadmin_are_allowed(self):
        for session, token in ((ADMIN, TOKEN), (SADMIN, "tok-bbbbbbbbbbbbbbbb")):
            env = ServiceEnv()
            job, created = env.create(session, token)
            self.assertTrue(created)
            self.assertEqual(job.status, st.CREATED)

    def test_rights_are_rechecked_on_every_call(self):
        env = ServiceEnv()
        job, _ = env.create()
        for call in (
            lambda s: env.service.request_precheck(s, job.id),
            lambda s: env.service.confirm(s, job.id, "x"),
            lambda s: env.service.cancel(s, job.id),
            lambda s: env.service.get_job_view(s, job.id),
        ):
            for session in (PLAIN_USER, OTHER_GROUP_ADMIN, NOBODY):
                self.assertEqual(code_of(call, session), FORBIDDEN)
        self.assertEqual(env.store.jobs[job.id].requested_action, None)
        self.assertEqual(env.store.jobs[job.id].status, st.CREATED)

    def test_listing_jobs_of_a_device_needs_access(self):
        env = ServiceEnv()
        env.create()
        self.assertEqual(
            code_of(env.service.list_jobs_for_device, OTHER_GROUP_ADMIN, 1), FORBIDDEN
        )
        self.assertEqual(
            code_of(env.service.list_jobs_for_device, ADMIN, "1; DROP"), INVALID
        )
        self.assertEqual(len(env.service.list_jobs_for_device(ADMIN, 1)), 1)

    def test_unknown_job(self):
        env = ServiceEnv()
        self.assertEqual(code_of(env.service.get_job_view, ADMIN, 999), NOT_FOUND)
        self.assertEqual(code_of(env.service.get_job_view, ADMIN, "abc"), NOT_FOUND)


class TestCreateJob(unittest.TestCase):
    def test_config_of_another_device_is_refused(self):
        env = ServiceEnv()
        env.configs.add(11, 2, TARGET)
        self.assertEqual(code_of(env.create, ADMIN, TOKEN, config_id=11), INVALID)
        self.assertEqual(env.store.jobs, {})

    def test_missing_config_device_and_bad_ids(self):
        env = ServiceEnv()
        self.assertEqual(code_of(env.create, ADMIN, TOKEN, config_id=999), INVALID)
        self.assertEqual(code_of(env.create, ADMIN, TOKEN, device_id=77), FORBIDDEN)
        self.assertEqual(code_of(env.create, ADMIN, TOKEN, device_id="x"), INVALID)
        self.assertEqual(code_of(env.create, ADMIN, TOKEN, config_id=-1), INVALID)

    def test_bad_token(self):
        env = ServiceEnv()
        for token in ("short", "has space aaaaaaaaaaaa", None, "x" * 100):
            self.assertEqual(code_of(env.create, ADMIN, token), INVALID)

    def test_same_token_returns_the_same_job(self):
        env = ServiceEnv()
        first, created_first = env.create()
        second, created_second = env.create()
        self.assertEqual((created_first, created_second), (True, False))
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(env.store.jobs), 1)

    def test_token_of_another_request_cannot_be_reused(self):
        env = ServiceEnv()
        env.create()
        self.assertEqual(code_of(env.create, SADMIN, TOKEN), CONFLICT)
        env.configs.add(12, 1, TARGET)
        self.assertEqual(code_of(env.create, ADMIN, TOKEN, config_id=12), CONFLICT)

    def test_profile_snapshot_is_stored(self):
        env = ServiceEnv()
        job, _ = env.create()
        self.assertEqual(
            (job.profile_source, job.profile_key), ("user", "mock_platform")
        )
        self.assertEqual(job.profile_content, profile_yaml())
        self.assertEqual(job.initiator, "anton")

    def test_profile_resolution(self):
        env = ServiceEnv()
        env.assignments.assigned = None
        self.assertEqual(code_of(env.create), INVALID)  # nothing assigned, none given
        ref = {"source": "user", "key": "mock_platform"}
        self.assertTrue(env.create(profile_ref=ref)[1])
        for bad in (
            {"source": "evil", "key": "x"},
            {"source": "user"},
            {"source": "user", "key": ""},
        ):
            self.assertEqual(
                code_of(env.create, ADMIN, "tok-cccccccccccccccc", profile_ref=bad),
                INVALID,
            )
        missing = {"source": "user", "key": "nope"}
        self.assertEqual(
            code_of(env.create, ADMIN, "tok-dddddddddddddddd", profile_ref=missing),
            NOT_FOUND,
        )

    def test_invalid_profile_is_refused(self):
        env = ServiceEnv()
        env.profiles.items[("user", "mock_platform")] = ProfileText(
            "user", "mock_platform", 1, "id: x"
        )
        self.assertEqual(code_of(env.create), INVALID)

    def test_a_user_profile_cannot_claim_to_be_builtin(self):
        env = ServiceEnv()
        text = profile_yaml(lambda d: d.update(builtin=True))
        env.profiles.items[("user", "mock_platform")] = ProfileText(
            "user", "mock_platform", 1, text
        )
        self.assertEqual(code_of(env.create), INVALID)


class TestLifecycleThroughService(unittest.TestCase):
    def test_precheck_request_state_rules(self):
        env = ServiceEnv()
        job, _ = env.create()
        env.service.request_precheck(ADMIN, job.id)
        self.assertEqual(env.store.jobs[job.id].requested_action, "precheck")
        env.store.jobs[job.id].status = st.QUEUED
        self.assertEqual(code_of(env.service.request_precheck, ADMIN, job.id), CONFLICT)

    def test_full_flow_create_precheck_confirm_execute(self):
        env = ServiceEnv()
        job, _ = env.create()
        env.service.request_precheck(ADMIN, job.id)
        self.assertEqual(
            env.store.jobs[job.id].status, st.CREATED
        )  # nothing yet: the worker does it
        self.assertEqual(env.worker.run_once(), 1)

        view = env.service.get_job_view(ADMIN, job.id)
        self.assertEqual(view["status"], st.AWAITING_CONFIRMATION)
        self.assertIn(view["precheck_status"], ("ready", "warning"))
        self.assertEqual(
            env.adapter.running_config, PRE
        )  # not applied before confirmation

        self.assertEqual(
            env.worker.run_once(), 0
        )  # nothing to do, and no repeated precheck
        env.service.confirm(ADMIN, job.id, view["fingerprint"])
        self.assertEqual(env.worker.run_once(), 1)

        view = env.service.get_job_view(ADMIN, job.id)
        self.assertEqual(view["status"], st.SUCCESS, view["summary"])
        self.assertTrue(view["terminal"])
        self.assertEqual(env.adapter.running_config, TARGET)
        self.assertTrue(view["events"])
        self.assertEqual(env.adapter.calls.count("apply_saved_config"), 1)

    def test_wrong_fingerprint_is_a_conflict_and_nothing_runs(self):
        env = ServiceEnv()
        job, _ = env.create()
        env.service.request_precheck(ADMIN, job.id)
        env.worker.run_once()
        self.assertEqual(code_of(env.service.confirm, ADMIN, job.id, "wrong"), CONFLICT)
        self.assertEqual(env.worker.run_once(), 0)
        self.assertNotIn("apply_saved_config", env.adapter.calls)

    def test_cancel_through_the_service(self):
        env = ServiceEnv()
        job, _ = env.create()
        env.service.cancel(ADMIN, job.id)
        self.assertEqual(env.store.jobs[job.id].status, st.CANCELLED)
        self.assertEqual(code_of(env.service.cancel, ADMIN, job.id), CONFLICT)

    def test_view_exposes_no_profile_text_or_secrets(self):
        env = ServiceEnv()
        job, _ = env.create()
        env.service.request_precheck(ADMIN, job.id)
        env.worker.run_once()
        text = str(env.service.get_job_view(ADMIN, job.id))
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn("schema_version", text)  # the YAML itself stays server side
        self.assertNotIn("worker_id", text)


class TestManualResolution(unittest.TestCase):
    def make_unknown(self):
        env = ServiceEnv()
        job, _ = env.create()
        env.store.update(
            job.id, status=st.UNKNOWN, diagnostics={"device_touched": True}
        )
        return env, env.store.get_job(job.id)

    def test_unknown_can_be_resolved_after_typed_manual_confirmation(self):
        env, job = self.make_unknown()
        result = env.service.resolve_unknown(
            ADMIN,
            job.id,
            "target_confirmed",
            "Checked running configuration and management access from console.",
            "sw1",
        )
        self.assertEqual(result.status, st.RESOLVED_MANUAL)
        self.assertEqual(
            result.diagnostics["manual_resolution"]["resolution"], "target_confirmed"
        )
        self.assertTrue(
            result.diagnostics["manual_resolution"]["device_identity_confirmed"]
        )
        self.assertTrue(any(e["type"] == "manually_resolved" for e in env.store.events))

    def test_leave_open_records_note_but_keeps_configurations_protected(self):
        env, job = self.make_unknown()
        result = env.service.resolve_unknown(
            ADMIN,
            job.id,
            "leave_open",
            "Console check completed but the active configuration is still uncertain.",
            "sw1",
        )
        self.assertEqual(result.status, st.UNKNOWN)
        self.assertEqual(len(result.diagnostics["manual_checks"]), 1)

    def test_manual_resolution_requires_note_and_exact_device_name(self):
        env, job = self.make_unknown()
        self.assertEqual(
            code_of(
                lambda: env.service.resolve_unknown(
                    ADMIN, job.id, "target_confirmed", "too short", "sw1"
                )
            ),
            INVALID,
        )
        self.assertEqual(
            code_of(
                lambda: env.service.resolve_unknown(
                    ADMIN,
                    job.id,
                    "target_confirmed",
                    "Checked running configuration from console and verified it.",
                    "wrong-device",
                )
            ),
            INVALID,
        )

    def test_failed_after_changes_can_be_resolved_but_clean_failure_cannot(self):
        for touched in (False, True):
            with self.subTest(touched=touched):
                env, job = self.make_unknown()
                env.store.update(
                    job.id, status=st.FAILED, diagnostics={"device_touched": touched}
                )
                args = (
                    ADMIN,
                    job.id,
                    "target_confirmed",
                    "Verified running and next-startup configuration from console.",
                    "sw1",
                )
                if touched:
                    result = env.service.resolve_unknown(*args)
                    self.assertEqual(result.status, st.RESOLVED_MANUAL)
                else:
                    self.assertEqual(
                        code_of(lambda: env.service.resolve_unknown(*args)), CONFLICT
                    )

    def test_other_states_cannot_be_manually_resolved(self):
        env = ServiceEnv()
        job, _ = env.create()
        self.assertEqual(
            code_of(
                lambda: env.service.resolve_unknown(
                    ADMIN,
                    job.id,
                    "target_confirmed",
                    "Checked running configuration from console and verified it.",
                    "sw1",
                )
            ),
            CONFLICT,
        )


class TestDisruptiveConfirmation(unittest.TestCase):
    """A restore that reboots the device needs the device name typed, not just a tick."""

    def disruptive_env(self):
        env = ServiceEnv()
        job, _ = env.create()
        env.service.request_precheck(ADMIN, job.id)
        env.worker.run_once()
        record = env.store.jobs[job.id]
        record.precheck_result[
            "disruptive"
        ] = True  # as the engine records it for such a profile
        return env, record

    def test_the_view_says_so(self):
        env, record = self.disruptive_env()
        self.assertTrue(env.service.get_job_view(ADMIN, record.id)["disruptive"])

    def test_confirmation_needs_the_device_name(self):
        env, record = self.disruptive_env()
        fingerprint = record.precheck_result["fingerprint"]
        for typed in (None, "", "wrong", "sw", "sw1 "[:2]):
            self.assertEqual(
                code_of(env.service.confirm, ADMIN, record.id, fingerprint, typed),
                INVALID,
                typed,
            )
        self.assertEqual(env.store.jobs[record.id].status, st.AWAITING_CONFIRMATION)
        confirmed = env.service.confirm(
            ADMIN, record.id, fingerprint, "  SW1 "
        )  # case and spaces do not matter
        self.assertEqual(confirmed.status, st.QUEUED)

    def test_an_ordinary_restore_does_not_ask_for_the_name(self):
        env = ServiceEnv()
        job, _ = env.create()
        env.service.request_precheck(ADMIN, job.id)
        env.worker.run_once()
        fingerprint = env.store.jobs[job.id].precheck_result["fingerprint"]
        self.assertFalse(env.service.get_job_view(ADMIN, job.id)["disruptive"])
        self.assertEqual(
            env.service.confirm(ADMIN, job.id, fingerprint).status, st.QUEUED
        )

    def test_the_name_falls_back_to_the_ip_when_there_is_no_hostname(self):
        env, record = self.disruptive_env()
        env.devices.device = base.DeviceInfo(1, "192.0.2.1", None, "mock_os")
        fingerprint = record.precheck_result["fingerprint"]
        self.assertEqual(
            code_of(env.service.confirm, ADMIN, record.id, fingerprint, "sw1"), INVALID
        )
        self.assertEqual(
            env.service.confirm(ADMIN, record.id, fingerprint, "192.0.2.1").status,
            st.QUEUED,
        )


class TestWorker(unittest.TestCase):
    def test_start_marks_claimed_jobs_unknown(self):
        env = ServiceEnv()
        job, _ = env.create()
        env.store.jobs[job.id].status = st.RUNNING
        self.assertEqual(env.worker.start(), [job.id])
        self.assertEqual(env.store.jobs[job.id].status, st.UNKNOWN)
        self.assertEqual(env.adapter.calls, [])

    def test_a_requested_precheck_is_claimed_exactly_once(self):
        env = ServiceEnv()
        job, _ = env.create()
        env.service.request_precheck(ADMIN, job.id)
        second_worker = RestoreWorker(env.engine, env.store, "w2", sleep=lambda s: None)
        self.assertEqual(env.worker.run_once() + second_worker.run_once(), 1)
        self.assertEqual(env.adapter.calls.count("fetch_current_config"), 1)

    def test_one_broken_job_does_not_stop_the_others(self):
        env = ServiceEnv()
        first, _ = env.create()
        second, _ = env.create(token="tok-eeeeeeeeeeeeeeee")
        for job in (first, second):
            env.service.request_precheck(ADMIN, job.id)
        real = env.engine.run_precheck
        calls = []

        def flaky(job_id):
            calls.append(job_id)
            if job_id == first.id:
                raise RuntimeError("boom")
            return real(job_id)

        env.engine.run_precheck = flaky
        with self.assertLogs("nabs.restore.worker", "ERROR"):
            handled = env.worker.run_once()
        self.assertEqual(calls, [first.id, second.id])
        self.assertEqual(handled, 1)
        self.assertEqual(env.store.jobs[second.id].status, st.AWAITING_CONFIRMATION)

    def test_run_forever_sleeps_only_when_idle_and_stops(self):
        env = ServiceEnv()
        sleeps = []
        worker = RestoreWorker(
            env.engine, env.store, "w", poll_seconds=7, sleep=sleeps.append
        )
        ticks = iter([False, False, True])
        worker.run_forever(lambda: next(ticks))
        self.assertEqual(sleeps, [7, 7])

    def test_queued_jobs_run_in_order_and_a_stale_precheck_is_not_applied(self):
        env = ServiceEnv()
        ids = []
        for token in ("tok-ffffffffffffffff", "tok-gggggggggggggggg"):
            job, _ = env.create(token=token)
            env.service.request_precheck(ADMIN, job.id)
            ids.append(job.id)
        env.worker.run_once()  # both prechecks saw the same, original device state
        for job_id in ids:
            fingerprint = env.store.jobs[job_id].precheck_result["fingerprint"]
            env.service.confirm(ADMIN, job_id, fingerprint)
        env.worker.run_once()
        first, second = (env.store.jobs[i] for i in ids)
        self.assertEqual(first.status, st.SUCCESS)
        # the first job changed the device, so the second one's precheck is stale:
        # it is refused instead of being applied on top of an unseen state
        self.assertEqual(second.status, st.FAILED)
        self.assertIn("changed after the precheck", second.summary)
        claimed = [e["job_id"] for e in env.store.events if e["type"] == "claimed"]
        self.assertEqual(claimed, ids)  # strictly one after the other, in order
        self.assertEqual(env.adapter.calls.count("apply_saved_config"), 1)


if __name__ == "__main__":
    unittest.main()
