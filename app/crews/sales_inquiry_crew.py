from __future__ import annotations

import time
from uuid import uuid4

from app.crews.agents import (
    EmailDraftingAgent,
    LocalLLMConfig,
    MultiAgentLLMConfig,
    SalesProcessingAgent,
    create_email_drafting_crewai_agent,
    create_local_llm,
    create_sales_processing_crewai_agent,
    create_supervisor_crewai_agent,
)
from app.crews.tasks import (
    create_draft_response_task,
    create_extract_inquiry_task,
    create_validation_task,
)
from app.crews.workflow_models import (
    DraftValidationResult,
    InquiryDetails,
    ProductContext,
    SalesWorkflowResult,
    WorkflowMode,
)
from app.core.config import get_app_settings
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
    """preserves the original dict API while using the structured workflow."""
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
    crew_llm_config: MultiAgentLLMConfig | None = None,
    reviewer_feedback: str | None = None,
    previous_draft: str | None = None,
    draft_id: str | None = None,
    verbose: bool = False,
) -> SalesWorkflowResult:
    """orchestrates preprocessing, extraction, drafting, validation, and audit data."""
    start = time.perf_counter()
    reviewer_feedback = (reviewer_feedback or "").strip() or None
    previous_draft = (previous_draft or "").strip() or None
    preprocessed = preprocess_email(email)
    cleaned_email = preprocessed.email
    processor = SalesProcessingAgent()
    drafter = EmailDraftingAgent()
    agent_models: dict[str, str] = {}
    supervisor_review: DraftValidationResult | None = None

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
    agent_backend = _resolve_agent_backend(use_crewai)
    chokeholds: list[str] = _detect_static_chokeholds(
        email=email,
        inquiry=inquiry,
        product_context=product_context,
        preprocessed_changed=preprocessed.changed,
    )

    if agent_backend == "external":
        external_result = _run_external_agent_draft(
            email=cleaned_email,
            inquiry=inquiry,
            product_context=product_context,
            reviewer_feedback=reviewer_feedback,
            previous_draft=previous_draft,
            draft_id=draft_id,
        )
        if external_result.draft:
            ai_draft = external_result.draft
            execution_mode = "external"
            agent_models = external_result.agent_models
            supervisor_review = external_result.supervisor_review
        else:
            ai_draft = drafter.generate_response(
                inquiry,
                product_context,
                reviewer_feedback=reviewer_feedback,
            )
            chokeholds.append(external_result.error or "external_agent_failed")
    elif agent_backend == "crewai":
        crew_result = _run_crewai_draft(
            inquiry=inquiry,
            product_context=product_context,
            reviewer_feedback=reviewer_feedback,
            previous_draft=previous_draft,
            llm_config=llm_config,
            crew_llm_config=crew_llm_config,
            verbose=verbose,
        )
        if crew_result.draft:
            ai_draft = crew_result.draft
            execution_mode = "crewai"
            agent_models = crew_result.agent_models
            supervisor_review = crew_result.supervisor_review
        else:
            ai_draft = drafter.generate_response(
                inquiry,
                product_context,
                reviewer_feedback=reviewer_feedback,
            )
            chokeholds.append(crew_result.error or "crewai_execution_failed")
    else:
        ai_draft = drafter.generate_response(
            inquiry,
            product_context,
            reviewer_feedback=reviewer_feedback,
        )

    validation = drafter.validate_draft(ai_draft, product_context)
    if inquiry.inquiry_type == "unsupported":
        validation = DraftValidationResult(
            valid=False,
            action="reject",
            reasons=[*validation.reasons, *inquiry.risk_flags],
        )
    elif inquiry.inquiry_type == "unknown":
        validation = DraftValidationResult(
            valid=False,
            action="reject",
            reasons=[*validation.reasons, "unsupported_inquiry_type"],
        )

    if supervisor_review and not supervisor_review.valid:
        chokeholds.extend(f"supervisor_{reason}" for reason in supervisor_review.reasons)
        if supervisor_review.action == "reject":
            validation = DraftValidationResult(
                valid=False,
                action="reject",
                reasons=[*validation.reasons, *supervisor_review.reasons],
            )
        elif validation.valid:
            validation = DraftValidationResult(
                valid=False,
                action="regenerate",
                reasons=supervisor_review.reasons,
            )

    if not validation.valid and validation.action == "regenerate":
        chokeholds.extend(validation.reasons)
        ai_draft = drafter.generate_response(
            inquiry,
            product_context,
            reviewer_feedback=reviewer_feedback,
        )
        validation = drafter.validate_draft(ai_draft, product_context)
        if not validation.valid:
            chokeholds.extend(validation.reasons)

    elapsed_ms = (time.perf_counter() - start) * 1000
    return SalesWorkflowResult(
        draft_id=draft_id or f"DFT-{uuid4().hex[:8].upper()}",
        sender=cleaned_email.sender,
        subject=cleaned_email.subject,
        customer_inquiry=cleaned_email.body,
        inquiry=inquiry,
        product_context=product_context,
        ai_draft=ai_draft,
        validation=validation,
        status="blocked" if validation.action == "reject" else "pending",
        reviewer_feedback=reviewer_feedback,
        previous_ai_draft=previous_draft,
        execution_mode=execution_mode,
        agent_models=agent_models,
        supervisor_review=supervisor_review,
        learning_notes=_build_learning_notes(reviewer_feedback, validation),
        chokeholds=_dedupe(chokeholds),
        elapsed_ms=round(elapsed_ms, 2),
    )


class _CrewDraftResult:
    """carries optional CrewAI output without throwing away fallback context."""

    def __init__(
        self,
        draft: str | None = None,
        error: str | None = None,
        agent_models: dict[str, str] | None = None,
        supervisor_review: DraftValidationResult | None = None,
    ) -> None:
        """stores both success and failure details for workflow reporting."""
        self.draft = draft
        self.error = error
        self.agent_models = agent_models or {}
        self.supervisor_review = supervisor_review


def _run_crewai_draft(
    *,
    inquiry: InquiryDetails,
    product_context: ProductContext,
    reviewer_feedback: str | None,
    previous_draft: str | None,
    llm_config: LocalLLMConfig | None,
    crew_llm_config: MultiAgentLLMConfig | None,
    verbose: bool,
) -> _CrewDraftResult:
    """tries the multi-agent path while keeping deterministic fallback possible."""
    try:
        multi_config = crew_llm_config or MultiAgentLLMConfig.from_env(
            sales_override=llm_config
        )
        multi_config.validate_unique_models()
        agent_models = multi_config.model_names()

        supervisor_llm = create_local_llm(multi_config.supervisor)
        sales_llm = create_local_llm(multi_config.sales)
        drafting_llm = create_local_llm(multi_config.drafting)
        supervisor_agent = create_supervisor_crewai_agent(
            llm=supervisor_llm, verbose=verbose
        )
        sales_agent = create_sales_processing_crewai_agent(
            llm=sales_llm, verbose=verbose
        )
        drafting_agent = create_email_drafting_crewai_agent(
            llm=drafting_llm, verbose=verbose
        )

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
            reviewer_feedback=reviewer_feedback,
            previous_draft=previous_draft,
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
            return _CrewDraftResult(
                error="crewai_returned_empty_draft", agent_models=agent_models
            )

        supervisor_review = None
        try:
            validation_task = create_validation_task(
                supervisor_agent,
                inquiry=inquiry,
                product_context=product_context,
                draft=draft,
                reviewer_feedback=reviewer_feedback,
                previous_draft=previous_draft,
            )
            supervisor_crew = Crew(
                agents=[supervisor_agent],
                tasks=[validation_task],
                process=Process.sequential,
                verbose=verbose,
                memory=False,
                cache=False,
            )
            supervisor_crew.kickoff()
            pydantic_output = getattr(validation_task.output, "pydantic", None)
            if isinstance(pydantic_output, DraftValidationResult):
                supervisor_review = pydantic_output
        except Exception:
            supervisor_review = None

        return _CrewDraftResult(
            draft=draft,
            agent_models=agent_models,
            supervisor_review=supervisor_review,
        )
    except Exception as exc:
        return _CrewDraftResult(error=_format_crewai_error(exc))


def _run_external_agent_draft(
    *,
    email: IncomingEmail,
    inquiry: InquiryDetails,
    product_context: ProductContext,
    reviewer_feedback: str | None,
    previous_draft: str | None,
    draft_id: str | None,
) -> _CrewDraftResult:
    """calls a vendor-hosted agent while keeping local validation authoritative."""
    settings = get_app_settings()
    if not settings.external_agent_url:
        return _CrewDraftResult(error="external_agent_url_not_configured")

    payload = {
        "draft_id": draft_id,
        "email": email.model_dump(),
        "inquiry": inquiry.model_dump(),
        "product_context": product_context.model_dump(),
        "reviewer_feedback": reviewer_feedback,
        "previous_draft": previous_draft,
        "constraints": {
            "use_only_product_context": True,
            "requires_human_review": True,
            "forbidden": [
                "invented prices",
                "invented stock",
                "invented lead times",
                "customer personal data",
                "subject line in response body",
            ],
        },
    }
    headers = {"Accept": "application/json"}
    if settings.external_agent_api_key:
        headers["Authorization"] = f"Bearer {settings.external_agent_api_key}"

    try:
        import httpx

        response = httpx.post(
            settings.external_agent_url,
            json=payload,
            headers=headers,
            timeout=settings.external_agent_timeout,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return _CrewDraftResult(error=f"external_agent_error:{exc.__class__.__name__}")

    if not isinstance(data, dict):
        return _CrewDraftResult(error="external_agent_returned_non_object")

    draft = str(
        data.get("ai_draft")
        or data.get("draft")
        or data.get("response")
        or ""
    ).strip()
    if not draft:
        return _CrewDraftResult(error="external_agent_returned_empty_draft")

    supervisor_review = None
    validation_payload = data.get("supervisor_review") or data.get("validation")
    if isinstance(validation_payload, dict):
        try:
            supervisor_review = DraftValidationResult.model_validate(validation_payload)
        except Exception:
            supervisor_review = None

    return _CrewDraftResult(
        draft=draft,
        agent_models={
            "external": settings.external_agent_url,
            "provider": str(data.get("provider") or "external"),
        },
        supervisor_review=supervisor_review,
    )


def _resolve_agent_backend(use_crewai: bool | None) -> str:
    """keeps legacy CrewAI override while supporting external agent providers."""
    if use_crewai is not None:
        return "crewai" if use_crewai else "deterministic"
    backend = get_app_settings().resolved_agent_backend
    if backend in {"deterministic", "crewai", "external"}:
        return backend
    return "deterministic"


def _format_crewai_error(exc: Exception) -> str:
    """records CrewAI failures compactly without leaking huge tracebacks."""
    detail = str(exc).strip() or repr(exc)
    detail = " ".join(detail.split())
    return f"crewai_error:{exc.__class__.__name__}:{detail[:240]}"


def _build_learning_notes(
    reviewer_feedback: str | None,
    validation: DraftValidationResult,
) -> list[str]:
    """makes reviewer corrections available to audits and future operators."""
    notes: list[str] = []
    if reviewer_feedback:
        notes.append(
            "Reviewer feedback applied to regenerated draft as workflow guidance."
        )
        notes.append(
            "Feedback was not treated as product truth; approved product context "
            "remained the factual source."
        )
    if validation.reasons:
        notes.extend(f"Supervisor/validator noted: {reason}" for reason in validation.reasons)
    return _dedupe(notes)


def _detect_static_chokeholds(
    *,
    email: IncomingEmail,
    inquiry: InquiryDetails,
    product_context: ProductContext,
    preprocessed_changed: bool,
) -> list[str]:
    """surfaces known workflow weak spots before they become silent failures."""
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
    """flags code-switching inputs that deterministic English rules may miss."""
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
    """keeps repeated chokehold signals readable in reports."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result
