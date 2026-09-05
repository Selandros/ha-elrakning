# P0-STORAGE-1 benchmark

Status: benchmark harness only. No collector, production store, migration, or
runtime configuration is introduced by this artifact.

The benchmark measures candidates against the frozen P0-DATA-1 workload:
site-scoped records, six critical role rows per UTC quarter, nested quality and
provenance fields, multiple sites, source generations, and range queries. It
also measures a file-copy backup and verifies that the copy has the same byte
size. The harness uses only Python standard-library facilities and writes only
to a temporary directory.

Run:

```text
python3 tools/p0_storage_benchmark.py --days 365 --sites 1
```

The first measured candidates are SQLite with explicit site/time and
site/role/time indexes, and append-only JSONL. JSONL is included as a control
candidate because it has simple append semantics; a full range query is a
linear scan. SQLite is not selected by this document before measurements are
reviewed.

Required benchmark workload and decision gates:

- 1 site / 1 year, 2 sites / 5 years, and 5 sites / 10 years sizing;
- write throughput and idempotent duplicate/revision behavior;
- 24-hour, 30-day, one-year, and multi-year range queries;
- site, logical-role, and source-generation filtering;
- source replacement and immutable revision cases;
- storage growth including quality/provenance metadata;
- crash/restart, partial-write, migration, backup, restore, and NAS-unavailable
  behavior;
- representation of every v1 contract field without semantic loss.

This first harness provides measured local data points for write, query, size,
and backup behavior. It does not claim that a candidate is production-ready;
the P0-STORAGE-1 gate remains open until the complete workload and recovery
acceptance are documented.

## Initial measured run

Measured locally on 2026-09-05 with Python 3.13.2 and SQLite 3.45.3, using
one site, 365 days, six critical role records per 15-minute interval, and
210,240 contract-enveloped rows. These figures are benchmark evidence for this
machine and workload, not universal performance guarantees.

| Candidate | Bytes | Write seconds | 24h query seconds | 30d query seconds | 1y query seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| JSONL | 263,068,215 | 0.707 | 0.538153 | 0.538879 | 0.528859 |
| SQLite with JSON payload | 312,283,136 | 0.764 | 0.000075 | 0.000283 | 0.003163 |
| SQLite normalized source metadata | 104,312,832 | 1.722 | 0.000053 | 0.000291 | 0.003331 |

The normalized SQLite candidate stores stable source-generation metadata once
and keeps contract fields/query keys in the observation table. It is the best
measured candidate so far for size and range-query behavior, while JSONL is the
fastest write control but has a linear range-query cost. No final production
selection is made until recovery, migration, backup/restore, partial-write,
and NAS-unavailable gates are measured.

Calculated sizing from the measured one-site/year bytes, explicitly marked as
projections rather than measurements:

| Scenario | Rows | JSONL | SQLite normalized |
| --- | ---: | ---: | ---: |
| 1 site / 1 year | 210,240 | 251 MiB | 99 MiB |
| 2 sites / 5 years | 2,102,400 | 2,507 MiB | 994 MiB |
| 5 sites / 10 years | 10,512,000 | 12,534 MiB | 4,969 MiB |

The benchmark therefore narrows the next gate to a normalized SQLite
recovery/migration benchmark and an explicit policy for whether the payload
fields that are currently normalized in the prototype remain lossless under
schema evolution. It does not create a runtime store or start collection.
