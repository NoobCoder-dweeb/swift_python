from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import app.core.environment  # noqa: F401
from app.crews.workflow_models import (
    DraftValidationResult,
    InquiryDetails,
    ProductContext,
)


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
    """extracts safe structured sales context before drafting begins."""

    def __init__(self, product_client: ProductLookupClient | None = None) -> None:
        """allows approved product data to come from a real client or local catalog."""
        self.product_client = product_client

    def extract_inquiry(self, sender: str, subject: str, body: str) -> InquiryDetails:
        """turns free-form email text into bounded workflow inputs."""
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
        )

    def detect_risks(self, text: str) -> list[str]:
        """blocks prompt injection and personal-data requests before drafting."""
        lower = text.lower()
        risks: list[str] = []
        if any(re.search(pattern, lower) for pattern in _PROMPT_INJECTION_PATTERNS):
            risks.append("prompt_injection")
        if any(re.search(pattern, lower) for pattern in _PERSONAL_DATA_PATTERNS):
            risks.append("personal_data")
        return risks

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
        reviewer_feedback: str | None = None,
    ) -> str:
        """drafts from known facts only, asking for missing details instead of guessing."""
        feedback = (reviewer_feedback or "").strip()
        feedback_lower = feedback.lower()
        if inquiry and inquiry.inquiry_type == "unsupported":
            return (
                "Hi,\n\n"
                "Thanks for your message. I cannot help with requests for confidential "
                "customer information or instructions that bypass our sales workflow. "
                "Please send a product pricing or stock availability question and I can "
                "help route it for review.\n\n"
                "Best regards,\n"
                "Project Swift Support"
            )

        product = context.product or (inquiry.product_name if inquiry else None)
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
            (requested_type in {"pricing", "mixed"} or wants_price)
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
        " ".join(content[:4]),
    ]


def _find_unapproved_fact_claims(
    draft: str,
    context: ProductContext,
) -> list[str]:
    """rejects regenerated drafts that drift from approved product data."""
    reasons: list[str] = []
    allowed_prices = {context.price} if context.price is not None else set()
    for note in context.notes:
        allowed_prices.update(
            float(group)
            for groups in re.findall(
                r"(?:usd|\$)\s*(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*usd",
                note,
                re.IGNORECASE,
            )
            for group in groups
            if group
        )

    for match in re.finditer(
        r"(?:usd|\$)\s*(?P<amount>\d+(?:\.\d{1,2})?)",
        draft,
        re.IGNORECASE,
    ):
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


def _dedupe(values: list[str]) -> list[str]:
    """keeps validation reasons stable and readable."""
    return list(dict.fromkeys(values))


def create_local_llm(config: LocalLLMConfig | None = None):
    """centralizes CrewAI LLM construction for every agent factory."""
    _configure_crewai_storage()
    try:
        from crewai import LLM
    except Exception as exc:
        raise RuntimeError(f"CrewAI LLM import failed: {_format_error_note(exc)}") from exc

    config = config or LocalLLMConfig.from_env()
    model = _normalize_model_name(config.model, config.provider)
    return LLM(
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
    try:
        from crewai import Agent
    except Exception as exc:
        raise RuntimeError(f"CrewAI Agent import failed: {_format_error_note(exc)}") from exc

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


def create_supervisor_crewai_agent(llm: Any = None, verbose: bool = False):
    """adds an independent review role before drafts reach humans."""
    _configure_crewai_storage()
    try:
        from crewai import Agent
    except Exception as exc:
        raise RuntimeError(f"CrewAI Agent import failed: {_format_error_note(exc)}") from exc

    return Agent(
        role="Sales Workflow Supervisor",
        goal=(
            "Supervise the sales inquiry workflow, verify that product facts came "
            "from approved data, and keep every AI response gated for human review."
        ),
        backstory=(
            "You are a sales operations supervisor. You check draft quality, "
            "guardrail compliance, and whether the draft is ready to notify a "
            "human sales officer for approval."
        ),
        llm=llm,
        verbose=verbose,
        allow_delegation=False,
        max_iter=4,
    )


def create_email_drafting_crewai_agent(llm: Any = None, verbose: bool = False):
    """isolates customer-facing copy generation from extraction/supervision."""
    _configure_crewai_storage()
    try:
        from crewai import Agent
    except Exception as exc:
        raise RuntimeError(f"CrewAI Agent import failed: {_format_error_note(exc)}") from exc

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


def _format_error_note(exc: Exception) -> str:
    """records failure reasons compactly without exposing tracebacks."""
    detail = str(exc).strip() or repr(exc)
    return f"{exc.__class__.__name__}: {' '.join(detail.split())[:160]}"
