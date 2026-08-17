from __future__ import annotations

from importlib import import_module
import os
import re
import time
import math
from typing import Any
from urllib.parse import quote_plus, urlparse
from uuid import uuid4

import httpx

from app.services.draft_content import normalize_email_draft
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
from app.repositories.product_repository import build_product_lookup_client
from app.schemas.email import IncomingEmail
from app.services.email_preprocessor import PreprocessedEmail, preprocess_email

try:
    _crewai = import_module("crewai")
except Exception as exc:  # pragma: no cover - depends on optional runtime install
    _crewai = None
    _CREWAI_WORKFLOW_IMPORT_ERROR = exc
else:
    _CREWAI_WORKFLOW_IMPORT_ERROR = None


class AgentBackendError(RuntimeError):
    """prevents an AI-configured run from being mislabeled deterministic."""


def run_sales_inquiry_crew(
    sender: str,
    subject: str,
    body: str,
    *,
    use_crewai: bool | None = None,
    llm_config: LocalLLMConfig | None = None,
    verbose: bool = False,
) -> dict:
    """
    Backward-compatible AI workflow entrypoint for raw email fields.

    This function is the simple callable surface for code that has sender,
    subject, and body strings rather than a validated IncomingEmail model. It
    delegates to the structured sales workflow, then returns the legacy dict
    shape expected by older API callers and tests.
    """
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
    """
    Run the complete AI-assisted sales inquiry workflow.

    The workflow preprocesses the email, extracts bounded inquiry details,
    looks up approved product facts, optionally asks an AI backend for a draft,
    validates the result, and returns audit-ready metadata. Local validation
    remains authoritative even when CrewAI or an external agent drafts the
    customer response.
    """
    start = time.perf_counter()
    reviewer_feedback = (reviewer_feedback or "").strip() or None
    previous_draft = (previous_draft or "").strip() or None
    # Rejection regeneration supplies an internal wrapper that already contains
    # a cleaned current reply plus trusted thread context. Running the ordinary
    # email relevance selector over that wrapper can discard the current reply
    # and retain only the previous rejected draft.
    has_internal_thread_context = "Current customer reply to answer now:" in email.body
    if has_internal_thread_context:
        preprocessed = PreprocessedEmail(
            email=email,
            original_body=email.body,
            removed_lines=[],
        )
    else:
        preprocessed = preprocess_email(email)
    cleaned_email = preprocessed.email
    processor = SalesProcessingAgent(product_client=build_product_lookup_client())
    drafter = EmailDraftingAgent()
    agent_models: dict[str, str] = {}
    supervisor_review: DraftValidationResult | None = None
    token_usage: dict[str, Any] = {}

    inquiry = processor.extract_inquiry(
        sender=cleaned_email.sender,
        subject=cleaned_email.subject,
        body=cleaned_email.body,
    )
    current_reply = _current_reply_segment(cleaned_email.body)
    product_query = f"{cleaned_email.subject}\n{current_reply}"
    product_history_query = (
        f"{cleaned_email.subject}\n{cleaned_email.body}"
        if current_reply != cleaned_email.body
        else None
    )
    product_context = _lookup_product_context_for_inquiry(
        processor,
        inquiry,
        product_query,
        fallback_query=product_history_query,
    )
    inquiry = _promote_product_only_inquiry(processor, inquiry, product_context)
    if (
        product_context.confidence >= 0.5
        and product_context.product
        and inquiry.product_name != product_context.product
    ):
        inquiry = inquiry.model_copy(
            update={
                "product_name": product_context.product,
                "missing_information": [
                    item
                    for item in inquiry.missing_information
                    if item != "product_name"
                ],
            }
        )
    if current_reply != cleaned_email.body:
        current_inquiry_type = _current_reply_inquiry_type(current_reply)
        current_quantity = processor._detect_quantity(current_reply.lower())
        current_delivery = processor._detect_delivery(current_reply)
        if current_inquiry_type or current_quantity or current_delivery:
            inquiry_type = current_inquiry_type or inquiry.inquiry_type
            quantity = (
                current_quantity
                if current_inquiry_type or current_quantity is not None
                else inquiry.quantity
            )
            requested_delivery = (
                current_delivery
                if current_inquiry_type or current_delivery is not None
                else inquiry.requested_delivery
            )
            inquiry = inquiry.model_copy(
                update={
                    "inquiry_type": inquiry_type,
                    "quantity": quantity,
                    "requested_delivery": requested_delivery,
                    "missing_information": processor._missing_information(
                        inquiry_type=inquiry_type,
                        product_name=inquiry.product_name,
                        quantity=quantity,
                        requested_delivery=requested_delivery,
                    ),
                }
            )

    feedback_inquiry_type = _current_reply_inquiry_type(reviewer_feedback or "")
    feedback_quantity = _feedback_quantity_override(reviewer_feedback or "")
    feedback_delivery = _feedback_delivery_override(reviewer_feedback or "")
    if (
        feedback_inquiry_type == "availability"
        and inquiry.inquiry_type in {"pricing", "mixed"}
        and feedback_delivery
    ):
        # Delivery feedback supplements a quotation; it must not demote the
        # customer's original commercial request to an availability inquiry.
        feedback_inquiry_type = None
    if feedback_inquiry_type or feedback_quantity or feedback_delivery:
        inquiry_type = feedback_inquiry_type or inquiry.inquiry_type
        quantity = feedback_quantity or inquiry.quantity
        requested_delivery = feedback_delivery or inquiry.requested_delivery
        inquiry = inquiry.model_copy(
            update={
                "inquiry_type": inquiry_type,
                "quantity": quantity,
                "requested_delivery": requested_delivery,
                "missing_information": processor._missing_information(
                    inquiry_type=inquiry_type,
                    product_name=inquiry.product_name,
                    quantity=quantity,
                    requested_delivery=requested_delivery,
                ),
            }
        )

    product_context = _lookup_product_context_for_inquiry(
        processor,
        inquiry,
        product_query,
        fallback_query=product_history_query,
    )
    inquiry = _promote_product_only_inquiry(processor, inquiry, product_context)
    if (
        product_context.confidence >= 0.5
        and product_context.product
        and inquiry.product_name != product_context.product
    ):
        inquiry = inquiry.model_copy(
            update={
                "product_name": product_context.product,
                "missing_information": [
                    item
                    for item in inquiry.missing_information
                    if item != "product_name"
                ],
            }
        )

    execution_mode: WorkflowMode = "deterministic"
    agent_backend = _resolve_agent_backend(use_crewai)
    chokeholds: list[str] = _detect_static_chokeholds(
        email=email,
        inquiry=inquiry,
        product_context=product_context,
        preprocessed_changed=preprocessed.changed,
    )

    canonical_quote_inquiry = _canonical_quote_inquiry(
        processor,
        inquiry,
        product_context,
    )
    if canonical_quote_inquiry is not None:
        canonical_quote_context = product_context.model_copy(
            update={"lead_time_days": None}
        )
        ai_draft = drafter.generate_response(
            canonical_quote_inquiry,
            canonical_quote_context,
            reviewer_feedback=reviewer_feedback,
        )
    elif agent_backend == "external":
        external_result = _retry_agent_draft(
            "external",
            lambda: _run_external_agent_draft(
                email=cleaned_email,
                inquiry=inquiry,
                product_context=product_context,
                reviewer_feedback=reviewer_feedback,
                previous_draft=previous_draft,
                draft_id=draft_id,
            ),
        )
        ai_draft = external_result.draft or ""
        execution_mode = "external"
        agent_models = external_result.agent_models
        supervisor_review = external_result.supervisor_review
        token_usage = external_result.token_usage
    elif agent_backend == "crewai":
        crew_result = _retry_agent_draft(
            "crewai",
            lambda: _run_crewai_draft(
                inquiry=inquiry,
                product_context=product_context,
                reviewer_feedback=reviewer_feedback,
                previous_draft=previous_draft,
                llm_config=llm_config,
                crew_llm_config=crew_llm_config,
                verbose=verbose,
            ),
        )
        ai_draft = crew_result.draft or ""
        execution_mode = "crewai"
        agent_models = crew_result.agent_models
        supervisor_review = crew_result.supervisor_review
        token_usage = crew_result.token_usage
    else:
        ai_draft = drafter.generate_response(
            inquiry,
            product_context,
            reviewer_feedback=reviewer_feedback,
        )

    ai_draft = normalize_email_draft(ai_draft)
    validation = drafter.validate_draft(
        ai_draft,
        product_context,
        reviewer_feedback=reviewer_feedback,
    )
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
        chokeholds.extend(
            f"supervisor_{reason}" for reason in supervisor_review.reasons
        )
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
        retry_feedback = _validation_retry_feedback(
            reviewer_feedback,
            validation.reasons,
        )
        if agent_backend == "crewai":
            retry_result = _retry_agent_draft(
                "crewai",
                lambda: _run_crewai_draft(
                    inquiry=inquiry,
                    product_context=product_context,
                    reviewer_feedback=retry_feedback,
                    previous_draft=ai_draft,
                    llm_config=llm_config,
                    crew_llm_config=crew_llm_config,
                    verbose=verbose,
                ),
            )
            ai_draft = retry_result.draft or ""
            token_usage = _merge_token_usage(token_usage, retry_result.token_usage)
        elif agent_backend == "external":
            retry_result = _retry_agent_draft(
                "external",
                lambda: _run_external_agent_draft(
                    email=cleaned_email,
                    inquiry=inquiry,
                    product_context=product_context,
                    reviewer_feedback=retry_feedback,
                    previous_draft=ai_draft,
                    draft_id=draft_id,
                ),
            )
            ai_draft = retry_result.draft or ""
            token_usage = _merge_token_usage(token_usage, retry_result.token_usage)
        else:
            ai_draft = drafter.generate_response(
                inquiry,
                product_context,
                reviewer_feedback=reviewer_feedback,
            )
        ai_draft = normalize_email_draft(ai_draft)
        validation = drafter.validate_draft(
            ai_draft,
            product_context,
            reviewer_feedback=reviewer_feedback,
        )
        if not validation.valid:
            chokeholds.extend(validation.reasons)

    ai_draft = _append_product_references(ai_draft, product_context)
    token_usage = _finalize_token_usage(
        token_usage,
        execution_mode=execution_mode,
        subject=cleaned_email.subject,
        body=cleaned_email.body,
        inquiry=inquiry,
        product_context=product_context,
        ai_draft=ai_draft,
    )

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
        status="blocked" if not validation.valid else "pending",
        reviewer_feedback=reviewer_feedback,
        previous_ai_draft=previous_draft,
        execution_mode=execution_mode,
        agent_models=agent_models,
        supervisor_review=supervisor_review,
        learning_notes=_build_learning_notes(reviewer_feedback, validation),
        chokeholds=_dedupe(chokeholds),
        elapsed_ms=round(elapsed_ms, 2),
        token_usage=token_usage,
    )


class _CrewDraftResult:
    """carries an AI attempt result and retry diagnostics."""

    def __init__(
        self,
        draft: str | None = None,
        error: str | None = None,
        agent_models: dict[str, str] | None = None,
        supervisor_review: DraftValidationResult | None = None,
        token_usage: dict[str, Any] | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        """stores both success and failure details for workflow reporting."""
        self.draft = draft
        self.error = error
        self.agent_models = agent_models or {}
        self.supervisor_review = supervisor_review
        self.token_usage = token_usage or {}
        self.retry_after_seconds = retry_after_seconds


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
    """
    Ask the configured CrewAI agents to produce and review a customer draft.

    The sales and drafting agents receive only validated inquiry data and
    approved product context, while a separate supervisor agent may review the
    output. Failures are returned to the retry controller; AI-configured runs
    never substitute a deterministic draft.
    """
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
            current_customer_reply=_current_reply_segment(inquiry.body),
            conversation_history=_conversation_history_segment(inquiry.body),
        )

        crew_class, process_class = _crewai_workflow_classes()
        crew_agents: list[Any] = [sales_agent, drafting_agent]
        crew_tasks: list[Any] = [extract_task, draft_task]

        crew = crew_class(
            agents=crew_agents,
            tasks=crew_tasks,
            process=process_class.sequential,
            verbose=verbose,
            memory=False,
            cache=False,
        )
        result = crew.kickoff()
        token_usage = _extract_token_usage(result, crew)
        draft = str(result).strip()
        if not draft:
            return _CrewDraftResult(
                error="crewai_returned_empty_draft",
                agent_models=agent_models,
                token_usage=token_usage,
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
                current_customer_reply=_current_reply_segment(inquiry.body),
                conversation_history=_conversation_history_segment(inquiry.body),
            )
            supervisor_agents: list[Any] = [supervisor_agent]
            supervisor_tasks: list[Any] = [validation_task]
            supervisor_crew = crew_class(
                agents=supervisor_agents,
                tasks=supervisor_tasks,
                process=process_class.sequential,
                verbose=verbose,
                memory=False,
                cache=False,
            )
            supervisor_result = supervisor_crew.kickoff()
            token_usage = _merge_token_usage(
                token_usage,
                _extract_token_usage(supervisor_result, supervisor_crew),
            )
            pydantic_output = getattr(validation_task.output, "pydantic", None)
            if isinstance(pydantic_output, DraftValidationResult):
                supervisor_review = pydantic_output
        except Exception:
            supervisor_review = None

        return _CrewDraftResult(
            draft=draft,
            agent_models=agent_models,
            supervisor_review=supervisor_review,
            token_usage=token_usage,
        )
    except Exception as exc:
        return _CrewDraftResult(
            error=_format_crewai_error(exc),
            retry_after_seconds=_provider_retry_after_seconds(exc),
        )


def _retry_agent_draft(backend: str, operation: Any) -> _CrewDraftResult:
    """retries empty/failed AI calls and raises rather than changing modes."""
    attempts = max(1, int(os.getenv("SWIFT_LLM_MAX_ATTEMPTS", "5") or "5"))
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        result = operation()
        if result.draft and result.draft.strip():
            return result
        errors.append(result.error or f"{backend}_returned_empty_draft")
        if attempt < attempts:
            default_delay = min(0.25 * attempt, 1.0)
            provider_delay = result.retry_after_seconds or 0.0
            max_delay = max(
                1.0,
                float(os.getenv("SWIFT_LLM_RETRY_MAX_SECONDS", "65") or "65"),
            )
            time.sleep(min(max(default_delay, provider_delay), max_delay))
    detail = "; ".join(errors[-3:])
    raise AgentBackendError(
        f"{backend} failed to return a draft after {attempts} attempts: {detail}"
    )


def _validation_retry_feedback(
    reviewer_feedback: str | None,
    reasons: list[str],
) -> str:
    """turns local validation failures into explicit LLM retry guidance."""
    guidance = "Correct these validation failures: " + ", ".join(reasons)
    return f"{reviewer_feedback}\n{guidance}".strip() if reviewer_feedback else guidance


def _run_external_agent_draft(
    *,
    email: IncomingEmail,
    inquiry: InquiryDetails,
    product_context: ProductContext,
    reviewer_feedback: str | None,
    previous_draft: str | None,
    draft_id: str | None,
) -> _CrewDraftResult:
    """
    Call a vendor-hosted AI drafting tool with explicit safety constraints.

    The payload gives the external agent the cleaned email, extracted inquiry,
    approved product context, reviewer feedback, and non-negotiable drafting
    constraints. The returned draft is never trusted blindly: it is normalised
    into a _CrewDraftResult and later checked by the local validator.
    """
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
                "invented product suggestions",
                "invented stock",
                "invented lead times",
                "unpersisted catalogue rows",
                "credential disclosure",
                "customer personal data",
                "customer data extraction",
                "unauthorised access guidance",
                "security bypass guidance",
                "subject line in response body",
            ],
        },
    }
    headers = {"Accept": "application/json"}
    if settings.external_agent_api_key:
        headers["Authorization"] = f"Bearer {settings.external_agent_api_key}"

    try:
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
        data.get("ai_draft") or data.get("draft") or data.get("response") or ""
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
        token_usage=_extract_token_usage(data),
    )


def _finalize_token_usage(
    token_usage: dict[str, Any],
    *,
    execution_mode: WorkflowMode,
    subject: str,
    body: str,
    inquiry: InquiryDetails,
    product_context: ProductContext,
    ai_draft: str,
) -> dict[str, Any]:
    """ensures every workflow exposes token usage for evaluation reports."""
    normalised = _normalize_token_usage(token_usage)
    if normalised.get("total_tokens", 0) > 0:
        return normalised

    input_text = "\n".join(
        [
            subject,
            body,
            inquiry.model_dump_json(),
            product_context.model_dump_json(),
        ]
    )
    source = (
        "estimated_slm_text"
        if execution_mode == "deterministic"
        else f"estimated_{execution_mode}_text"
    )
    return _estimated_token_usage(
        input_text=input_text,
        output_text=ai_draft,
        source=source,
    )


def _extract_token_usage(*objects: Any) -> dict[str, Any]:
    """pulls token usage from provider/CrewAI objects with varying shapes."""
    usage: dict[str, Any] = {}
    for item in objects:
        usage = _merge_token_usage(usage, _token_usage_from_object(item))
    return usage


def _token_usage_from_object(item: Any) -> dict[str, Any]:
    if item is None:
        return {}
    if isinstance(item, dict):
        direct = _normalize_token_usage(item)
        if direct.get("total_tokens", 0) > 0:
            return direct
        for key in ("usage", "token_usage", "usage_metrics", "tokens"):
            nested = item.get(key)
            if isinstance(nested, dict):
                normalised = _normalize_token_usage(nested)
                if normalised.get("total_tokens", 0) > 0:
                    return normalised
        return {}

    for attribute in ("token_usage", "usage", "usage_metrics", "tokens"):
        value = getattr(item, attribute, None)
        normalised = _normalize_token_usage(value)
        if normalised.get("total_tokens", 0) > 0:
            return normalised
    return {}


def _normalize_token_usage(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    elif hasattr(value, "dict"):
        value = value.dict()
    elif not isinstance(value, dict) and hasattr(value, "__dict__"):
        value = vars(value)
    if not isinstance(value, dict):
        return {}

    input_tokens = _first_int(
        value,
        "input_tokens",
        "prompt_tokens",
        "prompt_eval_count",
        "prompt_eval_tokens",
    )
    output_tokens = _first_int(
        value,
        "output_tokens",
        "completion_tokens",
        "eval_count",
        "completion_eval_count",
        "completion_eval_tokens",
    )
    total_tokens = _first_int(
        value,
        "total_tokens",
        "total_token_count",
        "tokens",
    )
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens
    if total_tokens == 0:
        return {}
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "token_consumption": total_tokens,
        "token_burn": total_tokens,
        "token_count_source": str(value.get("token_count_source") or "provider_usage"),
    }


def _merge_token_usage(*usages: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "token_consumption": 0,
        "token_burn": 0,
        "token_count_source": "provider_usage",
    }
    found = False
    sources: list[str] = []
    for usage in usages:
        normalised = _normalize_token_usage(usage)
        if not normalised:
            continue
        found = True
        merged["input_tokens"] += int(normalised.get("input_tokens", 0) or 0)
        merged["output_tokens"] += int(normalised.get("output_tokens", 0) or 0)
        merged["total_tokens"] += int(normalised.get("total_tokens", 0) or 0)
        source = str(normalised.get("token_count_source") or "provider_usage")
        sources.append(source)
    if not found:
        return {}
    merged["token_consumption"] = merged["total_tokens"]
    merged["token_burn"] = merged["total_tokens"]
    merged["token_count_source"] = ", ".join(_dedupe(sources))
    return merged


def _estimated_token_usage(
    *,
    input_text: str,
    output_text: str,
    source: str,
) -> dict[str, Any]:
    input_tokens = _estimate_tokens(input_text)
    output_tokens = _estimate_tokens(output_text)
    total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "token_consumption": total_tokens,
        "token_burn": total_tokens,
        "token_count_source": source,
    }


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def _first_int(payload: dict[str, Any], *keys: str) -> int:
    for key in keys:
        if key not in payload:
            continue
        try:
            return int(payload.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0


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


def _provider_retry_after_seconds(exc: Exception) -> float | None:
    """extracts Gemini-style retry guidance before error text is truncated."""
    detail = " ".join(str(exc).split())
    seconds_match = re.search(
        r"(?:retry in|retryDelay['\"=: ]+)\s*(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?",
        detail,
        flags=re.IGNORECASE,
    )
    if seconds_match:
        return float(math.ceil(float(seconds_match.group(1)))) + 0.5
    milliseconds_match = re.search(
        r"retry in\s*(\d+(?:\.\d+)?)\s*ms",
        detail,
        flags=re.IGNORECASE,
    )
    if milliseconds_match:
        return math.ceil(float(milliseconds_match.group(1))) / 1000 + 0.5
    return None


def _lookup_product_context_for_inquiry(
    processor: SalesProcessingAgent,
    inquiry: InquiryDetails,
    product_query: str,
    fallback_query: str | None = None,
) -> ProductContext:
    """
    Select the product lookup tool that matches the classified inquiry.

    Listing requests need a catalogue search so the AI can mention multiple
    persisted products. Product-specific pricing or availability requests use
    the single-product lookup path, keeping the draft grounded in the best
    approved match instead of letting the model invent catalogue facts.
    """
    if inquiry.inquiry_type == "listing":
        return processor.lookup_product_list_context(product_query)
    context = processor.lookup_product_context(inquiry.product_name, product_query)
    if context.confidence < 0.5 and fallback_query:
        return processor.lookup_product_context(inquiry.product_name, fallback_query)
    return context


def _promote_product_only_inquiry(
    processor: SalesProcessingAgent,
    inquiry: InquiryDetails,
    product_context: ProductContext,
) -> InquiryDetails:
    """lets approved product-only emails enter review instead of auto-rejecting."""
    if (
        inquiry.inquiry_type != "unknown"
        or product_context.confidence < 0.5
        or not product_context.product
    ):
        return inquiry

    inquiry_type = "mixed"
    return inquiry.model_copy(
        update={
            "inquiry_type": inquiry_type,
            "product_name": product_context.product,
            "missing_information": processor._missing_information(
                inquiry_type=inquiry_type,
                product_name=product_context.product,
                quantity=inquiry.quantity,
                requested_delivery=inquiry.requested_delivery,
            ),
            "confidence": max(inquiry.confidence, 0.7),
        }
    )


def _append_product_references(ai_draft: str, product_context: ProductContext) -> str:
    """
    Attach customer-visible product references to an AI-generated draft.

    The AI may draft the prose, but this helper deterministically appends
    approved source URLs from the product context. Existing References sections
    are preserved so regenerated or externally supplied drafts are not given
    duplicate link blocks.
    """
    draft_text = normalize_email_draft(ai_draft).rstrip()
    if not draft_text:
        return draft_text
    if any(line.strip().lower() == "references:" for line in draft_text.splitlines()):
        return draft_text

    references = _product_reference_urls(product_context)
    if not references:
        return draft_text

    lines = ["", "", "References:"]
    lines.extend(f"{index}. {url}" for index, url in enumerate(references, start=1))
    return f"{draft_text}{chr(10).join(lines)}"


def _product_reference_urls(product_context: ProductContext) -> list[str]:
    """
    Gather unique approved product URLs from all context visible to the AI.

    The primary product, listed products, and suggested alternatives can each
    contribute a reference. Dedupe happens here so the final customer draft is
    readable even when the same product appears through multiple lookup paths.
    """
    references: list[str] = []
    _add_product_reference_url(references, product_context)
    for item in [*product_context.listed_products, *product_context.suggested_products]:
        _add_product_reference_url(references, item)

    unique: list[str] = []
    seen: set[str] = set()
    for url in references:
        if url and url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _add_product_reference_url(references: list[str], product_context: Any) -> None:
    """
    Add one product reference URL from a catalogue-like object.

    AI-facing product context can come from ProductContext or ProductOption
    instances. This helper reads their shared product, sku, and source_url
    fields and falls back to a configured product-search URL when the catalogue
    row does not include a direct source link.
    """
    product = str(getattr(product_context, "product", "") or "").strip()
    sku = str(getattr(product_context, "sku", "") or "").strip()
    source_url = str(getattr(product_context, "source_url", "") or "").strip()
    if not product and not sku:
        return
    references.append(source_url or _fallback_product_reference_url(sku or product))


def _fallback_product_reference_url(query: str) -> str:
    """
    Build a deterministic product reference when catalogue data lacks a URL.

    The generated URL uses the configured product reference base and the product
    name or SKU. This keeps AI-generated replies anchored to a navigable product
    page/search without asking the model to construct links itself.
    """
    base_url = get_app_settings().product_reference_base_url.strip()
    if not base_url:
        return ""
    if "{query}" in base_url:
        return base_url.replace("{query}", quote_plus(query))

    parsed = urlparse(base_url)
    if parsed.netloc == "safetyware.com" and parsed.path.rstrip("/") == "/products":
        return base_url

    separator = (
        ""
        if base_url.endswith(("=", "?", "&"))
        else ("&" if "?" in base_url else "?q=")
    )
    return f"{base_url}{separator}{quote_plus(query)}"


def _current_reply_segment(body: str) -> str:
    """returns the explicit current-reply section when thread context is prepended."""
    marker = "Current customer reply to answer now:"
    if marker not in body:
        return body
    current = body.rsplit(marker, 1)[-1].strip()
    for context_marker in (
        "\nConversation history",
        "\nUse this only",
        "\nCustomer ",
        "\nCompany ",
    ):
        if context_marker in current:
            current = current.split(context_marker, 1)[0].strip()
    return current or body


def _conversation_history_segment(body: str) -> str:
    """separates prior thread messages from the current reply for CrewAI prompts."""
    marker = "Current customer reply to answer now:"
    if marker not in body:
        return ""
    current_and_history = body.rsplit(marker, 1)[-1].strip()
    if "\n\n" not in current_and_history:
        return ""
    return current_and_history.split("\n\n", 1)[-1].strip()


def _current_reply_inquiry_type(body: str) -> str | None:
    """lets the newest reply decide whether the answer is price, stock, or both."""
    lower = body.lower()
    listing = any(
        token in lower
        for token in (
            "list products",
            "show products",
            "which products",
            "what products",
            "browse products",
        )
    )
    pricing = any(
        token in lower
        for token in (
            "price",
            "pricing",
            "quote",
            "quotation",
            "cost",
            "rate",
            "how much",
            "total",
            "buy",
            "purchase",
            "harga",
            "berapa",
        )
    )
    availability = any(
        token in lower
        for token in (
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
        )
    )
    if listing:
        return "listing"
    if pricing and availability:
        return "mixed"
    if pricing:
        return "pricing"
    if availability:
        return "availability"
    return None


def _canonical_quote_inquiry(
    processor: SalesProcessingAgent,
    inquiry: InquiryDetails,
    product_context: ProductContext,
) -> InquiryDetails | None:
    """returns a database-grounded mixed inquiry for standard quantity quotes."""
    if (
        inquiry.inquiry_type not in {"pricing", "mixed"}
        or inquiry.quantity is None
        or inquiry.quantity <= 0
        or not product_context.product
        or product_context.price is None
        or product_context.confidence < 0.5
        or product_context.listed_products
    ):
        return None

    if processor.product_client is not None and product_context.source != "postgres":
        return None

    inquiry_type = "mixed"
    return inquiry.model_copy(
        update={
            "inquiry_type": inquiry_type,
            "product_name": product_context.product,
            "missing_information": processor._missing_information(
                inquiry_type=inquiry_type,
                product_name=product_context.product,
                quantity=inquiry.quantity,
                requested_delivery=inquiry.requested_delivery,
            ),
        }
    )


def _feedback_quantity_override(feedback: str) -> int | None:
    """
    Extract an explicit reviewer quantity correction for AI redrafting.

    Reviewer feedback can ask the workflow to compute or revise pricing for a
    different quantity. This helper accepts only direct quantity phrases such as
    units, pieces, boxes, cartons, pairs, or sets, then returns the last positive
    quantity found so downstream drafting uses the intended customer amount.
    """
    lower = feedback.lower()
    if not any(
        token in lower
        for token in (
            "want",
            "compute",
            "total",
            "price",
            "pricing",
            "quote",
            "quotation",
        )
    ):
        return None
    matches = [
        int(match.group("quantity").replace(",", ""))
        for match in re.finditer(
            r"\b(?P<quantity>\d{1,3}(?:,\d{3})+|\d{1,6})(?:\.\d+)?\s*"
            r"(?:units?|pcs?|pieces?|boxes?|cartons?|pairs?|sets?)\b",
            lower,
        )
        if int(match.group("quantity").replace(",", "")) > 0
    ]
    return matches[-1] if matches else None


def _feedback_delivery_override(feedback: str) -> str | None:
    """extracts explicit reviewer corrections for requested delivery."""
    if not feedback:
        return None
    patterns = (
        r"requested\s+delivery\s+(?:is|will\s+be|=|:)\s*[\"']?(?P<delivery>[^\"'.\n]+)",
        r"delivery\s+(?:is|will\s+be|=|:)\s*[\"']?(?P<delivery>[^\"'.\n]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, feedback, re.IGNORECASE)
        if not match:
            continue
        delivery = match.group("delivery").strip(" \"'")
        delivery = re.sub(r"\s+", " ", delivery).strip()
        return delivery or None
    return None


def _crewai_workflow_classes() -> tuple[Any, Any]:
    """returns concrete CrewAI orchestration classes before they are used."""
    if _crewai is not None:
        return _crewai.Crew, _crewai.Process
    raise RuntimeError(
        "CrewAI workflow import failed."
    ) from _crewai_workflow_import_error()


def _crewai_workflow_import_error() -> Exception:
    """returns the captured CrewAI workflow import failure as a concrete exception."""
    if _CREWAI_WORKFLOW_IMPORT_ERROR is not None:
        return _CREWAI_WORKFLOW_IMPORT_ERROR
    return RuntimeError("CrewAI module is unavailable.")


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
        notes.extend(
            f"Supervisor/validator noted: {reason}" for reason in validation.reasons
        )
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
