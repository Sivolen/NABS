"""
Restore Engine, stage 1: profile schema, validation, capabilities, compatibility.
The profile below is a TEST fixture for the "mock" adapter, not a shipped profile.
"""

import copy
import unittest

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

import yaml  # noqa: E402

from app.modules.restore import compat, schema  # noqa: E402

VALID = """
schema_version: 1
id: mock_platform
name: Mock platform
vendor: Test
platforms: [mock_os]
profile_version: 1
adapter:
  type: mock
restore:
  strategy: platform_specific
  require_precheck: true
  require_pre_restore_backup: true
  require_confirmation: true
  require_target_validation: true
  steps:
    - action: check_platform_support
    - action: check_rollback_available
    - action: fetch_current_config
    - action: save_pre_restore_backup
    - action: validate_target_config
    - action: apply_saved_config
    - action: verify_management_access
      params: {attempts: 2}
    - action: verify_running_config
failure:
  rollback_strategy: platform_specific
  mark_unknown_if_connection_lost: true
limits:
  connect_timeout: 10
"""


def data():
    return copy.deepcopy(yaml.safe_load(VALID))


def codes(result):
    return {i.code for i in result.errors}


class TestParsing(unittest.TestCase):
    def test_valid_profile(self):
        result = schema.parse_profile_yaml(VALID)
        self.assertTrue(result.ok, [str(i) for i in result.issues])
        self.assertEqual(result.profile.id, "mock_platform")
        self.assertEqual(result.profile.limits["operation_timeout"], 120)  # default
        self.assertFalse(result.profile.builtin)

    def test_broken_yaml_is_an_issue_not_an_exception(self):
        result = schema.parse_profile_yaml("a: [unclosed")
        self.assertFalse(result.ok)
        self.assertIn("yaml_syntax", codes(result))

    def test_not_text_and_not_a_mapping(self):
        self.assertIn("type", codes(schema.parse_profile_yaml(None)))
        self.assertIn("type", codes(schema.parse_profile_yaml("- a\n- b")))
        self.assertFalse(schema.parse_profile_yaml("").ok)

    def test_python_tags_are_rejected(self):
        evil = VALID + "\nx: !!python/object/apply:os.system ['echo hi']\n"
        self.assertFalse(schema.parse_profile_yaml(evil).ok)

    def test_aliases_are_rejected(self):
        text = VALID.replace("platforms: [mock_os]", "platforms: &p [mock_os]\nz: *p")
        self.assertIn("yaml_alias", codes(schema.parse_profile_yaml(text)))

    def test_duplicate_keys_are_rejected(self):
        text = VALID + "\nname: Another\n"
        result = schema.parse_profile_yaml(text)
        self.assertFalse(result.ok)
        self.assertIn("yaml_syntax", codes(result))

    def test_oversized_input(self):
        result = schema.parse_profile_yaml(VALID + "# " + "x" * schema.MAX_YAML_BYTES)
        self.assertIn("too_large", codes(result))

    def test_too_deep(self):
        d = data()
        node = d
        for _ in range(schema.MAX_YAML_DEPTH + 1):
            node["warnings"] = {}
            node = node["warnings"]
        self.assertIn("too_deep", codes(schema.validate_profile_data(d)))

    def test_unsupported_schema_version(self):
        d = data()
        d["schema_version"] = 99
        self.assertIn("unsupported_schema", codes(schema.validate_profile_data(d)))

    def test_unknown_field(self):
        d = data()
        d["exec"] = "rm -rf /"
        self.assertIn("unknown_key", codes(schema.validate_profile_data(d)))

    def test_secrets_are_rejected(self):
        d = data()
        d["adapter"]["password"] = "x"
        d["restore"]["steps"][0]["params"] = {"api_key": "x"}
        result = schema.validate_profile_data(d)
        self.assertEqual(sum(1 for i in result.errors if i.code == "secret_key"), 2)

    def test_bad_id(self):
        d = data()
        d["id"] = "Bad Id!"
        self.assertIn("format", codes(schema.validate_profile_data(d)))


class TestActionsAndOrder(unittest.TestCase):
    def test_unknown_action(self):
        d = data()
        d["restore"]["steps"].insert(0, {"action": "run_shell"})
        result = schema.validate_profile_data(d)
        self.assertIn("unknown_action", codes(result))
        self.assertIn("restore.steps[0].action", {i.path for i in result.errors})

    def test_unknown_param_and_bad_param_range(self):
        d = data()
        d["restore"]["steps"][6]["params"] = {"attempts": 99, "cmd": "x"}
        result = schema.validate_profile_data(d)
        self.assertIn("unknown_key", codes(result))
        self.assertIn("range", codes(result))

    def test_apply_is_required(self):
        d = data()
        d["restore"]["steps"] = [
            s for s in d["restore"]["steps"] if s["action"] != "apply_saved_config"
        ]
        self.assertIn("missing_apply", codes(schema.validate_profile_data(d)))

    def test_verify_after_apply_is_required(self):
        d = data()
        d["restore"]["steps"] = d["restore"]["steps"][:6]
        self.assertIn("missing_verify", codes(schema.validate_profile_data(d)))

    def test_apply_before_backup_is_rejected(self):
        d = data()
        steps = d["restore"]["steps"]
        steps[3], steps[5] = steps[5], steps[3]  # backup <-> apply
        result = schema.validate_profile_data(d)
        self.assertIn("order", codes(result))

    def test_backup_needs_fetch_first(self):
        d = data()
        d["restore"]["steps"] = [
            s for s in d["restore"]["steps"] if s["action"] != "fetch_current_config"
        ]
        self.assertIn("missing_step", codes(schema.validate_profile_data(d)))

    def test_duplicate_action(self):
        d = data()
        d["restore"]["steps"].append({"action": "verify_running_config"})
        self.assertIn("duplicate_action", codes(schema.validate_profile_data(d)))

    def test_critical_step_cannot_be_optional(self):
        d = data()
        d["restore"]["steps"][5]["required"] = False  # apply
        self.assertIn("not_skippable", codes(schema.validate_profile_data(d)))

    def test_skippable_step_gives_a_visible_warning(self):
        d = data()
        d["restore"]["steps"][1]["required"] = False  # check_rollback_available
        result = schema.validate_profile_data(d)
        # required by the declared rollback strategy, so still an error ...
        self.assertIn("step_optional", codes(result))
        d["failure"]["rollback_strategy"] = "none"
        result = schema.validate_profile_data(d)
        self.assertTrue(result.ok)
        self.assertIn("skippable_step", {i.code for i in result.warnings})


class TestSafetyFlags(unittest.TestCase):
    def test_huawei_requires_mandatory_persist(self):
        for adapter in ("huawei_ce", "huawei_s"):
            for step in (None, {"action": "persist_config", "required": False}):
                with self.subTest(adapter=adapter, step=step):
                    profile = data()
                    profile["adapter"]["type"] = adapter
                    if step:
                        profile["restore"]["steps"].append(step)
                    expected = "not_skippable" if step else "missing_persist"
                    self.assertIn(
                        expected, codes(schema.validate_profile_data(profile))
                    )

    def test_huawei_requires_running_config_verification(self):
        for adapter in ("huawei_ce", "huawei_s"):
            with self.subTest(adapter=adapter):
                profile = data()
                profile["adapter"]["type"] = adapter
                profile["restore"]["steps"][-1] = {"action": "persist_config"}
                self.assertIn(
                    "missing_verify_running",
                    codes(schema.validate_profile_data(profile)),
                )

    def test_confirmation_and_precheck_cannot_be_disabled(self):
        for key in ("require_confirmation", "require_precheck"):
            d = data()
            d["restore"][key] = False
            result = schema.validate_profile_data(d)
            self.assertIn("unsafe_setting", codes(result), key)

    def test_connection_loss_must_be_unknown(self):
        d = data()
        d["failure"]["mark_unknown_if_connection_lost"] = False
        self.assertIn("unsafe_setting", codes(schema.validate_profile_data(d)))

    def test_flag_requires_the_matching_step(self):
        d = data()
        d["restore"]["steps"] = [
            s for s in d["restore"]["steps"] if s["action"] != "validate_target_config"
        ]
        self.assertIn("missing_step", codes(schema.validate_profile_data(d)))
        d["restore"]["require_target_validation"] = False  # explicit choice
        result = schema.validate_profile_data(d)
        self.assertTrue(result.ok)
        self.assertIn("disabled_safety", {i.code for i in result.warnings})

    def test_no_rollback_is_a_warning(self):
        d = data()
        d["failure"]["rollback_strategy"] = "none"
        d["restore"]["steps"] = [
            s
            for s in d["restore"]["steps"]
            if s["action"] != "check_rollback_available"
        ]
        result = schema.validate_profile_data(d)
        self.assertTrue(result.ok)
        self.assertIn("no_rollback", {i.code for i in result.warnings})

    def test_unknown_strategy_and_adapter(self):
        d = data()
        d["restore"]["strategy"] = "generate_reverse_commands"
        d["adapter"]["type"] = "telnet_raw"
        result = schema.validate_profile_data(d)
        self.assertIn("unknown_strategy", codes(result))
        self.assertIn("unknown_adapter", codes(result))

    def test_limits_are_range_checked(self):
        d = data()
        d["limits"]["operation_timeout"] = 10**6
        d["limits"]["connect_timeout"] = "ten"
        result = schema.validate_profile_data(d)
        self.assertIn("range", codes(result))
        self.assertIn("type", codes(result))

    def test_builtin_flag_only_from_shipped_files(self):
        d = data()
        d["builtin"] = True
        self.assertIn("builtin_forbidden", codes(schema.validate_profile_data(d)))
        result = schema.validate_profile_data(d, allow_builtin=True)
        self.assertTrue(result.ok)
        self.assertTrue(result.profile.builtin)


class TestCapabilities(unittest.TestCase):
    def setUp(self):
        self.profile = schema.parse_profile_yaml(VALID).profile

    def test_all_actions_implemented(self):
        full = {s.action for s in self.profile.steps}
        self.assertEqual(
            schema.check_adapter_capabilities(self.profile, {"mock": full}), []
        )

    def test_missing_action_blocks_the_profile(self):
        partial = {s.action for s in self.profile.steps} - {"apply_saved_config"}
        issues = schema.check_adapter_capabilities(self.profile, {"mock": partial})
        self.assertEqual([i.code for i in issues], ["action_not_supported"])

    def test_adapter_not_registered(self):
        issues = schema.check_adapter_capabilities(self.profile, {})
        self.assertEqual(issues[0].code, "adapter_not_implemented")


class TestExport(unittest.TestCase):
    def test_round_trip(self):
        profile = schema.parse_profile_yaml(VALID).profile
        exported = schema.dump_profile_yaml(profile)
        again = schema.parse_profile_yaml(exported)
        self.assertTrue(again.ok, [str(i) for i in again.issues])
        self.assertEqual(again.profile, profile)

    def test_export_has_no_secret_like_keys(self):
        exported = schema.dump_profile_yaml(schema.parse_profile_yaml(VALID).profile)
        self.assertIsNone(schema.SECRET_KEY_RE.search(exported))


class TestCompatibility(unittest.TestCase):
    def profile(self, **compat_section):
        d = data()
        if compat_section:
            d["compatibility"] = compat_section
        return schema.validate_profile_data(d).profile

    def test_platform_match(self):
        p = self.profile()
        self.assertTrue(compat.check_compatibility(p, "mock_os").allowed)
        self.assertEqual(
            compat.check_compatibility(p, "ios").status, compat.INCOMPATIBLE
        )
        self.assertEqual(
            compat.check_compatibility(p, None).status, compat.INCOMPATIBLE
        )

    def test_unknown_model_is_not_a_match_when_restricted(self):
        p = self.profile(models=["CE68*"])
        self.assertEqual(
            compat.check_compatibility(p, "mock_os").status, compat.UNVERIFIABLE
        )
        self.assertFalse(compat.check_compatibility(p, "mock_os").allowed)
        self.assertTrue(
            compat.check_compatibility(p, "mock_os", model="ce6857").allowed
        )
        self.assertEqual(
            compat.check_compatibility(p, "mock_os", model="S5700").status,
            compat.INCOMPATIBLE,
        )

    def test_os_version_restriction(self):
        p = self.profile(os_versions=["16.*"])
        self.assertFalse(compat.check_compatibility(p, "mock_os").allowed)
        self.assertTrue(
            compat.check_compatibility(p, "mock_os", os_version="16.9.4").allowed
        )
        self.assertEqual(
            compat.check_compatibility(p, "mock_os", os_version="15.2").status,
            compat.INCOMPATIBLE,
        )


if __name__ == "__main__":
    unittest.main()
