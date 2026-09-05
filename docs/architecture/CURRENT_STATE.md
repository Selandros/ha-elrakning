# Elräkning – Current State

Updated: 2026-09-05

Status labels: `VERIFIED` means directly supported by the recorded
static/runtime evidence; `INFERRED` means derived from documented code or
architecture; `UNKNOWN` means not established by the permanent evidence.

## Release and repository

- VERIFIED (static, 2026-09-04): Current repository manifest: `0.0.594`
- VERIFIED (static, 2026-09-04): Branch: `main`
- VERIFIED (static, 2026-09-04): HEAD: `aee4254a6cf8ccc8a8c4c4aad5795fb177b3d00b`
- VERIFIED (recorded 2026-09-04): HEAD matched `origin/main`
- VERIFIED (static): This documentation change does not change production code
  or release version.

## Implemented and observed in the current codebase

- INFERRED (current-codebase statement; evidence not embedded): Persistent
  multi-site identity and site-scoped source bindings
- INFERRED (current-codebase statement): Global Nord Pool source with
  site-specific provider/grid layers
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
- INFERRED (current-codebase statement): Deterministic, read-only shadow
  calculations; no physical battery write path

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
- UNKNOWN (runtime/storage audit required): Exact per-entity Recorder
  retention and long-term-statistics coverage.
- UNKNOWN (architecture/runtime audit required): Separate background collector
  for inactive sites.
- UNKNOWN (runtime semantics audit required): Exact battery/PV-normalized
  physical meaning of `sensor.total_consumption` as a universal canonical
  source outside the observed regimes and source provenance per site.

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
- UNKNOWN (read-only audit required): Exact source entity IDs behind
  `sensor.total_consumption` and their long-term-statistics coverage.
- UNKNOWN (read-only audit required): Long-term statistics and common overlap
  for load, PV, grid import/export, battery power, SOC, phase data, and
  outdoor temperature.

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
