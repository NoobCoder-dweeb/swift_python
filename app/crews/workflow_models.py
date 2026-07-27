from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


InquiryType = Literal[
    "pricing",
    "availability",
    "mixed",
    "listing",
    "unsupported",
    "unknown",
]
WorkflowMode = Literal["deterministic", "crewai", "external"]


class InquiryDetails(BaseModel):
    """separates extracted customer intent from raw email text."""

    sender: str
    subject: str
    body: str
    inquiry_type: InquiryType = "unknown"
    product_name: str | None = None
    quantity: int | None = None
    requested_delivery: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class ProductOption(BaseModel):
    """represents a persisted catalogue row safe to mention in a draft."""

    product: str
    sku: str | None = None
    source_url: str | None = None
    category: str | None = None
    description: str | None = None
    stock_availability: int | None = None
    price: float | None = None
    currency: str = "RM"
    unit_of_measure: str | None = None
    source: str = "catalogue"
    confidence: float = 0.0


class ProductContext(BaseModel):
    """constrains draft generation to approved product data."""

    product: str | None = None
    sku: str | None = None
    source_url: str | None = None
    stock_availability: int | None = None
    price: float | None = None
    currency: str = "RM"
    lead_time_days: int | None = None
    source: str = "local_catalog"
    confidence: float = 0.0
    notes: list[str] = Field(default_factory=list)
    suggested_products: list[ProductOption] = Field(default_factory=list)
    listed_products: list[ProductOption] = Field(default_factory=list)


class DraftValidationResult(BaseModel):
    """makes approval/regeneration/rejection decisions explicit."""

    valid: bool
    action: Literal["approve", "regenerate", "reject"]
    reasons: list[str] = Field(default_factory=list)


class SalesWorkflowResult(BaseModel):
    """carries every workflow artifact needed for review and audit."""

    draft_id: str
    sender: str
    subject: str
    customer_inquiry: str
    inquiry: InquiryDetails
    product_context: ProductContext
    ai_draft: str
    validation: DraftValidationResult
    status: Literal["pending", "blocked"] = "pending"
    reviewer_feedback: str | None = None
    previous_ai_draft: str | None = None
    execution_mode: WorkflowMode = "deterministic"
    agent_models: dict[str, str] = Field(default_factory=dict)
    supervisor_review: DraftValidationResult | None = None
    learning_notes: list[str] = Field(default_factory=list)
    chokeholds: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0.0
    token_usage: dict[str, Any] = Field(default_factory=dict)


class StressScenario(BaseModel):
    """defines edge cases that probe workflow safety and coverage."""

    name: str
    sender: str = "stress.customer@example.com"
    subject: str
    body: str
    expected_type: InquiryType | None = None
    expected_status: Literal["pending", "blocked"] | None = None
    expected_quantity: int | None = None
    required_terms: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    required_chokeholds: list[str] = Field(default_factory=list)
    forbidden_chokeholds: list[str] = Field(default_factory=list)
    required_validation_reasons: list[str] = Field(default_factory=list)
    expect_valid: bool | None = None


class StressCaseResult(BaseModel):
    """records per-scenario outcomes for debugging regressions."""

    name: str
    passed: bool
    elapsed_ms: float
    issues: list[str] = Field(default_factory=list)
    chokeholds: list[str] = Field(default_factory=list)
    workflow: SalesWorkflowResult


class StressSuiteResult(BaseModel):
    """summarizes stress coverage across all scenarios."""

    mode: WorkflowMode
    total: int
    passed: int
    failed: int
    elapsed_ms: float
    case_results: list[StressCaseResult]
    chokeholds: list[str] = Field(default_factory=list)
