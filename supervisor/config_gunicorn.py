# -*-coding:utf-8 -*-
import importlib.util
import multiprocessing
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent


def _load_db_pool():
    """app/modules/db_pool.py has no dependencies: load it without starting the application."""
    spec = importlib.util.spec_from_file_location(
        "nabs_db_pool", _APP_DIR / "app" / "modules" / "db_pool.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _configured_workers():
    """GUNICORN_WORKERS of config.py (None / missing = automatic)."""
    try:
        import config

        return getattr(config, "GUNICORN_WORKERS", None)
    except Exception:
        return None


_db_pool = _load_db_pool()

bind = "127.0.0.1:8000"

# Increase the timeout if the operation takes a long time
timeout = 120

# Use the synchronous worker class if gevent is not needed
worker_class = "sync"

# Number of worker processes: CPUs*2+1, at most 9 unless GUNICORN_WORKERS is set in config.py.
# Every worker has its own database pool, so the number of workers is part of the
# PostgreSQL connection budget (see app/modules/db_pool.py, scripts/check_db_connections.py).
workers = _db_pool.worker_count(multiprocessing.cpu_count(), _configured_workers())

# Remove the threads parameter if gevent is used
# threads = multiprocessing.cpu_count() * 2

# The application is imported once in the master process and then forked.
preload_app = True

# Disable max_requests and max_requests_jitter if they are not needed
max_requests = 1024
max_requests_jitter = 50

# Each process turn-on thread
# threads = multiprocessing.cpu_count() * 2


def post_fork(server, worker):
    """
    With preload_app the application is imported in the MASTER before the fork, and
    importing it already talks to the database (the default admin check). A connection
    that is left in the master's pool would be inherited by EVERY worker: several
    processes would then use one TCP/SSL connection at the same time, which corrupts
    the protocol ("SSL error: decryption failed or bad record mac", random 500 errors).
    Each worker therefore starts with an empty pool; close=False leaves the master's
    own connections alone.
    """
    try:
        from app import app, db

        with app.app_context():
            db.engine.dispose(close=False)
    except Exception as error:  # a failure here must not stop the worker from starting
        server.log.error(
            "post_fork: could not reset the database pool: %s", type(error).__name__
        )
