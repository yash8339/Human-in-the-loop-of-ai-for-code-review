from __future__ import annotations

import os
from typing import Any, Dict, List
from urllib.parse import quote

from .base import build_prompt, normalize_findings, parse_response, post_json


def review(code: str, language: str = "python") -> List[Dict[str, Any]]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return []
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    endpoint = os.getenv(
        "GEMINI_API_URL",
        f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent",
    )
    try:
        payload = post_json(
            f"{endpoint}?key={quote(api_key)}",
            {
                "contents": [{"parts": [{"text": build_prompt(code, language)}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
            {"Content-Type": "application/json"},
        )
        content = payload["candidates"][0]["content"]["parts"][0]["text"]
        return normalize_findings(parse_response(content))
    except (KeyError, TypeError, ValueError, OSError):
        return []