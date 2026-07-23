from datetime import datetime, timezone
from app import db, logger
from app.models import (
    ValidationProfile,
    ValidationRule,
    DeviceValidation,
    ValidationResult,
)
from app.modules.dbutils.db_devices import get_device_id
from app.modules.dbutils.db_validation import (
    get_profile_for_device,
    get_profile_by_driver,
    get_profile_rules,
)
from app.modules.validation.engine import ValidationEngine


def run_validation(device_id: int, config: str, timestamp: str = None) -> None:
    """
    Resolve validation profile for a device and run rules against the config.
    Priority: explicit device profile > driver-based profile.
    Wrapped in try/except so it never breaks the backup process.
    """
    try:
        if not config:
            logger.warning(f"No config provided for validation on device {device_id}")
            return

        # 1. Resolve profile: explicit first, then by driver
        profile = get_profile_for_device(device_id)
        if not profile:
            profile = get_profile_by_driver(device_id)

        if not profile:
            logger.info(f"No validation profile found for device {device_id}")
            return

        # 2. Get rules for the profile
        rules = get_profile_rules(profile.id)
        if not rules:
            logger.info(f"No rules found for profile {profile.name}")
            return

        # 3. Create DeviceValidation record
        validation_record = DeviceValidation(
            device_id=device_id,
            profile_id=profile.id,
            status="pending",
            started_at=datetime.now(timezone.utc),
        )
        db.session.add(validation_record)
        db.session.commit()

        # 4. Run engine
        engine = ValidationEngine()
        all_passed = True
        results = []

        for rule in rules:
            if not rule.enabled:
                continue

            result = engine.evaluate_rule(
                {"rule_type": rule.rule_type, "pattern": rule.pattern}, config
            )

            results.append(
                {
                    "rule_id": rule.id,
                    "rule_name": rule.rule_name,
                    "passed": result["passed"],
                    "message": result["message"],
                }
            )

            if not result["passed"]:
                all_passed = False

        # 5. Save results
        for res in results:
            validation_result = ValidationResult(
                device_validation_id=validation_record.id,
                rule_id=res["rule_id"],
                rule_name=res["rule_name"],
                passed=res["passed"],
                message=res["message"],
                checked_at=datetime.now(timezone.utc),
            )
            db.session.add(validation_result)

        # 6. Update status
        validation_record.status = "passed" if all_passed else "failed"
        validation_record.completed_at = datetime.now(timezone.utc)
        db.session.commit()

        logger.info(
            f"Validation completed for device {device_id}: {validation_record.status}"
        )

    except Exception as e:
        logger.error(f"Validation run failed for device {device_id}: {e}")
        # Ensure we don't leave pending records forever
        try:
            last_validation = (
                DeviceValidation.query.filter_by(device_id=device_id, status="pending")
                .order_by(DeviceValidation.started_at.desc())
                .first()
            )
            if last_validation:
                last_validation.status = "error"
                last_validation.error_message = str(e)
                last_validation.completed_at = datetime.now(timezone.utc)
                db.session.commit()
        except Exception as inner_e:
            logger.error(
                f"Failed to update error status for device {device_id}: {inner_e}"
            )
