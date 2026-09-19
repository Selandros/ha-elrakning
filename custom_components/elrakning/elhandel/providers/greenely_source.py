"""Sanitized Greenely source-data helpers."""

from __future__ import annotations

from typing import Any

SENSITIVE_PARTS = (
    "password", "jwt", "token", "authorization", "cookie", "secret",
    "personnummer", "personal_number", "ssn", "ocr", "pdf_url", "bankid",
    "customer_id", "customerid", "meter_id", "meterid", "account_id", "accountid",
    "email", "first_name", "firstname", "last_name", "lastname", "cell_phone",
    "phone", "mobile", "ip_address", "ipaddress", "address", "street",
    "zip_code", "zipcode", "postal_code",
)


def sanitize_greenely_source(value: Any, key: str | None = None) -> Any:
    """Recursively retain useful source data while removing secrets."""
    if key and any(part in key.lower() for part in SENSITIVE_PARTS):
        return None
    if isinstance(value, dict):
        return {name: clean for name, item in value.items() if (clean := sanitize_greenely_source(item, str(name))) is not None}
    if isinstance(value, list):
        return [clean for item in value if (clean := sanitize_greenely_source(item)) is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def merge_consumption_samples(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge samples by stable source timestamp/localtime without duplicates."""
    merged = {}
    for item in previous + current:
        key = str(item.get("source_timestamp") or item.get("localtime") or "")
        if key:
            merged[key] = item
    return sorted(merged.values(), key=lambda item: item.get("localtime") or "")


def paginate_source(items: list[Any], offset: int, limit: int) -> dict[str, Any]:
    """Return a bounded page from a source-data list."""
    safe_offset = max(0, offset)
    safe_limit = min(500, max(1, limit))
    return {"total": len(items), "offset": safe_offset, "limit": safe_limit, "items": items[safe_offset:safe_offset + safe_limit]}
