from __future__ import annotations

import os
from typing import Any, Dict, List

from .base import build_prompt, normalize_findings, parse_response, post_json


def review(code: str, language: str = "python") -> List[Dict[str, Any]]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return []
    try:
        payload = post_json(
            os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages"),
            {
                "model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
                "max_tokens": 2048,
                "temperature": 0,
                "messages": [{"role": "user", "content": build_prompt(code, language)}],
            },
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        content = payload["content"][0]["text"]
        return normalize_findings(parse_response(content))
    except (KeyError, TypeError, ValueError, OSError):
        return []