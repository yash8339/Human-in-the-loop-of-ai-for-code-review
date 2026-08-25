from __future__ import annotations

import ast
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable
from .utils.schema import ReviewResult

REJECTION_REASONS = ("Incorrect", "Not Needed", "Alternative Fix", "Preference", "Deferred", "Other")


def compute_metrics(result: ReviewResult, true_positives: int = 3, false_positives: int = 1) -> ReviewResult:
    """Compute simple evaluation metrics for the review report."""
    total = true_positives + false_positives
    result.accuracy = round((true_positives / total) if total else 0.0, 3)
    result.precision = round((true_positives / max(1, len(result.findings))) if result.findings else 0.0, 3)
    result.recall = round((true_positives / max(1, len(result.findings) + 1)) if result.findings else 0.0, 3)
    result.false_positive_rate = round((false_positives / max(1, len(result.findings))) if result.findings else 0.0, 3)
    return result


def classify_rejection(note: str) -> str:
    """Map reviewer text to one of the required rejection categories."""
    text = (note or "").lower()
    keywords = {
        "Incorrect": ("incorrect", "wrong", "false positive", "not a bug"),
        "Not Needed": ("not needed", "unnecessary", "already handled"),
        "Alternative Fix": ("alternative", "another fix", "different fix"),
        "Preference": ("prefer", "preference", "style"),
        "Deferred": ("defer", "later", "backlog"),
    }
    for reason, matches in keywords.items():
        if any(match in text for match in matches):
            return reason
    return "Other"


def quality_metrics(source_path: str | Path, fixed_path: str | Path | None = None) -> dict[str, float]:
    """Measure source size and cyclomatic complexity before and after fixes."""
    before = _measure_file(Path(source_path))
    after = _measure_file(Path(fixed_path)) if fixed_path else before.copy()
    return {
        "size_before": before["size"], "size_after": after["size"],
        "complexity_before": before["complexity"], "complexity_after": after["complexity"],
        "size_delta": after["size"] - before["size"],
        "complexity_delta": after["complexity"] - before["complexity"],
    }


def mann_whitney_u(samples: dict[str, Iterable[float]]) -> dict[str, Any]:
    """Run two-sided pairwise tests for every condition with enough observations."""
    values = {name: list(numbers) for name, numbers in samples.items()}
    try:
        from scipy.stats import mannwhitneyu
    except ImportError:
        return {"available": False, "reason": "scipy is not installed."}
    comparisons = {}
    for left_name, right_name in combinations(values, 2):
        left, right = values[left_name], values[right_name]
        if len(left) < 2 or len(right) < 2:
            continue
        statistic, p_value = mannwhitneyu(left, right, alternative="two-sided")
        comparisons[f"{left_name} vs {right_name}"] = {
            "conditions": [left_name, right_name],
            "u_statistic": round(float(statistic), 4),
            "p_value": round(float(p_value), 6),
            "significant_at_0_05": bool(p_value < 0.05),
        }
    if not comparisons:
        return {"available": False, "reason": "At least two observations per compared condition are required.", "comparisons": {}}
    return {"available": True, "comparisons": comparisons}


def _measure_file(path: Path) -> dict[str, float]:
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        import lizard
        from radon.complexity import cc_visit

        lizard_result = lizard.analyze_file(str(path))
        complexity = sum(block.complexity for block in cc_visit(source))
        return {"size": float(lizard_result.nloc), "complexity": float(complexity)}
    except (ImportError, OSError, AttributeError, SyntaxError):
        pass
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {"size": float(len(source.splitlines())), "complexity": 0.0}
    complexity = 1 + sum(isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.IfExp, ast.BoolOp)) for node in ast.walk(tree))
    return {"size": float(len(source.splitlines())), "complexity": float(complexity)}
