from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ..utils.schema import ReviewFinding, ReviewResult

VALID_STATUSES = {"accept", "reject", "modify"}


@dataclass
class HumanDecision:
    issue_id: str
    status: str
    reviewer_note: str = ""

    def __post_init__(self) -> None:
        self.issue_id = str(self.issue_id).strip()
        self.status = str(self.status).strip().lower()
        self.reviewer_note = str(self.reviewer_note).strip()
        if not self.issue_id:
            raise ValueError("issue_id is required")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(VALID_STATUSES))}")


def issue_id_for(finding: ReviewFinding, index: int) -> str:
    """Return the stable ID used by the CLI and report for a finding."""
    return finding.issue_id or f"issue-{index + 1:03d}"


def save_decisions(decisions: Iterable[HumanDecision], file_path: str | Path) -> None:
    """Write validated decisions as a JSON array."""
    payload = [asdict(decision) for decision in decisions]
    Path(file_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_decisions(file_path: str | Path) -> list[HumanDecision]:
    """Load and validate decisions from a JSON array."""
    payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("decision log must contain a JSON array")
    return [HumanDecision(**item) for item in payload]


def review_findings_cli(findings: Iterable[ReviewFinding], input_fn=input, output_fn=print) -> list[HumanDecision]:
    """Collect decisions for findings through a small command-line prompt."""
    decisions: list[HumanDecision] = []
    for index, finding in enumerate(findings):
        issue_id = issue_id_for(finding, index)
        output_fn(f"\n{issue_id}: {finding.title} (line {finding.line}, {finding.severity})")
        output_fn(finding.description)
        if finding.suggested_fix:
            output_fn(f"Suggested fix: {finding.suggested_fix}")
        while True:
            status = input_fn("Decision [accept/reject/modify]: ").strip().lower()
            if status in VALID_STATUSES:
                break
            output_fn("Please enter accept, reject, or modify.")
        note = input_fn("Reviewer note (optional): ")
        decisions.append(HumanDecision(issue_id, status, note))
    return decisions


def apply_human_decisions(result: ReviewResult, decisions: dict) -> ReviewResult:
    """Apply human decisions to review findings."""
    for index, finding in enumerate(result.findings):
        finding.issue_id = issue_id_for(finding, index)
        decision = decisions.get(finding.issue_id, decisions.get(finding.title))
        if isinstance(decision, HumanDecision):
            status = decision.status
        else:
            status = decision
        if status in VALID_STATUSES:
            finding.accepted = status == "accept"
            if status == "modify":
                finding.accepted = None
    return result