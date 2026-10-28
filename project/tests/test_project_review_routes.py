from project.backend import main
from project.backend.utils.schema import ReviewFinding


class _FakeCursor:
    def __init__(self):
        self.rowcount = 0
        self.one = None
        self.rows = []
        self.statements = []

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
            }
        elif normalized_query.startswith("select review_status from uploads"):
            self.one = {"review_status": "processing"}
        elif normalized_query.startswith("select relative_path, content, supported"):
            self.rows = [
                {"relative_path": "src/app.py", "content": "print('hello')", "supported": 1}
            ]
        elif normalized_query.startswith("update uploads"):
            self.rowcount = 1

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class _FakeConnection:
    def __init__(self):
        self.fake_cursor = _FakeCursor()
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
