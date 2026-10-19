"""
Management of restore profiles: view, copy, edit, import/export, delete, and the
assignment of a profile to devices.

Rules enforced here (not in the UI):
  * built-in profiles are read-only: they can be viewed, exported and copied;
  * a user profile is always validated before it is stored; what is stored is the
    canonical YAML (comments are not preserved), with the id fixed and the profile
    version raised by the service whenever the content really changes;
  * saving needs the checksum of the text that was edited (no lost updates);
  * a profile is assigned to a device only if it is valid, runnable (its adapter really
    implements every action) and positively compatible with that device;
  * importing never assigns a profile and never overwrites without `overwrite=True`.
Every call checks the role (sadmin/admin) and, for devices, the access to each device.
"""

import dataclasses
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from app.modules.access import can_access_device, parse_id
from app.modules.restore.adapters import adapter_capabilities
from app.modules.restore.compat import COMPATIBLE, check_compatibility
from app.modules.restore.engine import ENGINE_IMPLEMENTED_ACTIONS
from app.modules.restore.profiles import BUILTIN, USER, BuiltinProfileProvider
from app.modules.restore.settings import unverified_adapters_enabled
from app.modules.restore.schema import (
    ID_RE,
    MAX_YAML_BYTES,
    Issue,
    RestoreProfile,
    ValidationResult,
    check_adapter_capabilities,
    dump_profile_yaml,
    parse_profile_yaml,
)
from app.modules.restore.service import (
    CONFLICT,
    FORBIDDEN,
    INVALID,
    NOT_FOUND,
    RESTORE_ROLES,
    ServiceError,
)
from app.modules.restore.storage import DeviceProvider, ProfileRepo, UserProfileRecord

audit = logging.getLogger("nabs.restore.audit")
MAX_BULK_DEVICES = 500


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _issues(items: List[Issue]) -> List[Dict[str, str]]:
    return [{"level": i.level, "path": i.path, "message": i.message} for i in items]


def _summary(profile: RestoreProfile) -> Dict[str, Any]:
    return {
        "key": profile.id,
        "name": profile.name,
        "description": profile.description,
        "vendor": profile.vendor,
        "platforms": list(profile.platforms),
        "profile_version": profile.profile_version,
        "schema_version": profile.schema_version,
        "adapter": profile.adapter_type,
    }


class ProfileService:
    def __init__(
        self,
        builtin: BuiltinProfileProvider,
        repo: ProfileRepo,
        devices: DeviceProvider,
        access: Callable[[Mapping, Any], bool] = can_access_device,
        capabilities: Optional[Callable[[], Dict[str, set]]] = None,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.builtin = builtin
        self.repo = repo
        self.devices = devices
        self._access = access
        self._capabilities = capabilities or (
            lambda: adapter_capabilities(
                engine_actions=ENGINE_IMPLEMENTED_ACTIONS,
                include_unverified=unverified_adapters_enabled(),
            )
        )
        self._now = now or (lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _require_role(session_obj: Mapping) -> str:
        user = str(session_obj.get("user") or "")
        if not user or str(session_obj.get("rights") or "") not in RESTORE_ROLES:
            raise ServiceError(
                FORBIDDEN, "You are not allowed to manage restore profiles"
            )
        return user

    def _audit(
        self, user: str, action: str, key: str, content_sha: Optional[str] = None
    ) -> None:
        # never the YAML itself, only who did what to which profile
        audit.info(
            "user=%s action=%s profile=%s sha256=%s",
            user,
            action,
            key,
            content_sha or "-",
        )

    def _runnable_issues(self, profile: RestoreProfile) -> List[Dict[str, str]]:
        issues = check_adapter_capabilities(profile, self._capabilities())
        out = _issues(issues)
        if any(i.code == "adapter_not_implemented" for i in issues):
            from app.modules.restore.adapters import adapter_classes

            cls = adapter_classes(include_mock=False, include_unverified=True).get(
                profile.adapter_type
            )
            if cls is not None and not cls.verified:
                out = [
                    {
                        "level": "error",
                        "path": "adapter.type",
                        "message": f"adapter {profile.adapter_type!r} has not been verified on"
                        " hardware and is switched off (RESTORE_ENABLE_UNVERIFIED_ADAPTERS)",
                    }
                ]
        return out

    @staticmethod
    def _parse(text: Any, allow_builtin: bool = False) -> ValidationResult:
        return parse_profile_yaml(text, allow_builtin=allow_builtin)

    @staticmethod
    def _invalid(result: ValidationResult) -> ServiceError:
        first = result.errors[0] if result.errors else None
        return ServiceError(
            INVALID,
            f"The profile is invalid: {first}" if first else "The profile is invalid",
            _issues(result.errors),
        )

    def _key_taken(self, key: str) -> Optional[str]:
        if self.builtin.get(BUILTIN, key) is not None:
            return "a built-in profile already uses this id"
        if self.repo.get_user_profile(key) is not None:
            return "a profile with this id already exists"
        return None

    def _check_new_key(self, key: Any) -> str:
        if not isinstance(key, str) or not ID_RE.match(key):
            raise ServiceError(
                INVALID, f"Invalid profile id (use a-z, 0-9, _ and -; {ID_RE.pattern})"
            )
        reason = self._key_taken(key)
        if reason:
            raise ServiceError(CONFLICT, f"Cannot use id {key!r}: {reason}")
        return key

    def _record(
        self,
        profile: RestoreProfile,
        user: str,
        origin: Optional[
            Tuple[str, Optional[str], Optional[int], Optional[str]]
        ] = None,
    ) -> UserProfileRecord:
        text = dump_profile_yaml(profile)
        now = self._now()
        kind, okey, over, osha = origin or (None, None, None, None)
        return UserProfileRecord(
            key=profile.id,
            name=profile.name,
            description=profile.description,
            vendor=profile.vendor,
            platforms=list(profile.platforms),
            schema_version=profile.schema_version,
            profile_version=profile.profile_version,
            content=text,
            content_sha256=_sha(text),
            origin_kind=kind,
            origin_key=okey,
            origin_version=over,
            origin_sha256=osha,
            author=user,
            created_at=now,
            updated_at=now,
            last_validation_ok=True,
            last_validation=_issues(self._parse(text).warnings),
        )

    def _load(self, source: str, key: Any) -> Tuple[str, Optional[UserProfileRecord]]:
        """(YAML text, user record or None for built-in). NOT_FOUND otherwise."""
        if source == BUILTIN:
            text = self.builtin.get(BUILTIN, str(key))
            if text is None:
                raise ServiceError(NOT_FOUND, "Profile not found")
            return text.content, None
        if source == USER:
            record = self.repo.get_user_profile(str(key))
            if record is None:
                raise ServiceError(NOT_FOUND, "Profile not found")
            return record.content, record
        raise ServiceError(INVALID, "Invalid profile source")

    # -------------------------------------------------------------------- read
    def list_profiles(
        self,
        session_obj: Mapping,
        query: str = "",
        kind: str = "",
        vendor: str = "",
        sort: str = "name",
    ) -> List[Dict[str, Any]]:
        self._require_role(session_obj)
        counts = self.repo.assigned_counts()
        rows: List[Dict[str, Any]] = []
        for key in self.builtin.keys():
            text = self.builtin.get(BUILTIN, key)
            profile = self._parse(text.content, allow_builtin=True).profile
            rows.append(self._row(BUILTIN, profile, counts, None))
        for record in self.repo.list_user_profiles():
            result = self._parse(record.content)
            if result.profile is None:  # stored text no longer validates
                rows.append(
                    {
                        "source": USER,
                        "key": record.key,
                        "name": record.name,
                        "vendor": record.vendor,
                        "platforms": record.platforms,
                        "profile_version": record.profile_version,
                        "kind": "user",
                        "valid": False,
                        "runnable": False,
                        "assigned_count": counts.get((USER, record.key), 0),
                        "origin": None,
                        "origin_outdated": False,
                        "updated_at": record.updated_at.isoformat()
                        if record.updated_at
                        else None,
                    }
                )
                continue
            rows.append(self._row(USER, result.profile, counts, record))
        needle = query.strip().lower()
        if needle:
            rows = [
                r
                for r in rows
                if needle in f"{r['key']} {r['name']} {r['vendor']}".lower()
            ]
        if kind in ("builtin", "user"):
            rows = [r for r in rows if r["kind"] == kind]
        if vendor:
            rows = [r for r in rows if (r["vendor"] or "").lower() == vendor.lower()]
        keyfunc = {
            "vendor": lambda r: (r["vendor"] or "").lower(),
            "updated": lambda r: r["updated_at"] or "",
            "version": lambda r: r["profile_version"],
        }.get(sort, lambda r: (r["name"] or "").lower())
        return sorted(rows, key=keyfunc, reverse=sort == "updated")

    def _row(self, source, profile, counts, record) -> Dict[str, Any]:
        row = _summary(profile)
        row.update(
            source=source,
            kind="builtin" if source == BUILTIN else "user",
            valid=True,
            runnable=not self._runnable_issues(profile),
            assigned_count=counts.get((source, profile.id), 0),
            origin=None,
            origin_outdated=False,
            updated_at=None,
        )
        if record is not None:
            row["updated_at"] = (
                record.updated_at.isoformat() if record.updated_at else None
            )
            if record.origin_kind:
                row["origin"] = {
                    "kind": record.origin_kind,
                    "key": record.origin_key,
                    "version": record.origin_version,
                }
                row["origin_outdated"] = self._origin_outdated(record)
        return row

    def _origin_outdated(self, record: UserProfileRecord) -> bool:
        """The built-in profile this copy came from has been updated since."""
        if record.origin_kind != BUILTIN:
            return False
        current = self.builtin.get(BUILTIN, record.origin_key or "")
        return current is not None and current.sha256 != record.origin_sha256

    def find_outdated_copies(self, session_obj: Mapping) -> List[Dict[str, Any]]:
        """User profiles created from an older version of a built-in profile."""
        self._require_role(session_obj)
        return [
            {
                "key": r.key,
                "origin_key": r.origin_key,
                "origin_version": r.origin_version,
            }
            for r in self.repo.list_user_profiles()
            if self._origin_outdated(r)
        ]

    def get_profile(
        self, session_obj: Mapping, source: str, key: str
    ) -> Dict[str, Any]:
        self._require_role(session_obj)
        content, record = self._load(source, key)
        result = self._parse(content, allow_builtin=source == BUILTIN)
        view: Dict[str, Any] = {
            "source": source,
            "key": key,
            "content": content,
            "content_sha256": _sha(content),
            "editable": source == USER,
            "valid": result.ok,
            "issues": _issues(result.issues),
            "runnable_issues": self._runnable_issues(result.profile)
            if result.profile
            else [],
        }
        if result.profile:
            view.update(_summary(result.profile))
            view["key"] = key
        if record is not None and record.origin_kind:
            view["origin"] = {
                "kind": record.origin_kind,
                "key": record.origin_key,
                "version": record.origin_version,
                "outdated": self._origin_outdated(record),
            }
        return view

    def export_profile(
        self, session_obj: Mapping, source: str, key: str
    ) -> Tuple[str, str]:
        """(file name, YAML text)."""
        user = self._require_role(session_obj)
        content, _record = self._load(source, key)
        self._audit(user, "export", str(key), _sha(content))
        return f"{key}.yaml", content

    def validate_text(self, session_obj: Mapping, text: Any) -> Dict[str, Any]:
        """Checks YAML typed in the editor. Stores nothing, changes nothing."""
        self._require_role(session_obj)
        result = self._parse(text)
        return {
            "valid": result.ok,
            "issues": _issues(result.issues),
            "runnable_issues": self._runnable_issues(result.profile)
            if result.profile
            else [],
            "profile": _summary(result.profile) if result.profile else None,
        }

    # ------------------------------------------------------------------ change
    def copy_profile(
        self,
        session_obj: Mapping,
        source: str,
        key: str,
        new_key: Optional[str] = None,
        new_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        user = self._require_role(session_obj)
        content, record = self._load(source, key)
        original = self._parse(content, allow_builtin=source == BUILTIN).profile
        if original is None:
            raise ServiceError(
                INVALID, "The source profile is invalid and cannot be copied"
            )
        if new_key is None:
            base = f"{key}_copy"[:58]
            candidates = [base] + [f"{base}{n}" for n in range(2, 100)]
            new_key = next((c for c in candidates if not self._key_taken(c)), None)
            if new_key is None:
                raise ServiceError(CONFLICT, "Too many copies; choose an id")
        self._check_new_key(new_key)
        name = (new_name or f"{original.name} (copy)").strip()[:100]
        copy = dataclasses.replace(
            original, id=new_key, name=name, builtin=False, profile_version=1
        )
        origin_kind = BUILTIN if source == BUILTIN else "copy"
        saved = self._record(
            copy, user, (origin_kind, key, original.profile_version, _sha(content))
        )
        if not self.repo.create_user_profile(saved):
            raise ServiceError(
                CONFLICT, f"A profile with id {new_key!r} already exists"
            )
        self._audit(user, "copy", f"{key}->{new_key}", saved.content_sha256)
        return self.get_profile(session_obj, USER, new_key)

    def create_profile(self, session_obj: Mapping, text: str) -> Dict[str, Any]:
        user = self._require_role(session_obj)
        result = self._parse(text)
        if not result.ok:
            raise self._invalid(result)
        self._check_new_key(result.profile.id)
        saved = self._record(
            dataclasses.replace(result.profile, profile_version=1), user
        )
        if not self.repo.create_user_profile(saved):
            raise ServiceError(CONFLICT, "A profile with this id already exists")
        self._audit(user, "create", saved.key, saved.content_sha256)
        return self.get_profile(session_obj, USER, saved.key)

    def update_profile(
        self,
        session_obj: Mapping,
        source: str,
        key: str,
        text: str,
        expected_sha256: str,
    ) -> Dict[str, Any]:
        user = self._require_role(session_obj)
        if source == BUILTIN:
            raise ServiceError(
                FORBIDDEN,
                "Built-in profiles are read-only: create a copy and edit the copy",
            )
        _content, record = self._load(source, key)
        result = self._parse(text)
        if not result.ok:
            raise self._invalid(result)
        if result.profile.id != key:
            raise ServiceError(
                INVALID, "The profile id cannot be changed; create a copy instead"
            )
        if record.content_sha256 != expected_sha256:
            raise ServiceError(
                CONFLICT,
                "The profile was changed by someone else; reload it and edit again",
            )
        # the saved text is canonical; the version rises only when something changed
        candidate = dataclasses.replace(
            result.profile, profile_version=record.profile_version
        )
        if _sha(dump_profile_yaml(candidate)) == record.content_sha256:
            return self.get_profile(session_obj, USER, key)  # nothing changed
        new = dataclasses.replace(
            result.profile, profile_version=record.profile_version + 1
        )
        stored = self._record(new, user)
        fields = {
            "name": stored.name,
            "description": stored.description,
            "vendor": stored.vendor,
            "platforms": stored.platforms,
            "schema_version": stored.schema_version,
            "profile_version": stored.profile_version,
            "content": stored.content,
            "content_sha256": stored.content_sha256,
            "updated_at": stored.updated_at,
            "last_validation_ok": True,
            "last_validation": stored.last_validation,
        }
        if not self.repo.update_user_profile(key, expected_sha256, fields):
            raise ServiceError(
                CONFLICT,
                "The profile was changed by someone else; reload it and edit again",
            )
        self._audit(user, "update", key, stored.content_sha256)
        return self.get_profile(session_obj, USER, key)

    def delete_profile(self, session_obj: Mapping, source: str, key: str) -> None:
        user = self._require_role(session_obj)
        if source == BUILTIN:
            raise ServiceError(FORBIDDEN, "Built-in profiles cannot be deleted")
        self._load(source, key)
        if self.repo.assigned_counts().get((USER, key), 0):
            raise ServiceError(
                CONFLICT, "The profile is assigned to devices: unassign it first"
            )
        if not self.repo.delete_user_profile(key):
            raise ServiceError(NOT_FOUND, "Profile not found")
        self._audit(user, "delete", key)

    # ------------------------------------------------------------------ import
    def import_profile(
        self,
        session_obj: Mapping,
        text: Any,
        preview: bool = False,
        overwrite: bool = False,
        new_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        preview=True only reports what would happen. An imported profile is always a
        USER profile (a `builtin: true` in the file is dropped), is never assigned to a
        device, and replaces an existing one only with overwrite=True.
        """
        user = self._require_role(session_obj)
        if (
            isinstance(text, str)
            and len(text.encode("utf-8", "replace")) > MAX_YAML_BYTES
        ):
            raise ServiceError(
                INVALID, f"The file is larger than {MAX_YAML_BYTES} bytes"
            )
        result = self._parse(text, allow_builtin=True)
        if not result.ok:
            if preview:
                return {
                    "valid": False,
                    "issues": _issues(result.issues),
                    "can_import": False,
                }
            raise self._invalid(result)
        incoming_sha = _sha(text)
        profile = dataclasses.replace(result.profile, builtin=False)
        if new_key is not None:
            if not isinstance(new_key, str) or not ID_RE.match(new_key):
                raise ServiceError(INVALID, "Invalid new profile id")
            profile = dataclasses.replace(profile, id=new_key)
        key = profile.id

        conflict = None
        if self.builtin.get(BUILTIN, key) is not None:
            conflict = "builtin"  # can never be overwritten: needs another id
        elif self.repo.get_user_profile(key) is not None:
            conflict = "user"
        info = {
            "valid": True,
            "issues": _issues(result.warnings),
            "profile": _summary(profile),
            "conflict": conflict,
            "runnable_issues": self._runnable_issues(profile),
            "can_import": conflict is None or (conflict == "user" and overwrite),
        }
        if preview:
            return info
        if conflict == "builtin":
            raise ServiceError(
                CONFLICT, "A built-in profile has this id: import it under another id"
            )
        if conflict == "user" and not overwrite:
            raise ServiceError(
                CONFLICT, "A profile with this id exists; confirm to overwrite it"
            )

        origin = (
            "import",
            result.profile.id,
            result.profile.profile_version,
            incoming_sha,
        )
        if conflict == "user":
            existing = self.repo.get_user_profile(key)
            stored = self._record(
                dataclasses.replace(
                    profile, profile_version=existing.profile_version + 1
                ),
                user,
                origin,
            )
            fields = {
                "name": stored.name,
                "description": stored.description,
                "vendor": stored.vendor,
                "platforms": stored.platforms,
                "schema_version": stored.schema_version,
                "profile_version": stored.profile_version,
                "content": stored.content,
                "content_sha256": stored.content_sha256,
                "updated_at": stored.updated_at,
                "origin_kind": "import",
                "origin_key": origin[1],
                "origin_version": origin[2],
                "origin_sha256": origin[3],
                "last_validation_ok": True,
                "last_validation": stored.last_validation,
            }
            if not self.repo.update_user_profile(key, existing.content_sha256, fields):
                raise ServiceError(
                    CONFLICT, "The profile was changed meanwhile; try again"
                )
            self._audit(user, "import_overwrite", key, stored.content_sha256)
        else:
            stored = self._record(
                dataclasses.replace(profile, profile_version=1), user, origin
            )
            if not self.repo.create_user_profile(stored):
                raise ServiceError(CONFLICT, "A profile with this id already exists")
            self._audit(user, "import", key, stored.content_sha256)
        return self.get_profile(session_obj, USER, key)

    # -------------------------------------------------------------- assignment
    def _assignable_profile(
        self, source: str, key: str
    ) -> Tuple[Optional[RestoreProfile], List[str]]:
        """(profile, reasons it cannot be assigned at all)."""
        content, _ = self._load(source, key)
        result = self._parse(content, allow_builtin=source == BUILTIN)
        if not result.ok:
            return None, [str(result.errors[0])]
        reasons = [i["message"] for i in self._runnable_issues(result.profile)]
        if reasons:
            reasons = ["not runnable: " + "; ".join(sorted(set(reasons)))]
        return result.profile, reasons

    def _device_row(self, session_obj, raw_id, profile) -> Dict[str, Any]:
        device_id = parse_id(raw_id)
        if device_id is None:
            return {
                "device_id": raw_id,
                "status": "invalid",
                "reason": "invalid device id",
            }
        if not self._access(session_obj, device_id):
            return {
                "device_id": device_id,
                "status": "denied",
                "reason": "no access to this device",
            }
        device = self.devices.get_device(device_id)
        if device is None:
            return {
                "device_id": device_id,
                "status": "not_found",
                "reason": "device not found",
            }
        compat = check_compatibility(
            profile, device.driver, device.model, device.os_version
        )
        return {
            "device_id": device_id,
            "hostname": device.hostname,
            "ip": device.ip,
            "status": compat.status,
            "reason": compat.reason,
            "current": self.repo.get_assignment(device_id),
        }

    def preview_assignment(
        self, session_obj: Mapping, device_ids: List[Any], source: str, key: str
    ) -> Dict[str, Any]:
        self._require_role(session_obj)
        if (
            not isinstance(device_ids, (list, tuple))
            or not device_ids
            or len(device_ids) > MAX_BULK_DEVICES
        ):
            raise ServiceError(INVALID, f"Choose 1..{MAX_BULK_DEVICES} devices")
        profile, blockers = self._assignable_profile(source, key)
        rows = (
            [
                self._device_row(session_obj, d, profile)
                for d in dict.fromkeys(device_ids)
            ]
            if profile is not None
            else []
        )
        return {
            "profile": {"source": source, "key": key},
            "blockers": blockers,
            "devices": rows,
            # three groups, as the specification asks
            "compatible": [r for r in rows if r["status"] == COMPATIBLE],
            "incompatible": [r for r in rows if r["status"] == "incompatible"],
            "unverifiable": [r for r in rows if r["status"] == "unverifiable"],
            "refused": [
                r for r in rows if r["status"] in ("denied", "invalid", "not_found")
            ],
            "can_assign": not blockers and any(r["status"] == COMPATIBLE for r in rows),
        }

    def assign(
        self, session_obj: Mapping, device_ids: List[Any], source: str, key: str
    ) -> Dict[str, Any]:
        """Assigns ONLY positively compatible devices; everything is re-checked here."""
        user = self._require_role(session_obj)
        preview = self.preview_assignment(session_obj, device_ids, source, key)
        if preview["blockers"]:
            raise ServiceError(
                INVALID,
                "The profile cannot be assigned: " + "; ".join(preview["blockers"]),
            )
        assigned, skipped = [], []
        for row in preview["devices"]:
            if row["status"] == COMPATIBLE:
                self.repo.set_assignment(row["device_id"], source, key, user)
                assigned.append(row["device_id"])
                self._audit(user, "assign", f"{key}->device:{row['device_id']}")
            else:
                skipped.append(
                    {
                        "device_id": row["device_id"],
                        "reason": row["reason"],
                        "status": row["status"],
                    }
                )
        return {"assigned": assigned, "skipped": skipped}

    def unassign(self, session_obj: Mapping, device_id: Any) -> bool:
        user = self._require_role(session_obj)
        parsed = parse_id(device_id)
        if parsed is None or not self._access(session_obj, parsed):
            raise ServiceError(FORBIDDEN, "You have no access to this device")
        removed = self.repo.delete_assignment(parsed)
        if removed:
            self._audit(user, "unassign", f"device:{parsed}")
        return removed

    def suggest_for_device(
        self, session_obj: Mapping, device_id: Any
    ) -> List[Dict[str, Any]]:
        """Profiles that could be assigned (valid, runnable, compatible). Never assigns."""
        self._require_role(session_obj)
        parsed = parse_id(device_id)
        if parsed is None or not self._access(session_obj, parsed):
            raise ServiceError(FORBIDDEN, "You have no access to this device")
        device = self.devices.get_device(parsed)
        if device is None:
            raise ServiceError(NOT_FOUND, "Device not found")
        offers = []
        for row in self.list_profiles(session_obj):
            if not (row.get("valid") and row.get("runnable")):
                continue
            profile = self._assignable_profile(row["source"], row["key"])[0]
            if (
                profile
                and check_compatibility(
                    profile, device.driver, device.model, device.os_version
                ).allowed
            ):
                offers.append(
                    {"source": row["source"], "key": row["key"], "name": row["name"]}
                )
        return offers

    def device_assignment(
        self, session_obj: Mapping, device_id: Any
    ) -> Optional[Dict[str, Any]]:
        """For the device card: which profile is assigned, if any."""
        self._require_role(session_obj)
        parsed = parse_id(device_id)
        if parsed is None or not self._access(session_obj, parsed):
            raise ServiceError(FORBIDDEN, "You have no access to this device")
        assigned = self.repo.get_assignment(parsed)
        if assigned is None:
            return None
        try:
            content, _ = self._load(*assigned)
        except ServiceError:
            return {"source": assigned[0], "key": assigned[1], "missing": True}
        profile = self._parse(content, allow_builtin=assigned[0] == BUILTIN).profile
        return {
            "source": assigned[0],
            "key": assigned[1],
            "missing": False,
            "name": profile.name if profile else assigned[1],
            "profile_version": profile.profile_version if profile else None,
        }
