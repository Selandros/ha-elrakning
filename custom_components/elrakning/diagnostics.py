"""Bounded, sanitized integration diagnostics."""

from __future__ import annotations

import re
import platform
from datetime import datetime, timezone
from typing import Any

MAX_DIAGNOSTICS = 500
SENSITIVE = re.compile(
    r"(?:^|[_-])(?:password|passphrase|authorization|cookie|cookies|client[_-]?secret|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|current[_-]?token|session[_-]?(?:token|secret)|"
    r"authorization[_-]?code|code[_-]?(?:verifier|challenge)|jwt|dpop|cat|credential|secret|token)(?:$|[_-])"
    r"|^MyEon(?:Session|AccessToken|IDToken|ResumeAt|AccessScopes)$",
    re.IGNORECASE,
)
DIAGNOSTIC_SENSITIVE = re.compile(
    r"password|passphrase|authorization|cookie|token|secret|credential|jwt|dpop|cat|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token",
    re.IGNORECASE,
)


def runtime_metadata(integration_version: str) -> dict[str, str]:
    """Return bounded runtime metadata without filesystem or credential details."""
    return {
        "integration_version": str(integration_version),
        "python_implementation": str(platform.python_implementation()),
        "python_version": str(platform.python_version()),
        "machine": str(platform.machine()),
        "system": str(platform.system()),
    }


def sanitize_source_data(value: Any, key: str = "") -> Any:
    """Recursively redact authentication and takeover-sensitive source values."""
    if SENSITIVE.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(name): sanitize_source_data(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [sanitize_source_data(item) for item in value]
    return value


def sanitize_diagnostic_text(value: Any) -> str:
    """Keep diagnostic messages useful without retaining credentials or payloads."""
    text = str(value)
    text = re.sub(r"https?://\S+", "[URL]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[E-POST]", text)
    text = re.sub(r"\b\d{10,}\b", "[NUMMER]", text)
    if DIAGNOSTIC_SENSITIVE.search(text):
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
