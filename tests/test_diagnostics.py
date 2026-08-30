import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "diagnostics.py"
spec = spec_from_file_location("diagnostics", path)
module = module_from_spec(spec)
spec.loader.exec_module(module)
append = module.append_diagnostic
sanitize = module.sanitize_diagnostic_text
sanitize_source = module.sanitize_source_data


class DiagnosticsTests(unittest.TestCase):
    def test_append_and_limit(self):
        logs = []
        for index in range(501):
            append(logs, "INFO", "test", str(index), "message")
        self.assertEqual(len(logs), 500)
        self.assertEqual(logs[0]["event"], "1")

    def test_secrets_are_redacted(self):
        self.assertNotIn("jwt-value", sanitize("jwt-value"))
        self.assertNotIn("https://secret.example", sanitize("https://secret.example"))

    def test_levels_are_normalized(self):
        logs = []
        append(logs, "NOPE", "source", "source_failed", "failed")
        self.assertEqual(logs[0]["level"], "INFO")

    def test_source_data_redacts_sensitive_nested_keys(self):
        result = sanitize_source({
            "customer_id": "customer-placeholder",
            "locations": [{
                "installation": {"id": "installation-placeholder"},
                "address": {"city": "Exampletown"},
            }],
            "price": 12.5,
        })
        self.assertEqual(result["customer_id"], "customer-placeholder")
        self.assertEqual(result["locations"][0]["installation"]["id"], "installation-placeholder")
        self.assertEqual(result["locations"][0]["address"]["city"], "Exampletown")
        self.assertEqual(result["price"], 12.5)

    def test_source_data_preserves_provider_data_and_redacts_auth_secrets(self):
        payload = {
            "email": "person@example.test",
            "firstName": "Test",
            "lastName": "Person",
            "postalCode": "123 45",
            "ipAddress": "192.0.2.1",
            "meterId": "meter-placeholder",
            "facilityId": "facility-placeholder",
            "siteId": "site-placeholder",
            "billLocationId": "bill-placeholder",
            "contractId": "contract-placeholder",
            "invoiceKey": "invoice-placeholder",
            "userId": "user-placeholder",
            "customerId": "customer-placeholder",
            "accountIds": ["account-placeholder"],
            "pod": "pod-placeholder",
            "installationId": "installation-placeholder",
            "premiseId": "premise-placeholder",
            "safe_value": 42,
            "access_token": "access-placeholder",
            "refreshToken": "refresh-placeholder",
            "Authorization": "Bearer placeholder",
            "MyEonSession": "session-placeholder",
            "password": "password-placeholder",
        }
        result = sanitize_source(payload)
        for key in ("email", "firstName", "lastName", "postalCode", "ipAddress", "meterId", "facilityId", "siteId", "billLocationId", "contractId", "invoiceKey", "userId", "customerId", "accountIds", "pod", "installationId", "premiseId"):
            self.assertEqual(result[key], payload[key])
        self.assertEqual(result["safe_value"], 42)
        for key in ("access_token", "refreshToken", "Authorization", "MyEonSession", "password"):
            self.assertEqual(result[key], "[redacted]")

    def test_clear_is_empty_and_sensitive_messages_are_redacted(self):
        logs = []
        append(logs, "INFO", "source", "loaded", "credentials were used")
        logs.clear()
        self.assertEqual(logs, [])
        self.assertEqual(sanitize("Authorization: JWT secret-value"), "Sensitive diagnostic data redacted")

    def test_startup_session_is_new_and_versioned(self):
        logs = [{"event": "old_event"}]
        logs.clear()
        append(logs, "INFO", "integration", "integration_start", "Integration started · Version: 0.0.64")
        self.assertEqual(len(logs), 1)
        self.assertIn("Version: 0.0.64", logs[0]["message"])


if __name__ == "__main__":
    unittest.main()
