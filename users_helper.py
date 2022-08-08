#!venv/bin/python3
# from sys import argv
from getpass import getpass
from argparse import ArgumentParser, RawDescriptionHelpFormatter

from app.modules.auth_users import AuthUsers
from app import logger


def add_new_user(email: str):
    user = AuthUsers
    while True:
        email = email
        username = input("Username: ")
        password = getpass("Password: ", stream=None)
        confirm_password = getpass("Retype password: ", stream=None)
        role = "admin"
        if password == confirm_password:
            check = user(
                username=username, password=password, email=email, role=role
            ).add_user()
            if check:
                logger.info(f"User {username} has been added")
            else:
                logger.info(
                    f"User {username} has not been added check your database settings"
                )
            break
        print("Passwords do not match")


def delete_user(email: str) -> bool:
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
