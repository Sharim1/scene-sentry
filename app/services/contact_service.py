"""
Deliver contact form submissions via Mailgun or Resend.

If no provider is configured, the message is logged at INFO (operators still see it).
"""

from __future__ import annotations

import html
import logging

import httpx
import resend

from app.config import settings
from app.services import mailgun_service, resend_service

logger = logging.getLogger(__name__)

MAILGUN_API_BASE = "https://api.mailgun.net/v3"


def _build_contact_html(
    name: str,
    reply_email: str,
    subject_line: str,
    message: str,
) -> str:
    safe_name = html.escape(name)
    safe_email = html.escape(reply_email)
    safe_subject = html.escape(subject_line)
    safe_message = html.escape(message).replace("\n", "<br>\n")
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0a0f;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0f;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#111118;border-radius:12px;border:1px solid rgba(255,255,255,0.06);">
        <tr>
          <td style="padding:32px 32px 24px;border-bottom:1px solid rgba(255,255,255,0.06);">
            <span style="font-size:18px;font-weight:700;color:#fafafa;">Scene Sentry — Contact form</span>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 12px;font-size:14px;color:#a1a1aa;"><strong style="color:#fafafa;">From:</strong> {safe_name} &lt;{safe_email}&gt;</p>
            <p style="margin:0 0 24px;font-size:14px;color:#a1a1aa;"><strong style="color:#fafafa;">Subject:</strong> {safe_subject}</p>
            <div style="font-size:15px;line-height:1.6;color:#e4e4e7;">{safe_message}</div>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px;border-top:1px solid rgba(255,255,255,0.06);text-align:center;">
            <p style="margin:0;font-size:12px;color:#52525b;">Reply directly to the sender address above.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send_via_mailgun(
    to_email: str,
    from_addr: str,
    subject: str,
    text_body: str,
    html_body: str,
    reply_to_email: str,
) -> bool:
    if not mailgun_service._is_configured():
        return False
    try:
        response = httpx.post(
            f"{MAILGUN_API_BASE}/{settings.mailgun_domain}/messages",
            auth=("api", settings.mailgun_api_key),
            data={
                "from": from_addr,
                "to": [to_email],
                "subject": subject,
                "text": text_body,
                "html": html_body,
                "h:Reply-To": reply_to_email,
            },
            timeout=15,
        )
        if response.status_code == 200:
            logger.info("Contact form email sent via Mailgun to %s", to_email)
            return True
        logger.warning(
            "Mailgun contact send failed (%s): %s",
            response.status_code,
            response.text[:200],
        )
        return False
    except Exception as exc:
        logger.error("Mailgun contact send error: %s", exc)
        return False


def _send_via_resend(
    to_email: str,
    from_addr: str,
    subject: str,
    text_body: str,
    html_body: str,
    reply_to: str | None,
) -> bool:
    if not resend_service._is_configured():
        return False
    resend.api_key = settings.resend_api_key
    try:
        params: resend.Emails.SendParams = {
            "from": from_addr,
            "to": [to_email],
            "subject": subject,
            "text": text_body,
            "html": html_body,
        }
        if reply_to:
            params["reply_to"] = reply_to
        result = resend.Emails.send(params)
        if result and result.get("id"):
            logger.info(
                "Contact form email sent via Resend to %s (id=%s)",
                to_email,
                result["id"],
            )
            return True
        logger.warning("Resend unexpected response for contact: %s", result)
        return False
    except Exception as exc:
        logger.error("Resend contact send error: %s", exc)
        return False


def deliver_contact_message(
    name: str,
    email: str,
    subject: str | None,
    message: str,
) -> tuple[bool, str]:
    """
    Send contact form to settings.contact_to_email.

    Returns:
        (delivered, method) where method is \"mailgun\", \"resend\", or \"logged\".
    """
    to_addr = (settings.contact_to_email or "").strip()
    subject_line = (subject or "").strip() or "No subject"
    email_subject = f"[Scene Sentry Contact] {subject_line}"

    plain = f"From: {name} <{email}>\nSubject: {subject_line}\n\n{message}"
    html_body = _build_contact_html(name, email, subject_line, message)
    from_addr = settings.effective_contact_from_address
    reply_to = str(email).strip()

    logger.info(
        "Contact form submission: from=%r email=%r subject=%r message_len=%d to=%r",
        name,
        email,
        subject_line,
        len(message),
        to_addr or "(none)",
    )

    if not to_addr:
        logger.info("CONTACT_TO_EMAIL not set — message logged only")
        return False, "logged"

    # Same priority as reminder email: Mailgun first, then Resend
    if _send_via_mailgun(to_addr, from_addr, email_subject, plain, html_body, reply_to):
        return True, "mailgun"

    if _send_via_resend(to_addr, from_addr, email_subject, plain, html_body, reply_to):
        return True, "resend"

    logger.info(
        "No email provider delivered contact message — content was logged above (to=%s)",
        to_addr,
    )
    return False, "logged"
