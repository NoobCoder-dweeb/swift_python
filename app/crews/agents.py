from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.crews.workflow_models import (
    DraftValidationResult,
    InquiryDetails,
    ProductContext,
)


class ProductLookupClient(Protocol):
    def get_product(self, query: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class LocalLLMConfig:
    model: str = "ollama/llama3.2:3b"
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    timeout: int = 45
    temperature: float = 0.1

    @classmethod
    def from_env(cls) -> "LocalLLMConfig":
        return cls(
            model=os.environ.get("SWIFT_LOCAL_LLM_MODEL", cls.model),
            provider=os.environ.get("SWIFT_LOCAL_LLM_PROVIDER", cls.provider),
            base_url=os.environ.get("SWIFT_LOCAL_LLM_BASE_URL", cls.base_url),
            timeout=int(os.environ.get("SWIFT_LOCAL_LLM_TIMEOUT", str(cls.timeout))),
            temperature=float(
                os.environ.get("SWIFT_LOCAL_LLM_TEMPERATURE", str(cls.temperature))
            ),
        )


DEFAULT_PRODUCT_CATALOG: list[ProductContext] = [
    ProductContext(
        product="Safety Helmet",
        sku="SAFE-HELMET-001",
        stock_availability=120,
        price=25.0,
        currency="USD",
        lead_time_days=7,
        confidence=0.95,
        notes=["Aliases: helmet, hard hat, safety helmet"],
    ),
    ProductContext(
        product="Product X",
        sku="PROD-X-001",
        stock_availability=500,
        price=120.0,
        currency="USD",
        lead_time_days=10,
        confidence=0.9,
        notes=["Bulk orders of 100 or more units may qualify for 95.00 USD pricing."],
    ),
    ProductContext(
        product="Safety Gloves",
        sku="SAFE-GLOVE-001",
        stock_availability=900,
        price=8.5,
        currency="USD",
        lead_time_days=5,
        confidence=0.88,
        notes=["Aliases: gloves, safety gloves"],
    ),
]

_PRODUCT_ALIASES: dict[str, tuple[str, ...]] = {
    "Safety Helmet": ("safety helmet", "helmets", "helmet", "hard hat", "hard hats"),
    "Product X": ("product x", "prod x", "product-x"),
    "Safety Gloves": ("safety gloves", "gloves", "glove"),
}

_PROMPT_INJECTION_PATTERNS = (
    r"ignore (all )?(previous|prior|above) instructions",
    r"reveal .*?(system prompt|developer message|confidential|customer data)",
    r"show .*?(another customer|customer list|private data)",
    r"bypass .*?(policy|guardrail|approval)",
    r"act as .*?system",
)

_PERSONAL_DATA_PATTERNS = (
    r"phone number",
    r"billing address",
    r"account contact",
    r"customer list",
    r"personal information",
)

_QUANTITY_RE = re.compile(
    r"\b(?P<quantity>\d{1,6})(?:[,.]\d+)?\s*(?:units?|pcs?|pieces?|boxes?|cartons?|pairs?|sets?)?\b",
    re.IGNORECASE,
)


class SalesProcessingAgent:
    def __init__(self, product_client: ProductLookupClient | None = None) -> None:
        self.product_client = product_client

    def extract_inquiry(self, sender: str, subject: str, body: str) -> InquiryDetails:
        text = f"{subject}\n{body}".strip()
        lower = text.lower()
        risk_flags = self.detect_risks(text)

        pricing = _contains_any(lower, ("price", "pricing", "quote", "cost", "rate"))
        availability = _contains_any(
            lower,
            ("stock", "availability", "available", "inventory", "in stock"),
        )

        if any(flag in risk_flags for flag in ("prompt_injection", "personal_data")):
            inquiry_type = "unsupported"
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
        if self.product_client:
            return self.product_client.get_product(query)

        product_name = self._detect_product(query.lower())
        context = self.lookup_product_context(product_name, query)
        return context.model_dump()

    def lookup_product_context(
        self, product_name: str | None, query: str = ""
    ) -> ProductContext:
        if self.product_client:
            return ProductContext.model_validate(self.product_client.get_product(query))

        target = product_name or self._detect_product(query.lower())
        for item in DEFAULT_PRODUCT_CATALOG:
            if item.product == target:
                return item

        return ProductContext(
            product=target,
            source="local_catalog",
            confidence=0.0,
            notes=["No approved product record matched the inquiry."],
        )

    def detect_risks(self, text: str) -> list[str]:
        lower = text.lower()
        risks: list[str] = []
        if any(re.search(pattern, lower) for pattern in _PROMPT_INJECTION_PATTERNS):
            risks.append("prompt_injection")
        if any(re.search(pattern, lower) for pattern in _PERSONAL_DATA_PATTERNS):
            risks.append("personal_data")
        return risks

    def _detect_product(self, lower_text: str) -> str | None:
        for product, aliases in _PRODUCT_ALIASES.items():
            if any(alias in lower_text for alias in aliases):
                return product
        return None

    def _detect_quantity(self, lower_text: str) -> int | None:
        matches = [
            int(match.group("quantity").replace(",", ""))
            for match in _QUANTITY_RE.finditer(lower_text)
            if int(match.group("quantity").replace(",", "")) > 0
        ]
        if not matches:
            return None
        return max(matches)

    def _detect_delivery(self, text: str) -> str | None:
        lowered = text.lower()
        for phrase in (
            "next week",
            "this week",
            "urgent",
            "immediate",
            "asap",
            "june shipment",
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
    def generate(self, info: dict[str, Any] | ProductContext | InquiryDetails) -> str:
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
                    "currency": info.get("currency", "USD"),
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
    ) -> str:
        if inquiry and inquiry.inquiry_type == "unsupported":
            return (
                "Hi,\n\n"
                "Thanks for your message. I cannot help with requests for confidential "
                "customer information or instructions that bypass our sales workflow. "
                "Please send a product pricing or stock availability question and I can "
                "help route it for review.\n\n"
                "Best regards,\n"
                "Swift Support"
            )

        product = context.product or (inquiry.product_name if inquiry else None)
        if not product:
            return (
                "Hi,\n\n"
                "Thanks for your inquiry. Could you please confirm the product name, "
                "quantity required, and target delivery timing so we can check pricing "
                "and stock availability accurately?\n\n"
                "Best regards,\n"
                "Swift Support"
            )

        lines = [
            "Hi,",
            "",
            f"Thanks for your inquiry about {product}.",
        ]

        requested_type = inquiry.inquiry_type if inquiry else "mixed"
        if requested_type in {"pricing", "mixed"} and context.price is not None:
            lines.append(
                f"The approved reference price is {context.currency} "
                f"{context.price:.2f} per unit."
            )
        if (
            requested_type in {"availability", "mixed"}
            and context.stock_availability is not None
        ):
            lines.append(
                f"Current available stock is {context.stock_availability} units."
            )
        if context.lead_time_days is not None:
            lines.append(
                f"Typical lead time is {context.lead_time_days} business days "
                "after order confirmation."
            )

        if inquiry:
            if inquiry.quantity and context.stock_availability is not None:
                if inquiry.quantity <= context.stock_availability:
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

        lines.extend(["", "Best regards,", "Swift Support"])
        return "\n".join(lines)

    def validate_draft(
        self, draft: str, info: dict[str, Any] | ProductContext | None = None
    ) -> DraftValidationResult:
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

        if info:
            product = (
                info.product
                if isinstance(info, ProductContext)
                else str(info.get("product") or "")
            )
            if product and product.lower() not in lower:
                reasons.append("missing_product_reference")

        if reasons:
            return DraftValidationResult(
                valid=False,
                action="regenerate",
                reasons=reasons,
            )

        return DraftValidationResult(valid=True, action="approve", reasons=[])


def create_local_llm(config: LocalLLMConfig | None = None):
    _configure_crewai_storage()
    from crewai import LLM

    config = config or LocalLLMConfig.from_env()
    return LLM(
        model=config.model,
        provider=config.provider,
        base_url=config.base_url,
        temperature=config.temperature,
        timeout=config.timeout,
    )


def create_sales_processing_crewai_agent(llm: Any = None, verbose: bool = False):
    _configure_crewai_storage()
    from crewai import Agent

    return Agent(
        role="Sales Processing Agent",
        goal=(
            "Extract product inquiry details, detect unsupported requests, and "
            "prepare structured sales context without inventing product facts."
        ),
        backstory=(
            "You are a careful sales operations analyst. You only use approved "
            "catalog or ERP context and you flag missing information clearly."
        ),
        llm=llm,
        verbose=verbose,
        allow_delegation=False,
        max_iter=5,
    )


def create_email_drafting_crewai_agent(llm: Any = None, verbose: bool = False):
    _configure_crewai_storage()
    from crewai import Agent

    return Agent(
        role="Email Drafting Agent",
        goal=(
            "Draft concise customer replies using only extracted inquiry details "
            "and approved product context."
        ),
        backstory=(
            "You write sales replies for human review. You do not disclose "
            "confidential data and you ask for missing details instead of guessing."
        ),
        llm=llm,
        verbose=verbose,
        allow_delegation=False,
        max_iter=5,
    )


def _configure_crewai_storage() -> None:
    storage_home = Path(
        os.environ.get("SWIFT_CREWAI_HOME", "/private/tmp/project_swift_crewai_home")
    )
    storage_home.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(storage_home)
    os.environ.setdefault("CREWAI_STORAGE_DIR", "project_swift")
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
