#!/usr/bin/env python3
"""
Helper of Install_v2.sh: everything that needs real logic (and therefore tests) lives
here, the shell script only calls it.  Standard library only, so it also works before
the virtual environment exists.

    nabs_setup.py [--app-dir DIR] config-get NAME      print one value of config.py
    nabs_setup.py [--app-dir DIR] init-config          create config.py (NEVER overwrites)
    nabs_setup.py [--app-dir DIR] check-config         validate config.py
    nabs_setup.py [--app-dir DIR] provision-db         create the DB role and database
    nabs_setup.py [--app-dir DIR] db-check             connect with config.py settings
    nabs_setup.py [--app-dir DIR] render FILE          unit / nginx file for this host

The configuration of NABS is the Python module config.py (created from
config_example.py). There is no YAML configuration.

Secrets are never printed, never passed on a command line and never logged.
"""

import argparse
import json
import os
import re
import runpy
import secrets
import shlex
import subprocess
import sys
from pathlib import Path

DEFAULT_APP_DIR = "/opt/NABS"  # the path written in supervisor/*
DEFAULT_SERVICE_USER = "nabs"  # the user written in supervisor/*
MIN_SECRET_LENGTH = 16
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "")

EXIT_OK, EXIT_ERROR, EXIT_EXISTS = 0, 1, 3


# --------------------------------------------------------------------------- config
def load_config(app_dir: Path) -> dict:
    """Runs config.py in an empty namespace (it is the administrator's own code)."""
    path = Path(app_dir) / "config.py"
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist")
    return runpy.run_path(str(path))


def new_secret(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def _replace_assignment(text: str, name: str, value: str) -> str:
    """name = "..."  ->  name = "<value>" (only a top-level assignment of a plain value)."""
    pattern = re.compile(
        rf'^({re.escape(name)}\s*=\s*)(?:"[^"\n]*"|\'[^\'\n]*\'|None)[ \t]*$', re.M
    )
    if not pattern.search(text):
        raise ValueError(f"config_example.py has no plain assignment of {name}")
    # a function as the replacement: no backslash / group escaping surprises
    return pattern.sub(lambda m: m.group(1) + json.dumps(value), text, count=1)


def init_config(app_dir: Path, group: str = "") -> int:
    """
    Creates config.py from config_example.py with freshly generated secrets.
    An existing config.py is NEVER touched: regenerating TOKEN or
    CREDENTIALS_ENCRYPTION_KEY would make every saved SSH password unreadable.
    """
    app_dir = Path(app_dir)
    target = app_dir / "config.py"
    if target.exists():
        print(f"config.py exists and is kept as it is: {target}")
        return EXIT_EXISTS
    text = (app_dir / "config_example.py").read_text(encoding="utf-8")
    for name in ("DBPassword", "TOKEN", "CREDENTIALS_ENCRYPTION_KEY"):
        text = _replace_assignment(
            text, name, new_secret(24 if name == "DBPassword" else 32)
        )
    # exclusive create: never overwrite, even if another run created the file meanwhile
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    if group:
        try:
            import grp

            os.chown(target, -1, grp.getgrnam(group).gr_gid)
        except (KeyError, PermissionError, ImportError) as error:
            print(
                f"Cannot set the group {group!r} of config.py: {type(error).__name__}"
            )
    os.chmod(target, 0o640)
    print(f"Created {target} with new DBPassword, TOKEN and CREDENTIALS_ENCRYPTION_KEY")
    return EXIT_OK


def check_config(values: dict) -> list:
    """List of problems that make the application unable to start or to connect."""
    problems = []
    for name in ("TOKEN", "CREDENTIALS_ENCRYPTION_KEY"):
        value = values.get(name)
        if not isinstance(value, str) or len(value) < MIN_SECRET_LENGTH:
            problems.append(
                f"{name} is missing, empty or shorter than {MIN_SECRET_LENGTH} characters"
            )
    key, token = values.get("CREDENTIALS_ENCRYPTION_KEY"), values.get("TOKEN")
    if isinstance(key, str) and key and key == token:
        problems.append("CREDENTIALS_ENCRYPTION_KEY must differ from TOKEN")
    for name in ("DBHost", "DBPort", "DBName", "DBUser", "DBPassword"):
        if not str(values.get(name) or "").strip():
            problems.append(f"{name} is not set")
    return problems


# ----------------------------------------------------------------------- SQL quoting
def sql_ident(name: str) -> str:
    if "\x00" in name or not name:
        raise ValueError("invalid SQL identifier")
    return '"' + name.replace('"', '""') + '"'


def sql_literal(value: str) -> str:
    if "\x00" in value:
        raise ValueError("invalid SQL literal")
    escaped = value.replace("'", "''")
    if "\\" in escaped:  # independent of standard_conforming_strings
        return "E'" + escaped.replace("\\", "\\\\") + "'"
    return "'" + escaped + "'"


# --------------------------------------------------------------- database provisioning
class Psql:
    """Runs SQL through psql. The SQL (with a password) goes through stdin only."""

    def __init__(self, command):
        self.command = list(command)

    def run(self, sql: str, dbname: str = None) -> str:
        argv = self.command + ["-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"]
        if dbname:
            argv += ["-d", dbname]
        result = subprocess.run(argv, input=sql, capture_output=True, text=True)
        if result.returncode != 0:
            # stderr of psql can quote the statement: show the first line, no more
            first = (result.stderr.strip().splitlines() or ["psql failed"])[0]
            raise RuntimeError(first[:300])
        return result.stdout.strip()


def provision_database(values: dict, psql) -> list:
    """
    Creates the role and the database from config.py when they do not exist.
    Idempotent: an existing role keeps its password, an existing database keeps its
    data; nothing is dropped, recreated or altered. Returns what was done.

    The database is created with OWNER = the application role: on PostgreSQL 15+ only
    the owner may create tables in the public schema (GRANT ALL ON DATABASE is not
    enough, so "flask db upgrade" would fail with "permission denied for schema public").
    """
    name, user, password = (
        str(values["DBName"]),
        str(values["DBUser"]),
        str(values["DBPassword"]),
    )
    done = []

    if psql.run(f"SELECT 1 FROM pg_roles WHERE rolname = {sql_literal(user)};") != "1":
        psql.run(
            f"CREATE ROLE {sql_ident(user)} LOGIN PASSWORD {sql_literal(password)};"
        )
        done.append(f"created role {user}")

    exists = (
        psql.run(f"SELECT 1 FROM pg_database WHERE datname = {sql_literal(name)};")
        == "1"
    )
    if not exists:
        psql.run(f"CREATE DATABASE {sql_ident(name)} OWNER {sql_ident(user)};")
        done.append(f"created database {name} owned by {user}")
    else:
        owner = psql.run(
            "SELECT pg_get_userbyid(datdba) FROM pg_database "
            f"WHERE datname = {sql_literal(name)};"
        )
        if owner != user:
            # an existing database of someone else: let the role work in it, additively
            psql.run(
                f"GRANT ALL PRIVILEGES ON DATABASE {sql_ident(name)} TO {sql_ident(user)};"
            )
            psql.run(f"GRANT ALL ON SCHEMA public TO {sql_ident(user)};", dbname=name)
            done.append(
                f"granted {user} access to the existing database {name} (owner {owner})"
            )
    return done


# ------------------------------------------------------------------- connection check
def explain_db_error(error: Exception, values: dict) -> str:
    """A short human explanation; the password is masked if a driver quotes it."""
    text = (str(error).strip().splitlines() or [""])[0]
    password = str(values.get("DBPassword") or "")
    if password:
        text = text.replace(password, "***")
    low = text.lower()
    if "password authentication failed" in low or "authentication failed" in low:
        hint = (
            "wrong DBUser / DBPassword in config.py (or the role has another password)"
        )
    elif "does not exist" in low and "database" in low:
        hint = "the database from DBName does not exist: run Install_v2.sh again or create it"
    elif "connection refused" in low or "could not connect" in low or "timeout" in low:
        hint = "PostgreSQL is not reachable at DBHost:DBPort (is it running?)"
    else:
        hint = "see the message above"
    return f"{type(error).__name__}: {text[:200]} -> {hint}"


def check_database(values: dict, connect=None) -> list:
    """Connects with the settings of config.py. Returns a list of problems (empty = OK)."""
    if connect is None:
        import psycopg2  # installed with requirements.txt

        connect = psycopg2.connect
    try:
        connection = connect(
            host=values["DBHost"],
            port=values["DBPort"],
            dbname=values["DBName"],
            user=values["DBUser"],
            password=values["DBPassword"],
            connect_timeout=10,
        )
    except Exception as error:
        return [explain_db_error(error, values)]
    problems = []
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
        if cursor.fetchone()[0] is not True:
            problems.append(
                f"user {values['DBUser']} cannot create tables in schema public (PostgreSQL 15+):"
                f' run  GRANT ALL ON SCHEMA public TO "{values["DBUser"]}";  in database'
                f" {values['DBName']}, or make the user the owner of the database"
            )
    except Exception as error:
        problems.append(explain_db_error(error, values))
    finally:
        connection.close()
    return problems


# ----------------------------------------------------------------------- rendering
def render_file(
    path: Path, app_dir: str, service_user: str, service_group: str = ""
) -> str:
    """
    The files in supervisor/ are written for /opt/NABS and the user "nabs"; this fits
    them to the real directory and the real service user (nothing else is changed).
    """
    text = Path(path).read_text(encoding="utf-8")
    text = text.replace(DEFAULT_APP_DIR, str(app_dir).rstrip("/"))
    group = service_group or service_user
    text = re.sub(r"^User=nabs$", f"User={service_user}", text, flags=re.M)
    text = re.sub(r"^Group=nabs$", f"Group={group}", text, flags=re.M)
    text = re.sub(r"^user=nabs$", f"user={service_user}", text, flags=re.M)
    return text


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--app-dir", default=str(Path(__file__).resolve().parent.parent)
    )
    parser.add_argument(
        "--psql", default="sudo -u postgres psql", help="how to start psql"
    )
    parser.add_argument("--service-user", default=DEFAULT_SERVICE_USER)
    parser.add_argument("--service-group", default="")
    sub = parser.add_subparsers(dest="command", required=True)
    get = sub.add_parser("config-get")
    get.add_argument("name")
    sub.add_parser("init-config")
    sub.add_parser("check-config")
    sub.add_parser("provision-db")
    sub.add_parser("db-check")
    render = sub.add_parser("render")
    render.add_argument("file")
    args = parser.parse_args(argv)
    app_dir = Path(args.app_dir)

    try:
        if args.command == "init-config":
            return init_config(app_dir, args.service_group or args.service_user)
        if args.command == "render":
            sys.stdout.write(
                render_file(
                    args.file, str(app_dir), args.service_user, args.service_group
                )
            )
            return EXIT_OK

        values = load_config(app_dir)
        if args.command == "config-get":
            print(values.get(args.name, ""))
            return EXIT_OK
        if args.command == "check-config":
            problems = check_config(values)
            for problem in problems:
                print(f"config.py: {problem}")
            return EXIT_ERROR if problems else EXIT_OK
        if args.command == "provision-db":
            host = str(values.get("DBHost") or "")
            if host not in LOCAL_HOSTS:
                print(
                    f"DBHost is {host}: a remote database is not created by the installer"
                )
                return EXIT_OK
            for line in provision_database(values, Psql(shlex.split(args.psql))):
                print(line)
            return EXIT_OK
        if args.command == "db-check":
            problems = check_database(values)
            for problem in problems:
                print(f"Database check failed: {problem}")
            return EXIT_ERROR if problems else EXIT_OK
    except Exception as error:
        print(f"{args.command} failed: {type(error).__name__}: {str(error)[:300]}")
        return EXIT_ERROR
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
