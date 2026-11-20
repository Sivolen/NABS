"""
Restore Engine: the Huawei S-series adapter (startup file + REBOOT) against a SIMULATED device.
The outputs of the simulator are synthetic (written from documentation), see huawei_sim.py.
"""

import unittest

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.restore import adapters, schema, states as st  # noqa: E402
from app.modules.restore.adapters import base, huawei_common as hw  # noqa: E402
from app.modules.restore.adapters.huawei_s import HuaweiSAdapter  # noqa: E402
from app.modules.restore.engine import ENGINE_IMPLEMENTED_ACTIONS  # noqa: E402
from app.modules.restore.profiles import BuiltinProfileProvider  # noqa: E402
from huawei_sim import (  # noqa: E402
    CE_VERSION,
    S_RUNNING,
    S_VERSION,
    SDevice,
    make_factory,
    make_sftp,
    stored,
)
from restore_test_support import PASSWORD, Env  # noqa: E402

SHIPPED = BuiltinProfileProvider().get("builtin", "huawei_s")
TARGET = stored(S_RUNNING.replace("old-name", "new-name"))
PRE = stored(S_RUNNING)
INFO = base.DeviceInfo(
    1, "192.0.2.1", "sw1", "huawei_vrp_ssh", netmiko_device_type="huawei_vrp_ssh"
)


def profile():
    result = schema.parse_profile_yaml(SHIPPED.content, allow_builtin=True)
    assert result.ok, result.issues
    return result.profile


def make_adapter(device):
    return HuaweiSAdapter(
        connection_factory=make_factory(device),
        sftp_factory=make_sftp(device),
        sleep=lambda s: None,
    )


def make_ctx(target=TARGET, params=None):
    ctx = base.RestoreContext(
        job_id=7, device=INFO, profile=profile(), target_config=target
    )
    ctx.params = params or {}
    return ctx


def connected(device):
    adapter = make_adapter(device)
    adapter.connect(INFO, base.Credentials("admin", PASSWORD), 5)
    return adapter


def prepared(device, target=TARGET):
    adapter = connected(device)
    ctx = make_ctx(target)
    assert adapter.fetch_current_config(ctx).ok
    assert adapter.check_rollback_available(ctx).ok
    ctx.scratch["pre_restore_config"] = PRE
    return adapter, ctx


class TestProfileAndRegistry(unittest.TestCase):
    def test_the_profile_says_it_reboots(self):
        p = profile()
        self.assertTrue(p.disruptive)
        self.assertIn("REBOOT", p.description)
        self.assertTrue(any("REBOOTED" in w for w in p.warnings))
        self.assertEqual(p.limits["reconnect_timeout"], 600)
        self.assertEqual(p.limits["verify_timeout"], 900)
        self.assertEqual(p.adapter_type, "huawei_s")

    def test_registry(self):
        self.assertFalse(HuaweiSAdapter.verified)
        self.assertNotIn("huawei_s", adapters.adapter_classes())
        caps = adapters.adapter_capabilities(
            engine_actions=ENGINE_IMPLEMENTED_ACTIONS, include_unverified=True
        )
        self.assertEqual(schema.check_adapter_capabilities(profile(), caps), [])
        self.assertTrue(HuaweiSAdapter.supports_rollback())

    def test_disruptive_survives_export_and_import(self):
        text = schema.dump_profile_yaml(profile())
        self.assertIn("disruptive: true", text)
        again = schema.parse_profile_yaml(text, allow_builtin=True).profile
        self.assertTrue(again.disruptive)

    def test_disruptive_is_off_for_the_other_profiles(self):
        for key in ("cisco_ios", "huawei_ce"):
            parsed = schema.parse_profile_yaml(
                BuiltinProfileProvider().get("builtin", key).content, allow_builtin=True
            )
            self.assertFalse(parsed.profile.disruptive, key)
        bad = SHIPPED.content.replace("disruptive: true", "disruptive: maybe")
        self.assertFalse(schema.parse_profile_yaml(bad, allow_builtin=True).ok)


class TestPrecheckHandlers(unittest.TestCase):
    def test_platform(self):
        self.assertTrue(connected(SDevice()).check_platform_support(make_ctx()).ok)
        wrong = connected(SDevice(version=CE_VERSION)).check_platform_support(
            make_ctx()
        )
        self.assertEqual(wrong.verdict, base.Verdict.FAILED)
        self.assertIn("CloudEngine", wrong.message)

    def test_s_model_on_another_vrp_generation_is_not_treated_as_vrp5(self):
        version = "VRP (R) software, Version 8.220 (S5735-L-V2 V600R023C00SPC100)"
        device = SDevice(version=version)
        result = connected(device).check_platform_support(make_ctx())
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("VRP5 only", result.message)
        self.assertFalse(
            any(
                command.startswith("startup saved-configuration")
                for command in device.commands
            )
        )
        self.assertNotIn("reboot", device.commands)

    def test_connectivity(self):
        device = SDevice()
        self.assertTrue(connected(device).check_connectivity(make_ctx()).ok)
        device.view = "system"
        self.assertEqual(
            connected(device).check_connectivity(make_ctx()).verdict,
            base.Verdict.FAILED,
        )

    def test_rollback_check_reads_the_startup_file_and_the_space(self):
        device = SDevice()
        adapter = connected(device)
        ctx = make_ctx()
        adapter.fetch_current_config(ctx)
        result = adapter.check_rollback_available(ctx)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(ctx.scratch["huawei_orig_startup"], "vrpcfg.zip")
        self.assertEqual(result.warnings, ())
        device.current_startup = "flash:/other.cfg"
        again = connected(device)
        ctx = make_ctx()
        again.fetch_current_config(ctx)
        self.assertTrue(
            any(
                "will boot from" in w
                for w in again.check_rollback_available(ctx).warnings
            )
        )
        small = SDevice(free_kb=1)
        adapter = connected(small)
        ctx = make_ctx()
        adapter.fetch_current_config(ctx)
        self.assertEqual(
            adapter.check_rollback_available(ctx).verdict, base.Verdict.FAILED
        )

        stranded = SDevice()
        stranded.next_startup = "flash:/nabs-restore-4-target.cfg"
        adapter = connected(stranded)
        ctx = make_ctx()
        adapter.fetch_current_config(ctx)
        result = adapter.check_rollback_available(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("previous restore manually", result.message)

    def test_validate_uploads_checks_and_warns_about_the_reboot(self):
        device = SDevice()
        adapter, ctx = prepared(device)
        result = adapter.validate_target_config(ctx)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.details, {"added": 1, "removed": 1})
        self.assertTrue(any("REBOOT" in w for w in result.warnings))
        self.assertEqual(device.running, S_RUNNING)
        self.assertEqual(device.next_startup, "flash:/vrpcfg.zip")  # nothing changed
        adapter.close()
        self.assertNotIn("nabs-restore-7-target.cfg", device.files)  # cleaned up
        self.assertIn(
            "vrpcfg.zip", device.files
        )  # the device's own file is never touched

    def test_validate_refusals(self):
        off = SDevice(running=S_RUNNING.replace("sftp server enable\n", ""))
        adapter, ctx = prepared(off)
        self.assertIn("sftp server enable", adapter.validate_target_config(ctx).message)
        self.assertEqual([n for n in off.files if n.startswith("nabs")], [])
        device = SDevice()
        adapter, ctx = prepared(
            device, stored(S_RUNNING.replace("192.0.2.1", "198.51.100.9"))
        )
        self.assertIn("management address", adapter.validate_target_config(ctx).message)
        adapter, ctx = prepared(device, stored("sysname x\nreturn\n"))
        self.assertIn("looks partial", adapter.validate_target_config(ctx).message)
        adapter, ctx = prepared(device, stored(S_RUNNING).replace("return\n", ""))
        self.assertIn("'return'", adapter.validate_target_config(ctx).message)
        broken = SDevice()
        broken.sftp_error = RuntimeError("Permission denied")
        adapter, ctx = prepared(broken)
        self.assertIn(
            "RuntimeError: Permission denied",
            adapter.validate_target_config(ctx).message,
        )


class TestApplyAndReboot(unittest.TestCase):
    def applied(self, device=None):
        device = device or SDevice()
        adapter, ctx = prepared(device)
        return device, adapter, ctx, adapter.apply_saved_config(ctx)

    def test_apply_reboots_into_the_target_and_never_saves_over_it(self):
        device, adapter, ctx, result = self.applied()
        self.assertTrue(result.ok, result.message)
        self.assertEqual(device.reboot_count, 1)
        self.assertFalse(device.saved_over_next)  # the "save" question was answered n
        self.assertEqual(device.current_startup, "flash:/nabs-restore-7-target.cfg")
        self.assertEqual(
            hw.normalize_config(device.running), hw.normalize_config(TARGET)
        )
        self.assertEqual(device.files["nabs-restore-7-pre.cfg"], PRE)
        self.assertEqual(device.files["nabs-restore-7-target.cfg"], TARGET)
        self.assertEqual(
            device.files["vrpcfg.zip"], S_RUNNING
        )  # the original saved file is untouched
        self.assertIn("y\n", device.written)
        self.assertTrue(adapter._conn is None)  # the old session is gone
        self.assertEqual(ctx.scratch["device_pre_file"], "nabs-restore-7-pre.cfg")

    def test_the_questions_are_answered_in_the_right_order(self):
        device, adapter, ctx, _ = self.applied()
        after = device.commands[device.commands.index("reboot") :]
        self.assertEqual(
            after, ["reboot", "n"]
        )  # n to "save"; the final y is written, not sent

    def test_an_unknown_question_is_refused_and_the_startup_file_is_put_back(self):
        device = SDevice()
        device.reboot_questions = [("Do you want to format the flash? [Y/N]:", "other")]
        adapter, ctx = prepared(device)
        result = adapter.apply_saved_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("unexpected question", result.message)
        self.assertEqual(device.reboot_count, 0)
        self.assertEqual(device.next_startup, "flash:/vrpcfg.zip")  # put back
        self.assertEqual(device.running, S_RUNNING)

    def test_a_version_that_saves_over_the_file_without_a_choice_is_refused(self):
        device = SDevice()
        device.reboot_questions = [
            (
                "Warning: The current configuration will be saved to the next startup saved-configuration "
                "file. System will reboot! Continue? [Y/N]:",
                "combined",
            )
        ]
        adapter, ctx = prepared(device)
        result = adapter.apply_saved_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("would save the running configuration", result.message)
        self.assertEqual(device.reboot_count, 0)
        self.assertFalse(device.saved_over_next)
        self.assertEqual(device.next_startup, "flash:/vrpcfg.zip")

    def test_no_reboot_question_at_all_is_not_a_reboot(self):
        device = SDevice()
        device.reboot_questions = [("Info: Nothing to do.", "other")]
        device.reply_for_reboot = True
        original = device.extra
        device.extra = (
            lambda c: device.reply("Info: Command accepted.")
            if c == "reboot"
            else original(c)
        )
        adapter, ctx = prepared(device)
        result = adapter.apply_saved_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertEqual(device.reboot_count, 0)
        self.assertEqual(device.next_startup, "flash:/vrpcfg.zip")

    def test_a_refused_startup_file_stops_before_the_reboot(self):
        device = SDevice()
        device.startup_error = "Error: The file is not a valid configuration file."
        adapter, ctx = prepared(device)
        result = adapter.apply_saved_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertEqual(device.reboot_count, 0)

    def test_apply_needs_the_stored_copy_and_a_working_upload(self):
        device = SDevice()
        adapter, ctx = prepared(device)
        ctx.scratch.pop("pre_restore_config")
        self.assertEqual(adapter.apply_saved_config(ctx).verdict, base.Verdict.FAILED)
        device2 = SDevice()
        adapter, ctx = prepared(device2)
        device2.sftp_error = RuntimeError("no")
        self.assertEqual(adapter.apply_saved_config(ctx).verdict, base.Verdict.FAILED)
        self.assertEqual(device2.reboot_count, 0)


class TestVerifyPersistRollback(unittest.TestCase):
    def rebooted(self, device=None):
        device = device or SDevice()
        adapter, ctx = prepared(device)
        self.assertTrue(adapter.apply_saved_config(ctx).ok)
        return device, adapter, ctx

    def test_management_access_waits_for_the_device_and_replaces_the_session(self):
        device, adapter, ctx = self.rebooted()
        device.boots_offline_polls = 0
        device.refuse_new_sessions = 2  # refuses the first two attempts
        slept = []
        adapter._sleep = slept.append
        ctx.params = {"attempts": 5, "wait_seconds": 90}
        result = adapter.verify_management_access(ctx)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(slept, [90, 90, 90])
        self.assertIsNotNone(
            adapter._conn
        )  # the new session is the one used from now on
        self.assertTrue(adapter.verify_running_config(ctx).ok)

    def test_a_device_that_does_not_come_back(self):
        device, adapter, ctx = self.rebooted(SDevice())
        device.online = False
        ctx.params = {"attempts": 3, "wait_seconds": 1}
        self.assertEqual(
            adapter.verify_management_access(ctx).verdict, base.Verdict.FAILED
        )
        with self.assertRaises(
            base.ConnectionLost
        ):  # the rollback cannot reach it either
            adapter.rollback(ctx)

    def test_verify_requires_that_the_device_booted_from_the_restore_file(self):
        device, adapter, ctx = self.rebooted()
        ctx.params = {
            "attempts": 3,
            "wait_seconds": 0,
        }  # the device refuses the first poll
        self.assertTrue(adapter.verify_management_access(ctx).ok)
        device.current_startup = "flash:/vrpcfg.zip"  # the reboot did not use our file
        result = adapter.verify_running_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("did not boot from the restore file", result.message)

    def test_verify_running_config_counts_only(self):
        device, adapter, ctx = self.rebooted()
        ctx.params = {
            "attempts": 3,
            "wait_seconds": 0,
        }  # the device refuses the first poll
        self.assertTrue(adapter.verify_management_access(ctx).ok)
        device.running = device.running.replace("new-name", "LEAKY-NAME")
        result = adapter.verify_running_config(ctx)
        self.assertEqual(result.details, {"missing": 1, "unexpected": 1})
        self.assertNotIn("LEAKY-NAME", result.message + str(result.details))

    def test_persist_moves_the_configuration_back_to_the_original_file(self):
        device, adapter, ctx = self.rebooted()
        ctx.params = {
            "attempts": 3,
            "wait_seconds": 0,
        }  # the device refuses the first poll
        self.assertTrue(adapter.verify_management_access(ctx).ok)
        result = adapter.persist_config(ctx)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(
            hw.normalize_config(device.files["vrpcfg.zip"]), hw.normalize_config(TARGET)
        )
        self.assertEqual(device.next_startup, "flash:/vrpcfg.zip")

    def test_persist_with_an_unexpected_question_or_error(self):
        device, adapter, ctx = self.rebooted()
        ctx.params = {
            "attempts": 3,
            "wait_seconds": 0,
        }  # the device refuses the first poll
        self.assertTrue(adapter.verify_management_access(ctx).ok)
        device.save_output = "Error: Failed to write the file."
        result = adapter.persist_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("boots from nabs-restore-7-target.cfg", result.message)

    def test_rollback_points_the_startup_file_at_the_rollback_file_and_reboots(self):
        device, adapter, ctx = self.rebooted()
        ctx.params = {
            "attempts": 3,
            "wait_seconds": 0,
        }  # the device refuses the first poll
        self.assertTrue(adapter.verify_management_access(ctx).ok)
        result = adapter.rollback(ctx)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(device.reboot_count, 2)
        self.assertEqual(device.current_startup, "flash:/nabs-restore-7-pre.cfg")
        self.assertFalse(device.saved_over_next)
        self.assertTrue(adapter.verify_rollback(ctx).ok)
        self.assertEqual(hw.normalize_config(device.running), hw.normalize_config(PRE))
        self.assertEqual(device.next_startup, "flash:/vrpcfg.zip")
        self.assertEqual(
            hw.normalize_config(device.files["vrpcfg.zip"]), hw.normalize_config(PRE)
        )

    def test_rollback_without_a_rollback_file(self):
        device = SDevice()
        adapter, ctx = prepared(device)
        self.assertEqual(adapter.rollback(ctx).verdict, base.Verdict.FAILED)
        self.assertEqual(device.reboot_count, 0)

    def test_the_hazard_would_be_visible_if_a_save_question_were_ever_answered_yes(
        self,
    ):
        # documents what the strict answers protect against: with Y the target file is overwritten
        device = SDevice()
        adapter, ctx = prepared(device)
        device.handle("reboot")
        device.handle("y")  # the wrong answer to the save question
        self.assertTrue(device.saved_over_next)


class EngineCase(unittest.TestCase):
    def build(self, device=None):
        self.device = device or SDevice()
        adapter = make_adapter(self.device)
        env = Env(
            adapter=adapter,
            profile=SHIPPED.content,
            profile_source="builtin",
            device=INFO,
        )
        env.configs.add(10, 1, TARGET)
        return env

    def run_to_end(self, env):
        env.to_queued()
        env.engine.execute(1, "w1")
        return env.live


class TestEngineWithS(EngineCase):
    def test_precheck_is_flagged_disruptive_and_changes_nothing(self):
        env = self.build()
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "warning", result["checks"])
        self.assertTrue(result["disruptive"])
        self.assertTrue(any("INTERRUPTS SERVICE" in w for w in result["warnings"]))
        self.assertEqual(self.device.reboot_count, 0)
        self.assertEqual(self.device.next_startup, "flash:/vrpcfg.zip")
        self.assertNotIn("nabs-restore-1-target.cfg", self.device.files)

    def test_full_success(self):
        env = self.build()
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.SUCCESS, job.summary)
        self.assertEqual(self.device.reboot_count, 1)
        self.assertEqual(
            hw.normalize_config(self.device.running), hw.normalize_config(TARGET)
        )
        self.assertEqual(
            self.device.next_startup, "flash:/vrpcfg.zip"
        )  # back on the original file name
        self.assertEqual(
            hw.normalize_config(self.device.files["vrpcfg.zip"]),
            hw.normalize_config(TARGET),
        )
        self.assertFalse(
            any(name.startswith("nabs-restore-") for name in self.device.files)
        )

    def test_the_device_that_does_not_come_back_is_unknown(self):
        device = SDevice()
        device.never_boots = True
        env = self.build(device)
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.UNKNOWN, job.summary)
        self.assertEqual(
            device.reboot_count, 1
        )  # no second reboot was attempted blindly
        self.assertTrue(any(name.startswith("nabs-restore-") for name in device.files))

    def test_a_reboot_that_did_not_use_the_file_is_rolled_back(self):
        device = SDevice()
        env = self.build(device)
        env.to_queued()
        original = device.do_reboot

        def lazy_reboot():  # boots, but ignores the next-startup file (stays on the old config)
            device.reboot_count += 1
            device.alive = False
            device.refuse_new_sessions = 1
            device.view = "user"

        device.do_reboot = lazy_reboot
        env.engine.execute(1, "w1")
        job = env.live
        self.assertIn(
            job.status,
            (st.FAILED_ROLLBACK_CONFIRMED, st.FAILED, st.ROLLBACK_FAILED, st.UNKNOWN),
            job.summary,
        )
        self.assertNotEqual(job.status, st.SUCCESS)

    def test_refused_reboot_with_unrestored_startup_is_unknown(self):
        class RefusesOriginalStartup(SDevice):
            def handle(self, command):
                if command == "startup saved-configuration vrpcfg.zip":
                    return self.reply("Error: permission denied")
                return super().handle(command)

        device = RefusesOriginalStartup()
        device.reboot_questions = [
            ("Do you want to erase the device? [Y/N]:", "unknown")
        ]
        env = self.build(device)
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.UNKNOWN, job.summary)
        self.assertTrue(job.diagnostics["device_touched"])
        self.assertIn(device.next_startup.split("/")[-1], device.files)

    def test_a_refused_reboot_is_a_clean_failure(self):
        device = SDevice()
        device.reboot_questions = [("Format everything? [Y/N]:", "other")]
        env = self.build(device)
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.FAILED, job.summary)
        self.assertEqual(device.reboot_count, 0)
        self.assertEqual(device.next_startup, "flash:/vrpcfg.zip")

    def test_blocked_prechecks(self):
        cases = {
            "a CloudEngine": SDevice(version=CE_VERSION),
            "no sftp": SDevice(running=S_RUNNING.replace("sftp server enable\n", "")),
            "no space": SDevice(free_kb=1),
        }
        for name, device in cases.items():
            env = self.build(device)
            self.assertEqual(env.engine.run_precheck(1)["status"], "blocked", name)
            self.assertEqual(device.reboot_count, 0, name)

    def test_the_password_is_nowhere_in_the_journal(self):
        env = self.build()
        self.run_to_end(env)
        self.assertNotIn(PASSWORD, env.all_text())


if __name__ == "__main__":
    unittest.main()
