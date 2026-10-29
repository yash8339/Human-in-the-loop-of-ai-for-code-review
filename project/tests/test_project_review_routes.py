from urllib.parse import parse_qs, urlsplit

from project.backend import main
from project.backend.project_review import MAX_PROJECT_REQUEST_SIZE
from project.backend.utils.schema import ReviewFinding


def test_upload_request_limit_allows_500_mib_projects_and_multipart_overhead():
    assert main.app.config["MAX_CONTENT_LENGTH"] == MAX_PROJECT_REQUEST_SIZE
    assert MAX_PROJECT_REQUEST_SIZE == 501 * 1024 * 1024


class _FakeCursor:
    def __init__(self, project_files=None):
        self.rowcount = 0
        self.one = None
        self.rows = []
        self.statements = []
        self.review_status = "uploaded"
        self.submission_type = "folder"
        self.upload_content = ""
        self.project_files = project_files or [
            {"relative_path": "src/app.py", "content": "print('hello')", "supported": 1}
        ]

    def execute(self, query, params=()):
        assert query.count("%s") == len(params)
        self.statements.append((query, params))
        normalized_query = " ".join(query.split()).lower()
        if normalized_query.startswith("select * from uploads"):
            self.one = {
                "id": 12,
                "user_id": 7,
                "submission_type": self.submission_type,
                "review_status": self.review_status,
                "analyzer": "semgrep",
                "model": "OpenAI",
                "filename": "sample-project",
                "language": "mixed",
                "content": self.upload_content,
            }
        elif normalized_query.startswith("select review_status from uploads"):
            self.one = {"review_status": "processing"}
        elif normalized_query.startswith("select * from reviews"):
            self.rows = [
                {
                    "id": 31,
                    "title": "unsafe-call",
                    "description": "Review found a risky call.",
                    "severity": "high",
                    "confidence": 0.9,
                    "source": "static",
                    "line": 2,
                    "filename": "src/app.py",
                    "suggested_fix": "Use a safer API.",
                },
                {
                    "id": 32,
                    "title": "missing-validation",
                    "description": "Input is not validated.",
                    "severity": "medium",
                    "confidence": 0.8,
                    "source": "ai",
                    "line": 3,
                    "filename": "src/app.py",
                    "suggested_fix": "Validate input.",
                },
            ]
        elif normalized_query.startswith("select hr.decision, r.title"):
            self.rows = []
        elif normalized_query.startswith("select * from reports"):
            self.one = None
        elif normalized_query.startswith("select relative_path, content, supported"):
            self.rows = self.project_files
        elif normalized_query.startswith("select relative_path, supported, unsupported_reason"):
            self.rows = []
        elif normalized_query.startswith("update uploads"):
            self.rowcount = 1

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, project_files=None):
        self.fake_cursor = _FakeCursor(project_files)
        self.committed = False

    def cursor(self):
        return self.fake_cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


class _FakeExecutor:
    def __init__(self):
        self.submitted = None

    def submit(self, function, *args):
        self.submitted = (function, args)


def test_project_review_start_returns_while_analysis_runs_in_background(monkeypatch):
    connection = _FakeConnection()
    executor = _FakeExecutor()
    active_review_ids = set()
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(main, "_PROJECT_REVIEW_EXECUTOR", executor)
    monkeypatch.setattr(main, "_ACTIVE_PROJECT_REVIEW_IDS", active_review_ids)

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.post("/project/12/start")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/review/12")
    assert executor.submitted is not None
    assert executor.submitted[0] is main._process_project_review
    assert 12 in active_review_ids
    assert connection.committed
    assert any(
        "review_status = 'processing'" in query
        for query, _params in connection.fake_cursor.statements
    )


def test_project_finding_modify_opens_source_editor_at_finding_line(monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setattr(main, "get_db", lambda: connection)

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.get("/review/12/edit?filename=src%2Fapp.py&line=2")

    assert response.status_code == 200
    assert b"Modify Code and Review Again" in response.data
    assert b"<strong>src/app.py</strong>" in response.data
    assert b"const targetLine = Number(2);" in response.data
    assert b"print(&#39;hello&#39;)" in response.data or b"print('hello')" in response.data


def test_saving_code_from_modify_returns_to_all_original_findings(monkeypatch):
    connection = _FakeConnection()
    connection.fake_cursor.submission_type = "code"
    connection.fake_cursor.upload_content = "old source"
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(main, "_create_upload_review", lambda *_args: 99)
    modified_findings = []
    monkeypatch.setattr(
        main,
        "_record_modified_finding",
        lambda upload_id, review_id: modified_findings.append((upload_id, review_id)),
    )

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.post(
        "/review/12/edit",
        data={
            "filename": "sample.py",
            "code": "updated source",
            "return_upload_id": "12",
            "return_review_id": "32",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/review/12")
    assert modified_findings == [(12, 32)]


def test_project_review_opens_selected_file_and_highlights_all_finding_lines(monkeypatch):
    connection = _FakeConnection(
        [{"relative_path": "src/app.py", "content": "first\nsecond\nthird", "supported": 1}]
    )
    monkeypatch.setattr(main, "get_db", lambda: connection)

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.get("/review/12?filename=src%2Fapp.py")

    assert response.status_code == 200
    assert b"Project files" in response.data
    assert b"src/app.py" in response.data
    assert b"id=\"selected-source-line-2\"" in response.data
    assert b"id=\"selected-source-line-3\"" in response.data
    assert b"is-target-line" in response.data
    assert b">Edit code</a>" in response.data
    assert b"/review/12/edit?filename=src/app.py" in response.data
    assert b'<button type="submit" name="decision" value="modify">Modify</button>' in response.data
    assert b"Modified explanation" not in response.data
    assert b"Save modification" not in response.data
    assert response.data.count(b'value="modify">Modify</button>') == 1
    assert b'class="save-decision-button" data-decision="accept">Accept</button>' in response.data
    assert b'class="save-decision-button" data-decision="reject">Reject</button>' in response.data
    assert b'formData.set("decision", decision)' in response.data
    assert b"new FormData(form, submitter)" not in response.data
    assert response.data.index(b'aria-label="Project files"') < response.data.index(
        b'<main class="project-review-findings">'
    )
    assert b"grid-template-columns: 280px minmax(0, 1fr)" in response.data


def test_final_report_renders_severity_and_human_decision_charts(monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(
        main,
        "load_decisions",
        lambda _upload_id: [
            main.HumanDecision("issue-031", "accept"),
            main.HumanDecision("issue-032", "modify"),
        ],
    )

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.get("/report/12")

    assert response.status_code == 200
    assert b"Findings by Severity" in response.data
    assert b"Human Review Decisions" in response.data
    assert b"Review Overview" in response.data
    assert b'class="report-chart-row overview-total"' in response.data
    assert b'class="report-chart-row overview-ai"' in response.data
    assert b'class="report-chart-row overview-static"' in response.data
    assert b'class="report-chart-row overview-reviewed"' in response.data
    assert b"Reviewed / marked" in response.data
    assert b'class="report-chart-row severity-high"' in response.data
    assert b'class="decision-legend-item decision-accept"' in response.data
    assert b'class="decision-legend-item decision-modify"' in response.data
    assert b'class="decision-legend-item decision-pending"' in response.data
    assert b'class="decision-donut-layout"' in response.data
    assert b'<svg class="decision-donut"' in response.data
    assert b'<circle class="decision-donut-segment decision-accept"' in response.data
    assert b'<circle class="decision-donut-segment decision-modify"' in response.data
    assert b'stroke="#2d9a77"' in response.data
    assert b'stroke="#7a52b5"' in response.data
    assert b'stroke-dasharray="226.1946710584651 226.1946710584651"' in response.data
    assert b'style="width: 50.0%"' in response.data
    assert response.data.index(b'id="review-overview-chart-title"') < response.data.index(b'class="summary-grid"')
    assert b"<h2>Total Findings</h2>" not in response.data
    assert b"<h2>AI Reviews</h2>" not in response.data
    assert b"<h2>Static Analysis Reviews</h2>" not in response.data
    assert b"False Positive Rate" not in response.data


def test_review_page_offers_generate_report_after_project_analysis(monkeypatch):
    connection = _FakeConnection()
    connection.fake_cursor.review_status = "reviewed"
    monkeypatch.setattr(main, "get_db", lambda: connection)

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.get("/review/12")

    assert response.status_code == 200
    assert b"Total findings:</strong> 2" in response.data
    assert b'data-metric=' not in response.data
    assert b">Generate Report</a>" in response.data
    assert b'class="nav-icon icon-dashboard"' in response.data
    assert b'class="nav-icon icon-review"' in response.data
    assert b'class="nav-icon icon-profile"' in response.data
    assert b'class="nav-icon icon-history"' in response.data


def test_review_page_decision_summary_renders_with_no_saved_decisions(monkeypatch):
    connection = _FakeConnection()
    connection.fake_cursor.submission_type = "code"
    connection.fake_cursor.upload_content = "example source"
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(main, "load_decisions", lambda _upload_id: [])

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.get("/review/12")

    assert response.status_code == 200
    assert b"Marked:</strong>" not in response.data
    assert b"Accepted:</strong>" not in response.data
    assert b"Rejected:</strong>" not in response.data
    assert b"Modified:</strong>" not in response.data
    assert b"Acceptance Rate" not in response.data
    assert b"Accepted Findings (%)" not in response.data
    assert b"Review Completion Rate" not in response.data
    assert b'id="show-source-code"' not in response.data
    assert b'<pre class="source-code review-source" id="source-view">' in response.data
    assert b"Code saved. A new review is running" not in response.data
    assert b"Open the new code review" not in response.data


def test_ai_modify_page_shows_only_finding_code_suggestion_and_edit_link(monkeypatch):
    connection = _FakeConnection()
    connection.fake_cursor.submission_type = "code"
    connection.fake_cursor.upload_content = "first\nsecond\nthird"
    monkeypatch.setattr(main, "get_db", lambda: connection)

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.get("/review/12/finding/32/modify")

    assert response.status_code == 200
    assert b"Modify AI Finding" in response.data
    assert b"AI suggestion for this finding" in response.data
    assert b"<p>Validate input.</p>" in response.data
    assert b"finding-source-line is-target-line" in response.data
    assert b'href="/review/12/edit?filename=src/app.py&amp;line=3&amp;return_upload_id=12&amp;return_review_id=32">Edit code</a>' in response.data
    assert b"unsafe-call" not in response.data
    assert b"Review found a risky call." not in response.data
    assert response.data.index(b"</pre>") < response.data.index(b">Edit code</a>")
    assert response.data.index(b">Edit code</a>") < response.data.index(b"AI suggestion for this finding")


def test_saving_finding_decision_returns_to_findings_page(monkeypatch):
    class DecisionCursor(_FakeCursor):
        def execute(self, query, params=()):
            super().execute(query, params)
            normalized_query = " ".join(query.split()).lower()
            if normalized_query.startswith("select r.* from reviews"):
                self.one = {
                    "id": 31,
                    "upload_id": 12,
                    "title": "unsafe-call",
                    "filename": "src/app.py",
                }
            elif normalized_query.startswith("select id from human_reviews"):
                self.one = None

    connection = _FakeConnection()
    connection.fake_cursor = DecisionCursor()
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(main, "save_decision", lambda *_args: None)

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.post(
        "/review/12/decision",
        data={
            "review_id": "31",
            "return_filename": "src/app.py",
            "decision": "accept",
        },
    )

    assert response.status_code == 302
    redirect_parts = urlsplit(response.headers["Location"])
    assert redirect_parts.path == "/review/12"
    assert parse_qs(redirect_parts.query) == {"filename": ["src/app.py"]}
    assert connection.committed


def test_ajax_accept_or_reject_returns_json_not_report_redirect(monkeypatch):
    class DecisionCursor(_FakeCursor):
        def execute(self, query, params=()):
            super().execute(query, params)
            normalized_query = " ".join(query.split()).lower()
            if normalized_query.startswith("select r.* from reviews"):
                self.one = {
                    "id": 31,
                    "upload_id": 12,
                    "title": "unsafe-call",
                    "source": "static",
                }
            elif normalized_query.startswith("select id from human_reviews"):
                self.one = None

    connection = _FakeConnection()
    connection.fake_cursor = DecisionCursor()
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(main, "save_decision", lambda *_args: None)

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.post(
        "/review/12/decision",
        data={"review_id": "31", "decision": "reject"},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"decision": "reject"}
    assert "Location" not in response.headers
    assert connection.committed


def test_ajax_decision_returns_json_when_session_has_expired():
    client = main.app.test_client()

    response = client.post(
        "/review/12/decision",
        data={"review_id": "31", "decision": "accept"},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )

    assert response.status_code == 401
    assert response.get_json() == {"error": "Your session has expired. Please sign in again."}


def test_ai_modify_action_opens_focused_modify_page(monkeypatch):
    class AIDecisionCursor(_FakeCursor):
        def execute(self, query, params=()):
            super().execute(query, params)
            normalized_query = " ".join(query.split()).lower()
            if normalized_query.startswith("select r.* from reviews"):
                self.one = {
                    "id": 32,
                    "upload_id": 12,
                    "title": "missing-validation",
                    "source": "ai",
                }
            elif normalized_query.startswith("select id from human_reviews"):
                self.one = None

    connection = _FakeConnection()
    connection.fake_cursor = AIDecisionCursor()
    saved_decisions = []
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(main, "save_decision", lambda *args: saved_decisions.append(args))

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.post(
        "/review/12/decision",
        data={
            "review_id": "32",
            "decision": "modify",
            "return_filename": "src/app.py",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(
        "/review/12/finding/32/modify"
    )
    assert saved_decisions == []


def test_review_cards_show_saved_decision_colors_and_counts(monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(
        main,
        "load_decisions",
        lambda _upload_id: [
            main.HumanDecision("issue-031", "accept"),
            main.HumanDecision("issue-032", "reject"),
        ],
    )

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.get("/review/12")

    assert response.status_code == 200
    assert b"finding-card decision-accept" in response.data
    assert b"finding-card decision-reject" in response.data
    assert b"background: rgba(45, 154, 119, 0.38)" in response.data
    assert b"background: rgba(185, 65, 75, 0.38)" in response.data
    assert b"background: rgba(122, 82, 181, 0.4)" in response.data
    assert b"Marked:</strong>" not in response.data
    assert b"Accepted:</strong>" not in response.data
    assert b"Rejected:</strong>" not in response.data


def test_static_finding_cannot_be_saved_as_modify(monkeypatch):
    class StaticDecisionCursor(_FakeCursor):
        def execute(self, query, params=()):
            super().execute(query, params)
            if "select r.* from reviews" in " ".join(query.split()).lower():
                self.one = {
                    "id": 31,
                    "upload_id": 12,
                    "title": "unsafe-call",
                    "source": "static",
                }

    connection = _FakeConnection()
    connection.fake_cursor = StaticDecisionCursor()
    saved_decisions = []
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(main, "save_decision", lambda *args: saved_decisions.append(args))

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.post(
        "/review/12/decision",
        data={
            "review_id": "31",
            "decision": "modify",
            "modified_description": "Changed explanation",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/review/12")
    assert saved_decisions == []


def test_saving_project_code_starts_review_and_returns_to_selected_file(monkeypatch):
    connection = _FakeConnection(
        [
            {"relative_path": "src/app.py", "content": "print('hello')", "supported": 1},
            {"relative_path": "README.md", "content": "", "supported": 0},
        ]
    )
    executor = _FakeExecutor()
    active_review_ids = set()
    created = {}
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(main, "_PROJECT_REVIEW_EXECUTOR", executor)
    monkeypatch.setattr(main, "_ACTIVE_PROJECT_REVIEW_IDS", active_review_ids)

    def fake_create_project_upload(name, submission_type, files):
        created["name"] = name
        created["submission_type"] = submission_type
        created["files"] = files
        return 99

    monkeypatch.setattr(main, "_create_project_upload", fake_create_project_upload)
    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.post(
        "/review/12/edit",
        data={
            "filename": "src/app.py",
            "line": "2",
            "code": "print('updated')",
            "model": "OpenAI",
            "analyzer": "semgrep",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(
        "/review/99?filename=src/app.py#source-view"
    )
    assert created["name"] == "sample-project"
    assert created["submission_type"] == "folder"
    assert [(file.relative_path, file.content, file.supported) for file in created["files"]] == [
        ("src/app.py", "print('updated')", True),
        ("README.md", "", False),
    ]
    assert executor.submitted is not None
    assert executor.submitted[0] is main._process_project_review
    assert executor.submitted[1][0:2] == (99, 7)
    assert executor.submitted[1][2] == [
        {"relative_path": "src/app.py", "content": "print('updated')", "supported": True},
        {"relative_path": "README.md", "content": "", "supported": False},
    ]
    assert 99 in active_review_ids


def test_project_review_status_endpoint_returns_authenticated_status(monkeypatch):
    connection = _FakeConnection()
    active_review_ids = {12}
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(main, "_ACTIVE_PROJECT_REVIEW_IDS", active_review_ids)

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.get("/project/12/status")

    assert response.status_code == 200
    assert response.get_json() == {"status": "processing"}


def test_project_review_status_recovers_abandoned_processing_review(monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(main, "_ACTIVE_PROJECT_REVIEW_IDS", set())

    client = main.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = 7

    response = client.get("/project/12/status")

    assert response.status_code == 200
    assert response.get_json() == {"status": "uploaded"}
    assert any(
        "set review_status = 'uploaded'" in query.lower()
        for query, _params in connection.fake_cursor.statements
    )


def test_background_project_review_persists_findings_and_marks_reviewed(monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setattr(main, "get_db", lambda: connection)
    monkeypatch.setattr(
        main,
        "analyze_project_files",
        lambda *_args, **_kwargs: [
            ReviewFinding(
                title="test-finding",
                description="Example finding.",
                severity="medium",
                confidence=0.8,
                source="static",
                line=2,
                filename="src/app.py",
            )
        ],
    )

    main._process_project_review(12, 7, [], "semgrep", "OpenAI")

    statements = [query.lower() for query, _params in connection.fake_cursor.statements]
    assert any("insert into reviews" in query for query in statements)
    assert any("review_status = 'reviewed'" in query for query in statements)
    assert any("insert into reports" in query for query in statements)
    report_statement = next(
        (query, params)
        for query, params in connection.fake_cursor.statements
        if "insert into reports" in query.lower()
    )
    assert len(report_statement[1]) == 7
    assert connection.committed


def test_background_project_review_marks_failed_when_analysis_raises(monkeypatch):
    connections = []

    def fake_get_db():
        connection = _FakeConnection()
        connections.append(connection)
        return connection

    def fail_analysis(*_args, **_kwargs):
        raise RuntimeError("analyzer failed")

    monkeypatch.setattr(main, "get_db", fake_get_db)
    monkeypatch.setattr(main, "analyze_project_files", fail_analysis)

    main._process_project_review(12, 7, [], "semgrep", "OpenAI")

    assert len(connections) == 1
    assert any(
        "review_status = 'failed'" in query.lower()
        for query, _params in connections[0].fake_cursor.statements
    )
    assert connections[0].committed
