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
                    logger.info(f"User {username} has been added")
                    break
                print("Passwords do not match")
            except KeyboardInterrupt:
                print("\n\nThe operation was interrupted by the user.")
                return


def delete_user(email: str) -> bool:
    with app.app_context():
        user = AuthUsers
        return user(email=email).del_user_by_email()


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


# def main():
#     args = argv
#     if len(args) > 1:
#         if args[1] == "-a":
#             add_new_user()
#         if args[1] == "-h":
#             print("-a  add new user")
#     else:
#         print("-a  add new user")


if __name__ == "__main__":
    cli_parser()
