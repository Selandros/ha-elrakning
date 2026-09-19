import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "elhandel" / "providers" / "greenely_source.py"
spec = spec_from_file_location("greenely_source", path)
module = module_from_spec(spec)
spec.loader.exec_module(module)
sanitize = module.sanitize_greenely_source
merge = module.merge_consumption_samples
paginate = module.paginate_source


class GreenelySourceTests(unittest.TestCase):
    def test_recursive_sanitizer_keeps_safe_fields(self):
        result = sanitize({"password": "x", "jwt": "y", "pdf_url": "https://x", "personnummer": "x", "facility_id": "facility-1", "price_area": "SE3", "timezone": "Europe/Stockholm", "nested": [{"usage": 63, "localtime": "2026-08-01"}]})
        self.assertNotIn("password", result)
        self.assertNotIn("jwt", result)
        self.assertNotIn("pdf_url", result)
        self.assertEqual(result["facility_id"], "facility-1")
        self.assertEqual(result["price_area"], "SE3")
        self.assertEqual(result["nested"][0]["usage"], 63)

    def test_recursive_sanitizer_removes_greenely_personal_source_fields(self):
        result = sanitize({
            "email": "person@example.test",
            "first_name": "Test",
            "last_name": "Person",
            "cell_phone": "+46000000000",
            "ip_address": "192.0.2.1",
            "street": "Example street",
            "address": {"city": "Exampletown"},
            "customer_id": "customer-placeholder",
            "meter_id": "meter-placeholder",
            "facility_id": "facility-placeholder",
        })
        for key in (
            "email", "first_name", "last_name", "cell_phone", "ip_address",
            "street", "address", "customer_id", "meter_id",
        ):
            self.assertNotIn(key, result)
        self.assertEqual(result["facility_id"], "facility-placeholder")

    def test_sample_merge_is_idempotent_and_updates(self):
        old = [{"source_timestamp": "100", "usage_wh": 63, "localtime": "2026-08-01T01:00:00"}]
        new = [{"source_timestamp": "100", "usage_wh": 64, "localtime": "2026-08-01T01:00:00"}, {"source_timestamp": "200", "usage_wh": 32, "localtime": "2026-08-01T02:00:00"}]
        result = merge(old, new)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["usage_wh"], 64)

    def test_pagination_is_bounded(self):
        result = paginate(list(range(600)), 10, 1000)
        self.assertEqual(result["total"], 600)
        self.assertEqual(len(result["items"]), 500)


if __name__ == "__main__":
    unittest.main()
