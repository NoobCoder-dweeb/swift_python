from __future__ import annotations

import importlib
import importlib.util
import json
import os

import pytest
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("CREWAI_TESTING", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from tests.evaluation.sales_eval_harness import evaluate_golden, load_goldens  # noqa: E402


pytestmark = pytest.mark.agent_eval

if os.getenv("SWIFT_RUN_AGENT_EVALS") != "1":
    pytest.skip(
        "Set SWIFT_RUN_AGENT_EVALS=1 to run DeepEval agent benchmarks.",
        allow_module_level=True,
    )

deepeval = pytest.importorskip("deepeval")

if (
    not os.getenv("OPENAI_API_KEY")
    and os.getenv("SWIFT_EVAL_JUDGE_CONFIGURED") != "1"
    and os.getenv("SWIFT_EVAL_ALLOW_NO_JUDGE") != "1"
):
    pytest.skip(
        "Set OPENAI_API_KEY or SWIFT_EVAL_JUDGE_CONFIGURED=1 to run DeepEval "
        "judge metrics, or set SWIFT_EVAL_ALLOW_NO_JUDGE=1 for deterministic-only "
        "gates.",
        allow_module_level=True,
    )

if (
    os.getenv("SWIFT_EVAL_JUDGE_CONFIGURED") == "1"
    and os.getenv("GOOGLE_API_KEY")
    and importlib.util.find_spec("google.genai") is None
):
    pytest.fail(
        "Gemini judge is configured, but google-genai is not installed. "
        "Run `.venv/bin/pip install -r requirements-eval.txt`."
    )

assert_test = importlib.import_module("deepeval").assert_test
metrics_module = importlib.import_module("deepeval.metrics")
test_case_module = importlib.import_module("deepeval.test_case")

GEval = getattr(metrics_module, "GEval")
ToolCorrectnessMetric = getattr(metrics_module, "ToolCorrectnessMetric")
LLMTestCase = getattr(test_case_module, "LLMTestCase")
ToolCall = getattr(test_case_module, "ToolCall")
SingleTurnParams = getattr(test_case_module, "SingleTurnParams", None)
if SingleTurnParams is None:
    SingleTurnParams = getattr(test_case_module, "LLMTestCaseParams", None)

if SingleTurnParams is None:
    pytest.skip("DeepEval single-turn parameter enum is unavailable.", allow_module_level=True)


def _goldens():
    limit = int(os.getenv("SWIFT_EVAL_LIMIT", "0") or "0") or None
    return load_goldens(limit=limit)


@pytest.mark.parametrize("golden", _goldens(), ids=lambda golden: golden["id"])
def test_sales_agent_four_pillar_benchmark(golden):
    record = evaluate_golden(
        golden,
        use_crewai=os.getenv("SWIFT_EVAL_USE_CREWAI") == "1",
    )

    fail_on_deterministic_gates = (
        os.getenv("SWIFT_EVAL_FAIL_ON_DETERMINISTIC_GATES") == "1"
    )
    minimum_field_f1 = float(os.getenv("SWIFT_EVAL_FIELD_F1_THRESHOLD", "0.60"))
    if fail_on_deterministic_gates:
        assert record.metrics.task_success["field_f1"] >= minimum_field_f1, json.dumps(
            record.metrics.task_success,
            indent=2,
            sort_keys=True,
        )

    maximum_duplicate_calls = int(os.getenv("SWIFT_EVAL_MAX_DUPLICATE_TOOL_CALLS", "0"))
    if fail_on_deterministic_gates:
        assert (
            record.metrics.coordination["duplicate_tool_calls"] <= maximum_duplicate_calls
        ), json.dumps(record.metrics.coordination, indent=2, sort_keys=True)

    test_case = LLMTestCase(
        input=record.input,
        actual_output=record.actual_output_text,
        expected_output=json.dumps(record.expected_output, sort_keys=True),
        tools_called=[ToolCall(name=name) for name in record.actual_tools],
        expected_tools=[ToolCall(name=name) for name in record.expected_tools],
        completion_time=record.metrics.cost_and_perf["latency_ms"] / 1000,
        token_cost=record.metrics.cost_and_perf["token_burn"],
    )

    metrics = []

    judge_configured = (
        os.getenv("OPENAI_API_KEY") or os.getenv("SWIFT_EVAL_JUDGE_CONFIGURED") == "1"
    )
    if judge_configured:
        metrics.append(
            ToolCorrectnessMetric(
                threshold=float(os.getenv("SWIFT_EVAL_TOOL_THRESHOLD", "0.90")),
                should_consider_ordering=True,
                include_reason=True,
            )
        )

    if judge_configured and os.getenv("SWIFT_EVAL_ENABLE_G_EVAL") == "1":
        metrics.append(
            GEval(
                name="Sales Task Completion",
                criteria=(
                    "Judge whether the sales agent satisfied the operational intent "
                    "of the input, used only approved product facts, preserved safety "
                    "guardrails, and produced the target structured fields."
                ),
                evaluation_params=[
                    SingleTurnParams.INPUT,
                    SingleTurnParams.ACTUAL_OUTPUT,
                    SingleTurnParams.EXPECTED_OUTPUT,
                ],
                threshold=float(os.getenv("SWIFT_EVAL_TASK_THRESHOLD", "0.80")),
            )
        )

    if metrics:
        assert_test(test_case, metrics)
