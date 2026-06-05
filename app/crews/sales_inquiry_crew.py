from __future__ import annotations

import os
import time
from uuid import uuid4

from app.crews.agents import (
    EmailDraftingAgent,
    LocalLLMConfig,
    SalesProcessingAgent,
    create_email_drafting_crewai_agent,
    create_local_llm,
    create_sales_processing_crewai_agent,
)
from app.crews.tasks import create_draft_response_task, create_extract_inquiry_task
from app.crews.workflow_models import (
    DraftValidationResult,
    InquiryDetails,
    ProductContext,
    SalesWorkflowResult,
    WorkflowMode,
)
from app.schemas.email import IncomingEmail
from app.services.email_preprocessor import preprocess_email


def run_sales_inquiry_crew(
    sender: str,
    subject: str,
    body: str,
    *,
    use_crewai: bool | None = None,
    llm_config: LocalLLMConfig | None = None,
    verbose: bool = False,
) -> dict:
    result = run_sales_inquiry_workflow(
        IncomingEmail(sender=sender, subject=subject, body=body),
        use_crewai=use_crewai,
        llm_config=llm_config,
        verbose=verbose,
    )
    return {
        "draft_id": result.draft_id,
        "draft": result.ai_draft,
        "result": result.model_dump(),
    }


def run_sales_inquiry_workflow(
    email: IncomingEmail,
    *,
    use_crewai: bool | None = None,
    llm_config: LocalLLMConfig | None = None,
    verbose: bool = False,
) -> SalesWorkflowResult:
    start = time.perf_counter()
    preprocessed = preprocess_email(email)
    cleaned_email = preprocessed.email
    processor = SalesProcessingAgent()
    drafter = EmailDraftingAgent()

    inquiry = processor.extract_inquiry(
        sender=cleaned_email.sender,
        subject=cleaned_email.subject,
        body=cleaned_email.body,
    )
    product_context = processor.lookup_product_context(
        inquiry.product_name,
        f"{cleaned_email.subject}\n{cleaned_email.body}",
    )

    execution_mode: WorkflowMode = "deterministic"
    chokeholds: list[str] = _detect_static_chokeholds(
        email=email,
        inquiry=inquiry,
        product_context=product_context,
        preprocessed_changed=preprocessed.changed,
    )

    if _should_use_crewai(use_crewai):
        crew_result = _run_crewai_draft(
            inquiry=inquiry,
            product_context=product_context,
            llm_config=llm_config,
            verbose=verbose,
        )
        if crew_result.draft:
            ai_draft = crew_result.draft
            execution_mode = "crewai"
        else:
            ai_draft = drafter.generate_response(inquiry, product_context)
            chokeholds.append(crew_result.error or "crewai_execution_failed")
    else:
        ai_draft = drafter.generate_response(inquiry, product_context)

    validation = drafter.validate_draft(ai_draft, product_context)
    if inquiry.inquiry_type == "unsupported":
        validation = DraftValidationResult(
            valid=False,
            action="reject",
            reasons=[*validation.reasons, *inquiry.risk_flags],
        )

    if not validation.valid and validation.action == "regenerate":
        chokeholds.extend(validation.reasons)

    elapsed_ms = (time.perf_counter() - start) * 1000
    return SalesWorkflowResult(
        draft_id=f"DFT-{uuid4().hex[:8].upper()}",
        sender=cleaned_email.sender,
        subject=cleaned_email.subject,
        customer_inquiry=cleaned_email.body,
        inquiry=inquiry,
        product_context=product_context,
        ai_draft=ai_draft,
        validation=validation,
        status="blocked" if validation.action == "reject" else "pending",
        execution_mode=execution_mode,
        chokeholds=_dedupe(chokeholds),
        elapsed_ms=round(elapsed_ms, 2),
    )


class _CrewDraftResult:
    def __init__(self, draft: str | None = None, error: str | None = None) -> None:
        self.draft = draft
        self.error = error


def _run_crewai_draft(
    *,
    inquiry: InquiryDetails,
    product_context: ProductContext,
    llm_config: LocalLLMConfig | None,
    verbose: bool,
) -> _CrewDraftResult:
    try:
        llm = create_local_llm(llm_config)
        sales_agent = create_sales_processing_crewai_agent(llm=llm, verbose=verbose)
        drafting_agent = create_email_drafting_crewai_agent(llm=llm, verbose=verbose)

        # Keep the extraction task in the CrewAI graph for observability, while
        # deterministic extraction remains the validated source of truth.
        extract_task = create_extract_inquiry_task(
            sales_agent,
            sender=inquiry.sender,
            subject=inquiry.subject,
            body=inquiry.body,
        )
        draft_task = create_draft_response_task(
            drafting_agent,
            inquiry=inquiry,
            product_context=product_context,
        )

        from crewai import Crew, Process

        crew = Crew(
            agents=[sales_agent, drafting_agent],
            tasks=[extract_task, draft_task],
            process=Process.sequential,
            verbose=verbose,
            memory=False,
            cache=False,
        )
        result = crew.kickoff()
        draft = str(result).strip()
        if not draft:
            return _CrewDraftResult(error="crewai_returned_empty_draft")
        return _CrewDraftResult(draft=draft)
    except Exception as exc:
        return _CrewDraftResult(error=f"crewai_error:{exc.__class__.__name__}")


def _should_use_crewai(use_crewai: bool | None) -> bool:
    if use_crewai is not None:
        return use_crewai
    return os.environ.get("SWIFT_CREWAI_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _detect_static_chokeholds(
    *,
    email: IncomingEmail,
    inquiry: InquiryDetails,
    product_context: ProductContext,
    preprocessed_changed: bool,
) -> list[str]:
    chokeholds: list[str] = []
    if len(email.body) > 6000:
        chokeholds.append("long_thread_context_pressure")
    if preprocessed_changed and len(inquiry.body) < 20:
        chokeholds.append("preprocessor_may_have_removed_too_much")
    if inquiry.inquiry_type == "unknown":
        chokeholds.append("inquiry_classification_uncertain")
    if inquiry.product_name is None:
        chokeholds.append("product_entity_missing_or_ambiguous")
    if inquiry.missing_information:
        chokeholds.extend(f"missing_{item}" for item in inquiry.missing_information)
    if product_context.confidence < 0.5:
        chokeholds.append("approved_product_context_not_found")
    if inquiry.risk_flags:
        chokeholds.extend(inquiry.risk_flags)
    if _looks_multilingual(email.body):
        chokeholds.append("multilingual_or_code_switching_input")
    return chokeholds


def _looks_multilingual(text: str) -> bool:
    lower = text.lower()
    return any(
        token in lower
        for token in (
            "boleh",
            "harga",
            "stok",
            "ada stock",
            "berapa",
            "有没有",
            "价格",
        )
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result
