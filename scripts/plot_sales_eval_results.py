from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Iterable


SCORE_METRICS = (
    ("accuracy", "Accuracy"),
    ("field_f1", "Field F1"),
    ("product_fact_accuracy", "Product facts"),
    ("required_response_coverage", "Response terms"),
    ("tool_f1", "Tool F1"),
    ("argument_accuracy", "Argument accuracy"),
)


def main() -> None:
    args = _parse_args()
    rows = _read_rows(Path(args.input))
    report_rows = _reportable_rows(rows)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_metric_comparison(output_dir / "figure_1_metric_scores.svg", report_rows)
    _write_module_accuracy(output_dir / "figure_2_slm_accuracy_by_module.svg", report_rows)
    _write_efficiency_chart(output_dir / "figure_3_review_time_saved.svg", report_rows)
    _write_markdown_summary(output_dir / "results_discussion_summary.md", rows, report_rows)

    print(f"Wrote figures and summary to {output_dir}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Graph raw sales evaluation rows for results/discussion reporting."
    )
    parser.add_argument(
        "--input",
        default="reports/evaluation/sales_eval_case_metrics.csv",
        help="Raw per-case evaluation CSV.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/evaluation/figures",
        help="Directory for SVG figures and Markdown summary.",
    )
    return parser.parse_args()


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_metric_comparison(path: Path, rows: list[dict[str, str]]) -> None:
    modes = [mode for mode in ("manual", "slm", "llm") if _mode_rows(rows, mode)]
    data = {
        mode: [
            _mean(_float(row[metric]) for row in _mode_rows(rows, mode))
            for metric, _label in SCORE_METRICS
        ]
        for mode in modes
    }
    labels = [label for _metric, label in SCORE_METRICS]
    path.write_text(
        _grouped_bar_svg(
            title="Evaluation quality by processing mode",
            subtitle="Mean score from raw per-case rows; higher is better",
            labels=labels,
            series=data,
            y_max=1.0,
            y_label="Mean score",
        ),
        encoding="utf-8",
    )


def _write_module_accuracy(path: Path, rows: list[dict[str, str]]) -> None:
    slm_rows = _mode_rows(rows, "slm")
    by_module: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in slm_rows:
        by_module[row["module"]].append(row)

    data = sorted(
        (
            module,
            _mean(_float(row["accuracy"]) for row in module_rows),
            len(module_rows),
        )
        for module, module_rows in by_module.items()
    )
    data.sort(key=lambda item: item[1])
    path.write_text(
        _horizontal_bar_svg(
            title="SLM accuracy by inquiry module",
            subtitle="Mean composite accuracy from raw SLM rows; lower bars show failure modes",
            rows=data,
            x_max=1.0,
            x_label="Mean accuracy",
        ),
        encoding="utf-8",
    )


def _write_efficiency_chart(path: Path, rows: list[dict[str, str]]) -> None:
    modes = [mode for mode in ("manual", "slm", "llm") if _mode_rows(rows, mode)]
    data = {
        mode: [
            _mean(_float(row["estimated_review_minutes"]) for row in _mode_rows(rows, mode)),
            _mean(_float(row["automation_time_saved_pct"]) for row in _mode_rows(rows, mode)),
        ]
        for mode in modes
    }
    path.write_text(
        _grouped_bar_svg(
            title="Review workload and estimated automation savings",
            subtitle="Mean values from raw per-case rows",
            labels=["Review minutes", "Time saved (%)"],
            series=data,
            y_max=100.0,
            y_label="Minutes / percent",
        ),
        encoding="utf-8",
    )


def _write_markdown_summary(
    path: Path,
    rows: list[dict[str, str]],
    report_rows: list[dict[str, str]],
) -> None:
    modes = [mode for mode in ("manual", "slm", "llm") if _mode_rows(rows, mode)]
    report_modes = [
        mode for mode in ("manual", "slm", "llm") if _mode_rows(report_rows, mode)
    ]
    excluded_rows = len(rows) - len(report_rows)
    lines = [
        "# Sales Evaluation Results Summary",
        "",
        "## Dataset",
        "",
        f"- Raw rows: {len(rows)}",
        "- Processing modes: "
        + ", ".join(f"{mode} (n={len(_mode_rows(rows, mode))})" for mode in modes),
        "- Source file: `reports/evaluation/sales_eval_case_metrics.csv`",
        f"- Reportable plotted rows: {len(report_rows)}",
    ]
    if excluded_rows:
        lines.append(
            f"- Excluded fallback/error LLM rows from plotted comparisons: {excluded_rows}"
        )
    lines.extend(
        [
        "",
        "## Core Results",
        "",
        "| Mode | n | Accuracy | Field F1 | Product facts | Response terms | Tool F1 | Argument accuracy | Exact fields | Exact tools | Review min | Time saved | Tokens |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in report_modes:
        mode_rows = _mode_rows(report_rows, mode)
        lines.append(
            "| "
            + " | ".join(
                [
                    mode.upper(),
                    str(len(mode_rows)),
                    _fmt(_mean(_float(row["accuracy"]) for row in mode_rows)),
                    _fmt(_mean(_float(row["field_f1"]) for row in mode_rows)),
                    _fmt(
                        _mean(
                            _float(row["product_fact_accuracy"]) for row in mode_rows
                        )
                    ),
                    _fmt(
                        _mean(
                            _float(row["required_response_coverage"])
                            for row in mode_rows
                        )
                    ),
                    _fmt(_mean(_float(row["tool_f1"]) for row in mode_rows)),
                    _fmt(
                        _mean(_float(row["argument_accuracy"]) for row in mode_rows)
                    ),
                    _pct(_rate(row["field_exact_match"] for row in mode_rows)),
                    _pct(_rate(row["tool_exact_sequence"] for row in mode_rows)),
                    _fmt(
                        _mean(
                            _float(row["estimated_review_minutes"])
                            for row in mode_rows
                        )
                    ),
                    _pct(
                        _mean(
                            _float(row["automation_time_saved_pct"])
                            for row in mode_rows
                        )
                        / 100
                    ),
                    _fmt(_mean(_float(row["total_tokens"]) for row in mode_rows)),
                ]
            )
            + " |"
        )

    slm_rows = _mode_rows(rows, "slm")
    if slm_rows:
        lowest = _lowest_modules(slm_rows)
        lines.extend(
            [
                "",
                "## Suggested Results Text",
                "",
                (
                    "The raw evaluation set contained "
                    f"{len(rows)} case-level rows across "
                    f"{len({row['module'] for row in rows})} inquiry modules. "
                    "Manual handling served as the human-verified baseline and "
                    "therefore scored 1.00 across task and tool metrics."
                ),
                "",
                (
                    "The deterministic/SLM workflow achieved mean composite "
                    f"accuracy of {_fmt(_mean(_float(row['accuracy']) for row in slm_rows))}, "
                    f"mean field F1 of {_fmt(_mean(_float(row['field_f1']) for row in slm_rows))}, "
                    f"and mean tool F1 of {_fmt(_mean(_float(row['tool_f1']) for row in slm_rows))}. "
                    f"Exact field matches occurred in {_pct(_rate(row['field_exact_match'] for row in slm_rows))} "
                    f"of SLM cases, while exact tool sequences occurred in {_pct(_rate(row['tool_exact_sequence'] for row in slm_rows))}."
                ),
                "",
                (
                    "The largest operational gain was review workload reduction: "
                    "manual processing was modeled at "
                    f"{_fmt(_mean(_float(row['estimated_manual_minutes']) for row in slm_rows))} minutes per case, "
                    "whereas the SLM workflow required an estimated "
                    f"{_fmt(_mean(_float(row['estimated_review_minutes']) for row in slm_rows))} review minutes, "
                    f"equivalent to {_pct(_mean(_float(row['automation_time_saved_pct']) for row in slm_rows) / 100)} "
                    "mean time savings."
                ),
                "",
                "## Suggested Discussion Text",
                "",
                (
                    "The results indicate that the workflow is strongest for "
                    "structured pricing and routine product inquiries, where tool "
                    "selection and product fact retrieval remain close to the manual "
                    "baseline. The weaker modules were "
                    + ", ".join(
                        f"{module} (mean accuracy {_fmt(score)}, n={count})"
                        for module, score, count in lowest
                    )
                    + ". These cases are useful targets for improving extraction "
                    "rules, response coverage, and edge-case handling."
                ),
                "",
                (
                    "Because no LLM/CrewAI rows are present in this raw export, the "
                    "figures should be reported as a comparison between manual "
                    "handling and the deterministic/SLM workflow only. LLM results "
                    "should be added as a separate processing mode once the local "
                    "LLM backend is running and `--include-llm` completes."
                ),
            ]
        )

    lines.extend(
        [
            "",
            "## Figures To Include",
            "",
            "- `figure_1_metric_scores.svg`: report task/tool quality against the manual baseline.",
            "- `figure_2_slm_accuracy_by_module.svg`: discuss which inquiry types are easiest or hardest.",
            "- `figure_3_review_time_saved.svg`: support operational-efficiency claims.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mode_rows(rows: list[dict[str, str]], mode: str) -> list[dict[str, str]]:
    return [row for row in rows if row["processing_mode"] == mode]


def _reportable_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Excludes failed LLM attempts that fell back to deterministic execution."""
    return [
        row
        for row in rows
        if row["processing_mode"] != "llm"
        or row.get("execution_mode") in {"crewai", "external"}
    ]


def _lowest_modules(rows: list[dict[str, str]]) -> list[tuple[str, float, int]]:
    by_module: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_module[row["module"]].append(row)
    modules = [
        (
            module,
            _mean(_float(row["accuracy"]) for row in module_rows),
            len(module_rows),
        )
        for module, module_rows in by_module.items()
    ]
    modules.sort(key=lambda item: item[1])
    return modules[:5]


def _grouped_bar_svg(
    *,
    title: str,
    subtitle: str,
    labels: list[str],
    series: dict[str, list[float]],
    y_max: float,
    y_label: str,
) -> str:
    width = 1040
    height = 620
    margin_left = 88
    margin_right = 36
    margin_top = 92
    margin_bottom = 130
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    colors = {"manual": "#536dfe", "slm": "#00897b", "llm": "#d81b60"}
    mode_names = list(series)
    group_w = plot_w / len(labels)
    bar_gap = 8
    bar_w = max(12, (group_w - 28 - bar_gap * (len(mode_names) - 1)) / len(mode_names))
    parts = [_svg_open(width, height), _title(title, subtitle, width)]
    parts.append(_axis(margin_left, margin_top, plot_w, plot_h, y_max, y_label))
    for group_idx, label in enumerate(labels):
        group_x = margin_left + group_idx * group_w
        label_x = group_x + group_w / 2
        parts.append(
            f'<text x="{label_x:.1f}" y="{height - 82}" text-anchor="middle" '
            'font-size="13" fill="#263238">'
            f"{_esc(label)}</text>"
        )
        for mode_idx, mode in enumerate(mode_names):
            value = series[mode][group_idx]
            x = group_x + 14 + mode_idx * (bar_w + bar_gap)
            bar_h = 0 if y_max == 0 else (value / y_max) * plot_h
            y = margin_top + plot_h - bar_h
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
                f'rx="3" fill="{colors.get(mode, "#546e7a")}"/>'
            )
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{max(y - 7, margin_top + 12):.1f}" '
                'text-anchor="middle" font-size="11" fill="#263238">'
                f"{value:.2f}</text>"
            )
    parts.append(_legend(mode_names, colors, margin_left, height - 34))
    parts.append("</svg>")
    return "\n".join(parts)


def _horizontal_bar_svg(
    *,
    title: str,
    subtitle: str,
    rows: list[tuple[str, float, int]],
    x_max: float,
    x_label: str,
) -> str:
    width = 1040
    row_h = 32
    height = 154 + row_h * len(rows)
    margin_left = 220
    margin_right = 84
    margin_top = 92
    plot_w = width - margin_left - margin_right
    colors = "#00897b"
    parts = [_svg_open(width, height), _title(title, subtitle, width)]
    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top - 8}" x2="{margin_left}" '
        f'y2="{height - 64}" stroke="#cfd8dc"/>'
    )
    parts.append(
        f'<text x="{margin_left + plot_w / 2}" y="{height - 20}" text-anchor="middle" '
        f'font-size="13" fill="#455a64">{_esc(x_label)}</text>'
    )
    for idx, (module, score, count) in enumerate(rows):
        y = margin_top + idx * row_h
        bar_w = 0 if x_max == 0 else score / x_max * plot_w
        parts.append(
            f'<text x="{margin_left - 10}" y="{y + 17}" text-anchor="end" '
            f'font-size="12" fill="#263238">{_esc(module)} (n={count})</text>'
        )
        parts.append(
            f'<rect x="{margin_left}" y="{y}" width="{bar_w:.1f}" height="22" '
            f'rx="3" fill="{colors}"/>'
        )
        parts.append(
            f'<text x="{margin_left + bar_w + 8:.1f}" y="{y + 16}" '
            f'font-size="12" fill="#263238">{score:.2f}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _axis(
    x: int,
    y: int,
    width: int,
    height: int,
    y_max: float,
    y_label: str,
) -> str:
    parts = [
        f'<line x1="{x}" y1="{y + height}" x2="{x + width}" y2="{y + height}" stroke="#b0bec5"/>',
        f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y + height}" stroke="#b0bec5"/>',
        f'<text x="22" y="{y + height / 2}" transform="rotate(-90 22 {y + height / 2})" '
        f'text-anchor="middle" font-size="13" fill="#455a64">{_esc(y_label)}</text>',
    ]
    for tick in range(6):
        value = y_max * tick / 5
        tick_y = y + height - (value / y_max * height if y_max else 0)
        parts.append(
            f'<line x1="{x - 5}" y1="{tick_y:.1f}" x2="{x + width}" y2="{tick_y:.1f}" '
            'stroke="#eceff1"/>'
        )
        parts.append(
            f'<text x="{x - 12}" y="{tick_y + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#607d8b">{value:.1f}</text>'
        )
    return "\n".join(parts)


def _legend(
    modes: list[str],
    colors: dict[str, str],
    x: int,
    y: int,
) -> str:
    parts = []
    cursor = x
    for mode in modes:
        parts.append(
            f'<rect x="{cursor}" y="{y - 12}" width="14" height="14" '
            f'rx="2" fill="{colors.get(mode, "#546e7a")}"/>'
        )
        parts.append(
            f'<text x="{cursor + 20}" y="{y}" font-size="13" fill="#263238">'
            f"{_esc(mode.upper())}</text>"
        )
        cursor += 110
    return "\n".join(parts)


def _title(title: str, subtitle: str, width: int) -> str:
    return "\n".join(
        [
            f'<text x="{width / 2}" y="38" text-anchor="middle" '
            f'font-size="24" font-weight="700" fill="#263238">{_esc(title)}</text>',
            f'<text x="{width / 2}" y="64" text-anchor="middle" '
            f'font-size="14" fill="#607d8b">{_esc(subtitle)}</text>',
        ]
    )


def _svg_open(width: int, height: int) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img">',
            '<rect width="100%" height="100%" fill="#ffffff"/>',
        ]
    )


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return mean(materialized) if materialized else 0.0


def _float(value: str) -> float:
    return float(value) if value not in ("", None) else 0.0


def _rate(values: Iterable[str]) -> float:
    materialized = list(values)
    if not materialized:
        return 0.0
    truthy = {"true", "1", "yes"}
    return sum(str(value).lower() in truthy for value in materialized) / len(materialized)


def _fmt(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


if __name__ == "__main__":
    main()
