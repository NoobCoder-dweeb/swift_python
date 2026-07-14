from __future__ import annotations

# ruff: noqa: E402

import argparse
from pathlib import Path
import sys

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.evaluation.sales_eval_harness import (
    DEFAULT_EVAL_OUTPUT_DIR,
    aggregate_case_rows,
    evaluate_goldens,
    evaluation_record_to_row,
    load_goldens,
    manual_baseline_row,
    pairwise_comparison_rows,
    write_csv_table,
)


def main() -> None:
    load_dotenv(override=False)
    args = _parse_args()
    output_dir = Path(args.output_dir)
    goldens = load_goldens(args.goldens, limit=args.limit)

    rows: list[dict] = []
    if not args.skip_manual:
        rows.extend(manual_baseline_row(golden) for golden in goldens)

    if not args.skip_slm:
        rows.extend(
            evaluation_record_to_row(record)
            for record in evaluate_goldens(
                goldens,
                use_crewai=False,
                processing_mode="slm",
                product_source=args.product_source,
            )
        )

    if args.include_llm:
        rows.extend(
            evaluation_record_to_row(record)
            for record in evaluate_goldens(
                goldens,
                use_crewai=True,
                processing_mode="llm",
                product_source=args.product_source,
            )
        )

    write_csv_table(output_dir / "sales_eval_case_metrics.csv", rows)
    if not args.raw_only:
        aggregate_rows = aggregate_case_rows(rows)
        comparison_rows = pairwise_comparison_rows(aggregate_rows)
        write_csv_table(output_dir / "sales_eval_aggregate_metrics.csv", aggregate_rows)
        write_csv_table(output_dir / "sales_eval_pairwise_comparison.csv", comparison_rows)

    output_mode = "raw case rows" if args.raw_only else "case, aggregate, and comparison rows"
    print(f"Wrote {len(rows)} {output_mode} to {output_dir}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export database-backed sales workflow evaluation metrics to CSV "
            "for manual, SLM, and optional LLM comparison."
        )
    )
    parser.add_argument(
        "--goldens",
        default="data/sales_workflow_goldens.json",
        help="Path to the golden dataset JSON.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_EVAL_OUTPUT_DIR),
        help="Directory for CSV outputs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional number of golden cases to evaluate.",
    )
    parser.add_argument(
        "--product-source",
        choices=("database", "golden"),
        default=None,
        help=(
            "Product fact source. Defaults to SWIFT_EVAL_PRODUCT_SOURCE or database. "
            "Use golden only for offline harness development."
        ),
    )
    parser.add_argument(
        "--include-llm",
        action="store_true",
        help="Also run the CrewAI/LLM path. Requires local LLM configuration.",
    )
    parser.add_argument(
        "--skip-manual",
        action="store_true",
        help="Do not emit the manual-processing baseline rows.",
    )
    parser.add_argument(
        "--skip-slm",
        action="store_true",
        help="Do not run the deterministic/SLM workflow rows.",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Write only the per-case raw CSV and skip aggregate/comparison outputs.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
