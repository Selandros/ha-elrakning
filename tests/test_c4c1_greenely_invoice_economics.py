"""Focused tests for the C.4C.1 Greenely invoice economics slice."""

import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)


install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning.elhandel.providers.greenely_invoice_economics import (
    DATASET,
    GreenelyInvoiceEconomicsProducer,
    _latest_invoice,
    _period_bounds,
    _source_generation,
)
from custom_components.elrakning.site_identity import SiteIdentityManager


class TestC4C1GreenelyInvoiceEconomics(unittest.TestCase):
    def test_latest_invoice_is_deterministic_and_ties_fail_closed(self):
        selected = _latest_invoice([
            ("c1", {"invoice_date": "2026-07-01", "due_date": "2026-07-15", "month": "2026-06", "ocr_number": "a"}),
            ("c2", {"invoice_date": "2026-08-01", "due_date": "2026-08-15", "month": "2026-07", "ocr_number": "b"}),
        ])
        self.assertEqual(selected[0], "c2")
        with self.assertRaises(ValueError):
            _latest_invoice([
                ("c1", {"invoice_date": "2026-08-01", "due_date": "2026-08-15", "month": "2026-07"}),
                ("c2", {"invoice_date": "2026-08-01", "due_date": "2026-08-15", "month": "2026-07"}),
            ])

    def test_invoice_period_uses_site_timezone_and_dst_boundaries(self):
        start, end = _period_bounds({"period_start": "2026-10-24", "period_end": "2026-10-25"}, "Europe/Stockholm")
        self.assertEqual(start, datetime(2026, 10, 23, 22, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 10, 25, 23, tzinfo=timezone.utc))
        spring_start, spring_end = _period_bounds({"period_start": "2026-03-29", "period_end": "2026-03-29"}, "Europe/Stockholm")
        self.assertEqual((spring_end - spring_start).total_seconds(), 23 * 3600)

    def test_generation_excludes_occurrence_and_values(self):
        target = {"binding": {"config_entry_id": "entry", "binding_fingerprint": "bind", "facility_id": "facility"}, "timezone": "Europe/Stockholm"}
        proof = {"proof_semantic_identity": "proof-semantic"}
        first, identity = _source_generation(target, proof, "entry", "contract")
        second, _ = _source_generation(target, proof, "entry", "contract")
        self.assertEqual(first, second)
        self.assertEqual(identity["dataset_identity"], DATASET)
        self.assertNotIn("occurrence", json.dumps(identity))
        self.assertNotIn("value", json.dumps(identity))

    def test_proof_fingerprint_is_versioned_and_deterministic(self):
        payload = {"installation_id": "opaque"}
        first = SiteIdentityManager.identity_fingerprint(payload)
        second = SiteIdentityManager.identity_fingerprint(payload)
        self.assertEqual(first, second)
        self.assertNotEqual(first, SiteIdentityManager.identity_fingerprint({"installation_id": "changed"}))

    def test_target_token_changes_when_site_ownership_changes(self):
        target = {"site_id": "site-a", "binding": {"config_entry_id": "entry", "binding_fingerprint": "bind-a", "facility_id": "facility-a"}, "timezone": "Europe/Stockholm"}
        proof = {"proof_fingerprint": "proof-a"}
        first = GreenelyInvoiceEconomicsProducer._target_token(target, proof, "key-a")
        changed = dict(target, binding=dict(target["binding"], binding_fingerprint="bind-b"))
        self.assertNotEqual(first, GreenelyInvoiceEconomicsProducer._target_token(changed, proof, "key-a"))
        self.assertNotEqual(first, GreenelyInvoiceEconomicsProducer._target_token(target, proof, "key-b"))


if __name__ == "__main__":
    unittest.main()
