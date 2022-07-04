#!venv/bin/python3
from sys import argv
from getpass import getpass

from app.modules.auth_users import add_user


def add_new_user():
    username = input("username:")
    password = getpass("password", stream=None)
    email = input("email:")
    role = input("role:")
    check = add_user(username=username, password=password, email=email, role=role)
    if check:
        print("User has been added")
    else:
        print("Error")


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
    main()
