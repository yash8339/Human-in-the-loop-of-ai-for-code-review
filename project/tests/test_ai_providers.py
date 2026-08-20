import pytest

from project.backend.ai_review import claude, gemini, groq, openai


FINDING = {
    "line": 3,
    "issue_type": "unsafe-command",
    "description": "A shell command is executed.",
    "suggested_fix": "Use a safe API and validate inputs.",
}


@pytest.mark.parametrize(
    ("provider", "key_name", "response"),
    [
        (openai, "OPENAI_API_KEY", {"choices": [{"message": {"content": '{"findings": [%s]}' % str(FINDING).replace("'", '"')}}]}),
        (groq, "GROQ_API_KEY", {"choices": [{"message": {"content": '{"findings": [%s]}' % str(FINDING).replace("'", '"')}}]}),
        (gemini, "GEMINI_API_KEY", {"candidates": [{"content": {"parts": [{"text": '{"findings": [%s]}' % str(FINDING).replace("'", '"')}]}}]}),
        (claude, "ANTHROPIC_API_KEY", {"content": [{"text": '{"findings": [%s]}' % str(FINDING).replace("'", '"')}]}),
    ],
)
def test_provider_returns_common_finding_schema(monkeypatch, provider, key_name, response):
    monkeypatch.setenv(key_name, "test-key")
    monkeypatch.setattr(provider, "post_json", lambda url, payload, headers: response)

    assert provider.review("print('unsafe')") == [FINDING]


@pytest.mark.parametrize(
    ("provider", "key_name"),
    [(openai, "OPENAI_API_KEY"), (gemini, "GEMINI_API_KEY"), (groq, "GROQ_API_KEY"), (claude, "ANTHROPIC_API_KEY")],
)
def test_provider_skips_request_without_api_key(monkeypatch, provider, key_name):
    monkeypatch.delenv(key_name, raising=False)
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider made a request without an API key")

    monkeypatch.setattr(provider, "post_json", fail_if_called)

    assert provider.review("print('safe')") == []
    assert called is False