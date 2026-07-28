from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import regex


@dataclass(frozen=True)
class GuardrailRule:
    """defines one deterministic customer-message risk detector."""

    flag: str
    patterns: tuple[regex.Pattern[str], ...]


@dataclass(frozen=True)
class GuardrailAssessment:
    """summarises guardrail findings for the sales workflow."""

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
    return CustomerInquiryGuardrail(_effective_guardrail_rules()).assess(text)


def default_guardrail_payload() -> list[dict[str, Any]]:
    """serialises default regex rules for the settings UI."""
    return [
        {
            "flag": rule.flag,
            "patterns": [pattern.pattern for pattern in rule.patterns],
        }
        for rule in DEFAULT_GUARDRAIL_RULES
    ]


def compile_guardrail_payload(payload: Any) -> tuple[GuardrailRule, ...]:
    """validates and compiles editable guardrail settings."""
    if not isinstance(payload, list):
        raise ValueError("Guardrail rules must be a list.")

    rules: list[GuardrailRule] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Guardrail rule {index + 1} must be an object.")
        flag = item.get("flag")
        patterns = item.get("patterns")
        if not isinstance(flag, str) or not flag.strip():
            raise ValueError(f"Guardrail rule {index + 1} needs a flag.")
        if not isinstance(patterns, list) or not patterns:
            raise ValueError(f"Guardrail rule {flag} needs at least one pattern.")
        pattern_texts = []
        for pattern_index, pattern in enumerate(patterns):
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError(
                    f"Guardrail rule {flag} pattern {pattern_index + 1} is empty."
                )
            pattern_texts.append(pattern.strip())
        try:
            compiled_patterns = _compile(*pattern_texts)
        except regex.error as exc:
            raise ValueError(
                f"Guardrail rule {flag} has an invalid regex pattern: {exc}"
            ) from exc
        rules.append(GuardrailRule(flag=flag.strip(), patterns=compiled_patterns))
    return tuple(rules)


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


def _effective_guardrail_rules() -> tuple[GuardrailRule, ...]:
    """loads database guardrail overrides, falling back to code defaults."""
    try:
        from app.repositories.state_repository import get_state_repository

        row = get_state_repository().get_setting("guardrail_overrides")
    except Exception:
        return DEFAULT_GUARDRAIL_RULES
    value = row.get("value") if row else None
    if not value:
        return DEFAULT_GUARDRAIL_RULES
    try:
        return compile_guardrail_payload(value)
    except ValueError:
        return DEFAULT_GUARDRAIL_RULES
