from flask import (
    render_template,
    session,
)
from app import app

# get_all_credentials
# update_associate_device_group,
from app import logger, __version__, __ui__
from app.modules.auth.auth_users_ldap import check_auth
from app.views.auth import login
from app.views.devices import devices
from app.views.config import config
from app.views.diff import diff_page
from app.views.previous_config import previous_config
from app.views.device_status import device_status
from app.views.device_setting import device_settings
from app.views.diff_configs import diff_configs
from app.views.users_groups import users_groups
from app.views.users import users
from app.views.devices_groups import devices_groups
from app.views.associate_settings import associate_settings
from app.views.user_group import user_group
from app.views.credentials import credentials
from app.views.get_credentials import get_credentials_data
from app.views.search import search
from app.views.dashboards import dashboards
from app.views.restore_config import restore_config

app.add_url_rule("/login", view_func=login, methods=["POST", "GET"])
app.add_url_rule("/", view_func=devices, methods=["POST", "GET"])
app.add_url_rule("/diff_page/<device_id>", view_func=diff_page, methods=["POST", "GET"])
app.add_url_rule("/config_page/<device_id>", view_func=config, methods=["POST", "GET"])
app.add_url_rule("/diff_configs/", view_func=diff_configs, methods=["POST", "GET"])
app.add_url_rule(
    "/previous_config/", view_func=previous_config, methods=["POST", "GET"]
)
app.add_url_rule("/device_status/", view_func=device_status, methods=["POST", "GET"])
app.add_url_rule(
    "/device_settings/", view_func=device_settings, methods=["POST", "GET"]
)
app.add_url_rule("/users/", view_func=users, methods=["POST", "GET"])
app.add_url_rule("/users_groups/", view_func=users_groups, methods=["POST", "GET"])
app.add_url_rule("/user_group/<user_id>", view_func=user_group, methods=["POST", "GET"])
app.add_url_rule(
    "/associate_settings/<user_group_id>",
    view_func=associate_settings,
    methods=["POST", "GET"],
)
app.add_url_rule("/devices_groups/", view_func=devices_groups, methods=["POST", "GET"])
app.add_url_rule("/credentials/", view_func=credentials, methods=["POST", "GET"])
app.add_url_rule(
    "/credentials_data/", view_func=get_credentials_data, methods=["POST", "GET"]
)
app.add_url_rule("/search/", view_func=search, methods=["POST", "GET"])
app.add_url_rule("/dashboards/", view_func=dashboards, methods=["POST", "GET"])
app.add_url_rule("/restore_config/", view_func=restore_config, methods=["POST", "GET"])


@app.context_processor
def inject_version():
    return dict(core_version=__version__, ui=__ui__)


@app.errorhandler(404)
@check_auth
def page_not_found(error):
    # note that we set the 404 status explicitly
    logger.info(f"User: {session['user']}, role {session['rights']} opens page {error}")
    return render_template("404.html"), 404
