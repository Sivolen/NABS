"""Inspection reads facts only, waits for backup, and rejects stale identities."""

import unittest
from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock, patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.backup_lock import device_backup_lock
from app.modules.restore.adapters.base import DeviceInfo, Credentials
from app.modules.restore.inspection import (
    DbInspectionStore,
    InspectionWorker,
    device_identity,
    inspect_platform,
    now_utc,
)
from cisco_sim import SHOW_VERSION_IOS, SHOW_VERSION_NXOS
from huawei_sim import CE_VERSION

DEVICE = DeviceInfo(876541, "192.0.2.12", "test", "ios", port=22, model="WS-C2960X")
LOGIN = Credentials("test", "hidden-password")


class TestReadOnlyProbe(unittest.TestCase):
    def test_platforms_use_only_fixed_read_commands(self):
        for driver, output, command, version in (
            ("ios", SHOW_VERSION_IOS, "show version", "15.2(7)E3"),
            ("huawei_vrp_ssh", CE_VERSION, "display version", "V200R019C10SPC800"),
            ("cisco_nxos", SHOW_VERSION_NXOS, "show version", "9.3(5)"),
        ):
            with self.subTest(driver=driver):
                connection = Mock()
                connection.send_command.return_value = output
                factory = Mock(return_value=connection)
                facts = inspect_platform(replace(DEVICE, driver=driver), LOGIN, factory)
                self.assertEqual(facts["os_version"], version)
                connection.send_command.assert_called_once_with(
                    command, read_timeout=30
                )
                connection.disconnect.assert_called_once()
                connection.send_config_set.assert_not_called()
                self.assertNotIn(LOGIN.password, str(facts))

    def test_full_model_is_not_replaced_by_a_shorter_family_name(self):
        connection = Mock()
        connection.send_command.return_value = CE_VERSION
        device = replace(DEVICE, driver="huawei_vrp", model="Ce6863E-48S6CQ")
        facts = inspect_platform(device, LOGIN, Mock(return_value=connection))
        self.assertEqual(facts["model"], device.model)

    def test_unknown_platform_does_not_connect(self):
        factory = Mock()
        with self.assertRaises(ValueError):
            inspect_platform(replace(DEVICE, driver="unknown"), LOGIN, factory)
        factory.assert_not_called()

    def test_parser_failure_closes_the_connection(self):
        connection = Mock()
        connection.send_command.return_value = "unknown software"
        with self.assertRaises(ValueError):
            inspect_platform(DEVICE, LOGIN, Mock(return_value=connection))
        connection.disconnect.assert_called_once()


class TestInspectionFreshness(unittest.TestCase):
    def setUp(self):
        self.store = DbInspectionStore()
        self.row = dict(
            status="ready",
            identity=device_identity(DEVICE),
            model="WS-C2960X",
            os_version="15.2",
            completed_at=now_utc(),
        )
        self.store.get = Mock(return_value=self.row)

    def test_fresh_result_enriches_inventory(self):
        self.assertEqual(self.store.enrich(DEVICE).os_version, "15.2")

    def test_changed_connection_or_expired_result_is_not_reused(self):
        for device in (
            replace(DEVICE, ip="192.0.2.13"),
            replace(DEVICE, port=2222),
            replace(DEVICE, driver="cisco_xe"),
        ):
            self.assertIsNone(self.store.enrich(device).os_version)
        self.row["completed_at"] = now_utc() - timedelta(days=2)
        self.assertIsNone(self.store.enrich(DEVICE).os_version)

    def test_running_or_failed_results_are_not_inventory(self):
        for status in ("queued", "running", "failed"):
            self.row["status"] = status
            self.assertIsNone(self.store.enrich(DEVICE).os_version)


class TestInspectionQueue(unittest.TestCase):
    def setUp(self):
        self.task = {"device_id": DEVICE.device_id, "identity": device_identity(DEVICE)}
        self.store = Mock()
        self.store.pending.return_value = [self.task]
        self.store.claim.return_value = True
        self.devices = Mock()
        self.devices.get_device.return_value = DEVICE
        self.devices.get_credentials.return_value = LOGIN
        self.probe = Mock(
            return_value={"model": DEVICE.model, "os_version": "15.2", "family": "ios"}
        )
        self.worker = InspectionWorker(self.store, self.devices, self.probe)

    def test_busy_device_keeps_its_pending_request(self):
        with device_backup_lock(DEVICE.device_id):
            self.assertEqual(self.worker.run_once(), 0)
        self.store.claim.assert_not_called()
        self.probe.assert_not_called()
        self.assertEqual(self.worker.run_once(), 1)
        self.store.finish.assert_called_once_with(
            self.task, facts=self.probe.return_value
        )

    def test_changed_identity_never_connects(self):
        self.devices.get_device.return_value = replace(DEVICE, ip="192.0.2.99")
        self.worker.run_once()
        self.probe.assert_not_called()
        self.assertIn("changed", self.store.finish.call_args.kwargs["message"])

    def test_probe_holds_the_backup_lock(self):
        def probe(*args):
            with device_backup_lock(DEVICE.device_id) as acquired:
                self.assertFalse(acquired)
            return {"os_version": "15.2", "family": "ios"}

        self.worker.probe = probe
        self.worker.run_once()
        with device_backup_lock(DEVICE.device_id) as acquired:
            self.assertTrue(acquired)

    def test_exception_text_is_not_sent_to_browser_or_saved(self):
        self.probe.side_effect = RuntimeError(LOGIN.password)
        self.worker.run_once()
        self.assertNotIn(LOGIN.password, str(self.store.finish.call_args))
        self.assertIn("RuntimeError", str(self.store.finish.call_args))

    def test_detected_os_cannot_silently_change_the_configured_platform(self):
        self.probe.return_value = {"os_version": "9.3", "family": "nxos"}
        self.worker.run_once()
        self.assertNotIn("facts", self.store.finish.call_args.kwargs)
        self.assertIn("driver", self.store.finish.call_args.kwargs["message"])

    def test_lost_claim_does_not_probe(self):
        self.store.claim.return_value = False
        self.assertEqual(self.worker.run_once(), 0)
        self.probe.assert_not_called()

    def test_start_recovers_interrupted_inspections(self):
        self.worker.start()
        self.store.recover.assert_called_once()


class TestInspectionApi(unittest.TestCase):
    def setUp(self):
        from app.views import restore_jobs as view
        from test_restore_service import ServiceEnv
        from view_test_support import make_test_app, logged_in

        self.env = ServiceEnv(device=replace(DEVICE, device_id=1))
        self.client = make_test_app(
            [
                (
                    "/api/restore/device/<device_id>/inspect",
                    "restore_device_inspection",
                    view.restore_device_inspection,
                    ["GET", "POST"],
                ),
                (
                    "/api/restore/inspect",
                    "restore_device_inspections",
                    view.restore_device_inspections,
                    ["POST"],
                ),
            ]
        ).test_client()
        logged_in(self.client, "admin", [5])
        services = patch.object(
            view, "_services", return_value=(self.env.service, None)
        )
        services.start()
        self.addCleanup(services.stop)
        store = patch("app.modules.restore.inspection.DbInspectionStore")
        self.store = store.start().return_value
        self.addCleanup(store.stop)
        self.row = dict(
            status="queued",
            identity=device_identity(self.env.device),
            completed_at=None,
            model=None,
            os_version=None,
            message="Waiting for worker",
        )
        self.store.request.return_value = self.row
        self.store.get.return_value = None

    def test_post_only_queues_and_never_connects(self):
        with patch("app.modules.restore.inspection.inspect_platform") as probe:
            response = self.client.post("/api/restore/device/1/inspect")
        self.assertEqual(response.status_code, 202)
        self.store.request.assert_called_once()
        probe.assert_not_called()
        self.assertNotIn("identity", response.get_json())

    def test_get_does_not_create_a_request(self):
        self.assertEqual(
            self.client.get("/api/restore/device/1/inspect").get_json()["status"],
            "not_requested",
        )
        self.store.request.assert_not_called()

    def test_plain_user_and_other_device_are_refused(self):
        from view_test_support import logged_in

        self.assertEqual(
            self.client.post("/api/restore/device/2/inspect").status_code, 403
        )
        logged_in(self.client, "user", [5])
        self.assertEqual(
            self.client.post("/api/restore/device/1/inspect").status_code, 403
        )
        self.store.request.assert_not_called()

    def test_unsupported_driver_is_not_queued(self):
        self.env.devices.device = replace(self.env.device, driver="unknown")
        self.assertEqual(
            self.client.post("/api/restore/device/1/inspect").status_code, 400
        )
        self.store.request.assert_not_called()

    def test_outdated_result_is_labeled(self):
        self.store.get.return_value = dict(
            self.row,
            status="ready",
            completed_at=now_utc() - timedelta(days=2),
            os_version="15.2",
        )
        response = self.client.get("/api/restore/device/1/inspect")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["fresh"])

    def test_bulk_detection_is_bounded_and_checks_access_before_queueing(self):
        response = self.client.post("/api/restore/inspect", json={"device_ids": [1, 2]})
        self.assertEqual(response.status_code, 403)
        self.store.request.assert_not_called()
        response = self.client.post(
            "/api/restore/inspect", json={"device_ids": [1] * 501}
        )
        self.assertEqual(response.status_code, 400)
        self.store.request.assert_not_called()

    def test_bulk_detection_deduplicates_selected_devices(self):
        response = self.client.post("/api/restore/inspect", json={"device_ids": [1, 1]})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["queued"], [1])
        self.store.request.assert_called_once()


class TestReadOnlyWorkerMode(unittest.TestCase):
    def test_inspection_mode_never_constructs_restore_execution(self):
        import restore_worker
        from contextlib import ExitStack

        with ExitStack() as stack:
            stack.enter_context(
                patch("sys.argv", ["restore_worker.py", "--inspect-only"])
            )
            stack.enter_context(patch.object(restore_worker, "db"))
            stack.enter_context(patch.object(restore_worker.signal, "signal"))
            loop = stack.enter_context(
                patch.object(restore_worker, "run_inspection_only")
            )
            engine = stack.enter_context(
                patch("app.modules.restore.engine.RestoreEngine")
            )
            jobs = stack.enter_context(patch("app.modules.restore.db_store.DbJobStore"))
            full_worker = stack.enter_context(
                patch("app.modules.restore.worker.RestoreWorker")
            )
            self.assertEqual(restore_worker.main(), 0)
            loop.assert_called_once()
            engine.assert_not_called()
            jobs.assert_not_called()
            full_worker.assert_not_called()

    def test_read_only_loop_only_polls_inspections(self):
        from restore_worker import run_inspection_only

        worker = Mock()
        worker.run_once.side_effect = [0, 1]
        stop = Mock(side_effect=[False, False, True])
        sleep = Mock()
        run_inspection_only(worker, stop, sleep)
        worker.start.assert_called_once()
        self.assertEqual(worker.run_once.call_count, 2)
        sleep.assert_called_once_with(3)


if __name__ == "__main__":
    unittest.main()
