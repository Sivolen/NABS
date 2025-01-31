from flask import render_template, session
from app import app, logger, __version__, __ui__
from app.modules.auth.auth_users_ldap import check_auth

# Import views
from app.views.auth import login
from app.views.devices import devices
from app.views.config import config
from app.views.diff import diff_page, compare_config
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
from app.views.drivers import drivers, drivers_settings
from app.views.search import search
from app.views.dashboards import dashboards
from app.views.restore_config import restore_config
from app.views.reports import reports

# Define route mappings
ROUTE_MAPPINGS = [
    # Authentication
    ("/login", login, ["POST", "GET"]),
    # Main pages
    ("/", devices, ["POST", "GET"]),
    ("/dashboards/", dashboards, ["POST", "GET"]),
    ("/search/", search, ["POST", "GET"]),
    # Device-related routes
    ("/diff_page/<device_id>", diff_page, ["POST", "GET"]),
    ("/config_page/<device_id>", config, ["POST", "GET"]),
    ("/compare_config/<device_id>", compare_config, ["POST", "GET"]),
    ("/device_status/", device_status, ["POST", "GET"]),
    ("/device_settings/", device_settings, ["POST", "GET"]),
    ("/restore_config/", restore_config, ["POST", "GET"]),
    # Configuration-related routes
    ("/diff_configs/", diff_configs, ["POST", "GET"]),
    ("/previous_config/", previous_config, ["POST", "GET"]),
    # User and group management
    ("/users/", users, ["POST", "GET"]),
    ("/users_groups/", users_groups, ["POST", "GET"]),
    ("/user_group/<user_id>", user_group, ["POST", "GET"]),
    ("/associate_settings/<user_group_id>", associate_settings, ["POST", "GET"]),
    # Device group management
    ("/devices_groups/", devices_groups, ["POST", "GET"]),
    # Credentials management
    ("/credentials/", credentials, ["POST", "GET"]),
    ("/credentials_data/", get_credentials_data, ["POST", "GET"]),
    # Drivers management
    ("/drivers/", drivers, ["POST", "GET"]),
    ("/drivers_settings/", drivers_settings, ["POST", "GET"]),
    # Reports
    ("/reports/", reports, ["POST", "GET"]),
]

# Register routes dynamically
for path, view_func, methods in ROUTE_MAPPINGS:
    app.add_url_rule(path, view_func=view_func, methods=methods)


# Context processor to inject version and UI info
@app.context_processor
def inject_version():
    """Inject version and UI information into all templates."""
    return dict(core_version=__version__, ui=__ui__)


# Error handler for 404
@app.errorhandler(404)
@check_auth
def page_not_found(error):
    """Handle 404 errors and log access attempts."""
    logger.info(
        f"User: {session['user']}, role {session['rights']} attempted to access missing page: {error}"
    )
    return render_template("404.html"), 404
