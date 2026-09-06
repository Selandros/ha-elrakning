# Elräkning – Current State

Updated: 2026-09-06

Status labels: `VERIFIED` means directly supported by the recorded
static/runtime evidence; `INFERRED` means derived from documented code or
architecture; `UNKNOWN` means not established by the permanent evidence.

## Release and repository

- VERIFIED (repository/runtime activation, 2026-09-06): `0.0.620` is released
  in commit `f250a01` on `main`, deployed to Home Assistant, and served by the
  runtime static manifest after a Core restart. Deployed `energy_history.py`
  and `manifest.json`
  SHA-256 hashes matched the release files.
- VERIFIED (static, 2026-09-06): The `0.0.620` native-statistics-unit fix passes
  278 Python tests, 27 frontend Node tests, `compileall`, manifest JSON parsing,
  and `git diff --check`.
- VERIFIED (runtime semantic readback, 2026-09-06): The authenticated 30 August
  `energy_history` payload now contains plausible hourly battery values,
  including `3.7472135248561114 kW` discharge and
  `1.9403342397427776 kW` charge, with `resolution_seconds=3600` and preserved
  original source intervals. The previous 1000x error is absent.
- LIMITATION (runtime probe metadata, 2026-09-06): The browser probe returned
  `version: null` because it searched panel text rather than the manifest. The
  served manifest separately returned `0.0.620`; no cache clearing, credential
  extraction, debug logging, or temporary runtime API was used.

## Implemented and observed in the current codebase

- INFERRED (current-codebase statement; evidence not embedded): Persistent
  multi-site identity and site-scoped source bindings
- VERIFIED (static/runtime baseline, 2026-09-05): Global Nord Pool source is
  persisted as immutable global external input frames and remains separate
  from site-specific provider/grid economic layers.
- INFERRED (current-codebase statement): Site-scoped Forecast.Solar,
  Open-Meteo, PVGIS, Solar Shadow, and Solar Evidence namespaces
- INFERRED (current-codebase statement): Solar Evidence `evidence-v1` and daily
  finalization catch-up
- INFERRED (current-codebase statement): Forecast.Solar baselines with capture
  timestamps
- INFERRED (current-codebase statement): Open-Meteo and PVGIS physical
  installation context
- INFERRED (current-codebase statement): Read-only Recorder-backed power,
  meter, phase, solar, battery, and SOC history paths
- VERIFIED (static/runtime, 0.0.620, 2026-09-06): Price-period `energy_history` merges
  canonical observations with Home Assistant hourly long-term statistics.
  LTS statistics are requested in their native unit domain (`units=None`) so
  returned values and metadata remain paired; Elräkning converts exactly once.
  Configured grid/battery sign inversion is preserved, and import/export energy counters outrank
  net-power fallback. When higher-fidelity canonical data overlaps an hourly LTS
  bucket, the display fallback is clipped around canonical data while retaining
  the original hourly source interval and `resolution_seconds=3600`; no synthetic
  15-minute LTS records are created.
- INFERRED (current-codebase statement): Deterministic, read-only shadow
  calculations; no physical battery write path
- VERIFIED (static, 2026-09-05): P0-AUDIT-1 provides a temporary, source-agnostic
  24-hour cadence audit for the configured logical roles. It snapshots active
  source generations from SiteIdentity, passively observes report/change events,
  and exposes state/start/stop/cleanup diagnostics without writing physical
  device state or becoming the canonical long-term collector.

- VERIFIED (design, 2026-09-05): P0-DATA-1 canonical data contract v1 is
  frozen in `docs/architecture/P0_DATA_CONTRACT_V1.md` with a machine-readable
  contract and pure standard-library fixtures/validator. The minimum critical
  roles are house load, physical PV1/PV2, grid, battery power, and SOC.
  Prospective canonical data is 15-minute UTC-aligned data; historical
  Recorder/LTS bootstrap preserves truthful source resolution and never
  expands hourly data into synthetic quarters. The contract defines
  site/source-generation identity, provenance and identity strength,
  `known_at <= decision_at`, quality/gap semantics, immutable revisions,
  timezone/DST rules, global shared external frames, and active-site versus
  collection separation.
- VERIFIED (runtime baseline, 2026-09-05): The site-independent canonical
  collector is deployed and runtime-verified through release `0.0.603`. It
  resolves explicit site/source generations, uses source-declared semantics,
  writes schema-v1 900-second UTC observations, finalizes silent sources as
  explicit gaps, deduplicates report/change pairs and preserves source
  generations without using `active_site_id` as collection identity.
- IMPLEMENTED (current codebase; runtime not re-verified in this audit):
  E.ON grouped-contract economics can be persisted as immutable site-scoped
  external input frames on `EON_GRID_UPDATE_EVENT`. Only an explicitly bound
  facility with an active grouped contract, explicit gross/VAT semantics and
  an aware UTC source snapshot timestamp is accepted. Import transfer charge,
  import energy tax and fixed monthly subscription are separate roles. Missing
  components remain unavailable; export, demand/peak fees and a summed customer
  price are not fabricated. Provider date-only start/end validity is preserved
  as provenance and is not converted to UTC until site timezone semantics are
  verified. Source replacement creates a new generation; exact replay is
  idempotent and corrections use immutable revisions. Global Nord Pool frames
  are not modified by this producer.
- VERIFIED (design/benchmark, 2026-09-05): P0-STORAGE-1 benchmark harness is
  present in `tools/p0_storage_benchmark.py` with results recorded in
  `docs/architecture/P0_STORAGE_BENCHMARK.md`. A normalized SQLite candidate
  had the smallest measured one-site/year footprint and indexed range-query
  times; it is the selected physical schema-v1 implementation.
- VERIFIED (isolated recovery gate, 2026-09-05): P0-STORAGE-1B candidate
  checks pass in `tools/p0_storage_recovery_gate.py` and
  `tests/test_p0_storage_recovery_gate.py`. The temporary normalized SQLite
  candidate passed transaction rollback, duplicate replay idempotency,
  immutable revision/supersedes, source replacement without history rewrite,
  transactional schema migration and rollback, SQLite backup/restore,
  global-frame and `known_at` preservation, integrity/corruption detection,
  and local-write continuity when the backup target is unavailable. WAL,
  `synchronous=FULL`, and foreign keys are measured candidate settings only.
- VERIFIED (isolated process/filesystem gate, 2026-09-05): real killed-process,
  multi-year migration timing, local backup/restore, and NAS-unavailable
  behavior passed in the temporary test harness. Actual host power-cut and NAS
  hardware semantics remain unverified.
- VERIFIED (isolated process/filesystem gate, 2026-09-05):
  `tools/p0_storage_durability_gate.py` passed a real `SIGKILL` writer test,
  reopening and integrity-checking the database, proving the uncommitted
  partial transaction was absent and replay was idempotent. It also passed
  migration/reopen/query checks over 350,400 synthetic 15-minute rows (2 sites
  x 5 years), migration rollback, local backup/restore, target unavailability
  without blocking local writes, backup resumption, and the measured WAL/
  `synchronous=FULL`/foreign-key/busy-timeout profile.
- VERIFIED (physical schema gate, 2026-09-05): normalized SQLite is selected
  for canonical P0 storage v1. The SQL schema, field mapping, round-trip
  fixtures, source replacement, revisions, shared global frames, constraints,
  immutable triggers, integer UTC timestamp encoding, and operating profile
  pass `tools/p0_storage_schema_gate.py`. The physical contract is recorded in
  `docs/architecture/P0_STORAGE_SCHEMA_V1.md` and AD-022. Actual host power
  cut, NAS hardware semantics, hardware budget, and backup calendar remain
  operationally unverified/open.

## Verified data limitations

- VERIFIED (static/runtime audit, 2026-09-04): `PowerManager.async_history()`
  clamps requested history to seven days.
- VERIFIED (static/runtime audit, 2026-09-04): Frontend power-history requests
  currently use seven days.
- VERIFIED (configuration audit, 2026-09-04): SQLite Recorder with
  `purge_keep_days: 7`.
- VERIFIED (static audit, 2026-09-04): No compact long-term load/PV/battery/SOC
  series of its own.
- VERIFIED (static audit, 2026-09-04): `known_at` is not consistently
  persisted for forecast, price, and weather inputs.
- VERIFIED (runtime audit, 2026-09-05): The Site A source mapping, Recorder
  raw availability, Elräkning reader availability, and HA long-term-statistics
  metadata/boundaries/coverage audit passed for the audited load, PV, grid,
  battery, SOC, and phase signals.
- VERIFIED (runtime audit, 2026-09-05): All 16 audited signal IDs had matching
  HA long-term-statistics metadata with mean statistics. LTS provides a
  longer-lived hourly path than the approximately seven-day raw Recorder
  window.
- VERIFIED (runtime LTS common-overlap audit, 2026-09-05): The critical
  boundary overlap is 2026-01-16T08:00:00Z through 2026-09-05T12:00:00Z,
  with 5,573 expected hourly buckets and 5,406 simultaneously usable across
  house load, PV1, PV2, grid, battery power, and SOC. The longest fully
  contiguous all-critical interval is 907 hourly buckets from
  2026-01-24T10:00:00Z through 2026-03-03T04:00:00Z. Phase data remains P1.
- UNKNOWN (architecture/runtime audit required): Complete external/model-input
  collection for inactive sites. Canonical telemetry collection for explicit
  inactive `collection_enabled` sites is implemented and statically verified;
  full external-input collection remains not fully runtime-verified.
- VERIFIED (runtime audit, 2026-09-05): `sensor.total_consumption` is a
  battery-independent gross-house-load candidate for the four observed
  charging, discharging, PV-producing, and low/no-PV regimes.
- NOT RECOVERABLE (current persisted HA configuration): The original
  historical/current Jinja/template body and its direct template provenance
  for `sensor.total_consumption` and `sensor.pv_power_now_kw` could not be
  recovered through the available read-only methods. No source IDs were
  inferred from numerical matching alone.

## New read-only data-foundation evidence

- VERIFIED (runtime Recorder audit, 2026-09-05): A 24-hour sample of
  `sensor.total_consumption` contained 830 states; all 830 had the required
  attributes and satisfied `state_w = pv_w + grid_w + batt_w` with zero
  residual in the observed charging, discharging, PV-producing, and
  low/no-PV regimes.
- VERIFIED (runtime Recorder audit, 2026-09-05): In that normalized sample,
  grid power was positive for import and negative for export; battery power
  was positive while supplying the house and negative while charging.
- VERIFIED (current audit): The result makes `sensor.total_consumption` a
  valid battery-independent gross-house-load candidate for the observed
  regimes. It does not by itself establish long-term retention, source
  provenance, or universal semantics across sites.
- VERIFIED (runtime reader audit, 2026-09-05): Site A mappings used by
  Elräkning were identified as `sensor.total_consumption`; PV1/PV2
  `sensor.fsp_ne_130170834_pv_1_input_power` and
  `sensor.fsp_ne_130170834_pv_2_input_power`; battery
  `sensor.fsp_ne_175846905_charge_discharge_power`; SOC
  `sensor.fsp_ne_175846905_state_of_charge`; grid
  `sensor.fsp_ne_175849203_active_power`; and discovered phase current,
  voltage, and active-power entities for L1-L3 under the same meter device.
- VERIFIED (runtime reader audit, 2026-09-05): Elräkning could read its mapped
  power history for up to seven local days and its meter/phase reader could
  read the current local day.
- VERIFIED (runtime LTS audit, 2026-09-05): All 16 requested statistic IDs
  were present with mean metadata and the audited LTS boundaries/coverage had
  no reported hard gaps.
- VERIFIED (runtime LTS common-overlap audit, 2026-09-05): The minimum
  critical replay/training contract uses house load
  `sensor.total_consumption`, physical PV1/PV2, grid power, battery power,
  and battery SOC.
- VERIFIED (runtime LTS common-overlap audit, 2026-09-05): Critical boundary
  overlap is `2026-01-16T08:00:00Z` through `2026-09-05T12:00:00Z`, with 5,573
  expected hourly buckets. The all-critical usable intersection contains
  5,406 buckets (97.00%); 167 boundary buckets have at least one missing
  critical signal.
- VERIFIED (runtime LTS common-overlap audit, 2026-09-05): The longest fully
  contiguous all-critical interval is
  `2026-01-24T10:00:00Z` through `2026-03-03T04:00:00Z`, containing 907
  hourly buckets without a missing critical bucket.
- VERIFIED (runtime LTS common-overlap audit, 2026-09-05): Phase current,
  voltage, and active-power series are not minimum replay requirements and are
  classified as P1 data for peak/fuse, phase-balance, diagnostics, and future
  safety-controller work. Their audited coverage was approximately 5,408/5,573
  buckets (97.04%) with 15 gaps.

## Point 7 planning status

- VERIFIED (read-only audit closure, 2026-09-05): Point 7B is closed for the
  planning phase. Site A source mapping, Recorder raw availability, Elräkning
  reader availability, HA long-term-statistics metadata/boundaries/coverage,
  and observed `sensor.total_consumption` runtime semantics are verified.
- LIMITATION (non-blocking for planning): The original Jinja/template body and
  direct template dependency provenance for `sensor.total_consumption` and
  `sensor.pv_power_now_kw` are not recoverable from the current persisted HA
  configuration through the available read-only methods. No source IDs were
  inferred from numerical matching.
- PLANNING CONSEQUENCE: The template provenance limitation must not be
  presented as verified dependencies. It does not invalidate the runtime
  gross-load evidence or block planning, but any future canonical collector
  must record explicit source identity and provenance from the point it begins
  collecting.

- PLANNING STATUS: The common-overlap audit completes the read-only point 7
  data audit for planning. It does not remove the P0 risk: Elräkning still
  lacks its own canonical long-term 15-minute collection with provenance,
  quality, and `known_at`.

## Plan 2.0 reconciliation

- VERIFIED (repository architecture, 2026-09-06): The current masterplan now
  explicitly preserves Plan 2.0 requirements for global shared intelligence,
  site-independent collection, source generations, shared external sources,
  Fiskvik day-one P0 collection, P1/smartplug expansion, Battery Health/SOH,
  historical product prices, deterministic MPC/LP/MILP, zero-write shadow,
  replay safety, storage diagnostics, NAS boundaries, and the full dataset
  catalogue.
- INFERRED (roadmap): `energy_history` is currently exposed through the price
  data WebSocket and is not yet a general Hour/Day/Month/Year history service.
  A later history-service scope must preserve canonical/LTS provenance and
  truthful source resolution while making price only one consumer.
- UNKNOWN (runtime gate): source-generation-specific cadence/stale thresholds
  and complete inactive-site external-input collection are not yet fully
  runtime-verified.

## Permanent data-foundation risks and gates

- IRREVERSIBLE DATA RISK (P0): Recorder/raw model-relevant history is currently
  short-retained or unverified beyond the observed window. Load, PV, grid,
  battery, SOC, price, and forecast history needed for future replay must be
  captured with provenance before it expires.
- MEMORY UPDATE REQUIRED: The canonical foundation must explicitly preserve
  source generation, sign convention, meter reset/rollover, quality states,
  schema version, `known_at`, DST-safe timestamps, and dataset-specific
  deduplication.
- MEMORY UPDATE REQUIRED: Backtest acceptance must include event replay,
  price-publication state, missing/stale data, DST, source changes, and
  reproducible dataset/model/calibration/parameter identities.
- MEMORY UPDATE REQUIRED: Safety acceptance must include zero-write shadow
  enforcement, hard limits, stale-input rejection, safe fallback,
  acknowledgement/timeout, command deduplication, and wrong-site prevention.
- MEMORY UPDATE REQUIRED: Evaluation must compare rule baselines and oracle,
  and separate forecast-driven regret from optimizer-driven regret.

## Current storage observations

VERIFIED (read-only measurement, 2026-09-04): The read-only audit measured:

- Elräkning-owned `.storage` files: `4.91 MiB`
- largest store: Solar Shadow, approximately `4.38 MiB` across global and
  Site A namespaces
- HA Recorder SQLite database: approximately `814 MiB`

These are point-in-time measurements, not growth-rate guarantees. Growth rate
is UNKNOWN.

## Architecture roadmap (LOCKED direction, not implementation status)

The intended dependency order is: canonical data contract; long-term storage;
site-independent collection; immutable known-at frames; quality/provenance;
Recorder/statistics verification; replay/backtest; digital twin; baselines/KPIs;
optimizer V1; shadow; forecast/calibration; Battery Health/degradation; Fiskvik
expansion; flexible loads; fast safety control; real-control adapter and safety
review; only then possible physical control. Peak/fuse safety may develop in
parallel, but physical control remains gated on its completion and verification.

## Next architectural milestone

INFERRED (roadmap): Long-term data foundation:

1. separate background collection from UI active-site context;
2. define compact 15-minute model data with `site_id`, `observed_at`,
   `known_at`, source fingerprints, and quality;
3. freeze forecast/price/weather input frames;
4. establish deterministic replay and battery digital-twin backtesting;
5. keep Vikarbodarna shadow-only and make Fiskvik collection-ready from day
   one.
