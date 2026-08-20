from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from . import claude, gemini, groq, openai


def _request_llm_review(code: str, language: str = "python") -> List[Dict[str, Any]]:
    """Request an OpenAI-compatible review for backwards compatibility."""
    return openai.review(code, language)


def _parse_json_response(content: Any) -> Any:
    """Parse an LLM response, including JSON wrapped in a markdown code fence."""
    if not isinstance(content, str):
        return content
    cleaned = content.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    parsed = json.loads(cleaned)
    if isinstance(parsed, dict) and isinstance(parsed.get("findings"), list):
        return parsed["findings"]
    return parsed


def _normalize_ai_findings(findings: Any) -> List[Dict[str, Any]]:
    """Keep only findings that satisfy the public AI review schema."""
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
        if line < 1:
            continue
        fields = ("issue_type", "description", "suggested_fix")
        if not all(isinstance(finding.get(field), str) and finding[field].strip() for field in fields):
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


def _request_provider_review(code: str, language: str, model: str) -> List[Dict[str, Any]]:
    providers = {
        "gemini": gemini.review,
        "openai": openai.review,
        "chatgpt": openai.review,
        "groq": groq.review,
        "claude": claude.review,
    }
    provider = providers.get((model or "openai").strip().lower(), openai.review)
    return provider(code, language)


def run_ai_review(file_path: str, language: str = "python", model: str = "OpenAI") -> List[Dict[str, Any]]:
    """Generate structured AI review findings from the file content."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    content = path.read_text(encoding="utf-8", errors="replace")
    if language.lower() != "python":
        return []

    if (model or "openai").strip().lower() in {"openai", "chatgpt"}:
        provider_findings = _request_llm_review(content, language=language)
    else:
        provider_findings = _request_provider_review(content, language, model)
    llm_findings = _normalize_ai_findings(provider_findings)
    if llm_findings:
        return llm_findings

    findings: List[Dict[str, Any]] = []
    lines = content.splitlines()
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if "exec(" in stripped or "eval(" in stripped:
            findings.append(
                {
                    "line": index,
                    "issue_type": "dynamic-execution",
                    "description": "Dynamic execution can make the code harder to reason about and may introduce security risks.",
                    "suggested_fix": "Replace dynamic execution with a safer explicit implementation.",
                }
            )
        elif "os.system" in stripped or "subprocess" in stripped:
            findings.append(
                {
                    "line": index,
                    "issue_type": "command-execution",
                    "description": "Executing shell commands directly can be vulnerable to injection.",
                    "suggested_fix": "Use safe APIs or validated input instead of direct command execution.",
                }
            )

    return findings


def review_file(file_path: str, language: str = "python") -> List[Dict[str, Any]]:
    """Run the AI reviewer directly on a source file."""
    return run_ai_review(file_path=file_path, language=language)
