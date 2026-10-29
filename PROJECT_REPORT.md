# Human-in-the-Loop AI for Code Review

## Project Report

**Document type:** Software project report  
**Prepared:** 24 November 2026  
**Project repository:** `yash8339/Human-in-the-loop-of-ai-for-code-review`  
**Implementation location:** `project/`

> This report describes the implementation visible in the repository at the time it was prepared. Evaluation figures are taken from the checked-in Phase 4 evaluation artifact and are limited to its small fixture set; they are not claims of production-scale performance.

## Abstract

This report documents a Flask-based code-review application that combines AI-assisted review, static analysis, finding comparison, and human decisions. It supports pasted code, a single source-file upload, and project-folder uploads. Project files retain relative paths during bounded analysis, and findings are presented with source, severity, explanation, location, and suggested fixes where available. Reviewers can accept, reject, or modify eligible findings, with decisions persisted for subsequent reporting. The report describes the architecture, workflow, upload safeguards, technologies, work plan, and current evaluation evidence. The checked-in evaluation output is explicitly treated as preliminary because it comes from a small fixture set; no broad performance or security assurance is inferred from it.

## Contents

1. Introduction
2. Problem Statement
3. Objectives and Scope
4. Literature Review / Technology Survey
5. Proposed Solution and Methodology
6. Tools, Technologies, and Requirements
7. Work Plan
8. Expected Outcomes and Evaluation
9. Conclusion
10. References
11. Appendix A: Running and Testing the Project

## 1. Introduction

Software review is an important quality-control activity. A reviewer must understand the submitted change, identify defects and security risks, judge the context of each observation, and communicate a practical correction. This work can be time-consuming, especially when a submission spans multiple files or a complete project.

Static-analysis tools help by checking source code against rules. They are consistent and useful for known patterns, but their findings may require contextual interpretation and can include false positives. AI-assisted review can produce contextual explanations and suggested fixes, but its output may be incomplete or incorrect. Neither source should be treated as an unquestionable authority.

The Human-in-the-Loop AI for Code Review project combines AI review, static analysis, finding comparison, and reviewer decisions in a web application. It accepts pasted code, a source file, or a project folder. Results are associated with source locations, presented for human assessment, and included in a final report.

The central design principle is that automated systems identify candidate issues while a person retains responsibility for deciding whether each finding is useful.

## 2. Problem Statement

Manual code review can become a bottleneck when reviewers have limited time or when projects contain many files. Reviewing individual snippets also makes it difficult to preserve the relationship between a finding and its original file, line, and surrounding project structure.

Automated review introduces its own problems:

- Static-analysis output is tool-specific and often needs to be normalized before it can be compared.
- AI output can be vague, duplicated, or inaccurate and should be validated by a person.
- Similar observations from AI and static analysis can appear as separate findings.
- Review decisions need to persist so that accepted, rejected, and modified findings remain visible later.
- Project uploads must be bounded and processed as data, not executed as application code.
- A report must distinguish descriptive review counts from benchmark measures that require ground-truth labels.

The project addresses these needs with an integrated submission, analysis, comparison, human-decision, and reporting workflow.

## 3. Objectives and Scope

### 3.1 Objectives

The project objectives are to:

1. Provide a Flask web interface for submitting code by paste, single-file upload, or folder upload.
2. Preserve relative paths for files in an uploaded project.
3. Analyze supported source files with the available AI and static-analysis integrations.
4. Normalize findings into a common representation that includes source, severity, explanation, line, filename, and suggested fix where available.
5. Reduce duplicate findings when multiple analyzers report the same issue.
6. Let a reviewer accept or reject findings and modify AI findings through a focused code-editing workflow.
7. Persist review decisions and display their status in the review interface and final report.
8. Keep uploads bounded and avoid executing submitted source code.
9. Provide automated tests for project preparation, analysis, routes, decisions, reports, and integrations.

### 3.2 Scope

The current application is a local-development Flask web application. Its documented persistence uses MySQL for application records and SQLite for human-review decisions. The project includes adapters for OpenAI, Gemini, Groq, and Claude; it also includes Semgrep, Bandit, and local Python rules.

The project-folder flow preserves supported files and relative paths, but analysis capabilities are not identical for every language. The repository documentation states that AI analysis currently targets Python. Other listed languages use Semgrep, while Bandit and local Python rules are Python-only.

The project is a working prototype and evaluation framework. It is not, on the evidence available in the repository, a hosted multi-tenant service, an enterprise access-control product, or a validated benchmark across a broad independent corpus.

## 4. Literature Review / Technology Survey

This section surveys the engineering approaches used in the project rather than asserting results from unverified external studies.

### 4.1 Manual review

Human review contributes context, domain knowledge, and accountability. A reviewer can assess whether an automated suggestion matches the intended behavior and can reject a technically plausible but irrelevant observation. Its limitations are reviewer availability, review effort, and variation in experience.

### 4.2 Static analysis

Static analyzers inspect source code without running the submitted program. Rule-based tools are useful for known risky constructs and repeatable checks. In this repository, Semgrep and Bandit are invoked as external analyzers, and local Python rules provide an additional fallback/checking path. Findings are converted into the application's common finding format.

Static results still require interpretation. Rules can be incomplete, findings can be noisy, and analyzer support depends on tool availability and language.

### 4.3 AI-assisted review

AI review can provide natural-language descriptions and suggested fixes. The application has provider adapters and normalizes AI results before presenting them. AI-generated findings remain proposals: the reviewer can accept, reject, or modify eligible AI findings.

The current AI review implementation has a Python-specific scope. When external provider output is unavailable or unusable, the repository includes local pattern-based fallback checks for selected Python constructs. Such fallback behavior is not equivalent to a comprehensive AI review.

### 4.4 Combining analyzers

Combining independent sources can improve coverage, but simply concatenating results creates duplicates and inconsistent terminology. The project normalizes findings and uses a similarity-based comparison that considers line numbers and tokens from categories and descriptions. For project review, merge checks are constrained to the same relative file so that a finding in one file is not merged with an unrelated finding in another.

### 4.5 Human-in-the-loop review

The human-in-the-loop approach places a reviewer between automated detection and final disposition. The application persists decisions using stable issue identifiers. This creates a review history and makes the final report reflect human choices rather than only raw analyzer output.

### 4.6 Evaluation methodology

The repository includes an evaluation runner that compares Human-only, AI-only, Static-analysis-only, and Combined conditions. Its checked-in evaluation cases use expected findings as ground truth and record bugs found, false positives, suggestions, review time, adoption, quality deltas, rejection reasons, and a statistical-test result when available.

Evaluation measures are only meaningful relative to their dataset and protocol. A small fixture set is appropriate for functional experimentation but cannot establish general effectiveness or superiority.

## 5. Proposed Solution and Methodology

### 5.1 System architecture

The application is organized as a Flask web application with template-based pages, analysis modules, and persistence:

```text
Browser
  |
  +-- Dashboard: paste code / upload file / upload folder
  |
  +-- Flask routes (project/backend/main.py)
        |
        +-- Project validation and temporary staging
        +-- AI provider adapters (Python review)
        +-- Static analysis (Semgrep / Bandit / local Python rules)
        +-- Finding normalization and comparison
        +-- MySQL: users, uploads, files, findings, reports
        +-- SQLite: human review decisions
  |
  +-- Review Findings: inspect and decide
  +-- Final Review Report: summaries, charts, findings by severity
```

### 5.2 Submission and validation

The dashboard offers three input modes: pasted code, a source file, or a selected project folder. Project files are validated before analysis. The current project-review module defines these limits:

| Control | Current limit or behavior |
|---|---|
| Files per project | 500 |
| Size of one file | 10 MiB |
| Total project content | 500 MiB |
| Accepted project text | UTF-8 source files from the supported extension map |
| Unsupported or binary files | Tracked as unsupported during preparation and not analyzed |
| Relative paths | Normalized and checked to prevent traversal and duplicate paths |
| Execution of uploaded code | Uploaded source is staged and analyzed as text; it is not run as the user's program |

Analysis uses a temporary directory that retains the relative folder structure. Project analysis runs in a background worker and uses a bounded thread pool, currently capped at four workers. The review page shows analysis status and refreshes when results are ready.

### 5.3 Analysis pipeline

For each supported file, the pipeline:

1. Determines language from the source extension.
2. Selects the configured analyzer for Python; non-Python files use Semgrep in the project-review path.
3. Runs static analysis and, for Python, the AI review path.
4. Converts tool findings into the shared `ReviewFinding` schema.
5. Attaches the original relative filename to project findings.
6. Compares candidate findings and merges likely duplicates where applicable.
7. Stores the results and presents them to the reviewer.

The shared finding model includes issue identity, title, description, severity, confidence, source, line, filename, suggested fix, and an optional accepted state.

### 5.4 Finding comparison

The merge implementation normalizes category, description, line, and source. Similarity is evaluated through token overlap and selected canonical issue terms; a line mismatch prevents a match when both findings have known line numbers. Project-level merging also requires the same filename. When findings are merged, the combined source is retained, confidence is maximized, and an available suggested fix is preserved.

This is a heuristic deduplication strategy, not a proof that two findings describe the same root cause. Reviewers should still validate the merged results.

### 5.5 Human review and modification

The review page displays findings with filename, line, severity, confidence, source, explanation, and suggested fix when available. Accept and Reject are available for findings; Modify is available for AI findings. Decisions are stored in SQLite and mirrored to the application's human-review records.

The Modify workflow opens a focused editor at the relevant location. Saving creates a new review submission and records the original AI finding as Modified; the browser returns to the original findings page. The new review is available through the review history rather than an extra post-save notice on the original findings page.

### 5.6 Reporting

The final report organizes findings by severity and includes a review overview chart and a human-decision donut chart with Accept, Reject, Modify, and Pending categories. The donut is intended to visualize the distribution of decisions; its legend reports counts and percentages.

The report also displays accuracy, precision, recall, and review time fields. Their interpretation requires care: the human-review report function currently computes its `accuracy` field as accepted decisions divided by recorded decisions, while benchmark evaluation uses ground-truth matching. Those measures are not interchangeable. Precision and recall should be treated as benchmark measures only when ground-truth labels and a defined evaluation protocol are present.

### 5.7 Upload and data-handling considerations

The project validates relative paths, rejects traversal and duplicate paths, limits file count and upload sizes, and ignores binary, invalid UTF-8, and unsupported files. Source is staged in a temporary directory with its relative structure and passed to static analyzers; the submitted program itself is not executed. Temporary staging is managed with Python's temporary-directory context manager.

Python source may be sent to the AI provider selected by the user when remote AI review is configured. This is distinct from local static analysis and should be considered before uploading proprietary or sensitive code. Provider retention and privacy terms are external to this repository. A production deployment should document that data flow, secure API keys, establish retention and access policies, and verify cleanup and logging behavior for its environment.

## 6. Tools, Technologies, and Requirements

### 6.1 Software stack

| Area | Technology in repository |
|---|---|
| Web application | Python and Flask |
| Templates | Jinja HTML templates |
| Main application database | MySQL through PyMySQL |
| Human decision storage | SQLite |
| Static analysis | Semgrep, Bandit, and local Python rules |
| AI providers | OpenAI, Gemini, Groq, and Claude adapters |
| Tests | pytest |
| Code-quality evaluation | Radon and Lizard where installed |

### 6.2 Runtime configuration

The README specifies Python 3.10 or newer, a MySQL server, installed static-analysis tools, and an optional provider API key. Supported API-key variables documented in the repository are `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, and `ANTHROPIC_API_KEY`. Provider model and endpoint overrides are also documented.

The current README describes the Flask development server at `http://127.0.0.1:5000`. Production deployment would require a separately configured WSGI server, secret management, database operations, logging, and hardened deployment settings.

### 6.3 Repository structure

```text
repository root/
|-- README.md
|-- evaluation_report.json
|-- evaluation_report_phase4.json
`-- project/
    |-- backend/
    |   |-- main.py
    |   |-- ai_review/
    |   |-- human_review/
    |   |-- merge/
    |   |-- static_analysis/
    |   |-- utils/
    |   |-- project_review.py
    |   |-- review_engine.py
    |   `-- evaluation_runner.py
    |-- frontend/templates/
    |-- tests/
    `-- requirements.txt
```

## 7. Work Plan

The following is a proposed work plan for continuing the project. It is a planning sequence, not a claim that each future activity has already been completed.

| Phase | Indicative duration | Activities | Deliverables |
|---|---:|---|---|
| 1. Requirements and baseline | 1-2 weeks | Confirm supported languages, analyzers, limits, and decision workflow; establish repeatable baseline tests | Requirements and baseline cases |
| 2. Analysis and normalization | 2-3 weeks | Improve provider schema validation, static-tool error reporting, merge behavior, and file-level traceability | Stable multi-source finding pipeline |
| 3. Human review and reporting | 2 weeks | Validate decision transitions, edit-and-return workflow, reporting labels, and chart behavior | Verified reviewer workflow and reports |
| 4. Evaluation expansion | 2-4 weeks | Add representative labeled projects, multiple reviewers, and repeatable timing protocol | Evaluation dataset and protocol |
| 5. Security and deployment readiness | 2-3 weeks | Review authentication, upload isolation, secret handling, database configuration, logging, and deployment | Deployment and security checklist |

Durations are indicative and should be revised based on team size, access to labeled code, and external-provider availability.

## 8. Expected Outcomes and Evaluation

### 8.1 Expected outcomes

The system is intended to:

- Reduce repetitive review effort by surfacing candidate issues from multiple analysis sources.
- Make project-level findings navigable by file and line.
- Preserve reviewer authority through explicit accept, reject, and modify decisions.
- Improve traceability by storing decisions with stable finding identifiers.
- Produce a final report that distinguishes findings, sources, severity, and human decisions.
- Support controlled experiments comparing review conditions.

These are intended outcomes, not guaranteed performance results.

### 8.2 Existing Phase 4 evaluation artifact

The checked-in `evaluation_report_phase4.json` records results from the repository's current fixture-based evaluation. The summary is:

| Condition | Bugs found | False positives | Suggestions | Review time (seconds) | Adoption rate |
|---|---:|---:|---:|---:|---:|
| Human-only | 2 | 0 | 2 | 12.400000 | 0.5000 |
| AI-only | 2 | 1 | 3 | 0.001634 | 0.3333 |
| Static-analysis-only | 2 | 1 | 3 | 1.409367 | 0.3333 |
| Combined | 2 | 1 | 3 | 1.411001 | 0.3333 |

The same artifact reports average before/after size values of 3.3333 and 3.0000, and complexity values of 1.0000 and 0.6667, respectively, with deltas of -0.3333 for both measures.

### 8.3 Interpretation and limitations of these figures

The repository evaluation cases are a small, hand-authored set of three fixtures, not a broad sample of production repositories. The figures therefore demonstrate the current evaluation pipeline and its example cases; they do not establish expected performance on arbitrary code.

The sub-millisecond AI timing values in the artifact should not be interpreted as end-to-end remote-provider latency. They may reflect fallback or mocked/local execution. Timing comparisons require a documented environment, network conditions, warm-up policy, and repeated trials.

The checked-in JSON reports pairwise Mann-Whitney U comparisons with p-values from 0.10 to 0.70; none is significant at the 0.05 threshold. With only three fixtures, these tests have very limited power and do not establish equivalence or superiority. No significance claim is made in this report.

The review report's `accuracy` label is not a substitute for benchmark accuracy unless computed against ground truth. For a defensible evaluation, precision, recall, and F1 should be computed from explicitly matched true positives, false positives, and false negatives on labeled cases; human acceptance should be reported separately as an adoption or acceptance measure.

### 8.4 Current automated verification

The project test suite was run during preparation of this report: **68 tests passed**. The suite includes tests for provider adapters, project validation and analysis, finding merge behavior, human-review decisions, evaluation logic, route behavior, and report rendering. Passing tests support implementation-level behavior but do not replace external validation or a security audit.

## 9. Conclusion

Human-in-the-Loop AI for Code Review combines AI-generated review candidates, static analysis, heuristic finding comparison, and reviewer decisions in a Flask application. It extends code-snippet review to individual files and folder uploads while preserving project-relative paths and applying limits to uploaded content.

Its most important design choice is keeping a human reviewer responsible for final dispositions. Persistent decisions and severity-organized reporting make the review process traceable. The current prototype also has meaningful limitations: AI review is Python-focused, analyzer behavior depends on installed tools and provider configuration, deduplication is heuristic, and the evaluation dataset is small.

The next substantive improvement should be a larger, independently labeled evaluation corpus with a reproducible timing protocol, followed by systematic deployment and security hardening. The current fixture results should be treated as preliminary engineering evidence rather than general performance claims.

## 10. References

Project documentation and implementation references:

1. Repository `README.md`: setup, supported submission modes, upload limits, providers, evaluation, and CLI usage.
2. `project/backend/main.py`: Flask routes, persistence integration, review and report workflows.
3. `project/backend/project_review.py`: project path validation, upload limits, supported languages, staging, and file analysis.
4. `project/backend/review_engine.py`: orchestration of AI, static analysis, and finding construction.
5. `project/backend/ai_review/reviewer.py`: AI provider selection, response normalization, and Python fallback behavior.
6. `project/backend/static_analysis/runner.py`: Semgrep, Bandit, and local Python-rule integration.
7. `project/backend/merge/merger.py`: finding normalization and similarity-based comparison.
8. `project/backend/human_review/decisions.py` and `storage.py`: decision model and persistence.
9. `project/backend/human_review/report.py`: severity-based final-report assembly.
10. `project/backend/evaluation_runner.py`: fixture evaluation conditions and quality metrics.
11. `project/tests/evaluation_cases.json` and `evaluation_report_phase4.json`: current sample cases and recorded output.
12. `project/tests/`: automated behavior tests.

## 11. Appendix A: Running and Testing the Project

### Install dependencies

From the repository root in PowerShell:

```powershell
cd project
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Start the development server

```powershell
python backend\main.py
```

Then open `http://127.0.0.1:5000`. The README notes that the development server disables Werkzeug's auto-reloader; restart it manually after source changes.

### Run tests

From the repository root:

```powershell
project\.venv\Scripts\python.exe -m pytest project\tests -q
```

### Run the fixture evaluation

From the repository root:

```powershell
project\.venv\Scripts\python.exe -m project.backend.evaluation_cli project\tests\evaluation_cases.json --output evaluation_report.json
```
