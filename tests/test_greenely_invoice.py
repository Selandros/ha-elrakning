import unittest
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_PARSER_PATH = Path(__file__).parents[1] / "custom_components" / "elrakning" / "elhandel" / "providers" / "greenely_invoice_parser.py"
_SPEC = spec_from_file_location("elrakning_invoice_parser", _PARSER_PATH)
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
parse_greenely_invoice_text = _MODULE.parse_greenely_invoice_text
parse_swedish_decimal = _MODULE.parse_swedish_decimal
parse_greenely_invoice_diagnostics = _MODULE.parse_greenely_invoice_diagnostics
build_greenely_summary = _MODULE.build_greenely_summary


class GreenelyInvoiceParserTests(unittest.TestCase):
    def test_swedish_numbers(self):
        self.assertEqual(parse_swedish_decimal("17,00"), Decimal("17.00"))
        self.assertEqual(parse_swedish_decimal("17.00"), Decimal("17.00"))
        self.assertEqual(parse_swedish_decimal("0.10"), Decimal("0.10"))
        self.assertEqual(parse_swedish_decimal("10.10"), Decimal("10.10"))
        self.assertEqual(parse_swedish_decimal("31.20"), Decimal("31.20"))
        self.assertEqual(parse_swedish_decimal("-483.00"), Decimal("-483.00"))
        self.assertEqual(parse_swedish_decimal("-0,04"), Decimal("-0.04"))
        self.assertEqual(parse_swedish_decimal("1 234,56"), Decimal("1234.56"))
        self.assertEqual(parse_swedish_decimal("1.234,56"), Decimal("1234.56"))
        self.assertEqual(parse_swedish_decimal("1,234.56"), Decimal("1234.56"))

    def test_known_invoice_rows_and_whitespace(self):
        result = parse_greenely_invoice_text(
            """
            Kvartsprisavtal
            Period 2026-07-01 – 2026-07-31
            Spotpris\n0,10 kWh 10,10 öre/kWh 0,01 kr
            Rörliga kostnader 0,10 kWh\n17,00 öre/kWh 0,02 kr
            Fast avgift 31,20 kr ex moms 39,00 kr inkl moms
            Moms 25 %
            Öresutjämning -0,04 kr
            """
        )
        self.assertEqual(result["agreement_name"], "Kvartsprisavtal")
        self.assertEqual(result["period_start"], "2026-07-01")
        self.assertEqual(result["consumption_kwh"], 0.1)
        self.assertEqual(result["spot"]["rate_ore_per_kwh_ex_vat"], 10.1)
        self.assertEqual(result["variable_cost"]["rate_ore_per_kwh_ex_vat"], 17.0)
        self.assertEqual(result["fixed_fee"]["amount_ex_vat_sek"], 31.2)
        self.assertEqual(result["vat"]["rate_percent"], 25.0)
        self.assertEqual(result["rounding_sek"], -0.04)
        self.assertNotIn("raw", result)

    def test_missing_tariff_rows_are_warnings(self):
        result = parse_greenely_invoice_text("Kvartsprisavtal Moms 25 %")
        self.assertIn("missing_variable_cost", result["warnings"])
        self.assertIn("missing_fixed_fee", result["warnings"])

    def test_live_pdf_structure(self):
        result = parse_greenely_invoice_text(
            """Elavtal: Testavtal, månadsavgift 39 krPeriod: 2026-07-01 - 2026-07-31 Avläsning: Verifierad
            Specifikation Antal Pris exkl. moms Summa exkl. moms
            Tillgodohavande från faktura nr 12345,
            2026-07-10 - 2026-07-10
            1 -483.00 SEK -483.00 SEK
            Spotpris, 2026-07-01 - 2026-07-31 0.10 kWh 10.10 öre/kWh 0.01 SEK
            Rörliga kostnader, 2026-07-01 - 2026-07-31 0.10 kWh 17.00 öre/kWh 0.02 SEK
            Fast avgift, 2026-07-01 - 2026-07-31 1 månad 31.20 sek/månad 31.20 SEK
            Öresutjämning -0,04 SEK
            Summa -444,00 SEK
            varav moms 7,81 SEK
            Totalt tillgodo 444,00 SEK
            Förklaring"""
        )
        self.assertEqual(result["agreement_name"], "Testavtal")
        self.assertEqual(result["consumption_kwh"], 0.1)
        self.assertEqual(result["spot"]["rate_ore_per_kwh_ex_vat"], 10.1)
        self.assertEqual(result["variable_cost"]["amount_ex_vat_sek"], 0.02)
        self.assertEqual(result["fixed_fee"]["rate_ex_vat_sek_per_month"], 31.2)
        self.assertEqual(result["fixed_fee"]["amount_incl_vat_sek"], 39.0)
        self.assertEqual(result["vat"]["amount_sek"], 7.81)
        self.assertEqual(result["credit"]["used_sek"], 39.0)
        self.assertEqual(result["gross_charge_sek"], 39.0)
        self.assertEqual(result["warnings"], [])

    def test_mismatch_warnings(self):
        result = parse_greenely_invoice_text("Spotpris 0.10 kWh 10.10 öre/kWh 0.50 SEK Rörliga kostnader 0.20 kWh 17.00 öre/kWh 0.50 SEK")
        self.assertIn("consumption_mismatch", result["warnings"])
        self.assertIn("spot_amount_mismatch", result["warnings"])

    def test_summary_separates_tariff_spot_credit_and_due(self):
        parsed = {
            "agreement_name": "Testavtal",
            "spot": {"rate_ore_per_kwh_ex_vat": 10.10},
            "variable_cost": {"rate_ore_per_kwh_ex_vat": 17.00},
            "fixed_fee": {"rate_ex_vat_sek_per_month": 31.20, "amount_ex_vat_sek": 31.20, "amount_incl_vat_sek": 39.00},
            "credit": {"closing_balance_sek": 444.00},
            "gross_charge_sek": 39.00,
            "period_start": "2026-07-01",
            "period_end": "2026-07-31",
        }
        summary = build_greenely_summary(parsed, 0.0)
        self.assertEqual(summary["tariff"]["variable_cost_ore_per_kwh_incl_vat"], 21.25)
        self.assertEqual(summary["tariff"]["fixed_fee_incl_vat_per_month"], 39.00)
        self.assertEqual(summary["latest_period"]["weighted_spot_average_ore_per_kwh"], 10.10)
        self.assertEqual(summary["latest_period"]["credit_closing_sek"], 444.00)
        self.assertEqual(summary["latest_period"]["amount_due_sek"], 0.0)
        self.assertNotIn("invoice_key", summary)
        self.assertNotIn("raw", summary)

    def test_summary_hides_unavailable_optional_values(self):
        summary = build_greenely_summary({"tariff": {}, "latest_period": {}}, None)
        self.assertIsNone(summary["tariff"]["variable_cost_ore_per_kwh_incl_vat"])
        self.assertIsNone(summary["latest_period"]["credit_closing_sek"])

    def test_spot_is_not_tariff_markup_and_credit_is_not_tariff(self):
        result = parse_greenely_invoice_text(
            "Spotpris 0,10 kWh 10,10 öre/kWh 0,01 kr Tillgodoräknande -483,00 kr"
        )
        self.assertNotIn("spot_rate_ore_per_kwh_ex_vat", result["tariff_candidates"])
        self.assertEqual(result["tariff_candidates"]["variable_cost_ore_per_kwh_ex_vat"], None)
        self.assertNotIn("Tillgodoräknande", result["tariff_candidates"])

    def test_debug_excerpt_preserves_lines_and_masks_sensitive_values(self):
        raw = """2026-07-01
Kund: user@example.com
Spotpris 0,10 kWh 10,10 öre/kWh 0,01 kr
OCR 123456789012
https://signed.example/invoice.pdf
"""
        _, diagnostics, excerpt = parse_greenely_invoice_diagnostics(raw)
        self.assertIn("Spotpris 0,10 kWh", excerpt)
        self.assertNotIn("user@example.com", excerpt)
        self.assertNotIn("OCR", excerpt)
        self.assertNotIn("https://", excerpt)
        self.assertIn("2026-07-01", excerpt)
        self.assertIn("10,10", excerpt)
        self.assertLessEqual(len(excerpt), 4000)
        self.assertIn("spot", diagnostics["matched_fields"])

    def test_installation_id_is_retained_for_single_installation(self):
        result = parse_greenely_invoice_text(
            "Anl.id: 735999248027541502 Elavtal: Testavtal, månadsavgift 39 kr "
            "Period: 2026-07-01 - 2026-07-31 Spotpris 0.10 kWh 10.10 öre/kWh 0.01 SEK "
            "Rörliga kostnader 0.10 kWh 17.00 öre/kWh 0.02 SEK "
            "Fast avgift 31.20 SEK/månad 31.20 SEK Moms 25 %"
        )
        self.assertEqual(result["installation_sections"][0]["installation_id"], "735999248027541502")

    def test_multiple_installations_are_not_collapsed(self):
        text = (
            "Anl.id: 735999248027541502 Spotpris 0.10 kWh 10.10 öre/kWh "
            "Anl.id: 735000114000851039 Spotpris 0.20 kWh 20.10 öre/kWh"
        )
        result = parse_greenely_invoice_text(text)
        self.assertEqual(
            [item["installation_id"] for item in result["installation_sections"]],
            ["735999248027541502", "735000114000851039"],
        )
        self.assertIn("multiple_installations_require_attribution", result["warnings"])


if __name__ == "__main__":
    unittest.main()
