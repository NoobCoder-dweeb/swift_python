from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
from typing import Any

from app.crews.sales_inquiry_crew import run_sales_inquiry_workflow
from app.crews.workflow_models import SalesWorkflowResult
from app.schemas.email import IncomingEmail


GOLDEN_DATASET_PATH = Path("data/sales_workflow_goldens.json")
NUMERIC_TOLERANCE = 0.02


@dataclass(frozen=True)
class MetricMatrix:
    task_success: dict[str, Any]
    tool_quality: dict[str, Any]
    coordination: dict[str, Any]
    cost_and_perf: dict[str, Any]


@dataclass(frozen=True)
class EvaluationRecord:
    golden_id: str
    module: str
    input: str
    expected_tools: list[str]
    actual_tools: list[str]
    expected_output: dict[str, Any]
    actual_output: dict[str, Any]
    actual_output_text: str
    workflow: SalesWorkflowResult
    metrics: MetricMatrix


def load_goldens(
    path: Path | str = GOLDEN_DATASET_PATH,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    goldens = list(payload["goldens"])
    return goldens[:limit] if limit else goldens


def raw_input_to_email(raw_input: str) -> IncomingEmail:
    sender = _first_match(
        raw_input,
        [
            r"(?im)^From:\s*(?P<value>\S+)",
            r"(?im)^ContactEmail:\s*(?P<value>\S+)",
            r"(?im)^Email:\s*(?P<value>\S+)",
            r"(?im)^email,[^\n]*\n(?P<value>[^,\s]+)",
            r"(?P<value>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
        ],
    )
    subject = _first_match(
        raw_input,
        [
            r"(?im)^Subject:\s*(?P<value>.+)$",
            r"(?im)^Interest:\s*(?P<value>.+)$",
            r"(?im)^LeadSource:\s*(?P<value>.+)$",
        ],
    )
    body = _body_from_raw_input(raw_input)
    return IncomingEmail(
        sender=sender or "unknown.customer@example.com",
        subject=subject or "Sales inquiry",
        body=body,
    )


def evaluate_golden(golden: dict[str, Any], *, use_crewai: bool = False) -> EvaluationRecord:
    email = raw_input_to_email(golden["input"])
    wall_start = time.perf_counter()
    workflow = run_sales_inquiry_workflow(email, use_crewai=use_crewai)
    measured_latency_ms = (time.perf_counter() - wall_start) * 1000
    expected_output = dict(golden["expected_output"])
    actual_output = workflow_to_output(workflow)
    actual_tools = infer_tool_trajectory(golden, workflow)
    metrics = score_four_pillars(
        expected_output=expected_output,
        actual_output=actual_output,
        expected_tools=list(golden["expected_tools"]),
        actual_tools=actual_tools,
        workflow=workflow,
        measured_latency_ms=measured_latency_ms,
    )
    return EvaluationRecord(
        golden_id=golden["id"],
        module=golden["module"],
        input=golden["input"],
        expected_tools=list(golden["expected_tools"]),
        actual_tools=actual_tools,
        expected_output=expected_output,
        actual_output=actual_output,
        actual_output_text=json.dumps(actual_output, sort_keys=True),
        workflow=workflow,
        metrics=metrics,
    )


def workflow_to_output(workflow: SalesWorkflowResult) -> dict[str, Any]:
    return {
        "status": workflow.status,
        "inquiry_type": workflow.inquiry.inquiry_type,
        "sender": workflow.sender,
        "product_name": workflow.inquiry.product_name,
        "quantity": workflow.inquiry.quantity,
        "requested_delivery": workflow.inquiry.requested_delivery,
        "missing_information": workflow.inquiry.missing_information,
        "risk_flags": workflow.inquiry.risk_flags,
        "product_context": {
            "sku": workflow.product_context.sku,
            "product": workflow.product_context.product,
            "price": workflow.product_context.price,
            "currency": workflow.product_context.currency,
            "stock_availability": workflow.product_context.stock_availability,
            "source": workflow.product_context.source,
            "listed_products": [
                item.model_dump() for item in workflow.product_context.listed_products
            ],
            "suggested_products": [
                item.model_dump() for item in workflow.product_context.suggested_products
            ],
        },
        "validation": workflow.validation.model_dump(),
        "erp_target": {
            "object": "blocked_inquiry" if workflow.status == "blocked" else "sales_draft",
            "queue": (
                "manager_review"
                if workflow.status == "blocked"
                else "pending_sales_review"
            ),
        },
        "ai_draft": workflow.ai_draft,
        "chokeholds": workflow.chokeholds,
        "execution_mode": workflow.execution_mode,
        "agent_models": workflow.agent_models,
    }


def infer_tool_trajectory(
    golden: dict[str, Any],
    workflow: SalesWorkflowResult,
) -> list[str]:
    tools: list[str] = []
    if golden["input"].lstrip().startswith("LeadSource:"):
        tools.append("lead_parser.parse_raw_lead")
    else:
        tools.append("email_preprocessor.preprocess_email")

    if _has_guardrail_signal(workflow):
        tools.append("guardrails.classify_risk")

    if "Re:" in workflow.subject:
        tools.append("conversation_linker.find_existing_draft")

    tools.append("sales_processing.extract_inquiry")
    tools.extend(_product_lookup_tools(workflow))
    tools.append(
        "email_drafting.generate_blocked_response"
        if workflow.status == "blocked"
        else "email_drafting.generate_response"
    )
    tools.append("draft_validation.validate_draft")
    tools.append(
        "draft_repository.upsert_draft"
        if workflow.status == "pending"
        else "draft_repository.upsert_draft"
    )
    return tools


def score_four_pillars(
    *,
    expected_output: dict[str, Any],
    actual_output: dict[str, Any],
    expected_tools: list[str],
    actual_tools: list[str],
    workflow: SalesWorkflowResult,
    measured_latency_ms: float,
) -> MetricMatrix:
    field_score = field_level_f1(expected_output, actual_output)
    return MetricMatrix(
        task_success={
            "field_f1": field_score["f1"],
            "field_precision": field_score["precision"],
            "field_recall": field_score["recall"],
            "field_checks": field_score["checks"],
            "task_completion_source": "deepeval_geval_when_enabled",
        },
        tool_quality={
            "tool_match": tool_match_score(expected_tools, actual_tools),
            "args_match": argument_match_score(expected_output, actual_output),
            "expected_tools": expected_tools,
            "actual_tools": actual_tools,
        },
        coordination={
            "routing_precision": routing_precision(workflow),
            "duplicate_tool_calls": duplicate_tool_calls(actual_tools),
            "execution_mode": workflow.execution_mode,
            "agent_models": workflow.agent_models,
        },
        cost_and_perf={
            "latency_ms": round(max(workflow.elapsed_ms, measured_latency_ms), 2),
            "token_burn": token_burn(workflow),
            "p50_source": "aggregate benchmark run",
            "p95_source": "aggregate benchmark run",
        },
    )


def field_level_f1(
    expected_output: dict[str, Any],
    actual_output: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for field in (
        "status",
        "inquiry_type",
        "sender",
        "product_name",
        "quantity",
        "requested_delivery",
        "erp_target",
    ):
        if field in expected_output:
            checks.append(_check_value(field, expected_output[field], actual_output.get(field)))

    expected_context = expected_output.get("product_context", {})
    actual_context = actual_output.get("product_context", {})
    for field in ("sku", "price", "currency", "stock_availability", "source"):
        if field in expected_context and expected_context[field] is not None:
            checks.append(
                _check_value(
                    f"product_context.{field}",
                    expected_context[field],
                    actual_context.get(field),
                )
            )

    for field in ("missing_information", "risk_flags"):
        checks.extend(
            _check_expected_members(
                field,
                expected_output.get(field, []),
                actual_output.get(field, []),
            )
        )

    true_positive = sum(1 for check in checks if check["matched"])
    false_positive = sum(1 for check in checks if not check["matched"])
    false_negative = false_positive
    precision = _safe_div(true_positive, true_positive + false_positive)
    recall = _safe_div(true_positive, true_positive + false_negative)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "checks": checks,
    }


def tool_match_score(expected_tools: list[str], actual_tools: list[str]) -> dict[str, Any]:
    expected_remaining = list(expected_tools)
    correct = 0
    for tool in actual_tools:
        if tool in expected_remaining:
            correct += 1
            expected_remaining.remove(tool)
    exact_sequence = expected_tools == actual_tools
    return {
        "score": round(_safe_div(correct, len(actual_tools)), 4),
        "correct_tools_called": correct,
        "total_tools_called": len(actual_tools),
        "exact_sequence_match": exact_sequence,
        "missing_tools": expected_remaining,
        "unexpected_tools": [tool for tool in actual_tools if tool not in expected_tools],
    }


def argument_match_score(
    expected_output: dict[str, Any],
    actual_output: dict[str, Any],
) -> dict[str, Any]:
    relevant_fields = ["sender", "product_name", "quantity", "requested_delivery"]
    checks = [
        _check_value(field, expected_output.get(field), actual_output.get(field))
        for field in relevant_fields
        if field in expected_output and expected_output.get(field) is not None
    ]
    matched = sum(1 for check in checks if check["matched"])
    return {
        "score": round(_safe_div(matched, len(checks)), 4),
        "checks": checks,
    }


def routing_precision(workflow: SalesWorkflowResult) -> float | None:
    if workflow.execution_mode != "crewai":
        return None
    expected_roles = {"supervisor", "sales_processing", "email_drafting"}
    actual_roles = set(workflow.agent_models)
    return round(_safe_div(len(expected_roles & actual_roles), len(expected_roles)), 4)


def duplicate_tool_calls(actual_tools: list[str]) -> int:
    return sum(
        1
        for previous, current in zip(actual_tools, actual_tools[1:], strict=False)
        if previous == current
    )


def token_burn(workflow: SalesWorkflowResult) -> int | None:
    if workflow.execution_mode == "deterministic":
        return 0
    return None


def _body_from_raw_input(raw_input: str) -> str:
    body_match = re.search(r"(?ims)^Body:\s*(?P<body>.*)$", raw_input)
    if body_match:
        return body_match.group("body").strip()
    message_match = re.search(r"(?ims)^Message:\s*(?P<body>.*)$", raw_input)
    if message_match:
        return message_match.group("body").strip()
    return raw_input.strip()


def _first_match(raw_input: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, raw_input)
        if match:
            return match.group("value").strip()
    return None


def _product_lookup_tools(workflow: SalesWorkflowResult) -> list[str]:
    if workflow.inquiry.inquiry_type == "listing" or workflow.product_context.listed_products:
        return ["postgres_product_lookup.search_products"]
    tools = []
    if workflow.inquiry.product_name or workflow.product_context.product:
        tools.append("postgres_product_lookup.get_product")
    if workflow.product_context.suggested_products:
        tools.append("postgres_product_lookup.suggest_products")
    return tools


def _has_guardrail_signal(workflow: SalesWorkflowResult) -> bool:
    guardrail_flags = {
        "prompt_injection",
        "privacy_request",
        "unsafe_request",
        "spam",
        "personal_data",
        "credential_request",
        "data_exfiltration",
        "hacking_intent",
        "out_of_scope",
        "no_sales_intent",
    }
    return bool(guardrail_flags & set(workflow.inquiry.risk_flags)) or workflow.status == "blocked"


def _check_expected_members(
    field: str,
    expected_values: list[Any],
    actual_values: list[Any],
) -> list[dict[str, Any]]:
    actual_normalized = {_normalize(value) for value in actual_values}
    return [
        {
            "field": field,
            "expected": expected,
            "actual": actual_values,
            "matched": _normalize(expected) in actual_normalized,
        }
        for expected in expected_values
    ]


def _check_value(field: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "field": field,
        "expected": expected,
        "actual": actual,
        "matched": _values_match(expected, actual),
    }


def _values_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, float | int) and isinstance(actual, float | int):
        tolerance = abs(float(expected)) * NUMERIC_TOLERANCE
        return abs(float(expected) - float(actual)) <= tolerance
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(
            key in actual and _values_match(value, actual[key])
            for key, value in expected.items()
            if value is not None
        )
    if expected is None:
        return actual is None
    return _normalize(expected) == _normalize(actual)


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0
