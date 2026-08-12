from project.src.review_engine import analyze_code, apply_human_decisions
from project.src.evaluation import compute_metrics
from project.src.models import ReviewResult


def test_analyze_code_returns_findings():
    code = "import os\nprint(os.system('ls'))"
    result = analyze_code(code, language="python")
    assert len(result.findings) >= 1
    assert result.summary


def test_apply_human_decisions_updates_findings():
    result = analyze_code("import os\nprint(os.system('ls'))", language="python")
    decisions = {result.findings[0].title: "accept"}
    updated = apply_human_decisions(result, decisions)
    assert updated.findings[0].accepted is True


def test_compute_metrics_returns_values():
    result = ReviewResult()
    compute_metrics(result, true_positives=3, false_positives=1)
    assert 0 <= result.accuracy <= 1
    assert 0 <= result.precision <= 1
    assert 0 <= result.recall <= 1
    assert 0 <= result.false_positive_rate <= 1


def test_analyze_code_uses_module_titles_for_structured_findings():
    result = analyze_code("exec('print(1)')", language="python")
    assert any(finding.title == "dynamic-execution" for finding in result.findings)
