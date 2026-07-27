import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _derive_fernet_key(key: str) -> bytes:
    """
    Fernet requires a 32-byte, urlsafe-base64-encoded key. Deterministically
    derive one from an arbitrary secret string (e.g. CREDENTIALS_ENCRYPTION_KEY
    from config.py), so callers keep passing a plain string like before.
    """
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(ssh_pass: str, key: str) -> str:
    """Encrypt ssh password (authenticated encryption via Fernet/AES)."""
    if ssh_pass is None:
        return None
    fernet = Fernet(_derive_fernet_key(key))
    return fernet.encrypt(ssh_pass.encode("utf-8")).decode("utf-8")


def decrypt(ssh_pass: str, key: str) -> str:
    """Decrypt ssh password. Returns None if ssh_pass is None or decryption
    fails (wrong key, or the value isn't a valid Fernet token - e.g. it was
    never migrated from the old cryptocode format, see
    migrate_credentials_to_fernet.py)."""
    if ssh_pass is None:
        return None
    fernet = Fernet(_derive_fernet_key(key))
    try:
        return fernet.decrypt(ssh_pass.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
