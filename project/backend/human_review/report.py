from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..utils.schema import ReviewFinding, ReviewResult
from .decisions import HumanDecision, issue_id_for


def generate_final_report(
    result: ReviewResult,
    decisions: Iterable[HumanDecision] = (),
    *,
    review_time: float | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> dict:
    """Build a serializable report from findings and human decisions."""
    decision_by_id = {decision.issue_id: decision for decision in decisions}
    findings = list(result.findings)
    sections = {
        "critical": _report_findings(findings, "critical", decision_by_id),
        "medium": _report_findings(findings, "medium", decision_by_id),
    }
    total_reviewed = len(decision_by_id)
    accepted = sum(decision.status == "accept" for decision in decision_by_id.values())
    elapsed = review_time
    if elapsed is None and started_at is not None and ended_at is not None:
        elapsed = max(0.0, (ended_at - started_at).total_seconds())
    if elapsed is None:
        elapsed = result.review_time

    return {
        **sections,
        "accepted_suggestions": [
            item["suggested_fix"]
            for item in sections["critical"] + sections["medium"]
            if item["decision"] == "accept" and item["suggested_fix"]
        ],
        "accuracy": round((accepted / total_reviewed * 100) if total_reviewed else 0.0, 2),
        "review_time": round(float(elapsed), 2),
    }


def _report_findings(
    findings: list[ReviewFinding],
    severity: str,
    decisions: dict[str, HumanDecision],
) -> list[dict]:
    report_items: list[dict] = []
    for index, finding in enumerate(findings):
        if finding.severity.lower() != severity:
            continue
        issue_id = issue_id_for(finding, index)
        decision = decisions.get(issue_id)
        report_items.append(
            {
                "issue_id": issue_id,
                "line": finding.line,
                "issue": finding.title,
                "description": finding.description,
                "suggested_fix": finding.suggested_fix,
                "decision": decision.status if decision else "pending",
                "reviewer_note": decision.reviewer_note if decision else "",
            }
        )
    return report_items