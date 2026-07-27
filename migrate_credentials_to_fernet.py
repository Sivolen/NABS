#!venv/bin/python3
"""
One-time migration: re-encrypt Credentials.credentials_password from the old
cryptocode+TOKEN scheme to the new Fernet+CREDENTIALS_ENCRYPTION_KEY scheme
(see app/modules/crypto.py).

Why this exists: app/modules/crypto.py no longer knows how to decrypt values
saved with the old cryptocode library - it only speaks Fernet now. Any
credential saved before this migration needs to be decrypted with the OLD
method (cryptocode + the OLD key, which used to be TOKEN) and re-encrypted
with the NEW method (Fernet + CREDENTIALS_ENCRYPTION_KEY) so the app can
still read it.

USAGE
    1. Set CREDENTIALS_ENCRYPTION_KEY in config.py (must be new/different
       from TOKEN - see config_example.py for how to generate one).
    2. BACK UP YOUR DATABASE before running this. This overwrites
       credentials_password in place.
    3. Dry run first (default) to see what WOULD change, without writing:
           ./migrate_credentials_to_fernet.py
    4. Apply for real:
           ./migrate_credentials_to_fernet.py --apply
    5. Restart the app (backuper.py / gunicorn / scheduler) afterwards.

    If a row is already a valid Fernet token (e.g. this script already ran,
    or the credential was saved/edited after the crypto.py switch), it's
    left untouched. If a row can't be decrypted with the legacy key (wrong
    old TOKEN, or already corrupted), it's reported and skipped rather than
    silently destroyed - fix the OLD_TOKEN value below and re-run.
"""

import argparse
import sys

import cryptocode

from app import app, db, logger
from app.models import Credentials
from app.modules.crypto import encrypt, decrypt
from config import CREDENTIALS_ENCRYPTION_KEY

# The OLD value of TOKEN that was used (as SECRET_KEY) to encrypt existing
# credentials with cryptocode, before this migration. If you haven't
# rotated TOKEN since, this is just your current TOKEN - import it directly
# instead of retyping it here:
from config import TOKEN as OLD_TOKEN


def is_already_migrated(value: str) -> bool:
    """True if `value` already decrypts fine with the NEW Fernet scheme."""
    return decrypt(value, CREDENTIALS_ENCRYPTION_KEY) is not None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes. Without this flag, only prints what would change.",
    )
    args = parser.parse_args()

    if not CREDENTIALS_ENCRYPTION_KEY or len(CREDENTIALS_ENCRYPTION_KEY) < 16:
        print("CREDENTIALS_ENCRYPTION_KEY is not set (or too short) in config.py.")
        print("Set it first - see config_example.py for how to generate one.")
        return 1

    with app.app_context():
        rows = Credentials.query.all()
        migrated, already_ok, skipped_empty, failed = 0, 0, 0, 0

        for row in rows:
            if not row.credentials_password:
                skipped_empty += 1
                continue

            if is_already_migrated(row.credentials_password):
                already_ok += 1
                continue

            plain = cryptocode.decrypt(row.credentials_password, OLD_TOKEN)
            if not plain:
                print(
                    f"[FAIL] Credentials id={row.id} name={row.credentials_name!r}: "
                    f"couldn't decrypt with the legacy key - is OLD_TOKEN correct? Skipped."
                )
                failed += 1
                continue

            new_value = encrypt(plain, CREDENTIALS_ENCRYPTION_KEY)
            print(
                f"[{'APPLY' if args.apply else 'DRY-RUN'}] Credentials id={row.id} "
                f"name={row.credentials_name!r}: migrating to Fernet"
            )
            if args.apply:
                row.credentials_password = new_value
            migrated += 1

        if args.apply and migrated:
            db.session.commit()
            logger.info(
                f"Credential encryption migration applied: {migrated} row(s) updated"
            )

        print("\n--- Summary ---")
        print(f"Migrated:            {migrated}")
        print(f"Already on Fernet:    {already_ok}")
        print(f"Empty (skipped):      {skipped_empty}")
        print(f"Failed to decrypt:    {failed}")
        if not args.apply and migrated:
            print("\nThis was a dry run - re-run with --apply to write these changes.")
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
