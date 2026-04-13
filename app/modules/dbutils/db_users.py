# app/modules/dbutils/db_users.py
from app.models import Users
from app import db, logger


def get_notification_recipients() -> list:
    """
    Returns list of email addresses of users who have enabled email notifications.
    """
    try:
        recipients = [user.email for user in Users.query.filter_by(send_notifications=True).all()]
        logger.debug(f"Found {len(recipients)} users with notifications enabled")
        return recipients
    except Exception as e:
        logger.error(f"Failed to get notification recipients: {e}")
        return []