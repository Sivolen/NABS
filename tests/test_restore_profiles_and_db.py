"""Restore Engine, stage 4: built-in profile loader, DB mapping, retention protection."""

import logging
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.dbutils import db_cleanup, db_restore_guard  # noqa: E402
from app.modules.dbutils.db_cleanup import select_configs_to_delete  # noqa: E402
from app.modules.restore import dbmap  # noqa: E402
from app.modules.restore.profiles import (  # noqa: E402
    BuiltinProfileProvider,
    CompositeProfileProvider,
    ProfileText,
)
from restore_test_support import profile_yaml  # noqa: E402

CUTOFF = datetime(2025, 9, 29)


def builtin_yaml(profile_id="mock_platform", builtin=True):
    return profile_yaml(lambda d: d.update(id=profile_id, builtin=builtin))


class TestBuiltinLoader(unittest.TestCase):
    def provider(self, files):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, text in files.items():
            Path(directory.name, name).write_text(text, encoding="utf-8")
        with self.assertLogs("nabs.restore", level="ERROR") if any(
            n.startswith("bad") for n in files
        ) else _nullcontext():
            return BuiltinProfileProvider(Path(directory.name))

    def test_valid_file_is_served_as_builtin_only(self):
        provider = self.provider({"mock_platform.yaml": builtin_yaml()})
        text = provider.get("builtin", "mock_platform")
        self.assertEqual((text.source, text.version), ("builtin", 1))
        self.assertIsNone(provider.get("user", "mock_platform"))
        self.assertIsNone(provider.get("builtin", "other"))
        self.assertEqual(provider.errors, [])

    def test_bad_files_are_skipped_and_reported(self):
        provider = self.provider(
            {
                "bad_yaml.yaml": "a: [",
                "bad_flag.yaml": builtin_yaml("bad_flag", builtin=False),
                "bad_name.yaml": builtin_yaml("other_id"),
            }
        )
        self.assertEqual(provider.keys(), [])
        self.assertEqual(len(provider.errors), 3)

    def test_missing_directory_is_just_empty(self):
        self.assertEqual(BuiltinProfileProvider(Path("/nonexistent/x")).keys(), [])

    def test_the_shipped_directory_only_contains_valid_profiles(self):
        provider = BuiltinProfileProvider()
        self.assertEqual(provider.errors, [])

    def test_composite_routes_by_source(self):
        builtin = BuiltinProfileProvider(Path("/nonexistent"))
        user = MagicMock()
        user.get.return_value = ProfileText("user", "k", 2, "x")
        composite = CompositeProfileProvider(builtin, user)
        self.assertEqual(composite.get("user", "k").version, 2)
        self.assertIsNone(composite.get("builtin", "k"))
        self.assertIsNone(composite.get("weird", "k"))

    def test_sha256_is_of_the_exact_text(self):
        self.assertEqual(
            ProfileText("user", "k", 1, "abc").sha256,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestDbMapping(unittest.TestCase):
    def test_json_fields_are_encoded_and_lengths_limited(self):
        values = dbmap.fields_to_columns(
            {
                "diagnostics": {"a": 1},
                "summary": "x" * 900,
                "status": "running",
                "heartbeat_at": None,
            }
        )
        self.assertEqual(values["diagnostics"], '{"a": 1}')
        self.assertEqual(len(values["summary"]), 500)
        self.assertEqual(values["status"], "running")

    def test_unknown_field_is_refused(self):
        with self.assertRaises(KeyError):
            dbmap.fields_to_columns({"drop_table": 1})

    def test_row_to_record_decodes_json_and_defaults(self):
        row = SimpleNamespace(
            id=3,
            device_id=1,
            target_config_id=2,
            profile_source="user",
            profile_key="k",
            profile_version=1,
            profile_sha256="s",
            profile_content="c",
            initiator="u",
            status=None,
            diagnostics='{"device_touched": true}',
            precheck_result="not json",
        )
        record = dbmap.row_to_record(row)
        self.assertEqual(record.status, "created")
        self.assertEqual(record.diagnostics, {"device_touched": True})
        self.assertIsNone(record.precheck_result)
        self.assertIsNone(record.worker_id)

    def test_round_trip(self):
        fields = {"precheck_result": {"status": "ready", "checks": []}}
        stored = dbmap.fields_to_columns(fields)["precheck_result"]
        self.assertEqual(dbmap.loads_json(stored, None), fields["precheck_result"])

    def test_every_record_field_has_a_model_column(self):
        # the model is a MagicMock in stub mode, so compare against the source text
        source = (
            Path(__file__).resolve().parent.parent / "app" / "models.py"
        ).read_text()
        restore_part = source[
            source.index("class RestoreJob(db.Model)") : source.index(
                "class RestoreJobEvent"
            )
        ]
        for name in dbmap.JOB_FIELDS:
            self.assertIn(f"    {name} = db.Column", restore_part, name)


class TestPlatformResolution(unittest.TestCase):
    CUSTOM = {
        6: {"drivers_platform": "cisco_ios_ssh"},
        3: {"drivers_platform": "cisco_xe"},
        4: {"drivers_platform": "huawei_vrp"},
        5: {"drivers_platform": None},
    }

    def test_napalm_device_is_identified_by_its_driver_name(self):
        self.assertEqual(
            dbmap.resolve_platform("ios", False, self.CUSTOM), ("ios", None)
        )
        self.assertEqual(
            dbmap.resolve_platform("ios", None, self.CUSTOM), ("ios", None)
        )
        self.assertEqual(dbmap.resolve_platform(None, False, self.CUSTOM), (None, None))

    def test_custom_driver_device_is_identified_by_the_netmiko_type_not_by_the_id(self):
        # connection_driver holds the Custom_Drivers id when the custom switch is on
        self.assertEqual(
            dbmap.resolve_platform("3", True, self.CUSTOM), ("cisco_xe", "cisco_xe")
        )
        self.assertEqual(
            dbmap.resolve_platform(" 4 ", True, self.CUSTOM),
            ("huawei_vrp", "huawei_vrp"),
        )

    def test_the_ssh_type_is_kept_as_the_platform(self):
        self.assertEqual(
            dbmap.resolve_platform("6", True, self.CUSTOM),
            ("cisco_ios_ssh", "cisco_ios_ssh"),
        )

    def test_an_unresolvable_custom_driver_gives_no_platform(self):
        for driver in ("99", "abc", None, "", "5"):
            self.assertEqual(
                dbmap.resolve_platform(driver, True, self.CUSTOM), (None, None), driver
            )

    def test_the_device_list_shows_the_platform_not_the_driver_id(self):
        import sys
        import types

        from app.views import restore_profiles as view
        from view_test_support import logged_in, make_test_app

        fake = types.ModuleType("app.modules.restore.db_store")
        fake.device_platforms = lambda ids: {1: "ios", 2: "cisco_xe"}
        devices = [
            {
                "device_id": 1,
                "hostname": "a",
                "device_ip": "1.1.1.1",
                "connection_driver": "ios",
            },
            {
                "device_id": 2,
                "hostname": "b",
                "device_ip": "2.2.2.2",
                "connection_driver": "3",
            },
        ]
        flask_app = make_test_app([])
        with patch.dict(sys.modules, {"app.modules.restore.db_store": fake}), patch(
            "app.modules.dbutils.db_devices.get_devices_by_rights", return_value=devices
        ), flask_app.test_request_context("/"):
            from flask import session

            session["user_id"] = 1
            rows = view._devices_for_user()
        self.assertEqual([r["platform"] for r in rows], ["ios", "cisco_xe"])
        self.assertEqual(rows[1]["connection_driver"], "3")  # untouched, only added to


class TestModelTimestamps(unittest.TestCase):
    def test_restore_tables_write_naive_utc_only(self):
        source = (
            Path(__file__).resolve().parent.parent / "app" / "models.py"
        ).read_text()
        restore_part = source[source.index("def _restore_now") :]
        # the only place that reads the clock is the helper, and it drops the zone
        self.assertEqual(restore_part.count("datetime.now("), 1)
        self.assertIn("datetime.now(timezone.utc).replace(tzinfo=None)", restore_part)
        self.assertGreaterEqual(restore_part.count("_restore_now()"), 6)


class TestRetentionProtection(unittest.TestCase):
    log = logging.getLogger("test.restore_cleanup")

    @staticmethod
    def rows():
        # device 1: old configs 1,2 and latest 3 (also old); device 2: 4 (old, latest)
        return [
            (1, 1, "10.0.0.1", "2020-01-01 00:00"),
            (2, 1, "10.0.0.1", "2020-02-01 00:00"),
            (3, 1, "10.0.0.1", "2020-03-01 00:00"),
            (4, 2, "10.0.0.2", "2020-01-01 00:00"),
        ]

    def test_protected_configs_are_not_deleted(self):
        ids, stats = select_configs_to_delete(
            self.rows(), CUTOFF, self.log, protected_ids={1}
        )
        self.assertEqual(ids, [2])
        self.assertEqual(stats["restore_protected"], 1)
        self.assertEqual(stats["preserved"], 2)  # the latest of each device, as before

    def test_without_protection_the_result_is_unchanged(self):
        ids, stats = select_configs_to_delete(self.rows(), CUTOFF, self.log)
        self.assertEqual(ids, [1, 2])
        self.assertNotIn("restore_protected", stats)
        self.assertEqual(
            select_configs_to_delete([], CUTOFF, self.log)[1],
            {"found": 0, "preserved": 0, "invalid": 0},
        )

    @patch(
        "app.modules.dbutils.db_cleanup.get_restore_protected_config_ids",
        return_value={2},
    )
    @patch("app.modules.dbutils.db_cleanup.Configs")
    @patch("app.modules.dbutils.db_cleanup.db")
    def test_cleanup_skips_protected_ids(self, mock_db, mock_configs, _guard):
        mock_db.session.query.return_value.all.return_value = self.rows()
        mock_configs.query.filter.return_value.delete.return_value = 1
        result = cleanup_run()
        self.assertEqual(result["deleted"], 1)
        mock_configs.id.in_.assert_called_once_with([1])

    @patch(
        "app.modules.dbutils.db_cleanup.get_restore_protected_config_ids",
        side_effect=RuntimeError("db"),
    )
    @patch("app.modules.dbutils.db_cleanup.Configs")
    @patch("app.modules.dbutils.db_cleanup.db")
    def test_if_protection_cannot_be_determined_nothing_is_deleted(
        self, mock_db, mock_configs, _guard
    ):
        mock_db.session.query.return_value.all.return_value = self.rows()
        self.assertIsNone(cleanup_run())
        mock_configs.query.filter.return_value.delete.assert_not_called()
        mock_db.session.rollback.assert_called()


def cleanup_run():
    with patch.object(db_cleanup.cleanup_logger, "error"):
        return db_cleanup.cleanup_old_configs(
            retention_days=365, now=datetime(2026, 9, 29, 3, 0)
        )


class TestGuardQuery(unittest.TestCase):
    @patch("app.modules.dbutils.db_restore_guard.db")
    def test_collects_target_and_pre_restore_ids_and_ignores_none(self, mock_db):
        mock_db.session.query.return_value.filter.return_value.all.return_value = [
            (5, 6, "unknown", None),
            (7, None, "rollback_failed", None),
            (5, 9, "running", None),
            (20, 21, "failed", '{"device_touched": true}'),
            (30, 31, "failed", '{"device_touched": false}'),
            (40, 41, "success", None),
            (
                50,
                51,
                "resolved_manual",
                '{"manual_resolution": {"resolution": "target_confirmed", "device_identity_confirmed": true}}',
            ),
            (
                60,
                61,
                "resolved_manual",
                '{"manual_resolution": {"resolution": "leave_open", "device_identity_confirmed": true}}',
            ),
        ]
        self.assertEqual(
            db_restore_guard.get_restore_protected_config_ids(),
            {5, 6, 7, 9, 20, 21, 60, 61},
        )

    def test_only_known_clean_terminal_states_release_their_configs(self):
        released = set(db_restore_guard.RELEASED_JOB_STATUSES)
        self.assertEqual(
            released, {"success", "failed_rollback_confirmed", "cancelled"}
        )
        for kept in (
            "failed",
            "unknown",
            "rollback_failed",
            "queued",
            "running",
            "awaiting_confirmation",
        ):
            self.assertNotIn(kept, released)


class TestManualDeleteProtection(unittest.TestCase):
    @patch(
        "app.modules.dbutils.db_utils.get_restore_protected_config_ids",
        return_value={5},
    )
    @patch("app.modules.dbutils.db_utils.Configs")
    @patch("app.modules.dbutils.db_utils.db")
    def test_protected_config_cannot_be_deleted(self, mock_db, mock_configs, _guard):
        from app.modules.dbutils.db_utils import delete_config_for_device

        self.assertFalse(delete_config_for_device(5, 1))
        mock_configs.query.filter_by.return_value.delete.assert_not_called()

    @patch(
        "app.modules.dbutils.db_utils.get_restore_protected_config_ids",
        return_value={5},
    )
    @patch("app.modules.dbutils.db_utils.Configs")
    @patch("app.modules.dbutils.db_utils.db")
    def test_other_configs_are_still_deleted(self, mock_db, mock_configs, _guard):
        from app.modules.dbutils.db_utils import delete_config_for_device

        mock_configs.query.filter_by.return_value.delete.return_value = 1
        self.assertTrue(delete_config_for_device(6, 1))

    @patch(
        "app.modules.dbutils.db_utils.get_restore_protected_config_ids",
        side_effect=RuntimeError("db"),
    )
    @patch("app.modules.dbutils.db_utils.Configs")
    @patch("app.modules.dbutils.db_utils.db")
    def test_if_protection_cannot_be_determined_nothing_is_deleted(
        self, mock_db, mock_configs, _guard
    ):
        from app.modules.dbutils.db_utils import delete_config_for_device

        self.assertFalse(delete_config_for_device(6, 1))
        mock_configs.query.filter_by.return_value.delete.assert_not_called()

    @patch(
        "app.modules.dbutils.db_utils.get_restore_protected_config_ids",
        return_value={5},
    )
    @patch("app.modules.dbutils.db_utils.Configs")
    @patch("app.modules.dbutils.db_utils.db")
    def test_legacy_unscoped_delete_also_respects_restore_protection(
        self, mock_db, mock_configs, _guard
    ):
        from app.modules.dbutils.db_utils import delete_config

        self.assertFalse(delete_config("5"))
        mock_configs.query.filter_by.return_value.delete.assert_not_called()
        mock_db.session.rollback.assert_called_once()

    @patch(
        "app.modules.dbutils.db_utils.get_restore_protected_config_ids",
        return_value={5},
    )
    @patch("app.modules.dbutils.db_utils.AssociatingDevice")
    @patch("app.modules.dbutils.db_utils.Devices")
    @patch("app.modules.dbutils.db_utils.Configs")
    @patch("app.modules.dbutils.db_utils.db")
    def test_device_with_protected_restore_configs_cannot_be_deleted(
        self, mock_db, mock_configs, mock_devices, mock_associating, _guard
    ):
        from app.modules.dbutils.db_utils import delete_device

        mock_db.session.query.return_value.filter_by.return_value.all.return_value = [
            (5,),
            (6,),
        ]
        self.assertFalse(delete_device(1))
        mock_configs.query.filter_by.return_value.delete.assert_not_called()
        mock_devices.query.filter_by.return_value.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
