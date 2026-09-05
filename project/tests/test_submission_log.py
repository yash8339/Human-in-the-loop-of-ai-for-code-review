import json

from project.backend import main


def test_log_submission_records_and_appends_submission(monkeypatch, tmp_path):
    log_path = tmp_path / "submission_log.json"
    monkeypatch.setattr(main, "SUBMISSION_LOG_PATH", log_path)

    with main.app.test_request_context("/dashboard"):
        main.session["user_id"] = 7
        main.session["user_name"] = "Test User"
        main.log_submission(12, "print('first')", "python", "ChatGPT", "Semgrep", "first.py", "2026-09-05 10:00:00")
        main.log_submission(13, "print('second')", "python", "Gemini", "Bandit", "second.py", "2026-09-05 10:01:00")

    submissions = json.loads(log_path.read_text(encoding="utf-8"))

    assert len(submissions) == 2
    assert submissions[0]["code"] == "print('first')"
    assert submissions[0]["submitted_at"] == "2026-09-05 10:00:00"
    assert submissions[0]["user_id"] == 7
    assert submissions[1]["code"] == "print('second')"
    assert submissions[1]["model"] == "Gemini"
