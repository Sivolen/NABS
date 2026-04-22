import os
import unittest
from app.modules.crypto import encrypt, decrypt

os.environ["FLASK_ENV"] = "testing"


class TestCrypto(unittest.TestCase):
    def setUp(self):
        self.key = "test_secret_key_12345"
        self.plain = "my_ssh_password"

    def test_encrypt_decrypt(self):
        encrypted = encrypt(self.plain, self.key)
        self.assertIsNotNone(encrypted)
        self.assertNotEqual(encrypted, self.plain)
        decrypted = decrypt(encrypted, self.key)
        self.assertEqual(decrypted, self.plain)

    def test_decrypt_none(self):
        self.assertIsNone(decrypt(None, self.key))


if __name__ == "__main__":
    unittest.main()
