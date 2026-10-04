"""
TZ 6: the logic of the installer (scripts/nabs_setup.py): config.py, the PostgreSQL role and
database, the connection check and the rendering of the unit / nginx files.
No PostgreSQL is needed: psql is replaced by a recording fake.
"""

import importlib.util
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "nabs_setup", ROOT / "scripts" / "nabs_setup.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def make_app_dir():
    directory = Path(tempfile.mkdtemp(prefix="nabs-setup-"))
    shutil.copy(ROOT / "config_example.py", directory / "config_example.py")
    return directory


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.dir = make_app_dir()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)


class TestInitConfig(TempDirCase):
    def test_creates_config_with_generated_secrets(self):
        self.assertEqual(setup.init_config(self.dir), setup.EXIT_OK)
        values = setup.load_config(self.dir)
        self.assertGreaterEqual(len(values["TOKEN"]), 32)
        self.assertGreaterEqual(len(values["CREDENTIALS_ENCRYPTION_KEY"]), 32)
        self.assertGreaterEqual(len(values["DBPassword"]), 24)
        self.assertNotEqual(values["TOKEN"], values["CREDENTIALS_ENCRYPTION_KEY"])
        self.assertNotEqual(values["DBPassword"], "nabs")
        self.assertEqual(setup.check_config(values), [])

    def test_database_names_are_those_of_the_example_and_the_readme(self):
        setup.init_config(self.dir)
        values = setup.load_config(self.dir)
        self.assertEqual((values["DBName"], values["DBUser"]), ("nabs", "nabs"))
        self.assertEqual(values["DBHost"], "localhost")
        self.assertEqual(str(values["DBPort"]), "5432")

    def test_the_rest_of_the_example_is_copied_unchanged(self):
        setup.init_config(self.dir)
        example = (self.dir / "config_example.py").read_text().splitlines()
        created = (self.dir / "config.py").read_text().splitlines()
        self.assertEqual(len(example), len(created))
        changed = [a for a, b in zip(example, created) if a != b]
        self.assertEqual(
            len(changed), 3
        )  # DBPassword, TOKEN, CREDENTIALS_ENCRYPTION_KEY

    def test_the_file_is_not_world_readable(self):
        setup.init_config(self.dir)
        mode = stat.S_IMODE(os.stat(self.dir / "config.py").st_mode)
        self.assertEqual(mode & 0o007, 0)
        self.assertEqual(mode & 0o600, 0o600)

    def test_an_existing_config_is_never_overwritten(self):
        custom = '# my own settings\nTOKEN = "my-token"\nCREDENTIALS_ENCRYPTION_KEY = "my-key"\n'
        (self.dir / "config.py").write_text(custom)
        self.assertEqual(setup.init_config(self.dir), setup.EXIT_EXISTS)
        self.assertEqual((self.dir / "config.py").read_text(), custom)

    def test_running_twice_keeps_the_same_secrets(self):
        setup.init_config(self.dir)
        first = (self.dir / "config.py").read_bytes()
        key = setup.load_config(self.dir)["CREDENTIALS_ENCRYPTION_KEY"]
        for _ in range(3):
            self.assertEqual(setup.init_config(self.dir), setup.EXIT_EXISTS)
        self.assertEqual((self.dir / "config.py").read_bytes(), first)
        self.assertEqual(setup.load_config(self.dir)["CREDENTIALS_ENCRYPTION_KEY"], key)

    def test_two_installations_get_different_secrets(self):
        other = make_app_dir()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        setup.init_config(self.dir)
        setup.init_config(other)
        a, b = setup.load_config(self.dir), setup.load_config(other)
        for name in ("TOKEN", "CREDENTIALS_ENCRYPTION_KEY", "DBPassword"):
            self.assertNotEqual(a[name], b[name])

    def test_replacement_is_safe_for_quotes_and_backslashes(self):
        text = 'TOKEN = ""\nOTHER = 1\n'
        result = setup._replace_assignment(text, "TOKEN", "a\"b\\c'd&\\1")
        namespace = {}
        exec(result, namespace)
        self.assertEqual(namespace["TOKEN"], "a\"b\\c'd&\\1")
        self.assertEqual(namespace["OTHER"], 1)

    def test_a_template_without_the_assignment_is_an_error(self):
        with self.assertRaises(ValueError):
            setup._replace_assignment("X = 1\n", "TOKEN", "v")


class TestCheckConfig(unittest.TestCase):
    GOOD = {
        "TOKEN": "t" * 32,
        "CREDENTIALS_ENCRYPTION_KEY": "k" * 32,
        "DBHost": "localhost",
        "DBPort": "5432",
        "DBName": "nabs",
        "DBUser": "nabs",
        "DBPassword": "secret",
    }

    def test_good(self):
        self.assertEqual(setup.check_config(self.GOOD), [])

    def test_empty_missing_or_short_secrets(self):
        for name in ("TOKEN", "CREDENTIALS_ENCRYPTION_KEY"):
            for bad in ("", "short", None, 123):
                values = dict(self.GOOD, **{name: bad})
                problems = setup.check_config(values)
                self.assertTrue(any(name in p for p in problems), (name, bad))
            values = dict(self.GOOD)
            del values[name]
            self.assertTrue(setup.check_config(values))

    def test_the_key_must_differ_from_the_token(self):
        values = dict(self.GOOD, CREDENTIALS_ENCRYPTION_KEY=self.GOOD["TOKEN"])
        self.assertTrue(any("differ" in p for p in setup.check_config(values)))

    def test_database_settings_are_required(self):
        for name in ("DBHost", "DBPort", "DBName", "DBUser", "DBPassword"):
            values = dict(self.GOOD, **{name: ""})
            self.assertTrue(any(name in p for p in setup.check_config(values)), name)


class TestSqlQuoting(unittest.TestCase):
    def test_identifiers(self):
        self.assertEqual(setup.sql_ident("nabs"), '"nabs"')
        self.assertEqual(setup.sql_ident('we"ird'), '"we""ird"')
        for bad in ("", "a\x00b"):
            with self.assertRaises(ValueError):
                setup.sql_ident(bad)

    def test_literals(self):
        self.assertEqual(setup.sql_literal("secret"), "'secret'")
        self.assertEqual(setup.sql_literal("it's"), "'it''s'")
        self.assertEqual(setup.sql_literal("a\\b"), "E'a\\\\b'")
        self.assertEqual(setup.sql_literal("a\\'b"), "E'a\\\\''b'")
        with self.assertRaises(ValueError):
            setup.sql_literal("a\x00b")

    def test_a_hostile_value_stays_inside_the_literal(self):
        literal = setup.sql_literal("x'; DROP DATABASE nabs; --")
        self.assertEqual(literal, "'x''; DROP DATABASE nabs; --'")


class FakePsql:
    """Answers the questions of provision_database from a pretend server."""

    def __init__(self, roles=(), databases=(), owner=None):
        self.roles, self.databases, self.owner = set(roles), set(databases), owner
        self.statements = []  # (sql, dbname)

    def run(self, sql, dbname=None):
        self.statements.append((sql, dbname))
        if sql.startswith("SELECT 1 FROM pg_roles"):
            return "1" if any(f"'{r}'" in sql for r in self.roles) else ""
        if sql.startswith("SELECT 1 FROM pg_database"):
            return "1" if any(f"'{d}'" in sql for d in self.databases) else ""
        if sql.startswith("SELECT pg_get_userbyid"):
            return self.owner or ""
        return ""

    def writes(self):
        return [s for s, _ in self.statements if not s.startswith("SELECT")]


VALUES = {"DBName": "nabs", "DBUser": "nabs", "DBPassword": "S3cret-pass"}


class TestProvisionDatabase(unittest.TestCase):
    def test_a_new_server_gets_a_role_and_a_database_owned_by_it(self):
        psql = FakePsql()
        done = setup.provision_database(VALUES, psql)
        self.assertEqual(
            psql.writes(),
            [
                "CREATE ROLE \"nabs\" LOGIN PASSWORD 'S3cret-pass';",
                'CREATE DATABASE "nabs" OWNER "nabs";',
            ],
        )
        self.assertEqual(len(done), 2)

    def test_the_database_owner_is_the_application_role(self):
        # PostgreSQL 15+: only the owner may create tables in schema public
        psql = FakePsql()
        setup.provision_database(
            dict(VALUES, DBName="nabs_db", DBUser="nabs_user"), psql
        )
        self.assertIn('CREATE DATABASE "nabs_db" OWNER "nabs_user";', psql.writes())

    def test_an_existing_installation_is_not_touched(self):
        psql = FakePsql(roles={"nabs"}, databases={"nabs"}, owner="nabs")
        self.assertEqual(setup.provision_database(VALUES, psql), [])
        self.assertEqual(psql.writes(), [])

    def test_an_existing_role_keeps_its_password(self):
        psql = FakePsql(roles={"nabs"})
        setup.provision_database(VALUES, psql)
        self.assertEqual(psql.writes(), ['CREATE DATABASE "nabs" OWNER "nabs";'])
        self.assertFalse(any("PASSWORD" in s for s in psql.writes()))

    def test_an_existing_database_of_another_owner_is_only_opened_additively(self):
        psql = FakePsql(roles={"nabs"}, databases={"nabs"}, owner="postgres")
        done = setup.provision_database(VALUES, psql)
        self.assertEqual(
            psql.writes(),
            [
                'GRANT ALL PRIVILEGES ON DATABASE "nabs" TO "nabs";',
                'GRANT ALL ON SCHEMA public TO "nabs";',
            ],
        )
        self.assertEqual(
            psql.statements[-1][1], "nabs"
        )  # the schema grant runs IN the database
        self.assertEqual(len(done), 1)

    def test_nothing_is_ever_dropped_or_altered(self):
        for server in (
            FakePsql(),
            FakePsql(roles={"nabs"}),
            FakePsql(roles={"nabs"}, databases={"nabs"}, owner="x"),
        ):
            setup.provision_database(VALUES, server)
            for sql in server.writes():
                self.assertFalse(
                    sql.upper().startswith(("DROP", "ALTER", "TRUNCATE", "DELETE")), sql
                )

    def test_running_twice_creates_nothing_the_second_time(self):
        psql = FakePsql()
        setup.provision_database(VALUES, psql)
        psql.roles.add("nabs")
        psql.databases.add("nabs")
        psql.owner = "nabs"
        psql.statements.clear()
        self.assertEqual(setup.provision_database(VALUES, psql), [])
        self.assertEqual(psql.writes(), [])

    def test_hostile_names_and_passwords_are_quoted(self):
        values = {
            "DBName": 'we"ird',
            "DBUser": "o'brien",
            "DBPassword": "p'a\\ss\"word;--",
        }
        psql = FakePsql()
        setup.provision_database(values, psql)
        role, database = psql.writes()
        self.assertEqual(
            role, "CREATE ROLE \"o'brien\" LOGIN PASSWORD E'p''a\\\\ss\"word;--';"
        )
        self.assertEqual(database, 'CREATE DATABASE "we""ird" OWNER "o\'brien";')


class TestPsqlRunner(unittest.TestCase):
    """The real Psql class against a fake psql program."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="fake-psql-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.log = self.dir / "calls.log"

    def fake(self, body):
        program = self.dir / "psql"
        program.write_text(
            f'#!/bin/sh\necho "ARGV: $*" >> "{self.log}"\ncat >> "{self.log}"\n{body}\n'
        )
        program.chmod(0o755)
        return setup.Psql([str(program)])

    def test_the_password_goes_through_stdin_never_through_the_command_line(self):
        psql = self.fake("echo 1")
        psql.run("CREATE ROLE \"nabs\" LOGIN PASSWORD 'Top-Secret-Pw';")
        log = self.log.read_text()
        argv_line = [line for line in log.splitlines() if line.startswith("ARGV:")][0]
        self.assertNotIn("Top-Secret-Pw", argv_line)
        self.assertIn("ON_ERROR_STOP=1", argv_line)
        self.assertIn(
            "Top-Secret-Pw", log.replace(argv_line, "")
        )  # it arrived on stdin

    def test_database_option(self):
        psql = self.fake("echo 1")
        psql.run("SELECT 1;", dbname="nabs")
        self.assertIn("-d nabs", self.log.read_text())

    def test_an_error_shows_the_first_line_only(self):
        psql = self.fake(
            "echo 'ERROR: permission denied' >&2; echo 'DETAIL: PASSWORD Top-Secret-Pw' >&2; exit 3"
        )
        with self.assertRaises(RuntimeError) as raised:
            psql.run("CREATE ROLE x PASSWORD 'Top-Secret-Pw';")
        self.assertIn("permission denied", str(raised.exception))
        self.assertNotIn("Top-Secret-Pw", str(raised.exception))


class TestDatabaseCheck(unittest.TestCase):
    VALUES = {
        "DBHost": "localhost",
        "DBPort": "5432",
        "DBName": "nabs",
        "DBUser": "nabs",
        "DBPassword": "Sup3r-Secret",
    }

    class Connection:
        def __init__(self, can_create=True):
            self.closed, self.can_create = False, can_create

        def cursor(self):
            return self

        def execute(self, sql):
            pass

        def fetchone(self):
            return (self.can_create,)

        def close(self):
            self.closed = True

    def test_a_working_connection(self):
        connection = self.Connection()
        self.assertEqual(setup.check_database(self.VALUES, lambda **kw: connection), [])
        self.assertTrue(connection.closed)

    def test_the_settings_of_config_py_are_used(self):
        seen = {}

        def connect(**kw):
            seen.update(kw)
            return self.Connection()

        setup.check_database(self.VALUES, connect)
        self.assertEqual(
            (seen["host"], seen["dbname"], seen["user"], seen["password"]),
            ("localhost", "nabs", "nabs", "Sup3r-Secret"),
        )
        self.assertEqual(seen["connect_timeout"], 10)

    def test_failures_are_explained_and_never_show_the_password(self):
        cases = {
            'password authentication failed for user "nabs" (Sup3r-Secret)': "DBUser / DBPassword",
            'database "nabs" does not exist': "DBName",
            "connection refused": "not reachable",
            "timeout expired": "not reachable",
        }
        for message, hint in cases.items():

            def connect(**kw):
                raise RuntimeError(message)

            problems = setup.check_database(self.VALUES, connect)
            self.assertEqual(len(problems), 1)
            self.assertIn(hint, problems[0])
            self.assertNotIn("Sup3r-Secret", problems[0])

    def test_postgres_15_missing_create_privilege_is_detected(self):
        connection = self.Connection(can_create=False)
        problems = setup.check_database(self.VALUES, lambda **kw: connection)
        self.assertEqual(len(problems), 1)
        self.assertIn("GRANT ALL ON SCHEMA public", problems[0])
        self.assertTrue(connection.closed)


class TestRender(unittest.TestCase):
    def test_units_are_fitted_to_the_directory_and_the_user(self):
        for name in ("nabs.service", "nabs-scheduler.service"):
            text = setup.render_file(
                ROOT / "supervisor" / name, "/srv/nabs", "svc-nabs", "svc-grp"
            )
            self.assertNotIn("/opt/NABS", text)
            self.assertIn("WorkingDirectory=/srv/nabs", text)
            self.assertIn("User=svc-nabs", text)
            self.assertNotIn("User=root", text)
            self.assertIn("ReadWritePaths=/srv/nabs/logs", text)

    def test_the_defaults_change_nothing(self):
        path = ROOT / "supervisor" / "nabs.service"
        self.assertEqual(setup.render_file(path, "/opt/NABS", "nabs"), path.read_text())

    def test_nginx_site_points_at_the_certificate_the_installer_creates(self):
        text = setup.render_file(ROOT / "supervisor" / "nabs", "/srv/nabs", "nabs")
        self.assertIn("ssl_certificate /srv/nabs/certs/cert.pem;", text)
        self.assertIn("ssl_certificate_key /srv/nabs/certs/key.pem;", text)
        self.assertNotIn("/opt/NABS", text)

    def test_services_do_not_run_as_root(self):
        for name in ("nabs.service", "nabs-scheduler.service", "nabs.conf"):
            text = (ROOT / "supervisor" / name).read_text()
            self.assertNotIn("User=root", text)
            self.assertNotIn("user=root", text)
            self.assertNotIn("Group=root", text)


class TestCommandLine(TempDirCase):
    def run_cli(self, *args):
        with patch("builtins.print") as printed:
            code = setup.main(["--app-dir", str(self.dir), *args])
        return code, " ".join(
            " ".join(map(str, c.args)) for c in printed.call_args_list
        )

    def test_init_then_check_then_get(self):
        self.assertEqual(self.run_cli("init-config")[0], setup.EXIT_OK)
        self.assertEqual(self.run_cli("check-config")[0], setup.EXIT_OK)
        code, output = self.run_cli("config-get", "DBName")
        self.assertEqual((code, output.strip()), (0, "nabs"))
        self.assertEqual(self.run_cli("init-config")[0], setup.EXIT_EXISTS)

    def test_check_config_fails_for_empty_secrets(self):
        shutil.copy(self.dir / "config_example.py", self.dir / "config.py")
        code, output = self.run_cli("check-config")
        self.assertEqual(code, setup.EXIT_ERROR)
        self.assertIn("CREDENTIALS_ENCRYPTION_KEY", output)

    def test_a_remote_database_is_not_provisioned(self):
        self.run_cli("init-config")
        text = (
            (self.dir / "config.py")
            .read_text()
            .replace('DBHost = "localhost"', 'DBHost = "db.example.org"')
        )
        (self.dir / "config.py").write_text(text)
        with patch.object(setup, "Psql") as psql:
            code, output = self.run_cli("provision-db")
        self.assertEqual(code, 0)
        psql.assert_not_called()
        self.assertIn("remote", output)

    def test_no_config_is_an_error_not_a_crash(self):
        code, output = self.run_cli("check-config")
        self.assertEqual(code, setup.EXIT_ERROR)
        self.assertIn("config.py", output)


if __name__ == "__main__":
    unittest.main()
