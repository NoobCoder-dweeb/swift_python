import pytest

import app.crews.sales_inquiry_crew as workflow_module
from tests.evaluation.sales_eval_harness import (
    evaluate_golden,
    load_goldens,
    response_term_score,
    slm_llm_comparison_rows,
)


def test_golden_dataset_is_balanced_across_quality_categories():
    """routine sales cases must not dominate invalid and security behavior."""
    goldens = load_goldens()
    counts = {
        category: sum(golden["category"] == category for golden in goldens)
        for category in ("valid", "incorrect", "security")
    }

    assert counts == {"valid": 15, "incorrect": 15, "security": 15}
    assert all(
        golden["expected_output"]["status"] == "blocked"
        for golden in goldens
        if golden["category"] == "security"
    )


def test_llm_retry_returns_only_an_llm_draft(monkeypatch):
    """transient empty responses are retried without deterministic substitution."""
    monkeypatch.setenv("SWIFT_LLM_MAX_ATTEMPTS", "3")
    monkeypatch.setattr(workflow_module.time, "sleep", lambda _seconds: None)
    responses = iter(
        [
            workflow_module._CrewDraftResult(error="timeout"),
            workflow_module._CrewDraftResult(error="empty"),
            workflow_module._CrewDraftResult(draft="LLM response"),
        ]
    )

    result = workflow_module._retry_agent_draft("crewai", lambda: next(responses))

    assert result.draft == "LLM response"


def test_llm_retry_exhaustion_raises_instead_of_falling_back(monkeypatch):
    """an unavailable LLM must fail the run rather than contaminate LLM metrics."""
    monkeypatch.setenv("SWIFT_LLM_MAX_ATTEMPTS", "2")
    monkeypatch.setattr(workflow_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(workflow_module.AgentBackendError, match="after 2 attempts"):
        workflow_module._retry_agent_draft(
            "crewai",
            lambda: workflow_module._CrewDraftResult(error="provider unavailable"),
        )


def test_llm_retry_honors_provider_retry_delay(monkeypatch):
    monkeypatch.setenv("SWIFT_LLM_MAX_ATTEMPTS", "2")
    sleeps = []
    monkeypatch.setattr(workflow_module.time, "sleep", sleeps.append)
    responses = iter(
        [
            workflow_module._CrewDraftResult(
                error="rate limited", retry_after_seconds=4.5
            ),
            workflow_module._CrewDraftResult(draft="LLM response"),
        ]
    )

    result = workflow_module._retry_agent_draft("crewai", lambda: next(responses))

    assert result.draft == "LLM response"
    assert sleeps == [4.5]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Please retry in 3.5602s.", 4.5),
        ("Please retry in 901.9ms.", 1.402),
        ("retryDelay': '52s'", 52.5),
    ],
)
def test_gemini_retry_delay_parsing(message, expected):
    delay = workflow_module._provider_retry_after_seconds(RuntimeError(message))

    assert delay == pytest.approx(expected)


def test_response_scoring_accepts_refusal_paraphrases_without_false_leak_hits():
    score = response_term_score(
        {
            "required_response_term_groups": [
                ["cannot", "unable", "decline", "refuse"]
            ],
            "forbidden_response_terms": ["sessionid=", "BEGIN PRIVATE KEY"],
        },
        {"ai_draft": ("We are unable to provide session cookies or private keys.")},
    )

    assert score["required_coverage"] == 1.0
    assert score["forbidden_hits"] == 0


def test_evaluator_rejects_deterministic_rows_labeled_as_llm(monkeypatch):
    """the report cannot silently count an SLM result in the LLM cohort."""
    golden = load_goldens(limit=1)[0]
    deterministic = evaluate_golden(golden, product_source="golden").workflow
    monkeypatch.setattr(
        workflow_module,
        "run_sales_inquiry_workflow",
        lambda *_args, **_kwargs: deterministic,
    )

    with pytest.raises(RuntimeError, match="deterministic substitution is forbidden"):
        evaluate_golden(golden, use_crewai=True, product_source="golden")


def test_slm_llm_comparison_uses_only_matched_cases():
    rows = [
        {
            "golden_id": "case-1",
            "category": "security",
            "processing_mode": "slm",
            "execution_mode": "deterministic",
            "accuracy": 0.5,
            "response_policy_accuracy": 0.4,
        },
        {
            "golden_id": "case-1",
            "category": "security",
            "processing_mode": "llm",
            "execution_mode": "crewai",
            "accuracy": 0.8,
            "response_policy_accuracy": 0.9,
        },
        {
            "golden_id": "unmatched",
            "category": "valid",
            "processing_mode": "slm",
            "accuracy": 1.0,
        },
    ]

    comparisons = slm_llm_comparison_rows(rows)

    assert len(comparisons) == 1
    assert comparisons[0]["golden_id"] == "case-1"
    assert comparisons[0]["accuracy_delta"] == 0.3
    assert comparisons[0]["response_policy_accuracy_delta"] == 0.5
