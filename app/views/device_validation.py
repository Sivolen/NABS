from flask import render_template, request, jsonify, redirect, url_for, flash, session
from app import app, logger, db
from app.modules.dbutils.db_validation import (
    get_device_validation_status,
    get_device_validation_history,
    disable_validation,
    enable_validation,
)
from app.modules.validation.runner import run_validation
from app.modules.dbutils.db_utils import get_last_config_for_device
from app.modules.auth.auth_users_ldap import check_auth
from app.models import (
    DeviceValidation,
    ValidationResult,
    Devices,
    ValidationProfile,
    ValidationRule,
)
from datetime import datetime, timezone


@app.route("/validation_report/<device_validation_id>", methods=["GET"])
@check_auth
def validation_report(device_validation_id):
    """Display validation report for a specific run."""
    validation_record = DeviceValidation.query.filter_by(
        id=device_validation_id
    ).first()
    if not validation_record:
        flash("Validation record not found", "danger")
        return redirect(url_for("devices"))

    results = (
        ValidationResult.query.filter_by(device_validation_id=device_validation_id)
        .order_by(ValidationResult.checked_at.desc())
        .all()
    )

    # ValidationResult only stores the rule's name/pass-fail/message, not what
    # was actually being checked - pull that from the rule itself (falls back
    # gracefully if the rule was edited or deleted since this run happened).
    rule_ids = [r.rule_id for r in results if r.rule_id]
    rules_by_id = (
        {
            rule.id: rule
            for rule in ValidationRule.query.filter(
                ValidationRule.id.in_(rule_ids)
            ).all()
        }
        if rule_ids
        else {}
    )
    for r in results:
        rule = rules_by_id.get(r.rule_id)
        r.rule_type_display = rule.rule_type if rule else None
        r.rule_pattern_display = (
            rule.pattern if rule else "(rule was since edited or deleted)"
        )

    # Devices has a composite primary key (id, device_ip), so .query.get()
    # can't be used here - it requires a value for every PK column.
    device = Devices.query.filter_by(id=validation_record.device_id).first()

    # DeviceValidation has no ORM relationship to ValidationProfile (only the
    # raw profile_id FK column), so the profile name has to be looked up
    # explicitly rather than via validation.profile.name.
    profile = None
    if validation_record.profile_id:
        profile = ValidationProfile.query.filter_by(
            id=validation_record.profile_id
        ).first()

    return render_template(
        "validation_report.html",
        validation=validation_record,
        results=results,
        device=device,
        profile=profile,
    )


@app.route("/api/validation_history/<device_id>", methods=["GET"])
@check_auth
def api_validation_history(device_id):
    """AJAX endpoint: recent validation runs for a device."""
    try:
        device_id_int = int(device_id)
    except ValueError:
        return jsonify({"error": "Invalid device_id"}), 400

    history = get_device_validation_history(device_id_int, limit=20)
    return jsonify(
        {
            "history": [
                {
                    "id": h.id,
                    "status": h.status,
                    "started_at": h.started_at.strftime("%Y-%m-%d %H:%M")
                    if h.started_at
                    else None,
                }
                for h in history
            ]
        }
    )


@app.route("/api/validation_status/<device_id>", methods=["GET"])
@check_auth
def api_validation_status(device_id):
    """AJAX endpoint to get validation status for a device."""
    status = get_device_validation_status(device_id)
    if status:
        failed_rules = []
        if status.status == "failed":
            failed_results = ValidationResult.query.filter_by(
                device_validation_id=status.id, passed=False
            ).all()
            failed_rules = [
                {"rule_name": r.rule_name, "message": r.message} for r in failed_results
            ]
        return jsonify(
            {
                "status": status.status,
                "completed_at": status.completed_at.isoformat()
                if status.completed_at
                else None,
                "validation_id": status.id,
                "failed_rules": failed_rules,
            }
        )
    return jsonify({"status": "none"})


@app.route("/api/validation_run/<device_id>", methods=["POST"])
@check_auth
def api_validation_run(device_id):
    """AJAX endpoint to trigger validation on a device using last saved config."""
    try:
        # Get last config
        last_config_data = get_last_config_for_device(device_id=device_id)
        if not last_config_data or not last_config_data.get("last_config"):
            return jsonify({"error": "No configuration found for this device"}), 400

        config = last_config_data["last_config"]

        # Run validation
        run_validation(
            device_id=device_id,
            config=config,
            timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        )

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Validation run failed for device {device_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/validation_disable/<device_id>", methods=["POST"])
@check_auth
def api_validation_disable(device_id):
    """AJAX endpoint to disable validation for a device."""
    try:
        user = session.get("user", "system")
        reason = request.form.get("reason", "Disabled by user")
        disable_validation(device_id, user, reason)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/validation_enable/<device_id>", methods=["POST"])
@check_auth
def api_validation_enable(device_id):
    """AJAX endpoint to enable validation for a device."""
    try:
        enable_validation(device_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
