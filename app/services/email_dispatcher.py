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
    reply_to: str | None = None


def send_approved_draft(
    *,
    recipient: str,
    subject: str,
    body: str,
    settings: AppSettings | None = None,
) -> EmailDispatchResult:
    """delivers an approved draft to the original customer email address."""
    settings = settings or get_app_settings()
    if settings.smtp_configured and not settings.smtp_reply_to_email:
        return EmailDispatchResult(
            sent=False,
            recipient=recipient.strip(),
            error="missing_reply_to",
        )
    return _send_customer_email(
        recipient=recipient,
        subject=subject,
        body=body,
        settings=settings,
    )


def send_bad_attempt_response(
    *,
    recipient: str,
    subject: str,
    settings: AppSettings | None = None,
) -> EmailDispatchResult:
    """tells the sender their message was blocked by the sales workflow."""
    return _send_customer_email(
        recipient=recipient,
        subject=subject,
        body=(
            "Hi,\n\n"
            "We could not process this request because it was identified as a "
            "bad attempt or an unsupported request for this sales workflow. "
            "Please send a product pricing or stock availability question for "
            "an approved product if you need assistance.\n\n"
            "Best regards,\n"
            "Project Swift Support"
        ),
        settings=settings,
    )


def _send_customer_email(
    *,
    recipient: str,
    subject: str,
    body: str,
    settings: AppSettings | None = None,
) -> EmailDispatchResult:
    """sends one plain-text customer email through configured SMTP."""
    settings = settings or get_app_settings()
    recipient = recipient.strip()
    if not recipient:
        return EmailDispatchResult(sent=False, recipient=recipient, error="missing_recipient")
    if not settings.smtp_configured:
        return EmailDispatchResult(
            sent=False,
            recipient=recipient,
            error="smtp_not_configured",
            reply_to=settings.smtp_reply_to_email or None,
        )

    message = EmailMessage()
    message["To"] = recipient
    message["From"] = formataddr(
        (settings.smtp_from_name, settings.smtp_from_address)
    )
    if settings.smtp_reply_to_email:
        message["Reply-To"] = settings.smtp_reply_to_email
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
            reply_to=settings.smtp_reply_to_email or None,
        )

    return EmailDispatchResult(
        sent=True,
        recipient=recipient,
        reply_to=settings.smtp_reply_to_email or None,
    )


def _reply_subject(subject: str) -> str:
    """keeps approved replies threaded without duplicating Re prefixes."""
    cleaned = " ".join((subject or "Your inquiry").split())
    if cleaned.lower().startswith("re:"):
        return cleaned
    return f"Re: {cleaned}"
