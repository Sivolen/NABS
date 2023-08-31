from flask import (
    render_template,
    request,
    session,
)
from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_user_rights import check_user_role_block


# TO DO
# Ajax function get devices status
@check_auth
@check_user_role_block
def restore_config():
    if request.method == "POST":
        pass
