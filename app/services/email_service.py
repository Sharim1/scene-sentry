"""
Unified email dispatcher.

Tries Mailgun first (primary); falls back to Resend if Mailgun is
unconfigured or fails.  If neither provider is available the call
is a silent no-op.
"""
import logging
from typing import Optional

from app.services import mailgun_service, resend_service

logger = logging.getLogger(__name__)


def send_reminder_email(
    to_email: str,
    subject: str,
    content_title: str,
    reminder_message: str,
    reminder_type: str,
    scheduled_time_display: str,
    app_link: Optional[str] = None,
) -> bool:
    """Attempt to send a reminder email using the first available provider.

    Provider priority: Mailgun -> Resend.
    Returns True if any provider succeeds.
    """
    kwargs = dict(
        to_email=to_email,
        subject=subject,
        content_title=content_title,
        reminder_message=reminder_message,
        reminder_type=reminder_type,
        scheduled_time_display=scheduled_time_display,
        app_link=app_link,
    )

    if mailgun_service._is_configured():
        ok = mailgun_service.send_reminder_email(**kwargs)
        if ok:
            return True
        logger.warning("Mailgun delivery failed for %s — trying Resend fallback", to_email)

    if resend_service._is_configured():
        ok = resend_service.send_reminder_email(**kwargs)
        if ok:
            return True
        logger.warning("Resend delivery also failed for %s", to_email)

    if not mailgun_service._is_configured() and not resend_service._is_configured():
        logger.debug("No email provider configured — skipping email to %s", to_email)

    return False
