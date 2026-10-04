"""
TZ 7: the PostgreSQL connection budget, the pool settings and the recovery from
exhausted / broken connections.

The calculation, the URL building, the gunicorn config and the report are tested with
no database at all. The tests of a REAL SQLAlchemy pool (exhaustion, recovery after a
dropped connection) need SQLAlchemy and are skipped when it is not installed.
"""

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pool = load("nabs_db_pool_test", "app/modules/db_pool.py")
check = load("nabs_check_connections", "scripts/check_db_connections.py")

try:
    import sqlalchemy

    # the mock module of nabs_test_stubs has no __version__: only the REAL library counts
    HAVE_SQLALCHEMY = isinstance(getattr(sqlalchemy, "__version__", None), str)
except ImportError:
    HAVE_SQLALCHEMY = False


class TestEngineOptions(unittest.TestCase):
    def test_defaults_are_small_and_self_healing(self):
        options = pool.engine_options({})
        self.assertEqual(options["pool_size"], 2)
        self.assertEqual(options["max_overflow"], 4)
        self.assertEqual(options["pool_timeout"], 60)
        self.assertEqual(options["pool_recycle"], 3600)
        self.assertIs(options["pool_pre_ping"], True)

    def test_an_old_config_without_the_options_works(self):
        self.assertEqual(pool.engine_options(None), pool.engine_options({}))

    def test_values_from_config_are_used(self):
        options = pool.engine_options(
            {
                "DB_POOL_SIZE": 3,
                "DB_MAX_OVERFLOW": 0,
                "DB_POOL_TIMEOUT": 10,
                "DB_POOL_RECYCLE": 600,
            }
        )
        self.assertEqual(
            (
                options["pool_size"],
                options["max_overflow"],
                options["pool_timeout"],
                options["pool_recycle"],
            ),
            (3, 0, 10, 600),
        )

    def test_absurd_values_fall_back_to_the_defaults(self):
        wrong_type = [None, True, "5", 2.5, [], {}]
        for value in wrong_type:
            options = pool.engine_options(
                {
                    "DB_POOL_SIZE": value,
                    "DB_MAX_OVERFLOW": value,
                    "DB_POOL_TIMEOUT": value,
                    "DB_POOL_RECYCLE": value,
                }
            )
            self.assertEqual(options["pool_size"], 2, repr(value))
            self.assertEqual(options["max_overflow"], 4, repr(value))
            self.assertEqual(options["pool_timeout"], 60, repr(value))
            self.assertEqual(options["pool_recycle"], 3600, repr(value))
        out_of_range = {
            "DB_POOL_SIZE": (0, -1, 51, 10**6),
            "DB_MAX_OVERFLOW": (-1, 51, 10**6),
            "DB_POOL_TIMEOUT": (0, -5, 301),
            "DB_POOL_RECYCLE": (0, 59, 86401),
        }
        defaults = {
            "DB_POOL_SIZE": 2,
            "DB_MAX_OVERFLOW": 4,
            "DB_POOL_TIMEOUT": 60,
            "DB_POOL_RECYCLE": 3600,
        }
        keys = {
            "DB_POOL_SIZE": "pool_size",
            "DB_MAX_OVERFLOW": "max_overflow",
            "DB_POOL_TIMEOUT": "pool_timeout",
            "DB_POOL_RECYCLE": "pool_recycle",
        }
        for name, values in out_of_range.items():
            for value in values:
                self.assertEqual(
                    pool.engine_options({name: value})[keys[name]],
                    defaults[name],
                    (name, value),
                )

    def test_pre_ping_cannot_be_switched_off(self):
        self.assertIs(
            pool.engine_options({"DB_POOL_PRE_PING": False})["pool_pre_ping"], True
        )

    def test_the_job_store_pool_is_tiny(self):
        options = pool.jobstore_engine_options()
        self.assertLessEqual(pool.peak_per_process(options), 3)
        self.assertIs(options["pool_pre_ping"], True)


class TestWorkers(unittest.TestCase):
    def test_formula_and_cap(self):
        self.assertEqual(pool.worker_count(1), 3)
        self.assertEqual(pool.worker_count(2), 5)
        self.assertEqual(pool.worker_count(4), 9)
        self.assertEqual(pool.worker_count(8), 9)  # capped
        self.assertEqual(pool.worker_count(64), 9)

    def test_override_from_config(self):
        self.assertEqual(pool.worker_count(4, 3), 3)
        self.assertEqual(pool.worker_count(4, 16), 16)

    def test_a_wrong_override_means_automatic(self):
        for value in (None, 0, -2, 65, "4", 2.5, True):
            self.assertEqual(pool.worker_count(4, value), 9, repr(value))

    def test_never_less_than_one(self):
        self.assertEqual(pool.worker_count(0), 3)
        self.assertEqual(pool.worker_count(None), 3)


class TestBudget(unittest.TestCase):
    def test_the_old_settings_could_exhaust_postgresql(self):
        old = {"pool_size": 30, "max_overflow": 15}
        estimate = pool.estimate_connections(9, old)
        self.assertEqual(estimate["web"], 9 * 45)
        self.assertGreater(estimate["total"], 400)
        available = pool.available_for_nabs(100, 3)
        self.assertEqual(pool.assess(estimate["total"], available)[0], "error")

    def test_the_new_defaults_fit_the_default_postgresql(self):
        estimate = pool.estimate_connections(9, pool.engine_options({}))
        self.assertEqual(estimate["web"], 54)
        self.assertEqual(estimate["scheduler"], 9)  # 6 (Flask pool) + 3 (job store)
        self.assertEqual(estimate["total"], 54 + 9 + 2)
        available = pool.available_for_nabs(100, 3)
        level, _ = pool.assess(estimate["total"], available)
        self.assertEqual(level, "ok")

    def test_other_applications_are_taken_into_account(self):
        estimate = pool.estimate_connections(9, pool.engine_options({}))
        available = pool.available_for_nabs(100, 3, used_by_others=30)
        self.assertEqual(available, 67)
        self.assertEqual(pool.assess(estimate["total"], available)[0], "warning")
        self.assertEqual(
            pool.assess(estimate["total"], pool.available_for_nabs(100, 3, 50))[0],
            "error",
        )

    def test_thresholds(self):
        self.assertEqual(pool.assess(80, 100)[0], "ok")
        self.assertEqual(pool.assess(81, 100)[0], "warning")
        self.assertEqual(pool.assess(100, 100)[0], "warning")
        self.assertEqual(pool.assess(101, 100)[0], "error")
        self.assertEqual(pool.assess(1, 0)[0], "error")

    def test_available_is_never_negative(self):
        self.assertEqual(pool.available_for_nabs(10, 3, 50), 0)

    def test_more_workers_cost_more_connections(self):
        options = pool.engine_options({})
        totals = [pool.estimate_connections(n, options)["total"] for n in (1, 3, 9, 20)]
        self.assertEqual(totals, sorted(totals))


class TestDatabaseUrl(unittest.TestCase):
    NASTY = [
        "p@ss:w/ord%#?&=+ ",
        "пароль",
        "a'b\"c;--",
        "%41%2F",
        "x" * 200,
        "@@@",
        "::",
        "///",
    ]

    def test_plain_values(self):
        self.assertEqual(
            pool.database_url("nabs", "secret", "localhost", "5432", "nabs"),
            "postgresql://nabs:secret@localhost:5432/nabs",
        )

    def test_every_password_survives_the_round_trip(self):
        for password in self.NASTY:
            url = pool.database_url("nabs", password, "db.example.org", 5432, "nabs")
            parts = urlsplit(url)
            self.assertEqual(unquote(parts.password), password, password)
            self.assertEqual(unquote(parts.username), "nabs")
            self.assertEqual(parts.hostname, "db.example.org")
            self.assertEqual(parts.port, 5432)
            self.assertEqual(parts.path, "/nabs")

    def test_user_and_database_are_encoded_too(self):
        url = pool.database_url("us@er", "p", "localhost", 5432, "my db/1")
        parts = urlsplit(url)
        self.assertEqual(unquote(parts.username), "us@er")
        self.assertEqual(unquote(parts.path), "/my db/1")

    def test_ipv6_host(self):
        self.assertIn("@[::1]:5432/", pool.database_url("u", "p", "::1", 5432, "n"))

    @unittest.skipUnless(HAVE_SQLALCHEMY, "SQLAlchemy is not installed")
    def test_sqlalchemy_reads_the_password_back_unchanged(self):
        from sqlalchemy.engine import make_url

        for password in self.NASTY:
            url = make_url(
                pool.database_url("nabs", password, "localhost", 5432, "nabs")
            )
            self.assertEqual(url.password, password, password)
            self.assertEqual(
                (url.host, url.port, url.database), ("localhost", 5432, "nabs")
            )


class TestApplicationConfiguration(unittest.TestCase):
    """app/configuration.py really uses the pool module (checked in the source)."""

    def setUp(self):
        self.source = (ROOT / "app" / "configuration.py").read_text()

    def test_no_hand_made_url_and_no_hard_coded_pool(self):
        self.assertNotIn("postgresql://{DBUser}", self.source)
        self.assertNotIn('"pool_size": 30', self.source)
        self.assertIn("database_url(", self.source)
        self.assertIn("engine_options(", self.source)

    def test_other_places_do_not_build_the_url_by_hand_either(self):
        helpers = (ROOT / "app" / "modules" / "helpers.py").read_text()
        self.assertNotIn("postgresql://{DBUser}", helpers)
        self.assertIn("database_url(", helpers)

    def test_the_scheduler_job_store_has_its_own_small_pool(self):
        scheduler = (ROOT / "scheduler_runner.py").read_text()
        self.assertIn("jobstore_engine_options()", scheduler)


class TestGunicornConfig(unittest.TestCase):
    def setUp(self):
        self.module = load("nabs_gunicorn_test", "supervisor/config_gunicorn.py")

    def test_workers_follow_the_budget(self):
        self.assertIsInstance(self.module.workers, int)
        self.assertGreaterEqual(self.module.workers, 1)
        self.assertLessEqual(
            self.module.workers, 9
        )  # config.py of the test has no override

    def test_the_old_formula_is_gone(self):
        text = (ROOT / "supervisor" / "config_gunicorn.py").read_text()
        self.assertNotIn("workers = multiprocessing.cpu_count() * 2 + 1", text)

    def test_the_worker_starts_with_an_empty_pool(self):
        app, db = MagicMock(), MagicMock()
        fake_app_module = types.ModuleType("app")
        fake_app_module.app, fake_app_module.db = app, db
        with patch.dict(sys.modules, {"app": fake_app_module}):
            self.module.post_fork(MagicMock(), MagicMock())
        app.app_context.assert_called_once()
        db.engine.dispose.assert_called_once_with(close=False)

    def test_a_failing_reset_does_not_stop_the_worker(self):
        app, db = MagicMock(), MagicMock()
        db.engine.dispose.side_effect = RuntimeError("boom")
        fake_app_module = types.ModuleType("app")
        fake_app_module.app, fake_app_module.db = app, db
        server = MagicMock()
        with patch.dict(sys.modules, {"app": fake_app_module}):
            self.module.post_fork(server, MagicMock())  # must not raise
        server.log.error.assert_called_once()

    def test_the_hook_preloads_nothing_new(self):
        self.assertTrue(self.module.preload_app)
        self.assertTrue(callable(self.module.post_fork))


class TestConnectionReport(unittest.TestCase):
    SERVER = {"max_connections": 100, "reserved": 3, "nabs_now": 7, "others_now": 2}

    def report(self, cpus=4, settings=None, **kw):
        return check.build_report(pool, settings or {}, cpus, dict(self.SERVER), **kw)

    def test_default_settings_are_ok(self):
        lines, code = self.report()
        self.assertEqual(code, 0)
        self.assertIn("OK", lines[-1])
        self.assertIn("web 54 + scheduler 9 + admin 2 = 65", " ".join(lines))

    def test_the_old_pool_settings_are_an_error(self):
        lines, code = self.report(
            settings={"DB_POOL_SIZE": 30, "DB_MAX_OVERFLOW": 15},
        )
        # 30 is accepted by the module (limit 50), the total does not fit into 100
        self.assertEqual(code, 2)
        self.assertIn("ERROR", lines[-1])

    def test_other_clients_can_be_given_by_the_administrator(self):
        # worst case 65; available = 100 - 3 - other clients
        self.assertEqual(self.report(other_clients=0)[1], 0)  # 97 available: ok
        self.assertEqual(
            self.report(other_clients=25)[1], 1
        )  # 72 available: 65 > 80%: warning
        self.assertEqual(
            self.report(other_clients=40)[1], 2
        )  # 57 available: does not fit
        self.assertEqual(self.report(other_clients=60)[1], 2)

    def test_the_worker_override(self):
        lines, _ = self.report(workers_override=3)
        self.assertIn("3 gunicorn workers", lines[1])

    def test_the_report_never_contains_secrets(self):
        lines, _ = self.report(settings={"DB_POOL_SIZE": 2})
        self.assertNotIn("password", " ".join(lines).lower())

    def test_server_numbers_come_from_the_right_queries(self):
        answers = iter([("100",), ("3",), (7, 2)])
        queries = []

        class Cursor:
            def execute(self, sql, params=None):
                queries.append(sql)

            def fetchone(self):
                return next(answers)

        server = check.read_server(Cursor(), "nabs", "nabs")
        self.assertEqual(
            server,
            {"max_connections": 100, "reserved": 3, "nabs_now": 7, "others_now": 2},
        )
        self.assertEqual(queries[0], "SHOW max_connections")
        self.assertEqual(queries[1], "SHOW superuser_reserved_connections")
        self.assertIn("pg_stat_activity", queries[2])

    def test_a_connection_error_is_reported_without_the_password(self):
        config = types.ModuleType("config")
        config.DBPassword = "Sup3r-Secret"
        printed = []
        with patch.dict(sys.modules, {"config": config}), patch.object(
            check,
            "connect_from_config",
            side_effect=RuntimeError("bad Sup3r-Secret here"),
        ), patch(
            "builtins.print",
            side_effect=lambda *a: printed.append(" ".join(map(str, a))),
        ):
            code = check.main([])
        self.assertEqual(code, 3)
        self.assertNotIn("Sup3r-Secret", " ".join(printed))


@unittest.skipUnless(
    HAVE_SQLALCHEMY, "SQLAlchemy is not installed: run in the project venv"
)
class TestRealPool(unittest.TestCase):
    """A real SQLAlchemy QueuePool (SQLite file) with the structure of the NABS options."""

    def setUp(self):
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import QueuePool

        self.text = text
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.url = f"sqlite:///{self.dir.name}/pool.db"
        self.make = lambda **kw: create_engine(self.url, poolclass=QueuePool, **kw)

    def test_exhaustion_is_an_error_not_a_hang(self):
        from sqlalchemy.exc import TimeoutError as PoolTimeout

        engine = self.make(pool_size=1, max_overflow=1, pool_timeout=0.2)
        first, second = (
            engine.connect(),
            engine.connect(),
        )  # pool_size + max_overflow = 2
        with self.assertRaises(PoolTimeout):
            engine.connect()
        first.close()  # a connection is returned: the next request works again
        with engine.connect() as again:
            self.assertEqual(again.execute(self.text("select 1")).scalar(), 1)
        second.close()
        engine.dispose()

    def test_the_pool_does_not_grow_beyond_its_limit(self):
        options = pool.engine_options({"DB_POOL_SIZE": 2, "DB_MAX_OVERFLOW": 1})
        engine = self.make(
            pool_size=options["pool_size"],
            max_overflow=options["max_overflow"],
            pool_timeout=0.1,
        )
        held = [engine.connect() for _ in range(3)]
        self.assertEqual(engine.pool.checkedout(), 3)
        with self.assertRaises(Exception):
            engine.connect()
        for connection in held:
            connection.close()
        engine.dispose()

    def test_a_dropped_connection_is_replaced_not_reused(self):
        engine = self.make(pool_size=1, max_overflow=0, pool_pre_ping=True)
        connection = engine.connect()
        connection.connection.dbapi_connection.close()  # the server drops the connection
        connection.close()
        with engine.connect() as healed:  # pre-ping notices and opens a new one
            self.assertEqual(healed.execute(self.text("select 1")).scalar(), 1)
        engine.dispose()

    def test_dispose_gives_a_fresh_pool(self):
        engine = self.make(pool_size=1, max_overflow=0)
        with engine.connect() as connection:
            connection.execute(self.text("select 1"))
        engine.dispose(close=False)  # what post_fork does in a worker
        with engine.connect() as connection:
            self.assertEqual(connection.execute(self.text("select 1")).scalar(), 1)
        engine.dispose()

    def test_an_unreachable_database_is_an_error(self):
        from sqlalchemy import create_engine
        from sqlalchemy.exc import OperationalError

        engine = create_engine("sqlite:////nonexistent-directory/x/db.sqlite")
        with self.assertRaises(OperationalError):
            engine.connect()


if __name__ == "__main__":
    unittest.main()
