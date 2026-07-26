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
    add_rule,
    update_rule,
    delete_rule,
    get_rule_counts_by_profile,
)
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_drivers import get_all_drivers
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
                vendor_model = f'{d["drivers_vendor"] or ""} {d["drivers_model"] or ""}'.strip()
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
                add_rule(pid, rule_name, rule_type, pattern, enabled, order)
                flash("Rule added successfully", "success")
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
                update_rule(rule_id, rule_name, rule_type, pattern, enabled, order)
                flash("Rule updated successfully", "success")
            else:
                flash("Invalid rule data", "danger")

        elif action == "delete_rule":
            rule_id = request.form.get("rule_id", type=int)
            if rule_id:
                delete_rule(rule_id)
                flash("Rule deleted successfully", "success")

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
    driver_labels = {
        p.id: _driver_display_label(p.driver_vendor, custom_drivers_list, standard_drivers)
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
        driver_labels=driver_labels,
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
