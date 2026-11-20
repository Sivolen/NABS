"""
Database-backed implementations of the Restore Engine interfaces (storage.py).

Everything that changes a job's status is ONE "UPDATE ... WHERE id = :id AND status IN
(:expected)" statement: the row count tells who won, so a repeated request, a second
worker or a restart can never run a job twice. Reads use populate_existing() so a
long-lived worker never works with a stale cached row.

NOT covered by the unit tests (they need a real PostgreSQL): verify it on a staging
database before use (create/duplicate token, status CAS with two sessions, claim).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    Configs,
    CustomDrivers,
    Devices,
    DeviceRestoreProfile,
    RestoreJob,
    RestoreJobEvent,
    RestoreProfile,
)
from app.modules.restore.adapters.base import Credentials, DeviceInfo
from app.modules.restore.dbmap import (
    PROFILE_FIELDS,
    dumps_json,
    fields_to_columns,
    loads_json,
    profile_fields_to_columns,
    resolve_platform,
    row_to_profile_record,
    row_to_record,
)
from app.modules.restore.profiles import USER, ProfileText
from app.modules.restore.storage import ConfigRecord, JobRecord, UserProfileRecord

log = logging.getLogger("nabs.restore")

PRECHECK_STATES = ("created", "awaiting_confirmation")


class DbJobStore:
    def get_job(self, job_id: int) -> Optional[JobRecord]:
        row = RestoreJob.query.populate_existing().filter_by(id=job_id).first()
        record = row_to_record(row) if row is not None else None
        db.session.commit()  # end the read transaction
        return record

    def transition(
        self,
        job_id: int,
        new_status: str,
        expected: Iterable[str],
        *,
        expected_precheck: Optional[Dict[str, Any]] = None,
        **fields: Any,
    ) -> bool:
        values = fields_to_columns(fields)
        values["status"] = new_status
        query = RestoreJob.query.filter(
            RestoreJob.id == job_id, RestoreJob.status.in_(list(expected))
        )
        if expected_precheck is not None:
            query = query.filter(
                RestoreJob.precheck_result == dumps_json(expected_precheck)
            )
        try:
            changed = query.update(values, synchronize_session=False)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return changed == 1

    def update(self, job_id: int, **fields: Any) -> None:
        try:
            RestoreJob.query.filter_by(id=job_id).update(
                fields_to_columns(fields), synchronize_session=False
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    def add_event(
        self,
        job_id: int,
        stage: Optional[str],
        event_type: str,
        level: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            db.session.add(
                RestoreJobEvent(
                    job_id=job_id,
                    stage=(stage or "")[:60] or None,
                    event_type=event_type[:40],
                    level=level[:10],
                    message=message[:1000],
                    details=dumps_json(details),
                )
            )
            db.session.commit()
        except Exception:
            # a journal write must not abort a running restore, but it is never silent
            db.session.rollback()
            log.error(
                "could not write the journal of restore job %s", job_id, exc_info=True
            )

    def list_jobs(self, statuses: Iterable[str]) -> List[JobRecord]:
        rows = (
            RestoreJob.query.populate_existing()
            .filter(RestoreJob.status.in_(list(statuses)))
            .order_by(RestoreJob.id)
            .all()
        )
        records = [row_to_record(r) for r in rows]
        db.session.commit()
        return records

    def list_requested(self, action: str) -> List[JobRecord]:
        rows = (
            RestoreJob.query.populate_existing()
            .filter(
                RestoreJob.requested_action == action,
                RestoreJob.status.in_(PRECHECK_STATES),
            )
            .order_by(RestoreJob.id)
            .all()
        )
        records = [row_to_record(r) for r in rows]
        db.session.commit()
        return records

    def create_job(self, fields: Dict[str, Any]) -> Tuple[JobRecord, bool]:
        values = fields_to_columns(fields)
        try:
            row = RestoreJob(**values)
            db.session.add(row)
            db.session.commit()
            return row_to_record(row), True
        except IntegrityError:
            db.session.rollback()
            existing = RestoreJob.query.filter_by(
                client_token=fields["client_token"]
            ).first()
            if existing is None:
                raise
            record = row_to_record(existing)
            db.session.commit()
            return record, False
        except Exception:
            db.session.rollback()
            raise

    def list_events(self, job_id: int) -> List[Dict[str, Any]]:
        rows = (
            RestoreJobEvent.query.filter_by(job_id=job_id)
            .order_by(RestoreJobEvent.id)
            .all()
        )
        events = [
            {
                "time": r.created_at.isoformat() if r.created_at else None,
                "stage": r.stage,
                "type": r.event_type,
                "level": r.level,
                "message": r.message,
                "details": loads_json(r.details, None),
            }
            for r in rows
        ]
        db.session.commit()
        return events

    def list_jobs_for_device(self, device_id: int, limit: int = 50) -> List[JobRecord]:
        rows = (
            RestoreJob.query.filter_by(device_id=device_id)
            .order_by(RestoreJob.id.desc())
            .limit(limit)
            .all()
        )
        records = [row_to_record(r) for r in rows]
        db.session.commit()
        return records


class DbConfigStore:
    """The existing `Configs` table: restore reads from it and writes its pre-copies to it."""

    def get_config(self, config_id: int) -> Optional[ConfigRecord]:
        row = Configs.query.filter_by(id=config_id).first()
        record = (
            ConfigRecord(row.id, row.device_id, row.device_config, row.timestamp)
            if row is not None
            else None
        )
        db.session.commit()
        return record

    def save_pre_restore_config(
        self, device_id: int, ip: str, text: str, timestamp: str
    ) -> Optional[int]:
        # write_config() returns only a bool; the job needs the new row's id
        try:
            row = Configs(
                device_ip=ip,
                device_config=text,
                device_id=device_id,
                timestamp=timestamp,
            )
            db.session.add(row)
            db.session.flush()
            config_id = row.id
            db.session.commit()
            return config_id
        except Exception:
            db.session.rollback()
            log.error(
                "could not save the pre-restore copy for device %s",
                device_id,
                exc_info=True,
            )
            return None


def _custom_drivers() -> Dict[int, Dict[str, Any]]:
    """The (small) Custom_Drivers table as {id: {...}}."""
    rows = CustomDrivers.query.all()
    return {
        r.id: {"drivers_platform": r.drivers_platform, "drivers_name": r.drivers_name}
        for r in rows
    }


def device_platforms(device_ids: Iterable[int]) -> Dict[int, Optional[str]]:
    """{device id: platform} for the device list (two queries, however many devices)."""
    ids = list(device_ids)
    if not ids:
        return {}
    custom = _custom_drivers()
    rows = (
        db.session.query(
            Devices.id, Devices.connection_driver, Devices.custom_drivers_switch
        )
        .filter(Devices.id.in_(ids))
        .all()
    )
    result = {
        device_id: resolve_platform(driver, switch, custom)[0]
        for device_id, driver, switch in rows
    }
    db.session.commit()
    return result


class DbDeviceProvider:
    def get_device(self, device_id: int) -> Optional[DeviceInfo]:
        row = Devices.query.filter_by(id=device_id).first()
        info = None
        if row is not None:
            platform, netmiko_type = resolve_platform(
                row.connection_driver, row.custom_drivers_switch, _custom_drivers()
            )
            info = DeviceInfo(
                device_id=row.id,
                ip=row.device_ip,
                hostname=row.device_hostname,
                driver=platform,
                netmiko_device_type=netmiko_type,
                port=row.ssh_port,
                vendor=row.device_vendor,
                model=row.device_model,
                # NABS does not store the OS version as a field: a profile that
                # restricts versions therefore cannot be confirmed (it blocks)
                os_version=None,
            )
        db.session.commit()
        if info is not None:
            from app.modules.restore.inspection import DbInspectionStore

            info = DbInspectionStore().enrich(info)
        return info

    def get_credentials(self, device_id: int) -> Optional[Credentials]:
        from app.modules.crypto import decrypt
        from app.modules.dbutils.db_utils import get_user_and_pass
        from config import CREDENTIALS_ENCRYPTION_KEY

        try:
            data = get_user_and_pass(device_id)
            if not data or not data.get("credentials_username"):
                return None
            password = decrypt(
                data["credentials_password"], key=CREDENTIALS_ENCRYPTION_KEY
            )
            return Credentials(data["credentials_username"], password)
        except Exception:
            # never include the exception text: it could carry a secret
            log.error("could not read the credentials of device %s", device_id)
            return None


class DbProfileRepo:
    """
    User profiles + device assignments. It is also the ProfileProvider for source "user"
    (`get`) and the AssignmentProvider of the restore service (`get_assigned`).
    """

    # ---- ProfileProvider / AssignmentProvider
    def get(self, source: str, key: str) -> Optional[ProfileText]:
        if source != USER:
            return None
        row = RestoreProfile.query.filter_by(profile_key=key).first()
        text = (
            ProfileText(USER, row.profile_key, row.profile_version, row.content)
            if row is not None
            else None
        )
        db.session.commit()
        return text

    def get_assigned(self, device_id: int) -> Optional[Tuple[str, str]]:
        return self.get_assignment(device_id)

    # ---- ProfileRepo
    def list_user_profiles(self) -> List[UserProfileRecord]:
        rows = RestoreProfile.query.order_by(RestoreProfile.profile_key).all()
        records = [row_to_profile_record(r) for r in rows]
        db.session.commit()
        return records

    def get_user_profile(self, key: str) -> Optional[UserProfileRecord]:
        row = (
            RestoreProfile.query.populate_existing().filter_by(profile_key=key).first()
        )
        record = row_to_profile_record(row) if row is not None else None
        db.session.commit()
        return record

    def create_user_profile(self, record: UserProfileRecord) -> bool:
        try:
            db.session.add(
                RestoreProfile(
                    **profile_fields_to_columns(
                        {name: getattr(record, name) for name in PROFILE_FIELDS}
                    )
                )
            )
            db.session.commit()
            return True
        except IntegrityError:
            db.session.rollback()
            return False
        except Exception:
            db.session.rollback()
            raise

    def update_user_profile(
        self, key: str, expected_sha256: str, fields: Dict[str, Any]
    ) -> bool:
        try:
            changed = RestoreProfile.query.filter(
                RestoreProfile.profile_key == key,
                RestoreProfile.content_sha256 == expected_sha256,
            ).update(profile_fields_to_columns(fields), synchronize_session=False)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return changed == 1

    def delete_user_profile(self, key: str) -> bool:
        try:
            deleted = RestoreProfile.query.filter_by(profile_key=key).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return deleted == 1

    def assigned_counts(self) -> Dict[Tuple[str, str], int]:
        rows = (
            db.session.query(
                DeviceRestoreProfile.profile_source,
                DeviceRestoreProfile.profile_key,
                db.func.count(DeviceRestoreProfile.id),
            )
            .group_by(
                DeviceRestoreProfile.profile_source, DeviceRestoreProfile.profile_key
            )
            .all()
        )
        counts = {(source, key): count for source, key, count in rows}
        db.session.commit()
        return counts

    def get_assignment(self, device_id: int) -> Optional[Tuple[str, str]]:
        row = DeviceRestoreProfile.query.filter_by(device_id=device_id).first()
        result = (row.profile_source, row.profile_key) if row is not None else None
        db.session.commit()
        return result

    def set_assignment(self, device_id: int, source: str, key: str, user: str) -> None:
        values = {
            "profile_source": source,
            "profile_key": key,
            "assigned_by": user,
            "assigned_at": datetime.now(timezone.utc).replace(tzinfo=None),
        }
        try:
            changed = DeviceRestoreProfile.query.filter_by(device_id=device_id).update(
                values, synchronize_session=False
            )
            if changed == 0:
                db.session.add(DeviceRestoreProfile(device_id=device_id, **values))
            db.session.commit()
        except IntegrityError:
            # another request inserted the same device meanwhile: update it instead
            db.session.rollback()
            DeviceRestoreProfile.query.filter_by(device_id=device_id).update(
                values, synchronize_session=False
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    def delete_assignment(self, device_id: int) -> bool:
        try:
            deleted = DeviceRestoreProfile.query.filter_by(device_id=device_id).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return deleted > 0


# earlier names, kept so nothing that imported them breaks
DbUserProfileRepo = DbProfileRepo
DbAssignments = DbProfileRepo
