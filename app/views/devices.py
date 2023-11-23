import collections

from flask import (
    render_template,
    request,
    flash,
    session,
    url_for,
    redirect,
)

from app.modules.dbutils.db_credentials import (
    get_allowed_credentials,
)
from app.modules.dbutils.db_drivers import get_all_drivers
from app.modules.dbutils.db_utils import (
    delete_device,
    update_device,
)
from app.modules.dbutils.db_devices import (
    add_device,
    get_devices_by_rights,
    get_devices_env,
    get_device_id,
)
from app.modules.dbutils.db_groups import (
    get_all_devices_group,
)
from app.modules.dbutils.db_users_permission import (
    get_associate_user_group,
    create_associate_device_group,
    convert_user_group_in_association_id,
    get_association_user_and_device,
    delete_associate_by_list,
)
from app.utils import check_ip
from app import logger
from app.modules.auth.auth_users_ldap import check_auth

from config import drivers


@check_auth
def devices():
    """
    This function render devices page
    """
    group_result: bool = True
    devices_menu_active = True
    logger.info(f"User: {session['user']} opens the devices page")

    # If there are post requests from the form, we start processing these requests [add, delete, change device].
    if request.method == "POST" and request.form.get("add_device_btn"):
        user_groups: list = request.form.getlist("add_user_groups")
        page_data = {
            "group_id": int(request.form.get("device_group")),
            "hostname": request.form.get("add_hostname"),
            "ipaddress": request.form.get("add_ipaddress"),
            "connection_driver": request.form.get("add_platform"),
            "ssh_port": int(request.form.get("add_port")),
            "credentials_id": int(request.form.get("add_credentials_profile")),
        }
        logger.info(
            f"User: {session['user']} add a new device {page_data['ipaddress']}"
        )
        if (
            not page_data["hostname"]
            or not page_data["ipaddress"]
            or not page_data["connection_driver"]
            or not page_data["ssh_port"]
        ):
            flash("All fields must be filled", "warning")
            return redirect(url_for("devices"))

        if get_device_id(ipaddress=page_data["ipaddress"]):
            logger.info(
                f"User: {session['user']} tried to add a device:"
                f" {page_data['ipaddress']} that is already in the database"
            )
            flash("The device is already in the database", "warning")
            return redirect(url_for("devices"))

        if not check_ip(page_data["ipaddress"]):
            logger.info(
                f"User: {session['user']} tried to add a device with the wrong ip"
                f" address {page_data['ipaddress']}"
            )
            flash("The IP address is incorrect", "warning")
            return redirect(url_for("devices"))

        result = add_device(**page_data)
        if not result:
            logger.info(
                f"Adding a new device {page_data['ipaddress']} by user"
                f" {session['user']} ended with an error"
            )
            flash(
                (
                    "There was an error when chiseling a new device"
                    f" {page_data['ipaddress']}"
                ),
                "danger",
            )
            return redirect(url_for("devices"))

        if result and user_groups != []:
            device_id = get_device_id(ipaddress=page_data["ipaddress"])[0]
            for group_id in user_groups:
                group_result = create_associate_device_group(
                    device_id=int(device_id),
                    user_group_id=int(group_id),
                )
                if not group_result:
                    flash(
                        "An error occurred while adding the user group",
                        "danger",
                    )
            return redirect(url_for("devices"))
        if result:
            logger.info(
                f"User: {session['user']} added a new device {page_data['ipaddress']}"
            )
            flash("The device has been added", "success")
            return redirect(url_for("devices"))

    # Delete a new device
    if request.method == "POST" and request.form.get("del_device_btn"):
        device_id: int = int(request.form.get("del_device_btn"))
        logger.info(
            f"User: {session['user']} is trying to remove the device 10 {device_id}"
        )
        result: bool = delete_device(device_id=device_id)

        if not result:
            logger.info(f"Device {device_id} removed")
            flash(f"An error occurred when deleting a device {device_id}", "danger")
            return redirect(url_for("devices"))

        logger.info(f"Device {device_id} removed")
        flash("The device has been removed", "success")
        return redirect(url_for("devices"))

    # Change the device
    if request.method == "POST" and request.form.get("edit_device_btn"):
        print(request.form)
        edit_user_group = request.form.getlist(f"user-group")
        edit_user_group = list(map(int, edit_user_group))
        page_data = {
            "group_id": int(request.form.get(f"device-group")),
            "hostname": request.form.get(f"hostname"),
            "device_id": int(request.form.get(f"edit_device_btn")),
            "new_ipaddress": request.form.get(f"ipaddress"),
            "connection_driver": request.form.get(f"platform"),
            "ssh_port": int(request.form.get(f"port")),
            "credentials_id": int(request.form.get(f"credentials_profile")),
        }
        logger.info(
            f"User: {session['user']} tries to edit the device"
            f" {page_data['new_ipaddress']}"
        )
        if (
            not page_data["hostname"]
            or not page_data["new_ipaddress"]
            or not page_data["connection_driver"]
            or not page_data["ssh_port"]
        ):
            flash("All fields must be filled", "warning")
            return redirect(url_for("devices"))

        if not check_ip(page_data["new_ipaddress"]):
            logger.info(f"The new IP address is incorrect {page_data['new_ipaddress']}")
            flash("The new IP address is incorrect", "warning")
            return redirect(url_for("devices"))

        # Update device data
        result = update_device(**page_data)

        if not result:
            logger.info(f"Update device error {page_data['new_ipaddress']}")
            flash("Update device error", "warning")
            return redirect(url_for("devices"))

        if result and edit_user_group != []:
            old_user_groups: list = get_association_user_and_device(
                user_id=session["user_id"],
                device_id=page_data["device_id"],
            )
            converted_groups_list: list = convert_user_group_in_association_id(
                user_id=session["user_id"],
                device_id=page_data["device_id"],
                user_groups_list=edit_user_group,
            )
            if not collections.Counter(old_user_groups) == collections.Counter(
                converted_groups_list
            ) or not len(edit_user_group) == len(old_user_groups):
                delete_associate_by_list(associate_id=old_user_groups)
                for group in edit_user_group:
                    group_result = create_associate_device_group(
                        device_id=int(page_data["device_id"]),
                        user_group_id=int(group),
                    )
                if not group_result:
                    flash(
                        (
                            f"The {page_data['new_ipaddress']} device was updated, but"
                            " an error occurred when updating user groups"
                        ),
                        "warning",
                    )

                    logger.debug(
                        f"The {page_data['new_ipaddress']} device was updated, but an"
                        " error occurred when updating user groups"
                    )
                    return redirect(url_for("devices"))

            flash("The device has been updated", "success")
            logger.info(f"The device {page_data['new_ipaddress']} has been updated ")
            return redirect(url_for("devices"))
        #
        if result and edit_user_group == []:
            old_user_groups: list = get_association_user_and_device(
                user_id=session["user_id"],
                device_id=page_data["device_id"],
            )
            if not old_user_groups:
                logger.info(
                    f"The device {page_data['new_ipaddress']} has been updated "
                )
                flash("The device has been updated", "success")
                return redirect(url_for("devices"))

            group_result: bool = delete_associate_by_list(associate_id=old_user_groups)
            if not group_result:
                logger.info(
                    f"The device {page_data['new_ipaddress']} has been updated but an"
                    " error occurred while deleting user groups"
                )
                flash(
                    (
                        f"The device {page_data['new_ipaddress']} has been updated but"
                        " an error occurred while deleting user groups"
                    ),
                    "warning",
                )

            logger.info(f"The device {page_data['new_ipaddress']} has been updated ")
            flash("The device has been updated", "success")
            return redirect(url_for("devices"))

    # Render template if get request
    if session["rights"] == "sadmin":
        devices_table = get_devices_env()
        user_groups = get_associate_user_group(user_id=session["user_id"])
    else:
        devices_table = get_devices_by_rights(user_id=session["user_id"])
        user_groups = get_associate_user_group(user_id=session["user_id"])
    # Loading the page if a GET request arrives
    return render_template(
        "devices.html",
        devices_env=devices_table,
        groups=get_all_devices_group(),
        user_groups=user_groups,
        drivers=drivers,
        custom_drivers=get_all_drivers(),
        devices_menu_active=devices_menu_active,
        credentials_profiles=get_allowed_credentials(user_id=session["user_id"]),
    )
