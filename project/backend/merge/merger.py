from __future__ import annotations

import re
from typing import Any, Dict, List


def normalize_finding(finding: Dict[str, Any], source: str = "unknown") -> Dict[str, Any]:
    """Convert a tool-specific finding into a common schema."""
    category = (
        finding.get("title")
        or finding.get("rule_id")
        or finding.get("issue_type")
        or "review-finding"
    )
    description = (
        finding.get("description")
        or finding.get("message")
        or "No description provided."
    )
    line = finding.get("line") or finding.get("line_number") or 0
    severity = finding.get("severity") or "medium"
    source_tool = (source or "unknown").strip().lower() or "unknown"
    return {
        "source_tool": source_tool,
        "category": str(category),
        "line": int(line),
        "description": str(description),
        "severity": str(severity).lower(),
        "raw": finding,
        "tool": source_tool,
        "title": str(category),
    }


def _tokenize(text: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if token}


def _canonicalize_tokens(tokens: set[str]) -> set[str]:
    canonical: set[str] = set()
    for token in tokens:
        if token in {"subprocess", "shell", "command", "commands", "execute", "exec", "execution", "executing"}:
            canonical.add("command-execution")
        elif token in {"dynamic", "eval"}:
            canonical.add("dynamic-execution")
        elif token in {"risk", "dangerous", "unsafe", "vulnerable", "injection"}:
            canonical.add("security-risk")
        else:
            canonical.add(token)
    return canonical


def findings_match(left: Dict[str, Any], right: Dict[str, Any], *, threshold: float = 0.4) -> bool:
    """Return True when two normalized findings likely refer to the same issue."""
    left_line = int(left.get("line") or 0)
    right_line = int(right.get("line") or 0)
    if left_line and right_line and left_line != right_line:
        return False

    left_tokens = _canonicalize_tokens(_tokenize(str(left.get("category", left.get("title", ""))) + " " + str(left.get("description", ""))))
    right_tokens = _canonicalize_tokens(_tokenize(str(right.get("category", right.get("title", ""))) + " " + str(right.get("description", ""))))
    if not left_tokens or not right_tokens:
        return left.get("title") == right.get("title")

    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    similarity = len(overlap) / len(union) if union else 0.0
    return similarity >= threshold or bool(overlap & {"command-execution", "dynamic-execution", "security-risk"})


def build_comparison_table(findings_by_source: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Create a reusable comparison table for findings from multiple tools."""
    normalized_rows: List[Dict[str, Any]] = []
    for source_name, findings in findings_by_source.items():
        for finding in findings:
            normalized = normalize_finding(finding, source=source_name)
            normalized_rows.append(normalized)

    grouped: List[Dict[str, Any]] = []
    for row in normalized_rows:
        matched = False
        for existing in grouped:
            if findings_match(existing["base"], row):
                column_name = _column_name_for_source(row["tool"])
                existing[column_name] = row["description"]
                matched = True
                break
        if not matched:
            row_payload = {
                "issue": row["category"],
                "line": row["line"],
                "category": row["category"],
                "base": row,
                "chatgpt": "",
                "semgrep": "",
                "bandit": "",
            }
            row_payload[_column_name_for_source(row["tool"])] = row["description"]
            grouped.append(row_payload)

    return grouped


def _column_name_for_source(source: str) -> str:
    normalized = (source or "").strip().lower()
    if normalized in {"gpt", "llm", "ai", "chatgpt"}:
        return "chatgpt"
    if normalized in {"semgrep", "sg"}:
        return "semgrep"
    if normalized in {"bandit", "b"}:
        return "bandit"
    return normalized or "unknown"
