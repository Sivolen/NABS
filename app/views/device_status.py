from multiprocessing import Pool

from flask import (
    request,
    jsonify,
)

from app.modules.backuper import run_backup_config_on_db
from app.modules.auth.auth_users_ldap import check_auth

from config import proccesor_pool


# Ajax function to check device status
@check_auth
def device_status():
    """
    Ajax function to check device status
    """
    if request.method == "POST":
        previous_config_data = request.get_json()
        with Pool(processes=proccesor_pool) as pool:
            result = pool.apply_async(
                run_backup_config_on_db, args=(previous_config_data,)
            )
            result_dict = result.get()
        return jsonify(
            {
                "status": True,
                "device_id": result_dict["device_id"],
                "device_ip": result_dict["device_ip"],
                "vendor": result_dict["vendor"],
                "timestamp": result_dict["timestamp"],
                "last_changed": str(result_dict["last_changed"]),
                "connection_status": str(result_dict["connection_status"]),
            }
        )
