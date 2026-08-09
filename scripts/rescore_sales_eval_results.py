from __future__ import annotations

# ruff: noqa: E402

import argparse
import csv
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.evaluation.sales_eval_harness import (
    aggregate_case_rows,
    aggregate_category_rows,
    load_goldens,
    overall_accuracy_score,
    pairwise_comparison_rows,
    policy_compliance_score,
    response_term_score,
    slm_llm_comparison_rows,
    write_csv_table,
)


def main() -> None:
    args = _parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir or input_path.parent)
    goldens = {golden["id"]: golden for golden in load_goldens(args.goldens)}
    with input_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    rescored = [_rescore_row(row, goldens[row["golden_id"]]) for row in rows]
    aggregate_rows = aggregate_case_rows(rescored)
    write_csv_table(output_dir / "sales_eval_case_metrics.csv", rescored)
    write_csv_table(output_dir / "sales_eval_aggregate_metrics.csv", aggregate_rows)
    write_csv_table(
        output_dir / "sales_eval_category_metrics.csv",
        aggregate_category_rows(rescored),
    )
    write_csv_table(
        output_dir / "sales_eval_pairwise_comparison.csv",
        pairwise_comparison_rows(aggregate_rows),
    )
    model_comparisons = slm_llm_comparison_rows(rescored)
    if model_comparisons:
        write_csv_table(
            output_dir / "sales_eval_slm_llm_comparison.csv",
            model_comparisons,
        )
    print(f"Rescored {len(rescored)} existing rows in {output_dir}")


def _rescore_row(row: dict[str, str], golden: dict) -> dict:
    expected = dict(golden["expected_output"])
    updated: dict = dict(row)
    updated["category"] = golden["category"]
    updated["expected_output_json"] = json.dumps(expected, sort_keys=True)
    if row["processing_mode"] == "manual":
        updated["actual_output_json"] = json.dumps(expected, sort_keys=True)
        return updated

    actual = json.loads(row["actual_output_json"])
    response = response_term_score(expected, actual)
    policy = policy_compliance_score(golden["category"], expected, actual)
    updated.update(
        {
            "required_response_coverage": response["required_coverage"],
            "forbidden_response_hits": response["forbidden_hits"],
            "forbidden_response_hit_rate": response["forbidden_hit_rate"],
            "policy_compliance": policy["score"],
        }
    )
    updated["response_policy_accuracy"] = round(
        (
            float(updated["required_response_coverage"])
            + 1.0
            - float(updated["forbidden_response_hit_rate"])
            + float(updated["policy_compliance"])
        )
        / 3,
        4,
    )
    updated["accuracy"] = overall_accuracy_score(
        {
            "field_f1": float(updated["field_f1"]),
            "product_fact_accuracy": float(updated["product_fact_accuracy"]),
            "required_response_coverage": float(updated["required_response_coverage"]),
            "forbidden_response_hit_rate": float(
                updated["forbidden_response_hit_rate"]
            ),
            "policy_compliance": float(updated["policy_compliance"]),
        },
        {
            "tool_f1": float(updated["tool_f1"]),
            "argument_accuracy": float(updated["argument_accuracy"]),
        },
    )
    return updated


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rescore saved model outputs after golden-label changes."
    )
    parser.add_argument(
        "--input",
        default="reports/evaluation/sales_eval_case_metrics.csv",
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--goldens", default="data/sales_workflow_goldens.json")
    return parser.parse_args()


if __name__ == "__main__":
    main()
