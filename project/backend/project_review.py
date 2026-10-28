from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .merge.merger import findings_match
from .review_engine import analyze_file
from .utils.schema import ReviewFinding

MAX_PROJECT_FILES = 100
MAX_FILE_SIZE = 1024 * 1024
MAX_PROJECT_SIZE = 10 * 1024 * 1024
MAX_ANALYSIS_WORKERS = 4

SOURCE_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
}


@dataclass(frozen=True)
class ProjectFile:
    relative_path: str
    content: str
    supported: bool
    reason: str = ""


def normalize_project_path(raw_path: str) -> str:
    """Validate and normalize a browser-provided relative path."""
    if not raw_path or "\\" in raw_path or ":" in raw_path:
        raise ValueError("Invalid project file path.")
    if any(ord(character) < 32 for character in raw_path):
        raise ValueError("Project paths cannot contain control characters.")
    parts = raw_path.split("/")
    if any(part in {"", ".", ".."} or part.endswith((" ", ".")) for part in parts):
        raise ValueError("Project file paths must stay inside the selected folder.")
    path = PurePosixPath(*parts)
    if path.is_absolute() or len(path.as_posix()) > 500:
        raise ValueError("Invalid or overly long project file path.")
    return path.as_posix()


def prepare_project_files(uploaded_files: Iterable[tuple[str, bytes]]) -> list[ProjectFile]:
    """Validate a project upload and retain only supported UTF-8 source contents."""
    records: list[ProjectFile] = []
    seen_paths: set[str] = set()
    total_size = 0

    for index, (raw_path, raw_content) in enumerate(uploaded_files):
        if index >= MAX_PROJECT_FILES:
            raise ValueError(f"A project can contain at most {MAX_PROJECT_FILES} files.")
        relative_path = normalize_project_path(raw_path)
        path_key = relative_path.casefold()
        if path_key in seen_paths:
            raise ValueError("The selection contains duplicate file paths.")
        seen_paths.add(path_key)

        content_bytes = raw_content or b""
        total_size += len(content_bytes)
        if len(content_bytes) > MAX_FILE_SIZE:
            raise ValueError("A selected file exceeds the 1 MiB per-file limit.")
        if total_size > MAX_PROJECT_SIZE:
            raise ValueError("The project exceeds the 10 MiB total upload limit.")

        language = SOURCE_LANGUAGES.get(Path(relative_path).suffix.lower())
        if language is None:
            records.append(ProjectFile(relative_path, "", False, "Unsupported file type"))
            continue
        if b"\x00" in content_bytes:
            records.append(ProjectFile(relative_path, "", False, "Binary files are not analyzed"))
            continue
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            records.append(ProjectFile(relative_path, "", False, "File is not valid UTF-8 text"))
            continue
        records.append(ProjectFile(relative_path, content, True))

    if not records:
        raise ValueError("Select at least one file to upload.")
    if not any(record.supported for record in records):
        raise ValueError("The selection contains no supported source files.")
    return records


def analyze_project_files(
    files: Iterable[dict[str, Any]],
    *,
    analyzer: str = "semgrep",
    model: str = "OpenAI",
) -> list[ReviewFinding]:
    """Analyze supported files without executing them, preserving their relative paths."""
    with tempfile.TemporaryDirectory(prefix="code-review-project-") as temp_dir:
        root = Path(temp_dir)
        staged_files: list[tuple[str, Path, str, str]] = []
        for project_file in files:
            relative_path = normalize_project_path(str(project_file["relative_path"]))
            if not project_file["supported"]:
                continue
            language = SOURCE_LANGUAGES.get(Path(relative_path).suffix.lower())
            if language is None:
                continue
            file_analyzer = analyzer if language == "python" else "semgrep"

            source_path = root.joinpath(*PurePosixPath(relative_path).parts)
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(str(project_file["content"]), encoding="utf-8")
            staged_files.append((relative_path, source_path, language, file_analyzer))

        def analyze_staged_file(file_info: tuple[str, Path, str, str]) -> list[ReviewFinding]:
            relative_path, source_path, language, file_analyzer = file_info
            result = analyze_file(
                source_path,
                language=language,
                analyzer=file_analyzer,
                model=model,
            )
            for finding in result.findings:
                finding.filename = relative_path
            return result.findings

        worker_count = min(MAX_ANALYSIS_WORKERS, len(staged_files))
        if worker_count == 0:
            return []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            file_findings = executor.map(analyze_staged_file, staged_files)

        findings: list[ReviewFinding] = []
        for findings_for_file in file_findings:
            for finding in findings_for_file:
                _append_or_merge(findings, finding)
    return findings


def _append_or_merge(findings: list[ReviewFinding], finding: ReviewFinding) -> None:
    candidate = {
        "line": finding.line,
        "category": finding.title,
        "description": finding.description,
    }
    for existing in findings:
        if existing.filename != finding.filename:
            continue
        current = {
            "line": existing.line,
            "category": existing.title,
            "description": existing.description,
        }
        if not findings_match(current, candidate):
            continue
        sources = set(existing.source.split("+")) | set(finding.source.split("+"))
        existing.source = "+".join(sorted(sources))
        existing.confidence = max(existing.confidence, finding.confidence)
        if finding.suggested_fix and not existing.suggested_fix:
            existing.suggested_fix = finding.suggested_fix
        if len(finding.description) > len(existing.description):
            existing.description = finding.description
        if finding.severity.lower() in {"critical", "high"}:
            existing.severity = finding.severity
        return
    findings.append(finding)
