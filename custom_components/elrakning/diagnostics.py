"""Bounded, sanitized integration diagnostics."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

MAX_DIAGNOSTICS = 500
SENSITIVE = re.compile(r"(password|jwt|token|authorization|cookie|secret|pdf[_-]?url|ocr|personnummer|personal[_-]?number|ssn|credential)", re.IGNORECASE)


def sanitize_diagnostic_text(value: Any) -> str:
    """Keep diagnostic messages useful without retaining credentials or payloads."""
    text = str(value)
    text = re.sub(r"https?://\S+", "[URL]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[E-POST]", text)
    text = re.sub(r"\b\d{10,}\b", "[NUMMER]", text)
    if SENSITIVE.search(text):
        return "Sensitive diagnostic data redacted"
    return text[:500]


def append_diagnostic(logs: list[dict[str, Any]], level: str, component: str, event: str, message: str) -> None:
    """Append one bounded diagnostic entry."""
    logs.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level if level in {"ERROR", "WARNING", "INFO", "DEBUG"} else "INFO",
        "component": sanitize_diagnostic_text(component),
        "event": sanitize_diagnostic_text(event),
        "message": sanitize_diagnostic_text(message),
    })
    del logs[:-MAX_DIAGNOSTICS]
