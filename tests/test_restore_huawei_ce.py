"""
Restore Engine: the Huawei CloudEngine adapter against a SIMULATED device.
The outputs of the simulator are synthetic (written from documentation), see huawei_sim.py.
"""

import unittest
from pathlib import Path

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.restore import adapters, schema, states as st  # noqa: E402
from app.modules.restore.adapters import base, huawei_common as hw  # noqa: E402
from app.modules.restore.adapters.huawei_ce import (
    HuaweiCeAdapter,
    trial_seconds,
)  # noqa: E402
from app.modules.restore.compat import check_compatibility  # noqa: E402
from app.modules.restore.engine import ENGINE_IMPLEMENTED_ACTIONS  # noqa: E402
from app.modules.restore.profiles import BuiltinProfileProvider  # noqa: E402
from huawei_sim import (  # noqa: E402
    AR_VERSION,
    CE_RUNNING,
    CE_VERSION,
    S_VERSION,
    CeDevice,
    make_factory,
    make_sftp,
    stored,
)
from restore_test_support import PASSWORD, Env  # noqa: E402

SHIPPED = BuiltinProfileProvider().get("builtin", "huawei_ce")
TARGET = stored(CE_RUNNING.replace("old-name", "new-name"))


def profile():
    result = schema.parse_profile_yaml(SHIPPED.content, allow_builtin=True)
    assert result.ok, result.issues
    return result.profile


def make_adapter(device, **kw):
    return HuaweiCeAdapter(
        connection_factory=make_factory(device),
        sftp_factory=make_sftp(device),
        sleep=lambda s: None,
        **kw
    )


def make_ctx(target=TARGET, scratch=None, params=None, job_id=7):
    info = base.DeviceInfo(
        1, "192.0.2.1", "sw1", "huawei_vrp_ssh", netmiko_device_type="huawei_vrp_ssh"
    )
    ctx = base.RestoreContext(
        job_id=job_id, device=info, profile=profile(), target_config=target
    )
    ctx.scratch.update(scratch or {})
    ctx.params = params or {}
    return ctx


def connected(device, **kw):
    adapter = make_adapter(device, **kw)
    adapter.connect(
        base.DeviceInfo(
            1,
            "192.0.2.1",
            "sw1",
            "huawei_vrp_ssh",
            netmiko_device_type="huawei_vrp_ssh",
        ),
        base.Credentials("admin", PASSWORD),
        5,
    )
    return adapter


def prepared(device, target=TARGET):
    adapter = connected(device)
    ctx = make_ctx(target)
    assert adapter.fetch_current_config(ctx).ok
    assert adapter.check_rollback_available(ctx).ok
    ctx.scratch["pre_restore_config"] = stored(CE_RUNNING)
    return adapter, ctx


class TestParsersAndRegistry(unittest.TestCase):
    def test_display_version(self):
        ce = hw.parse_display_version(CE_VERSION)
        self.assertEqual(
            (ce.family, ce.model, ce.software, ce.vrp_version),
            ("ce", "CE6863E", "V200R019C10SPC800", "8.191"),
        )
        self.assertEqual(hw.parse_display_version(S_VERSION).family, "s")
        self.assertEqual(hw.parse_display_version(AR_VERSION).family, "other")
        self.assertIsNone(hw.parse_display_version("nothing"))
        self.assertEqual(
            hw.parse_display_version("VRP (R) software, Version 8.1").family, "other"
        )

    def test_free_space_startup_and_names(self):
        self.assertEqual(
            hw.parse_free_bytes("1,036,308 KB total (582,296 KB free)"), 582296 * 1024
        )
        self.assertEqual(
            hw.parse_free_bytes("100 MB total (40 MB free)"), 40 * 1024**2
        )
        self.assertIsNone(hw.parse_free_bytes("garbage"))
        text = "  Startup saved-configuration file:  flash:/a.zip\n  Next startup saved-configuration file:  flash:/b.cfg"
        self.assertEqual(hw.parse_startup(text), ("flash:/a.zip", "flash:/b.cfg"))
        self.assertEqual(hw.basename("flash:/B.cfg"), "b.cfg")

    def test_normalization_and_prompt_cleaning(self):
        text = (
            "!Software Version V1\n#\nsysname a  \n\ninterface x\n#\nreturn\n<HUAWEI>"
        )
        self.assertEqual(
            hw.normalize_config(hw.clean_output(text)), "sysname a\ninterface x\nreturn"
        )
        self.assertIn("!Software Version V1", hw.normalize_config(text, mode="exact"))
        self.assertEqual(hw.clean_output("a\nb\n[~HUAWEI]"), "a\nb")
        self.assertEqual(hw.clean_output("a\n[HUAWEI-aaa]\n"), "a")
        self.assertEqual(hw.normalize_platform("huawei_vrp_ssh"), "huawei_vrp")

    def test_registry_profile_and_compatibility(self):
        self.assertTrue(HuaweiCeAdapter.supports_rollback())
        self.assertEqual(HuaweiCeAdapter.supported_actions(), set(base.ACTION_HANDLERS))
        self.assertFalse(HuaweiCeAdapter.verified)
        self.assertNotIn("huawei_ce", adapters.adapter_classes())
        self.assertIs(
            adapters.adapter_classes(include_unverified=True)["huawei_ce"],
            HuaweiCeAdapter,
        )
        caps = adapters.adapter_capabilities(
            engine_actions=ENGINE_IMPLEMENTED_ACTIONS, include_unverified=True
        )
        self.assertEqual(schema.check_adapter_capabilities(profile(), caps), [])
        self.assertFalse(profile().disruptive)
        for platform, ok in (
            ("huawei_vrp_ssh", True),
            ("huawei_ssh", True),
            ("huawei_vrp", True),
            ("cisco_ios_ssh", False),
            ("ios", False),
        ):
            self.assertEqual(
                check_compatibility(profile(), platform).allowed, ok, platform
            )

    def test_connects_with_the_custom_driver_type(self):
        device = CeDevice()
        connected(device)
        self.assertEqual(device.last_connect_kwargs["device_type"], "huawei_vrp_ssh")
        adapter = make_adapter(device)
        adapter.connect(
            base.DeviceInfo(
                1, "192.0.2.1", "sw", "ios", netmiko_device_type="cisco_ios_ssh"
            ),
            base.Credentials("a", "b"),
            5,
        )
        self.assertEqual(device.last_connect_kwargs["device_type"], "huawei")


class TestPrecheckHandlers(unittest.TestCase):
    def test_platform(self):
        self.assertTrue(connected(CeDevice()).check_platform_support(make_ctx()).ok)
        wrong = connected(CeDevice(version=S_VERSION)).check_platform_support(
            make_ctx()
        )
        self.assertEqual(wrong.verdict, base.Verdict.FAILED)
        self.assertIn("S-series", wrong.message)
        self.assertEqual(
            connected(CeDevice(version=AR_VERSION))
            .check_platform_support(make_ctx())
            .verdict,
            base.Verdict.FAILED,
        )
        self.assertEqual(
            connected(CeDevice(version="???"))
            .check_platform_support(make_ctx())
            .verdict,
            base.Verdict.UNKNOWN,
        )

    def test_two_phase_mode_is_required_and_the_view_is_left(self):
        device = CeDevice()
        self.assertTrue(connected(device).check_connectivity(make_ctx()).ok)
        self.assertEqual(device.view, "user")
        immediate = CeDevice(two_phase=False)
        result = connected(immediate).check_connectivity(make_ctx())
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("two-phase", result.message)
        self.assertEqual(immediate.view, "user")

    def test_fetch_and_space(self):
        device = CeDevice()
        adapter = connected(device)
        ctx = make_ctx()
        result = adapter.fetch_current_config(ctx)
        self.assertTrue(result.ok)
        self.assertTrue(result.payload.rstrip().endswith("return"))
        self.assertNotIn("<HUAWEI>", result.payload)
        self.assertTrue(ctx.scratch["huawei_sftp_enabled"])
        self.assertTrue(adapter.check_rollback_available(ctx).ok)
        small = CeDevice(free_kb=1)
        adapter = connected(small)
        ctx = make_ctx()
        adapter.fetch_current_config(ctx)
        self.assertEqual(
            adapter.check_rollback_available(ctx).verdict, base.Verdict.FAILED
        )
        truncated = CeDevice(running="sysname x\n")
        self.assertFalse(connected(truncated).fetch_current_config(make_ctx()).ok)


class TestValidate(unittest.TestCase):
    def test_dry_run_changes_nothing_and_cleans_up(self):
        device = CeDevice()
        adapter, ctx = prepared(device)
        result = adapter.validate_target_config(ctx)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.details, {"added": 1, "removed": 1})
        self.assertEqual(device.running, CE_RUNNING)
        self.assertIsNone(device.candidate)  # the candidate was thrown away
        self.assertIsNone(device.trial)
        self.assertEqual(device.view, "user")  # and the view was left
        self.assertIn("clear configuration candidate", device.commands)
        self.assertFalse(any(c.startswith("commit") for c in device.commands))
        adapter.close()
        self.assertEqual(device.files, {})  # the uploaded file is deleted again
        self.assertFalse(Path(device.last_local_file).exists())

    def test_sftp_off_is_named_before_anything_is_uploaded(self):
        device = CeDevice(running=CE_RUNNING.replace("sftp server enable\n", ""))
        adapter, ctx = prepared(device)
        result = adapter.validate_target_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("sftp server enable", result.message)
        self.assertEqual(device.files, {})

    def test_upload_failure_carries_the_device_text(self):
        class SFTPError(Exception):
            pass

        device = CeDevice()
        device.sftp_error = SFTPError("Permission denied")
        adapter, ctx = prepared(device)
        result = adapter.validate_target_config(ctx)
        self.assertIn("SFTPError: Permission denied", result.message)
        self.assertIn("service-type sftp", result.message)

    def test_a_file_outside_the_root_directory_is_refused(self):
        device = CeDevice()
        adapter, ctx = prepared(device)
        original = device.handle
        device.handle = (
            lambda c: device.reply("Error: Wrong parameter found at '^' position.")
            if c.startswith("dir nabs")
            else original(c)
        )
        result = adapter.validate_target_config(ctx)
        self.assertIn("root directory", result.message)

    def test_replace_failures_the_device_predicts_block(self):
        device = CeDevice()
        device.replace_failures = ["undo ntp-service enable", "undo vlan 10"]
        adapter, ctx = prepared(device)
        result = adapter.validate_target_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("cannot replace 2 command(s)", result.message)
        self.assertIsNone(device.candidate)

    def test_the_device_refusing_the_load_blocks(self):
        device = CeDevice()
        device.load_error = "Error: The configuration file is invalid."
        adapter, ctx = prepared(device)
        self.assertEqual(
            adapter.validate_target_config(ctx).verdict, base.Verdict.FAILED
        )
        self.assertEqual(device.view, "user")

    def test_text_checks(self):
        device = CeDevice()
        adapter, ctx = prepared(
            device, target=stored(CE_RUNNING).replace("return\n", "")
        )
        self.assertIn("'return'", adapter.validate_target_config(ctx).message)
        partial = stored(
            "sysname x\ninterface MEth0/0/0\n ip address 192.0.2.1 255.255.255.0\nreturn\n"
        )
        adapter, ctx = prepared(device, target=partial)
        self.assertIn("looks partial", adapter.validate_target_config(ctx).message)
        no_ip = stored(CE_RUNNING.replace("192.0.2.1", "198.51.100.9"))
        adapter, ctx = prepared(device, target=no_ip)
        self.assertIn(
            "management address 192.0.2.1", adapter.validate_target_config(ctx).message
        )
        self.assertEqual(device.files, {})

    def test_risky_removals_are_warned_about(self):
        device = CeDevice()
        target = stored(
            CE_RUNNING.replace(" protocol inbound ssh\n", " protocol inbound all\n")
        )
        adapter, ctx = prepared(device, target=target)
        result = adapter.validate_target_config(ctx)
        self.assertTrue(result.ok)
        self.assertTrue(any("remote access" in w for w in result.warnings))


class TestApplyVerifyPersist(unittest.TestCase):
    def applied(self, device=None):
        device = device or CeDevice()
        adapter, ctx = prepared(device)
        ctx.params = {}
        result = adapter.apply_saved_config(ctx)
        return device, adapter, ctx, result

    def test_apply_runs_the_target_on_trial(self):
        device, adapter, ctx, result = self.applied()
        self.assertTrue(result.ok, result.message)
        self.assertEqual(
            hw.normalize_config(device.running), hw.normalize_config(TARGET)
        )
        self.assertEqual(device.trial["seconds"], trial_seconds(ctx))
        self.assertEqual(
            device.trial["seconds"], 780
        )  # verify + commit + save + safety margin
        self.assertNotIn(
            "commit", device.commands[device.commands.index("commit trial 780") + 1 :]
        )
        self.assertEqual(device.view, "user")
        self.assertIn("nabs-restore-7-pre.cfg", device.files)
        self.assertIn("nabs-restore-7-target.cfg", device.files)
        self.assertEqual(device.files["nabs-restore-7-pre.cfg"], stored(CE_RUNNING))
        adapter.close()
        self.assertIn(
            "nabs-restore-7-pre.cfg", device.files
        )  # after an apply the files stay

    def test_nothing_is_committed_when_the_load_fails(self):
        device = CeDevice()
        device.replace_failures = ["undo vlan 10"]
        adapter, ctx = prepared(device)
        result = adapter.apply_saved_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertEqual(device.running, CE_RUNNING)
        self.assertIsNone(device.trial)
        self.assertIsNone(device.candidate)
        device2 = CeDevice()
        device2.trial_error = "Error: The trial commit is not supported."
        adapter, ctx = prepared(device2)
        self.assertEqual(adapter.apply_saved_config(ctx).verdict, base.Verdict.FAILED)
        self.assertEqual(device2.running, CE_RUNNING)
        self.assertIsNone(device2.candidate)

    def test_apply_needs_the_stored_pre_copy_and_a_working_upload(self):
        device = CeDevice()
        adapter, ctx = prepared(device)
        ctx.scratch.pop("pre_restore_config")
        self.assertEqual(adapter.apply_saved_config(ctx).verdict, base.Verdict.FAILED)
        device2 = CeDevice()
        adapter, ctx = prepared(device2)
        device2.sftp_error = RuntimeError("no")
        self.assertEqual(adapter.apply_saved_config(ctx).verdict, base.Verdict.FAILED)
        self.assertEqual(device2.running, CE_RUNNING)

    def test_a_session_lost_during_the_trial_commit_reverts_by_itself(self):
        device = CeDevice()
        device.drop_after = "commit trial"
        adapter, ctx = prepared(device)
        with self.assertRaises(base.ConnectionLost):
            adapter.apply_saved_config(ctx)
        self.assertEqual(device.running, CE_RUNNING)  # the device went back on its own

    def test_management_access_uses_a_new_session_and_can_fail(self):
        device, adapter, ctx, _ = self.applied()
        before = device.sessions_opened
        ctx.params = {"attempts": 2, "wait_seconds": 1}
        self.assertTrue(adapter.verify_management_access(ctx).ok)
        self.assertEqual(device.sessions_opened, before + 1)
        device.online = False
        slept = []
        adapter._sleep = slept.append
        ctx.params = {"attempts": 3, "wait_seconds": 7}
        self.assertEqual(
            adapter.verify_management_access(ctx).verdict, base.Verdict.FAILED
        )
        self.assertEqual(slept, [7, 7, 7])

    def test_verify_running_config_never_leaks_lines(self):
        device, adapter, ctx, _ = self.applied()
        self.assertTrue(adapter.verify_running_config(ctx).ok)
        device.running = device.running.replace("new-name", "LEAKY-NAME")
        result = adapter.verify_running_config(ctx)
        self.assertEqual(
            (result.verdict, result.details),
            (base.Verdict.FAILED, {"missing": 1, "unexpected": 1}),
        )
        self.assertNotIn("LEAKY-NAME", result.message + str(result.details))
        ctx.params = {"compare": "exact"}
        self.assertFalse(
            adapter.verify_running_config(ctx).ok
        )  # exact keeps the "!" comment lines

    def test_persist_commits_the_trial_and_saves(self):
        device, adapter, ctx, _ = self.applied()
        result = adapter.persist_config(ctx)
        self.assertTrue(result.ok, result.message)
        self.assertIsNone(device.trial)  # confirmed: it no longer reverts
        self.assertEqual(device.startup_saved, device.running)
        self.assertEqual(device.view, "user")

    def test_persist_without_a_trial_or_with_a_refused_commit(self):
        device = CeDevice()
        adapter, ctx = prepared(device)
        self.assertEqual(adapter.persist_config(ctx).verdict, base.Verdict.FAILED)
        device, adapter, ctx, _ = self.applied()
        device.commit_error = "Error: Commit failed."
        result = adapter.persist_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("reverts", result.message)
        device, adapter, ctx, _ = self.applied()
        device.save_output = "Error: not enough space"
        self.assertEqual(adapter.persist_config(ctx).verdict, base.Verdict.FAILED)

    def test_rollback_aborts_an_open_trial(self):
        device, adapter, ctx, _ = self.applied()
        self.assertTrue(adapter.rollback(ctx).ok)
        self.assertEqual(device.running, CE_RUNNING)
        self.assertIsNone(device.trial)
        self.assertTrue(adapter.verify_rollback(ctx).ok)

    def test_rollback_without_a_trial_is_a_noop_when_already_back_else_loads_the_file(
        self,
    ):
        device, adapter, ctx, _ = self.applied()
        device.kill_session()  # the device reverted by itself
        adapter.connect(
            base.DeviceInfo(1, "192.0.2.1", "sw1", "huawei_vrp_ssh"),
            base.Credentials("a", "b"),
            5,
        )
        result = adapter.rollback(ctx)
        self.assertIn("already at the previous configuration", result.message)
        self.assertFalse(
            any(
                c.startswith("commit") and c != "commit trial 780"
                for c in device.commands[-6:]
            )
        )
        device, adapter, ctx, _ = self.applied()
        adapter.persist_config(ctx)  # committed and saved: a real rollback is needed
        self.assertTrue(adapter.rollback(ctx).ok)
        self.assertIn(
            "load configuration file nabs-restore-7-pre.cfg replace", device.commands
        )
        self.assertEqual(
            hw.normalize_config(device.running), hw.normalize_config(stored(CE_RUNNING))
        )
        self.assertTrue(adapter.verify_rollback(ctx).ok)

    def test_the_password_is_only_given_to_the_connection(self):
        device, adapter, ctx, _ = self.applied()
        self.assertEqual(device.last_connect_kwargs["password"], PASSWORD)
        self.assertNotIn(PASSWORD, repr(adapter))
        self.assertFalse(any(PASSWORD in c for c in device.commands))


class EngineCase(unittest.TestCase):
    def build(self, device=None):
        self.device = device or CeDevice()
        adapter = make_adapter(self.device)
        env = Env(
            adapter=adapter,
            profile=SHIPPED.content,
            profile_source="builtin",
            device=base.DeviceInfo(
                1,
                "192.0.2.1",
                "sw1",
                "huawei_vrp_ssh",
                netmiko_device_type="huawei_vrp_ssh",
            ),
        )
        env.configs.add(10, 1, TARGET)
        return env

    def run_to_end(self, env):
        env.to_queued()
        env.engine.execute(1, "w1")
        return env.live


class TestEngineWithCe(EngineCase):
    def test_precheck_is_ready_with_warnings_and_changes_nothing(self):
        env = self.build()
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "warning", result["checks"])
        self.assertFalse(result["disruptive"])
        self.assertEqual(self.device.running, CE_RUNNING)
        self.assertIsNone(self.device.candidate)
        self.assertEqual(self.device.files, {})
        self.assertEqual(
            (result["diff"]["added"], result["diff"]["removed"]), (1, 1)
        )  # "!" lines and "#" are not shown

    def test_precheck_blocks_if_candidate_cleanup_is_refused_or_unconfirmed(self):
        class RetainsCandidate(CeDevice):
            def handle(self, command):
                if command == "clear configuration candidate":
                    self.cancelled = self.cancel_precheck()
                    return self.reply(self.clear_output)
                return super().handle(command)

        for output in ("Error: permission denied", ""):
            with self.subTest(output=output):
                device = RetainsCandidate()
                device.clear_output = output
                env = self.build(device)
                device.cancel_precheck = lambda: env.engine.cancel(1, "tester")
                result = env.engine.run_precheck(1)
                self.assertFalse(device.cancelled)
                self.assertEqual(env.live.status, st.FAILED)
                self.assertEqual(result["status"], "blocked")
                self.assertIsNone(result["fingerprint"])
                self.assertIsNotNone(device.candidate)
                self.assertTrue(env.live.diagnostics["device_touched"])
                self.assertTrue(env.live.diagnostics["candidate_cleanup_uncertain"])
                self.assertNotIn("Nothing was changed", env.live.summary)

    def test_interrupted_precheck_requires_candidate_inspection(self):
        env = self.build()
        env.store.update(env.job.id, status=st.PRECHECK_RUNNING)
        self.assertEqual(env.engine.recover_interrupted(), [env.job.id])
        self.assertEqual(env.live.status, st.UNKNOWN)
        self.assertTrue(env.live.diagnostics["candidate_cleanup_uncertain"])
        self.assertEqual(self.device.commands, [])

    def test_precheck_preserves_existing_candidate(self):
        device = CeDevice()
        device.candidate = TARGET
        result = self.build(device).engine.run_precheck(1)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(device.candidate, TARGET)
        self.assertNotIn("clear configuration candidate", device.commands)

    def test_precheck_cleanup_failure_is_visible_as_a_warning(self):
        device = CeDevice()
        device.refuse_delete = True
        env = self.build(device)
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "warning")
        self.assertTrue(
            any(
                c["name"] == "cleanup" and c["status"] == "warning"
                for c in result["checks"]
            )
        )
        self.assertTrue(any(name.startswith("nabs-restore-") for name in device.files))

    def test_full_success_confirms_and_saves(self):
        env = self.build()
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.SUCCESS, job.summary)
        self.assertIsNone(self.device.trial)
        self.assertEqual(self.device.startup_saved, self.device.running)
        self.assertEqual(
            hw.normalize_config(self.device.running), hw.normalize_config(TARGET)
        )
        self.assertFalse(
            any(name.startswith("nabs-restore-") for name in self.device.files)
        )
        self.assertNotIn("cleanup_errors", job.diagnostics or {})

    def test_cleanup_failure_after_success_is_journaled_without_false_failure(self):
        device = CeDevice()
        device.refuse_delete = True
        env = self.build(device)
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.SUCCESS, job.summary)
        self.assertIn("Temporary device files could not be cleaned up", job.summary)
        self.assertTrue(job.diagnostics.get("cleanup_errors"))
        self.assertTrue(
            any(e["type"] == "cleanup_incomplete" for e in env.store.events)
        )

    def test_the_profile_parameters_reach_the_adapter(self):
        env = self.build()
        waits = []
        env.adapter._sleep = waits.append
        self.run_to_end(env)
        self.assertEqual(waits, [10])

    def test_a_verification_mismatch_aborts_the_trial(self):
        env = self.build()
        env.to_queued()
        original = self.device.handle

        def tamper(command):
            out = original(command)
            if command.startswith("commit trial"):
                self.device.running += (
                    "interface LoopBack99\n"  # the device adds something
                )
            return out

        self.device.handle = tamper
        env.engine.execute(1, "w1")
        job = env.live
        self.assertEqual(job.status, st.FAILED_ROLLBACK_CONFIRMED, job.summary)
        self.assertIsNone(self.device.trial)
        self.assertEqual(
            hw.normalize_config(self.device.running),
            hw.normalize_config(stored(CE_RUNNING)),
        )
        self.assertFalse(
            any(name.startswith("nabs-restore-") for name in self.device.files)
        )

    def test_a_lost_session_ends_with_the_device_back_on_its_old_configuration(self):
        device = CeDevice()
        device.drop_after = "commit trial"
        env = self.build(device)
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.FAILED_ROLLBACK_CONFIRMED, job.summary)
        self.assertEqual(device.running, CE_RUNNING)
        self.assertEqual(
            sum(c.startswith("commit trial") for c in device.commands), 1
        )  # never re-applied

    def test_blocked_prechecks(self):
        cases = {
            "an S-series switch": CeDevice(version=S_VERSION),
            "no two-phase mode": CeDevice(two_phase=False),
            "no sftp": CeDevice(running=CE_RUNNING.replace("sftp server enable\n", "")),
            "no space": CeDevice(free_kb=1),
        }
        for name, device in cases.items():
            env = self.build(device)
            self.assertEqual(env.engine.run_precheck(1)["status"], "blocked", name)
            self.assertEqual(env.live.status, st.FAILED, name)
            self.assertIsNone(device.trial, name)

    def test_the_password_is_nowhere_in_the_journal(self):
        env = self.build()
        self.run_to_end(env)
        self.assertNotIn(PASSWORD, env.all_text())


if __name__ == "__main__":
    unittest.main()
