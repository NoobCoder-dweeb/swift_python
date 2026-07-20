from __future__ import annotations

import json
from importlib import import_module
from typing import Any

from app.crews.agent_config import get_task_prompt
from app.crews.agents import _configure_crewai_storage
from app.crews.workflow_models import (
    DraftValidationResult,
    InquiryDetails,
    ProductContext,
)

try:
    _crewai = import_module("crewai")
except Exception as exc:  # pragma: no cover - depends on optional runtime install
    _crewai = None
    _CREWAI_TASK_IMPORT_ERROR = exc
else:
    _CREWAI_TASK_IMPORT_ERROR = None


def create_extract_inquiry_task(
    agent: Any,
    sender: str,
    subject: str,
    body: str,
):
    """constrains the sales agent to structured extraction instead of prose."""
    _configure_crewai_storage()
    task_class = _crewai_task_class()
    prompt = get_task_prompt("extract_inquiry")

    return task_class(
        description=prompt.render_description(
            sender=sender,
            subject=subject,
            body=body,
        ),
        expected_output=prompt.expected_output,
        agent=agent,
        output_pydantic=InquiryDetails,
    )


def create_draft_response_task(
    agent: Any,
    inquiry: InquiryDetails,
    product_context: ProductContext,
    reviewer_feedback: str | None = None,
    previous_draft: str | None = None,
):
    """gives the drafting agent explicit facts and boundaries for the reply."""
    _configure_crewai_storage()
    task_class = _crewai_task_class()
    prompt = get_task_prompt("draft_response")
    feedback = (reviewer_feedback or "").strip()
    prior = (previous_draft or "").strip()

    return task_class(
        description=prompt.render_description(
            inquiry_json=inquiry.model_dump_json(indent=2),
            product_context_json=product_context.model_dump_json(indent=2),
            reviewer_feedback=feedback or "None",
            previous_draft=prior or "None",
        ),
        expected_output=prompt.expected_output,
        agent=agent,
    )


def create_validation_task(
    agent: Any,
    inquiry: InquiryDetails,
    product_context: ProductContext,
    draft: str,
    reviewer_feedback: str | None = None,
    previous_draft: str | None = None,
):
    """asks a separate agent to catch unsafe claims before human review."""
    _configure_crewai_storage()
    task_class = _crewai_task_class()
    prompt = get_task_prompt("validation")

    payload = {
        "inquiry": inquiry.model_dump(),
        "product_context": product_context.model_dump(),
        "reviewer_feedback": reviewer_feedback or "",
        "previous_draft": previous_draft or "",
        "draft": draft,
    }

    return task_class(
        description=prompt.render_description(
            validation_payload=json.dumps(payload, indent=2),
        ),
        expected_output=prompt.expected_output,
        agent=agent,
        output_pydantic=DraftValidationResult,
    )


def _crewai_task_class() -> Any:
    """returns the concrete CrewAI Task class or raises before construction."""
    if _crewai is not None:
        return _crewai.Task
    raise RuntimeError("CrewAI Task import failed.") from _crewai_task_import_error()


def _crewai_task_import_error() -> Exception:
    """returns the captured CrewAI task import failure as a concrete exception."""
    if _CREWAI_TASK_IMPORT_ERROR is not None:
        return _CREWAI_TASK_IMPORT_ERROR
    return RuntimeError("CrewAI module is unavailable.")
