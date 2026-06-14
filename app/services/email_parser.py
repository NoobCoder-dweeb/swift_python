from __future__ import annotations

from collections.abc import Mapping
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser
from typing import Any

from app.schemas.email import IncomingEmail


class EmailParseError(ValueError):
    """gives routes a typed error they can safely return as 400 responses."""


class _HTMLTextExtractor(HTMLParser):
    """converts HTML emails to plain text before drafting."""

    def __init__(self) -> None:
        """collects text chunks while preserving useful line breaks."""
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        """keeps visible HTML text and ignores empty formatting whitespace."""
        text = data.strip()
        if text:
            self._chunks.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """preserves block boundaries so sentences do not collapse together."""
        if tag in {"br", "p", "div", "li"}:
            self._chunks.append("\n")

    def get_text(self) -> str:
        """returns normalized plain text for downstream preprocessing."""
        return _clean_body("\n".join(self._chunks))


def incoming_email_from_mapping(payload: Mapping[str, Any]) -> IncomingEmail:
    """supports webhook/form aliases without separate route code paths."""
    sender = payload.get("sender") or payload.get("from") or payload.get("mail_from")
    subject = payload.get("subject") or "No subject"
    body = payload.get("body") or payload.get("text") or payload.get("message")

    if isinstance(body, list):
        body = "\n".join(str(item) for item in body)

    email = IncomingEmail(
        sender=str(sender or "").strip(),
        subject=str(subject or "").strip() or "No subject",
        body=str(body or "").strip(),
    )
    _validate_incoming_email(email)
    return email


def parse_rfc822_email(raw: bytes) -> IncomingEmail:
    """lets curl or mail listeners submit real RFC822-style messages."""
    if not raw.strip():
        raise EmailParseError("Email payload is empty.")

    message = BytesParser(policy=policy.default).parsebytes(raw)
    sender_header = message.get("From") or message.get("Sender") or ""
    display_name, sender_address = parseaddr(str(sender_header))
    sender = (sender_address or display_name or str(sender_header)).strip()
    subject = str(message.get("Subject") or "No subject").strip() or "No subject"
    body = _extract_body(message)

    email = IncomingEmail(sender=sender, subject=subject, body=body)
    _validate_incoming_email(email)
    return email


def _validate_incoming_email(email: IncomingEmail) -> None:
    """fails early before empty intake records reach drafting/storage."""
    if not email.sender:
        raise EmailParseError("Email payload is missing a sender/from value.")
    if not email.body.strip():
        raise EmailParseError("Email payload is missing a body.")


def _extract_body(message: Message) -> str:
    """prefers readable text and ignores attachments for safer drafting context."""
    if message.is_multipart():
        body_part = message.get_body(preferencelist=("plain", "html"))
        if body_part:
            return _part_to_text(body_part)

        for part in message.walk():
            if part.is_multipart():
                continue
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type().startswith("text/"):
                return _part_to_text(part)
        return ""

    return _part_to_text(message)


def _part_to_text(part: Message) -> str:
    """decodes varied email payload encodings into a single text body."""
    try:
        content = part.get_content()
    except Exception:
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = part.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")
        else:
            content = payload or ""

    if isinstance(content, bytes):
        charset = part.get_content_charset() or "utf-8"
        content = content.decode(charset, errors="replace")

    text = str(content or "")
    if part.get_content_type() == "text/html":
        parser = _HTMLTextExtractor()
        parser.feed(text)
        return parser.get_text()

    return _clean_body(text)


def _clean_body(text: str) -> str:
    """normalizes line endings so preprocessing rules behave consistently."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()
