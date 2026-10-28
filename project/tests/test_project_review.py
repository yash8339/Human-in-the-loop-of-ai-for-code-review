import threading
import time

import pytest

from project.backend.project_review import (
    MAX_ANALYSIS_WORKERS,
    MAX_FILE_SIZE,
    MAX_PROJECT_SIZE,
    analyze_project_files,
    normalize_project_path,
    prepare_project_files,
)
from project.backend.utils.schema import ReviewFinding, ReviewResult


def test_prepare_project_files_preserves_tree_and_skips_unsupported_files():
    files = prepare_project_files(
        [
            ("sample-app/src/main.py", b"print('hello')\n"),
            ("sample-app/assets/logo.png", b"\x00binary"),
            ("sample-app/README.md", b"notes"),
        ]
    )

    assert files[0].relative_path == "sample-app/src/main.py"
    assert files[0].supported is True
    assert files[1].supported is False
    assert files[1].reason == "Unsupported file type"
    assert files[2].supported is False


@pytest.mark.parametrize("path", ["../outside.py", "/root.py", "C:/outside.py", "src\\outside.py"])
def test_normalize_project_path_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        normalize_project_path(path)


def test_prepare_project_files_rejects_duplicate_paths():
    with pytest.raises(ValueError, match="duplicate"):
        prepare_project_files([("src/app.py", b"one"), ("src/app.py", b"two")])


def test_prepare_project_files_accepts_projects_larger_than_previous_limit():
    file_content = b"x" * (2 * 1024 * 1024)
    uploaded_files = [
        (f"src/file_{index}.{'py' if index == 0 else 'md'}", file_content)
        for index in range(2)
    ]

    files = prepare_project_files(uploaded_files)

    assert MAX_PROJECT_SIZE == 500 * 1024 * 1024
    assert MAX_FILE_SIZE == 10 * 1024 * 1024
    assert len(files) == 2
    assert len(files[0].content.encode("utf-8")) == len(file_content)


def test_prepare_project_files_rejects_file_over_10_mib():
    with pytest.raises(ValueError, match="10 MiB per-file limit"):
        prepare_project_files([("src/large.py", b"x" * (MAX_FILE_SIZE + 1))])


def test_prepare_project_files_accepts_500_files():
    files = prepare_project_files(
        [(f"src/file_{index}.py", b"pass") for index in range(500)]
    )

    assert len(files) == 500


def test_prepare_project_files_rejects_more_than_500_files():
    with pytest.raises(ValueError, match="at most 500 files"):
        prepare_project_files(
            [(f"src/file_{index}.py", b"pass") for index in range(501)]
        )


def test_project_analysis_preserves_paths_and_merges_matching_tool_findings(monkeypatch):
    def fake_analyze_file(path, **kwargs):
        assert path.suffix == ".py"
        return ReviewResult(
            findings=[
                ReviewFinding(
                    title="command-execution",
                    description="Shell execution may be unsafe.",
                    severity="high",
                    confidence=0.9,
                    source="static",
                    line=4,
                ),
                ReviewFinding(
                    title="command-execution",
                    description="Shell command may permit injection.",
                    severity="medium",
                    confidence=0.8,
                    source="ai",
                    line=4,
                    suggested_fix="Use a safe API.",
                ),
            ]
        )

    monkeypatch.setattr("project.backend.project_review.analyze_file", fake_analyze_file)
    findings = analyze_project_files(
        [
            {
                "relative_path": "app/worker.py",
                "content": "source text",
                "supported": True,
            }
        ]
    )

    assert len(findings) == 1
    assert findings[0].filename == "app/worker.py"
    assert findings[0].source == "ai+static"
    assert findings[0].suggested_fix == "Use a safe API."


def test_project_analysis_processes_files_concurrently_with_a_bounded_worker_count(monkeypatch):
    active_workers = 0
    peak_workers = 0
    lock = threading.Lock()

    def fake_analyze_file(path, **kwargs):
        nonlocal active_workers, peak_workers
        with lock:
            active_workers += 1
            peak_workers = max(peak_workers, active_workers)
        time.sleep(0.03)
        with lock:
            active_workers -= 1
        return ReviewResult(
            findings=[
                ReviewFinding(
                    title="test-finding",
                    description="Test finding.",
                    severity="low",
                    confidence=0.8,
                    source="static",
                    line=1,
                )
            ]
        )

    monkeypatch.setattr("project.backend.project_review.analyze_file", fake_analyze_file)
    findings = analyze_project_files(
        [
            {"relative_path": f"src/file_{index}.py", "content": "pass", "supported": True}
            for index in range(MAX_ANALYSIS_WORKERS * 2)
        ]
    )

    assert peak_workers > 1
    assert peak_workers <= MAX_ANALYSIS_WORKERS
    assert [finding.filename for finding in findings] == [
        f"src/file_{index}.py" for index in range(MAX_ANALYSIS_WORKERS * 2)
    ]
