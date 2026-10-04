#!/usr/bin/env python3
"""
Checks the worst-case number of PostgreSQL connections of NABS against what the server allows.

    python scripts/check_db_connections.py [--other-clients N] [--workers N]

Run it from the NABS directory (it reads config.py). It only reads: it changes nothing,
neither in NABS nor in PostgreSQL.

Exit code: 0 = ok, 1 = warning (little room left), 2 = the worst case does not fit,
3 = cannot connect to the database.

The worst case is every pool full at the same moment:
    gunicorn workers x (pool_size + max_overflow)
  + scheduler (its Flask-SQLAlchemy pool + the APScheduler job store pool)
  + a small reserve for flask db, scripts and a psql session.
Other applications that use the same PostgreSQL are NOT known to this script: pass
--other-clients with the number of connections they may use, otherwise the number of their
sessions at this moment is used.
"""

import argparse
import importlib.util
import multiprocessing
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


def load_db_pool():
    spec = importlib.util.spec_from_file_location(
        "nabs_db_pool", APP_DIR / "app" / "modules" / "db_pool.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_server(cursor, user: str, database: str) -> dict:
    """max_connections, the superuser reserve and who uses the connections now."""
    cursor.execute("SHOW max_connections")
    max_connections = int(cursor.fetchone()[0])
    cursor.execute("SHOW superuser_reserved_connections")
    reserved = int(cursor.fetchone()[0])
    cursor.execute(
        "SELECT count(*) FILTER (WHERE usename = %s AND datname = %s), "
        "count(*) FILTER (WHERE NOT (usename = %s AND datname = %s)) "
        "FROM pg_stat_activity WHERE backend_type = 'client backend'",
        (user, database, user, database),
    )
    nabs_now, others_now = cursor.fetchone()
    return {
        "max_connections": max_connections,
        "reserved": reserved,
        "nabs_now": int(nabs_now),
        "others_now": int(others_now),
    }


def build_report(
    pool,
    settings: dict,
    cpu_count: int,
    server: dict,
    workers_override=None,
    other_clients=None,
) -> tuple:
    """
    (lines, exit_code) from the settings of config.py (`settings`: DB_POOL_*,
    GUNICORN_WORKERS) and the numbers of the server. Pure: no database access here.
    """
    options = pool.engine_options(settings)
    workers = pool.worker_count(
        cpu_count,
        workers_override if workers_override else settings.get("GUNICORN_WORKERS"),
    )
    estimate = pool.estimate_connections(workers, options)
    others = server["others_now"] if other_clients is None else other_clients
    available = pool.available_for_nabs(
        server["max_connections"], server["reserved"], others
    )
    level, message = pool.assess(estimate["total"], available)
    lines = [
        f"PostgreSQL: max_connections={server['max_connections']}, reserved for superusers="
        f"{server['reserved']}; in use now: NABS {server['nabs_now']}, other clients {server['others_now']}",
        f"NABS: {workers} gunicorn workers on {cpu_count} CPU(s); per process pool_size="
        f"{options['pool_size']} + max_overflow={options['max_overflow']} = {estimate['per_process']}"
        f" (pool_timeout={options['pool_timeout']}s, pool_recycle={options['pool_recycle']}s)",
        f"Worst case: web {estimate['web']} + scheduler {estimate['scheduler']} + admin "
        f"{estimate['admin']} = {estimate['total']}",
        f"Available for NABS: {server['max_connections']} - {server['reserved']} (reserved) - "
        f"{others} (other clients{' as given' if other_clients is not None else ' now'}) = {available}",
        f"{level.upper()}: {message}",
    ]
    return lines, {"ok": 0, "warning": 1, "error": 2}[level]


def connect_from_config():
    import config  # the NABS directory must be the current directory
    import psycopg2

    return config, psycopg2.connect(
        host=config.DBHost,
        port=config.DBPort,
        dbname=config.DBName,
        user=config.DBUser,
        password=config.DBPassword,
        connect_timeout=10,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--other-clients",
        type=int,
        default=None,
        help="connections other applications may use (default: their sessions now)",
    )
    parser.add_argument(
        "--workers", type=int, default=None, help="test another worker count"
    )
    args = parser.parse_args(argv)
    try:
        config, connection = connect_from_config()
    except Exception as error:
        text = (str(error).strip().splitlines() or [""])[0]
        try:
            import config as loaded

            password = str(getattr(loaded, "DBPassword", "") or "")
            text = text.replace(password, "***") if password else text
        except Exception:
            pass
        print(f"Cannot connect to the database: {type(error).__name__}: {text[:200]}")
        return 3
    try:
        server = read_server(
            connection.cursor(), str(config.DBUser), str(config.DBName)
        )
    finally:
        connection.close()
    settings = {
        name: getattr(config, name, None)
        for name in (
            "DB_POOL_SIZE",
            "DB_MAX_OVERFLOW",
            "DB_POOL_TIMEOUT",
            "DB_POOL_RECYCLE",
            "GUNICORN_WORKERS",
        )
    }
    lines, code = build_report(
        load_db_pool(),
        settings,
        multiprocessing.cpu_count(),
        server,
        args.workers,
        args.other_clients,
    )
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
