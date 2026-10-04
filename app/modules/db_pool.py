"""
Database connection settings and the connection budget of NABS.

No imports from the application: this module is used by app/configuration.py, by
supervisor/config_gunicorn.py and by scripts/check_db_connections.py, which load it
before (or without) the application.

THE BUDGET.  Every process has its OWN pool, and a pool may open at most
pool_size + max_overflow connections:

    web:        workers x (pool_size + max_overflow)
    scheduler:  one Flask-SQLAlchemy pool + the APScheduler job store pool
    admin:      flask db ..., scripts, psql sessions of the administrator

A gunicorn "sync" worker serves ONE request at a time, so it normally needs one
connection. A backup (the scheduler, or "Run backup now" in a web worker) runs up to
NORNIR_WORKERS = 20 threads; each one works inside its own `with app.app_context()`.
That used to keep a connection "idle in transaction" for the whole SSH session
(minutes), so up to ~40 connections were held per backup and the pools had to be huge
(pool_size=30 + max_overflow=15, times 9 workers = 405 possible connections against
the PostgreSQL default max_connections = 100; and every worker KEPT up to 30 idle
connections after a burst until pool_recycle).
backuper.py now returns the connection to the pool before the SSH session, so a task
holds a connection only for its short queries. Threads that find the pool busy simply
wait for a free connection (pool_timeout) instead of each holding one for minutes.
"""

from typing import Mapping, Optional
from urllib.parse import quote

# ---- per-process pool of the web workers and of the scheduler's Flask-SQLAlchemy engine
DEFAULT_POOL_SIZE = 2
DEFAULT_MAX_OVERFLOW = 4
DEFAULT_POOL_TIMEOUT = 60  # seconds to wait for a free connection before an error
DEFAULT_POOL_RECYCLE = 3600  # seconds; a connection older than this is replaced

# ---- the APScheduler job store has a pool of its own (separate engine)
JOBSTORE_POOL_SIZE = 1
JOBSTORE_MAX_OVERFLOW = 2

# ---- gunicorn
DEFAULT_MAX_WORKERS = 9  # CPUs*2+1 on 4 CPUs; more only if you set GUNICORN_WORKERS

# ---- PostgreSQL
DEFAULT_MAX_CONNECTIONS = 100
DEFAULT_SUPERUSER_RESERVED = 3
ADMIN_RESERVE = 2  # connections kept for flask db, scripts and a psql session
NORNIR_WORKERS = 20  # num_workers of the threaded Nornir runner (helpers.py)
WARN_RATIO = 0.8  # of the connections that are really available for NABS

OPTION_LIMITS = {
    "pool_size": (1, 50),
    "max_overflow": (0, 50),
    "pool_timeout": (1, 300),
    "pool_recycle": (60, 86400),
}


def _integer_in_range(value, low: int, high: int, default: int) -> int:
    """value if it is a real integer in [low, high], otherwise the default."""
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if low <= value <= high else default


def engine_options(values: Optional[Mapping] = None) -> dict:
    """
    SQLAlchemy engine options for the web workers / the scheduler. `values` holds the
    optional DB_POOL_* settings of config.py; a missing, wrong or absurd value falls
    back to the default (the application must start with an old config.py).
    """
    values = values or {}
    return {
        "pool_size": _integer_in_range(
            values.get("DB_POOL_SIZE"), *OPTION_LIMITS["pool_size"], DEFAULT_POOL_SIZE
        ),
        "max_overflow": _integer_in_range(
            values.get("DB_MAX_OVERFLOW"),
            *OPTION_LIMITS["max_overflow"],
            DEFAULT_MAX_OVERFLOW,
        ),
        "pool_timeout": _integer_in_range(
            values.get("DB_POOL_TIMEOUT"),
            *OPTION_LIMITS["pool_timeout"],
            DEFAULT_POOL_TIMEOUT,
        ),
        "pool_recycle": _integer_in_range(
            values.get("DB_POOL_RECYCLE"),
            *OPTION_LIMITS["pool_recycle"],
            DEFAULT_POOL_RECYCLE,
        ),
        # a connection that PostgreSQL closed (restart, idle timeout, failover) is
        # detected before use and replaced instead of failing the request
        "pool_pre_ping": True,
    }


def jobstore_engine_options() -> dict:
    """The job store only reads / writes a few rows: a tiny pool is enough."""
    return {
        "pool_size": JOBSTORE_POOL_SIZE,
        "max_overflow": JOBSTORE_MAX_OVERFLOW,
        "pool_timeout": DEFAULT_POOL_TIMEOUT,
        "pool_recycle": DEFAULT_POOL_RECYCLE,
        "pool_pre_ping": True,
    }


def worker_count(cpu_count: int, override=None, cap: int = DEFAULT_MAX_WORKERS) -> int:
    """
    gunicorn workers: GUNICORN_WORKERS of config.py when it is a sensible integer,
    otherwise CPUs*2+1 limited to `cap` (a 32 CPU host must not start 65 processes,
    each with a pool).
    """
    if (
        not isinstance(override, bool)
        and isinstance(override, int)
        and 1 <= override <= 64
    ):
        return override
    cpus = cpu_count if isinstance(cpu_count, int) and cpu_count > 0 else 1
    return max(1, min(cpus * 2 + 1, cap))


def peak_per_process(options: Mapping) -> int:
    """The most connections one process can hold open."""
    return int(options["pool_size"]) + int(options["max_overflow"])


def estimate_connections(
    workers: int,
    options: Mapping,
    scheduler_processes: int = 1,
    jobstore_options: Optional[Mapping] = None,
    admin_reserve: int = ADMIN_RESERVE,
) -> dict:
    """The worst case (every pool full at the same moment) split into its parts."""
    jobstore = jobstore_options or jobstore_engine_options()
    web = workers * peak_per_process(options)
    scheduler = scheduler_processes * (
        peak_per_process(options) + peak_per_process(jobstore)
    )
    return {
        "web": web,
        "scheduler": scheduler,
        "admin": admin_reserve,
        "total": web + scheduler + admin_reserve,
        "per_process": peak_per_process(options),
        "workers": workers,
    }


def available_for_nabs(
    max_connections: int, reserved: int, used_by_others: int = 0
) -> int:
    """Connections NABS may use: the limit minus the superuser reserve and other clients."""
    return max(0, max_connections - reserved - used_by_others)


def assess(estimate_total: int, available: int) -> tuple:
    """('ok' | 'warning' | 'error', message)."""
    if available <= 0:
        return "error", "PostgreSQL has no connections left for NABS"
    if estimate_total > available:
        return (
            "error",
            f"worst case {estimate_total} connections > {available} available: under load "
            "PostgreSQL would refuse connections (too many clients). Lower the number of "
            "workers or DB_POOL_SIZE / DB_MAX_OVERFLOW, or raise max_connections "
            "after checking the memory of the server.",
        )
    if estimate_total > available * WARN_RATIO:
        return (
            "warning",
            f"worst case {estimate_total} of {available} available connections "
            f"(more than {int(WARN_RATIO * 100)}%): little room left for other applications",
        )
    return "ok", f"worst case {estimate_total} of {available} available connections"


def database_url(user, password, host, port, name) -> str:
    """
    postgresql://user:password@host:port/name with every part percent-encoded: a password
    with @ / : % # ? or a space would otherwise break the URL (SQLAlchemy decodes it).
    """
    host = str(host)
    if ":" in host and not host.startswith("["):  # an IPv6 address
        host = f"[{host}]"
    return (
        f"postgresql://{quote(str(user), safe='')}:{quote(str(password), safe='')}"
        f"@{host}:{port}/{quote(str(name), safe='')}"
    )
