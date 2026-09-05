# P0-STORAGE-1B2 process and filesystem durability gate

Status: benchmark/test-only. The gate creates temporary databases and does not
touch Home Assistant, production storage, a collector, or runtime data.

`tools/p0_storage_durability_gate.py` verifies:

- a separate writer process is killed with `SIGKILL` during an open SQLite
  transaction;
- the database reopens with `PRAGMA integrity_check`, the partial transaction
  is absent, the baseline revision/source state is preserved, and replay is
  idempotent;
- migration timing and query correctness at 2 sites x 5 years x 15-minute
  rows (350,400 rows), including migration rollback on failure;
- local backup/restore, target unavailability while local writes continue, and
  backup resumption after the target returns;
- the measured SQLite profile is WAL, `synchronous=FULL`, foreign keys on,
  and a 5-second busy timeout.

This proves process-kill behavior and the tested filesystem path only. It does
not claim an actual host power cut, NAS hardware semantics, or production
backup policy. Physical schema selection remains open until the measured
results are reviewed against the canonical contract and hardware budget.

Run:

```text
python3 tools/p0_storage_durability_gate.py
python3 -m unittest tests/test_p0_storage_durability_gate.py
```
