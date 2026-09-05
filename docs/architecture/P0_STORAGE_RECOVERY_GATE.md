# P0-STORAGE-1B recovery and durability gate

Status: isolated candidate gate only. It creates temporary SQLite databases and
does not touch Home Assistant, production files, a collector, or runtime data.

`tools/p0_storage_recovery_gate.py` exercises the normalized SQLite candidate
against the failure modes required before a physical storage decision:

- transaction rollback for an uncommitted partial write;
- duplicate replay idempotency;
- immutable revision plus `supersedes_record_id`;
- source replacement without overwriting old history;
- schema migration and transactional migration rollback;
- online SQLite backup API and restore into an empty database;
- restored global frame scope and `known_at` preservation;
- SQLite integrity check and deliberate corruption detection;
- local writes continuing when a backup target is unavailable.

The harness also enables WAL, `synchronous=FULL`, and foreign keys for the
candidate test. These are measured candidate settings, not a production choice.
The gate does not yet simulate a real killed subprocess at every write phase,
large multi-year migration timing, filesystem power-loss behavior, or an actual
NAS. Those remain explicit acceptance work before P0-STORAGE-1 can be closed.

Run:

```text
python3 tools/p0_storage_recovery_gate.py
python3 -m unittest tests/test_p0_storage_recovery_gate.py
```

The result is PASS only when every named result is true. A PASS here is not a
final storage selection; it is the isolated recovery prerequisite for the
subsequent physical schema and migration gate.
