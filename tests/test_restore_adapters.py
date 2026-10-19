"""Restore Engine, stage 2: adapter interface, registry and the scriptable mock."""

import unittest

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.restore import actions, adapters, schema  # noqa: E402
from app.modules.restore.adapters import base  # noqa: E402
from app.modules.restore.adapters.mock import MockAdapter  # noqa: E402
from test_restore_schema import VALID  # noqa: E402

TARGET = "hostname A\ninterface 1\n"
PRE = "hostname B\n"


def make_ctx(target=TARGET, pre=PRE):
    profile = schema.parse_profile_yaml(VALID).profile
    device = base.DeviceInfo(
        device_id=1, ip="192.0.2.1", hostname="sw1", driver="mock_os"
    )
    ctx = base.RestoreContext(
        job_id=5, device=device, profile=profile, target_config=target
    )
    ctx.scratch["pre_restore_config"] = pre
    return ctx


class TestInterface(unittest.TestCase):
    def test_catalog_and_handlers_agree(self):
        self.assertEqual(
            set(actions.ACTIONS),
            set(base.ACTION_HANDLERS) | set(actions.ENGINE_ACTIONS),
        )
        for method in base.ACTION_HANDLERS.values():
            self.assertTrue(callable(getattr(base.RestoreAdapter, method)))

    def test_base_adapter_supports_nothing(self):
        self.assertEqual(base.RestoreAdapter.supported_actions(), frozenset())
        self.assertFalse(base.RestoreAdapter.supports_rollback())
        with self.assertRaises(base.UnsupportedOperation):
            base.RestoreAdapter().apply_saved_config(make_ctx())

    def test_partial_adapter_declares_only_what_it_overrides(self):
        class ReadOnly(base.RestoreAdapter):
            def fetch_current_config(self, ctx):
                return base.ActionResult.success(payload="x")

        self.assertEqual(ReadOnly.supported_actions(), {"fetch_current_config"})
        self.assertFalse(ReadOnly.supports_rollback())

    def test_mock_supports_every_adapter_action_and_rollback(self):
        self.assertEqual(MockAdapter.supported_actions(), set(base.ACTION_HANDLERS))
        self.assertTrue(MockAdapter.supports_rollback())

    def test_credentials_never_show_the_password(self):
        creds = base.Credentials("admin", "s3cr3t-pass")
        for text in (repr(creds), str(creds), f"{creds}", f"{[creds]}"):
            self.assertNotIn("s3cr3t-pass", text)

    def test_context_manager_closes(self):
        adapter = MockAdapter()
        with adapter:
            pass
        self.assertTrue(adapter.closed)


class TestRegistry(unittest.TestCase):
    def test_production_registry_has_no_adapters(self):
        self.assertEqual(adapters.adapter_classes(), {})
        self.assertIsNone(adapters.get_adapter_class("mock"))
        self.assertEqual(adapters.adapter_capabilities(), {})

    def test_mock_only_when_asked(self):
        self.assertIs(
            adapters.get_adapter_class("mock", include_mock=True), MockAdapter
        )

    def test_a_yaml_profile_alone_does_not_make_a_platform_supported(self):
        profile = schema.parse_profile_yaml(VALID).profile
        issues = schema.check_adapter_capabilities(
            profile, adapters.adapter_capabilities()
        )
        self.assertEqual([i.code for i in issues], ["adapter_not_implemented"])

    def test_profile_is_runnable_with_mock_and_engine_actions(self):
        profile = schema.parse_profile_yaml(VALID).profile
        caps = adapters.adapter_capabilities(
            include_mock=True, engine_actions=frozenset(actions.ENGINE_ACTIONS)
        )
        self.assertEqual(schema.check_adapter_capabilities(profile, caps), [])
        # without the engine's own action the profile is not runnable
        caps = adapters.adapter_capabilities(include_mock=True)
        issues = schema.check_adapter_capabilities(profile, caps)
        self.assertEqual([i.code for i in issues], ["action_not_supported"])


class TestMockAdapter(unittest.TestCase):
    def test_happy_path(self):
        adapter = MockAdapter(running_config=PRE)
        ctx = make_ctx()
        adapter.connect(ctx.device, base.Credentials("u", "p"), 5)
        self.assertEqual(adapter.fetch_current_config(ctx).payload, PRE)
        self.assertTrue(adapter.apply_saved_config(ctx).ok)
        self.assertTrue(adapter.verify_running_config(ctx).ok)
        self.assertEqual(adapter.saved_config, PRE)  # not persisted yet
        self.assertTrue(adapter.persist_config(ctx).ok)
        self.assertEqual(adapter.saved_config, TARGET)

    def test_apply_ok_is_not_proof_of_success(self):
        failing_verify = {"verify_running_config": base.ActionResult.failure("differs")}
        adapter = MockAdapter(running_config=PRE, script=failing_verify)
        ctx = make_ctx()
        self.assertTrue(adapter.apply_saved_config(ctx).ok)
        self.assertFalse(adapter.verify_running_config(ctx).ok)

    def test_scripted_exception_is_raised(self):
        adapter = MockAdapter(
            script={"connect": base.AuthenticationFailed("bad login")}
        )
        with self.assertRaises(base.AuthenticationFailed):
            adapter.connect(make_ctx().device, base.Credentials("u", "p"), 5)
        self.assertFalse(adapter.connected)

    def test_connection_lost_after_the_config_took_effect(self):
        adapter = MockAdapter(
            running_config=PRE,
            script={"apply_saved_config": base.ConnectionLost("session dropped")},
            apply_effect_before_error=True,
        )
        ctx = make_ctx()
        with self.assertRaises(base.ConnectionLost):
            adapter.apply_saved_config(ctx)
        self.assertEqual(adapter.running_config, TARGET)  # changed although it raised

    def test_failed_apply_does_not_change_the_device(self):
        adapter = MockAdapter(
            running_config=PRE,
            script={"apply_saved_config": base.ActionResult.failure("rejected")},
        )
        self.assertFalse(adapter.apply_saved_config(make_ctx()).ok)
        self.assertEqual(adapter.running_config, PRE)

    def test_rollback_and_its_verification_are_separate(self):
        adapter = MockAdapter(running_config=PRE)
        ctx = make_ctx()
        adapter.apply_saved_config(ctx)
        self.assertTrue(adapter.rollback(ctx).ok)
        self.assertTrue(adapter.verify_rollback(ctx).ok)

        broken = MockAdapter(
            running_config=PRE,
            script={"rollback": base.ActionResult.success("accepted")},
        )
        broken.apply_saved_config(ctx)
        self.assertTrue(broken.rollback(ctx).ok)  # accepted, but nothing restored
        self.assertFalse(broken.verify_rollback(ctx).ok)

    def test_empty_target_fails_validation(self):
        self.assertFalse(
            MockAdapter().validate_target_config(make_ctx(target=" \n")).ok
        )

    def test_whitespace_only_differences_do_not_fail_verification(self):
        adapter = MockAdapter(running_config="hostname A  \n\ninterface 1\n")
        self.assertTrue(adapter.verify_running_config(make_ctx()).ok)

    def test_calls_are_recorded(self):
        adapter = MockAdapter()
        ctx = make_ctx()
        adapter.connect(ctx.device, base.Credentials("u", "p"), 5)
        adapter.check_platform_support(ctx)
        adapter.close()
        self.assertEqual(adapter.calls, ["connect", "check_platform_support", "close"])


if __name__ == "__main__":
    unittest.main()
