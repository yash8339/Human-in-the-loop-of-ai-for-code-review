from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def _request_llm_review(code: str, language: str = "python") -> List[Dict[str, Any]]:
    """Request structured review findings from an LLM if an API key is configured."""
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return []

    prompt = (
        f"You are a secure code reviewer. Review the following {language} code and return a JSON array of objects "
        f"with fields line, issue_type, description, suggested_fix. Only return valid JSON.\n\nCode:\n{code}"
    )

    try:
        import requests

        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]}
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        return []

    return []


def run_static_analysis(file_path: str, language: str = "python", analyzer: str = "semgrep") -> List[Dict[str, Any]]:
    """Run the selected static analyzer on the given file and return structured findings."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if language.lower() != "python":
        return []

    analyzer_name = (analyzer or "semgrep").strip().lower()
    if analyzer_name not in {"semgrep", "bandit"}:
        analyzer_name = "semgrep"

    try:
        if analyzer_name == "bandit":
            result = subprocess.run(
                [sys.executable, "-m", "bandit", "-r", str(path), "-f", "json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            payload = json.loads(result.stdout or "{}")
            findings = []
            for issue in payload.get("results", []):
                findings.append(
                    {
                        "line": issue.get("line_number") or 0,
                        "rule_id": issue.get("test_id") or "B000",
                        "severity": (issue.get("issue_severity") or "low").lower(),
                        "message": issue.get("issue_text") or "Bandit finding",
                    }
                )
            return findings

        semgrep_cli = str(Path(sys.executable).parent / "Scripts" / "semgrep.exe")
        if not Path(semgrep_cli).exists():
            semgrep_cli = str(Path(sys.executable).parent / "semgrep.exe")
        result = subprocess.run(
            [semgrep_cli, "scan", "--json", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        payload = json.loads(result.stdout or "{}")
        findings = []
        for issue in payload.get("results", []):
            extra = issue.get("extra", {})
            findings.append(
                {
                    "line": issue.get("start", {}).get("line") or 0,
                    "rule_id": extra.get("rule_id") or "semgrep-rule",
                    "severity": (extra.get("severity") or "info").lower(),
                    "message": extra.get("message") or "Semgrep finding",
                }
            )
        return findings
    except (json.JSONDecodeError, ValueError, FileNotFoundError):
        return []


def run_ai_review(file_path: str, language: str = "python") -> List[Dict[str, Any]]:
    """Generate structured AI review findings from the file content."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    content = path.read_text(encoding="utf-8", errors="replace")
    if language.lower() != "python":
        return []

    llm_findings = _request_llm_review(content, language=language)
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


def review_file(file_path: str, language: str = "python", analyzer: str = "semgrep") -> Dict[str, Any]:
    """Run both reviewer modules and return a combined result."""
    return {
        "static_analysis": run_static_analysis(file_path=file_path, language=language, analyzer=analyzer),
        "ai_review": run_ai_review(file_path=file_path, language=language),
    }
