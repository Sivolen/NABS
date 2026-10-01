import logging
import os
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.modules.dbutils import db_cleanup
from app.modules.dbutils.db_cleanup import (
    DEFAULT_CONFIG_RETENTION_DAYS,
    cleanup_old_configs,
    get_retention_days,
    parse_config_timestamp,
    select_configs_to_delete,
)

os.environ["FLASK_ENV"] = "testing"

# "Today" for all tests, 365 days retention -> cutoff 2025-09-29 00:00
NOW = datetime(2026, 9, 29, 3, 0)
CUTOFF = datetime(2025, 9, 29, 0, 0)


def row(config_id, device_id, timestamp, device_ip="10.0.0.1"):
    """(config_id, device_id, device_ip, timestamp) like the DB query returns"""
    return config_id, device_id, device_ip, timestamp


class TestParseConfigTimestamp(unittest.TestCase):
    def test_valid_timestamp(self):
        self.assertEqual(
            parse_config_timestamp("2026-09-29 14:32"), datetime(2026, 9, 29, 14, 32)
        )

    def test_valid_timestamp_with_seconds(self):
        self.assertEqual(
            parse_config_timestamp("2026-09-29 14:32:10"),
            datetime(2026, 9, 29, 14, 32, 10),
        )

    def test_invalid_timestamps(self):
        for value in ("unknown", "", "2026-13-45 99:99", "29.09.2026", None, 123):
            with self.subTest(value=value):
                self.assertIsNone(parse_config_timestamp(value))


class TestSelectConfigsToDelete(unittest.TestCase):
    def setUp(self):
        self.log = logging.getLogger("test.config_cleanup")

    def test_deletes_only_old_configs(self):
        rows = [
            row(1, 1, "2024-12-01 10:00"),
            row(2, 1, "2025-05-01 10:00"),
            row(3, 1, "2026-07-01 10:00"),
            row(4, 1, "2026-09-29 14:32"),
        ]
        ids, stats = select_configs_to_delete(rows, CUTOFF, self.log)
        self.assertEqual(sorted(ids), [1, 2])
        self.assertEqual(stats["found"], 2)
        self.assertEqual(stats["preserved"], 0)

    def test_latest_config_of_device_is_preserved_when_all_are_old(self):
        rows = [
            row(1, 1, "2023-01-01 10:00"),
            row(2, 1, "2024-01-01 10:00"),
            row(3, 1, "2024-06-01 10:00"),  # latest, but older than cutoff
        ]
        ids, stats = select_configs_to_delete(rows, CUTOFF, self.log)
        self.assertEqual(sorted(ids), [1, 2])
        self.assertNotIn(3, ids)
        self.assertEqual(stats["found"], 3)
        self.assertEqual(stats["preserved"], 1)

    def test_latest_is_defined_by_timestamp_not_by_id(self):
        # id 10 is inserted later, but its timestamp is older (manual upload)
        rows = [
            row(1, 1, "2024-06-01 10:00"),
            row(10, 1, "2024-01-01 10:00"),
        ]
        ids, stats = select_configs_to_delete(rows, CUTOFF, self.log)
        self.assertEqual(ids, [10])
        self.assertEqual(stats["preserved"], 1)

    def test_every_device_keeps_at_least_one_config(self):
        rows = [
            row(1, 1, "2020-01-01 00:00"),
            row(2, 1, "2020-02-01 00:00"),
            row(3, 2, "2021-01-01 00:00"),
            row(4, 2, "2021-02-01 00:00"),
            row(5, 3, "2026-09-01 00:00"),
            row(6, 3, "2020-01-01 00:00"),
        ]
        ids, stats = select_configs_to_delete(rows, CUTOFF, self.log)
        self.assertEqual(sorted(ids), [1, 3, 6])
        remaining_devices = {r[1] for r in rows if r[0] not in ids}
        self.assertEqual(remaining_devices, {1, 2, 3})

    def test_preserved_counts_devices_that_needed_protection(self):
        rows = [
            # device 1: has a fresh config, nothing to protect
            row(1, 1, "2020-01-01 00:00"),
            row(2, 1, "2026-09-01 00:00"),
            # devices 2 and 3: everything is old, latest must be protected
            row(3, 2, "2020-01-01 00:00"),
            row(4, 2, "2020-06-01 00:00"),
            row(5, 3, "2019-01-01 00:00"),
        ]
        ids, stats = select_configs_to_delete(rows, CUTOFF, self.log)
        self.assertEqual(sorted(ids), [1, 3])
        self.assertEqual(stats["found"], 4)
        self.assertEqual(stats["preserved"], 2)

    def test_config_exactly_on_cutoff_is_kept(self):
        rows = [
            row(1, 1, "2025-09-28 23:59"),
            row(2, 1, "2025-09-29 00:00"),
            row(3, 1, "2026-01-01 00:00"),
        ]
        ids, _ = select_configs_to_delete(rows, CUTOFF, self.log)
        self.assertEqual(ids, [1])

    def test_invalid_timestamps_are_skipped_and_logged(self):
        rows = [
            row(1, 1, "unknown"),
            row(2, 1, "2020-01-01 00:00"),
            row(3, 1, "2026-09-01 00:00"),
            row(1234, 1, None),
        ]
        with self.assertLogs(self.log, level="WARNING") as captured:
            ids, stats = select_configs_to_delete(rows, CUTOFF, self.log)
        self.assertEqual(ids, [2])
        self.assertEqual(stats["invalid"], 2)
        messages = "\n".join(captured.output)
        self.assertIn('Invalid config timestamp for config ID 1: "unknown"', messages)
        self.assertIn("config ID 1234", messages)

    def test_invalid_timestamp_never_deleted_even_if_it_is_the_only_config(self):
        rows = [row(1, 1, "garbage")]
        with self.assertLogs(self.log, level="WARNING"):
            ids, stats = select_configs_to_delete(rows, CUTOFF, self.log)
        self.assertEqual(ids, [])
        self.assertEqual(stats["found"], 0)

    def test_configs_without_device_id_are_grouped_by_ip(self):
        rows = [
            row(1, None, "2020-01-01 00:00", device_ip="10.0.0.1"),
            row(2, None, "2020-02-01 00:00", device_ip="10.0.0.1"),
            row(3, None, "2020-01-01 00:00", device_ip="10.0.0.2"),
        ]
        ids, stats = select_configs_to_delete(rows, CUTOFF, self.log)
        self.assertEqual(ids, [1])
        self.assertEqual(stats["preserved"], 2)

    def test_empty_input(self):
        ids, stats = select_configs_to_delete([], CUTOFF, self.log)
        self.assertEqual(ids, [])
        self.assertEqual(stats, {"found": 0, "preserved": 0, "invalid": 0})


class TestGetRetentionDays(unittest.TestCase):
    @staticmethod
    def _config_module(**attrs):
        module = types.ModuleType("config")
        for name, value in attrs.items():
            setattr(module, name, value)
        return {"config": module}

    def test_value_from_config(self):
        with patch.dict(sys.modules, self._config_module(CONFIG_RETENTION_DAYS=180)):
            self.assertEqual(get_retention_days(), 180)

    def test_missing_option_uses_default(self):
        with patch.dict(sys.modules, self._config_module()):
            self.assertEqual(get_retention_days(), DEFAULT_CONFIG_RETENTION_DAYS)

    def test_invalid_option_uses_default(self):
        for bad_value in ("abc", None, 0, -5):
            with self.subTest(value=bad_value):
                module = self._config_module(CONFIG_RETENTION_DAYS=bad_value)
                with patch.dict(sys.modules, module):
                    with self.assertLogs(db_cleanup.cleanup_logger, level="WARNING"):
                        self.assertEqual(
                            get_retention_days(), DEFAULT_CONFIG_RETENTION_DAYS
                        )


class TestCleanupOldConfigs(unittest.TestCase):
    @patch("app.modules.dbutils.db_cleanup.Configs")
    @patch("app.modules.dbutils.db_cleanup.db")
    def test_cleanup_deletes_old_and_commits(self, mock_db, mock_configs):
        mock_db.session.query.return_value.all.return_value = [
            row(1, 1, "2020-01-01 00:00"),
            row(2, 1, "2020-02-01 00:00"),
            row(3, 1, "2026-09-01 00:00"),
        ]
        delete = mock_configs.query.filter.return_value.delete
        delete.return_value = 2

        result = cleanup_old_configs(retention_days=365, now=NOW)

        self.assertEqual(result["found"], 2)
        self.assertEqual(result["deleted"], 2)
        self.assertEqual(result["preserved"], 0)
        # one bulk DELETE, not one per config
        delete.assert_called_once_with(synchronize_session=False)
        mock_configs.id.in_.assert_called_once_with([1, 2])
        mock_db.session.commit.assert_called_once()
        mock_db.session.rollback.assert_not_called()
        mock_db.session.delete.assert_not_called()

    @patch("app.modules.dbutils.db_cleanup.DELETE_CHUNK_SIZE", 2)
    @patch("app.modules.dbutils.db_cleanup.Configs")
    @patch("app.modules.dbutils.db_cleanup.db")
    def test_cleanup_deletes_in_chunks(self, mock_db, mock_configs):
        mock_db.session.query.return_value.all.return_value = [
            row(i, 1, "2020-01-01 00:00") for i in range(1, 6)
        ] + [row(6, 1, "2026-09-01 00:00")]
        delete = mock_configs.query.filter.return_value.delete
        delete.return_value = 2

        cleanup_old_configs(retention_days=365, now=NOW)

        self.assertEqual(delete.call_count, 3)  # 5 ids -> chunks of 2, 2, 1
        mock_db.session.commit.assert_called_once()

    @patch("app.modules.dbutils.db_cleanup.Configs")
    @patch("app.modules.dbutils.db_cleanup.db")
    def test_cleanup_nothing_to_delete(self, mock_db, mock_configs):
        mock_db.session.query.return_value.all.return_value = [
            row(1, 1, "2026-09-01 00:00"),
        ]
        result = cleanup_old_configs(retention_days=365, now=NOW)
        self.assertEqual(result["deleted"], 0)
        mock_configs.query.filter.assert_not_called()

    @patch("app.modules.dbutils.db_cleanup.Configs")
    @patch("app.modules.dbutils.db_cleanup.db")
    def test_cleanup_error_rolls_back_and_does_not_raise(self, mock_db, mock_configs):
        mock_db.session.query.return_value.all.return_value = [
            row(1, 1, "2020-01-01 00:00"),
            row(2, 1, "2026-09-01 00:00"),
        ]
        mock_configs.query.filter.return_value.delete.side_effect = RuntimeError(
            "db is down"
        )

        with self.assertLogs(db_cleanup.cleanup_logger, level="ERROR") as captured:
            result = cleanup_old_configs(retention_days=365, now=NOW)

        self.assertIsNone(result)
        mock_db.session.rollback.assert_called_once()
        mock_db.session.commit.assert_not_called()
        self.assertIn("Config cleanup failed: db is down", captured.output[0])

    @patch("app.modules.dbutils.db_cleanup.Configs")
    @patch("app.modules.dbutils.db_cleanup.db")
    def test_dry_run_deletes_nothing(self, mock_db, mock_configs):
        mock_db.session.query.return_value.all.return_value = [
            row(1, 1, "2020-01-01 00:00"),
            row(2, 1, "2020-02-01 00:00"),
            row(3, 1, "2026-09-01 00:00"),
        ]
        with self.assertLogs(db_cleanup.cleanup_logger, level="INFO") as captured:
            result = cleanup_old_configs(retention_days=365, now=NOW, dry_run=True)

        self.assertEqual(result["found"], 2)
        self.assertEqual(result["deleted"], 0)
        mock_configs.query.filter.assert_not_called()
        mock_db.session.commit.assert_not_called()
        self.assertIn("Dry run: 2 configs would be deleted", "\n".join(captured.output))

    @patch("app.modules.dbutils.db_cleanup.get_retention_days", return_value=180)
    @patch("app.modules.dbutils.db_cleanup.Configs")
    @patch("app.modules.dbutils.db_cleanup.db")
    def test_cleanup_uses_retention_from_config(self, mock_db, mock_configs, _days):
        # 180 days before 2026-09-29 is 2026-04-02
        mock_db.session.query.return_value.all.return_value = [
            row(1, 1, "2026-04-01 12:00"),  # older than cutoff -> deleted
            row(2, 1, "2026-04-03 12:00"),  # newer than cutoff -> kept
            row(3, 1, "2026-09-01 12:00"),
        ]
        mock_configs.query.filter.return_value.delete.return_value = 1

        result = cleanup_old_configs(now=NOW)

        self.assertEqual(result["found"], 1)
        mock_configs.id.in_.assert_called_once_with([1])

    @patch("app.modules.dbutils.db_cleanup.Configs", new_callable=MagicMock)
    @patch("app.modules.dbutils.db_cleanup.db")
    def test_cleanup_logs_summary(self, mock_db, mock_configs):
        mock_db.session.query.return_value.all.return_value = [
            row(1, 1, "2020-01-01 00:00"),
            row(2, 1, "2020-06-01 00:00"),
        ]
        mock_configs.query.filter.return_value.delete.return_value = 1

        with self.assertLogs(db_cleanup.cleanup_logger, level="INFO") as captured:
            cleanup_old_configs(retention_days=365, now=NOW)

        output = "\n".join(captured.output)
        for expected in (
            "Starting old configs cleanup",
            "Retention period: 365 days",
            "Cutoff: 2025-09-29 00:00",
            "Found 2 old configs",
            "Deleted configs: 1",
            "Preserved 1 latest configs",
            "Cleanup completed",
        ):
            self.assertIn(expected, output)


if __name__ == "__main__":
    unittest.main()
