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
                "submission_type": "folder",
                "review_status": "uploaded",
                "analyzer": "semgrep",
                "model": "OpenAI",
                "filename": "sample-project",
                "language": "mixed",
                "content": "",
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
    assert b'class="link-button open-project-finding"' in response.data
    assert b'data-target-url="/review/12?filename=src/app.py#source-view"' in response.data
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
    assert b'class="report-chart-row severity-high"' in response.data
    assert b'class="report-chart-row decision-accept"' in response.data
    assert b'class="report-chart-row decision-modify"' in response.data
    assert b'class="report-chart-row decision-pending"' in response.data
    assert b'style="width: 50.0%"' in response.data


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
