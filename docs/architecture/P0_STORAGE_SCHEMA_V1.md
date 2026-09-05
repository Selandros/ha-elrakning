# P0-STORAGE-1C physical schema v1

Status: PASS as a design and isolated schema gate on 2026-09-05. This is not
production storage and does not implement collection.

## Selected candidate

Normalized SQLite is selected for canonical P0 storage v1. The selection is
based on the P0-STORAGE-1A benchmark, logical recovery gate, process/filesystem
durability gate, and the schema/round-trip gate in
`tools/p0_storage_schema_gate.py`. JSONL remains a benchmark reference and a
JSON-payload SQLite table remains a comparison baseline; neither is selected.

The database is installation-owned and can contain multiple sites and global
shared sources. `active_site_id` is not stored as collection identity.

## Physical tables

- `schema_meta` and `schema_migrations` hold explicit schema identity and
  migration checksums.
- `source_generations` owns site/global source identity, generation boundaries,
  identity strength, provenance, source resolution, and timezone state.
- `energy_observations` stores native canonical 900-second site observations.
- `historical_energy_observations` stores truthful bootstrap data at its actual
  source resolution; it is physically separate from native canonical data.
- `external_input_frames` stores immutable price/tariff/weather/forecast
  vintages, and `external_input_points` stores their time-valued points.

The runtime SQL definition is the packaged asset
`custom_components/elrakning/p0_storage_schema_v1.sql`; the schema gate reads
that same asset. The older documentation path
`docs/architecture/contracts/p0_storage_schema_v1.sql` remains a design
reference for the initial schema review. The field-level mapping is in
`p0_storage_schema_v1.mapping.json`.

## Encoding and invariants

Opaque identifiers are `TEXT`, not UUID-only columns, because source IDs are
not guaranteed to be UUIDs and readable IDs simplify backup/debug/restore.
The variant benchmark measured 987,136 bytes for 10,000 TEXT identifiers and
548,864 bytes for BLOB identifiers; this is an explicit portability/debug
trade-off, not an unmeasured assumption. UTC timestamps are `INTEGER`
microseconds since Unix epoch. Units, signs, quality, and provenance remain
explicit; extensible quality/provenance details remain JSON payloads while
query-critical identity/time fields are normalized.

Constraints and triggers enforce global/site scope ownership, foreign keys,
duplicate semantic revision rejection, same-semantic supersedes chains,
immutable observation/frame rows, and unique points within a frame. Source
replacement is represented by a new source generation and never by rewriting
old history.

The tested operating profile is WAL, `synchronous=FULL`, foreign keys enabled,
and a 5-second busy timeout. Transaction boundaries, WAL checkpoint policy,
backup from a consistent local snapshot, and sequential migration checksums
are part of the physical contract.

## Gate and limits

The gate round-trips canonical energy, historical hourly bootstrap, shared
global external frames, revisions, source replacement, `known_at`, quality,
and provenance. It also rejects `active_site_id` as a storage field.

The gate does not claim an actual host power cut, NAS hardware failure
semantics, production hardware budget, or production backup calendar. Those
are operational limits, not reasons to hide the selected schema. The next
scope is P0-COLLECT-1; it must use this schema without silently changing the
contract, and the full test environment must restore the known `voluptuous`
dependency before the first production write-path release.
