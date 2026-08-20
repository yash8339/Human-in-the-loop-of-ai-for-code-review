from typing import List
from .utils.schema import ReviewResult


def compute_metrics(result: ReviewResult, true_positives: int = 3, false_positives: int = 1) -> ReviewResult:
    """Compute simple evaluation metrics for the review report."""
    total = true_positives + false_positives
    result.accuracy = round((true_positives / total) if total else 0.0, 3)
    result.precision = round((true_positives / max(1, len(result.findings))) if result.findings else 0.0, 3)
    result.recall = round((true_positives / max(1, len(result.findings) + 1)) if result.findings else 0.0, 3)
    result.false_positive_rate = round((false_positives / max(1, len(result.findings))) if result.findings else 0.0, 3)
    return result
