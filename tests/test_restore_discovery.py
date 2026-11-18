"""Mixed-fleet scenario selection must not imply hardware verification."""

import unittest
from dataclasses import replace
from unittest.mock import Mock

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.restore.adapters import adapter_capabilities
from app.modules.restore.adapters.base import DeviceInfo
from app.modules.restore.engine import ENGINE_IMPLEMENTED_ACTIONS
from app.modules.restore.families import identify_family
from app.modules.restore.profile_service import ProfileService
from app.modules.restore.profiles import BuiltinProfileProvider
from app.modules.restore.service import ServiceError
from restore_test_support import InMemoryProfileRepo

ADMIN = {"user": "admin", "rights": "admin"}


class TestInventoryFamilies(unittest.TestCase):
    def test_mixed_inventory(self):
        cases = {
            "1921/k9": "cisco_ios",
            "2911r-v/k9": "cisco_ios",
            "Asr1001-x": "cisco_ios",
            "Ws-c2960x-48fps-l": "cisco_ios",
            "N5k-c5548up": "cisco_nxos",
            "Ce6863e-48s6cq": "huawei_ce",
            "Ce8851-32cq8dq-p": "huawei_ce",
            "Cloudengine s5735-l-v2": "huawei_campus",
            "S1720-10gw-pwr-2p-e": "huawei_campus",
            "S5732-h48um2cc": "huawei_campus",
            "Ar6140-16g4xg": "huawei_ar",
            "Ac6508": "huawei_ac",
            "Mes5332a": "eltex_mes",
            "Esr-15r": "eltex_esr",
            "Dgs-1520-28": "dlink",
            "Chr vmware, inc. vmware virtual platform": "mikrotik",
            "Hp vc flexfabric 10gb/24-port module": "hpe",
            "Smart-ups 1500 rm 667.18.i": "apc",
            "Generic x86 [64bit]": "unknown",
        }
        for model, expected in cases.items():
            with self.subTest(model=model):
                self.assertEqual(identify_family(model, None).key, expected)

    def test_generic_huawei_driver_does_not_guess_ce_or_campus(self):
        self.assertEqual(identify_family("Generic", "huawei_vrp_ssh").key, "unknown")
        self.assertEqual(identify_family(None, "cisco_nxos_ssh").key, "cisco_nxos")


class TestScenarioAssessment(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryProfileRepo()
        self.device = DeviceInfo(
            1, "192.0.2.1", "test", "huawei_vrp_ssh", model="CE6881-48S6CQ"
        )
        self.devices = Mock()
        self.devices.get_device.side_effect = lambda _: self.device
        self.service = ProfileService(
            BuiltinProfileProvider(),
            self.repo,
            self.devices,
            access=lambda session, device: True,
            capabilities=lambda: adapter_capabilities(
                include_unverified=True, engine_actions=ENGINE_IMPLEMENTED_ACTIONS
            ),
        )

    def assess(self):
        return self.service.assess_for_device(ADMIN, 1)

    def test_ce_has_one_recommended_scenario(self):
        result = self.assess()
        self.assertEqual([r["key"] for r in result["choices"]], ["huawei_ce"])
        self.assertEqual(result["recommended"]["key"], "huawei_ce")
        self.assertTrue(result["inventory_only"])
        self.assertFalse(result["requires_choice"])

    def test_campus_scenario_is_explicitly_disruptive(self):
        self.device = replace(self.device, model="Cloudengine S5735-L-V2")
        result = self.assess()
        self.assertEqual(result["recommended"]["key"], "huawei_s")
        self.assertTrue(result["recommended"]["disruptive"])

    def test_ar_and_ac_are_not_given_switch_restore_methods(self):
        for model in ("AR161", "AC6508"):
            self.device = replace(self.device, model=model)
            self.assertEqual(self.assess()["choices"], [])

    def test_unknown_huawei_family_requires_explicit_choice(self):
        self.device = replace(self.device, model="Generic")
        result = self.assess()
        self.assertEqual(len(result["choices"]), 2)
        self.assertIsNone(result["recommended"])
        self.assertTrue(result["requires_choice"])

    def test_disabled_adapters_have_a_reason_and_no_recommendation(self):
        self.service._capabilities = lambda: {}
        result = self.assess()
        self.assertEqual(result["choices"], [])
        self.assertIsNone(result["recommended"])
        ce = next(r for r in result["blocked"] if r["key"] == "huawei_ce")
        self.assertTrue(any("switched off" in text for text in ce["reasons"]))

    def test_wrong_assignment_is_not_silently_replaced(self):
        self.repo.set_assignment(1, "builtin", "huawei_s", "admin")
        result = self.assess()
        self.assertIsNone(result["recommended"])
        self.assertTrue(result["requires_choice"])
        self.assertTrue(any(r["assigned"] for r in result["blocked"]))

    def test_removed_assignment_is_explained(self):
        self.repo.set_assignment(1, "user", "removed", "admin")
        result = self.assess()
        self.assertIsNone(result["recommended"])
        self.assertIn("no longer exists", result["blocked"][-1]["reasons"][0])

    def test_access_is_checked_before_reading_inventory(self):
        self.service._access = lambda session, device: False
        with self.assertRaises(ServiceError):
            self.assess()
        self.devices.get_device.assert_not_called()

    def test_family_restrictions_also_apply_to_assignment(self):
        preview = self.service.preview_assignment(ADMIN, [1], "builtin", "huawei_s")
        self.assertFalse(preview["can_assign"])
        self.assertEqual(preview["devices"][0]["status"], "incompatible")
        result = self.service.assign(ADMIN, [1], "builtin", "huawei_s")
        self.assertEqual(result["assigned"], [])
        self.assertIsNone(self.repo.get_assignment(1))


if __name__ == "__main__":
    unittest.main()
