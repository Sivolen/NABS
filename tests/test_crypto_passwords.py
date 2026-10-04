"""
TZ 4.3 / 4.4 / 5: encryption of SSH passwords - long passwords, special characters,
Unicode, wrong key, missing key, and errors that never leak the password.
"""

import math
import unittest

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.modules.crypto import (  # noqa: E402
    MAX_PASSWORD_LENGTH,
    EncryptionKeyError,
    PasswordTooLongError,
    decrypt,
    encrypt,
    new_password_or_none,
    validate_password,
)

KEY = "unit-test-key-0123456789abcdef"
OTHER_KEY = "another-key-0123456789abcdefgh"

SPECIAL = "p@ss'w\"rd;--/*%s %d {0} \\n \\ $HOME `id` <script>&amp; \t|"
UNICODE = [
    "пароль-Ж\u0451\u044e",
    "密码测试",
    "pässwörd",
    "🔑secret🔒",
    "ñandú",
    "a\u0301b\u0300",
]


class TestRoundTrip(unittest.TestCase):
    def test_lengths_from_1_to_max(self):
        for n in (
            1,
            2,
            15,
            16,
            17,
            31,
            32,
            63,
            64,
            100,
            127,
            128,
            255,
            256,
            512,
            1000,
            MAX_PASSWORD_LENGTH,
        ):
            password = ("Ab1!" * (n // 4 + 1))[:n]
            token = encrypt(password, KEY)
            self.assertEqual(decrypt(token, KEY), password, n)

    def test_special_characters(self):
        for password in (SPECIAL, " leading and trailing ", "a" * 10 + "\n" + "b", "x"):
            self.assertEqual(decrypt(encrypt(password, KEY), KEY), password)

    def test_unicode(self):
        for password in UNICODE:
            self.assertEqual(decrypt(encrypt(password, KEY), KEY), password)

    def test_unicode_long(self):
        password = "密码🔑" * 200  # 800 characters, ~2200 bytes in UTF-8
        self.assertEqual(decrypt(encrypt(password, KEY), KEY), password)

    def test_none_passes_through(self):
        self.assertIsNone(encrypt(None, KEY))
        self.assertIsNone(decrypt(None, KEY))

    def test_every_encryption_is_different_but_decrypts_the_same(self):
        self.assertNotEqual(encrypt("same", KEY), encrypt("same", KEY))


class TestTokenLength(unittest.TestCase):
    """Documents why VARCHAR(100) was too small."""

    @staticmethod
    def expected_length(n_bytes):
        padded = 16 * (n_bytes // 16 + 1)
        return 4 * math.ceil((57 + padded) / 3)

    def test_token_length_formula(self):
        for n in (0, 1, 15, 16, 100, 500, 1024):
            self.assertEqual(len(encrypt("x" * n, KEY)), self.expected_length(n), n)

    def test_a_16_byte_password_no_longer_fits_in_varchar_100(self):
        self.assertLessEqual(len(encrypt("x" * 15, KEY)), 100)
        self.assertGreater(len(encrypt("x" * 16, KEY)), 100)

    def test_the_longest_allowed_password_fits_far_below_the_index_limit(self):
        # PostgreSQL B-tree entries are limited to ~2700 bytes
        worst = encrypt("🔑" * MAX_PASSWORD_LENGTH, KEY)  # 4 bytes per character
        self.assertLess(len(worst), 6000)
        self.assertLess(len(encrypt("x" * MAX_PASSWORD_LENGTH, KEY)), 1500)


class TestErrors(unittest.TestCase):
    def test_wrong_key_does_not_decrypt(self):
        token = encrypt("secret", KEY)
        self.assertIsNone(decrypt(token, OTHER_KEY))

    def test_damaged_or_foreign_values_do_not_decrypt(self):
        for value in ("", "not-a-token", "gAAAAAB-broken", "Zm9v", "кириллица"):
            self.assertIsNone(decrypt(value, KEY), value)

    def test_missing_key_is_a_clear_configuration_error(self):
        for bad in (None, "", "   ", 0):
            with self.assertRaises(EncryptionKeyError) as raised:
                encrypt("secret", bad)
            self.assertIn("CREDENTIALS_ENCRYPTION_KEY", str(raised.exception))
            with self.assertRaises(EncryptionKeyError):
                decrypt("anything", bad)

    def test_too_long_password_is_refused_not_cut(self):
        with self.assertRaises(PasswordTooLongError) as raised:
            encrypt("x" * (MAX_PASSWORD_LENGTH + 1), KEY)
        self.assertNotIn("xxxxx", str(raised.exception))  # the message has no password
        self.assertIsNotNone(encrypt("x" * MAX_PASSWORD_LENGTH, KEY))

    def test_a_non_text_password_is_refused(self):
        for value in (123, b"bytes", ["x"]):
            with self.assertRaises(TypeError):
                encrypt(value, KEY)

    def test_error_messages_never_contain_the_password_or_the_key(self):
        password = "SuperSecret-" + "z" * MAX_PASSWORD_LENGTH
        try:
            encrypt(password, KEY)
        except PasswordTooLongError as error:
            self.assertNotIn("SuperSecret", str(error))
            self.assertNotIn(KEY, str(error))
        try:
            encrypt("x", "")
        except EncryptionKeyError as error:
            self.assertNotIn("x" * 5, str(error))

    def test_a_failed_decrypt_is_not_confused_with_an_empty_password(self):
        self.assertEqual(decrypt(encrypt("", KEY), KEY), "")
        self.assertIsNone(decrypt("garbage", KEY))


class TestPasswordInput(unittest.TestCase):
    def test_empty_field_means_keep(self):
        self.assertIsNone(new_password_or_none(None))
        self.assertIsNone(new_password_or_none(""))

    def test_anything_else_is_a_new_password(self):
        for value in ("x", " ", "  spaces  ", "0", "None", "The password is not set"):
            self.assertEqual(new_password_or_none(value), value)

    def test_validate_password(self):
        self.assertIsNone(validate_password(None))
        self.assertIsNone(validate_password(""))
        self.assertIsNone(validate_password("x" * MAX_PASSWORD_LENGTH))
        self.assertIn("too long", validate_password("x" * (MAX_PASSWORD_LENGTH + 1)))
        self.assertIsNotNone(validate_password(123))


if __name__ == "__main__":
    unittest.main()
