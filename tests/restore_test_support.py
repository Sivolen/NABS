"""In-memory doubles for the Restore Engine tests (no database, no equipment)."""

import copy
import hashlib
from datetime import datetime, timedelta, timezone

import yaml

from app.modules.restore import states as st
from app.modules.restore.adapters import base
from app.modules.restore.adapters.mock import MockAdapter
from app.modules.restore.engine import RestoreEngine
from app.modules.restore.storage import ConfigRecord, JobRecord
from test_restore_schema import VALID

PASSWORD = "S3cretPW-do-not-log"
PRE = "hostname old\ninterface 1\n shutdown\n"
TARGET = "hostname new\ninterface 1\n no shutdown\n"
T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    """Deterministic time: sleeping advances it."""

    def __init__(self):
        self.now = T0
        self.mono = 0.0
        self.sleeps = []

    def utcnow(self):
        return self.now

    def monotonic(self):
        return self.mono

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.mono += seconds
        self.now += timedelta(seconds=seconds)

    def advance(self, seconds):
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


class InMemoryJobStore:
    def __init__(self):
        self.jobs = {}
        self.events = []
        self.transitions = []

    def add_job(self, job):
        self.jobs[job.id] = job

    def get_job(self, job_id):
        job = self.jobs.get(job_id)
        return copy.deepcopy(job) if job else None

    def transition(self, job_id, new_status, expected, **fields):
        job = self.jobs.get(job_id)
        if job is None or job.status not in set(expected):
            return False
        self.transitions.append((job.status, new_status))
        job.status = new_status
        for key, value in fields.items():
            setattr(job, key, value)
        return True

    def update(self, job_id, **fields):
        job = self.jobs[job_id]
        for key, value in fields.items():
            setattr(job, key, value)

    def add_event(self, job_id, stage, event_type, level, message, details=None):
        self.events.append(
            dict(
                job_id=job_id,
                stage=stage,
                type=event_type,
                level=level,
                message=message,
                details=details,
                time="2026-10-05T12:00:00+00:00",
            )
        )

    def list_jobs(self, statuses):
        wanted = set(statuses)
        return [copy.deepcopy(j) for j in self.jobs.values() if j.status in wanted]

    # ---- added for the service/worker (same contract as DbJobStore)
    def create_job(self, fields):
        for job in self.jobs.values():
            if job.client_token == fields["client_token"]:
                return copy.deepcopy(job), False
        job_id = max(self.jobs, default=0) + 1
        job = JobRecord(id=job_id, **fields)
        self.jobs[job_id] = job
        return copy.deepcopy(job), True

    def claim_requested_action(self, job_id, action):
        job = self.jobs.get(job_id)
        if job is None or job.requested_action != action:
            return False
        job.requested_action = None
        return True

    def list_requested(self, action):
        return [
            copy.deepcopy(j)
            for j in self.jobs.values()
            if j.requested_action == action
            and j.status in ("created", "awaiting_confirmation")
        ]

    def list_events(self, job_id):
        return [e for e in self.events if e["job_id"] == job_id]

    def list_jobs_for_device(self, device_id, limit=50):
        rows = [j for j in self.jobs.values() if j.device_id == device_id]
        return [copy.deepcopy(j) for j in sorted(rows, key=lambda j: -j.id)[:limit]]


class InMemoryConfigStore:
    def __init__(self):
        self.configs = {}
        self.next_id = 100
        self.fail_save = False

    def add(self, config_id, device_id, text):
        self.configs[config_id] = ConfigRecord(
            config_id, device_id, text, "2026-10-05 12:00"
        )

    def get_config(self, config_id):
        return self.configs.get(config_id)

    def save_pre_restore_config(self, device_id, ip, text, timestamp):
        if self.fail_save:
            return None
        self.next_id += 1
        self.add(self.next_id, device_id, text)
        return self.next_id


class InMemoryDevices:
    def __init__(self, device, credentials):
        self.device = device
        self.credentials = credentials

    def get_device(self, device_id):
        return (
            self.device if self.device and self.device.device_id == device_id else None
        )

    def get_credentials(self, device_id):
        return self.credentials


def profile_yaml(mutate=None):
    data = yaml.safe_load(VALID)
    if mutate:
        mutate(data)
    return yaml.safe_dump(data, sort_keys=False)


def make_job(content=None, job_id=1, device_id=1, target_config_id=10, source="user"):
    content = content or profile_yaml()
    return JobRecord(
        id=job_id,
        device_id=device_id,
        target_config_id=target_config_id,
        profile_source=source,
        profile_key="mock_platform",
        profile_version=1,
        profile_sha256=hashlib.sha256(content.encode()).hexdigest(),
        profile_content=content,
        initiator="tester",
    )


class Env:
    """Everything wired together; `adapter` is the one the engine will get."""

    def __init__(
        self,
        adapter=None,
        profile=None,
        device=None,
        credentials="default",
        profile_source="user",
    ):
        self.clock = FakeClock()
        self.store = InMemoryJobStore()
        self.configs = InMemoryConfigStore()
        self.configs.add(10, 1, TARGET)
        self.adapter = (
            adapter if adapter is not None else MockAdapter(running_config=PRE)
        )
        self.device = device or base.DeviceInfo(
            device_id=1,
            ip="192.0.2.1",
            hostname="sw1",
            driver="mock_os",
            model="M1",
            os_version="1.0",
        )
        if credentials == "default":
            credentials = base.Credentials("admin", PASSWORD)
        self.devices = InMemoryDevices(self.device, credentials)
        self.factory_calls = 0
        self.engine = RestoreEngine(
            self.store,
            self.configs,
            self.devices,
            self._factory,
            now=self.clock.utcnow,
            timestamp=lambda: "2026-10-05 12:00",
            sleep=self.clock.sleep,
            monotonic=self.clock.monotonic,
        )
        self.job = make_job(profile, source=profile_source)
        self.store.add_job(self.job)

    def _factory(self, adapter_type):
        self.factory_calls += 1
        return (
            self.adapter
            if adapter_type == getattr(self.adapter, "type", None)
            else None
        )

    # ---- shortcuts
    @property
    def live(self):
        return self.store.jobs[self.job.id]

    def to_queued(self):
        result = self.engine.run_precheck(self.job.id)
        assert result["status"] in ("ready", "warning"), result
        ok, why = self.engine.confirm(self.job.id, "tester", result["fingerprint"])
        assert ok, why
        return result

    def run_all(self):
        self.to_queued()
        self.engine.execute(self.job.id, "w1")
        return self.live

    def all_text(self):
        parts = [
            self.live.summary or "",
            str(self.live.diagnostics),
            str(self.live.rollback_details),
        ]
        parts += [f"{e['message']} {e['details']}" for e in self.store.events]
        return "\n".join(parts)


class InMemoryProfileRepo:
    """Same contract as DbProfileRepo."""

    def __init__(self):
        self.profiles = {}
        self.assignments = {}

    def list_user_profiles(self):
        return [copy.deepcopy(self.profiles[k]) for k in sorted(self.profiles)]

    def get_user_profile(self, key):
        return copy.deepcopy(self.profiles.get(key))

    def create_user_profile(self, record):
        if record.key in self.profiles:
            return False
        self.profiles[record.key] = copy.deepcopy(record)
        return True

    def update_user_profile(self, key, expected_sha256, fields):
        record = self.profiles.get(key)
        if record is None or record.content_sha256 != expected_sha256:
            return False
        for name, value in fields.items():
            setattr(record, name, value)
        return True

    def delete_user_profile(self, key):
        return self.profiles.pop(key, None) is not None

    def assigned_counts(self):
        counts = {}
        for source, key in self.assignments.values():
            counts[(source, key)] = counts.get((source, key), 0) + 1
        return counts

    def get_assignment(self, device_id):
        return self.assignments.get(device_id)

    def set_assignment(self, device_id, source, key, user):
        self.assignments[device_id] = (source, key)

    def delete_assignment(self, device_id):
        return self.assignments.pop(device_id, None) is not None


class NaiveUtcStore(InMemoryJobStore):
    """Like the real database: datetimes come back NAIVE (tz-aware ones lose their zone)."""

    @staticmethod
    def _naive(fields):
        out = {}
        for key, value in fields.items():
            if hasattr(value, "tzinfo") and value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            out[key] = value
        return out

    def transition(self, job_id, new_status, expected, **fields):
        return super().transition(job_id, new_status, expected, **self._naive(fields))

    def update(self, job_id, **fields):
        return super().update(job_id, **self._naive(fields))
