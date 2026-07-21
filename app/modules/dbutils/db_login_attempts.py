"""
DB-backed brute-force protection for the /login endpoint.

Failed attempts are tracked per email address. After MAX_FAILED_ATTEMPTS
failures within ATTEMPT_WINDOW, the account is locked for LOCKOUT_DURATION.
Deliberately stored in the DB (not in-process memory) because the app runs
under multiple gunicorn worker processes (see supervisor/config_gunicorn.py) -
an in-memory counter would only ever see a fraction of the real attempts.
"""

from datetime import datetime, timedelta
from typing import Optional

from app import db, logger
from app.models import LoginAttempt

MAX_FAILED_ATTEMPTS = 5
ATTEMPT_WINDOW = timedelta(minutes=15)
LOCKOUT_DURATION = timedelta(minutes=15)


def is_locked_out(email: str) -> Optional[timedelta]:
    """
    Returns the remaining lockout duration if the account is currently
    locked out, or None if the account may attempt to log in.
    """
    if not email:
        return None
    try:
        record = LoginAttempt.query.filter_by(email=email).first()
        if not record or not record.locked_until:
            return None
        remaining = record.locked_until - datetime.utcnow()
        if remaining.total_seconds() <= 0:
            return None
        return remaining
    except Exception as e:
        logger.error(f"Login rate-limit check error for {email}: {e}")
        # Fail open on infra errors - don't lock legitimate users out because
        # of a DB hiccup; the underlying login still requires valid credentials.
        return None


def register_failed_attempt(email: str) -> None:
    """Record a failed login attempt and lock the account out if the
    configured threshold is exceeded."""
    if not email:
        return
    try:
        record = LoginAttempt.query.filter_by(email=email).first()
        now = datetime.utcnow()
        if not record:
            record = LoginAttempt(email=email, failed_count=1, last_attempt_at=now)
            db.session.add(record)
        else:
            # Reset the counter if the previous failure was outside the window
            if record.last_attempt_at and now - record.last_attempt_at > ATTEMPT_WINDOW:
                record.failed_count = 0
            record.failed_count += 1
            record.last_attempt_at = now

        if record.failed_count >= MAX_FAILED_ATTEMPTS:
            record.locked_until = now + LOCKOUT_DURATION
            logger.warning(
                f"Account {email} locked out until {record.locked_until} "
                f"after {record.failed_count} failed login attempts"
            )
        db.session.commit()
    except Exception as e:
        logger.error(f"Failed to register failed login attempt for {email}: {e}")
        db.session.rollback()


def reset_attempts(email: str) -> None:
    """Clear the failed-attempt counter after a successful login."""
    if not email:
        return
    try:
        record = LoginAttempt.query.filter_by(email=email).first()
        if record and (record.failed_count or record.locked_until):
            record.failed_count = 0
            record.locked_until = None
            db.session.commit()
    except Exception as e:
        logger.error(f"Failed to reset login attempts for {email}: {e}")
        db.session.rollback()
