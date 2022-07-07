#!venv/bin/python3
from sys import argv
from getpass import getpass
from argparse import ArgumentParser, RawDescriptionHelpFormatter

from app.modules.auth_users import add_user


def add_new_user(username: str):
    username = username
    email = input("email: ")
    password = getpass("password: ", stream=None)
    role = "admin"
    check = add_user(username=username, password=password, email=email, role=role)
    if check:
        print("User has been added")
    else:
        print("Error")


def cli_parser():

    parser = ArgumentParser(
        description="Users setting script", formatter_class=RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers()
    aad_user = subparsers.add_parser("add", help="Add a new user")
    # aad_user.set_defaults(func=add_new_user)
    # del_user = subparsers.add_parser("del", help="Del user, enter user email")
    # del_user.set_defaults(func=add_new_user)

    parser.add_argument(
        "-a",
        "--add",
        dest="username",
        help="points to the config file to read config data from "
        + "which is not installed under the default path '",
    )

    parser.add_argument(
        "-d", "--del", dest="del_user", help="set log level (overrides config)"
    )
    #
    # parser.add_argument("-n", "--dry_run", action="store_true",
    #                     help="Operate as usual but don't change anything in NetBox. Great if you want to test "
    #                          "and see what would be changed.")
    #
    # parser.add_argument("-p", "--purge", action="store_true",
    #                     help="Remove (almost) all synced objects which were create by this script. "
    #                          "This is helpful if you want to start fresh or stop using this script.")

    args = parser.parse_args()
    print(args)

    if args.username is not None:
        print(f"Creating user: {args.username}")
        add_new_user(username=args.username)

    if args.del_user is not None:
        print(f"Creating user: {args.add_user}")
        add_new_user(username=args.add_user)
    # args.func()


def main():
    args = argv
    if len(args) > 1:
        if args[1] == "-a":
            add_new_user()
        if args[1] == "-h":
            print("-a  add new user")
    else:
        print("-a  add new user")


if __name__ == "__main__":
    cli_parser()
