import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/p0_storage_schema_gate.py"


class P0StorageSchemaGateTests(unittest.TestCase):
    def test_physical_schema_gate_passes(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)], check=True, capture_output=True, text=True
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["ok"], result)
        self.assertTrue(all(result["checks"].values()))


if __name__ == "__main__":
    unittest.main()
