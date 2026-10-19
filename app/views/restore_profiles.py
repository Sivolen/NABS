"""
Web UI of the Restore Engine, part 1: restore profiles (list, view, copy, edit, import,
export, delete) and their assignment to devices.

The views are thin: every rule (roles, built-in protection, validation, compatibility)
lives in ProfileService and is enforced there, on the server, on every call.
"""

import re
from functools import lru_cache

from flask import (
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app import app, logger
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.restore.profile_service import ProfileService
from app.modules.restore.profiles import SOURCES, BuiltinProfileProvider
from app.modules.restore.schema import MAX_YAML_BYTES
from app.modules.restore.service import (
    CONFLICT,
    FORBIDDEN,
    INVALID,
    NOT_FOUND,
    ServiceError,
)

STATUS = {FORBIDDEN: 403, NOT_FOUND: 404, INVALID: 400, CONFLICT: 409}
SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]")


@lru_cache(maxsize=1)
def _builtin_provider() -> BuiltinProfileProvider:
    return BuiltinProfileProvider()


def _profile_service() -> ProfileService:
    """One service per request; the tests replace this function."""
    from app.modules.restore.db_store import DbDeviceProvider, DbProfileRepo

    return ProfileService(_builtin_provider(), DbProfileRepo(), DbDeviceProvider())


def _devices_for_user():
    """The user's devices, each with its platform (for custom-driver devices the
    connection_driver column holds a driver id, which says nothing to a person)."""
    from app.modules.dbutils.db_devices import get_devices_by_rights
    from app.modules.restore.db_store import device_platforms

    devices = get_devices_by_rights(user_id=session.get("user_id")) or []
    platforms = device_platforms([d["device_id"] for d in devices])
    return [dict(d, platform=platforms.get(d["device_id"])) for d in devices]


def _json_error(error: ServiceError):
    return (
        jsonify({"error": error.message, "details": error.details}),
        STATUS.get(error.code, 400),
    )


def _flash_error(error: ServiceError) -> None:
    flash(error.message, "warning" if error.code == FORBIDDEN else "danger")


def _read_upload(field: str):
    """Text of an uploaded file, limited in size; (text, error message)."""
    upload = request.files.get(field)
    if upload is None or not upload.filename:
        return None, "Choose a YAML file"
    raw = upload.read(MAX_YAML_BYTES + 1)
    if len(raw) > MAX_YAML_BYTES:
        return None, f"The file is larger than {MAX_YAML_BYTES} bytes"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "The file is not valid UTF-8 text"


def _render(service, source=None, key=None, editor_text=None, errors=None, status=200):
    """The page. The detail panel shows profile (source, key); editor_text keeps what
    the user typed after a refused save so that no work is lost."""
    args = request.args
    rows = service.list_profiles(
        session,
        query=args.get("q", ""),
        kind=args.get("kind", ""),
        vendor=args.get("vendor", ""),
        sort=args.get("sort", "name"),
    )
    detail = None
    assignment_devices = []
    if source in SOURCES and key:
        try:
            detail = service.get_profile(session, source, key)
            assignment_devices = _devices_for_user()
        except ServiceError as error:
            _flash_error(error)
    response = make_response(
        render_template(
            "restore_profiles.html",
            profiles=rows,
            detail=detail,
            editor_text=editor_text
            if editor_text is not None
            else (detail or {}).get("content"),
            errors=errors or [],
            outdated=[r["key"] for r in rows if r.get("origin_outdated")],
            assignment_devices=assignment_devices,
            filters={k: args.get(k, "") for k in ("q", "kind", "vendor", "sort")},
            vendors=sorted({r["vendor"] for r in rows if r.get("vendor")}),
            restore_profiles_menu_active=True,
            settings_menu_active=True,
        )
    )
    response.status_code = status
    return response


@app.route("/restore_profiles/", methods=["GET", "POST"])
@check_auth
def restore_profiles():
    service = _profile_service()
    source = request.values.get("source")
    key = request.values.get("key")

    if request.method == "GET":
        try:
            return _render(service, source, key)
        except ServiceError as error:  # the list itself needs the admin role
            _flash_error(error)
            return redirect(url_for("devices"))

    action = request.form.get("action")
    text = request.form.get("yaml_text")
    try:
        if action == "copy":
            view = service.copy_profile(
                session,
                source,
                key,
                new_key=request.form.get("new_key") or None,
                new_name=request.form.get("new_name") or None,
            )
            flash(f"Created the copy '{view['key']}'. Edit it here.", "success")
            return redirect(url_for("restore_profiles", source="user", key=view["key"]))
        if action == "create":
            view = service.create_profile(session, text)
            flash("Profile created", "success")
            return redirect(url_for("restore_profiles", source="user", key=view["key"]))
        if action == "update":
            view = service.update_profile(
                session, source, key, text, request.form.get("expected_sha256", "")
            )
            flash(f"Saved (version {view['profile_version']})", "success")
            return redirect(url_for("restore_profiles", source="user", key=key))
        if action == "delete":
            service.delete_profile(session, source, key)
            flash("Profile deleted", "success")
            return redirect(url_for("restore_profiles"))
        if action == "import":
            imported, problem = _read_upload("import_file")
            if problem:
                flash(problem, "danger")
                return redirect(url_for("restore_profiles"))
            view = service.import_profile(
                session,
                imported,
                overwrite=request.form.get("overwrite") == "on",
                new_key=request.form.get("new_key") or None,
            )
            flash("Imported. The profile is not assigned to any device.", "success")
            return redirect(url_for("restore_profiles", source="user", key=view["key"]))
        if action == "unassign":
            service.unassign(session, request.form.get("device_id"))
            flash("Profile unassigned", "success")
            return redirect(url_for("restore_profiles", source=source, key=key))
        flash("Unknown action", "danger")
        return redirect(url_for("restore_profiles"))
    except ServiceError as error:
        if error.code == FORBIDDEN:
            _flash_error(error)
            return redirect(url_for("devices"))
        _flash_error(error)
        if action in ("update", "create") and text is not None:
            # keep the editor open with the user's text and the problems found
            shown = (source, key) if action == "update" else (None, None)
            return _render(
                service,
                *shown,
                editor_text=text,
                errors=error.details,
                status=STATUS.get(error.code, 400),
            )
        return redirect(url_for("restore_profiles", source=source, key=key))


@app.route("/restore_profiles/export/<source>/<key>", methods=["GET"])
@check_auth
def export_restore_profile(source, key):
    try:
        filename, content = _profile_service().export_profile(session, source, key)
    except ServiceError as error:
        _flash_error(error)
        return redirect(url_for("restore_profiles"))
    response = make_response(content)
    response.headers["Content-Type"] = "text/yaml; charset=utf-8"
    response.headers[
        "Content-Disposition"
    ] = f"attachment; filename={SAFE_NAME.sub('_', filename)}"
    return response


def _json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@app.route("/api/restore_profiles/validate", methods=["POST"])
@check_auth
def api_restore_profile_validate():
    try:
        return jsonify(
            _profile_service().validate_text(session, _json_body().get("text"))
        )
    except ServiceError as error:
        return _json_error(error)


@app.route("/api/restore_profiles/import_preview", methods=["POST"])
@check_auth
def api_restore_profile_import_preview():
    body = _json_body()
    try:
        return jsonify(
            _profile_service().import_profile(
                session,
                body.get("text"),
                preview=True,
                overwrite=bool(body.get("overwrite")),
                new_key=body.get("new_key") or None,
            )
        )
    except ServiceError as error:
        return _json_error(error)


@app.route("/api/restore_profiles/assign_preview", methods=["POST"])
@check_auth
def api_restore_profile_assign_preview():
    body = _json_body()
    try:
        return jsonify(
            _profile_service().preview_assignment(
                session, body.get("device_ids"), body.get("source"), body.get("key")
            )
        )
    except ServiceError as error:
        return _json_error(error)


@app.route("/api/restore_profiles/assign", methods=["POST"])
@check_auth
def api_restore_profile_assign():
    body = _json_body()
    try:
        result = _profile_service().assign(
            session, body.get("device_ids"), body.get("source"), body.get("key")
        )
    except ServiceError as error:
        return _json_error(error)
    logger.info(
        f"User: {session.get('user')} assigned restore profile {body.get('key')} to"
        f" devices {result['assigned']}"
    )
    return jsonify(result)


@app.route("/api/restore_profiles/device/<device_id>", methods=["GET"])
@check_auth
def api_restore_profile_device(device_id):
    """For the device card: the assigned profile and the profiles that could be assigned."""
    service = _profile_service()
    try:
        return jsonify(
            {
                "assigned": service.device_assignment(session, device_id),
                "suggestions": service.suggest_for_device(session, device_id),
            }
        )
    except ServiceError as error:
        return _json_error(error)
