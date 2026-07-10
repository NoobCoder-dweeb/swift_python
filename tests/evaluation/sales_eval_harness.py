from __future__ import annotations

from contextlib import contextmanager, nullcontext
import csv
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from statistics import mean, median, stdev
import time
from typing import Any

import app.crews.sales_inquiry_crew as sales_inquiry_crew
from app.crews.workflow_models import SalesWorkflowResult
from app.core.config import get_app_settings
from app.repositories.product_repository import build_product_lookup_client
from app.schemas.email import IncomingEmail


GOLDEN_DATASET_PATH = Path("data/sales_workflow_goldens.json")
DEFAULT_EVAL_OUTPUT_DIR = Path("reports/evaluation")
NUMERIC_TOLERANCE = 0.02
PROCESSING_MODES = ("manual", "slm", "llm")


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
    processing_mode: str
    product_source: str
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


def evaluate_golden(
    golden: dict[str, Any],
    *,
    use_crewai: bool = False,
    processing_mode: str | None = None,
    product_source: str | None = None,
) -> EvaluationRecord:
    email = raw_input_to_email(golden["input"])
    resolved_product_source = _resolve_product_source(product_source)
    if resolved_product_source == "database":
        assert_database_catalog_available_for_golden(golden)

    wall_start = time.perf_counter()
    lookup_context = (
        _golden_product_lookup_context(golden)
        if resolved_product_source == "golden"
        else nullcontext()
    )
    with lookup_context:
        workflow = sales_inquiry_crew.run_sales_inquiry_workflow(
            email,
            use_crewai=use_crewai,
        )
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
        processing_mode=processing_mode or ("llm" if use_crewai else "slm"),
        product_source=resolved_product_source,
        input=golden["input"],
        expected_tools=list(golden["expected_tools"]),
        actual_tools=actual_tools,
        expected_output=expected_output,
        actual_output=actual_output,
        actual_output_text=json.dumps(actual_output, sort_keys=True),
        workflow=workflow,
        metrics=metrics,
    )


def evaluate_goldens(
    goldens: list[dict[str, Any]],
    *,
    use_crewai: bool = False,
    processing_mode: str | None = None,
    product_source: str | None = None,
) -> list[EvaluationRecord]:
    return [
        evaluate_golden(
            golden,
            use_crewai=use_crewai,
            processing_mode=processing_mode,
            product_source=product_source,
        )
        for golden in goldens
    ]


class GoldenProductLookupClient:
    """offline-only fallback that serves product facts declared by one golden."""

    def __init__(self, golden: dict[str, Any]) -> None:
        self.expected_output = dict(golden["expected_output"])
        self.expected_context = dict(self.expected_output.get("product_context", {}))

    def get_product(self, query: str) -> dict[str, Any]:
        product = self.expected_output.get("product_name")
        if not product or self.expected_context.get("source") is None:
            return self._missing_product_context(product)

        context = {
            "product": product,
            "sku": self.expected_context.get("sku"),
            "source_url": _golden_source_url(product, self.expected_context.get("sku")),
            "stock_availability": self.expected_context.get("stock_availability"),
            "price": self.expected_context.get("price"),
            "currency": self.expected_context.get("currency", "RM"),
            "source": self.expected_context.get("source", "postgres"),
            "confidence": 0.99,
            "notes": ["Golden evaluation catalog row."],
        }
        if context["sku"] is None and context["price"] is None:
            return self._missing_product_context(product)
        return context

    def search_products(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        products = self.expected_context.get("products")
        if isinstance(products, list):
            return [_golden_option(item) for item in products[:limit]]

        options = []
        seen = set()
        for term in self.expected_output.get("required_response_terms", []):
            option = _golden_named_option(str(term))
            if option and option["product"] not in seen:
                seen.add(option["product"])
                options.append(option)
        return options[:limit]

    def suggest_products(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
        return self.search_products(query, limit=limit)

    def _missing_product_context(self, product: str | None) -> dict[str, Any]:
        return {
            "product": product,
            "source": "postgres",
            "confidence": 0.0,
            "notes": ["No approved golden product record matched the inquiry."],
            "suggested_products": [],
        }


@contextmanager
def _golden_product_lookup_context(golden: dict[str, Any]):
    original = sales_inquiry_crew.build_product_lookup_client
    sales_inquiry_crew.build_product_lookup_client = lambda: GoldenProductLookupClient(
        golden
    )
    try:
        yield
    finally:
        sales_inquiry_crew.build_product_lookup_client = original


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
    response_score = response_term_score(expected_output, actual_output)
    product_score = product_fact_score(expected_output, actual_output)
    tool_score = tool_match_score(expected_tools, actual_tools)
    argument_score = argument_match_score(expected_output, actual_output)
    return MetricMatrix(
        task_success={
            "field_f1": field_score["f1"],
            "field_precision": field_score["precision"],
            "field_recall": field_score["recall"],
            "field_exact_match": field_score["exact_match"],
            "field_checks": field_score["checks"],
            "required_response_coverage": response_score["required_coverage"],
            "forbidden_response_hits": response_score["forbidden_hits"],
            "forbidden_response_hit_rate": response_score["forbidden_hit_rate"],
            "product_fact_accuracy": product_score["accuracy"],
            "product_fact_checks": product_score["checks"],
            "task_completion_source": "deepeval_geval_when_enabled",
        },
        tool_quality={
            "tool_match": tool_score,
            "tool_precision": tool_score["precision"],
            "tool_recall": tool_score["recall"],
            "tool_f1": tool_score["f1"],
            "args_match": argument_score,
            "argument_accuracy": argument_score["score"],
            "expected_tools": expected_tools,
            "actual_tools": actual_tools,
        },
        coordination={
            "routing_precision": routing_precision(workflow),
            "duplicate_tool_calls": duplicate_tool_calls(actual_tools),
            "tool_call_count": len(actual_tools),
            "chokehold_count": len(workflow.chokeholds),
            "blocked_status": workflow.status == "blocked",
            "human_review_required": workflow.status in {"pending", "blocked"},
            "execution_mode": workflow.execution_mode,
            "agent_models": workflow.agent_models,
        },
        cost_and_perf={
            "latency_ms": round(max(workflow.elapsed_ms, measured_latency_ms), 2),
            "token_burn": token_burn(workflow),
            "estimated_manual_minutes": _env_float(
                "SWIFT_EVAL_MANUAL_MINUTES_PER_CASE",
                10.0,
            ),
            "estimated_review_minutes": estimated_review_minutes(workflow),
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
        "exact_match": bool(checks) and all(check["matched"] for check in checks),
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
    precision = _safe_div(correct, len(actual_tools))
    recall = _safe_div(correct, len(expected_tools))
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {
        "score": round(precision, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "correct_tools_called": correct,
        "total_tools_called": len(actual_tools),
        "expected_tool_count": len(expected_tools),
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


def response_term_score(
    expected_output: dict[str, Any],
    actual_output: dict[str, Any],
) -> dict[str, Any]:
    draft = str(actual_output.get("ai_draft") or "")
    draft_normalized = _normalize(draft)
    required_terms = [str(term) for term in expected_output.get("required_response_terms", [])]
    forbidden_terms = [str(term) for term in expected_output.get("forbidden_response_terms", [])]
    required_checks = [
        {
            "term": term,
            "matched": _normalize(term) in draft_normalized,
        }
        for term in required_terms
    ]
    forbidden_hits = [
        term for term in forbidden_terms if _normalize(term) in draft_normalized
    ]
    return {
        "required_coverage": round(
            _safe_div(
                sum(1 for check in required_checks if check["matched"]),
                len(required_checks),
            ),
            4,
        ),
        "required_checks": required_checks,
        "forbidden_hits": len(forbidden_hits),
        "forbidden_hit_terms": forbidden_hits,
        "forbidden_hit_rate": round(_safe_div(len(forbidden_hits), len(forbidden_terms)), 4),
    }


def product_fact_score(
    expected_output: dict[str, Any],
    actual_output: dict[str, Any],
) -> dict[str, Any]:
    expected_context = expected_output.get("product_context", {})
    actual_context = actual_output.get("product_context", {})
    checks: list[dict[str, Any]] = []
    for field in ("sku", "price", "currency", "stock_availability", "source"):
        if field in expected_context and expected_context[field] is not None:
            checks.append(
                _check_value(
                    f"product_context.{field}",
                    expected_context[field],
                    actual_context.get(field),
                )
            )

    expected_products = expected_context.get("products")
    if isinstance(expected_products, list):
        actual_products = [
            *actual_context.get("listed_products", []),
            *actual_context.get("suggested_products", []),
        ]
        actual_skus = {_normalize(item.get("sku")) for item in actual_products}
        for product in expected_products:
            sku = product.get("sku")
            if sku:
                checks.append(
                    {
                        "field": "product_context.products.sku",
                        "expected": sku,
                        "actual": sorted(actual_skus),
                        "matched": _normalize(sku) in actual_skus,
                    }
                )

    matched = sum(1 for check in checks if check["matched"])
    return {
        "accuracy": round(_safe_div(matched, len(checks)), 4),
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


def estimated_review_minutes(workflow: SalesWorkflowResult) -> float:
    base = _env_float("SWIFT_EVAL_REVIEW_MINUTES_PER_PENDING_CASE", 2.0)
    blocked = _env_float("SWIFT_EVAL_REVIEW_MINUTES_PER_BLOCKED_CASE", 4.0)
    return blocked if workflow.status == "blocked" else base


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


def assert_database_catalog_available_for_golden(golden: dict[str, Any]) -> None:
    """Ensure benchmark product facts are read from the configured database."""
    expected_output = dict(golden.get("expected_output", {}))
    expected_context = dict(expected_output.get("product_context", {}))
    if expected_context.get("source") != "postgres":
        return

    client = _database_product_lookup_client()
    product_name = expected_output.get("product_name")
    expected_sku = expected_context.get("sku")
    if expected_sku and product_name:
        context = client.get_product(str(product_name))
        if not _values_match(expected_sku, context.get("sku")):
            raise AssertionError(
                "Golden dataset product context must match swift_products. "
                f"{golden.get('id')} expected sku={expected_sku!r}, "
                f"database returned sku={context.get('sku')!r} for {product_name!r}."
            )

    expected_products = expected_context.get("products")
    if isinstance(expected_products, list):
        rows = client.search_products(golden.get("input", ""), limit=max(5, len(expected_products)))
        actual_skus = {_normalize(row.get("sku")) for row in rows}
        missing = [
            item.get("sku")
            for item in expected_products
            if item.get("sku") and _normalize(item.get("sku")) not in actual_skus
        ]
        if missing:
            raise AssertionError(
                "Golden dataset multi-product context must be retrievable from "
                f"swift_products. {golden.get('id')} missing skus={missing!r}."
            )


def _database_product_lookup_client():
    settings = get_app_settings()
    if settings.storage_mode != "postgres" or not settings.database_url:
        raise RuntimeError(
            "Agent evaluation requires database-backed product facts by default. "
            "Set SWIFT_STORAGE_BACKEND=postgres and DATABASE_URL, then seed "
            "swift_products with init.db. For offline harness development only, "
            "set SWIFT_EVAL_PRODUCT_SOURCE=golden."
        )
    client = build_product_lookup_client()
    if client is None:
        raise RuntimeError("PostgreSQL product lookup client is unavailable.")
    return client


def _resolve_product_source(product_source: str | None = None) -> str:
    explicit = (product_source or os.getenv("SWIFT_EVAL_PRODUCT_SOURCE") or "").strip().lower()
    if explicit:
        if explicit not in {"database", "golden"}:
            raise ValueError("SWIFT_EVAL_PRODUCT_SOURCE must be 'database' or 'golden'.")
        return explicit

    legacy = os.getenv("SWIFT_EVAL_USE_GOLDEN_PRODUCT_CATALOG")
    if legacy is not None and legacy != "0":
        return "golden"
    return "database"


def _golden_option(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "product": item.get("product") or item.get("name"),
        "sku": item.get("sku"),
        "source_url": _golden_source_url(item.get("product") or item.get("name"), item.get("sku")),
        "category": item.get("category"),
        "description": item.get("description"),
        "stock_availability": item.get("stock_availability"),
        "price": item.get("price"),
        "currency": item.get("currency", "RM"),
        "unit_of_measure": item.get("unit_of_measure") or "unit",
        "source": item.get("source", "postgres"),
        "confidence": item.get("confidence", 0.99),
    }


def _golden_named_option(term: str) -> dict[str, Any] | None:
    term_lower = term.lower()
    for product, values in _GOLDEN_PRODUCT_FACTS.items():
        if product.lower() in term_lower:
            return _golden_option({"product": product, **values})
    return None


def _golden_source_url(product: str | None, sku: str | None) -> str | None:
    if not product and not sku:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", (sku or product or "").lower()).strip("-")
    return f"https://safetyware.com/product/{slug}/"


def manual_baseline_row(golden: dict[str, Any]) -> dict[str, Any]:
    """Represent manual processing as the human-labeled gold standard row."""
    manual_minutes = _env_float("SWIFT_EVAL_MANUAL_MINUTES_PER_CASE", 10.0)
    expected_output = dict(golden["expected_output"])
    expected_tools = list(golden["expected_tools"])
    return {
        "golden_id": golden["id"],
        "module": golden["module"],
        "processing_mode": "manual",
        "product_source": "human_verified_database",
        "execution_mode": "manual",
        "field_f1": 1.0,
        "field_precision": 1.0,
        "field_recall": 1.0,
        "field_exact_match": True,
        "product_fact_accuracy": 1.0,
        "required_response_coverage": 1.0,
        "forbidden_response_hits": 0,
        "forbidden_response_hit_rate": 0.0,
        "tool_precision": 1.0,
        "tool_recall": 1.0,
        "tool_f1": 1.0,
        "tool_exact_sequence": True,
        "argument_accuracy": 1.0,
        "duplicate_tool_calls": 0,
        "tool_call_count": len(expected_tools),
        "chokehold_count": 0,
        "latency_ms": round(manual_minutes * 60 * 1000, 2),
        "estimated_manual_minutes": manual_minutes,
        "estimated_review_minutes": manual_minutes,
        "automation_time_saved_pct": 0.0,
        "token_burn": 0,
        "status": expected_output.get("status"),
        "inquiry_type": expected_output.get("inquiry_type"),
        "product_name": expected_output.get("product_name"),
        "sku": expected_output.get("product_context", {}).get("sku"),
        "price": expected_output.get("product_context", {}).get("price"),
        "stock_availability": expected_output.get("product_context", {}).get("stock_availability"),
        "expected_tools": json.dumps(expected_tools),
        "actual_tools": json.dumps(expected_tools),
    }


def evaluation_record_to_row(record: EvaluationRecord) -> dict[str, Any]:
    task = record.metrics.task_success
    tool_match = record.metrics.tool_quality["tool_match"]
    coordination = record.metrics.coordination
    cost = record.metrics.cost_and_perf
    actual_context = record.actual_output.get("product_context", {})
    manual_minutes = float(cost["estimated_manual_minutes"])
    review_minutes = float(cost["estimated_review_minutes"])
    return {
        "golden_id": record.golden_id,
        "module": record.module,
        "processing_mode": record.processing_mode,
        "product_source": record.product_source,
        "execution_mode": record.workflow.execution_mode,
        "field_f1": task["field_f1"],
        "field_precision": task["field_precision"],
        "field_recall": task["field_recall"],
        "field_exact_match": task["field_exact_match"],
        "product_fact_accuracy": task["product_fact_accuracy"],
        "required_response_coverage": task["required_response_coverage"],
        "forbidden_response_hits": task["forbidden_response_hits"],
        "forbidden_response_hit_rate": task["forbidden_response_hit_rate"],
        "tool_precision": record.metrics.tool_quality["tool_precision"],
        "tool_recall": record.metrics.tool_quality["tool_recall"],
        "tool_f1": record.metrics.tool_quality["tool_f1"],
        "tool_exact_sequence": tool_match["exact_sequence_match"],
        "argument_accuracy": record.metrics.tool_quality["argument_accuracy"],
        "duplicate_tool_calls": coordination["duplicate_tool_calls"],
        "tool_call_count": coordination["tool_call_count"],
        "chokehold_count": coordination["chokehold_count"],
        "latency_ms": cost["latency_ms"],
        "estimated_manual_minutes": manual_minutes,
        "estimated_review_minutes": review_minutes,
        "automation_time_saved_pct": round(
            _safe_div(manual_minutes - review_minutes, manual_minutes) * 100,
            2,
        ),
        "token_burn": cost["token_burn"],
        "status": record.actual_output.get("status"),
        "inquiry_type": record.actual_output.get("inquiry_type"),
        "product_name": record.actual_output.get("product_name"),
        "sku": actual_context.get("sku"),
        "price": actual_context.get("price"),
        "stock_availability": actual_context.get("stock_availability"),
        "expected_tools": json.dumps(record.expected_tools),
        "actual_tools": json.dumps(record.actual_tools),
    }


def aggregate_case_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["processing_mode"]), []).append(row)

    metric_names = (
        "field_f1",
        "product_fact_accuracy",
        "required_response_coverage",
        "forbidden_response_hit_rate",
        "tool_f1",
        "argument_accuracy",
        "latency_ms",
        "estimated_review_minutes",
        "automation_time_saved_pct",
        "chokehold_count",
    )
    summary_rows: list[dict[str, Any]] = []
    for mode, mode_rows in sorted(grouped.items()):
        summary: dict[str, Any] = {
            "processing_mode": mode,
            "n": len(mode_rows),
            "field_exact_match_rate": _rate(mode_rows, "field_exact_match"),
            "tool_exact_sequence_rate": _rate(mode_rows, "tool_exact_sequence"),
        }
        for metric in metric_names:
            values = [_float(row.get(metric)) for row in mode_rows if row.get(metric) not in ("", None)]
            summary.update(_numeric_summary(metric, values))
        summary_rows.append(summary)
    return summary_rows


def pairwise_comparison_rows(
    aggregate_rows: list[dict[str, Any]],
    *,
    baseline: str = "manual",
) -> list[dict[str, Any]]:
    by_mode = {row["processing_mode"]: row for row in aggregate_rows}
    baseline_row = by_mode.get(baseline)
    if not baseline_row:
        return []

    comparisons: list[dict[str, Any]] = []
    for mode, row in sorted(by_mode.items()):
        if mode == baseline:
            continue
        comparisons.append(
            {
                "baseline": baseline,
                "comparison": mode,
                "field_f1_delta": _delta(row, baseline_row, "field_f1_mean"),
                "product_fact_accuracy_delta": _delta(
                    row,
                    baseline_row,
                    "product_fact_accuracy_mean",
                ),
                "tool_f1_delta": _delta(row, baseline_row, "tool_f1_mean"),
                "latency_ms_delta": _delta(row, baseline_row, "latency_ms_mean"),
                "latency_reduction_pct": _percent_reduction(
                    baseline_row.get("latency_ms_mean"),
                    row.get("latency_ms_mean"),
                ),
                "review_minutes_delta": _delta(
                    row,
                    baseline_row,
                    "estimated_review_minutes_mean",
                ),
                "review_time_reduction_pct": _percent_reduction(
                    baseline_row.get("estimated_review_minutes_mean"),
                    row.get("estimated_review_minutes_mean"),
                ),
                "automation_time_saved_pct_mean": row.get(
                    "automation_time_saved_pct_mean"
                ),
            }
        )
    return comparisons


def write_csv_table(path: Path | str, rows: list[dict[str, Any]]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _csv_fieldnames(rows)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _rate(rows: list[dict[str, Any]], key: str) -> float:
    return round(_safe_div(sum(1 for row in rows if _truthy(row.get(key))), len(rows)), 4)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes"}


def _numeric_summary(metric: str, values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            f"{metric}_mean": "",
            f"{metric}_median": "",
            f"{metric}_stdev": "",
            f"{metric}_stderr": "",
            f"{metric}_ci95_low": "",
            f"{metric}_ci95_high": "",
            f"{metric}_min": "",
            f"{metric}_max": "",
        }
    metric_mean = mean(values)
    metric_stdev = stdev(values) if len(values) > 1 else 0.0
    stderr = metric_stdev / (len(values) ** 0.5) if values else 0.0
    ci_delta = 1.96 * stderr
    return {
        f"{metric}_mean": round(metric_mean, 4),
        f"{metric}_median": round(median(values), 4),
        f"{metric}_stdev": round(metric_stdev, 4),
        f"{metric}_stderr": round(stderr, 4),
        f"{metric}_ci95_low": round(metric_mean - ci_delta, 4),
        f"{metric}_ci95_high": round(metric_mean + ci_delta, 4),
        f"{metric}_min": round(min(values), 4),
        f"{metric}_max": round(max(values), 4),
    }


def _delta(row: dict[str, Any], baseline: dict[str, Any], key: str) -> float | str:
    if row.get(key) in ("", None) or baseline.get(key) in ("", None):
        return ""
    return round(float(row[key]) - float(baseline[key]), 4)


def _percent_reduction(baseline: Any, current: Any) -> float | str:
    if baseline in ("", None) or current in ("", None):
        return ""
    baseline_value = float(baseline)
    current_value = float(current)
    return round(_safe_div(baseline_value - current_value, baseline_value) * 100, 2)


def _csv_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    return fieldnames


_GOLDEN_PRODUCT_FACTS: dict[str, dict[str, Any]] = {
    "Safety Helmet": {
        "sku": "SAFE-HELMET-001",
        "price": 25.0,
        "currency": "RM",
        "stock_availability": 120,
        "source": "postgres",
    },
    "Safety Gloves": {
        "sku": "SAFE-GLOVES-001",
        "price": 8.5,
        "currency": "RM",
        "stock_availability": 900,
        "source": "postgres",
    },
    "Product X": {
        "sku": "PROD-X-001",
        "price": 120.0,
        "currency": "RM",
        "stock_availability": 500,
        "source": "postgres",
    },
    "Face Shield": {
        "sku": "SAFE-FACE-SHIELD",
        "price": 12.5,
        "currency": "RM",
        "stock_availability": 30,
        "source": "postgres",
    },
    "Steel-Toe Safety Boots": {
        "sku": "SAFE-BOOTS-001",
        "price": 58.0,
        "currency": "RM",
        "stock_availability": 180,
        "source": "postgres",
    },
    "Fire Hose": {
        "sku": "SAFE-FIRE-HOSE",
        "price": 88.0,
        "currency": "RM",
        "stock_availability": 24,
        "source": "postgres",
    },
}
