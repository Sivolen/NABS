"""Dashboard regression checks with real SQL and overlapping device groups."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    AssociatingDevice,
    Configs,
    Devices,
    DeviceValidation,
    GroupPermission,
)
from app.modules.dbutils.db_dashboards import get_dashboard_summary


class TestDBDashboards(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        for model in (
            Devices,
            Configs,
            GroupPermission,
            AssociatingDevice,
            DeviceValidation,
        ):
            model.__table__.create(engine)
        session = Session(engine)
        self.addCleanup(session.close)
        patcher = patch(
            "app.modules.dbutils.db_dashboards.db", SimpleNamespace(session=session)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        session.add_all(
            [
                Devices(
                    id=1,
                    device_hostname="edge",
                    device_vendor="Cisco",
                    connection_status="Timeout",
                    timestamp="2026-03-04 12:00",
                    is_enabled=True,
                ),
                Devices(
                    id=2,
                    device_hostname="lab",
                    device_vendor="Cisco",
                    connection_status="Timeout",
                    is_enabled=False,
                ),
                Devices(
                    id=3,
                    device_hostname="other-group",
                    device_vendor="Huawei",
                    connection_status="Timeout",
                    is_enabled=True,
                ),
                Devices(id=4, device_hostname="new-switch", is_enabled=True),
                Devices(
                    id=5,
                    device_hostname="core",
                    connection_status="Ok",
                    is_enabled=True,
                ),
                Devices(
                    id=6,
                    device_hostname="no-copy",
                    connection_status="Auth failed",
                    is_enabled=True,
                ),
                GroupPermission(user_id=7, user_group_id=10),
                GroupPermission(user_id=7, user_group_id=20),
                GroupPermission(user_id=8, user_group_id=30),
                AssociatingDevice(device_id=1, user_group_id=10),
                AssociatingDevice(device_id=1, user_group_id=20),
                AssociatingDevice(device_id=2, user_group_id=10),
                AssociatingDevice(device_id=3, user_group_id=30),
                AssociatingDevice(device_id=4, user_group_id=20),
                AssociatingDevice(device_id=5, user_group_id=20),
                AssociatingDevice(device_id=6, user_group_id=20),
                Configs(
                    id=1,
                    device_id=1,
                    device_ip="192.0.2.1",
                    device_config="first",
                    timestamp="2026-01-01 12:01",
                ),
                Configs(
                    id=2,
                    device_id=1,
                    device_ip="192.0.2.1",
                    device_config="latest",
                    timestamp="2026-03-01 12:02",
                ),
                Configs(
                    id=3,
                    device_id=3,
                    device_ip="192.0.2.3",
                    device_config="invisible",
                    timestamp="2026-03-01 12:01",
                ),
                Configs(
                    id=4,
                    device_id=5,
                    device_ip="192.0.2.5",
                    device_config="old",
                    timestamp="2025-12-31 12:01",
                ),
                DeviceValidation(device_id=1, status="failed"),
                DeviceValidation(device_id=1, status="passed"),
                DeviceValidation(device_id=3, status="failed"),
                DeviceValidation(device_id=4, status="pending"),
            ]
        )
        session.commit()

    def summary(self, **session_overrides):
        identity = {"user": "operator", "user_id": 7, "rights": "user"}
        return get_dashboard_summary({**identity, **session_overrides}, year=2026)

    def test_coverage_issues_and_last_check_use_visible_enabled_devices(self):
        summary = self.summary()
        self.assertEqual(
            {
                key: summary[key]
                for key in (
                    "total",
                    "enabled",
                    "covered",
                    "missing",
                    "errors",
                    "disabled",
                )
            },
            {
                "total": 5,
                "enabled": 4,
                "covered": 2,
                "missing": 2,
                "errors": 2,
                "disabled": 1,
            },
        )
        issues = {row["id"]: row for row in summary["issues"]}
        self.assertEqual(set(issues), {1, 4, 6})
        self.assertEqual(issues[1]["checked_at"], "2026-03-04 12:00")
        self.assertEqual(issues[1]["saved_at"], "2026-03-01 12:02")
        self.assertIsNone(issues[4]["checked_at"])
        self.assertIsNone(issues[4]["error"])
        self.assertFalse(issues[6]["has_backup"])
        self.assertEqual(issues[6]["error"], "Auth failed")

    def test_months_include_empty_gaps_and_exclude_other_groups_and_years(self):
        summary = self.summary()
        self.assertEqual(
            [row["count"] for row in summary["months"]], [1, 0, 1] + [0] * 9
        )
        self.assertEqual(summary["snapshot_total"], 2)

    def test_validation_is_latest_per_visible_device(self):
        summary = self.summary()
        self.assertEqual(summary["validation"], {"passed": 1, "pending": 1})
        self.assertEqual(summary["not_validated"], 3)
        superadmin = self.summary(rights="sadmin")
        self.assertEqual(superadmin["total"], 6)
        self.assertEqual(superadmin["validation"]["failed"], 1)

    def test_unknown_membership_fails_closed(self):
        summary = self.summary(user_id=None)
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["issues"], [])
