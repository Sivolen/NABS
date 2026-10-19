"""
Restore Engine, stage 8: the Cisco IOS / IOS XE adapter, against a SIMULATED device.

Nothing here proves that real devices behave like the simulator: the outputs are written
from Cisco's documented formats. These tests check the adapter's own logic and its
cooperation with the engine.
"""

import os
import unittest
from pathlib import Path

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.restore import actions, adapters, schema, states as st  # noqa: E402
from app.modules.restore.adapters import base  # noqa: E402
from app.modules.restore.adapters import cisco_ios as cisco  # noqa: E402
from app.modules.restore.adapters.cisco_ios import CiscoIosAdapter  # noqa: E402
from app.modules.restore.engine import ENGINE_IMPLEMENTED_ACTIONS  # noqa: E402
from app.modules.restore.profiles import BuiltinProfileProvider  # noqa: E402
from cisco_sim import (  # noqa: E402
    RUNNING,
    SHOW_VERSION_ASA,
    SHOW_VERSION_IOS,
    SHOW_VERSION_IOSXE,
    SHOW_VERSION_NXOS,
    SHOW_VERSION_XR,
    TARGET,
    SimDevice,
    make_factory,
    make_transfer,
)
from restore_test_support import PASSWORD, Env  # noqa: E402

SHIPPED = BuiltinProfileProvider().get("builtin", "cisco_ios")


def profile():
    result = schema.parse_profile_yaml(SHIPPED.content, allow_builtin=True)
    assert result.ok, result.issues
    return result.profile


def make_adapter(device, **kw):
    return CiscoIosAdapter(
        connection_factory=kw.pop("factory", make_factory(device)),
        transfer=make_transfer(device),
        sleep=lambda s: None,
        **kw,
    )


def make_ctx(device_sim, target=TARGET, scratch=None, params=None):
    info = base.DeviceInfo(1, "192.0.2.1", "sw1", "ios")
    ctx = base.RestoreContext(
        job_id=7, device=info, profile=profile(), target_config=target
    )
    ctx.scratch.update(scratch or {})
    ctx.params = params or {}
    return ctx


def connected(device, **kw):
    adapter = make_adapter(device, **kw)
    adapter.connect(
        base.DeviceInfo(1, "192.0.2.1", "sw1", "ios"),
        base.Credentials("admin", PASSWORD),
        5,
    )
    return adapter


def prepared_ctx(device, target=TARGET):
    """The context as it is after a normal precheck."""
    adapter = connected(device)
    ctx = make_ctx(device, target)
    assert adapter.fetch_current_config(ctx).ok
    assert adapter.check_rollback_available(ctx).ok
    ctx.scratch["pre_restore_config"] = RUNNING
    return adapter, ctx


class TestParsers(unittest.TestCase):
    def test_show_version(self):
        xe = cisco.parse_show_version(SHOW_VERSION_IOSXE)
        self.assertEqual((xe.family, xe.version), ("iosxe", "16.09.04"))
        ios = cisco.parse_show_version(SHOW_VERSION_IOS)
        self.assertEqual(
            (ios.family, ios.version, ios.model),
            ("ios", "15.2(7)E3", "WS-C2960X-24TS-L"),
        )
        self.assertEqual(cisco.parse_show_version(SHOW_VERSION_NXOS).family, "nxos")
        self.assertEqual(cisco.parse_show_version(SHOW_VERSION_XR).family, "iosxr")
        self.assertEqual(cisco.parse_show_version(SHOW_VERSION_ASA).family, "asa")
        self.assertIsNone(cisco.parse_show_version("garbage"))
        self.assertIsNone(cisco.parse_show_version(""))

    def test_dir(self):
        info = cisco.parse_dir(
            "Directory of bootflash:/\n\n 1 -rw- 5 x\n\n11353194496 bytes total (9876543210 bytes free)\n"
        )
        self.assertEqual(
            (info.filesystem, info.total, info.free),
            ("bootflash:", 11353194496, 9876543210),
        )
        self.assertIsNone(cisco.parse_dir("nothing useful"))

    def test_diff(self):
        diff = cisco.parse_diff(
            "!Contextual Config Diffs:\n+hostname a\n-hostname b\n+ no shutdown\n!List of Rollback Commands:\nhostname b\n"
        )
        self.assertEqual(diff.added, ("hostname a", " no shutdown"))
        self.assertEqual(diff.removed, ("hostname b",))
        self.assertTrue(cisco.parse_diff("No changes were found").identical)
        self.assertIsNone(cisco.parse_diff("something unexpected"))

    def test_normalization(self):
        raw = "Building configuration...\n\nCurrent configuration : 99 bytes\n!\nhostname a  \n\n! comment\nntp clock-period 17180\ninterface x\n"
        self.assertEqual(cisco.normalize_config(raw), "hostname a\ninterface x")
        self.assertIn("! comment", cisco.normalize_config(raw, mode="exact"))
        self.assertEqual(
            cisco.normalize_config("a\nsecret-x 1\nb", [r"secret-x \d\n"]), "a\nb"
        )
        self.assertEqual(
            cisco.strip_show_header(
                "Building configuration...\n\nCurrent configuration : 5 bytes\n!\nx\nend\n"
            ).splitlines()[0],
            "!",
        )

    def test_exceptions_are_translated(self):
        class NetmikoAuthenticationException(Exception):
            pass

        class ReadTimeout(Exception):
            pass

        self.assertIsInstance(
            cisco._translate(NetmikoAuthenticationException("x")),
            base.AuthenticationFailed,
        )
        self.assertIsInstance(cisco._translate(ReadTimeout("x")), base.AdapterTimeout)
        self.assertIsInstance(cisco._translate(OSError("x")), base.ConnectionLost)
        self.assertIsInstance(cisco._translate(EOFError()), base.ConnectionLost)
        self.assertNotIsInstance(cisco._translate(ValueError("x")), base.ConnectionLost)


class TestRegistryAndProfile(unittest.TestCase):
    def test_declared_capabilities_are_exactly_the_implemented_handlers(self):
        self.assertEqual(CiscoIosAdapter.supported_actions(), set(base.ACTION_HANDLERS))
        self.assertTrue(CiscoIosAdapter.supports_rollback())
        self.assertFalse(CiscoIosAdapter.verified)

    def test_off_by_default_on_when_enabled(self):
        self.assertEqual(adapters.adapter_classes(), {})
        self.assertIsNone(adapters.create_adapter("cisco_ios"))
        self.assertIs(
            adapters.adapter_classes(include_unverified=True)["cisco_ios"],
            CiscoIosAdapter,
        )
        self.assertIsInstance(
            adapters.create_adapter(
                "cisco_ios", include_unverified=True, ignore_patterns=["x"]
            ),
            CiscoIosAdapter,
        )

    def test_shipped_profile_is_valid_and_matches_the_adapter(self):
        self.assertEqual(BuiltinProfileProvider().errors, [])
        self.assertEqual(
            BuiltinProfileProvider().keys(), ["cisco_ios", "huawei_ce", "huawei_s"]
        )
        p = profile()
        self.assertEqual(
            (p.adapter_type, p.platforms, p.builtin),
            ("cisco_ios", ("ios", "cisco_ios", "cisco_xe"), True),
        )
        self.assertEqual(p.rollback_strategy, "platform_specific")
        self.assertTrue(p.mark_unknown_if_connection_lost)
        self.assertTrue(
            p.warnings and any("not been verified" in w for w in p.warnings)
        )
        caps = adapters.adapter_capabilities(
            engine_actions=ENGINE_IMPLEMENTED_ACTIONS, include_unverified=True
        )
        self.assertEqual(schema.check_adapter_capabilities(p, caps), [])
        off = adapters.adapter_capabilities(engine_actions=ENGINE_IMPLEMENTED_ACTIONS)
        self.assertEqual(
            [i.code for i in schema.check_adapter_capabilities(p, off)],
            ["adapter_not_implemented"],
        )

    def test_the_profile_carries_no_secret_and_no_command(self):
        import yaml

        data = yaml.safe_load(SHIPPED.content)

        def keys(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    yield key
                    yield from keys(value)
            elif isinstance(node, list):
                for item in node:
                    yield from keys(item)

        self.assertEqual([k for k in keys(data) if schema.SECRET_KEY_RE.search(k)], [])
        for step in data["restore"]["steps"]:
            self.assertIn(step["action"], actions.ACTIONS)  # only catalogued actions
            self.assertEqual(set(step) - {"action", "params", "required"}, set())


class TestCustomDriverDevices(unittest.TestCase):
    """Devices that use a NABS custom driver (Netmiko) instead of a NAPALM driver."""

    def connect_kwargs(self, **device_kw):
        device = SimDevice()
        adapter = make_adapter(device)
        adapter.connect(
            base.DeviceInfo(1, "192.0.2.1", "sw1", "cisco_xe", **device_kw),
            base.Credentials("a", "b"),
            5,
        )
        return device.last_connect_kwargs

    def test_the_netmiko_type_of_the_custom_driver_is_used(self):
        self.assertEqual(
            self.connect_kwargs(netmiko_device_type="cisco_xe")["device_type"],
            "cisco_xe",
        )
        self.assertEqual(
            self.connect_kwargs(netmiko_device_type="cisco_ios")["device_type"],
            "cisco_ios",
        )

    def test_the_ssh_type_of_the_custom_driver_is_passed_through_as_it_is(self):
        # NABS only offers *_ssh types; backups already connect with them
        self.assertEqual(
            self.connect_kwargs(netmiko_device_type="cisco_ios_ssh")["device_type"],
            "cisco_ios_ssh",
        )
        self.assertEqual(
            self.connect_kwargs(netmiko_device_type="cisco_xe_ssh")["device_type"],
            "cisco_xe_ssh",
        )
        self.assertEqual(
            self.connect_kwargs(netmiko_device_type="cisco_ios_telnet")["device_type"],
            "cisco_ios",
        )

    def test_napalm_devices_and_foreign_types_use_the_default(self):
        self.assertEqual(self.connect_kwargs()["device_type"], "cisco_ios")
        self.assertEqual(
            self.connect_kwargs(netmiko_device_type="cisco_s300")["device_type"],
            "cisco_ios",
        )

    def test_custom_driver_platforms_match_the_profile_but_foreign_ones_do_not(self):
        from app.modules.restore.compat import check_compatibility

        for platform, allowed in (
            ("ios", True),
            ("cisco_ios", True),
            ("cisco_xe", True),
            ("cisco_ios_ssh", True),
            ("cisco_xe_ssh", True),
            ("CISCO_IOS_SSH", True),
            ("cisco_ios_telnet", False),
            ("cisco_s300_ssh", False),
            ("cisco_s300", False),
            ("huawei_vrp_ssh", False),
            ("3", False),
            (None, False),
            ("_ssh", False),
        ):
            self.assertEqual(
                check_compatibility(profile(), platform).allowed, allowed, platform
            )

    def test_the_header_a_custom_driver_stored_is_not_sent_to_the_device(self):
        stored = (
            "Building configuration...\n\nCurrent configuration : 321 bytes\n!\n"
            + TARGET
        )
        device = SimDevice()
        adapter, ctx = prepared_ctx(device, stored)
        self.assertTrue(adapter.validate_target_config(ctx).ok)
        sent = device.files["flash:nabs-restore-7-target.cfg"]
        self.assertNotIn("Building configuration", sent)
        self.assertNotIn("Current configuration", sent)
        self.assertIn("hostname new-name", sent)
        adapter.apply_saved_config(ctx)
        self.assertNotIn(
            "Building configuration", device.files["flash:nabs-restore-7-target.cfg"]
        )
        self.assertTrue(adapter.verify_running_config(ctx).ok)

    def test_old_ios_using_line_is_a_header_too(self):
        text = cisco.strip_show_header(
            "Building configuration...\n\nCurrent configuration : 5 bytes\nUsing 1234 out of 262144 bytes\n!\nx\n"
        )
        self.assertNotIn("Using", text)

    def test_a_partial_stored_configuration_is_refused(self):
        device = SimDevice()
        partial = "hostname new-name\ninterface GigabitEthernet0/0\n ip address 192.0.2.1 255.255.255.0\nend\n"
        adapter, ctx = prepared_ctx(device, partial)
        result = adapter.validate_target_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("looks partial", result.message)
        self.assertIn("custom driver", result.message)
        self.assertNotIn(
            "flash:nabs-restore-7-target.cfg", device.files
        )  # nothing uploaded

    def test_a_large_removal_is_flagged(self):
        running = RUNNING + "".join(
            f"ip route 10.{i}.0.0 255.255.0.0 192.0.2.254\n" for i in range(12)
        )
        device = SimDevice(running=running)
        target = RUNNING.replace("old-name", "new-name")
        adapter = connected(device)
        ctx = make_ctx(device, target)
        adapter.fetch_current_config(ctx)
        adapter.check_rollback_available(ctx)
        # the target keeps enough lines to pass the partial check but drops 12 routes
        ctx.scratch[
            "cisco_current_lines"
        ] = 16  # as if the device had 16 lines before the routes
        result = adapter.validate_target_config(ctx)
        self.assertTrue(result.ok, result.message)
        self.assertTrue(
            any("complete running-config" in w for w in result.warnings),
            result.warnings,
        )


class TestHandlers(unittest.TestCase):
    def test_platform_support(self):
        for version, ok in ((SHOW_VERSION_IOSXE, True), (SHOW_VERSION_IOS, True)):
            adapter = connected(SimDevice(version=version))
            self.assertEqual(adapter.check_platform_support(make_ctx(None)).ok, ok)
        for version in (SHOW_VERSION_NXOS, SHOW_VERSION_XR, SHOW_VERSION_ASA):
            result = connected(SimDevice(version=version)).check_platform_support(
                make_ctx(None)
            )
            self.assertEqual(result.verdict, base.Verdict.FAILED)
            self.assertIn("unsupported platform", result.message)
        self.assertEqual(
            connected(SimDevice(version="???"))
            .check_platform_support(make_ctx(None))
            .verdict,
            base.Verdict.UNKNOWN,
        )

    def test_connectivity_needs_privileged_mode(self):
        self.assertTrue(
            connected(SimDevice(prompt="sw#")).check_connectivity(make_ctx(None)).ok
        )
        result = connected(SimDevice(prompt="sw>")).check_connectivity(make_ctx(None))
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("privilege", result.message)
        self.assertEqual(
            connected(SimDevice(prompt="weird"))
            .check_connectivity(make_ctx(None))
            .verdict,
            base.Verdict.UNKNOWN,
        )

    def test_fetch_strips_the_header_and_rejects_truncated_output(self):
        device = SimDevice()
        result = connected(device).fetch_current_config(make_ctx(device))
        self.assertTrue(result.ok)
        self.assertNotIn("Building configuration", result.payload)
        self.assertNotIn("Current configuration", result.payload)
        self.assertTrue(result.payload.rstrip().endswith("end"))
        truncated = SimDevice(running="hostname x\n")
        self.assertFalse(
            connected(truncated).fetch_current_config(make_ctx(truncated)).ok
        )

    def test_rollback_space_check(self):
        device = SimDevice()
        adapter = connected(device)
        ctx = make_ctx(device)
        adapter.fetch_current_config(ctx)
        self.assertTrue(adapter.check_rollback_available(ctx).ok)
        self.assertEqual(ctx.scratch["cisco_fs"], "flash:")
        small = SimDevice(free=100)
        adapter = connected(small)
        ctx = make_ctx(small)
        adapter.fetch_current_config(ctx)
        result = adapter.check_rollback_available(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("not enough free space", result.message)
        self.assertNotIn("cisco_fs", ctx.scratch)

    def test_validate_reports_the_diff_and_leaves_the_device_unchanged(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device)
        result = adapter.validate_target_config(ctx)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.details, {"added": 1, "removed": 1})
        self.assertEqual(device.running, RUNNING)  # nothing was applied
        self.assertFalse(
            any(c.startswith("configure replace") for c in device.commands)
        )

    def test_validate_cleans_up_its_upload_and_never_leaves_a_local_copy(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device)
        adapter.validate_target_config(ctx)
        self.assertIn("flash:nabs-restore-7-target.cfg", device.files)
        self.assertFalse(
            os.path.exists(device.last_local_file)
        )  # the temp file is gone
        adapter.close()
        self.assertNotIn("flash:nabs-restore-7-target.cfg", device.files)
        self.assertIn("delete /force flash:nabs-restore-7-target.cfg", device.commands)

    def test_validate_refuses_a_config_without_end_and_warns_without_version(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device, target="hostname x\ninterface a\n")
        result = adapter.validate_target_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("'end'", result.message)
        no_version = RUNNING.replace(
            "version 16.9\n", ""
        )  # keeps the management address
        adapter, ctx = prepared_ctx(device, target=no_version)
        result = adapter.validate_target_config(ctx)
        self.assertTrue(result.ok, result.message)
        self.assertTrue(any("version" in w for w in result.warnings))

    def test_validate_blocks_a_restore_that_removes_the_management_address(self):
        device = SimDevice()
        target = RUNNING.replace(
            "192.0.2.1 255.255.255.0", "198.51.100.9 255.255.255.0"
        )
        adapter, ctx = prepared_ctx(device, target)
        result = adapter.validate_target_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("management address 192.0.2.1", result.message)

    def test_validate_warns_when_access_related_lines_go_away(self):
        device = SimDevice()
        target = RUNNING.replace(" transport input ssh\n", " transport input telnet\n")
        adapter, ctx = prepared_ctx(device, target)
        result = adapter.validate_target_config(ctx)
        self.assertTrue(result.ok)
        self.assertTrue(any("remote access" in w for w in result.warnings))

    def test_validate_flags_an_identical_configuration(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device, RUNNING)
        result = adapter.validate_target_config(ctx)
        self.assertTrue(
            any("already has this configuration" in w for w in result.warnings)
        )

    def test_validate_upload_failure_is_a_clear_refusal(self):
        device = SimDevice()
        device.transfer_error = RuntimeError("scp refused")
        adapter, ctx = prepared_ctx(device)
        result = adapter.validate_target_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("ip scp server enable", result.message)

    def test_validate_with_an_unreadable_comparison_is_undecided_not_ok(self):
        device = SimDevice()
        device.diff_output = "gibberish"
        adapter, ctx = prepared_ctx(device)
        self.assertEqual(
            adapter.validate_target_config(ctx).verdict, base.Verdict.UNKNOWN
        )
        device.diff_output = "%Error opening flash:x (No such file or directory)"
        self.assertEqual(
            adapter.validate_target_config(ctx).verdict, base.Verdict.FAILED
        )


class TestLongCommandsAndDiffView(unittest.TestCase):
    def test_long_commands_wait_for_the_prompt(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device)
        device.kwargs_log.clear()
        adapter.apply_saved_config(ctx)
        replace = [
            kw for cmd, kw in device.kwargs_log if cmd.startswith("configure replace")
        ]
        self.assertEqual(len(replace), 1)
        self.assertIn("expect_string", replace[0])  # not a fixed-silence read
        self.assertEqual(
            replace[0]["read_timeout"], 300
        )  # operation_timeout of the profile
        self.assertFalse(replace[0]["strip_prompt"])

    def test_prompts_are_answered_with_a_new_line_command(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device)
        device.kwargs_log.clear()
        adapter.apply_saved_config(ctx)
        copy_steps = [c for c, _ in device.kwargs_log][:2]
        self.assertEqual(
            copy_steps, ["copy running-config flash:nabs-restore-7-pre.cfg", "\n"]
        )

    def test_the_diff_view_drops_headers_and_timestamp_comments(self):
        adapter = CiscoIosAdapter()
        text = (
            "Building configuration...\n\nCurrent configuration : 321 bytes\n!\n"
            "! Last configuration change at 13:55:12 SAKH Mon Oct 5 2026 by a\n"
            "! NVRAM config last updated at 12:42:31 SAKH Tue Sep 22 2026 by a\n!\nversion 15.2\nend\n"
        )
        shown = adapter.normalize_for_diff(text)
        for gone in (
            "Building configuration",
            "Current configuration",
            "Last configuration change",
            "NVRAM config",
        ):
            self.assertNotIn(gone, shown)
        self.assertIn("version 15.2", shown)

    def test_the_precheck_diff_shows_only_the_real_difference(self):
        device = SimDevice()
        env = EngineCase().build(device)
        stored = (
            "Building configuration...\n\nCurrent configuration : 54536 bytes\n!\n"
            "! Last configuration change at 13:55:12 SAKH Mon Oct 5 2026 by a\n"
            + TARGET
        )
        env.configs.add(10, 1, stored)
        device.running = (
            "! Last configuration change at 10:49:39 SAKH Wed Oct 7 2026 by a\n"
            + RUNNING
        )
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "warning", result["checks"])
        diff = result["diff"]
        self.assertEqual(
            (diff["added"], diff["removed"]), (1, 1)
        )  # only the hostname line
        body = "\n".join(diff["lines"])
        self.assertNotIn("Building configuration", body)
        self.assertNotIn("Last configuration change", body)

    def test_a_config_that_differs_only_in_header_and_comments_is_reported_identical(
        self,
    ):
        device = SimDevice()
        env = EngineCase().build(device)
        env.configs.add(
            10,
            1,
            "Building configuration...\n\nCurrent configuration : 5 bytes\n" + RUNNING,
        )
        device.running = (
            "! Last configuration change at 10:49:39 SAKH Wed Oct 7 2026 by a\n"
            + RUNNING
        )
        result = env.engine.run_precheck(1)
        self.assertTrue(result["diff"]["identical"])
        self.assertTrue(any("already has" in w for w in result["warnings"]))


class TestScpPrerequisites(unittest.TestCase):
    """The reported case: the precheck failed with a bare 'SCPException'."""

    def test_scp_disabled_is_named_before_anything_is_uploaded(self):
        device = SimDevice(running=RUNNING.replace("ip scp server enable\n", ""))
        adapter, ctx = prepared_ctx(device)
        result = adapter.validate_target_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("no 'ip scp server enable' line", result.message)
        self.assertFalse(any(c.startswith("<scp") for c in device.commands))
        self.assertEqual(device.files, {})

    def test_the_error_text_of_a_failed_upload_is_reported(self):
        class SCPException(Exception):
            pass

        device = SimDevice()
        device.transfer_error = SCPException(
            "scp: flash:nabs-restore-7-target.cfg: Permission denied"
        )
        adapter, ctx = prepared_ctx(device)
        result = adapter.validate_target_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn(
            "SCPException: scp: flash:nabs-restore-7-target.cfg: Permission denied",
            result.message,
        )

    def test_aaa_without_exec_authorization_is_pointed_out(self):
        class SCPException(Exception):
            pass

        device = SimDevice(
            running=RUNNING.replace(
                "hostname old-name\n", "hostname old-name\naaa new-model\n"
            )
        )
        device.transfer_error = SCPException("Channel closed")
        adapter, ctx = prepared_ctx(device)
        result = adapter.validate_target_config(ctx)
        self.assertIn("no 'aaa authorization exec' line", result.message)
        withexec = SimDevice(
            running=RUNNING.replace(
                "hostname old-name\n",
                "hostname old-name\naaa new-model\naaa authorization exec default local\n",
            )
        )
        withexec.transfer_error = SCPException("Channel closed")
        adapter, ctx = prepared_ctx(withexec)
        self.assertNotIn(
            "no 'aaa authorization exec' line",
            adapter.validate_target_config(ctx).message,
        )

    def test_an_upload_error_never_carries_the_password(self):
        class SCPException(Exception):
            pass

        env = EngineCase()
        device = SimDevice()
        device.transfer_error = SCPException(f"login failed for admin / {PASSWORD}")
        built = env.build(device)
        built.engine.run_precheck(1)
        self.assertNotIn(PASSWORD, built.all_text())
        self.assertIn("***", built.all_text())

    def test_precheck_with_scp_disabled_blocks_with_a_readable_reason_and_changes_nothing(
        self,
    ):
        env = EngineCase()
        device = SimDevice(running=RUNNING.replace("ip scp server enable\n", ""))
        built = env.build(device)
        result = built.engine.run_precheck(1)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("ip scp server enable", str(result["checks"]))
        self.assertEqual(built.live.status, st.FAILED)
        self.assertEqual(device.running, RUNNING.replace("ip scp server enable\n", ""))
        self.assertEqual(device.files, {})


class TestApply(unittest.TestCase):
    def test_sequence_and_what_is_kept(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device)
        result = adapter.apply_saved_config(ctx)
        self.assertTrue(result.ok)
        self.assertIn("not yet verified", result.message)
        order = [
            c
            for c in device.commands
            if c.startswith(("copy running", "configure replace", "<scp"))
        ]
        self.assertEqual(
            order,
            [
                "copy running-config flash:nabs-restore-7-pre.cfg",
                "<scp nabs-restore-7-target.cfg>",
                "configure replace flash:nabs-restore-7-target.cfg force",
            ],
        )
        self.assertEqual(ctx.scratch["device_pre_file"], "flash:nabs-restore-7-pre.cfg")
        self.assertEqual(device.files["flash:nabs-restore-7-pre.cfg"], RUNNING)
        adapter.close()  # after an apply the files are evidence: they stay
        self.assertIn("flash:nabs-restore-7-pre.cfg", device.files)
        self.assertIn("flash:nabs-restore-7-target.cfg", device.files)
        self.assertFalse(any(c.startswith("delete") for c in device.commands))

    def test_configuration_text_is_never_sent_as_a_command(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device)
        adapter.validate_target_config(ctx)
        adapter.apply_saved_config(ctx)
        for line in TARGET.splitlines():
            if line.strip() and line.strip() not in ("end",):
                self.assertFalse(
                    any(
                        line in command
                        for command in device.commands
                        if not command.startswith("<scp")
                    ),
                    line,
                )

    def test_a_device_error_is_a_failure_and_the_output_without_markers_is_unknown(
        self,
    ):
        device = SimDevice()
        device.replace_output = "% Invalid input detected at '^' marker."
        adapter, ctx = prepared_ctx(device)
        self.assertEqual(adapter.apply_saved_config(ctx).verdict, base.Verdict.FAILED)
        device = SimDevice()
        device.replace_output = "..."
        adapter, ctx = prepared_ctx(device)
        self.assertEqual(adapter.apply_saved_config(ctx).verdict, base.Verdict.UNKNOWN)

    def test_a_failed_snapshot_stops_before_anything_is_replaced(self):
        device = SimDevice()
        device.copy_output = "%Error copying running-config (No space left on device)"
        adapter, ctx = prepared_ctx(device)
        result = adapter.apply_saved_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertIn("nothing was changed", result.message)
        self.assertFalse(
            any(c.startswith("configure replace") for c in device.commands)
        )
        self.assertNotIn("device_pre_file", ctx.scratch)

    def test_a_failed_upload_stops_before_the_replace(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device)
        device.transfer_error = RuntimeError("scp down")
        result = adapter.apply_saved_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertFalse(
            any(c.startswith("configure replace") for c in device.commands)
        )

    def test_a_dropped_session_during_the_replace_is_connection_lost(self):
        device = SimDevice()

        def drop(dev):
            dev.running = dev.files["flash:nabs-restore-7-target.cfg"]  # it took effect
            raise OSError("socket is closed")

        device.on_replace = drop
        adapter, ctx = prepared_ctx(device)
        with self.assertRaises(base.ConnectionLost):
            adapter.apply_saved_config(ctx)

    def test_unsafe_device_file_names_are_never_deleted(self):
        device = SimDevice()
        adapter = connected(device)
        adapter._delete_device_file("flash:startup-config")
        adapter._delete_device_file("flash:nabs-restore-1-target.cfg; reload")
        self.assertFalse(any(c.startswith("delete") for c in device.commands))


class TestVerifyPersistRollback(unittest.TestCase):
    def applied(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device)
        adapter.apply_saved_config(ctx)
        return device, adapter, ctx

    def test_management_access_uses_a_new_session(self):
        device, adapter, ctx = self.applied()
        before = device.sessions_opened
        ctx.params = {"attempts": 3, "wait_seconds": 1}
        self.assertTrue(adapter.verify_management_access(ctx).ok)
        self.assertEqual(device.sessions_opened, before + 1)

    def test_management_access_retries_then_fails(self):
        device, adapter, ctx = self.applied()
        device.new_sessions_allowed = False
        slept = []
        adapter._sleep = slept.append
        ctx.params = {"attempts": 3, "wait_seconds": 7}
        result = adapter.verify_management_access(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertEqual(slept, [7, 7, 7])

    def test_running_config_matches_or_differs_without_leaking_lines(self):
        device, adapter, ctx = self.applied()
        self.assertTrue(adapter.verify_running_config(ctx).ok)
        device.running = device.running.replace("new-name", "SECRET-HOSTNAME-LEAK")
        result = adapter.verify_running_config(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertEqual(result.details, {"missing": 1, "unexpected": 1})
        self.assertNotIn("SECRET-HOSTNAME-LEAK", result.message + str(result.details))

    def test_compare_modes(self):
        device, adapter, ctx = self.applied()
        device.running += "! Last configuration change at 12:00\n"
        ctx.params = {"compare": "normalized"}
        self.assertTrue(adapter.verify_running_config(ctx).ok)
        ctx.params = {"compare": "exact"}
        self.assertFalse(adapter.verify_running_config(ctx).ok)

    def test_nabs_clear_patterns_are_ignored_in_the_comparison(self):
        device = SimDevice()
        adapter = connected(device, ignore_patterns=[r"ntp clock-period \d+\n"])
        ctx = make_ctx(device)
        device.running = TARGET.replace("end\n", "ntp clock-period 17179\nend\n")
        self.assertTrue(adapter.verify_running_config(ctx).ok)

    def test_persist(self):
        device, adapter, ctx = self.applied()
        self.assertTrue(adapter.persist_config(ctx).ok)
        self.assertEqual(device.startup, device.running)
        device.commands.clear()
        self.assertEqual(
            adapter.persist_config(make_ctx(device)).verdict, base.Verdict.OK
        )

    def test_persist_unclear_output_is_unknown(self):
        device, adapter, ctx = self.applied()
        device.handle = lambda command: "?"
        self.assertEqual(adapter.persist_config(ctx).verdict, base.Verdict.UNKNOWN)

    def test_rollback_uses_the_device_copy_and_is_verified_against_the_nabs_copy(self):
        device, adapter, ctx = self.applied()
        self.assertTrue(adapter.rollback(ctx).ok)
        self.assertIn(
            "configure replace flash:nabs-restore-7-pre.cfg force", device.commands
        )
        self.assertEqual(device.running, RUNNING)
        self.assertTrue(adapter.verify_rollback(ctx).ok)

    def test_rollback_that_changed_nothing_is_not_confirmed(self):
        device, adapter, ctx = self.applied()
        device.replace_applies = False
        self.assertTrue(adapter.rollback(ctx).ok)  # accepted ...
        self.assertEqual(
            adapter.verify_rollback(ctx).verdict, base.Verdict.FAILED
        )  # ... but not true

    def test_rollback_without_a_device_copy(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device)
        result = adapter.rollback(ctx)
        self.assertEqual(result.verdict, base.Verdict.FAILED)
        self.assertFalse(
            any(c.startswith("configure replace") for c in device.commands)
        )

    def test_verify_rollback_without_a_stored_copy_is_undecided(self):
        device, adapter, ctx = self.applied()
        ctx.scratch.pop("pre_restore_config")
        self.assertEqual(adapter.verify_rollback(ctx).verdict, base.Verdict.UNKNOWN)


class TestSecrets(unittest.TestCase):
    def test_password_is_only_given_to_the_connection(self):
        device = SimDevice()
        adapter, ctx = prepared_ctx(device)
        adapter.validate_target_config(ctx)
        adapter.apply_saved_config(ctx)
        self.assertEqual(device.last_connect_kwargs["password"], PASSWORD)
        self.assertEqual(device.last_connect_kwargs["device_type"], "cisco_ios")
        self.assertNotIn(PASSWORD, repr(adapter))
        self.assertFalse(any(PASSWORD in c for c in device.commands))

    def test_connection_errors_never_carry_the_exception_text(self):
        def factory(**kwargs):
            raise RuntimeError(f"boom {kwargs['password']}")

        adapter = CiscoIosAdapter(connection_factory=factory)
        with self.assertRaises(base.AdapterConnectionError) as ctx:
            adapter.connect(
                base.DeviceInfo(1, "192.0.2.1", "sw", "ios"),
                base.Credentials("a", PASSWORD),
                5,
            )
        self.assertNotIn(PASSWORD, str(ctx.exception))

    def test_authentication_failure_is_reported_as_such(self):
        class NetmikoAuthenticationException(Exception):
            pass

        def factory(**kwargs):
            raise NetmikoAuthenticationException("bad")

        adapter = CiscoIosAdapter(connection_factory=factory)
        with self.assertRaises(base.AuthenticationFailed):
            adapter.connect(
                base.DeviceInfo(1, "192.0.2.1", "sw", "ios"),
                base.Credentials("a", "b"),
                5,
            )


# ------------------------------------------------------------ engine + adapter + simulator
class EngineCase(unittest.TestCase):
    def build(self, device=None, factory=None, **kw):
        self.device = device or SimDevice()
        self.factory = factory or make_factory(self.device)
        adapter = CiscoIosAdapter(
            connection_factory=self.factory,
            transfer=make_transfer(self.device),
            sleep=lambda s: None,
            **kw,
        )
        env = Env(
            adapter=adapter,
            profile=SHIPPED.content,
            profile_source="builtin",
            device=base.DeviceInfo(1, "192.0.2.1", "sw1", "ios"),
        )
        env.configs.add(10, 1, TARGET)
        return env

    def run_to_end(self, env):
        env.to_queued()
        env.engine.execute(1, "w1")
        return env.live


class TestEngineWithCisco(EngineCase):
    def test_precheck_has_warnings_and_blocks_nothing(self):
        env = self.build()
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "warning", result["checks"])
        self.assertTrue(any("not been verified" in w for w in result["warnings"]))
        self.assertTrue(result["rollback_available"])
        self.assertEqual(self.device.running, RUNNING)
        self.assertNotIn(
            "flash:nabs-restore-1-target.cfg", self.device.files
        )  # cleaned up

    def test_full_success(self):
        env = self.build()
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.SUCCESS, job.summary)
        self.assertEqual(
            cisco.normalize_config(self.device.running), cisco.normalize_config(TARGET)
        )
        self.assertEqual(
            self.device.startup, self.device.running
        )  # saved as the last step
        self.assertEqual(
            sum(c.startswith("configure replace") for c in self.device.commands), 1
        )
        self.assertFalse(any("nabs-restore-" in name for name in self.device.files))
        self.assertNotIn("cleanup_errors", job.diagnostics or {})

    def test_cleanup_failure_after_success_is_journaled_without_false_failure(self):
        device = SimDevice()
        device.refuse_delete = True
        env = self.build(device)
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.SUCCESS, job.summary)
        self.assertIn("Temporary device files could not be cleaned up", job.summary)
        self.assertTrue(job.diagnostics.get("cleanup_errors"))
        self.assertTrue(
            any(e["type"] == "cleanup_incomplete" for e in env.store.events)
        )

    def test_the_step_parameters_of_the_profile_reach_the_adapter(self):
        env = self.build()
        waits = []
        env.adapter._sleep = waits.append
        self.run_to_end(env)
        self.assertEqual(
            waits, [10]
        )  # wait_seconds from the profile, one successful attempt

    def test_verification_mismatch_is_rolled_back_and_confirmed(self):
        device = SimDevice()
        device.replace_extra_line = (
            "interface Loopback99\n"  # the device adds something
        )
        env = self.build(device)
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.FAILED_ROLLBACK_CONFIRMED, job.summary)
        self.assertEqual(job.rollback_status, "confirmed")
        self.assertEqual(
            cisco.normalize_config(self.device.running), cisco.normalize_config(RUNNING)
        )

    def test_a_dropped_session_is_unknown_and_never_retried(self):
        device = SimDevice()

        def drop(dev):
            dev.running = dev.files["flash:nabs-restore-1-target.cfg"]
            raise OSError("socket is closed")

        device.on_replace = drop
        # precheck + execution open one session each; every later connect fails
        env = self.build(device, factory=make_factory(device, fail_after=2))
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.UNKNOWN, job.summary)
        self.assertTrue(any("nabs-restore-" in name for name in device.files))
        self.assertEqual(
            sum(c.startswith("configure replace") for c in device.commands), 1
        )
        self.assertNotIn(
            "configure replace flash:nabs-restore-1-pre.cfg force", device.commands
        )
        self.assertTrue(job.diagnostics["connection_lost"])

    def test_session_drops_but_the_device_comes_back_with_the_target(self):
        device = SimDevice()

        def drop(dev):
            dev.running = dev.files["flash:nabs-restore-1-target.cfg"]
            raise OSError("socket is closed")

        device.on_replace = drop
        env = self.build(device)  # reconnecting works
        job = self.run_to_end(env)
        self.assertEqual(job.status, st.SUCCESS, job.summary)
        self.assertTrue(
            any("connection was lost" in n for n in job.diagnostics["notes"])
        )
        self.assertEqual(
            sum(c.startswith("configure replace") for c in device.commands), 1
        )

    def test_no_new_ssh_session_after_the_replace_triggers_a_rollback(self):
        env = self.build()
        env.to_queued()
        self.device.on_replace = lambda dev: setattr(dev, "new_sessions_allowed", False)
        env.engine.execute(1, "w1")
        job = env.live
        self.assertEqual(job.status, st.FAILED_ROLLBACK_CONFIRMED, job.summary)
        self.assertIn(
            "configure replace flash:nabs-restore-1-pre.cfg force", self.device.commands
        )

    def test_a_refused_replace_leaves_the_device_unchanged_and_is_a_clean_failure(self):
        device = SimDevice()
        device.replace_output = "% Invalid input detected at '^' marker."
        device.replace_applies = False
        job = self.run_to_end(self.build(device))
        self.assertEqual(job.status, st.FAILED)
        self.assertIn("verified unchanged", job.summary)
        self.assertFalse(job.diagnostics["device_touched"])

    def test_blocked_prechecks(self):
        cases = {
            "wrong platform": SimDevice(version=SHOW_VERSION_NXOS),
            "not privileged": SimDevice(prompt="sw>"),
            "no space": SimDevice(free=1000),
        }
        for name, device in cases.items():
            env = self.build(device)
            result = env.engine.run_precheck(1)
            self.assertEqual(result["status"], "blocked", name)
            self.assertEqual(env.live.status, st.FAILED, name)
            self.assertEqual(device.running, RUNNING, name)
            self.assertFalse(
                any(c.startswith("configure replace") for c in device.commands), name
            )

    def test_target_that_removes_the_management_address_is_blocked(self):
        env = self.build()
        env.configs.add(10, 1, RUNNING.replace("192.0.2.1 255", "198.51.100.9 255"))
        result = env.engine.run_precheck(1)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("management address", str(result["checks"]))

    def test_the_password_is_nowhere_in_the_journal(self):
        env = self.build()
        self.run_to_end(env)
        self.assertNotIn(PASSWORD, env.all_text())


if __name__ == "__main__":
    unittest.main()
