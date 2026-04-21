import secrets
import string
from app import app, db
from app.models import Users
from app.modules.auth.auth_users_local import AuthUsers
from sqlalchemy import inspect


def ensure_default_admin() -> None:
    """
    Create a default administrator user if no user with the 'sadmin' role exists.

    This function is intended to be called during application startup. It checks
    the database for any user with the role 'sadmin'. If none is found, it creates
    a new user with:
      - email: admin@admin.local
      - username: admin
      - role: sadmin
      - auth_method: local
      - a randomly generated 12-character password (letters, digits, and symbols).

    The generated password is logged and also printed to the console. The function
    ensures an application context is active before performing database operations.

    Side effects:
        - Inserts a new user record into the database if no sadmin exists.
        - Outputs messages to the application log and the console.
    """

    with app.app_context():
        # Проверяем, существует ли таблица 'users' (на случай, если миграции ещё не применены)
        inspector = inspect(db.engine)
        if not inspector.has_table('users'):
            app.logger.info("Table 'users' does not exist yet, skipping default admin creation.")
            return None
        sadmin_exists = Users.query.filter_by(role="sadmin").first()
        if sadmin_exists:
            app.logger.info("Default admin already exists, skipping creation.")
            return None

        alphabet: str = string.ascii_letters + string.digits + "!@#$%^&*"
        password: str = "".join(secrets.choice(alphabet) for _ in range(12))

        user = AuthUsers(
            email="admin@admin.local",
            username="admin",
            role="sadmin",
            password=password,
            auth_method="local",
            send_notifications=False,
        )
        success = user.add_user()
        if not success:
            app.logger.error("Failed to create default admin user!")
            return None

        app.logger.info("=" * 60)
        app.logger.info("Default admin user created.")
        app.logger.info(f"Email: admin@admin.local")
        app.logger.info(f"Password: {password}")
        app.logger.info("Please change the password after first login!")
        app.logger.info("=" * 60)
        app.logger.info("User created successfully.")
        print("\n" + "=" * 60)
        print("Default admin user created.")
        print(f"Email: admin@admin.local")
        print(f"Password: {password}")
        print("Please change the password after first login!")
        print("=" * 60 + "\n")

        return None
