#!venv/bin/python3
import re
# from sys import argv
from getpass import getpass
from argparse import ArgumentParser, RawDescriptionHelpFormatter

from app.modules.auth.auth_users_local import AuthUsers
from app import app, logger

def is_valid_email(email: str) -> bool:
    """Checks if a string is a valid email address."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def is_strong_password(password: str) -> tuple[bool, str]:
    """
    Checks whether the provided password meets strong password criteria.

    Returns:
        tuple[bool, str]:
            - (True, "") if the password is strong.
            - (False, "error message") if the password fails any requirement.
    """
    # Check minimum length requirement (at least 8 characters)
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"

    # Check for at least one digit
    if not re.search(r'\d', password):
        return False, "Password must contain at least one digit"

    # Check for at least one uppercase letter
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"

    # Check for at least one lowercase letter
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"

    # Check for at least one special character from a predefined set
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character (!@#$%^&*(), etc.)"

    # All checks passed – password is strong
    return True, ""


def add_new_user(email: str):
    # Проверка валидности email
    if not is_valid_email(email):
        print("Error: Invalid email address format")
        return
    with app.app_context():
        user = AuthUsers
        while True:
            try:
                username = input("Username: ")
                print("\nPassword requirements:")
                print("- At least 8 characters long")
                print("- At least one digit (0–9)")
                print("- At least one uppercase letter (A–Z)")
                print("- At least one lowercase letter (a–z)")
                print("- At least one special character (!@#$%^&*, etc.)")
                print()
                password = getpass("Password: ", stream=None)
                confirm_password = getpass("Retype password: ", stream=None)
                role = "sadmin"
                auth_method = "local"
                if password == confirm_password:
                    check = user(
                        username=username,
                        password=password,
                        email=email,
                        role=role,
                        auth_method=auth_method,
                    ).add_user()
                    if not check:
                        logger.info(
                            f"User {username} has not been added check your database settings"
                        )
                    # Check password strength using the is_strong_password function
                    is_strong, message = is_strong_password(password)

                    # If the password is weak, display the error message and prompt the user again
                    if not is_strong:
                        print(f"Weak password: {message}\n")
                        continue

                    logger.info(f"User {username} has been added")
                    break
                print("Passwords do not match")
            except KeyboardInterrupt:
                print("\n\nThe operation was interrupted by the user.")
                return


def delete_user(email: str) -> bool:
    with app.app_context():
        try:
            # Prompt the user for confirmation before deletion
            confirm = input(f"Are you sure you want to delete the user with email '{email}'? [y/N]: ")

            # If the user does not confirm (only 'y', 'yes' are accepted), cancel the operation
            if confirm.lower() not in ['y', 'yes']:
                print("Deletion operation cancelled.")
                return False

            # Attempt to delete the user by email using the AuthUsers model
            user = AuthUsers
            result = user(email=email).del_user_by_email()

            if result:
                print(f"User with email '{email}' has been successfully deleted.")
            else:
                print(f"Failed to delete user with email '{email}'.")

            return result

        except KeyboardInterrupt:
            # Handle user interruption (e.g., Ctrl+C)
            print("\n\nOperation interrupted by user.")
            return False


def cli_parser():
    parser = ArgumentParser(
        description="Users setting script", formatter_class=RawDescriptionHelpFormatter
    )

    parser.add_argument("-a", "--add", dest="email", help="Add user by email")

    parser.add_argument(
        "-d", "--del", dest="deleting_email", help="Delete user by email"
    )

    args = parser.parse_args()
    if args.email is not None:
        print(f"Creating user: {args.email}")
        add_new_user(email=args.email)

    elif args.deleting_email is not None:
        print(f"Deleting user: {args.deleting_email}")
        delete_user(email=args.deleting_email)

    else:
        print("You need to use arguments, use -h to see options")


if __name__ == "__main__":
    cli_parser()
