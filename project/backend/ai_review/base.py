from __future__ import annotations

import json
from typing import Any, Dict, List
from urllib import request


def build_prompt(code: str, language: str) -> str:
    return (
        f"You are a secure code reviewer. Review the following {language} code. "
        "Return only a valid JSON object with a `findings` array. Every finding must contain exactly: "
        "line (integer), issue_type (short string), description (string), and suggested_fix (string). "
        "Use the source line where the issue occurs and return {\"findings\": []} when there are no issues.\n\n"
        f"Code:\n{code}"
    )


def post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    http_request = request.Request(url, data=body, headers=headers, method="POST")
    with request.urlopen(http_request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_response(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    cleaned = content.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    parsed = json.loads(cleaned)
    if isinstance(parsed, dict) and isinstance(parsed.get("findings"), list):
        return parsed["findings"]
    return parsed


def normalize_findings(findings: Any) -> List[Dict[str, Any]]:
    if not isinstance(findings, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        try:
            line = int(finding["line"])
        except (KeyError, TypeError, ValueError):
            continue
        fields = ("issue_type", "description", "suggested_fix")
        if line < 1 or not all(isinstance(finding.get(field), str) and finding[field].strip() for field in fields):
            continue
        normalized.append(
            {
                "line": line,
                "issue_type": finding["issue_type"].strip(),
                "description": finding["description"].strip(),
                "suggested_fix": finding["suggested_fix"].strip(),
            }
        )
    return normalized