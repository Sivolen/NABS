from app import db
from app.models import (
    ValidationProfile,
    ValidationRule,
    DeviceValidation,
    ValidationResult,
    Devices,
    CustomDrivers,
)
from typing import List, Optional
from datetime import datetime, timezone
from sqlalchemy import func


def get_validation_profiles() -> List[ValidationProfile]:
    """Get all validation profiles."""
    return ValidationProfile.query.order_by(ValidationProfile.created_at.desc()).all()


def get_rule_counts_by_profile() -> dict:
    """Rule count per profile_id, for the profile list sidebar badge - one
    query instead of counting per-profile (which previously only worked for
    whichever profile happened to be open, showing '?' for all others)."""
    rows = (
        db.session.query(ValidationRule.profile_id, func.count(ValidationRule.id))
        .group_by(ValidationRule.profile_id)
        .all()
    )
    return {profile_id: count for profile_id, count in rows}


def get_profile_by_id(profile_id: int) -> Optional[ValidationProfile]:
    """Get a profile by ID."""
    return ValidationProfile.query.filter_by(id=profile_id).first()


def create_validation_profile(
    name: str, driver_vendor: str, description: str
) -> ValidationProfile:
    """Create a new validation profile."""
    profile = ValidationProfile(
        name=name, driver_vendor=driver_vendor, description=description
    )
    db.session.add(profile)
    db.session.commit()
    return profile


def update_validation_profile(
    profile_id: int, name: str, driver_vendor: str, description: str
) -> Optional[ValidationProfile]:
    """Update an existing profile."""
    profile = get_profile_by_id(profile_id)
    if profile:
        profile.name = name
        profile.driver_vendor = driver_vendor
        profile.description = description
        db.session.commit()
    return profile


def delete_validation_profile(profile_id: int) -> bool:
    """Delete a profile and its rules."""
    profile = get_profile_by_id(profile_id)
    if profile:
        # Delete rules first
        ValidationRule.query.filter_by(profile_id=profile_id).delete()
        # Then delete profile
        db.session.delete(profile)
        db.session.commit()
        return True
    return False


def get_profile_rules(profile_id: int) -> List[ValidationRule]:
    """Get all rules for a profile, ordered."""
    return (
        ValidationRule.query.filter_by(profile_id=profile_id)
        .order_by(ValidationRule.order)
        .all()
    )


def add_rule(
    profile_id: int,
    rule_name: str,
    rule_type: str,
    pattern: str,
    enabled: bool,
    order: int,
) -> ValidationRule:
    """Add a new rule to a profile."""
    rule = ValidationRule(
        profile_id=profile_id,
        rule_name=rule_name,
        rule_type=rule_type,
        pattern=pattern,
        enabled=enabled,
        order=order,
    )
    db.session.add(rule)
    db.session.commit()
    return rule


def update_rule(
    rule_id: int,
    rule_name: str,
    rule_type: str,
    pattern: str,
    enabled: bool,
    order: int,
) -> Optional[ValidationRule]:
    """Update an existing rule."""
    rule = ValidationRule.query.filter_by(id=rule_id).first()
    if rule:
        rule.rule_name = rule_name
        rule.rule_type = rule_type
        rule.pattern = pattern
        rule.enabled = enabled
        rule.order = order
        db.session.commit()
    return rule


def delete_rule(rule_id: int) -> bool:
    """Delete a rule."""
    rule = ValidationRule.query.filter_by(id=rule_id).first()
    if rule:
        db.session.delete(rule)
        db.session.commit()
        return True
    return False


def get_device_validation_status(device_id: int) -> Optional[DeviceValidation]:
    """Get the latest validation status for a device."""
    return (
        DeviceValidation.query.filter_by(device_id=device_id)
        .order_by(DeviceValidation.started_at.desc())
        .first()
    )


def get_validation_results(device_validation_id: int) -> List[ValidationResult]:
    """Get all results for a specific validation run."""
    return (
        ValidationResult.query.filter_by(device_validation_id=device_validation_id)
        .order_by(ValidationResult.checked_at.desc())
        .all()
    )


def get_profile_by_driver(device_id: int) -> Optional[ValidationProfile]:
    """
    Resolve a validation profile for a device based on its driver.
    """
    device = Devices.query.filter_by(id=device_id).first()
    if not device:
        return None

    if device.custom_drivers_switch and device.connection_driver:
        # NOTE: when custom_drivers_switch is on, connection_driver actually
        # holds the CustomDrivers.id (as a string), not a name - see
        # get_custom_driver_id() in db_devices.py / how the platform select
        # is populated in devices.html. Devices.custom_driver is not used
        # for this anywhere else in the app.
        #
        # Match by id, not by drivers_name: CustomDrivers.drivers_name has
        # no uniqueness constraint, so two different custom drivers (e.g.
        # different vendor/model/commands) can share the same name - matching
        # by name alone made profile selection ambiguous (see 'custom:' below,
        # which mirrors the value used by the profile's driver <select>).
        try:
            driver = f"custom:{int(device.connection_driver)}"
        except (TypeError, ValueError):
            driver = None
    else:
        driver = device.connection_driver

    if not driver:
        return None

    # Try to find a profile that matches this driver
    return ValidationProfile.query.filter_by(driver_vendor=driver).first()


def set_device_validation_profile(device_id: int, profile_id: int) -> bool:
    """
    Explicitly link a device to a validation profile.
    """
    device = Devices.query.filter_by(id=device_id).first()
    if device:
        device.validation_profile_id = profile_id
        db.session.commit()
        return True
    return False


def disable_validation(device_id: int, by: str, reason: str) -> bool:
    """Disable validation for a device."""
    device = Devices.query.filter_by(id=device_id).first()
    if device:
        device.validation_enabled = False
        device.validation_disabled_by = by
        device.validation_disabled_date = datetime.now(timezone.utc)
        device.validation_disabled_reason = reason
        db.session.commit()
        return True
    return False


def enable_validation(device_id: int) -> bool:
    """Enable validation for a device."""
    device = Devices.query.filter_by(id=device_id).first()
    if device:
        device.validation_enabled = True
        device.validation_disabled_by = None
        device.validation_disabled_date = None
        device.validation_disabled_reason = None
        db.session.commit()
        return True
    return False


def get_all_validation_profiles() -> List[ValidationProfile]:
    """Get all validation profiles for dropdown selector."""
    return ValidationProfile.query.order_by(ValidationProfile.name).all()


def get_profile_for_device(device_id: int) -> Optional[ValidationProfile]:
    """Get explicitly assigned validation profile for a device."""
    device = Devices.query.filter_by(id=device_id).first()
    if device and device.validation_profile_id:
        return ValidationProfile.query.filter_by(
            id=device.validation_profile_id
        ).first()
    return None


def get_validation_dashboard_summary() -> dict:
    """
    Aggregate counts of the LATEST validation run per device, for the
    Dashboard card. A device can have many DeviceValidation rows over time -
    only the most recent one per device counts here.
    """
    latest_ids_subq = (
        db.session.query(
            DeviceValidation.device_id,
            func.max(DeviceValidation.id).label("max_id"),
        )
        .group_by(DeviceValidation.device_id)
        .subquery()
    )
    latest_runs = (
        db.session.query(DeviceValidation)
        .join(latest_ids_subq, DeviceValidation.id == latest_ids_subq.c.max_id)
        .all()
    )

    summary = {"passed": 0, "failed": 0, "error": 0, "pending": 0}
    for run in latest_runs:
        summary[run.status] = summary.get(run.status, 0) + 1

    total_devices = Devices.query.count()
    checked = len(latest_runs)
    summary["total_devices"] = total_devices
    summary["checked"] = checked
    summary["not_checked"] = max(0, total_devices - checked)
    return summary
