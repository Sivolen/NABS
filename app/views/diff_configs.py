from difflib import SequenceMatcher
from flask import (
    request,
    jsonify,
    session,
)
from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    get_previous_config,
)
from app.modules.dbutils.db_user_rights import check_user_role_block
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.access import can_access_device, parse_id


@check_auth
@check_user_role_block
def diff_configs() -> object:
    """
    Ajax function to compare device configurations
    """
    if request.method == "POST":
        data: dict = request.get_json(silent=True) or {}
        device_id = parse_id(data.get("device_id"))
        previous_config_timestamp = data.get("date")
        config_id = parse_id(data.get("config_id"))
        if (
            device_id is None
            or ("config_id" in data and config_id is None)
            or (config_id is None and previous_config_timestamp is None)
        ):
            return jsonify({"status": "error", "message": "Invalid request"}), 400
        if not can_access_device(session, device_id):
            return jsonify({"status": "error", "message": "Access denied"}), 403
        selector = (
            {"config_id": config_id}
            if config_id is not None
            else {"db_timestamp": previous_config_timestamp}
        )
        previous_config_dict = get_previous_config(device_id=device_id, **selector)
        if "last_config_id" in data:
            last_config_id = parse_id(data["last_config_id"])
            if last_config_id is None:
                return jsonify({"status": "error", "message": "Invalid request"}), 400
            last_version = get_previous_config(
                device_id=device_id, config_id=last_config_id
            )
            last_config_dict = (
                {"last_config": last_version["device_config"]} if last_version else None
            )
        else:
            last_config_dict = get_last_config_for_device(device_id=device_id)
        if previous_config_dict is None or last_config_dict is None:
            result = "none"
            return jsonify(
                {
                    "status": result,
                    "previous_config_file": None,
                }
            )
        previous_config_file: list = previous_config_dict["device_config"].splitlines()
        # pattern = r"^\n"
        #
        # last_config_file: str = re.sub(pattern, "", str(last_config_dict["last_config"]))
        # last_config_file: list = last_config_file.splitlines()
        last_config_file: list = last_config_dict["last_config"].splitlines()
        opcodes: list = SequenceMatcher(
            None, previous_config_file, last_config_file
        ).get_opcodes()

        return jsonify(
            {
                "status": "ok",
                "opcodes": opcodes,
            }
        )
    return jsonify({"status": "error", "message": "Method not allowed"}), 405
