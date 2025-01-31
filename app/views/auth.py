from flask import (
    render_template,
    request,
    flash,
    session,
    redirect,
    url_for
)
from app.modules.dbutils.db_users_permission import get_users_group
from app.modules.dbutils.db_user_rights import check_user_rights
from app.modules.auth.auth_users_local import AuthUsers
from app.modules.auth.auth_users_ldap import LdapFlask
from urllib.parse import urlparse, urljoin
import logging

# Initialize logger
logger = logging.getLogger(__name__)

def is_safe_url(target):
    """Verify if the redirect URL belongs to our domain to prevent open redirects"""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and test_url.netloc == ref_url.netloc

def setup_user_session(user_id: int, email: str):
    """Initialize user session with required parameters"""
    session.permanent = True  # Enable persistent sessions
    # app.permanent_session_lifetime = timedelta(minutes=30)
    session["user"] = email
    session["user_id"] = user_id
    session["rights"] = check_user_rights(user_email=email)
    session["allowed_devices"] = get_users_group(user_id=user_id)
    logger.info(f"Session initialized for user: {email} (ID: {user_id})")

def handle_auth_attempt(email: str, password: str, auth_method: str):
    """Handle authentication attempts for different methods (local/LDAP)"""
    try:
        if auth_method == "local":
            logger.debug(f"Attempting local authentication for: {email}")
            auth = AuthUsers(email=email, password=password)
            if not auth.check_user():
                logger.warning(f"Failed local authentication attempt for: {email} from IP: {request.remote_addr}")
                return False
            return auth.get_user_id_by_email()

        if auth_method == "ldap":
            logger.debug(f"Attempting LDAP authentication for: {email}")
            ldap = LdapFlask(email, password)
            if not ldap.bind():
                logger.warning(f"Failed LDAP authentication attempt for: {email} from IP: {request.remote_addr}")
                return False
            return AuthUsers(email=email).get_user_id_by_email()

    except Exception as e:
        logger.error(f"Authentication error for {email}: {str(e)}", exc_info=True)
        return None

def login():
    """Handle user authentication and session management"""
    # If user is already authenticated (for simplified logout functionality)
    if session.get("user"):
        logger.info(f"Force logout initiated for: {session['user']} from IP: {request.remote_addr}")
        session.clear()
        flash("You were successfully logged out", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        next_url = request.form.get("next") or session.pop("next_url", None)
        client_ip = request.remote_addr

        # Validate required fields
        if not email or not password:
            logger.warning(f"Empty credentials attempt from IP: {client_ip}")
            flash("Please fill all required fields", "danger")
            return render_template("login.html", next_url=next_url)

        try:
            # Retrieve user authentication method
            auth_user = AuthUsers(email=email)
            user_id = auth_user.get_user_id_by_email()
            auth_method = auth_user.get_user_auth_method()

            if not user_id or not auth_method:
                logger.warning(f"User lookup failed for: {email} from IP: {client_ip}")
                flash("User not found or authentication method not configured", "warning")
                return render_template("login.html", next_url=next_url)

            # Process authentication attempt
            auth_result = handle_auth_attempt(email, password, auth_method)

            if not auth_result:
                logger.warning(f"Invalid credentials for: {email} from IP: {client_ip}")
                flash("Authentication failed. Check your credentials", "danger")
                return render_template("login.html", next_url=next_url)

            # Initialize user session
            setup_user_session(user_id, email)
            logger.info(f"Successful authentication for: {email} (Method: {auth_method}) from IP: {client_ip}")

            # Handle post-authentication redirect
            if next_url and is_safe_url(next_url):
                logger.debug(f"Redirecting user {email} to: {next_url}")
                return redirect(next_url)

            logger.debug(f"Default redirect for user {email} to devices page")
            return redirect(url_for("devices"))

        except Exception as e:
            logger.error(f"Critical authentication error for {email}: {str(e)}", exc_info=True)
            flash("Internal server error. Please try again later", "danger")
            return render_template("login.html", next_url=next_url)

    # Handle GET requests
    next_url = request.args.get("next", "")
    logger.debug(f"Login page accessed from IP: {request.remote_addr} with next URL: {next_url}")
    return render_template("login.html", next_url=next_url)