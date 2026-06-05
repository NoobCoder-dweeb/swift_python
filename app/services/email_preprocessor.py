from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.email import IncomingEmail


@dataclass(frozen=True)
class PreprocessedEmail:
    email: IncomingEmail
    original_body: str
    removed_lines: list[str]

    @property
    def changed(self) -> bool:
        return self.email.body != self.original_body.strip()


_BOILERPLATE_PATTERNS = (
    r"^caution:",
    r"^external email",
    r"^confidentiality notice",
    r"^disclaimer:",
    r"^this (email|message) and any attachments",
    r"^this (email|message) is confidential",
    r"^the information contained in this",
    r"^if you are not the intended recipient",
    r"^please consider the environment",
    r"^unsubscribe\b",
    r"^virus-free",
)

_CONTACT_PATTERNS = (
    r"^(tel|phone|mobile|cell|fax|direct|office)\s*[:+]",
    r"^e-?mail\s*:",
    r"^web(site)?\s*:",
    r"^www\.",
    r"https?://",
)

_INQUIRY_KEYWORDS = (
    "availability",
    "available",
    "bulk",
    "catalog",
    "cost",
    "delivery",
    "inventory",
    "item",
    "lead time",
    "model",
    "order",
    "part",
    "price",
    "pricing",
    "product",
    "quantity",
    "quote",
    "rate",
    "ship",
    "shipment",
    "sku",
    "stock",
    "unit",
    "units",
)

_REQUEST_PHRASES = (
    "can you",
    "could you",
    "do you",
    "i need",
    "i would like",
    "looking for",
    "please",
    "send me",
    "share",
    "confirm",
)

_QUANTITY_RE = re.compile(
    r"\b\d+(?:[,.]\d+)?\s*(?:units?|pcs?|pieces?|boxes?|cartons?|pairs?|sets?)\b",
    re.IGNORECASE,
)


def preprocess_email(email: IncomingEmail) -> PreprocessedEmail:
    original_body = _normalize_newlines(email.body)
    candidate_lines, removed_lines = _remove_structural_noise(original_body)
    selected_lines = _select_relevant_lines(candidate_lines)

    cleaned_body = _join_lines(selected_lines or candidate_lines)
    if not cleaned_body:
        cleaned_body = original_body.strip()

    return PreprocessedEmail(
        email=IncomingEmail(
            sender=email.sender,
            subject=email.subject,
            body=cleaned_body,
        ),
        original_body=original_body,
        removed_lines=removed_lines,
    )


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _remove_structural_noise(body: str) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    removed: list[str] = []

    for raw_line in body.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        if _starts_quoted_block(line):
            removed.append(line)
            break

        if line.startswith(">"):
            removed.append(line)
            continue

        if _is_greeting(line):
            removed.append(line)
            continue

        if _is_signature_marker(line):
            removed.append(line)
            break

        if kept and _is_signoff(line):
            removed.append(line)
            break

        if _is_boilerplate_line(line) or _is_contact_line(line):
            removed.append(line)
            continue

        kept.append(line)

    return kept, removed


def _select_relevant_lines(lines: list[str]) -> list[str]:
    scored = [(_relevance_score(line), line) for line in lines]
    relevant = [line for score, line in scored if score > 0]
    if not relevant:
        return []

    return relevant


def _relevance_score(line: str) -> int:
    lower = line.lower()
    score = 0

    if any(keyword in lower for keyword in _INQUIRY_KEYWORDS):
        score += 3
    if any(phrase in lower for phrase in _REQUEST_PHRASES):
        score += 2
    if "?" in line:
        score += 2
    if _QUANTITY_RE.search(line):
        score += 2

    return score


def _join_lines(lines: list[str]) -> str:
    cleaned: list[str] = []
    previous = ""
    for line in lines:
        if line == previous:
            continue
        cleaned.append(line)
        previous = line
    return "\n".join(cleaned).strip()


def _starts_quoted_block(line: str) -> bool:
    lower = line.lower()
    return (
        lower.startswith("-----original message-----")
        or lower.startswith("begin forwarded message:")
        or lower.startswith("forwarded message")
        or bool(re.match(r"^on .+wrote:$", lower))
        or bool(re.match(r"^(from|sent|to|subject):\s+.+", line, re.IGNORECASE))
    )


def _is_greeting(line: str) -> bool:
    return bool(
        re.match(
            r"^(hi|hello|dear|good morning|good afternoon|good evening)\b[\w\s,.-]*$",
            line,
            re.IGNORECASE,
        )
    )


def _is_signature_marker(line: str) -> bool:
    return line in {"--", "-- "}


def _is_signoff(line: str) -> bool:
    return bool(
        re.match(
            r"^(thanks|thank you|regards|best regards|kind regards|sincerely|cheers)"
            r"[\s,!.:-]*$",
            line,
            re.IGNORECASE,
        )
    )


def _is_boilerplate_line(line: str) -> bool:
    lower = line.lower()
    return any(re.search(pattern, lower) for pattern in _BOILERPLATE_PATTERNS)


def _is_contact_line(line: str) -> bool:
    lower = line.lower()
    return any(re.search(pattern, lower) for pattern in _CONTACT_PATTERNS)
