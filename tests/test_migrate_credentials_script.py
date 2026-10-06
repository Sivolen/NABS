"""
TZ 5: the migration that widens credentials.credentials_password to TEXT.
The SQL logic is tested against a fake cursor (no PostgreSQL here) - run the script
with --apply on a COPY of the database before the real one (see docs).
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "migrate_credentials_password_text.py"
)
spec = importlib.util.spec_from_file_location("migrate_credentials_script", SCRIPT)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


class FakePostgres:
    """Just enough of information_schema and ALTER TABLE for the script."""

    def __init__(
        self,
        data_type="character varying",
        length=100,
        rows=3,
        longest=100,
        table_exists=True,
        alter_error=None,
        changes_data=False,
    ):
        self.column = (data_type, length) if table_exists else None
        self.rows, self.longest = rows, longest
        self.alter_error, self.changes_data = alter_error, changes_data
        self.statements, self.committed, self.rolled_back = [], 0, 0

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.statements.append(sql)
        self._last = sql
        if sql.startswith("ALTER TABLE"):
            if self.alter_error:
                raise self.alter_error
            self.column = ("text", None)
            if self.changes_data:
                self.longest += 1

    def fetchone(self):
        if "information_schema" in self._last:
            return self.column
        if "count(*)" in self._last:
            return (self.rows, self.longest)
        raise AssertionError(self._last)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def altered(self):
        return any(s.startswith("ALTER TABLE") for s in self.statements)


def run(db, apply):
    lines = []
    code = script.migrate(db, apply=apply, out=lines.append)
    return code, "\n".join(lines)


class TestMigration(unittest.TestCase):
    def test_dry_run_changes_nothing(self):
        db = FakePostgres()
        code, text = run(db, apply=False)
        self.assertEqual(code, 0)
        self.assertFalse(db.altered())
        self.assertEqual(db.committed, 0)
        self.assertIn("Dry run", text)
        self.assertEqual(db.column, ("character varying", 100))

    def test_apply_widens_the_column_and_keeps_the_data(self):
        db = FakePostgres(rows=5, longest=100)
        code, text = run(db, apply=True)
        self.assertEqual(code, 0)
        self.assertTrue(db.altered())
        self.assertEqual(db.committed, 1)
        self.assertEqual(db.column[0], "text")
        self.assertEqual((db.rows, db.longest), (5, 100))
        self.assertIn("5 profile(s) kept unchanged", text)

    def test_the_only_change_is_the_column_type(self):
        db = FakePostgres()
        run(db, apply=True)
        changing = [
            s
            for s in db.statements
            if s.split()[0] in ("ALTER", "UPDATE", "INSERT", "DELETE", "DROP")
        ]
        self.assertEqual(len(changing), 1)
        self.assertIn("TYPE TEXT", changing[0])
        self.assertNotIn(
            "UPDATE", " ".join(db.statements)
        )  # values are never rewritten

    def test_running_twice_is_harmless(self):
        db = FakePostgres()
        run(db, apply=True)
        statements_after_first = len(db.statements)
        code, text = run(db, apply=True)
        self.assertEqual(code, 0)
        self.assertIn("already TEXT", text)
        self.assertEqual(db.committed, 1)  # no second change
        self.assertFalse(
            any(s.startswith("ALTER") for s in db.statements[statements_after_first:])
        )

    def test_a_new_database_without_the_table(self):
        db = FakePostgres(table_exists=False)
        code, text = run(db, apply=True)
        self.assertEqual(code, 0)
        self.assertFalse(db.altered())
        self.assertIn("does not exist yet", text)

    def test_an_unexpected_column_type_is_not_touched(self):
        db = FakePostgres(data_type="bytea", length=None)
        code, text = run(db, apply=True)
        self.assertEqual(code, 2)
        self.assertFalse(db.altered())
        self.assertIn("unexpected type", text)

    def test_a_failure_is_rolled_back(self):
        db = FakePostgres(alter_error=RuntimeError("lock timeout"))
        code, text = run(db, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual(db.committed, 0)
        self.assertEqual(db.rolled_back, 1)
        self.assertIn("rolled back", text)

    def test_a_change_of_the_data_is_rolled_back(self):
        db = FakePostgres(changes_data=True)
        code, text = run(db, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual(db.committed, 0)
        self.assertEqual(db.rolled_back, 1)

    def test_lock_wait_is_limited(self):
        db = FakePostgres()
        run(db, apply=True)
        self.assertTrue(any("lock_timeout" in s for s in db.statements))


class TestConnectionErrors(unittest.TestCase):
    def fake_config(self, password="Sup3r-Secret-DB-Pass"):
        module = types.ModuleType("config")
        module.DBPassword = password
        return patch.dict(sys.modules, {"config": module})

    def test_connection_error_never_prints_the_password(self):
        error = RuntimeError(
            "could not connect with password=Sup3r-Secret-DB-Pass to host"
        )
        printed = []
        with self.fake_config(), patch.object(
            script, "connect_from_config", side_effect=error
        ), patch(
            "builtins.print",
            side_effect=lambda *a: printed.append(" ".join(map(str, a))),
        ):
            code = script.main(["--apply"])
        self.assertEqual(code, 1)
        text = " ".join(printed)
        self.assertIn("Cannot connect", text)
        self.assertNotIn("Sup3r-Secret-DB-Pass", text)
        self.assertIn("***", text)

    def test_failure_message_never_prints_the_password(self):
        db = FakePostgres(alter_error=RuntimeError("bad Sup3r-Secret-DB-Pass value"))
        lines = []
        with self.fake_config():
            script.migrate(db, apply=True, out=lines.append)
        self.assertNotIn("Sup3r-Secret-DB-Pass", " ".join(lines))

    def test_the_connection_is_closed_after_the_run(self):
        db = FakePostgres()
        closed = []
        db.close = lambda: closed.append(True)
        with patch.object(script, "connect_from_config", return_value=db):
            self.assertEqual(script.main([]), 0)
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
