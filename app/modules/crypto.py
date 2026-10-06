import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

# The longest password NABS accepts (characters). A Fernet token is about 1.4 times
# longer than the password, so this keeps the stored value far below any column or
# index limit. A longer password is refused with a clear message, never truncated.
MAX_PASSWORD_LENGTH = 1024


class EncryptionKeyError(ValueError):
    """CREDENTIALS_ENCRYPTION_KEY is missing or unusable (a configuration problem)."""


class PasswordTooLongError(ValueError):
    """The password is longer than MAX_PASSWORD_LENGTH characters."""


def _derive_fernet_key(key: str) -> bytes:
    """
    Fernet requires a 32-byte, urlsafe-base64-encoded key. Deterministically
    derive one from an arbitrary secret string (e.g. CREDENTIALS_ENCRYPTION_KEY
    from config.py), so callers keep passing a plain string like before.
    """
    if not isinstance(key, str) or not key.strip():
        raise EncryptionKeyError(
            "CREDENTIALS_ENCRYPTION_KEY is not set: set it in config.py"
            " (it must never be generated again once passwords are saved)"
        )
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def new_password_or_none(value) -> Optional[str]:
    """
    The password field of an edit form: None or an empty string means "keep the
    stored password"; any other text is a NEW password that has to be encrypted.
    (The stored value is never sent to the browser, so it can never come back here.)
    """
    if value is None or value == "":
        return None
    return value


def validate_password(password) -> Optional[str]:
    """None if the password can be stored, otherwise a message that is safe to show."""
    if password is None:
        return None
    if not isinstance(password, str):
        return "The password must be text"
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"The password is too long (at most {MAX_PASSWORD_LENGTH} characters)"
    return None


def encrypt(ssh_pass: str, key: str) -> str:
    """Encrypt ssh password (authenticated encryption via Fernet/AES)."""
    if ssh_pass is None:
        return None
    # the messages never contain the password
    if not isinstance(ssh_pass, str):
        raise TypeError("The password must be text")
    if len(ssh_pass) > MAX_PASSWORD_LENGTH:
        raise PasswordTooLongError(validate_password(ssh_pass))
    fernet = Fernet(_derive_fernet_key(key))
    return fernet.encrypt(ssh_pass.encode("utf-8")).decode("utf-8")


def decrypt(ssh_pass: str, key: str) -> str:
    """Decrypt ssh password. Returns None if ssh_pass is None or decryption
    fails (wrong key, or the value isn't a valid Fernet token - e.g. it was
    never migrated from the old cryptocode format, see
    migrate_credentials_to_fernet.py). A missing key raises EncryptionKeyError:
    that is a configuration error, not a damaged value."""
    if ssh_pass is None:
        return None
    fernet = Fernet(_derive_fernet_key(key))
    try:
        return fernet.decrypt(ssh_pass.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
