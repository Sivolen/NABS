from flask import (
    render_template,
    request,
    flash,
    session,
    url_for,
    redirect,
)
from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    get_config_versions,
    get_previous_config,
    delete_config_for_device,
    get_last_env_for_device,
)
from app.modules.dbutils.db_user_rights import check_user_permission
from app import logger
from app.modules.access import parse_id
from app.modules.auth.auth_users_ldap import check_auth


@check_auth
@check_user_permission
def config(device_id):
    """
    This function renders config page
    """
    logger.info(f"User: {session['user']} opens the config compare page")
    if request.method == "POST" and request.form.get("del_config_btn"):
        # config_id comes from the client: delete it only if it belongs to THIS device
        config_id = parse_id(request.form.get("del_config_btn"))
        result: bool = bool(config_id) and delete_config_for_device(
            config_id=config_id, device_id=parse_id(device_id)
        )
        if not result:
            logger.warning(
                f"User: {session['user']} failed to delete config"
                f" {request.form.get('del_config_btn')!r} of device {device_id}"
            )
            flash("Delete config error", "warning")
            return redirect(url_for("config", device_id=device_id))
        logger.info(
            f"User: {session['user']} deleted config {config_id} of device {device_id}"
        )
        flash("Config has been deleted", "success")
        return redirect(url_for("config", device_id=device_id))
        #
    config_versions = get_config_versions(device_id)
    last_config_dict = get_last_config_for_device(device_id)
    check_previous_config = len(config_versions) > 1
    requested_id = request.args.get("config_id")
    requested_date = request.args.get("date")
    if requested_id is not None or requested_date:
        selected_id = parse_id(requested_id)
        selected = None
        if requested_id is None or selected_id is not None:
            selected = get_previous_config(
                device_id=device_id, config_id=selected_id, db_timestamp=requested_date
            )
        if selected:
            last_config_dict = {**selected, "last_config": selected["device_config"]}
        else:
            flash("Selected config is no longer available", "warning")
    device_environment = get_last_env_for_device(device_id=device_id)
    if last_config_dict is None:
        flash("Config not found?", "info")
        return redirect(url_for("devices", device_id=device_id))

    return render_template(
        "config_page.html",
        config_id=last_config_dict["id"],
        ipaddress=device_environment["device_ip"],
        last_config=last_config_dict["last_config"],
        timestamp=last_config_dict["timestamp"],
        config_versions=config_versions,
        check_previous_config=check_previous_config,
        device_environment=device_environment,
    )
