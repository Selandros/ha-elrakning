import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "diagnostics.py"
spec = spec_from_file_location("diagnostics", path)
module = module_from_spec(spec)
spec.loader.exec_module(module)
append = module.append_diagnostic
sanitize = module.sanitize_diagnostic_text


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
