from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import AppSettings, get_app_settings


@dataclass(frozen=True)
class EmailDispatchResult:
    """captures whether SMTP delivery accepted the approved draft."""

    sent: bool
    recipient: str
    error: str | None = None


def send_approved_draft(
    *,
    recipient: str,
    subject: str,
    body: str,
    settings: AppSettings | None = None,
) -> EmailDispatchResult:
    """delivers an approved draft to the original customer email address."""
    settings = settings or get_app_settings()
    recipient = recipient.strip()
    if not recipient:
        return EmailDispatchResult(sent=False, recipient=recipient, error="missing_recipient")
    if not settings.smtp_configured:
        return EmailDispatchResult(
            sent=False,
            recipient=recipient,
            error="smtp_not_configured",
        )

    message = EmailMessage()
    message["To"] = recipient
    message["From"] = formataddr(
        (settings.smtp_from_name, settings.smtp_from_address)
    )
    message["Subject"] = _reply_subject(subject)
    message.set_content(body)

    try:
        with smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout,
        ) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username or settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except Exception as exc:
        return EmailDispatchResult(
            sent=False,
            recipient=recipient,
            error=f"smtp_error:{exc.__class__.__name__}",
        )

    return EmailDispatchResult(sent=True, recipient=recipient)


def _reply_subject(subject: str) -> str:
    """keeps approved replies threaded without duplicating Re prefixes."""
    cleaned = " ".join((subject or "Your inquiry").split())
    if cleaned.lower().startswith("re:"):
        return cleaned
    return f"Re: {cleaned}"
