"""
TZ 6.4: the REAL Install_v2.sh is run in a sandbox directory with every external command
(psql, systemctl, nginx, flask, sudo, chown, useradd, openssl ...) replaced by a recording
stub. This checks the logic and the order of the installer for two scenarios:

  * a clean installation (empty directory, no database),
  * an update of an existing installation (kept config.py with keys, existing database,
    nginx site, systemd units, certificates).

It does NOT replace a run on a real test host: apt, pip, PostgreSQL, systemd and nginx are
not exercised here (see the report and docs/DEPLOYMENT.md).
"""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STUBS = {
    "sudo": '''
        if [ "$1" = "-u" ]; then shift 2; fi
        if [ "$1" = "test" ] && [ -n "$FAKE_AS_USER_FAIL" ]; then exit 1; fi
        exec "$@"''',
    "runuser": '''
        while [ "$1" != "--" ]; do shift; done; shift
        if [ "$1" = "test" ] && [ -n "$FAKE_AS_USER_FAIL" ]; then exit 1; fi
        exec "$@"''',
    "chown": "exit 0",
    "chgrp": "exit 0",
    "useradd": "exit 0",
    "apt-get": "exit 0",
    "journalctl": "exit 0",
    "sleep": "exit 0",
    "migrate_text": "exit 0",
    "systemctl": '[ "$1" = "is-active" ] && exit "${FAKE_INACTIVE:-0}"; exit 0',
    "nginx": '[ "$1" = "-t" ] && exit "${FAKE_NGINX_FAIL:-0}"; exit 0',
    "flask": '[ "$1 $2" = "db init" ] && mkdir -p migrations; exit 0',
    "openssl": """
        while [ $# -gt 0 ]; do
          case "$1" in -keyout) echo KEY > "$2"; shift ;; -out) echo CERT > "$2"; shift ;; esac
          shift
        done; exit 0""",
    "psql": """
        stdin="$(cat)"
        printf '%s\\n' "$stdin" >> "$FAKE_PSQL_STDIN"
        case "$stdin" in
          *"FROM pg_roles"*) [ -f "$FAKE_STATE/role" ] && echo 1 ;;
          *"FROM pg_database"*) [ -f "$FAKE_STATE/db" ] && echo 1 ;;
          *"pg_get_userbyid"*) cat "$FAKE_STATE/owner" 2>/dev/null ;;
          "CREATE ROLE"*) touch "$FAKE_STATE/role" ;;
          "CREATE DATABASE"*) touch "$FAKE_STATE/db"; echo nabs > "$FAKE_STATE/owner" ;;
        esac
        exit 0""",
    # stands in for the helper's database check (psycopg2 is not available here)
    "db_check": '[ -n "$FAKE_DB_CHECK_FAIL" ] && { echo "wrong password (stub)"; exit 1; }; exit 0',
}


class InstallerCase(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="nabs-installer-"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.app = self.sandbox / "NABS"
        self.bin = self.sandbox / "bin"
        self.state = self.sandbox / "state"
        self.systemd = self.sandbox / "systemd"
        self.nginx = self.sandbox / "nginx"
        for directory in (
            self.app,
            self.bin,
            self.state,
            self.systemd,
            self.nginx / "sites-available",
            self.nginx / "sites-enabled",
        ):
            directory.mkdir(parents=True)
        for name in ("Install_v2.sh", "config_example.py"):
            shutil.copy(ROOT / name, self.app / name)
        shutil.copytree(ROOT / "scripts", self.app / "scripts")
        shutil.copytree(ROOT / "supervisor", self.app / "supervisor")
        (self.nginx / "sites-enabled" / "default").write_text("default site")
        self.calls = self.sandbox / "calls.log"
        self.psql_stdin = self.sandbox / "psql_stdin.log"
        self.calls.touch()
        self.psql_stdin.touch()
        for name, body in STUBS.items():
            path = self.bin / name
            path.write_text(f'#!/bin/sh\necho "{name} $*" >> "$FAKE_CALLS"\n{body}\n')
            path.chmod(0o755)
        # the helper: the real nabs_setup.py, but the DB connection check is the stub
        wrapper = self.bin / "helper"
        wrapper.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "db-check" ]; then echo "helper db-check" >> "$FAKE_CALLS"; exec db_check; fi\n'
            f'exec python3 "{self.app}/scripts/nabs_setup.py" --app-dir "{self.app}" '
            '--service-user nabs --psql psql "$@"\n'
        )
        wrapper.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            NABS_APP_DIR=str(self.app),
            NABS_SERVICE_USER="nabs",
            NABS_SYSTEMD_DIR=str(self.systemd),
            NABS_NGINX_DIR=str(self.nginx),
            NABS_SKIP_PACKAGES="1",
            NABS_SKIP_VENV="1",
            NABS_PYTHON="python3",
            NABS_FLASK=str(self.bin / "flask"),
            NABS_HELPER=str(self.bin / "helper"),
            NABS_MIGRATE_TEXT_CMD="migrate_text",
            FAKE_CALLS=str(self.calls),
            FAKE_PSQL_STDIN=str(self.psql_stdin),
            FAKE_STATE=str(self.state),
        )

    # ------------------------------------------------------------------ helpers
    def install(self, *args, **extra_env):
        env = dict(self.env, **extra_env)
        return subprocess.run(
            ["bash", str(self.app / "Install_v2.sh"), *args],
            env=env,
            cwd=self.app,
            capture_output=True,
            text=True,
        )

    def call_log(self):
        return self.calls.read_text().splitlines()

    def calls_of(self, prefix):
        return [line for line in self.call_log() if line.startswith(prefix)]

    def position(self, prefix):
        for index, line in enumerate(self.call_log()):
            if line.startswith(prefix):
                return index
        self.fail(f"no call starting with {prefix!r} in {self.call_log()}")

    def sql(self):
        return self.psql_stdin.read_text()

    def config(self):
        import runpy

        return runpy.run_path(str(self.app / "config.py"))

    def make_existing_installation(self):
        """The state of a server installed earlier: data that must survive an update."""
        (self.app / "certs").mkdir()
        (self.app / "certs" / "cert.pem").write_text("MY CERT")
        (self.app / "certs" / "key.pem").write_text("MY KEY")
        text = (ROOT / "config_example.py").read_text()
        text = text.replace('TOKEN = ""', 'TOKEN = "existing-token-0123456789abcdef"')
        text = text.replace(
            'CREDENTIALS_ENCRYPTION_KEY = ""',
            'CREDENTIALS_ENCRYPTION_KEY = "existing-key-0123456789abcdef"',
        )
        text = text.replace(
            'DBPassword = "nabs"', 'DBPassword = "existing-db-password"'
        )
        text += "\n# my own setting\nMY_OWN_SETTING = 42\n"
        (self.app / "config.py").write_text(text)
        (self.app / "migrations").mkdir()
        (self.state / "role").touch()
        (self.state / "db").touch()
        (self.state / "owner").write_text("nabs")
        (self.nginx / "sites-available" / "nabs").write_text("# my own nginx site\n")
        (self.nginx / "sites-enabled" / "nabs").symlink_to(
            self.nginx / "sites-available" / "nabs"
        )
        (self.systemd / "nabs.service").write_text(
            "[Service]\nUser=root\nExecStart=/old\n"
        )
        (self.systemd / "nabs-scheduler.service").write_text(
            "[Service]\nUser=custom\nExecStart=/mine\n"
        )


class TestCleanInstallation(InstallerCase):
    def test_a_clean_installation_works_end_to_end(self):
        result = self.install("--self-signed")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        # config.py: created once, with secrets, not readable by everybody
        values = self.config()
        self.assertGreaterEqual(len(values["TOKEN"]), 32)
        self.assertGreaterEqual(len(values["CREDENTIALS_ENCRYPTION_KEY"]), 32)
        self.assertNotEqual(values["TOKEN"], values["CREDENTIALS_ENCRYPTION_KEY"])
        self.assertEqual(stat.S_IMODE((self.app / "config.py").stat().st_mode), 0o640)

        # the database is created from config.py, owned by the application role
        self.assertIn('CREATE ROLE "nabs" LOGIN PASSWORD', self.sql())
        self.assertIn('CREATE DATABASE "nabs" OWNER "nabs";', self.sql())

        # directories: the service user owns only what it must write, never 777
        for name in ("logs", "backups", "user_uploads"):
            self.assertEqual(
                stat.S_IMODE((self.app / name).stat().st_mode), 0o750, name
            )
        self.assertIn("chown -R nabs:nabs logs backups user_uploads", self.call_log())
        self.assertIn("chgrp nabs config.py", self.call_log())

    def test_the_order_of_the_steps(self):
        self.assertEqual(self.install("--self-signed").returncode, 0)
        order = [
            self.position("useradd"),  # the unprivileged user exists first
            self.position("helper db-check"),  # the database is usable ...
            self.position("migrate_text"),  # ... the column is widened ...
            self.position("flask db init"),  # ... the schema is created ...
            self.position("flask db migrate"),
            self.position("flask db upgrade"),
            self.position(
                "systemctl daemon-reload"
            ),  # ... and only then the services start
            self.position("systemctl enable nabs nabs-scheduler"),
            self.position("systemctl restart nabs nabs-scheduler"),
            self.position("nginx -t"),  # nginx is checked before it is reloaded
            self.position("systemctl reload nginx"),
        ]
        self.assertEqual(order, sorted(order), self.call_log())

    def test_units_run_as_the_service_user_from_the_installation_directory(self):
        self.assertEqual(self.install("--self-signed").returncode, 0)
        for name in ("nabs.service", "nabs-scheduler.service"):
            text = (self.systemd / name).read_text()
            self.assertIn("User=nabs", text)
            self.assertIn("Group=nabs", text)
            for line in text.splitlines():
                if line.startswith(("User=", "Group=")):
                    self.assertNotIn("root", line)
            self.assertIn(f"WorkingDirectory={self.app}", text)
            self.assertIn(f"ExecStart={self.app}/venv/bin/", text)
            self.assertIn(f"ReadWritePaths={self.app}/logs", text)
            self.assertNotIn("/opt/NABS", text)

    def test_both_services_are_installed_enabled_and_started(self):
        self.assertEqual(self.install("--self-signed").returncode, 0)
        self.assertTrue((self.systemd / "nabs.service").exists())
        self.assertTrue(
            (self.systemd / "nabs-scheduler.service").exists()
        )  # was missing before
        self.assertIn("systemctl enable nabs nabs-scheduler", self.call_log())
        self.assertIn("systemctl restart nabs nabs-scheduler", self.call_log())

    def test_nginx_uses_the_certificate_files_that_exist(self):
        self.assertEqual(self.install("--self-signed").returncode, 0)
        site = (self.nginx / "sites-available" / "nabs").read_text()
        self.assertIn(f"ssl_certificate {self.app}/certs/cert.pem;", site)
        self.assertIn(f"ssl_certificate_key {self.app}/certs/key.pem;", site)
        self.assertTrue((self.app / "certs" / "cert.pem").is_file())
        self.assertTrue((self.app / "certs" / "key.pem").is_file())
        self.assertEqual(
            stat.S_IMODE((self.app / "certs" / "key.pem").stat().st_mode), 0o600
        )
        self.assertTrue((self.nginx / "sites-enabled" / "nabs").is_symlink())
        self.assertFalse((self.nginx / "sites-enabled" / "default").exists())

    def test_no_secret_reaches_a_command_line(self):
        self.assertEqual(self.install("--self-signed").returncode, 0)
        values = self.config()
        log = self.calls.read_text()
        for name in ("DBPassword", "TOKEN", "CREDENTIALS_ENCRYPTION_KEY"):
            self.assertNotIn(values[name], log, name)
        self.assertIn(
            values["DBPassword"], self.sql()
        )  # the password travels on stdin only

    def test_nothing_is_installed_with_chmod_777(self):
        import re

        code = [
            line
            for line in (ROOT / "Install_v2.sh").read_text().splitlines()
            if not line.lstrip().startswith("#") and "log " not in line
        ]
        for line in code:
            self.assertIsNone(
                re.search(r"chmod\s+(-\w+\s+)*0?777|a\+rwx|o\+w", line), line
            )

    def test_the_installer_does_not_touch_yaml_configuration(self):
        text = (ROOT / "Install_v2.sh").read_text()
        for name in ("config_example.yaml", "config.yaml"):
            self.assertNotIn(name, text.replace("there is no YAML configuration", ""))
        self.assertTrue(
            subprocess.run(["bash", "-n", str(ROOT / "Install_v2.sh")]).returncode == 0
        )


class TestUsingExistingCertificates(InstallerCase):
    def test_production_mode_uses_your_certificate_and_creates_none(self):
        (self.app / "certs").mkdir()
        (self.app / "certs" / "cert.pem").write_text("MY CERT")
        (self.app / "certs" / "key.pem").write_text("MY KEY")
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls_of("openssl"), [])
        self.assertEqual((self.app / "certs" / "cert.pem").read_text(), "MY CERT")
        self.assertEqual((self.app / "certs" / "key.pem").read_text(), "MY KEY")

    def test_self_signed_never_replaces_an_existing_certificate(self):
        (self.app / "certs").mkdir()
        (self.app / "certs" / "cert.pem").write_text("MY CERT")
        (self.app / "certs" / "key.pem").write_text("MY KEY")
        self.assertEqual(self.install("--self-signed").returncode, 0)
        self.assertEqual(self.calls_of("openssl"), [])
        self.assertEqual((self.app / "certs" / "cert.pem").read_text(), "MY CERT")

    def test_missing_certificates_stop_the_installer_before_any_change(self):
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--self-signed", result.stderr)
        self.assertEqual(self.call_log(), [])  # nothing at all was run
        self.assertFalse((self.app / "config.py").exists())
        self.assertEqual(self.sql(), "")

    def test_only_one_of_the_two_files_stops_the_installer(self):
        (self.app / "certs").mkdir()
        (self.app / "certs" / "cert.pem").write_text("MY CERT")
        result = self.install("--self-signed")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.call_log(), [])

    def test_skip_nginx_needs_no_certificate_and_does_not_touch_nginx(self):
        result = self.install("--skip-nginx")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls_of("nginx"), [])
        self.assertNotIn("systemctl reload nginx", self.call_log())
        self.assertFalse((self.nginx / "sites-available" / "nabs").exists())
        self.assertTrue((self.nginx / "sites-enabled" / "default").exists())

    def test_nginx_is_not_started_when_its_config_is_invalid(self):
        result = self.install("--self-signed", FAKE_NGINX_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("systemctl reload nginx", self.call_log())
        self.assertNotIn("systemctl restart nginx", self.call_log())
        self.assertFalse(
            (self.nginx / "sites-enabled" / "nabs").exists()
        )  # the new site is withdrawn


class TestUpdateOfAnExistingInstallation(InstallerCase):
    def test_the_update_keeps_every_user_setting(self):
        self.make_existing_installation()
        before = (self.app / "config.py").read_bytes()
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        # secrets and DB settings: byte for byte the same - no new encryption key
        self.assertEqual((self.app / "config.py").read_bytes(), before)
        values = self.config()
        self.assertEqual(
            values["CREDENTIALS_ENCRYPTION_KEY"], "existing-key-0123456789abcdef"
        )
        self.assertEqual(values["MY_OWN_SETTING"], 42)

        # the database is neither recreated nor altered
        self.assertNotIn("CREATE", self.sql())
        self.assertNotIn("DROP", self.sql())
        self.assertNotIn("ALTER", self.sql())

        # your nginx site and certificate are kept
        self.assertEqual(
            (self.nginx / "sites-available" / "nabs").read_text(),
            "# my own nginx site\n",
        )
        self.assertEqual((self.app / "certs" / "cert.pem").read_text(), "MY CERT")
        self.assertEqual(self.calls_of("openssl"), [])

    def test_the_update_moves_the_root_unit_to_the_service_user_and_keeps_a_copy(self):
        self.make_existing_installation()
        self.assertEqual(self.install().returncode, 0)
        text = (self.systemd / "nabs.service").read_text()
        self.assertIn("User=nabs", text)
        self.assertNotIn("User=root", text)
        backups = list(self.systemd.glob("nabs.service.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertIn("User=root", backups[0].read_text())

    def test_a_unit_with_its_own_user_is_kept(self):
        self.make_existing_installation()
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(
            (self.systemd / "nabs-scheduler.service").read_text(),
            "[Service]\nUser=custom\nExecStart=/mine\n",
        )

    def test_the_schema_is_upgraded_not_recreated(self):
        self.make_existing_installation()
        self.assertEqual(self.install().returncode, 0)
        flask = self.calls_of("flask")
        self.assertNotIn("flask db init", flask)
        self.assertEqual(
            [c for c in flask],
            [
                "flask db upgrade",
                "flask db migrate -m NABS update " + flask[1].rsplit(" ", 1)[-1],
                "flask db upgrade",
            ],
        )
        self.assertLess(
            self.position("migrate_text"), self.position("flask db upgrade")
        )

    def test_services_are_restarted_after_the_update(self):
        self.make_existing_installation()
        self.assertEqual(self.install().returncode, 0)
        self.assertIn("systemctl restart nabs nabs-scheduler", self.call_log())

    def test_running_the_installer_twice_changes_nothing_the_second_time(self):
        self.assertEqual(self.install("--self-signed").returncode, 0)
        config = (self.app / "config.py").read_bytes()
        site = (self.nginx / "sites-available" / "nabs").read_text()
        cert = (self.app / "certs" / "cert.pem").read_text()
        self.psql_stdin.write_text("")
        self.calls.write_text("")
        result = self.install("--self-signed")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.app / "config.py").read_bytes(), config)  # the same keys
        self.assertEqual((self.nginx / "sites-available" / "nabs").read_text(), site)
        self.assertEqual((self.app / "certs" / "cert.pem").read_text(), cert)
        self.assertNotIn("CREATE", self.sql())
        self.assertEqual(self.calls_of("openssl"), [])


class TestFailuresStopEarlyAndSafely(InstallerCase):
    def test_a_config_without_the_encryption_key_is_not_fixed_by_generating_one(self):
        self.make_existing_installation()
        text = (
            (self.app / "config.py")
            .read_text()
            .replace(
                'CREDENTIALS_ENCRYPTION_KEY = "existing-key-0123456789abcdef"',
                'CREDENTIALS_ENCRYPTION_KEY = ""',
            )
        )
        (self.app / "config.py").write_text(text)
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Do NOT generate a new CREDENTIALS_ENCRYPTION_KEY", result.stderr)
        self.assertEqual((self.app / "config.py").read_text(), text)  # untouched
        self.assertEqual(self.sql(), "")  # the database is not reached
        self.assertNotIn("systemctl restart nabs nabs-scheduler", self.call_log())

    def test_a_database_that_cannot_be_used_stops_before_the_schema_and_the_services(
        self,
    ):
        self.make_existing_installation()
        result = self.install(FAKE_DB_CHECK_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls_of("flask"), [])
        self.assertEqual(self.calls_of("migrate_text"), [])
        self.assertNotIn("systemctl restart nabs nabs-scheduler", self.call_log())
        self.assertIn("The database is not usable", result.stderr)

    def test_the_service_user_must_be_able_to_read_the_config(self):
        result = self.install("--self-signed", FAKE_AS_USER_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot read", result.stderr)
        self.assertEqual(self.calls_of("flask"), [])
        self.assertNotIn("systemctl restart nabs nabs-scheduler", self.call_log())

    def test_a_service_that_does_not_start_is_reported(self):
        result = self.install("--self-signed", FAKE_INACTIVE="3")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not start", result.stderr)
        self.assertTrue(self.calls_of("journalctl"))
        self.assertNotIn(
            "systemctl reload nginx", self.call_log()
        )  # nginx is not started on top

    def test_an_unknown_option_is_refused(self):
        result = self.install("--nope")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.call_log(), [])


if __name__ == "__main__":
    unittest.main()
