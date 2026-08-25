from project.backend.evaluation import classify_rejection, mann_whitney_u, quality_metrics
from project.backend.evaluation_runner import EvaluationCase, evaluate_test_set


def test_rejection_reasons_are_categorized():
    assert classify_rejection("This is a false positive") == "Incorrect"
    assert classify_rejection("Use an alternative fix") == "Alternative Fix"
    assert classify_rejection("Defer this until later") == "Deferred"
    assert classify_rejection("No clear reason") == "Other"


def test_quality_metrics_reports_before_after_delta(tmp_path):
    before = tmp_path / "before.py"
    after = tmp_path / "after.py"
    before.write_text("def f(value):\n    if value:\n        return value\n    return 0\n", encoding="utf-8")
    after.write_text("def f(value):\n    return value\n", encoding="utf-8")

    metrics = quality_metrics(before, after)

    assert metrics["size_delta"] < 0
    assert metrics["complexity_delta"] < 0


def test_mann_whitney_requires_enough_data():
    result = mann_whitney_u({"AI-only": [1.0], "Combined": [2.0]})

    assert result["available"] is False


def test_evaluation_runs_all_conditions_and_logs_each_case(monkeypatch, tmp_path):
    source = tmp_path / "sample.py"
    source.write_text("exec('print(1)')\n", encoding="utf-8")
    expected = [{"line": 1, "issue_type": "dynamic-execution"}]

    monkeypatch.setattr(
        "project.backend.evaluation_runner.run_ai_review",
        lambda path, model="OpenAI": [{"line": 1, "issue_type": "dynamic-execution", "description": "dynamic"}],
    )
    monkeypatch.setattr(
        "project.backend.evaluation_runner.run_static_analysis",
        lambda path, analyzer="semgrep": [{"line": 1, "rule_id": "dynamic-execution", "message": "dynamic", "severity": "high"}],
    )

    report = evaluate_test_set([
        EvaluationCase(
            str(source),
            expected=expected,
            human_decisions=[{"issue_id": "issue-001", "status": "accept", "reviewer_note": "Confirmed"}],
        )
    ])

    assert set(report["conditions"]) == {"Human-only", "AI-only", "Static-analysis-only", "Combined"}
    assert report["conditions"]["Combined"]["case_results"][0]["bugs_found"] == 1
    assert report["conditions"]["AI-only"]["false_positives"] == 0
    assert report["conditions"]["Human-only"]["adoption_rate"] == 1.0
    assert report["conditions"]["Human-only"]["review_time"] == 0.0
    assert report["rejection_reasons"]["Other"] == 0


def test_evaluation_supports_condition_adoption_time_and_quality(monkeypatch, tmp_path):
    source = tmp_path / "before.py"
    fixed = tmp_path / "after.py"
    source.write_text("def f(value):\n    if value:\n        return value\n    return 0\n", encoding="utf-8")
    fixed.write_text("def f(value):\n    return value\n", encoding="utf-8")

    monkeypatch.setattr(
        "project.backend.evaluation_runner.run_ai_review",
        lambda path, model="OpenAI": [{"line": 1, "issue_type": "issue-a", "description": "a", "suggested_fix": "fix"}],
    )
    monkeypatch.setattr(
        "project.backend.evaluation_runner.run_static_analysis",
        lambda path, analyzer="semgrep": [{"line": 1, "rule_id": "issue-a", "message": "a", "severity": "high"}],
    )

    report = evaluate_test_set([EvaluationCase(
        str(source), fixed_path=str(fixed), human_review_time=2.5,
        expected=[{"line": 1, "issue_type": "issue-a"}, {"line": 2, "issue_type": "issue-b"}],
        decisions_by_condition={
            "Human-only": [{"status": "accept"}, {"status": "reject"}],
            "AI-only": [{"status": "accept"}],
            "Static-analysis-only": [{"status": "reject"}],
            "Combined": [{"status": "accept"}],
        },
    )])

    assert report["conditions"]["Human-only"]["review_time"] == 2.5
    assert report["conditions"]["Human-only"]["adoption_rate"] == 0.5
    assert report["conditions"]["AI-only"]["adoption_rate"] == 1.0
    assert report["conditions"]["Static-analysis-only"]["adoption_rate"] == 0.0
    assert report["conditions"]["Combined"]["adoption_rate"] == 1.0
    assert report["quality_delta"]["size_delta"] < 0
    assert report["quality_delta"]["complexity_delta"] < 0