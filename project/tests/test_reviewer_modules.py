from pathlib import Path

from project.src.reviewer_modules import run_ai_review, run_static_analysis

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_static_analysis_detects_unsafe_patterns():
    findings = run_static_analysis(file_path=str(FIXTURES_DIR / "unsafe_code.py"), language="python", analyzer="semgrep")

    assert findings
    assert all({"line", "rule_id", "severity", "message"}.issubset(finding) for finding in findings)
    assert any(finding["rule_id"] for finding in findings)


def test_ai_review_returns_structured_findings():
    findings = run_ai_review(file_path=str(FIXTURES_DIR / "dynamic_code.py"), language="python")

    assert findings
    assert all({"line", "issue_type", "description", "suggested_fix"}.issubset(finding) for finding in findings)
    assert any(finding["issue_type"] == "dynamic-execution" for finding in findings)


def test_ai_review_uses_llm_response_when_available(monkeypatch, tmp_path):
    file_path = tmp_path / "sample.py"
    file_path.write_text("import os\nos.system('ls')\n", encoding="utf-8")

    def fake_request(code, language):
        return [
            {
                "line": 2,
                "issue_type": "command-execution",
                "description": "The code executes a shell command.",
                "suggested_fix": "Use a safer API.",
            }
        ]

    monkeypatch.setattr("project.src.reviewer_modules._request_llm_review", fake_request, raising=False)

    findings = run_ai_review(file_path=str(file_path), language="python")

    assert findings[0]["issue_type"] == "command-execution"
    assert findings[0]["suggested_fix"] == "Use a safer API."


def test_static_analysis_returns_empty_for_safe_code():
    findings = run_static_analysis(file_path=str(FIXTURES_DIR / "benign_code.py"), language="python")

    assert findings == []


def test_static_analysis_uses_selected_analyzer_rule_ids():
    findings_semgrep = run_static_analysis(file_path=str(FIXTURES_DIR / "unsafe_code.py"), language="python", analyzer="semgrep")
    findings_bandit = run_static_analysis(file_path=str(FIXTURES_DIR / "unsafe_code.py"), language="python", analyzer="bandit")

    assert findings_semgrep
    assert findings_bandit
    assert findings_semgrep[0]["rule_id"] != findings_bandit[0]["rule_id"]


def test_static_analysis_handles_windows_cp1252_decode_issue(monkeypatch, tmp_path):
    file_path = tmp_path / "sample.py"
    file_path.write_text("print('hi')\n", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        if kwargs.get("text") is True and kwargs.get("encoding") is None:
            raise UnicodeDecodeError("cp1252", b"\x90", 0, 1, "character maps to <undefined>")
        return type(
            "Result",
            (),
            {"stdout": '{"results":[{"extra":{"rule_id":"R001","severity":"high","message":"unsafe"},"start":{"line":1}}]}', "stderr": ""},
        )()

    monkeypatch.setattr("project.src.reviewer_modules.subprocess.run", fake_run)

    findings = run_static_analysis(file_path=str(file_path), language="python", analyzer="semgrep")

    assert findings
    assert findings[0]["rule_id"] == "R001"
    assert findings[0]["message"] == "unsafe"
