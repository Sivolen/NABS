from difflib import SequenceMatcher
from flask import (
    request,
    jsonify,
)
from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    get_previous_config,
)
from app.modules.dbutils.db_user_rights import check_user_role_block
from app.modules.auth.auth_users_ldap import check_auth


@check_auth
@check_user_role_block
def diff_configs() -> object:
    """
    Ajax function to compare device configurations
    """
    if request.method == "POST":
        data: dict = request.get_json()
        device_id: int = data["device_id"]
        previous_config_timestamp: str = data["date"]
        previous_config_dict: dict = get_previous_config(
            device_id=device_id, db_timestamp=previous_config_timestamp
        )
        last_config_dict: dict = get_last_config_for_device(device_id=device_id)
        if previous_config_dict is None or last_config_dict is None:
            result = "none"
            return jsonify(
                {
                    "status": result,
                    "previous_config_file": None,
                }
            )

        previous_config_file: str = previous_config_dict["device_config"].splitlines()
        last_config_file: str = last_config_dict["last_config"].splitlines()
        opcodes: list = SequenceMatcher(
            None, previous_config_file, last_config_file
        ).get_opcodes()

        return jsonify(
            {
                "status": "ok",
                "opcodes": opcodes,
            }
        )
