"""
Mailgun email service for sending reminder notification emails.

Requires MAILGUN_API_KEY, MAILGUN_DOMAIN, and MAILGUN_FROM_EMAIL in config.
"""
import logging
import httpx
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

MAILGUN_API_BASE = "https://api.mailgun.net/v3"


def _is_configured() -> bool:
    return bool(settings.mailgun_api_key and settings.mailgun_domain)


def send_reminder_email(
    to_email: str,
    subject: str,
    content_title: str,
    reminder_message: str,
    reminder_type: str,
    scheduled_time_display: str,
    app_link: Optional[str] = None,
) -> bool:
    """Send a reminder notification email via Mailgun.

    Returns True on success, False on failure (logged, never raises).
    """
    if not _is_configured():
        logger.debug("Mailgun not configured — skipping email to %s", to_email)
        return False

    from_addr = settings.mailgun_from_email or f"Scene Sentry <noreply@{settings.mailgun_domain}>"
    app_url = app_link or ""

    html_body = _build_html(
        content_title=content_title,
        reminder_message=reminder_message,
        reminder_type=reminder_type,
        scheduled_time_display=scheduled_time_display,
        app_url=app_url,
    )

    try:
        response = httpx.post(
            f"{MAILGUN_API_BASE}/{settings.mailgun_domain}/messages",
            auth=("api", settings.mailgun_api_key),
            data={
                "from": from_addr,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            },
            timeout=15,
        )
        if response.status_code == 200:
            logger.info("Reminder email sent to %s", to_email)
            return True

        logger.warning(
            "Mailgun returned %s for %s: %s",
            response.status_code,
            to_email,
            response.text[:200],
        )
        return False
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_email, exc)
        return False


def _build_html(
    content_title: str,
    reminder_message: str,
    reminder_type: str,
    scheduled_time_display: str,
    app_url: str,
) -> str:
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0a0f;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0f;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#111118;border-radius:12px;border:1px solid rgba(255,255,255,0.06);">
        <!-- Header -->
        <tr>
          <td style="padding:32px 32px 24px;border-bottom:1px solid rgba(255,255,255,0.06);">
            <table width="100%"><tr>
              <td>
                <span style="display:inline-block;width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,hsl(270,70%,60%),hsl(320,80%,60%));text-align:center;line-height:32px;font-size:16px;color:#fff;">&#10024;</span>
              </td>
              <td style="padding-left:10px;">
                <span style="font-size:18px;font-weight:700;color:#fafafa;letter-spacing:-0.3px;">Scene Sentry</span>
              </td>
            </tr></table>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 6px;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:hsl(270,70%,60%);">{reminder_type} Reminder</p>
            <h1 style="margin:0 0 20px;font-size:22px;font-weight:700;color:#fafafa;">{content_title}</h1>
            <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#a1a1aa;">{reminder_message}</p>
            <table cellpadding="0" cellspacing="0" style="background:rgba(255,255,255,0.04);border-radius:8px;width:100%;margin-bottom:28px;">
              <tr>
                <td style="padding:16px 20px;">
                  <span style="font-size:12px;color:#71717a;display:block;margin-bottom:4px;">Scheduled Time</span>
                  <span style="font-size:15px;font-weight:600;color:#fafafa;">{scheduled_time_display}</span>
                </td>
              </tr>
            </table>
            {"<a href='" + app_url + "' style='display:inline-block;padding:12px 28px;background:hsl(270,70%,60%);color:#fff;border-radius:8px;font-size:14px;font-weight:600;text-decoration:none;'>View in App</a>" if app_url else ""}
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="padding:20px 32px;border-top:1px solid rgba(255,255,255,0.06);text-align:center;">
            <p style="margin:0;font-size:12px;color:#52525b;">You received this because you have email notifications enabled in Scene Sentry.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
