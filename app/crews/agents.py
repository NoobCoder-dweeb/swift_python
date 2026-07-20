from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

import app.core.environment  # noqa: F401
from app.crews.agent_config import get_agent_definition
from app.crews.workflow_models import (
    DraftValidationResult,
    InquiryDetails,
    ProductContext,
    ProductOption,
)
from app.services.inquiry_guardrails import assess_customer_inquiry

try:
    _crewai = import_module("crewai")
except Exception as exc:  # pragma: no cover - depends on optional runtime install
    _crewai = None
    _CREWAI_AGENT_IMPORT_ERROR = exc
else:
    _CREWAI_AGENT_IMPORT_ERROR = None


class ProductLookupClient(Protocol):
    """allows tests or ERP/Odoo clients to supply product facts."""

    def get_product(self, query: str) -> dict[str, Any]:
        """defines the lookup contract without depending on one ERP client."""
        ...


@dataclass(frozen=True)
class LocalLLMConfig:
    """captures local model settings without hard-coding them in agents."""

    model: str = "llama3.2:3b"
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    timeout: int = 45
    temperature: float = 0.1

    @classmethod
    def from_env(cls) -> "LocalLLMConfig":
        """lets deployments tune local LLM settings through environment variables."""
        return cls(
            model=_env_text("SWIFT_LOCAL_LLM_MODEL", cls.model),
            provider=_env_text("SWIFT_LOCAL_LLM_PROVIDER", cls.provider),
            base_url=_env_text("SWIFT_LOCAL_LLM_BASE_URL", cls.base_url),
            timeout=_env_int("SWIFT_LOCAL_LLM_TIMEOUT", cls.timeout, minimum=1),
            temperature=_env_float(
                "SWIFT_LOCAL_LLM_TEMPERATURE",
                cls.temperature,
                minimum=0.0,
            ),
        )

    @classmethod
    def for_role(cls, role: str, default_model: str) -> "LocalLLMConfig":
        """supports separate model choices for each CrewAI responsibility."""
        prefix = f"SWIFT_{role.upper()}_LLM"
        return cls(
            model=_env_text(
                f"{prefix}_MODEL",
                _env_text("SWIFT_LOCAL_LLM_MODEL", default_model)
                if role == "sales"
                else default_model,
            ),
            provider=_env_text(
                f"{prefix}_PROVIDER",
                _env_text("SWIFT_LOCAL_LLM_PROVIDER", cls.provider),
            ),
            base_url=_env_text(
                f"{prefix}_BASE_URL",
                _env_text("SWIFT_LOCAL_LLM_BASE_URL", cls.base_url),
            ),
            timeout=_env_int(
                f"{prefix}_TIMEOUT",
                _env_int("SWIFT_LOCAL_LLM_TIMEOUT", cls.timeout, minimum=1),
                minimum=1,
            ),
            temperature=_env_float(
                f"{prefix}_TEMPERATURE",
                _env_float(
                    "SWIFT_LOCAL_LLM_TEMPERATURE",
                    cls.temperature,
                    minimum=0.0,
                ),
                minimum=0.0,
            ),
        )


@dataclass(frozen=True)
class MultiAgentLLMConfig:
    """groups role-specific LLMs so one model is not reused accidentally."""

    supervisor: LocalLLMConfig = field(
        default_factory=lambda: LocalLLMConfig(model="nemotron-mini:4b")
    )
    sales: LocalLLMConfig = field(
        default_factory=lambda: LocalLLMConfig(model="llama3.2:3b")
    )
    drafting: LocalLLMConfig = field(
        default_factory=lambda: LocalLLMConfig(model="qwen2.5:3b")
    )

    @classmethod
    def from_env(
        cls, sales_override: LocalLLMConfig | None = None
    ) -> "MultiAgentLLMConfig":
        """builds the multi-agent model map from deployment configuration."""
        config = cls(
            supervisor=LocalLLMConfig.for_role(
                "supervisor", "nemotron-mini:4b"
            ),
            sales=sales_override
            or LocalLLMConfig.for_role("sales", "llama3.2:3b"),
            drafting=LocalLLMConfig.for_role("draft", "qwen2.5:3b"),
        )
        config.validate_unique_models()
        return config

    def validate_unique_models(self) -> None:
        """avoids role collapse when separate agents should provide checks."""
        if _env_bool("SWIFT_ALLOW_SHARED_LLM_MODELS", False):
            return
        role_models = {
            "supervisor": self.supervisor.model,
            "sales": self.sales.model,
            "draft": self.drafting.model,
        }
        if len(set(role_models.values())) != len(role_models):
            raise ValueError(
                "CrewAI role models must be unique: "
                + ", ".join(f"{role}={model}" for role, model in role_models.items())
            )

    def model_names(self) -> dict[str, str]:
        """records which model handled each role for observability."""
        return {
            "supervisor": self.supervisor.model,
            "sales": self.sales.model,
            "draft": self.drafting.model,
        }


DEFAULT_PRODUCT_CATALOG: list[ProductContext] = [
    ProductContext(
        product="Safety Helmet",
        sku="SAFE-HELMET-001",
        stock_availability=120,
        price=25.0,
        currency="RM",
        lead_time_days=7,
        confidence=0.95,
        notes=["Aliases: helmet, hard hat, safety helmet"],
    ),
    ProductContext(
        product="Product X",
        sku="PROD-X-001",
        stock_availability=500,
        price=120.0,
        currency="RM",
        lead_time_days=10,
        confidence=0.9,
        notes=["Bulk orders of 100 or more units may qualify for RM 95.00 pricing."],
    ),
    ProductContext(
        product="Safety Gloves",
        sku="SAFE-GLOVES-001",
        stock_availability=900,
        price=8.5,
        currency="RM",
        lead_time_days=5,
        confidence=0.88,
        notes=["Aliases: gloves, safety gloves"],
    ),
]

_PRODUCT_ALIASES: dict[str, tuple[str, ...]] = {
    "Safety Helmet": ("safety helmet", "helmets", "helmet", "hard hat", "hard hats"),
    "Product X": ("product x", "prod x", "product-x", "prod-x-001"),
    "Safety Gloves": ("safety gloves", "gloves", "glove"),
}

_QUANTITY_RE = re.compile(
    r"\b(?P<quantity>\d{1,3}(?:,\d{3})+|\d{1,6})(?:\.\d+)?\s*(?:units?|pcs?|pieces?|boxes?|cartons?|pairs?|sets?)?\b",
    re.IGNORECASE,
)

_NUMBER_WORDS: dict[str, int] = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


class SalesProcessingAgent:
    """extracts safe structured sales context before drafting begins."""

    def __init__(self, product_client: ProductLookupClient | None = None) -> None:
        """allows approved product data to come from a real client or local catalog."""
        self.product_client = product_client

    def extract_inquiry(self, sender: str, subject: str, body: str) -> InquiryDetails:
        """turns free-form email text into bounded workflow inputs."""
        text = f"{subject}\n{body}".strip()
        lower = text.lower()
        risk_flags = self.detect_risks(text)

        listing = _is_product_listing_request(lower)
        pricing = _contains_any(
            lower,
            (
                "price",
                "pricing",
                "quote",
                "cost",
                "rate",
                "how much",
                "total",
                "buy",
                "purchase",
                "harga",
                "berapa",
            ),
        )
        availability = _contains_any(
            lower,
            (
                "stock",
                "availability",
                "available",
                "inventory",
                "in stock",
                "carry",
                "supply",
                "delivery",
                "courier",
                "ship",
                "shipment",
                "order",
            ),
        )
        pricing_only = _contains_any(
            lower,
            (
                "only need price",
                "only need pricing",
                "price only",
                "pricing only",
                "quote only",
                "only need item pricing",
            ),
        )
        if pricing_only:
            availability = False

        if risk_flags:
            inquiry_type = "unsupported"
        elif listing:
            inquiry_type = "listing"
        elif pricing and availability:
            inquiry_type = "mixed"
        elif pricing:
            inquiry_type = "pricing"
        elif availability:
            inquiry_type = "availability"
        else:
            inquiry_type = "unknown"

        product_name = self._detect_product(lower)
        quantity = self._detect_quantity(lower)
        requested_delivery = self._detect_delivery(text)
        missing_information = self._missing_information(
            inquiry_type=inquiry_type,
            product_name=product_name,
            quantity=quantity,
            requested_delivery=requested_delivery,
        )

        confidence = 0.25
        if inquiry_type in {"pricing", "availability", "mixed"}:
            confidence += 0.3
        if product_name:
            confidence += 0.25
        if quantity:
            confidence += 0.1
        if not risk_flags:
            confidence += 0.1

        return InquiryDetails(
            sender=sender,
            subject=subject,
            body=body,
            inquiry_type=inquiry_type,
            product_name=product_name,
            quantity=quantity,
            requested_delivery=requested_delivery,
            missing_information=missing_information,
            risk_flags=risk_flags,
            confidence=round(min(confidence, 0.99), 2),
        )

    def get_product_context(self, query: str) -> dict[str, Any]:
        """exposes product lookup in the older dict format used by tests."""
        if self.product_client:
            try:
                return ProductContext.model_validate(
                    self.product_client.get_product(query)
                ).model_dump()
            except Exception as exc:
                return ProductContext(
                    product=self._detect_product(query.lower()),
                    source="product_client",
                    confidence=0.0,
                    notes=[
                        "Product lookup failed; draft should ask for confirmation.",
                        _format_error_note(exc),
                    ],
                ).model_dump()

        product_name = self._detect_product(query.lower())
        context = self.lookup_product_context(product_name, query)
        return context.model_dump()

    def lookup_product_context(
        self, product_name: str | None, query: str = ""
    ) -> ProductContext:
        """keeps drafting grounded in approved catalog/ERP facts."""
        if self.product_client:
            try:
                return ProductContext.model_validate(self.product_client.get_product(query))
            except Exception as exc:
                return ProductContext(
                    product=product_name,
                    source="product_client",
                    confidence=0.0,
                    notes=[
                        "Product lookup failed; draft should ask for confirmation.",
                        _format_error_note(exc),
                    ],
                )

        target = product_name or self._detect_product(query.lower())
        for item in DEFAULT_PRODUCT_CATALOG:
            if item.product == target:
                return item

        return ProductContext(
            product=target,
            source="local_catalog",
            confidence=0.0,
            notes=["No approved product record matched the inquiry."],
            suggested_products=_local_product_suggestions(query or target or "", limit=3),
        )

    def lookup_product_list_context(self, query: str) -> ProductContext:
        """returns approved catalog rows for list-style customer requests."""
        limit = _requested_listing_limit(query)
        if self.product_client and hasattr(self.product_client, "search_products"):
            try:
                search_products = getattr(self.product_client, "search_products")
                products = [
                    ProductOption.model_validate(item)
                    for item in search_products(query, limit=limit)
                ]
                return ProductContext(
                    product=None,
                    source="product_client",
                    confidence=0.9 if products else 0.0,
                    notes=["Catalog list request grounded in persisted products."],
                    listed_products=products,
                )
            except Exception as exc:
                return ProductContext(
                    source="product_client",
                    confidence=0.0,
                    notes=[
                        "Product list lookup failed; draft should ask for confirmation.",
                        _format_error_note(exc),
                    ],
                )

        products = _local_product_suggestions(query, limit=limit)
        if not products and _is_product_listing_request(query.lower()):
            products = _local_product_options(limit=limit)
        return ProductContext(
            product=None,
            source="local_catalog",
            confidence=0.9 if products else 0.0,
            notes=["Catalog list request grounded in local approved products."],
            listed_products=products,
        )

    def detect_risks(self, text: str) -> list[str]:
        """blocks unsafe requests before product lookup or drafting."""
        return assess_customer_inquiry(text).flags

    def _detect_product(self, lower_text: str) -> str | None:
        """maps customer wording to approved product catalog names."""
        for product, aliases in _PRODUCT_ALIASES.items():
            if any(alias in lower_text for alias in aliases):
                return product
        return None

    def _detect_quantity(self, lower_text: str) -> int | None:
        """extracts order size so stock and pricing replies can be specific."""
        matches = [
            int(match.group("quantity").replace(",", ""))
            for match in _QUANTITY_RE.finditer(lower_text)
            if int(match.group("quantity").replace(",", "")) > 0
        ]
        word_quantity = _detect_word_quantity(lower_text)
        if word_quantity:
            matches.append(word_quantity)
        if not matches:
            return None
        return max(matches)

    def _detect_delivery(self, text: str) -> str | None:
        """captures urgency/timing signals that affect availability replies."""
        lowered = text.lower()
        for phrase in (
            "next week",
            "this week",
            "urgent",
            "immediate",
            "asap",
            "june shipment",
            "courier",
        ):
            if phrase in lowered:
                return phrase
        return None

    def _missing_information(
        self,
        inquiry_type: str,
        product_name: str | None,
        quantity: int | None,
        requested_delivery: str | None,
    ) -> list[str]:
        """tells the draft to ask for facts that are needed but absent."""
        missing: list[str] = []
        if inquiry_type in {"pricing", "availability", "mixed"}:
            if not product_name:
                missing.append("product_name")
            if not quantity:
                missing.append("quantity")
            if inquiry_type in {"availability", "mixed"} and not requested_delivery:
                missing.append("requested_delivery")
        return missing


class EmailDraftingAgent:
    """creates bounded customer replies from structured, approved context."""

    def generate(self, info: dict[str, Any] | ProductContext | InquiryDetails) -> str:
        """preserves compatibility with tests and newer workflow models."""
        if isinstance(info, ProductContext):
            context = info
            inquiry = None
        elif isinstance(info, InquiryDetails):
            context = ProductContext(product=info.product_name)
            inquiry = info
        else:
            context = ProductContext.model_validate(
                {
                    "product": info.get("product"),
                    "sku": info.get("sku"),
                    "stock_availability": info.get("stock_availability"),
                    "price": info.get("price"),
                    "currency": info.get("currency", "RM"),
                    "lead_time_days": info.get("lead_time_days"),
                    "confidence": info.get("confidence", 0.0),
                }
            )
            inquiry = None

        return self.generate_response(inquiry, context)

    def generate_response(
        self,
        inquiry: InquiryDetails | None,
        context: ProductContext,
        reviewer_feedback: str | None = None,
    ) -> str:
        """drafts from known facts only, asking for missing details instead of guessing."""
        feedback = (reviewer_feedback or "").strip()
        feedback_lower = feedback.lower()
        if inquiry and inquiry.inquiry_type == "unsupported":
            return (
                "Hi,\n\n"
                "Thanks for your message. I cannot help with requests for confidential "
                "customer information, credentials, system access, data extraction, or "
                "instructions that bypass our sales workflow. Please send a product "
                "pricing or stock availability question and I can help route it for "
                "review.\n\n"
                "Best regards,\n"
                "Project Swift Support"
            )
        if inquiry and inquiry.inquiry_type == "unknown":
            return (
                "Hi,\n\n"
                "Thanks for your message. This workflow only supports product pricing "
                "and stock availability inquiries. Please send a product pricing or "
                "availability question and I can help route it for review.\n\n"
                "Best regards,\n"
                "Project Swift Support"
            )

        product = context.product or (inquiry.product_name if inquiry else None)
        if context.listed_products:
            lines = [
                "Hi,",
                "",
                "Thanks for your inquiry. The following approved products match your request:",
            ]
            lines.extend(_format_product_option_line(item) for item in context.listed_products)
            lines.append(
                "Please confirm the product name or SKU you would like us to quote."
            )
            lines.extend(["", "Best regards,", "Project Swift Support"])
            return "\n".join(lines)

        product_missing = (
            context.confidence == 0.0
            and any(
                "No approved product record matched" in note
                for note in context.notes
            )
        )
        if product_missing:
            product_phrase = f" for {product}" if product else ""
            lines = [
                "Hi,",
                "",
                f"Thanks for your inquiry{product_phrase}. We don't have this product "
                "listed in our approved product database, so I cannot quote price "
                "or stock availability for it.",
            ]
            if context.suggested_products:
                lines.append("Do you mean one of the following:")
                lines.extend(
                    _format_product_option_line(item)
                    for item in context.suggested_products[:3]
                )
            lines.append(
                "Please confirm the product name, SKU, category, or description "
                "keywords so we can match it to the correct database record."
            )
            lines.extend(["", "Best regards,", "Project Swift Support"])
            return "\n".join(lines)
        if not product:
            return (
                "Hi,\n\n"
                "Thanks for your inquiry. Could you please confirm the product name, "
                "quantity required, and target delivery timing so we can check pricing "
                "and stock availability accurately?\n\n"
                "Best regards,\n"
                "Project Swift Support"
            )

        wants_concise = any(
            token in feedback_lower for token in ("short", "brief", "concise", "too long")
        )
        wants_price = any(
            token in feedback_lower for token in ("price", "pricing", "quote", "rate")
        )
        wants_stock = any(
            token in feedback_lower
            for token in ("stock", "availability", "inventory", "available")
        )
        wants_lead_time = any(
            token in feedback_lower
            for token in ("lead time", "timeline", "delivery", "ship", "shipment")
        )
        avoid_price = any(
            token in feedback_lower
            for token in ("remove price", "without price", "no price", "do not mention price")
        )
        avoid_stock = any(
            token in feedback_lower
            for token in ("remove stock", "without stock", "do not mention stock")
        )

        lines = [
            "Hi,",
            "",
            f"Thanks for your inquiry about {product}.",
        ]

        requested_type = inquiry.inquiry_type if inquiry else "mixed"
        should_include_price = (
            (requested_type in {"pricing", "availability", "mixed"} or wants_price)
            and not avoid_price
            and context.price is not None
        )
        should_include_stock = (
            (requested_type in {"availability", "mixed"} or wants_stock)
            and not avoid_stock
            and context.stock_availability is not None
        )
        should_include_lead_time = context.lead_time_days is not None and (
            requested_type in {"availability", "mixed"} or wants_lead_time
        )

        if should_include_price:
            if inquiry and inquiry.quantity and requested_type in {"pricing", "mixed"}:
                total_price = inquiry.quantity * context.price
                lines.append(
                    f"The total price for {inquiry.quantity} units is "
                    f"{context.currency} {total_price:.2f}."
                )
                lines.extend(
                    [
                        "Quote summary:",
                        f"- Product: {product}",
                        f"- Units requested: {inquiry.quantity}",
                        f"- Price per unit: {context.currency} {context.price:.2f}",
                        f"- Total: {context.currency} {total_price:.2f}",
                    ]
                )
                lines.append(
                    f"This is calculated because the approved reference price is "
                    f"{context.currency} {context.price:.2f} per unit, so "
                    f"{inquiry.quantity} x {context.currency} {context.price:.2f} = "
                    f"{context.currency} {total_price:.2f}."
                )
            else:
                lines.append(
                    f"The approved reference price is {context.currency} "
                    f"{context.price:.2f} per unit."
                )
        elif wants_price:
            lines.append(
                "I do not have an approved price in the product context, so sales "
                "review should confirm pricing before quoting."
            )

        if should_include_stock:
            if context.stock_availability == 0:
                lines.append(f"{product} is not in stock.")
            else:
                lines.append(
                    f"Current available stock is {context.stock_availability} units."
                )
        elif wants_stock:
            lines.append(
                "I do not have approved stock availability in the product context, "
                "so sales review should confirm inventory before committing stock."
            )

        if should_include_lead_time:
            lines.append(
                f"Typical lead time is {context.lead_time_days} business days "
                "after order confirmation."
            )

        if inquiry:
            if inquiry.quantity and context.stock_availability is not None:
                if requested_type not in {"availability", "mixed"}:
                    pass
                elif context.stock_availability == 0:
                    lines.append(
                        "Because this product is not in stock, sales review should "
                        "confirm restock timing before committing availability."
                    )
                elif inquiry.quantity <= context.stock_availability:
                    lines.append(
                        f"Your requested quantity of {inquiry.quantity} units appears "
                        "to be within the current available stock."
                    )
                else:
                    lines.append(
                        f"Your requested quantity of {inquiry.quantity} units is above "
                        "current available stock, so allocation needs sales review."
                    )
            if inquiry.missing_information:
                readable = ", ".join(
                    item.replace("_", " ") for item in inquiry.missing_information
                )
                lines.append(f"Please confirm the missing details: {readable}.")

        if wants_concise:
            lines = _condense_response_lines(lines)

        lines.extend(["", "Best regards,", "Project Swift Support"])
        return "\n".join(lines)

    def validate_draft(
        self, draft: str, info: dict[str, Any] | ProductContext | None = None
    ) -> DraftValidationResult:
        """catches unsafe, incomplete, or placeholder-filled drafts before review."""
        reasons: list[str] = []
        lower = draft.lower()

        if len(draft.split()) < 20:
            reasons.append("draft_too_short")
        if "hi," not in lower and "dear" not in lower:
            reasons.append("missing_customer_greeting")
        if "best regards" not in lower:
            reasons.append("missing_signature")
        if any(term in lower for term in ("unknown", "tbd", "invented")):
            reasons.append("contains_unapproved_placeholder")
        if re.search(r"\[[^\]]+\]", draft):
            reasons.append("contains_signature_placeholder")
        if any(
            term in lower
            for term in (
                "your name",
                "your position",
                "your company",
                "sales representative",
            )
        ):
            reasons.append("contains_generic_signature_placeholder")
        if any(line.strip().lower().startswith("subject:") for line in draft.splitlines()):
            reasons.append("contains_subject_line")
        if any(
            term in lower
            for term in (
                "no additional cost",
                "no extra cost",
                "free of charge",
                "no cost",
            )
        ):
            reasons.append("contains_unapproved_commercial_claim")

        if info:
            product = (
                info.product
                if isinstance(info, ProductContext)
                else str(info.get("product") or "")
            )
            if product and product.lower() not in lower:
                reasons.append("missing_product_reference")
            context = (
                info
                if isinstance(info, ProductContext)
                else ProductContext.model_validate(info)
            )
            reasons.extend(_find_unapproved_fact_claims(draft, context))

        if reasons:
            return DraftValidationResult(
                valid=False,
                action="regenerate",
                reasons=reasons,
            )

        return DraftValidationResult(valid=True, action="approve", reasons=[])


def _condense_response_lines(lines: list[str]) -> list[str]:
    """honors concise feedback while preserving factual content lines."""
    content = [line for line in lines[2:] if line.strip()]
    if not content:
        return lines
    return [
        "Hi,",
        "",
        " ".join(content[:9]),
    ]


def _format_product_option_line(item: ProductOption) -> str:
    price = (
        f"{item.currency} {item.price:.2f}"
        if item.price is not None
        else "pricing to be confirmed"
    )
    stock = (
        f"{item.stock_availability} {item.unit_of_measure or 'units'} available"
        if item.stock_availability is not None
        else "stock to be confirmed"
    )
    sku = f" ({item.sku})" if item.sku else ""
    category = f", Category: {item.category}" if item.category else ""
    return f"- {item.product}{sku}: {price} per {item.unit_of_measure or 'unit'}, {stock}{category}."


def _detect_word_quantity(lower_text: str) -> int | None:
    dozen_match = re.search(
        r"\b(?P<count>a|an|half|one|two|three|four|five|six|seven|eight|nine|ten)?\s*dozen\b",
        lower_text,
    )
    if dozen_match:
        count = (dozen_match.group("count") or "one").strip()
        if count == "half":
            return 6
        return _NUMBER_WORDS.get(count, 1) * 12

    unit_match = re.search(
        r"\b(?P<words>(?:one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
        r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
        r"eighty|ninety)(?:[-\s]+(?:one|two|three|four|five|six|seven|"
        r"eight|nine))?)\s+"
        r"(?:units?|pcs?|pieces?|boxes?|cartons?|pairs?|sets?)\b",
        lower_text,
    )
    if not unit_match:
        return None
    return _parse_number_words(unit_match.group("words"))


def _parse_number_words(value: str) -> int | None:
    parts = re.split(r"[-\s]+", value.strip())
    total = sum(_NUMBER_WORDS.get(part, 0) for part in parts)
    return total if total > 0 else None


def _find_unapproved_fact_claims(
    draft: str,
    context: ProductContext,
) -> list[str]:
    """rejects regenerated drafts that drift from approved product data."""
    reasons: list[str] = []
    lower = draft.lower()
    catalog_options = _catalog_options(context)
    allowed_prices = {context.price} if context.price is not None else set()
    if context.price is not None:
        for quantity_match in re.finditer(
            r"\b(?P<quantity>\d{1,6})\s+units?\b|"
            r"\bunits\s+requested:\s*(?P<requested>\d{1,6})\b",
            draft,
            re.IGNORECASE,
        ):
            quantity = int(
                quantity_match.group("quantity") or quantity_match.group("requested")
            )
            if quantity > 0:
                allowed_prices.add(quantity * context.price)
    for option in catalog_options:
        if option.price is not None:
            allowed_prices.add(option.price)
            for quantity_match in re.finditer(
                r"\b(?P<quantity>\d{1,6})\s+units?\b|"
                r"\bunits\s+requested:\s*(?P<requested>\d{1,6})\b",
                draft,
                re.IGNORECASE,
            ):
                quantity = int(
                    quantity_match.group("quantity")
                    or quantity_match.group("requested")
                )
                if quantity > 0:
                    allowed_prices.add(quantity * option.price)
    for note in context.notes:
        allowed_prices.update(
            float(group)
            for groups in re.findall(
                r"(?:usd|rm|myr|\$)\s*(\d+(?:\.\d{1,2})?)|"
                r"(\d+(?:\.\d{1,2})?)\s*(?:usd|rm|myr)",
                note,
                re.IGNORECASE,
            )
            for group in groups
            if group
        )

    allowed_currency = _normalize_currency(context.currency)
    for match in re.finditer(
        r"(?P<currency>usd|rm|myr|\$)\s*(?P<amount>\d+(?:\.\d{1,2})?)",
        draft,
        re.IGNORECASE,
    ):
        currency = _normalize_currency(match.group("currency"))
        if currency != allowed_currency:
            reasons.append("contains_unapproved_currency")
            continue
        amount = float(match.group("amount"))
        if allowed_prices and not any(abs(amount - price) < 0.01 for price in allowed_prices):
            reasons.append("contains_unapproved_price")
        elif not allowed_prices:
            reasons.append("contains_unapproved_price")

    stock_match = re.search(
        r"(?:current\s+available\s+stock|available\s+stock|inventory)\D{0,20}"
        r"(?P<stock>\d{1,6})\s+units?",
        draft,
        re.IGNORECASE,
    )
    if stock_match:
        claimed_stock = int(stock_match.group("stock"))
        if context.stock_availability is None or claimed_stock != context.stock_availability:
            reasons.append("contains_unapproved_stock_claim")
    elif context.stock_availability is None and _claims_stock_availability(lower):
        reasons.append("contains_unapproved_stock_claim")

    allowed_stock_values = {
        item.stock_availability
        for item in catalog_options
        if item.stock_availability is not None
    }
    if context.stock_availability is not None:
        allowed_stock_values.add(context.stock_availability)
    for match in re.finditer(
        r"\b(?P<stock>\d{1,6})\s+"
        r"(?:units?|pcs?|pieces?|pairs?|sets?)\s+available\b",
        draft,
        re.IGNORECASE,
    ):
        claimed_stock = int(match.group("stock"))
        if claimed_stock not in allowed_stock_values:
            reasons.append("contains_unapproved_stock_claim")

    allowed_products = {
        item.product.lower()
        for item in catalog_options
        if item.product
    }
    if context.product:
        allowed_products.add(context.product.lower())
    for line in draft.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        label = stripped[2:].split(":", 1)[0]
        label = re.sub(r"\s*\([^)]*\)\s*$", "", label).strip().lower()
        if label in {"product", "units requested", "price per unit", "total"}:
            continue
        if label and allowed_products and label not in allowed_products:
            reasons.append("contains_unapproved_product_reference")

    lead_time_match = re.search(
        r"(?:lead\s*time|delivery\s*timeline|timeline)\D{0,30}"
        r"(?P<days>\d{1,3})\s+business\s+days?",
        draft,
        re.IGNORECASE,
    )
    if lead_time_match:
        claimed_days = int(lead_time_match.group("days"))
        if context.lead_time_days is None or claimed_days != context.lead_time_days:
            reasons.append("contains_unapproved_lead_time")

    return _dedupe(reasons)


def _catalog_options(context: ProductContext) -> list[ProductOption]:
    """returns every persisted row approved for list or suggestion drafting."""
    return [*context.listed_products, *context.suggested_products]


def _claims_stock_availability(lower_draft: str) -> bool:
    """detects qualitative stock promises when no stock fact was provided."""
    stock_claim_patterns = (
        r"\bwithin\s+(?:the\s+)?current(?:ly)?\s+available\s+stock\b",
        r"\b(?:is|are|appears?|seems?)\s+(?:to\s+be\s+)?(?:currently\s+)?(?:available|in stock|not in stock|out of stock)\b",
        r"\b(?:currently\s+)?available\s+for\s+(?:immediate\s+)?(?:shipment|delivery)\b",
    )
    return any(
        re.search(pattern, lower_draft, re.IGNORECASE)
        for pattern in stock_claim_patterns
    )


def _normalize_currency(currency: str) -> str:
    value = (currency or "").strip().lower()
    if value in {"rm", "myr"}:
        return "rm"
    if value in {"usd", "$"}:
        return "usd"
    return value


def _dedupe(values: list[str]) -> list[str]:
    """keeps validation reasons stable and readable."""
    return list(dict.fromkeys(values))


def create_local_llm(config: LocalLLMConfig | None = None):
    """centralizes CrewAI LLM construction for every agent factory."""
    _configure_crewai_storage()
    llm_class = _crewai_symbol("LLM")

    config = config or LocalLLMConfig.from_env()
    model = _normalize_model_name(config.model, config.provider)
    return llm_class(
        model=model,
        provider=config.provider,
        base_url=config.base_url,
        temperature=config.temperature,
        timeout=config.timeout,
    )


def _normalize_model_name(model: str, provider: str) -> str:
    """CrewAI expects Ollama model names without a duplicate provider prefix."""
    if provider == "ollama" and model.startswith("ollama/"):
        return model.removeprefix("ollama/")
    return model


def create_sales_processing_crewai_agent(llm: Any = None, verbose: bool = False):
    """wraps sales extraction instructions in a CrewAI agent when enabled."""
    _configure_crewai_storage()
    agent_class = _crewai_symbol("Agent")
    definition = get_agent_definition("sales_processing")

    return agent_class(
        role=definition.role,
        goal=definition.goal,
        backstory=definition.backstory,
        llm=llm,
        verbose=verbose,
        allow_delegation=definition.allow_delegation,
        max_iter=definition.max_iter,
        tools=_crewai_tools_for_agent(definition.tools),
    )


def create_supervisor_crewai_agent(llm: Any = None, verbose: bool = False):
    """adds an independent review role before drafts reach humans."""
    _configure_crewai_storage()
    agent_class = _crewai_symbol("Agent")
    definition = get_agent_definition("supervisor")

    return agent_class(
        role=definition.role,
        goal=definition.goal,
        backstory=definition.backstory,
        llm=llm,
        verbose=verbose,
        allow_delegation=definition.allow_delegation,
        max_iter=definition.max_iter,
        tools=_crewai_tools_for_agent(definition.tools),
    )


def create_email_drafting_crewai_agent(llm: Any = None, verbose: bool = False):
    """isolates customer-facing copy generation from extraction/supervision."""
    _configure_crewai_storage()
    agent_class = _crewai_symbol("Agent")
    definition = get_agent_definition("email_drafting")

    return agent_class(
        role=definition.role,
        goal=definition.goal,
        backstory=definition.backstory,
        llm=llm,
        verbose=verbose,
        allow_delegation=definition.allow_delegation,
        max_iter=definition.max_iter,
        tools=_crewai_tools_for_agent(definition.tools),
    )


def _crewai_tools_for_agent(tool_names: list[str]) -> list[Any]:
    """builds CrewAI BaseTool instances declared in agent YAML."""
    if not tool_names:
        return []
    from app.crews.tools import build_crewai_tools

    return build_crewai_tools(tool_names)


def _crewai_symbol(symbol_name: str) -> Any:
    """returns a concrete CrewAI symbol or raises a specific optional-import error."""
    if _crewai is not None:
        return getattr(_crewai, symbol_name)
    import_error = _crewai_import_error()
    raise RuntimeError(
        f"CrewAI {symbol_name} import failed: "
        f"{_format_error_note(import_error)}"
    ) from import_error


def _crewai_import_error() -> Exception:
    """returns the captured CrewAI import failure as a concrete exception."""
    if _CREWAI_AGENT_IMPORT_ERROR is not None:
        return _CREWAI_AGENT_IMPORT_ERROR
    return RuntimeError("CrewAI module is unavailable.")


def _configure_crewai_storage() -> None:
    """keeps CrewAI runtime files out of the repository and disables tracing noise."""
    storage_home = Path(
        os.environ.get("SWIFT_CREWAI_HOME", "/tmp/project_swift_crewai_home")
    )
    try:
        storage_home.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        fallback_home = Path("/tmp/project_swift_crewai_home")
        try:
            fallback_home.mkdir(parents=True, exist_ok=True)
        except OSError as fallback_exc:
            raise RuntimeError(
                "CrewAI storage directory could not be created: "
                f"{_format_error_note(fallback_exc)}"
            ) from exc
        storage_home = fallback_home
    os.environ["HOME"] = str(storage_home)
    os.environ.setdefault("CREWAI_STORAGE_DIR", "project_swift")
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    """keeps keyword checks readable at classification call sites."""
    return any(needle in text for needle in needles)


def _is_product_listing_request(lower_text: str) -> bool:
    """detects customer requests to browse or list catalog products."""
    if any(
        phrase in lower_text
        for phrase in (
            "list products",
            "list some products",
            "show products",
            "which products",
            "what products",
            "browse products",
            "products that",
            "products with",
            "products in",
            "available products",
        )
    ):
        return True
    return bool(
        re.search(
            r"\b(?:list|show|browse|recommend|suggest)\b.{0,80}\b(?:products?|items?|catalog)\b",
            lower_text,
        )
    )


def _requested_listing_limit(query: str, *, default: int = 5) -> int:
    """uses explicit list sizes like 'top 3' while keeping responses bounded."""
    lower = query.lower()
    match = re.search(
        r"\b(?:top|first|show|list)\s+(?P<count>\d{1,2})\b|"
        r"\b(?P<count_after>\d{1,2})\s+(?:products?|items?)\b",
        lower,
    )
    if not match:
        return default
    count = int(match.group("count") or match.group("count_after"))
    return max(1, min(count, 10))


def _local_product_suggestions(query: str, *, limit: int) -> list[ProductOption]:
    """ranks the built-in catalog without using unapproved product facts."""
    query_tokens = _simple_product_tokens(query)
    scored: list[tuple[int, str, ProductContext]] = []
    for item in DEFAULT_PRODUCT_CATALOG:
        searchable = " ".join(
            [
                item.product or "",
                item.sku or "",
                " ".join(item.notes),
            ]
        )
        overlap = query_tokens & _simple_product_tokens(searchable)
        score = len(overlap)
        if item.product and item.product.lower() in query.lower():
            score += 5
        if not score and query_tokens:
            continue
        scored.append((score, item.product or "", item))

    scored.sort(key=lambda value: (-value[0], value[1]))
    return [
        _local_product_option(item, confidence=0.62 if score else 0.5)
        for score, _, item in scored[:limit]
        if item.product
    ]


def _local_product_options(*, limit: int) -> list[ProductOption]:
    """returns broad approved local catalog rows for generic list requests."""
    return [
        _local_product_option(item, confidence=0.86)
        for item in DEFAULT_PRODUCT_CATALOG[:limit]
        if item.product
    ]


def _local_product_option(item: ProductContext, *, confidence: float) -> ProductOption:
    return ProductOption(
        product=item.product or "",
        sku=item.sku,
        source_url=item.source_url,
        stock_availability=item.stock_availability,
        price=item.price,
        currency=item.currency,
        unit_of_measure="unit",
        source=item.source,
        confidence=confidence,
    )


def _simple_product_tokens(value: str) -> set[str]:
    stop_words = {
        "and",
        "any",
        "available",
        "availability",
        "browse",
        "can",
        "for",
        "in",
        "list",
        "price",
        "pricing",
        "product",
        "products",
        "quote",
        "show",
        "stock",
        "the",
        "unit",
        "units",
        "what",
        "which",
        "with",
    }
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", value.lower()):
        if len(token) < 2 or token.isdigit() or token in stop_words:
            continue
        tokens.add(token)
        if token.endswith("s") and len(token) > 3:
            tokens.add(token[:-1])
    return tokens


def _env_text(name: str, default: str) -> str:
    """treats blank environment overrides as missing configuration."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    """keeps malformed numeric env vars from crashing app startup."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    """keeps malformed float env vars from crashing app startup."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _env_bool(name: str, default: bool) -> bool:
    """parses common environment booleans without surprising truthiness."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _format_error_note(exc: Exception) -> str:
    """records failure reasons compactly without exposing tracebacks."""
    detail = str(exc).strip() or repr(exc)
    return f"{exc.__class__.__name__}: {' '.join(detail.split())[:160]}"
