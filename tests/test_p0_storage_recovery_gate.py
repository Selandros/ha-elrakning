import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/p0_storage_recovery_gate.py"


class P0StorageRecoveryGateTests(unittest.TestCase):
    def test_isolated_recovery_gate_passes(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)], check=True, capture_output=True, text=True
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["ok"], result)
        self.assertTrue(all(result["results"].values()))


if __name__ == "__main__":
    unittest.main()
