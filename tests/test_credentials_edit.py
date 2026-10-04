"""
TZ 4: editing SSH credentials.
 - an empty password field keeps the stored password (no decrypt, no second encryption);
 - the password - plain or encrypted - is never sent to the browser;
 - errors do not leak the password and do not damage the stored credentials.
"""

import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules import crypto  # noqa: E402
from app.modules.dbutils import db_credentials  # noqa: E402
from app.views import credentials as credentials_view  # noqa: E402
from app.views import get_credentials as get_credentials_view  # noqa: E402
from view_test_support import flashed, logged_in, make_test_app  # noqa: E402

KEY = "unit-test-key-0123456789abcdef"
DB = "app.modules.dbutils.db_credentials"
TEMPLATE = (
    Path(__file__).resolve().parent.parent / "app" / "templates" / "credentials.html"
)


def stored_profile(password="OldPassword-123"):
    """What the table holds: the password only as a Fernet token."""
    return SimpleNamespace(
        credentials_name="core",
        credentials_username="admin",
        credentials_password=crypto.encrypt(password, KEY),
        user_group_id=10,
    )


class TestUpdateCredentials(unittest.TestCase):
    def setUp(self):
        self.record = stored_profile()
        self.token_before = self.record.credentials_password
        self.db = patch(f"{DB}.db").start()
        self.db.session.query.return_value.filter_by.return_value.first.return_value = (
            self.record
        )
        patch(f"{DB}.CREDENTIALS_ENCRYPTION_KEY", KEY).start()
        self.log = patch(f"{DB}.logger").start()
        self.addCleanup(patch.stopall)

    def update(self, **kw):
        args = dict(
            credentials_id=1,
            credentials_name="core",
            credentials_username="admin",
            credentials_password="",
            credentials_user_group=10,
        )
        args.update(kw)
        return db_credentials.update_credentials(**args)

    def test_changing_only_the_profile_name_keeps_the_password(self):
        self.assertTrue(self.update(credentials_name="core-2", credentials_password=""))
        self.assertEqual(self.record.credentials_name, "core-2")
        self.assertEqual(
            self.record.credentials_password, self.token_before
        )  # same token
        self.assertEqual(
            crypto.decrypt(self.record.credentials_password, KEY), "OldPassword-123"
        )
        self.db.session.commit.assert_called_once()

    def test_changing_only_the_login_keeps_the_password(self):
        self.assertTrue(
            self.update(credentials_username="root", credentials_password=None)
        )
        self.assertEqual(self.record.credentials_username, "root")
        self.assertEqual(self.record.credentials_password, self.token_before)

    def test_changing_the_other_fields_keeps_the_password(self):
        self.assertTrue(self.update(credentials_user_group=11, credentials_password=""))
        self.assertEqual(self.record.user_group_id, 11)
        self.assertEqual(self.record.credentials_password, self.token_before)

    def test_an_empty_field_never_decrypts_or_encrypts(self):
        with patch(f"{DB}.encrypt") as encrypt:
            self.update(credentials_name="x", credentials_password="")
            self.update(credentials_name="y", credentials_password=None)
        encrypt.assert_not_called()

    def test_a_new_password_is_encrypted_exactly_once(self):
        self.assertTrue(self.update(credentials_password="Brand-New-Passw0rd!"))
        self.assertNotEqual(self.record.credentials_password, self.token_before)
        self.assertNotIn("Brand-New", self.record.credentials_password)
        # one layer only: decrypting once gives the password, not another token
        self.assertEqual(
            crypto.decrypt(self.record.credentials_password, KEY), "Brand-New-Passw0rd!"
        )

    def test_the_new_password_may_be_long_or_unicode(self):
        for password in (
            "Z" * 500,
            "пароль-密码-🔑" * 20,
            "q'\"; DROP TABLE credentials;--",
        ):
            self.update(credentials_password=password)
            self.assertEqual(
                crypto.decrypt(self.record.credentials_password, KEY), password
            )

    def test_a_too_long_password_changes_nothing(self):
        self.assertFalse(
            self.update(credentials_name="hacked", credentials_password="x" * 5000)
        )
        self.assertEqual(self.record.credentials_name, "core")
        self.assertEqual(self.record.credentials_password, self.token_before)
        self.db.session.commit.assert_not_called()
        self.db.session.rollback.assert_called_once()

    def test_a_missing_key_changes_nothing(self):
        with patch(f"{DB}.CREDENTIALS_ENCRYPTION_KEY", ""):
            self.assertFalse(
                self.update(credentials_name="hacked", credentials_password="new")
            )
        self.assertEqual(self.record.credentials_name, "core")
        self.assertEqual(self.record.credentials_password, self.token_before)
        self.db.session.commit.assert_not_called()

    def test_a_database_error_is_rolled_back_and_does_not_leak_secrets(self):
        error = Exception(
            "INSERT ... [parameters: ('gAAAA-SECRET-TOKEN',)] Secret-Plain-Pass"
        )
        error.orig = Exception("value too long for type character varying(100)")
        self.db.session.commit.side_effect = error
        self.assertFalse(self.update(credentials_password="Secret-Plain-Pass"))
        self.db.session.rollback.assert_called_once()
        logged = " ".join(str(call) for call in self.log.mock_calls)
        self.assertIn("value too long", logged)  # the useful part is logged
        self.assertNotIn("Secret-Plain-Pass", logged)
        self.assertNotIn("SECRET-TOKEN", logged)

    def test_unknown_profile(self):
        self.db.session.query.return_value.filter_by.return_value.first.return_value = (
            None
        )
        self.assertIsNone(self.update(credentials_id=99))
        self.db.session.commit.assert_not_called()


class TestAddCredentialsLogging(unittest.TestCase):
    @patch(f"{DB}.logger")
    @patch(f"{DB}.db")
    def test_add_error_does_not_leak_the_token(self, db, log):
        error = Exception("INSERT [parameters: ('gAAAA-SECRET-TOKEN',)]")
        error.orig = Exception("value too long for type character varying(100)")
        db.session.commit.side_effect = error
        self.assertFalse(
            db_credentials.add_credentials("n", "u", "gAAAA-SECRET-TOKEN", 1)
        )
        self.assertNotIn("SECRET-TOKEN", " ".join(str(c) for c in log.mock_calls))
        db.session.rollback.assert_called_once()


class TestCredentialsApiNeverSendsThePassword(unittest.TestCase):
    PLAIN = "Plain-Password-That-Must-Not-Leak"

    def setUp(self):
        self.token = crypto.encrypt(self.PLAIN, KEY)
        self.flask_app = make_test_app(
            [
                (
                    "/credentials_data/",
                    "get_credentials_data",
                    get_credentials_view.get_credentials_data,
                    ["POST"],
                )
            ]
        )
        self.client = self.flask_app.test_client()
        profile = {
            "credentials_name": "core",
            "credentials_username": "admin",
            "credentials_password": self.token,
            "credentials_user_group": 10,
        }
        self.get = patch(
            "app.views.get_credentials.get_credentials", return_value=profile
        ).start()
        patch(
            "app.views.get_credentials.get_associate_user_group", return_value=[]
        ).start()
        patch(
            "app.views.get_credentials.is_group_allowed_for_user", return_value=True
        ).start()
        self.addCleanup(patch.stopall)
        logged_in(self.client, "admin", [10])

    def test_response_has_neither_the_password_nor_the_token(self):
        response = self.client.post("/credentials_data/", json={"credentials_id": 1})
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertNotIn(self.PLAIN, text)
        self.assertNotIn(self.token, text)
        body = json.loads(text)
        self.assertNotIn("credentials_password", body)
        self.assertEqual(body["credentials_name"], "core")
        self.assertIs(body["has_password"], True)

    def test_profile_without_a_password(self):
        profile = {
            "credentials_name": "c",
            "credentials_username": "u",
            "credentials_password": None,
            "credentials_user_group": 10,
        }
        self.get.return_value = profile
        body = self.client.post(
            "/credentials_data/", json={"credentials_id": 1}
        ).get_json()
        self.assertIs(body["has_password"], False)
        self.assertNotIn("The password is not set", json.dumps(body))

    def test_a_plain_user_gets_nothing(self):
        logged_in(self.client, "user", [10])
        response = self.client.post("/credentials_data/", json={"credentials_id": 1})
        self.assertNotIn(self.token, response.get_data(as_text=True))


class TestEditFormTemplate(unittest.TestCase):
    """The page HTML/JS must not put a password into the edit form."""

    def setUp(self):
        self.html = TEMPLATE.read_text(encoding="utf-8")

    def test_the_script_does_not_fill_the_password_field(self):
        self.assertNotIn('result["credentials_password"]', self.html)
        self.assertNotRegex(
            self.html, r'#db_credentials_password"\)\s*\.val\(\s*result'
        )

    def test_password_inputs_have_no_value_attribute_and_no_autofill(self):
        for tag in re.findall(r"<input[^>]*type=\"password\"[^>]*>", self.html):
            self.assertNotRegex(tag, r"\svalue\s*=", tag)
            self.assertIn('autocomplete="new-password"', tag)

    def test_the_hint_explains_that_an_empty_field_keeps_the_password(self):
        self.assertIn("Leave blank to keep the current password", self.html)
        self.assertIn("Оставьте пустым, чтобы сохранить текущий пароль", self.html)


class TestCredentialsViewEdit(unittest.TestCase):
    def setUp(self):
        self.flask_app = make_test_app(
            [
                (
                    "/credentials/",
                    "credentials",
                    credentials_view.credentials,
                    ["GET", "POST"],
                )
            ]
        )
        self.client = self.flask_app.test_client()
        logged_in(self.client, "admin", [10])
        self.update = patch(
            "app.views.credentials.update_credentials", return_value=True
        ).start()
        self.add = patch(
            "app.views.credentials.add_credentials", return_value=True
        ).start()
        patch(
            "app.views.credentials.get_credentials",
            return_value={"credentials_user_group": 10},
        ).start()
        patch(
            "app.views.credentials.is_group_allowed_for_user", return_value=True
        ).start()
        patch("app.views.credentials.CREDENTIALS_ENCRYPTION_KEY", KEY).start()
        self.addCleanup(patch.stopall)

    def edit(self, password):
        return self.client.post(
            "/credentials/",
            data={
                "edit_dbprofile_btn": "5",
                "db_credentials_name": "renamed",
                "db_credentials_username": "admin",
                "db_credentials_password": password,
                "db_user-group": "10",
            },
        )

    def test_edit_with_an_empty_password_field(self):
        self.edit("")
        kwargs = self.update.call_args.kwargs
        self.assertEqual(kwargs["credentials_name"], "renamed")
        self.assertEqual(
            kwargs["credentials_password"], ""
        )  # = keep, decided in one place
        self.assertIn("Credentials profile has been modified", flashed(self.client))

    def test_edit_with_a_new_password(self):
        self.edit("New-Pass")
        self.assertEqual(
            self.update.call_args.kwargs["credentials_password"], "New-Pass"
        )

    def test_edit_with_a_too_long_password_is_refused(self):
        self.edit("x" * 2000)
        self.update.assert_not_called()
        self.assertTrue(any("too long" in m for m in flashed(self.client)))

    def test_add_stores_an_encrypted_password_only(self):
        self.client.post(
            "/credentials/",
            data={
                "add_profile_btn": "1",
                "credentials_name": "n",
                "credentials_username": "u",
                "credentials_password": "Plain-Add-Pass",
                "add_user_groups": "10",
            },
        )
        stored = self.add.call_args.kwargs["credentials_password"]
        self.assertNotIn("Plain-Add-Pass", stored)
        self.assertEqual(crypto.decrypt(stored, KEY), "Plain-Add-Pass")

    def test_add_with_a_long_unicode_password(self):
        password = "密码🔑пароль" * 40
        self.client.post(
            "/credentials/",
            data={
                "add_profile_btn": "1",
                "credentials_name": "n",
                "credentials_username": "u",
                "credentials_password": password,
                "add_user_groups": "10",
            },
        )
        self.assertEqual(
            crypto.decrypt(self.add.call_args.kwargs["credentials_password"], KEY),
            password,
        )

    def test_add_with_a_too_long_password_is_refused(self):
        self.client.post(
            "/credentials/",
            data={
                "add_profile_btn": "1",
                "credentials_name": "n",
                "credentials_username": "u",
                "credentials_password": "x" * 2000,
                "add_user_groups": "10",
            },
        )
        self.add.assert_not_called()

    def test_add_without_a_key_does_not_save(self):
        with patch("app.views.credentials.CREDENTIALS_ENCRYPTION_KEY", ""):
            self.client.post(
                "/credentials/",
                data={
                    "add_profile_btn": "1",
                    "credentials_name": "n",
                    "credentials_username": "u",
                    "credentials_password": "pass",
                    "add_user_groups": "10",
                },
            )
        self.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
