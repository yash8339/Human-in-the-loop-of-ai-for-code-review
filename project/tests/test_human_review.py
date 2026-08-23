from datetime import datetime, timedelta

import pytest

from project.backend.human_review.decisions import (
    HumanDecision,
    apply_human_decisions,
    load_decisions,
    review_findings_cli,
    save_decisions,
)
from project.backend.human_review.report import generate_final_report
from project.backend.human_review.storage import load_decisions as load_sqlite_decisions, save_decision
from project.backend.utils.schema import ReviewFinding, ReviewResult


def make_result():
    return ReviewResult(
        findings=[
            ReviewFinding(
                title="command-execution",
                description="Shell command uses untrusted input.",
                severity="critical",
                confidence=0.9,
                source="ai",
                issue_id="issue-001",
                line=5,
                suggested_fix="Use a safe API.",
            ),
            ReviewFinding(
                title="weak-validation",
                description="Input is not validated.",
                severity="medium",
                confidence=0.8,
                source="bandit",
                issue_id="issue-002",
                line=8,
                suggested_fix="Validate the input before use.",
            ),
        ]
    )


def test_human_decision_validates_schema():
    decision = HumanDecision("issue-001", "ACCEPT", "Confirmed by reviewer")

    assert decision.status == "accept"
    assert decision.reviewer_note == "Confirmed by reviewer"
    with pytest.raises(ValueError):
        HumanDecision("issue-001", "pending")


def test_decisions_round_trip_as_json(tmp_path):
    path = tmp_path / "decisions.json"
    decisions = [HumanDecision("issue-001", "accept", "Looks correct.")]

    save_decisions(decisions, path)

    assert load_decisions(path) == decisions


def test_decisions_round_trip_in_sqlite(tmp_path):
    path = tmp_path / "human-review.sqlite3"
    decision = HumanDecision("issue-001", "reject", "False positive.")

    save_decision(42, decision, path)

    assert load_sqlite_decisions(42, path) == [decision]


def test_cli_collects_and_validates_decisions():
    answers = iter(["invalid", "modify", "Needs a safer implementation."])
    result = make_result()

    decisions = review_findings_cli(result.findings[:1], input_fn=lambda _: next(answers), output_fn=lambda _: None)

    assert decisions == [HumanDecision("issue-001", "modify", "Needs a safer implementation.")]


def test_apply_human_decisions_uses_issue_id():
    result = make_result()

    apply_human_decisions(result, {"issue-001": HumanDecision("issue-001", "accept")})

    assert result.findings[0].accepted is True


def test_final_report_has_sections_suggestions_accuracy_and_time():
    result = make_result()
    decisions = [
        HumanDecision("issue-001", "accept", "Confirmed."),
        HumanDecision("issue-002", "reject", "Not actionable."),
    ]
    start = datetime(2026, 1, 1, 12, 0, 0)

    report = generate_final_report(result, decisions, started_at=start, ended_at=start + timedelta(seconds=12.345))

    assert report["critical"][0]["decision"] == "accept"
    assert report["medium"][0]["reviewer_note"] == "Not actionable."
    assert report["accepted_suggestions"] == ["Use a safe API."]
    assert report["accuracy"] == 50.0
    assert report["review_time"] == 12.35
