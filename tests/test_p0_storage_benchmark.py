import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/p0_storage_benchmark.py"


class P0StorageBenchmarkTests(unittest.TestCase):
    def test_small_contract_workload_runs_for_both_candidates(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--days", "2", "--sites", "1"],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["workload"]["rows"], 2 * 96 * 6)
        self.assertEqual(set(result["candidates"]), {"sqlite", "sqlite_normalized", "jsonl"})
        for candidate in result["candidates"].values():
            self.assertGreater(candidate["bytes"], 0)
            self.assertEqual(candidate["bytes"], candidate["backup_bytes"])
            self.assertEqual(candidate["query_seconds"]["24h"]["rows"], 96 * 6)


if __name__ == "__main__":
    unittest.main()
