"""
Web UI of the Restore Engine, part 2: restoring a configuration.

Flow: pick a stored configuration -> /restore/new (nothing is created yet) -> "Run
precheck" creates the job and asks the restore worker for the precheck -> the job page
shows checks, warnings and the diff -> the user explicitly confirms (bound to what was
shown) -> the worker executes. The web process NEVER connects to a device: it only reads
and writes the database.
"""

import secrets

from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app import app, logger
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.restore import states as st
from app.modules.restore.profile_service import ProfileService
from app.modules.restore.profiles import SOURCES
from app.modules.restore.service import (
    CONFLICT,
    FORBIDDEN,
    INVALID,
    NOT_FOUND,
    RestoreService,
    ServiceError,
)

STATUS = {FORBIDDEN: 403, NOT_FOUND: 404, INVALID: 400, CONFLICT: 409}


def _services():
    """(RestoreService, ProfileService) for one request; the tests replace this."""
    from app.modules.restore.db_store import (
        DbConfigStore,
        DbDeviceProvider,
        DbJobStore,
        DbProfileRepo,
    )
    from app.modules.restore.engine import RestoreEngine
    from app.modules.restore.profiles import CompositeProfileProvider
    from app.views.restore_profiles import _builtin_provider

    store, configs, devices, repo = (
        DbJobStore(),
        DbConfigStore(),
        DbDeviceProvider(),
        DbProfileRepo(),
    )
    builtin = _builtin_provider()
    # the web process only confirms and cancels: its engine has NO adapters, so it can
    # never open a connection to a device
    engine = RestoreEngine(store, configs, devices, lambda adapter_type: None)
    restore = RestoreService(
        store, configs, devices, CompositeProfileProvider(builtin, repo), repo, engine
    )
    return restore, ProfileService(builtin, repo, devices)


def _fail(error: ServiceError, to_devices: bool = False):
    flash(error.message, "warning" if error.code == FORBIDDEN else "danger")
    return (
        redirect(url_for("devices")) if to_devices or error.code == FORBIDDEN else None
    )


def _json_error(error: ServiceError):
    return jsonify({"error": error.message}), STATUS.get(error.code, 400)


# ---------------------------------------------------------------- start a restore
@app.route("/restore/new", methods=["GET", "POST"])
@check_auth
def restore_new():
    restore, profile_service = _services()
    source = request.values
    try:
        if request.method == "POST":
            return _create_and_request_precheck(restore)
        page = restore.prepare_new(
            session, source.get("device_id"), source.get("config_id")
        )
        offers = profile_service.suggest_for_device(session, page["device"]["id"])
    except ServiceError as error:
        if request.method == "POST" and error.code != FORBIDDEN:
            # a problem with the submitted choice: back to the form, with the reason
            flash(error.message, "danger")
            return redirect(
                url_for(
                    "restore_new",
                    device_id=request.form.get("device_id", ""),
                    config_id=request.form.get("config_id", ""),
                )
            )
        return _fail(error, to_devices=True)

    assigned = page["assigned"]
    choices = []
    seen = set()
    for item in (
        [
            {
                "source": assigned[0],
                "key": assigned[1],
                "name": f"{assigned[1]} (assigned)",
            }
        ]
        if assigned
        else []
    ) + offers:
        ref = (item["source"], item["key"])
        if ref not in seen:
            seen.add(ref)
            choices.append(item)
    return render_template(
        "restore_new.html",
        page=page,
        choices=choices,
        assigned=assigned,
        token=secrets.token_urlsafe(
            24
        ),  # 32 chars; a repeated POST reuses the same job
        restore_profiles_menu_active=False,
    )


def _create_and_request_precheck(restore: RestoreService):
    profile_ref = None
    chosen = (request.form.get("profile") or "").strip()
    if chosen:
        source, _, key = chosen.partition(":")
        if source not in SOURCES or not key:
            raise ServiceError(INVALID, "Invalid profile choice")
        profile_ref = {"source": source, "key": key}
    job, created = restore.create_job(
        session,
        request.form.get("device_id"),
        request.form.get("config_id"),
        request.form.get("client_token", ""),
        profile_ref,
    )
    if created:
        logger.info(
            f"User: {session.get('user')} created restore job {job.id} for device"
            f" {job.device_id} (config {job.target_config_id}, profile {job.profile_key})"
        )
    if job.status == st.CREATED:
        try:
            restore.request_precheck(session, job.id)
        except ServiceError as error:
            if (
                error.code != CONFLICT
            ):  # a repeated request: the precheck is already on its way
                raise
    return redirect(url_for("restore_job", job_id=job.id))


# --------------------------------------------------------------------- job pages
@app.route("/restore/job/<job_id>", methods=["GET"])
@check_auth
def restore_job(job_id):
    restore, _profiles = _services()
    try:
        view = restore.get_job_view(session, job_id)
    except ServiceError as error:
        return _fail(error, to_devices=True)
    device = restore.devices.get_device(view["device_id"])
    target = restore.configs.get_config(view["target_config_id"])
    return render_template(
        "restore_job.html",
        job=view,
        device=device,
        target=target,
        precheck=view.get("precheck") or {},
        events=view["events"],
        restore_profiles_menu_active=False,
    )


@app.route("/api/restore/job/<job_id>", methods=["GET"])
@check_auth
def api_restore_job(job_id):
    """Polled by the job page; the same authorization as the page."""
    restore, _profiles = _services()
    try:
        view = restore.get_job_view(session, job_id)
    except ServiceError as error:
        return _json_error(error)
    return jsonify(
        {
            "id": view["id"],
            "status": view["status"],
            "status_label": view["status_label"],
            "terminal": view["terminal"],
            "stage": view["stage"],
            "events": len(view["events"]),
        }
    )


def _job_action(job_id, action):
    restore, _profiles = _services()
    try:
        if action == "confirm":
            if request.form.get("acknowledge") != "on":
                raise ServiceError(
                    INVALID,
                    "Tick the box to confirm that you have read the checks and the diff",
                )
            restore.confirm(
                session,
                job_id,
                request.form.get("fingerprint", ""),
                request.form.get("confirm_name"),
            )
            logger.info(f"User: {session.get('user')} confirmed restore job {job_id}")
            flash("Confirmed. The restore will start shortly.", "success")
        elif action == "cancel":
            restore.cancel(session, job_id)
            logger.info(f"User: {session.get('user')} cancelled restore job {job_id}")
            flash("The restore was cancelled. Nothing was changed.", "info")
        elif action == "recheck":
            restore.request_precheck(session, job_id)
            flash("A new precheck was requested. Earlier confirmation is void.", "info")
        elif action == "resolve":
            if request.form.get("acknowledge") != "on":
                raise ServiceError(
                    INVALID,
                    "Confirm that you inspected the device through console or out-of-band access",
                )
            job = restore.resolve_unknown(
                session,
                job_id,
                request.form.get("resolution", ""),
                request.form.get("inspection_note", ""),
                request.form.get("confirm_name", ""),
            )
            if job.status == st.RESOLVED_MANUAL:
                flash(
                    "Manual resolution recorded. The job is closed and its configuration copies may now follow retention policy.",
                    "warning",
                )
            else:
                flash(
                    "Inspection recorded. The job remains unresolved and its configuration copies remain protected.",
                    "info",
                )
    except ServiceError as error:
        if error.code == FORBIDDEN:
            return _fail(error, to_devices=True)
        flash(error.message, "danger")
    return redirect(url_for("restore_job", job_id=job_id))


@app.route("/restore/job/<job_id>/confirm", methods=["POST"])
@check_auth
def restore_job_confirm(job_id):
    return _job_action(job_id, "confirm")


@app.route("/restore/job/<job_id>/cancel", methods=["POST"])
@check_auth
def restore_job_cancel(job_id):
    return _job_action(job_id, "cancel")


@app.route("/restore/job/<job_id>/recheck", methods=["POST"])
@check_auth
def restore_job_recheck(job_id):
    return _job_action(job_id, "recheck")


@app.route("/restore/device/<device_id>", methods=["GET"])
@check_auth
def restore_device_jobs(device_id):
    restore, _profiles = _services()
    try:
        jobs = restore.list_jobs_for_device(session, device_id)
    except ServiceError as error:
        return _fail(error, to_devices=True)
    device = restore.devices.get_device(jobs[0]["device_id"]) if jobs else None
    return render_template(
        "restore_jobs.html", jobs=jobs, device=device, device_id=device_id
    )


@app.route("/restore/job/<job_id>/resolve", methods=["POST"])
@check_auth
def restore_job_resolve(job_id):
    return _job_action(job_id, "resolve")
