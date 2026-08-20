from __future__ import annotations

import os
from typing import Any, Dict, List

from .base import build_prompt, normalize_findings, parse_response, post_json


def review(code: str, language: str = "python") -> List[Dict[str, Any]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return []
    try:
        payload = post_json(
            os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions"),
            {
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": build_prompt(code, language)}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        content = payload["choices"][0]["message"]["content"]
        return normalize_findings(parse_response(content))
    except (KeyError, TypeError, ValueError, OSError):
        return []