"""Pure Greenely invoice text parser."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

NUMBER = r"[-+]?(?:\d[\d .]*\d|\d)(?:[,.]\d+)?"
DATE_RANGE = r"(\d{4}-\d{2}-\d{2})\s*[–-]\s*(\d{4}-\d{2}-\d{2})"


def parse_swedish_decimal(value: str) -> Decimal:
    """Parse Swedish or international decimal notation without locale state."""
    normalized = value.strip().replace("\u00a0", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        decimal_separator = "," if normalized.rfind(",") > normalized.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        normalized = normalized.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation as err:
        raise ValueError("invalid_number") from err


def parse_greenely_invoice_text(text: str) -> dict[str, Any]:
    """Parse known Greenely invoice rows into a bounded normalized result."""
    normalized = re.sub(r"\s+", " ", text).strip()
    installation_sections = _installation_sections(normalized)
    if len(installation_sections) > 1:
        return {
            "parser_version": 3,
            "installation_sections": installation_sections,
            "warnings": ["multiple_installations_require_attribution"],
        }
    if len(installation_sections) == 1:
        result = _parse_greenely_invoice_body(installation_sections[0]["text"])
        result["installation_sections"] = installation_sections
        return result
    return _parse_greenely_invoice_body(normalized)


def _parse_greenely_invoice_body(normalized: str) -> dict[str, Any]:
    """Parse one already isolated invoice installation section."""
    warnings: list[str] = []
    agreement_match = re.search(rf"Elavtal\s*:\s*(.+?),\s*månadsavgift\s*({NUMBER})\s*kr", normalized, re.IGNORECASE)
    agreement = agreement_match.group(1).strip() if agreement_match else _search_text(normalized, r"(Kvartsprisavtal)")
    agreement_fee = parse_swedish_decimal(agreement_match.group(2)) if agreement_match else None
    period = re.search(DATE_RANGE, normalized)
    spot_kwh, spot_rate, spot_amount = _cost_row(normalized, "Spotpris")
    variable_kwh, variable_rate, variable_amount = _cost_row(normalized, "Rörliga kostnader")
    if variable_rate is None:
        warnings.append("missing_variable_cost")
    if spot_rate is None:
        warnings.append("missing_spot")
    fixed = _fixed_fee_row(normalized)
    if fixed and agreement_fee is not None:
        fixed["amount_incl_vat_sek"] = agreement_fee
    if not fixed:
        warnings.append("missing_fixed_fee")
    vat_amount, vat_rate = _vat_values(normalized)
    if vat_amount is None and vat_rate is None:
        warnings.append("missing_vat")
    if not period:
        warnings.append("missing_period")
    consumption = spot_kwh if spot_kwh is not None else variable_kwh
    if spot_kwh is not None and variable_kwh is not None and abs(spot_kwh - variable_kwh) > Decimal("0.001"):
        warnings.append("consumption_mismatch")
        consumption = None
    if consumption is None and spot_kwh is None and variable_kwh is None:
        warnings.append("missing_consumption")
    if spot_amount is not None and spot_rate is not None and spot_kwh is not None:
        _add_mismatch_warning(warnings, "spot_amount_mismatch", spot_kwh * spot_rate / 100, spot_amount)
    if variable_amount is not None and variable_rate is not None and variable_kwh is not None:
        _add_mismatch_warning(warnings, "variable_amount_mismatch", variable_kwh * variable_rate / 100, variable_amount)
    result = {
        "parser_version": 2,
        "agreement_name": agreement,
        "period_start": period.group(1) if period else None,
        "period_end": period.group(2) if period else None,
        "consumption_kwh": consumption,
        "spot": {"consumption_kwh": spot_kwh, "rate_ore_per_kwh_ex_vat": spot_rate, "amount_ex_vat_sek": spot_amount},
        "variable_cost": {"consumption_kwh": variable_kwh, "rate_ore_per_kwh_ex_vat": variable_rate, "amount_ex_vat_sek": variable_amount},
        "fixed_fee": fixed or {"quantity_months": None, "unit": None, "rate_ex_vat_sek_per_month": None, "amount_ex_vat_sek": None, "amount_incl_vat_sek": agreement_fee},
        "vat": {"amount_sek": vat_amount, "rate_percent": vat_rate},
        "tariff_candidates": {
            "variable_cost_ore_per_kwh_ex_vat": variable_rate,
            "fixed_fee_ex_vat_per_month": fixed["rate_ex_vat_sek_per_month"] if fixed else None,
            "fixed_fee_incl_vat_per_month": (fixed["amount_incl_vat_sek"] if fixed else agreement_fee),
        },
        "credit": _credit_values(normalized),
        "rounding_sek": _rounding_value(normalized),
        "gross_charge_sek": _gross_charge(spot_amount, variable_amount, fixed, vat_amount, _rounding_value(normalized)),
        "warnings": warnings,
    }
    return _clean_result(result)


def _installation_sections(normalized: str) -> list[dict[str, Any]]:
    """Split invoice text at explicit provider installation identifiers."""
    matches = list(re.finditer(r"\bAnl\.?\s*id\s*[:#]?\s*([0-9]{6,})", normalized, re.IGNORECASE))
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        sections.append({"installation_id": match.group(1), "text": normalized[match.start():end].strip()})
    return sections


def parse_greenely_invoice_diagnostics(text: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Return parsed data, bounded diagnostics, and a sanitized raw-text excerpt."""
    parsed = parse_greenely_invoice_text(text)
    field_map = {
        "agreement_name": parsed.get("agreement_name"),
        "period": parsed.get("period_start") and parsed.get("period_end"),
        "consumption": parsed.get("consumption_kwh"),
        "spot": parsed.get("spot", {}).get("rate_ore_per_kwh_ex_vat"),
        "variable_cost": parsed.get("variable_cost", {}).get("rate_ore_per_kwh_ex_vat"),
        "fixed_fee": parsed.get("fixed_fee", {}).get("amount_ex_vat_sek"),
        "vat": parsed.get("vat", {}).get("amount_sek") or parsed.get("vat", {}).get("rate_percent"),
    }
    diagnostics = {
        "extracted_character_count": len(text),
        "matched_fields": [key for key, value in field_map.items() if value is not None],
        "missing_fields": [key for key, value in field_map.items() if value is None],
    }
    return parsed, diagnostics, build_debug_text_excerpt(text)


def build_greenely_summary(parsed: dict[str, Any], amount_due_sek: float | None) -> dict[str, Any]:
    """Build the small, public-safe summary used by the Elhandel card."""
    fixed = parsed.get("fixed_fee") or {}
    variable = parsed.get("variable_cost") or {}
    spot = parsed.get("spot") or {}
    fixed_ex = fixed.get("amount_ex_vat_sek")
    fixed_incl = fixed.get("amount_incl_vat_sek")
    variable_ex = variable.get("rate_ore_per_kwh_ex_vat")
    multiplier = fixed_incl / fixed_ex if fixed_ex and fixed_incl else None
    variable_incl = variable_ex * multiplier if variable_ex is not None and multiplier is not None else None
    period = {
        "period_start": parsed.get("period_start"),
        "period_end": parsed.get("period_end"),
        "weighted_spot_average_ore_per_kwh": spot.get("rate_ore_per_kwh_ex_vat"),
        "gross_charge_sek": parsed.get("gross_charge_sek"),
        "credit_closing_sek": (parsed.get("credit") or {}).get("closing_balance_sek"),
        "amount_due_sek": amount_due_sek,
    }
    return {
        "agreement_name": parsed.get("agreement_name"),
        "tariff": {
            "variable_cost_ore_per_kwh_ex_vat": variable_ex,
            "variable_cost_ore_per_kwh_incl_vat": variable_incl,
            "fixed_fee_ex_vat_per_month": fixed.get("rate_ex_vat_sek_per_month"),
            "fixed_fee_incl_vat_per_month": fixed_incl,
        },
        "latest_period": period,
    }


def build_debug_text_excerpt(text: str, max_chars: int = 4000) -> str:
    """Keep relevant original lines while masking sensitive values."""
    lines = text.splitlines()
    start_match = re.search(r"(?im)^\s*(elavtal:|specifikation)\b", text)
    end_match = re.search(r"(?im)^\s*förklaring\b", text)
    if start_match:
        start = text[: start_match.start()].count("\n")
        end = text[: end_match.start()].count("\n") + 1 if end_match else len(lines)
        return "\n".join(_sanitize_debug_line(line) for line in lines[start:end])[:max_chars]
    terms = (
        "kvartsprisavtal", "period", "spotpris", "rörliga kostnader", "fast avgift",
        "varav moms", "moms 25", "öresutjämning", "rabatt", "tillgodohavande", "tillgodoräknande", "kredit", "tillgodo",
    )
    selected: set[int] = set()
    for index, line in enumerate(lines):
        if any(term in line.lower() for term in terms):
            selected.update(range(max(0, index - 2), min(len(lines), index + 4)))
    excerpt = "\n".join(_sanitize_debug_line(lines[index]) for index in sorted(selected))
    return excerpt[:max_chars]


def _sanitize_debug_line(line: str) -> str:
    if re.search(r"\bocr\b", line, re.IGNORECASE):
        return ""
    line = re.sub(r"https?://\S+", "[URL]", line)
    line = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[E-POST]", line)
    line = re.sub(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f-]{27,}\b", "[ID]", line)
    line = re.sub(r"\b\d{6,8}[-+]\d{4}\b", "[PERSONNUMMER]", line)
    line = re.sub(r"\b\d{10,}\b", "[NUMMER]", line)
    return line


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, int]:
    """Extract digital PDF text in memory using pypdf."""
    try:
        from io import BytesIO
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages), len(reader.pages)
    except ImportError as err:
        raise RuntimeError("pdf_parser_unavailable") from err
    except Exception as err:
        raise RuntimeError("invalid_pdf") from err


def _cost_row(text: str, label: str) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    match = re.search(
        rf"{re.escape(label)}\s*,?\s*(?:{DATE_RANGE})?\s*({NUMBER})\s*kWh\s+({NUMBER})\s*öre/kWh\s+({NUMBER})\s*(?:kr|sek)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, None, None
    return tuple(parse_swedish_decimal(value) for value in match.groups()[-3:])


def _fixed_fee_row(text: str) -> dict[str, Any] | None:
    match = re.search(rf"Fast avgift.*?(\d+)\s+([\wåäö]+)\s+({NUMBER})\s*sek/månad\s+({NUMBER})\s*(?:kr|sek)", text, re.IGNORECASE)
    if not match:
        legacy = re.search(rf"Fast avgift.*?({NUMBER})\s*kr\s*ex moms.*?({NUMBER})\s*kr\s*inkl moms", text, re.IGNORECASE)
        if legacy:
            return {"quantity_months": None, "unit": "månad", "rate_ex_vat_sek_per_month": parse_swedish_decimal(legacy.group(1)), "amount_ex_vat_sek": parse_swedish_decimal(legacy.group(1)), "amount_incl_vat_sek": parse_swedish_decimal(legacy.group(2))}
    if not match:
        return None
    return {"quantity_months": int(match.group(1)), "unit": match.group(2), "rate_ex_vat_sek_per_month": parse_swedish_decimal(match.group(3)), "amount_ex_vat_sek": parse_swedish_decimal(match.group(4)), "amount_incl_vat_sek": None}


def _vat_values(text: str) -> tuple[Decimal | None, Decimal | None]:
    amount = re.search(rf"varav moms\s+({NUMBER})\s*(?:kr|sek)", text, re.IGNORECASE)
    rate = re.search(rf"Moms\s+({NUMBER})\s*%", text, re.IGNORECASE)
    return (parse_swedish_decimal(amount.group(1)) if amount else None, parse_swedish_decimal(rate.group(1)) if rate else None)


def _credit_values(text: str) -> dict[str, Decimal | None]:
    opening_match = re.search(rf"(?:Tillgodohavande|Tillgodoräknande|Tillgodo).*?\b\d+\s+(-?{NUMBER})\s*(?:kr|sek)", text, re.IGNORECASE | re.DOTALL)
    closing_match = re.search(rf"Totalt tillgodo\s+({NUMBER})\s*(?:kr|sek)", text, re.IGNORECASE)
    opening = abs(parse_swedish_decimal(opening_match.group(1))) if opening_match else None
    closing = abs(parse_swedish_decimal(closing_match.group(1))) if closing_match else None
    used = opening - closing if opening is not None and closing is not None else None
    if used is not None and used < 0:
        used = None
    return {"opening_balance_sek": opening, "closing_balance_sek": closing, "used_sek": used, "new_credit_sek": None, "direct_discount_sek": None}


def _gross_charge(spot: Decimal | None, variable: Decimal | None, fixed: dict[str, Any] | None, vat: Decimal | None, rounding: Decimal | None) -> Decimal | None:
    values = [spot, variable, fixed["amount_ex_vat_sek"] if fixed else None, vat, rounding]
    return sum(values, Decimal("0")) if all(value is not None for value in values) else None


def _search_text(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None


def _rounding_value(text: str) -> Decimal | None:
    match = re.search(rf"Öresutjämning.*?(-?{NUMBER})\s*(?:kr|sek)", text, re.IGNORECASE)
    return parse_swedish_decimal(match.group(1)) if match else None


def _add_mismatch_warning(warnings: list[str], code: str, calculated: Decimal, actual: Decimal) -> None:
    if abs(calculated - actual) > Decimal("0.01"):
        warnings.append(code)


def _clean_result(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _clean_result(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_result(item) for item in value]
    return value
