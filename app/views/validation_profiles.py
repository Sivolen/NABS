from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    make_response,
    jsonify,
)
import json
from app import app, logger
from app.modules.dbutils.db_validation import (
    get_validation_profiles,
    get_profile_by_id,
    create_validation_profile,
    update_validation_profile,
    delete_validation_profile,
    get_profile_rules,
    get_rule_by_id,
    add_rule,
    update_rule,
    delete_rule,
    move_rule,
    get_rule_counts_by_profile,
    get_device_counts_by_profile,
)
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_drivers import get_all_drivers
from app.modules.validation.engine import validate_pattern_format, ValidationEngine
from config import drivers as standard_drivers


def _driver_display_label(driver_vendor, custom_drivers_list, standard_drivers_list):
    """Human-readable label for a profile's stored driver_vendor value,
    resolving 'custom:<id>' back to a name (see get_profile_by_driver for
    why matching is done by id and not by the non-unique drivers_name)."""
    if not driver_vendor:
        return "Any Driver"
    if driver_vendor.startswith("custom:"):
        try:
            custom_id = int(driver_vendor.split(":", 1)[1])
        except (IndexError, ValueError):
            return driver_vendor
        for d in custom_drivers_list:
            if d["custom_drivers_id"] == custom_id:
                vendor_model = (
                    f'{d["drivers_vendor"] or ""} {d["drivers_model"] or ""}'.strip()
                )
                return f'{vendor_model or d["drivers_name"]} (custom)'
        return f"custom driver #{custom_id} (deleted)"
    for d in standard_drivers_list:
        if d["driver"] == driver_vendor:
            return f'{d["name"]} ({d["driver"]})'
    return driver_vendor


@app.route("/validation_profiles/", methods=["POST", "GET"])
@check_auth
def validation_profiles():
    """
    Admin view for managing validation profiles.
    If ID is in URL, show profile detail with rules.
    """
    validation_profiles_menu_active: bool = True
    settings_menu_active: bool = True
    profile_id = request.args.get("profile_id", type=int)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create_profile":
            name = request.form.get("name")
            driver_vendor = request.form.get("driver_vendor")
            description = request.form.get("description", "")
            if not name:
                flash("Profile name is required", "danger")
            else:
                create_validation_profile(name, driver_vendor, description)
                flash("Profile created successfully", "success")
                return redirect(url_for("validation_profiles", profile_id=None))

        elif action == "update_profile":
            pid = request.form.get("profile_id", type=int)
            name = request.form.get("name")
            driver_vendor = request.form.get("driver_vendor")
            description = request.form.get("description", "")
            if pid and name:
                update_validation_profile(pid, name, driver_vendor, description)
                flash("Profile updated successfully", "success")
            else:
                flash("Invalid profile data", "danger")

        elif action == "delete_profile":
            pid = request.form.get("profile_id", type=int)
            if pid:
                delete_validation_profile(pid)
                flash("Profile deleted successfully", "success")
            return redirect(url_for("validation_profiles", profile_id=None))

        elif action == "add_rule":
            pid = request.form.get("profile_id", type=int)
            rule_name = request.form.get("rule_name")
            rule_type = request.form.get("rule_type")
            pattern = request.form.get("pattern", "")
            enabled = request.form.get("enabled") == "on"
            order = int(request.form.get("order", 0))

            if pid and rule_name and rule_type:
                try:
                    add_rule(pid, rule_name, rule_type, pattern, enabled, order)
                    flash("Rule added successfully", "success")
                except ValueError as e:
                    flash(f"Invalid rule: {str(e)}", "danger")
            else:
                flash("Invalid rule data", "danger")

        elif action == "update_rule":
            rule_id = request.form.get("rule_id", type=int)
            rule_name = request.form.get("rule_name")
            rule_type = request.form.get("rule_type")
            pattern = request.form.get("pattern", "")
            enabled = request.form.get("enabled") == "on"
            order = int(request.form.get("order", 0))

            if rule_id and rule_name and rule_type:
                try:
                    update_rule(rule_id, rule_name, rule_type, pattern, enabled, order)
                    flash("Rule updated successfully", "success")
                except ValueError as e:
                    flash(f"Invalid rule: {str(e)}", "danger")
            else:
                flash("Invalid rule data", "danger")

        elif action == "delete_rule":
            rule_id = request.form.get("rule_id", type=int)
            if rule_id:
                delete_rule(rule_id)
                flash("Rule deleted successfully", "success")

        elif action == "move_rule":
            rule_id = request.form.get("rule_id", type=int)
            direction = request.form.get("direction")
            if rule_id and direction in ("up", "down"):
                move_rule(rule_id, direction)

        return redirect(url_for("validation_profiles", profile_id=profile_id))

    # GET request
    profiles = get_validation_profiles()
    profile = None
    rules = []

    if profile_id:
        profile = get_profile_by_id(profile_id)
        if profile:
            rules = get_profile_rules(profile_id)

    custom_drivers_list = get_all_drivers()
    device_counts = get_device_counts_by_profile()
    driver_labels = {
        p.id: _driver_display_label(
            p.driver_vendor, custom_drivers_list, standard_drivers
        )
        for p in profiles
    }
    if profile:
        driver_labels[profile.id] = _driver_display_label(
            profile.driver_vendor, custom_drivers_list, standard_drivers
        )

    return render_template(
        "validation_profiles.html",
        profiles=profiles,
        profile=profile,
        rules=rules,
        active_profile_id=profile_id,
        standard_drivers=standard_drivers,
        custom_drivers=custom_drivers_list,
        rule_counts=get_rule_counts_by_profile(),
        device_counts=device_counts,
        driver_labels=driver_labels,
        validation_profiles_menu_active=validation_profiles_menu_active,
        settings_menu_active=settings_menu_active,
    )


@app.route("/validation_profiles/export/<int:profile_id>", methods=["GET"])
@check_auth
def export_validation_profile(profile_id):
    """Download a profile + its rules as a JSON file."""
    profile = get_profile_by_id(profile_id)
    if not profile:
        flash("Profile not found", "danger")
        return redirect(url_for("validation_profiles"))

    rules = get_profile_rules(profile_id)
    data = {
        "name": profile.name,
        "description": profile.description,
        "driver_vendor": profile.driver_vendor,
        "rules": [
            {
                "rule_name": r.rule_name,
                "rule_type": r.rule_type,
                "pattern": r.pattern,
                "enabled": r.enabled,
                "order": r.order,
            }
            for r in rules
        ],
    }
    response = make_response(json.dumps(data, indent=2, ensure_ascii=False))
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    safe_name = (
        "".join(c if c.isalnum() or c in "-_" else "_" for c in profile.name)
        or "profile"
    )
    response.headers[
        "Content-Disposition"
    ] = f"attachment; filename=validation_profile_{safe_name}.json"
    return response


@app.route("/validation_profiles/test_rule", methods=["POST"])
@check_auth
def test_rule():
    """AJAX: try a rule_type/pattern against a pasted sample config, without
    saving anything - same engine used for real validation runs."""
    rule_type = request.form.get("rule_type", "")
    pattern = request.form.get("pattern", "")
    test_config = request.form.get("test_config", "")

    if not test_config.strip():
        return (
            jsonify(
                {"passed": False, "message": "Paste a sample config to test against"}
            ),
            400,
        )

    format_error = validate_pattern_format(rule_type, pattern)
    if format_error:
        return jsonify({"passed": False, "message": format_error}), 400

    engine = ValidationEngine()
    result = engine.evaluate_rule(
        {"rule_type": rule_type, "pattern": pattern}, test_config
    )
    return jsonify(result)


@app.route("/validation_profiles/export_rule/<int:rule_id>", methods=["GET"])
@check_auth
def export_rule(rule_id):
    """Download a single rule as a JSON file, to share/reuse in another profile."""
    rule = get_rule_by_id(rule_id)
    if not rule:
        flash("Rule not found", "danger")
        return redirect(url_for("validation_profiles"))

    data = {
        "rule_name": rule.rule_name,
        "rule_type": rule.rule_type,
        "pattern": rule.pattern,
        "enabled": rule.enabled,
        "order": rule.order,
    }
    response = make_response(json.dumps(data, indent=2, ensure_ascii=False))
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    safe_name = (
        "".join(c if c.isalnum() or c in "-_" else "_" for c in rule.rule_name)
        or "rule"
    )
    response.headers[
        "Content-Disposition"
    ] = f"attachment; filename=validation_rule_{safe_name}.json"
    return response


@app.route("/validation_profiles/import_rule", methods=["POST"])
@check_auth
def import_rule():
    """Add a rule to a profile from a previously exported single-rule JSON file."""
    profile_id = request.form.get("profile_id", type=int)
    file = request.files.get("import_rule_file")

    if not profile_id or not get_profile_by_id(profile_id):
        flash("No profile selected to import the rule into", "danger")
        return redirect(url_for("validation_profiles"))

    if not file or not file.filename:
        flash("No file selected", "danger")
        return redirect(url_for("validation_profiles", profile_id=profile_id))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except Exception as e:
        flash(f"Invalid JSON file: {e}", "danger")
        return redirect(url_for("validation_profiles", profile_id=profile_id))

    rule_name = data.get("rule_name")
    rule_type = data.get("rule_type")
    pattern = data.get("pattern", "")
    if not rule_name or not rule_type:
        flash("Imported file is missing rule_name/rule_type", "danger")
        return redirect(url_for("validation_profiles", profile_id=profile_id))

    error = validate_pattern_format(rule_type, pattern)
    if error:
        flash(f"Rule not imported: {error}", "danger")
        return redirect(url_for("validation_profiles", profile_id=profile_id))

    add_rule(
        profile_id=profile_id,
        rule_name=rule_name,
        rule_type=rule_type,
        pattern=pattern,
        enabled=data.get("enabled", True),
        order=data.get("order", 0),
    )
    flash(f'Rule "{rule_name}" imported successfully', "success")
    return redirect(url_for("validation_profiles", profile_id=profile_id))


@app.route("/validation_profiles/import", methods=["POST"])
@check_auth
def import_validation_profile():
    """Create a new profile (+ its rules) from a previously exported JSON file."""
    file = request.files.get("import_file")
    if not file or not file.filename:
        flash("No file selected", "danger")
        return redirect(url_for("validation_profiles"))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except Exception as e:
        flash(f"Invalid JSON file: {e}", "danger")
        return redirect(url_for("validation_profiles"))

    name = data.get("name")
    if not name:
        flash('Imported file is missing the profile "name" field', "danger")
        return redirect(url_for("validation_profiles"))

    new_profile = create_validation_profile(
        name=name,
        driver_vendor=data.get("driver_vendor"),
        description=data.get("description", ""),
    )

    imported_count = 0
    for r in data.get("rules", []):
        rule_name = r.get("rule_name")
        rule_type = r.get("rule_type")
        if rule_name and rule_type:
            add_rule(
                profile_id=new_profile.id,
                rule_name=rule_name,
                rule_type=rule_type,
                pattern=r.get("pattern", ""),
                enabled=r.get("enabled", True),
                order=r.get("order", 0),
            )
            imported_count += 1

    flash(f'Imported profile "{name}" with {imported_count} rule(s)', "success")
    return redirect(url_for("validation_profiles", profile_id=new_profile.id))
