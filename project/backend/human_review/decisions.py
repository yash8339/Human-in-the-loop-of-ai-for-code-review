from ..utils.schema import ReviewResult


def apply_human_decisions(result: ReviewResult, decisions: dict) -> ReviewResult:
    """Apply human decisions to review findings."""
    for finding in result.findings:
        if finding.title in decisions:
            finding.accepted = decisions[finding.title] == "accept"
            if decisions[finding.title] == "modify":
                finding.accepted = None
    return result