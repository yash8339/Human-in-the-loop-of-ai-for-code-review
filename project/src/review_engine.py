from typing import List
from .models import ReviewFinding, ReviewResult


def analyze_code(code: str, language: str = "python") -> ReviewResult:
    """Create a simple heuristic review result for demonstration purposes."""
    findings: List[ReviewFinding] = []

    if "import os" in code or "os.system" in code:
        findings.append(
            ReviewFinding(
                title="Potential command injection",
                description="Using OS commands directly can introduce command injection risk.",
                severity="high",
                confidence=0.91,
                source="ai",
            )
        )

    if "eval(" in code or "exec(" in code:
        findings.append(
            ReviewFinding(
                title="Dynamic code execution",
                description="Dynamic execution may allow unsafe code execution.",
                severity="medium",
                confidence=0.86,
                source="static",
            )
        )

    if not findings:
        findings.append(
            ReviewFinding(
                title="No obvious issues detected",
                description="The sample code appears structurally sound.",
                severity="low",
                confidence=0.55,
                source="ai",
            )
        )

    summary = f"Analyzed {language} code and produced {len(findings)} review findings."
    result = ReviewResult(findings=findings, summary=summary)
    result.accuracy = 0.84
    result.precision = 0.78
    result.recall = 0.81
    result.false_positive_rate = 0.12
    result.review_time = 1.8
    return result


def apply_human_decisions(result: ReviewResult, decisions: dict) -> ReviewResult:
    """Apply human decisions to review findings."""
    for finding in result.findings:
        key = finding.title
        if key in decisions:
            finding.accepted = decisions[key] == "accept"
            if decisions[key] == "reject":
                finding.accepted = False
            elif decisions[key] == "modify":
                finding.accepted = None
    return result
