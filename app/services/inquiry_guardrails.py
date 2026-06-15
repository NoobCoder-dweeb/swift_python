from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import regex


@dataclass(frozen=True)
class GuardrailRule:
    """defines one deterministic customer-message risk detector."""

    flag: str
    patterns: tuple[regex.Pattern[str], ...]


@dataclass(frozen=True)
class GuardrailAssessment:
    """summarizes guardrail findings for the sales workflow."""

    flags: list[str]

    @property
    def blocked(self) -> bool:
        """any guardrail finding makes the inquiry unsupported for drafting."""
        return bool(self.flags)


class CustomerInquiryGuardrail:
    """detects unsafe customer requests before product lookup or drafting."""

    def __init__(self, rules: Iterable[GuardrailRule] | None = None) -> None:
        self.rules = tuple(rules or DEFAULT_GUARDRAIL_RULES)

    def assess(self, text: str) -> GuardrailAssessment:
        """returns stable risk flags from compiled security rules."""
        flags: list[str] = []
        for rule in self.rules:
            if any(pattern.search(text) for pattern in rule.patterns):
                flags.append(rule.flag)

        if any(
            flag in flags
            for flag in (
                "credential_request",
                "data_exfiltration",
                "unauthorized_access",
            )
        ):
            flags.append("hacking_intent")

        return GuardrailAssessment(flags=_dedupe(flags))


def assess_customer_inquiry(text: str) -> GuardrailAssessment:
    """keeps callers independent from guardrail construction details."""
    return DEFAULT_INQUIRY_GUARDRAIL.assess(text)


def _compile(*patterns: str) -> tuple[regex.Pattern[str], ...]:
    return tuple(regex.compile(pattern, regex.IGNORECASE | regex.DOTALL) for pattern in patterns)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


DEFAULT_GUARDRAIL_RULES: tuple[GuardrailRule, ...] = (
    GuardrailRule(
        flag="prompt_injection",
        patterns=_compile(
            r"\bignore\s+(?:all\s+)?(?:previous|prior|above|system|developer)\s+instructions\b",
            r"\b(?:reveal|show|print|dump|repeat)\b.{0,80}\b(?:system prompt|developer message|hidden instructions|confidential prompt)\b",
            r"\bbypass\b.{0,80}\b(?:policy|guardrail|approval|safety|instructions?)\b",
            r"\bact\s+as\b.{0,40}\b(?:system|developer|admin|administrator|root)\b",
            r"\bjailbreak\b|\bDAN mode\b",
        ),
    ),
    GuardrailRule(
        flag="personal_data",
        patterns=_compile(
            r"\b(?:share|show|send|give|provide|reveal|list|export|download|dump|pull|lookup|query)\b.{0,100}\b(?:customer|client|account|user)\b.{0,100}\b(?:data|details|records?|list|database|emails?|phone(?:\s+numbers?)?|billing\s+addresses?|contacts?|personal\s+(?:data|information)|pii)\b",
            r"\b(?:share|show|send|give|provide|reveal|export|download|dump|pull|lookup|query)\b.{0,100}\b(?:phone(?:\s+numbers?)?|billing\s+addresses?|account\s+contacts?|customer\s+emails?|customer\s+list)\b",
            r"\b(?:another|other|all)\s+customers?'?\s+(?:data|details|records?|emails?|phone(?:\s+numbers?)?|billing\s+addresses?|contacts?)\b",
            r"\bcustomer\s+(?:data|details|information|list|database|records?|personal\s+data|pii)\b",
            r"\b(?:client|account|user)\s+(?:data|details|information|records?|pii)\b",
        ),
    ),
    GuardrailRule(
        flag="credential_request",
        patterns=_compile(
            r"\b(?:share|show|send|give|provide|reveal|print|dump|export|download|extract)\b.{0,100}\b(?:passwords?|api\s*keys?|secrets?|tokens?|auth(?:entication)?\s+tokens?|session\s+cookies?|ssh\s+keys?|private\s+keys?|database\s+credentials?)\b",
            r"\b(?:passwords?|api\s*keys?|secrets?|tokens?|session\s+cookies?|ssh\s+keys?|private\s+keys?|database\s+credentials?)\b.{0,80}\b(?:for|from)\b.{0,60}\b(?:admin|database|postgres|crm|customer|account|system)\b",
        ),
    ),
    GuardrailRule(
        flag="data_exfiltration",
        patterns=_compile(
            r"\b(?:dump|export|download|exfiltrate|extract|scrape|copy|pull)\b.{0,100}\b(?:database|postgres|sql|crm|customer|client|account|orders?|emails?|records?|tables?)\b",
            r"\b(?:select|query)\b.{0,80}\b(?:from|all)\b.{0,80}\b(?:customers?|users?|accounts?|emails?|orders?)\b",
        ),
    ),
    GuardrailRule(
        flag="unauthorized_access",
        patterns=_compile(
            r"\b(?:hack|break\s+into|gain\s+access\s+to|unauthori[sz]ed\s+access|privilege\s+escalation|escalate\s+privileges?)\b",
            r"\b(?:bypass|disable|turn\s+off)\b.{0,80}\b(?:login|authentication|auth|mfa|2fa|audit\s+logs?|access\s+control)\b",
            r"\b(?:admin|root|superuser)\s+access\b",
        ),
    ),
)

DEFAULT_INQUIRY_GUARDRAIL = CustomerInquiryGuardrail()
