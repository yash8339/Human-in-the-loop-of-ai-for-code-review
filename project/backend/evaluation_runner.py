from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ai_review.reviewer import run_ai_review
from .evaluation import REJECTION_REASONS, classify_rejection, mann_whitney_u, quality_metrics
from .merge.merger import build_comparison_table, findings_match, normalize_finding
from .static_analysis.runner import run_static_analysis


@dataclass
class EvaluationCase:
    path: str
    expected: list[dict[str, Any]] = field(default_factory=list)
    fixed_path: str | None = None
    human_decisions: list[dict[str, str]] = field(default_factory=list)


def evaluate_test_set(cases: list[EvaluationCase], analyzer: str = "semgrep", model: str = "OpenAI") -> dict[str, Any]:
    """Run Human-only, AI-only, Static-only, and Combined conditions."""
    condition_results = {name: [] for name in ("Human-only", "AI-only", "Static-analysis-only", "Combined")}
    quality = []
    for case in cases:
        ai = _timed(lambda: run_ai_review(case.path, model=model))
        static = _timed(lambda: run_static_analysis(case.path, analyzer=analyzer))
        combined = build_comparison_table({"chatgpt": ai["findings"], analyzer: static["findings"]})
        combined_findings = [{"line": row.get("line", 0), "title": row.get("category", row.get("issue", ""))} for row in combined]
        conditions = {
            "Human-only": (case.expected, 0.0), "AI-only": (ai["findings"], ai["seconds"]),
            "Static-analysis-only": (static["findings"], static["seconds"]),
            "Combined": (combined_findings, ai["seconds"] + static["seconds"]),
        }
        for name, (findings, seconds) in conditions.items():
            condition_results[name].append(_score(findings, case.expected, seconds))
        quality.append(quality_metrics(case.path, case.fixed_path))

    summary = {name: _summarize(results) for name, results in condition_results.items()}
    for name, results in condition_results.items():
        summary[name]["case_results"] = results
    summary["Human-only"]["adoption_rate"] = _human_adoption(cases)
    return {"conditions": summary, "quality_delta": _average_quality(quality),
            "rejection_reasons": _rejection_summary(cases),
            "statistical_test": mann_whitney_u({name: [row["review_time"] for row in rows] for name, rows in condition_results.items()})}


def save_evaluation(report: dict[str, Any], output_path: str | Path) -> None:
    Path(output_path).write_text(json.dumps(report, indent=2), encoding="utf-8")


def _timed(function):
    started = time.perf_counter()
    return {"findings": function(), "seconds": round(time.perf_counter() - started, 6)}


def _score(findings: list[dict[str, Any]], expected: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    expected_rows = [normalize_finding(item, source="ground-truth") for item in expected]
    found_rows = [normalize_finding(item, source="condition") for item in findings]
    matched_expected: set[int] = set()
    true_positives = 0
    for found in found_rows:
        for index, expected_row in enumerate(expected_rows):
            if index not in matched_expected and findings_match(found, expected_row):
                matched_expected.add(index)
                true_positives += 1
                break
    return {"bugs_found": true_positives, "false_positives": len(found_rows) - true_positives,
            "total_suggestions": len(found_rows), "review_time": seconds}


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {key: sum(row[key] for row in results) for key in ("bugs_found", "false_positives", "total_suggestions")} | {"review_time": round(sum(row["review_time"] for row in results), 6), "adoption_rate": 0.0}


def _human_adoption(cases: list[EvaluationCase]) -> float:
    decisions = [decision for case in cases for decision in case.human_decisions]
    return round(sum(decision.get("status") == "accept" for decision in decisions) / len(decisions), 4) if decisions else 0.0


def _rejection_summary(cases: list[EvaluationCase]) -> dict[str, int]:
    counts = {reason: 0 for reason in REJECTION_REASONS}
    for case in cases:
        for decision in case.human_decisions:
            if decision.get("status") in {"reject", "modify"}:
                counts[classify_rejection(decision.get("reviewer_note", ""))] += 1
    return counts


def _average_quality(metrics: list[dict[str, float]]) -> dict[str, float]:
    if not metrics:
        return {}
    return {key: round(sum(item[key] for item in metrics) / len(metrics), 4) for key in metrics[0]}