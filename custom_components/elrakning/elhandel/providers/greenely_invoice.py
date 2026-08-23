"""Greenely-specific invoice download and processing."""

from __future__ import annotations

from typing import Any

from .greenely_invoice_parser import (
    build_greenely_summary,
    extract_pdf_text,
    parse_greenely_invoice_diagnostics,
)


class GreenelyInvoiceError(RuntimeError):
    """A normalized invoice processing error with its processing stage."""

    def __init__(self, code: str, stage: str) -> None:
        super().__init__(code)
        self.code = code
        self.stage = stage


class GreenelyInvoiceProcessor:
    """Download and normalize one Greenely invoice without owning manager state."""

    def __init__(self, provider) -> None:
        self._provider = provider

    async def async_process(
        self,
        contract_id: str,
        invoice_key: str,
        amount_due_sek: float | None,
    ) -> dict[str, Any]:
        pdf_bytes = await self._provider.async_get_invoice_pdf(contract_id, invoice_key)
        try:
            extracted_text, page_count = extract_pdf_text(pdf_bytes)
        except RuntimeError as err:
            raise GreenelyInvoiceError(str(err), "pdf_extract") from err

        try:
            parsed, diagnostics, debug_text_excerpt = parse_greenely_invoice_diagnostics(extracted_text)
        except RuntimeError as err:
            raise GreenelyInvoiceError(str(err), "parse") from err

        diagnostics["pdf_pages"] = page_count
        used_credit = parsed.get("credit", {}).get("used_sek")
        gross_charge = parsed.get("gross_charge_sek")
        if gross_charge is not None and used_credit is not None and amount_due_sek is not None:
            diagnostics["payment_reconciliation"] = (
                "ok"
                if abs(gross_charge - used_credit - amount_due_sek) <= 0.02
                else "payment_reconciliation_mismatch"
            )

        if (
            parsed.get("warnings")
            or not parsed.get("agreement_name")
            or not parsed.get("period_start")
            or not parsed.get("period_end")
            or parsed.get("variable_cost", {}).get("rate_ore_per_kwh_ex_vat") is None
            or parsed.get("fixed_fee", {}).get("amount_ex_vat_sek") is None
            or diagnostics.get("payment_reconciliation") == "payment_reconciliation_mismatch"
        ):
            error = parsed.get("warnings", ["invalid_invoice"])[0] if parsed.get("warnings") else "validation_failed"
            raise GreenelyInvoiceError(error, "validation")

        return {
            "parsed": parsed,
            "diagnostics": diagnostics,
            "debug_text_excerpt": debug_text_excerpt,
            "summary": build_greenely_summary(parsed, amount_due_sek),
        }
