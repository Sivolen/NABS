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

# Setting up the logger
logger = logging.getLogger(__name__)


def is_safe_url(target):
    """Проверка безопасности URL для редиректа"""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and test_url.netloc == ref_url.netloc


def setup_user_session(user_id: int, email: str):
    """Установка сессионных данных пользователя"""
    session.permanent = True  # Включаем постоянную сессию
    session["user"] = email
    session["user_id"] = user_id
    session["rights"] = check_user_rights(user_email=email)
    session["allowed_devices"] = get_users_group(user_id=user_id)


def handle_auth_attempt(email: str, password: str, auth_method: str):
    """Обработка попытки аутентификации"""
    try:
        if auth_method == "local":
            auth = AuthUsers(email=email, password=password)
            if not auth.check_user():
                logger.warning(f"Failed local login attempt for {email}")
                return False
            return auth.get_user_id_by_email()

        if auth_method == "ldap":
            ldap = LdapFlask(email, password)
            if not ldap.bind():
                logger.warning(f"Failed LDAP login attempt for {email}")
                return False
            return AuthUsers(email=email).get_user_id_by_email()

    except Exception as e:
        logger.error(f"Auth error for {email}: {str(e)}")
        return None


def login():
    """Обработчик авторизации пользователей"""
    # Если пользователь уже авторизован
    if session.get("user"):
        session.clear()
        flash("You were successfully logged out", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        next_url = request.form.get("next") or session.pop("next_url", None)

        # Валидация входных данных
        if not email or not password:
            flash("Please fill all required fields", "danger")
            return render_template("login.html", next_url=next_url)

        try:
            # Получение информации о пользователе
            auth_user = AuthUsers(email=email)
            user_id = auth_user.get_user_id_by_email()
            auth_method = auth_user.get_user_auth_method()

            if not user_id or not auth_method:
                flash("User not found or authentication method not configured", "warning")
                return render_template("login.html", next_url=next_url)

            # Попытка аутентификации
            auth_result = handle_auth_attempt(email, password, auth_method)

            if not auth_result:
                flash("Authentication failed. Check your credentials", "danger")
                return render_template("login.html", next_url=next_url)

            # Установка сессии
            setup_user_session(user_id, email)
            logger.info(f"Successful login for {email}")

            # Обработка редиректа
            if next_url and is_safe_url(next_url):
                return redirect(next_url)

            return redirect(url_for("devices"))

        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            flash("Internal server error. Please try again later", "danger")
            return render_template("login.html", next_url=next_url)

    # GET-запрос
    next_url = request.args.get("next", "")
    return render_template("login.html", next_url=next_url)