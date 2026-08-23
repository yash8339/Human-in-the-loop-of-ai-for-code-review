from __future__ import annotations

import argparse
from pathlib import Path

from ..ai_review.reviewer import run_ai_review
from ..static_analysis.runner import run_static_analysis
from .decisions import review_findings_cli, save_decisions


def main() -> None:
    parser = argparse.ArgumentParser(description="Review automated findings and save human decisions.")
    parser.add_argument("file", type=Path, help="Python source file to review")
    parser.add_argument("--output", type=Path, default=Path("decisions.json"), help="Decision JSON output path")
    args = parser.parse_args()

    ai_findings = run_ai_review(str(args.file))
    static_findings = run_static_analysis(str(args.file), analyzer="bandit")
    findings = []
    for finding in ai_findings:
        findings.append({
            "line": finding["line"],
            "title": finding["issue_type"],
            "description": finding["description"],
            "severity": "medium",
            "source": "ai",
            "suggested_fix": finding["suggested_fix"],
        })
    for finding in static_findings:
        findings.append({
            "line": finding["line"],
            "title": finding["rule_id"],
            "description": finding["message"],
            "severity": finding["severity"],
            "source": "bandit",
        })

    from ..utils.schema import ReviewFinding

    review_findings = [ReviewFinding(issue_id=f"issue-{index + 1:03d}", **finding) for index, finding in enumerate(findings)]
    decisions = review_findings_cli(review_findings)
    save_decisions(decisions, args.output)
    print(f"Saved {len(decisions)} decisions to {args.output}")


if __name__ == "__main__":
    main()
