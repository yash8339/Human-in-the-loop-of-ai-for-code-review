from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from .python_rules import run_python_rules


def run_static_analysis(file_path: str, language: str = "python", analyzer: str = "semgrep") -> List[Dict[str, Any]]:
    """Run Semgrep or Bandit and return findings in the common static schema."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if language.lower() != "python":
        return []

    analyzer_name = (analyzer or "semgrep").strip().lower()
    if analyzer_name not in {"semgrep", "bandit"}:
        analyzer_name = "semgrep"

    local_findings = run_python_rules(path)
    try:
        if analyzer_name == "bandit":
            result = subprocess.run(
                [sys.executable, "-m", "bandit", "-r", str(path), "-f", "json"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            payload = json.loads(result.stdout or "{}")
            external_findings = [
                {"line": issue.get("line_number") or 0, "rule_id": issue.get("test_id") or "B000",
                 "severity": (issue.get("issue_severity") or "low").lower(),
                 "message": issue.get("issue_text") or "Bandit finding"}
                for issue in payload.get("results", [])
            ]
            return _merge_findings(external_findings, local_findings)

        semgrep_command = shutil.which("semgrep") or "semgrep"
        result = subprocess.run(
            [semgrep_command, "scan", "--json", "--config", "auto", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        payload = json.loads(result.stdout or "{}")
        external_findings = [
            {"line": issue.get("start", {}).get("line") or 0,
             "rule_id": issue.get("extra", {}).get("rule_id") or "semgrep-rule",
             "severity": (issue.get("extra", {}).get("severity") or "info").lower(),
             "message": issue.get("extra", {}).get("message") or "Semgrep finding"}
            for issue in payload.get("results", [])
        ]
        return _merge_findings(external_findings, local_findings)
    except (json.JSONDecodeError, ValueError, FileNotFoundError, OSError):
        return local_findings


def _merge_findings(external_findings: List[Dict[str, Any]], local_findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged = {(finding["line"], finding["rule_id"]): finding for finding in external_findings}
    for finding in local_findings:
        merged.setdefault((finding["line"], finding["rule_id"]), finding)
    return list(merged.values())