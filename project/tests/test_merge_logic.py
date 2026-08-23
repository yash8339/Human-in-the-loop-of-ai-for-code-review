from project.backend.merge.merger import build_comparison_table, findings_match, normalize_finding


def test_normalize_finding_uses_common_schema():
    finding = {
        "line": 4,
        "issue_type": "dynamic-execution",
        "description": "Dynamic execution can be risky.",
        "suggested_fix": "Use explicit logic instead.",
    }

    normalized = normalize_finding(finding, source="ai")

    assert normalized["tool"] == "ai"
    assert normalized["source_tool"] == "ai"
    assert normalized["category"] == "dynamic-execution"
    assert normalized["title"] == "dynamic-execution"
    assert normalized["line"] == 4
    assert normalized["description"] == "Dynamic execution can be risky."


def test_findings_match_detects_same_issue_across_tools():
    semgrep_finding = normalize_finding(
        {
            "line": 7,
            "rule_id": "python.lang.security.audit.dangerous-subprocess-use",
            "message": "Found subprocess usage.",
            "severity": "high",
        },
        source="semgrep",
    )
    ai_finding = normalize_finding(
        {
            "line": 7,
            "issue_type": "command-execution",
            "description": "Executing shell commands directly can be vulnerable to injection.",
            "suggested_fix": "Use safe APIs instead.",
        },
        source="ai",
    )

    assert findings_match(semgrep_finding, ai_finding)


def test_findings_match_rejects_different_lines():
    first = normalize_finding(
        {"line": 7, "issue_type": "command-execution", "description": "shell command"},
        source="chatgpt",
    )
    second = normalize_finding(
        {"line": 10, "rule_id": "command-execution", "message": "shell command"},
        source="bandit",
    )

    assert not findings_match(first, second)


def test_build_comparison_table_returns_tool_columns():
    findings_by_source = {
        "chatgpt": [
            {
                "line": 3,
                "issue_type": "dynamic-execution",
                "description": "Dynamic execution can be risky.",
                "suggested_fix": "Use explicit logic instead.",
            }
        ],
        "semgrep": [
            {
                "line": 3,
                "rule_id": "python.lang.security.audit.dangerous-exec",
                "message": "Use of exec detected.",
                "severity": "high",
            }
        ],
        "bandit": [
            {
                "line": 3,
                "rule_id": "B404",
                "message": "Consider possible security risk with subprocess.",
                "severity": "medium",
            }
        ],
    }

    rows = build_comparison_table(findings_by_source)

    assert len(rows) >= 1
    assert rows[0]["issue"]
    assert rows[0]["chatgpt"]
    assert rows[0]["semgrep"]
    assert rows[0]["bandit"]
