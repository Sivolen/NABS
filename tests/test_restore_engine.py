"""Restore Engine, stage 3: precheck, confirmation, execution, failures. Mock adapter only."""

import unittest
from dataclasses import replace

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.restore import states as st  # noqa: E402
from app.modules.restore.adapters import base  # noqa: E402
from app.modules.restore.adapters.mock import MockAdapter  # noqa: E402
from restore_test_support import (  # noqa: E402
    PASSWORD,
    PRE,
    TARGET,
    Env,
    make_job,
    profile_yaml,
)


def failed_check(result, name):
    return [
        c for c in result["checks"] if c["name"] == name and c["status"] == "failed"
    ]


class TestPrecheck(unittest.TestCase):
    def test_ready(self):
        env = Env()
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "ready", result["checks"])
        self.assertEqual(env.live.status, st.AWAITING_CONFIRMATION)
        self.assertTrue(result["fingerprint"])
        self.assertTrue(result["rollback_available"])
        self.assertEqual(
            result["diff"]["added"] > 0 and result["diff"]["removed"] > 0, True
        )
        self.assertTrue(env.adapter.closed)

    def test_pre_restore_copy_is_saved_in_config_storage_and_linked(self):
        env = Env()
        result = env.engine.run_precheck(1)
        config_id = result["pre_restore_config_id"]
        self.assertEqual(env.live.pre_restore_config_id, config_id)
        saved = env.configs.get_config(config_id)
        self.assertEqual((saved.device_id, saved.text), (1, PRE))

    def test_nothing_is_applied_by_a_precheck(self):
        env = Env()
        env.engine.run_precheck(1)
        self.assertNotIn("apply_saved_config", env.adapter.calls)
        self.assertEqual(env.adapter.running_config, PRE)

    def test_blocked_job_ends_failed_without_touching_the_device(self):
        env = Env()
        env.configs.fail_save = True
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(failed_check(result, "save_pre_restore_backup"))
        self.assertEqual(env.live.status, st.FAILED)
        self.assertNotIn("apply_saved_config", env.adapter.calls)

    def test_config_of_another_device_is_refused(self):
        env = Env()
        env.configs.add(10, 2, TARGET)
        result = env.engine.run_precheck(1)
        self.assertTrue(failed_check(result, "target_config"))
        self.assertNotIn("connect", env.adapter.calls)  # never even connected

    def test_missing_and_empty_target(self):
        env = Env()
        del env.configs.configs[10]
        self.assertTrue(failed_check(env.engine.run_precheck(1), "target_config"))
        env = Env()
        env.configs.add(10, 1, "  \n")
        self.assertTrue(failed_check(env.engine.run_precheck(1), "target_config"))

    def test_incompatible_driver_and_unverifiable_model(self):
        env = Env()
        env.device = env.devices.device = base.DeviceInfo(1, "192.0.2.1", "sw", "ios")
        self.assertTrue(failed_check(env.engine.run_precheck(1), "compatibility"))

        def restrict(data):
            data["compatibility"] = {"models": ["X*"]}

        env = Env(profile=profile_yaml(restrict))
        env.device = env.devices.device = base.DeviceInfo(
            1, "192.0.2.1", "sw", "mock_os"
        )
        result = env.engine.run_precheck(1)
        self.assertIn(
            "unverifiable", failed_check(result, "compatibility")[0]["message"]
        )

    def test_missing_credentials(self):
        env = Env(credentials=None)
        self.assertTrue(failed_check(env.engine.run_precheck(1), "credentials"))
        env = Env(credentials=base.Credentials("admin", ""))
        self.assertTrue(failed_check(env.engine.run_precheck(1), "credentials"))

    def test_unknown_adapter_blocks(self):
        env = Env()
        env.engine.adapter_factory = lambda adapter_type: None
        self.assertTrue(failed_check(env.engine.run_precheck(1), "adapter"))

    def test_adapter_missing_an_action_blocks(self):
        class NoApply(MockAdapter):
            apply_saved_config = base.RestoreAdapter.apply_saved_config

        env = Env(adapter=NoApply(running_config=PRE))
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "apply_saved_config", failed_check(result, "adapter")[0]["message"]
        )

    def test_declared_rollback_without_adapter_support_blocks(self):
        class NoRollback(MockAdapter):
            rollback = base.RestoreAdapter.rollback

        env = Env(adapter=NoRollback(running_config=PRE))
        self.assertEqual(env.engine.run_precheck(1)["status"], "blocked")

    def test_connect_failure_blocks(self):
        env = Env(
            adapter=MockAdapter(
                script={"connect": base.AuthenticationFailed("bad login")}
            )
        )
        result = env.engine.run_precheck(1)
        self.assertTrue(failed_check(result, "connect"))

    def test_target_validation_failure_blocks(self):
        script = {"validate_target_config": base.ActionResult.failure("syntax error")}
        env = Env(adapter=MockAdapter(running_config=PRE, script=script))
        result = env.engine.run_precheck(1)
        self.assertTrue(failed_check(result, "validate_target_config"))

    def test_undeterminable_check_is_not_treated_as_a_pass(self):
        script = {"check_platform_support": base.ActionResult.unknown("no facts")}
        env = Env(adapter=MockAdapter(running_config=PRE, script=script))
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "could not be determined",
            failed_check(result, "check_platform_support")[0]["message"],
        )

    def test_adapter_crash_blocks_instead_of_raising(self):
        env = Env(
            adapter=MockAdapter(
                running_config=PRE,
                script={"fetch_current_config": RuntimeError("boom")},
            )
        )
        with self.assertLogs("nabs.restore", "ERROR"):
            self.assertEqual(env.engine.run_precheck(1)["status"], "blocked")
        self.assertEqual(env.live.status, st.FAILED)

    def test_snapshot_checksum_mismatch_blocks(self):
        env = Env()
        env.live.profile_content += "\n# tampered\n"
        self.assertTrue(failed_check(env.engine.run_precheck(1), "profile"))

    def test_warnings_make_the_status_warning(self):
        def no_rollback(data):
            data["failure"]["rollback_strategy"] = "none"
            data["restore"]["steps"] = [
                s
                for s in data["restore"]["steps"]
                if s["action"] != "check_rollback_available"
            ]

        env = Env(profile=profile_yaml(no_rollback))
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "warning")
        self.assertTrue(any("rollback" in w for w in result["warnings"]))

    def test_identical_config_is_flagged(self):
        env = Env(adapter=MockAdapter(running_config=TARGET))
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "warning")
        self.assertTrue(result["diff"]["identical"])

    def test_precheck_cannot_be_started_twice_at_once(self):
        env = Env()
        env.live.status = st.PRECHECK_RUNNING
        self.assertIsNone(env.engine.run_precheck(1))
        env.live.status = st.QUEUED
        self.assertIsNone(env.engine.run_precheck(1))

    def test_rerun_invalidates_the_confirmation(self):
        env = Env()
        first = env.engine.run_precheck(1)
        self.assertEqual(env.live.status, st.AWAITING_CONFIRMATION)
        second = env.engine.run_precheck(1)
        self.assertEqual(env.live.status, st.AWAITING_CONFIRMATION)
        self.assertIsNone(env.live.confirmed_fingerprint)
        self.assertEqual(first["status"], second["status"])


class TestConfirmCancel(unittest.TestCase):
    def test_confirm_needs_the_exact_fingerprint(self):
        env = Env()
        result = env.engine.run_precheck(1)
        self.assertFalse(env.engine.confirm(1, "u", "wrong")[0])
        self.assertFalse(env.engine.confirm(1, "u", "")[0])
        self.assertEqual(env.live.status, st.AWAITING_CONFIRMATION)
        self.assertTrue(env.engine.confirm(1, "u", result["fingerprint"])[0])
        self.assertEqual((env.live.status, env.live.confirmed_by), (st.QUEUED, "u"))

    def test_changed_port_invalidates_confirmation(self):
        env = Env()
        result = env.engine.run_precheck(env.job.id)
        env.devices.device = replace(env.device, port=2222)
        confirmed, _ = env.engine.confirm(env.job.id, "tester", result["fingerprint"])
        self.assertFalse(confirmed)

    def test_confirm_twice(self):
        env = Env()
        result = env.engine.run_precheck(1)
        self.assertTrue(env.engine.confirm(1, "u", result["fingerprint"])[0])
        self.assertFalse(env.engine.confirm(1, "u", result["fingerprint"])[0])

    def test_blocked_or_unprepared_job_cannot_be_confirmed(self):
        env = Env()
        self.assertFalse(env.engine.confirm(1, "u", "x")[0])  # created
        env.configs.fail_save = True
        result = env.engine.run_precheck(1)
        self.assertFalse(env.engine.confirm(1, "u", result["fingerprint"] or "x")[0])

    def test_fingerprint_depends_on_what_the_user_saw(self):
        a = Env()
        b = Env(adapter=MockAdapter(running_config=PRE + "extra\n"))
        self.assertNotEqual(
            a.engine.run_precheck(1)["fingerprint"],
            b.engine.run_precheck(1)["fingerprint"],
        )

    def test_cancel_before_start_only(self):
        env = Env()
        env.engine.run_precheck(1)
        self.assertTrue(env.engine.cancel(1, "u"))
        self.assertEqual(env.live.status, st.CANCELLED)
        env2 = Env()
        env2.to_queued()
        env2.engine.execute(1, "w")
        self.assertFalse(env2.engine.cancel(1, "u"))
        self.assertEqual(env2.live.status, st.SUCCESS)


class TestExecuteSuccessAndGuards(unittest.TestCase):
    def test_success(self):
        env = Env()
        job = env.run_all()
        self.assertEqual(job.status, st.SUCCESS, job.summary)
        self.assertEqual(env.adapter.running_config, TARGET)
        self.assertIn("verify_running_config", env.adapter.calls)
        self.assertTrue(env.adapter.closed)
        self.assertIsNotNone(job.finished_at)

    def test_state_path_is_the_expected_one(self):
        env = Env()
        env.run_all()
        self.assertEqual(
            [t[1] for t in env.store.transitions],
            [
                st.PRECHECK_RUNNING,
                st.AWAITING_CONFIRMATION,
                st.QUEUED,
                st.RUNNING,
                st.VERIFYING,
                st.SUCCESS,
            ],
        )

    def test_unconfirmed_job_is_never_executed(self):
        env = Env()
        env.engine.run_precheck(1)
        self.assertFalse(env.engine.execute(1))
        env.live.status = st.CREATED
        self.assertFalse(env.engine.execute(1))
        self.assertNotIn("apply_saved_config", env.adapter.calls)

    def test_second_execute_does_nothing(self):
        env = Env()
        env.run_all()
        calls = env.adapter.calls.count("apply_saved_config")
        self.assertFalse(env.engine.execute(1))
        self.assertEqual(env.adapter.calls.count("apply_saved_config"), calls)
        self.assertEqual(calls, 1)

    def test_a_lost_claim_race_applies_nothing(self):
        env = Env()
        env.to_queued()
        original = env.store.transition
        env.store.transition = lambda *a, **k: False  # another worker won
        self.assertFalse(env.engine.execute(1))
        env.store.transition = original
        self.assertNotIn("apply_saved_config", env.adapter.calls)

    def test_expired_confirmation_is_cancelled_not_executed(self):
        env = Env()
        env.to_queued()
        env.clock.advance(env.engine.confirmation_ttl + 1)
        self.assertFalse(env.engine.execute(1))
        self.assertEqual(env.live.status, st.CANCELLED)
        self.assertNotIn("apply_saved_config", env.adapter.calls)

    def test_device_changed_after_the_precheck(self):
        env = Env()
        env.to_queued()
        env.adapter.running_config = PRE + "interface 2\n"  # somebody edited it
        env.engine.execute(1, "w")
        self.assertEqual(env.live.status, st.FAILED)
        self.assertIn("changed after the precheck", env.live.summary)
        self.assertNotIn("apply_saved_config", env.adapter.calls)
        self.assertFalse(env.live.diagnostics["device_touched"])

    def test_changed_connection_blocks_execution_before_opening_a_session(self):
        for changed in (
            {"ip": "192.0.2.99"},
            {"driver": "other"},
            {"netmiko_device_type": "other"},
        ):
            with self.subTest(changed=changed):
                env = Env()
                env.to_queued()
                calls = env.factory_calls
                env.devices.device = replace(env.device, **changed)
                env.engine.execute(env.job.id)
                self.assertEqual(env.live.status, st.FAILED)
                self.assertFalse(env.live.diagnostics["device_touched"])
                self.assertEqual(env.factory_calls, calls)

    def test_legacy_confirmation_without_connection_identity_cannot_execute(self):
        env = Env()
        precheck = env.to_queued()
        precheck.pop("connection_identity")
        env.store.update(env.job.id, precheck_result=precheck)
        calls = env.factory_calls
        env.engine.execute(env.job.id)
        self.assertEqual(env.live.status, st.FAILED)
        self.assertIn("create a new restore job", env.live.summary)
        self.assertEqual(env.factory_calls, calls)

    def test_target_config_removed_after_confirmation(self):
        env = Env()
        env.to_queued()
        del env.configs.configs[10]
        env.engine.execute(1, "w")
        self.assertEqual(env.live.status, st.FAILED)
        self.assertNotIn("apply_saved_config", env.adapter.calls)

    def test_connect_failure_at_execution_is_a_clean_failure(self):
        env = Env()
        env.to_queued()
        env.adapter.script["connect"] = base.AdapterConnectionError("down")
        env.engine.execute(1, "w")
        self.assertEqual(env.live.status, st.FAILED)
        self.assertNotIn("apply_saved_config", env.adapter.calls)


class TestStepParameters(unittest.TestCase):
    def test_profile_params_and_action_defaults_reach_the_adapter(self):
        env = Env()
        env.run_all()
        # VALID sets attempts=2 for verify_management_access; wait_seconds is the default
        self.assertEqual(
            env.adapter.params["verify_management_access"],
            {"attempts": 2, "wait_seconds": 10},
        )
        self.assertEqual(
            env.adapter.params["verify_running_config"], {"compare": "normalized"}
        )
        self.assertEqual(env.adapter.params["apply_saved_config"], {})


class TestTimeHandling(unittest.TestCase):
    """The reported case: a queued job never started because the stored time was naive."""

    def env_with_naive_store(self):
        from restore_test_support import NaiveUtcStore

        env = Env()
        naive = NaiveUtcStore()
        naive.jobs = env.store.jobs
        env.store = naive
        env.engine.store = naive
        return env

    def test_a_naive_confirmation_time_from_the_database_does_not_stall_the_job(self):
        env = (
            self.env_with_naive_store()
        )  # the engine's clock is tz-aware, the store's values are not
        job = env.run_all()
        self.assertEqual(job.status, st.SUCCESS, job.summary)
        self.assertIsNone(job.confirmed_at.tzinfo)

    def test_naive_clock_and_naive_values(self):
        env = self.env_with_naive_store()
        env.engine._now = lambda: env.clock.utcnow().replace(tzinfo=None)
        self.assertEqual(env.run_all().status, st.SUCCESS)

    def test_an_expired_confirmation_is_still_detected_with_naive_values(self):
        env = self.env_with_naive_store()
        env.to_queued()
        env.clock.advance(env.engine.confirmation_ttl + 1)
        self.assertFalse(env.engine.execute(1))
        self.assertEqual(env.live.status, st.CANCELLED)

    def test_a_confirmation_time_in_the_future_is_not_trusted(self):
        # e.g. written in local time by an older version: 11 hours ahead of UTC
        from datetime import timedelta

        env = Env()
        env.to_queued()
        env.live.confirmed_at = env.clock.utcnow() + timedelta(hours=11)
        self.assertFalse(env.engine.execute(1))
        self.assertEqual(env.live.status, st.CANCELLED)
        self.assertIn("not valid", env.live.summary)
        self.assertNotIn("apply_saved_config", env.adapter.calls)

    def test_an_unexpected_error_before_the_start_cancels_instead_of_looping(self):
        env = Env()
        env.to_queued()
        env.live.confirmed_at = "garbage"  # anything the clock arithmetic cannot handle
        with self.assertLogs("nabs.restore", "ERROR"):
            self.assertFalse(env.engine.execute(1))
        self.assertEqual(env.live.status, st.CANCELLED)
        self.assertIn("nothing was changed", env.live.summary.lower())
        # the worker has nothing left to retry
        self.assertEqual(env.engine.store.list_jobs([st.QUEUED]), [])

    def test_the_worker_does_not_spin_on_such_a_job(self):
        from app.modules.restore.worker import RestoreWorker

        env = Env()
        env.to_queued()
        env.live.confirmed_at = "garbage"
        worker = RestoreWorker(env.engine, env.store, "w", sleep=lambda s: None)
        with self.assertLogs("nabs.restore", "ERROR"):
            self.assertEqual(worker.run_once(), 1)
        self.assertEqual(worker.run_once(), 0)  # settled: not retried forever


class TestFailures(unittest.TestCase):
    def test_apply_rejected_and_device_verified_unchanged(self):
        script = {"apply_saved_config": base.ActionResult.failure("rejected")}
        env = Env(adapter=MockAdapter(running_config=PRE, script=script))
        job = env.run_all()
        self.assertEqual(job.status, st.FAILED)
        self.assertIn("verified unchanged", job.summary)
        self.assertNotIn("rollback", env.adapter.calls)
        self.assertFalse(job.diagnostics["device_touched"])

    def test_apply_error_with_partial_change_is_rolled_back_and_confirmed(self):
        def partial(ctx):
            env.adapter.running_config = "partial"
            return base.ActionResult.failure("failed halfway")

        env = Env(adapter=MockAdapter(running_config=PRE))
        env.adapter.script["apply_saved_config"] = partial
        job = env.run_all()
        self.assertEqual(job.status, st.FAILED_ROLLBACK_CONFIRMED, job.summary)
        self.assertEqual(env.adapter.running_config, PRE)
        self.assertEqual(job.rollback_status, "confirmed")

    def test_verify_failure_triggers_rollback(self):
        script = {"verify_running_config": base.ActionResult.failure("differs")}
        env = Env(adapter=MockAdapter(running_config=PRE, script=script))
        job = env.run_all()
        self.assertEqual(job.status, st.FAILED_ROLLBACK_CONFIRMED)
        self.assertEqual(env.adapter.running_config, PRE)
        self.assertEqual(env.adapter.calls.count("apply_saved_config"), 1)

    def test_management_access_lost_after_apply_triggers_rollback(self):
        script = {"verify_management_access": base.ActionResult.failure("no ssh")}
        env = Env(adapter=MockAdapter(running_config=PRE, script=script))
        self.assertEqual(env.run_all().status, st.FAILED_ROLLBACK_CONFIRMED)

    def test_rollback_failure_is_reported_as_such(self):
        script = {
            "verify_running_config": base.ActionResult.failure("differs"),
            "rollback": base.ActionResult.failure("device refused"),
        }
        env = Env(adapter=MockAdapter(running_config=PRE, script=script))
        job = env.run_all()
        self.assertEqual(job.status, st.ROLLBACK_FAILED)
        self.assertEqual(job.rollback_status, "failed")

    def test_rollback_accepted_but_not_confirmed_is_not_success(self):
        script = {
            "verify_running_config": base.ActionResult.failure("differs"),
            "rollback": base.ActionResult.success("accepted"),  # changes nothing
        }
        env = Env(adapter=MockAdapter(running_config=PRE, script=script))
        job = env.run_all()
        self.assertEqual(job.status, st.ROLLBACK_FAILED)

    def test_unverifiable_rollback_is_unknown(self):
        script = {
            "verify_running_config": base.ActionResult.failure("differs"),
            "verify_rollback": base.ActionResult.unknown("cannot read"),
        }
        env = Env(adapter=MockAdapter(running_config=PRE, script=script))
        self.assertEqual(env.run_all().status, st.UNKNOWN)

    def test_verification_that_cannot_be_decided_is_unknown_and_not_rolled_back(self):
        script = {"verify_running_config": base.ActionResult.unknown("no data")}
        env = Env(adapter=MockAdapter(running_config=PRE, script=script))
        job = env.run_all()
        self.assertEqual(job.status, st.UNKNOWN)
        self.assertNotIn("rollback", env.adapter.calls)

    def test_failure_without_rollback_strategy_is_failed_with_a_warning_text(self):
        def no_rollback(data):
            data["failure"]["rollback_strategy"] = "none"
            data["restore"]["steps"] = [
                s
                for s in data["restore"]["steps"]
                if s["action"] != "check_rollback_available"
            ]

        script = {"verify_running_config": base.ActionResult.failure("differs")}
        env = Env(
            adapter=MockAdapter(running_config=PRE, script=script),
            profile=profile_yaml(no_rollback),
        )
        job = env.run_all()
        self.assertEqual(job.status, st.FAILED)
        self.assertIn("rollback is not available", job.summary)
        self.assertNotIn("rollback", env.adapter.calls)

    def test_adapter_crash_during_apply_is_unknown(self):
        env = Env(
            adapter=MockAdapter(
                running_config=PRE, script={"apply_saved_config": RuntimeError("boom")}
            )
        )
        with self.assertLogs("nabs.restore", "ERROR"):
            job = env.run_all()
        # the crash left the device state unproven: never "success"
        self.assertIn(job.status, (st.FAILED, st.UNKNOWN, st.FAILED_ROLLBACK_CONFIRMED))
        self.assertNotEqual(job.status, st.SUCCESS)
        self.assertEqual(env.adapter.calls.count("apply_saved_config"), 1)


class TestConnectionLoss(unittest.TestCase):
    def lose_connection_env(self, reconnect_after=None, effect=True):
        """connect() works the first time; later connects fail until `reconnect_after`."""
        counter = {"n": 0}

        def connect(_ctx):
            counter["n"] += 1
            if counter["n"] > 2 and (
                reconnect_after is None or counter["n"] - 2 <= reconnect_after
            ):
                raise base.AdapterConnectionError(
                    "no route"
                )  # precheck + execute = 2 connects

        adapter = MockAdapter(
            running_config=PRE,
            script={
                "apply_saved_config": base.ConnectionLost("session dropped"),
                "connect": connect,
            },
            apply_effect_before_error=effect,
        )
        return Env(adapter=adapter)

    def test_lost_and_never_back_is_unknown_without_retry(self):
        env = self.lose_connection_env(reconnect_after=None)
        job = env.run_all()
        self.assertEqual(job.status, st.UNKNOWN)
        self.assertEqual(env.adapter.calls.count("apply_saved_config"), 1)
        self.assertNotIn("rollback", env.adapter.calls)
        self.assertTrue(env.clock.sleeps)  # it did try to reconnect within the limit
        self.assertLessEqual(sum(env.clock.sleeps), 60)
        self.assertTrue(job.diagnostics["connection_lost"])

    def test_back_and_verified_is_success_with_a_note(self):
        env = self.lose_connection_env(reconnect_after=1)
        job = env.run_all()
        self.assertEqual(job.status, st.SUCCESS, job.summary)
        self.assertEqual(env.adapter.calls.count("apply_saved_config"), 1)
        self.assertTrue(
            any("connection was lost" in n for n in job.diagnostics["notes"])
        )

    def test_back_but_config_differs_is_rolled_back(self):
        env = self.lose_connection_env(reconnect_after=1, effect=False)
        # the config did not take effect, the device still has the old one
        env.adapter.running_config = "something else"
        env.configs.add(10, 1, TARGET)
        job = env.run_all()
        self.assertEqual(job.status, st.FAILED_ROLLBACK_CONFIRMED, job.summary)
        self.assertEqual(env.adapter.calls.count("apply_saved_config"), 1)

    def test_loss_during_rollback_is_unknown(self):
        script = {
            "verify_running_config": base.ActionResult.failure("differs"),
            "rollback": base.ConnectionLost("dropped"),
        }
        env = Env(adapter=MockAdapter(running_config=PRE, script=script))
        job = env.run_all()
        self.assertEqual(job.status, st.UNKNOWN)
        self.assertEqual(job.rollback_status, "unknown")
        self.assertEqual(env.adapter.calls.count("rollback"), 1)

    def test_loss_while_verifying_is_unknown(self):
        script = {"verify_management_access": base.ConnectionLost("dropped")}
        env = Env(adapter=MockAdapter(running_config=PRE, script=script))
        job = env.run_all()
        self.assertEqual(job.status, st.UNKNOWN)


class TestPersistStep(unittest.TestCase):
    def profile_with_persist(self):
        def add(data):
            data["restore"]["steps"].append({"action": "persist_config"})

        return profile_yaml(add)

    def test_persist_runs_after_verification(self):
        env = Env(profile=self.profile_with_persist())
        job = env.run_all()
        self.assertEqual(job.status, st.SUCCESS)
        self.assertEqual(env.adapter.saved_config, TARGET)

    def test_persist_failure_is_not_success(self):
        script = {"persist_config": base.ActionResult.failure("flash full")}
        env = Env(
            adapter=MockAdapter(running_config=PRE, script=script),
            profile=self.profile_with_persist(),
        )
        job = env.run_all()
        self.assertEqual(job.status, st.FAILED)
        self.assertTrue(job.diagnostics["applied_not_persisted"])
        self.assertNotIn("rollback", env.adapter.calls)


class TestRestartRecovery(unittest.TestCase):
    def test_claimed_jobs_become_unknown_and_nothing_is_resumed(self):
        env = Env()
        for status in (st.RUNNING, st.VERIFYING, st.ROLLBACK_RUNNING):
            env.live.status = status
            env.live.finished_at = None
            self.assertEqual(env.engine.recover_interrupted(), [1])
            self.assertEqual(env.live.status, st.UNKNOWN)
        self.assertEqual(env.adapter.calls, [])
        self.assertEqual(env.factory_calls, 0)

    def test_queued_job_stays_queued_and_other_states_are_untouched(self):
        env = Env()
        for status in (st.QUEUED, st.AWAITING_CONFIRMATION, st.SUCCESS, st.CREATED):
            env.live.status = status
            self.assertEqual(env.engine.recover_interrupted(), [])
            self.assertEqual(env.live.status, status)

    def test_a_recently_active_job_is_left_alone_when_a_threshold_is_given(self):
        env = Env()
        env.live.status = st.RUNNING
        env.live.heartbeat_at = env.clock.utcnow()
        self.assertEqual(env.engine.recover_interrupted(stale_after_seconds=300), [])
        env.clock.advance(301)
        self.assertEqual(env.engine.recover_interrupted(stale_after_seconds=300), [1])

    def test_an_unknown_job_is_never_executed_again(self):
        env = Env()
        env.live.status = st.UNKNOWN
        self.assertFalse(env.engine.execute(1))
        self.assertFalse(env.engine.cancel(1, "u"))


class TestSecretsAndJournal(unittest.TestCase):
    def test_password_never_reaches_events_summary_or_diagnostics(self):
        leaky_connect = MockAdapter(
            script={
                "connect": base.AdapterConnectionError(f"login failed for {PASSWORD}")
            }
        )
        leaky_verify = MockAdapter(
            running_config=PRE,
            script={
                "verify_running_config": base.ActionResult.failure(f"leak {PASSWORD}")
            },
        )
        blocked = Env(adapter=leaky_connect)
        blocked.engine.run_precheck(1)
        failed = Env(adapter=leaky_verify)
        failed.run_all()
        for env in (blocked, failed):
            self.assertNotIn(PASSWORD, env.all_text())
        self.assertIn("***", blocked.all_text())

    def test_journal_records_the_main_stages(self):
        env = Env()
        env.run_all()
        types = [e["type"] for e in env.store.events]
        for expected in (
            "precheck_started",
            "precheck_done",
            "confirmed",
            "claimed",
            "step_started",
            "adapter_call",
            "finished",
        ):
            self.assertIn(expected, types)
        self.assertTrue(all(e["job_id"] == 1 for e in env.store.events))


if __name__ == "__main__":
    unittest.main()
