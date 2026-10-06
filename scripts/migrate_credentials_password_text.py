#!/usr/bin/env python3
"""
Widen credentials.credentials_password from VARCHAR(100) to TEXT.

Why: the column holds a Fernet token, which is about 1.4 times longer than the
password (a 15 byte password = 100 characters, a 16 byte one = 120). With
VARCHAR(100) PostgreSQL refuses every longer password with "value too long".

What it does:   ALTER TABLE credentials ALTER COLUMN credentials_password TYPE TEXT
What it never does: read, decrypt, re-encrypt or rewrite a password. Existing values
are kept byte for byte. PostgreSQL changes VARCHAR(n) -> TEXT without rewriting rows.
Safe to run again: if the column is already TEXT nothing is changed.

    python scripts/migrate_credentials_password_text.py           # dry run: only look
    python scripts/migrate_credentials_password_text.py --apply   # change the column

Run it from the NABS directory (it reads the DB* settings of config.py).
Take a backup first:  pg_dump -t credentials <database> > credentials_backup.sql

Rollback: not needed for the application - the old code works with a TEXT column.
To restore the data use the backup. Do NOT convert the column back to VARCHAR(100)
after long passwords were saved: it would fail or cut them.
"""

import argparse
import sys

TABLE = "credentials"
COLUMN = "credentials_password"

COLUMN_INFO_SQL = (
    "SELECT data_type, character_maximum_length FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s"
)
ALTER_SQL = f'ALTER TABLE "{TABLE}" ALTER COLUMN "{COLUMN}" TYPE TEXT'
STATS_SQL = f'SELECT count(*), coalesce(max(length("{COLUMN}")), 0) FROM "{TABLE}"'

MISSING = "missing"  # no such table / column: nothing to migrate (new database)
DONE = "done"  # already TEXT
NEEDED = "needed"  # VARCHAR(n)
UNEXPECTED = "unexpected"  # some other type: do not touch


def column_state(cursor):
    """Returns (state, data_type, max_length) of the column."""
    cursor.execute(COLUMN_INFO_SQL, (TABLE, COLUMN))
    row = cursor.fetchone()
    if row is None:
        return MISSING, None, None
    data_type, length = row[0], row[1]
    if data_type == "text":
        return DONE, data_type, length
    if data_type == "character varying":
        return NEEDED, data_type, length
    return UNEXPECTED, data_type, length


def migrate(connection, apply: bool, out=print) -> int:
    """
    Looks at the column and, with apply=True, widens it. Returns an exit code:
    0 = fine (changed, or nothing to do / dry run), 1 = error, 2 = unexpected schema.
    """
    cursor = connection.cursor()
    state, data_type, length = column_state(cursor)

    if state == MISSING:
        out(f"Table {TABLE}.{COLUMN} does not exist yet: nothing to migrate.")
        out("(A new database gets the TEXT column from the models.)")
        return 0
    if state == DONE:
        out(f"{TABLE}.{COLUMN} is already TEXT: nothing to do.")
        return 0
    if state == UNEXPECTED:
        out(f"{TABLE}.{COLUMN} has the unexpected type '{data_type}': not changed.")
        return 2

    cursor.execute(STATS_SQL)
    count, longest = cursor.fetchone()
    out(
        f"{TABLE}.{COLUMN} is VARCHAR({length}); {count} profile(s), the longest value"
        f" is {longest} characters."
    )
    if not apply:
        out("Dry run: nothing was changed. Run again with --apply to widen the column.")
        return 0

    try:
        cursor.execute("SET LOCAL lock_timeout = '10s'")  # do not wait for a long lock
        cursor.execute(ALTER_SQL)
        state_after, _, _ = column_state(cursor)
        if state_after != DONE:
            raise RuntimeError(f"the column is still not TEXT ({state_after})")
        cursor.execute(STATS_SQL)
        count_after, longest_after = cursor.fetchone()
        if (count_after, longest_after) != (count, longest):
            raise RuntimeError("the data changed during the migration")
        connection.commit()
    except Exception as error:
        connection.rollback()
        out(
            f"Migration FAILED and was rolled back, nothing was changed: "
            f"{type(error).__name__}: {_redact(str(error))[:200]}"
        )
        return 1
    out(f"Done: {TABLE}.{COLUMN} is TEXT now; {count_after} profile(s) kept unchanged.")
    return 0


def connect_from_config():
    """Connects with the DB* settings of config.py. Never prints the password."""
    import config  # the NABS directory must be the current directory
    import psycopg2

    return psycopg2.connect(
        host=config.DBHost,
        port=config.DBPort,
        dbname=config.DBName,
        user=config.DBUser,
        password=config.DBPassword,
        connect_timeout=10,
    )


def _redact(text: str) -> str:
    """Masks the database password if a driver ever puts it into an error message."""
    try:
        import config

        password = str(getattr(config, "DBPassword", "") or "")
    except Exception:
        password = ""
    return text.replace(password, "***") if password else text


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="change the column")
    args = parser.parse_args(argv)
    try:
        connection = connect_from_config()
    except Exception as error:
        # the class and the first line only: never a connection string or a password
        first_line = _redact((str(error).strip().splitlines() or [""])[0])[:200]
        print(f"Cannot connect to the database: {type(error).__name__}: {first_line}")
        return 1
    try:
        return migrate(connection, apply=args.apply)
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
