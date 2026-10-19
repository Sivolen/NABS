"""
What the Restore Engine needs from the rest of NABS, as small interfaces.

The engine never touches SQLAlchemy, Flask or the existing db_* helpers itself: the
service (next stage) provides database-backed implementations, the tests provide
in-memory ones. `JobStore.transition` is the ONLY way a job changes state and it
must be an atomic compare-and-set (UPDATE ... WHERE status IN (:expected)).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Protocol

from app.modules.restore.adapters.base import Credentials, DeviceInfo


@dataclass
class JobRecord:
    id: int
    device_id: int
    target_config_id: int
    profile_source: str  # "builtin" | "user"
    profile_key: str
    profile_version: int
    profile_sha256: str
    profile_content: str  # snapshot of the YAML used by this job
    initiator: str
    status: str = "created"
    stage: Optional[str] = None
    summary: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    precheck_status: Optional[str] = None
    precheck_result: Optional[Dict[str, Any]] = None
    confirmed_fingerprint: Optional[str] = None
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    pre_restore_config_id: Optional[int] = None
    rollback_status: Optional[str] = None
    rollback_details: Optional[str] = None
    worker_id: Optional[str] = None
    # set by the service ("precheck"); the worker claims it atomically
    requested_action: Optional[str] = None
    client_token: Optional[str] = None
    heartbeat_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


@dataclass(frozen=True)
class ConfigRecord:
    id: int
    device_id: Optional[int]
    text: str
    timestamp: Optional[str] = None


class JobStore(Protocol):
    def get_job(self, job_id: int) -> Optional[JobRecord]:
        ...

    def transition(
        self, job_id: int, new_status: str, expected: Iterable[str], **fields: Any
    ) -> bool:
        """Atomically set status (and fields) if the current status is in `expected`."""

    def update(self, job_id: int, **fields: Any) -> None:
        """Update fields that do not change the status."""

    def add_event(
        self,
        job_id: int,
        stage: Optional[str],
        event_type: str,
        level: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        ...

    def list_jobs(self, statuses: Iterable[str]) -> List[JobRecord]:
        ...

    def create_job(self, fields: Dict[str, Any]) -> "tuple[JobRecord, bool]":
        """
        Insert a job. `client_token` is unique: a repeated request returns the
        EXISTING job and False instead of creating a second one.
        """

    def claim_requested_action(self, job_id: int, action: str) -> bool:
        """Atomically clear requested_action if it equals `action` (one claimer wins)."""

    def list_requested(self, action: str) -> List[JobRecord]:
        ...

    def list_events(self, job_id: int) -> List[Dict[str, Any]]:
        ...

    def list_jobs_for_device(self, device_id: int, limit: int = 50) -> List[JobRecord]:
        ...


class ConfigStore(Protocol):
    """The existing NABS configuration storage (the `Configs` table)."""

    def get_config(self, config_id: int) -> Optional[ConfigRecord]:
        ...

    def save_pre_restore_config(
        self, device_id: int, ip: str, text: str, timestamp: str
    ) -> Optional[int]:
        """Store the pre-restore copy in the same storage as every backup; its id."""


class DeviceProvider(Protocol):
    def get_device(self, device_id: int) -> Optional[DeviceInfo]:
        ...

    def get_credentials(self, device_id: int) -> Optional[Credentials]:
        ...


@dataclass
class UserProfileRecord:
    key: str
    name: str
    description: str
    vendor: str
    platforms: List[str]
    schema_version: int
    profile_version: int
    content: str
    content_sha256: str
    origin_kind: Optional[str] = None  # "builtin" | "copy" | "import" | None
    origin_key: Optional[str] = None
    origin_version: Optional[int] = None
    origin_sha256: Optional[str] = None
    author: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_validation_ok: Optional[bool] = None
    last_validation: List[Dict[str, str]] = field(default_factory=list)


class ProfileRepo(Protocol):
    """User profiles and the profile assigned to each device."""

    def list_user_profiles(self) -> List[UserProfileRecord]:
        ...

    def get_user_profile(self, key: str) -> Optional[UserProfileRecord]:
        ...

    def create_user_profile(self, record: UserProfileRecord) -> bool:
        """False if the key is already taken (unique)."""

    def update_user_profile(
        self, key: str, expected_sha256: str, fields: Dict[str, Any]
    ) -> bool:
        """Compare-and-set on content_sha256: False if somebody changed it meanwhile."""

    def delete_user_profile(self, key: str) -> bool:
        ...

    def assigned_counts(self) -> Dict["tuple[str, str]", int]:
        ...

    def get_assignment(self, device_id: int) -> Optional["tuple[str, str]"]:
        ...

    def set_assignment(self, device_id: int, source: str, key: str, user: str) -> None:
        ...

    def delete_assignment(self, device_id: int) -> bool:
        ...
