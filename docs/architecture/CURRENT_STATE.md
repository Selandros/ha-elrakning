# Elräkning – Current State

Updated: 2026-09-13

Status labels: `VERIFIED` means directly supported by the recorded
static/runtime evidence; `INFERRED` means derived from documented code or
architecture; `UNKNOWN` means not established by the permanent evidence.

## Release and repository

- VERIFIED (runtime, 2026-09-06): Release `0.0.624` is deployed and runtime
  accepted for the provider-attribution/current-price fix. Authenticated
  A→B→A→B verification showed Vikarbodarna consistently restoring 51 invoices,
  its attributed current summary, and `electricity_cost_ex_vat=0.17` SEK/kWh.
  Fiskvik consistently remained at zero invoices, null summary, null
  consumption, and null current Greenely cost. E.ON remained `FUTURE`; its
  preview was retained and `grid_cost_ex_vat` remained null.
- VERIFIED (scope boundary, 2026-09-06): The separate E.ON global
  multi-facility/facility-selection risk is not resolved by this release and
  remains a follow-up scope.
- VERIFIED (runtime, 0.0.626, 2026-09-06): E.ON shared-facility acceptance
  passed on authenticated Home Assistant runtime through A→B→A→B. Both sites
  retained the same explicit strong binding to installation `40093679` and
  POD `735999114000851039`, with
  `identity_provenance=legacy_context_reconciled_unique` and
  `identity_strength=strong`. Restart persistence also passed.
- VERIFIED (runtime, 0.0.626, 2026-09-06): Vikarbodarna retained its 51
  Greenely invoices and `electricity_cost_ex_vat=0.17`; Fiskvik remained at
  zero invoices, null Greenely summary/consumption/current cost; E.ON remained
  `FUTURE` with `grid_cost_ex_vat=null` across the switch sequence.
- VERIFIED (scope boundary, 0.0.626, 2026-09-06): Shared-facility E.ON
  behavior is runtime verified. Distinct multi-facility X/Y isolation is
  test-verified only because the current real configuration uses one shared
  facility; it is not claimed as runtime verified.
- VERIFIED (runtime, 0.0.627, 2026-09-06): Step C.1 external-frame
  integrity and decision-time replay reader are complete on the real
  canonical SQLite database. Additive integrity migration 2 is present,
  `external_input_points` UPDATE/DELETE immutability triggers are active,
  SQLite integrity is `ok`, and the existing 38 real global frames with 3,648
  points remain readable after restart.
- VERIFIED (runtime, 0.0.627, 2026-09-06): The global replay path reads real
  Nord Pool frames, filters by `decision_at`, excludes frames with
  `known_at > decision_at`, survives reopen/restart, and uses the replay
  indexes. The current E.ON `FUTURE` contract correctly produces no current
  economic frames; this is expected fail-closed runtime semantics.
- TEST VERIFIED (0.0.627, 2026-09-06): Site-scoped replay selection against a
  real E.ON economic frame is covered by tests, but is not runtime-verified
  because no legitimate site-scoped E.ON frame exists while the contract is
  `FUTURE`. This is an evidence limitation, not a C.1 implementation blocker.
- FUTURE VERIFICATION NOTE: When a legitimate site-scoped economic frame
  first exists in runtime, verify the `decision_at` reader against it without
  changing the C.1 implementation.
- VERIFIED (scope boundary, 0.0.627, 2026-09-06): Step C.1 is complete.
  Global path is runtime verified; site-scoped real-frame path is test
  verified with runtime evidence pending. Step C.2 begins with a read-only
  design/audit of Forecast.Solar and Open-Meteo immutable capture plus
  site-independent `collection_enabled` semantics. No C.2 implementation is
  included here.
- VERIFIED (runtime, 0.0.628, 2026-09-06): Step C.2.0 site-context isolation
  passed on authenticated Home Assistant runtime through A→B→A→B, both
  before and after a normal Home Assistant Core restart. Forecast.Solar
  returned `available=true` with the Vikarbodarna site id and the same ten
  Vikarbodarna baselines at A1 and A2. Fiskvik returned
  `available=false`/unconfigured at B1 and B2, with no Vikarbodarna
  baselines exposed.
- VERIFIED (runtime persistence, 0.0.628, 2026-09-06): Forecast.Solar and
  Open-Meteo namespaced Store isolation passed read-only before and after the
  authenticated switch sequence and restart. The Vikarbodarna stores kept
  their ownership and hashes; Fiskvik had no namespaced Forecast.Solar or
  Open-Meteo store, and no cross-site persistence contamination was observed.
  Global legacy stores were not used as evidence of Fiskvik ownership.
- TEST VERIFIED (0.0.628, 2026-09-06): Open-Meteo in-memory stale-state
  clearing, obsolete-response discard, out-of-order response protection, and
  context/request-generation guards are covered by regression tests. The
  Open-Meteo manager has no public websocket read command for direct live-state
  inspection, so those internal protections are not promoted to runtime
  manager-state evidence.
- VERIFIED (scope boundary, 0.0.628, 2026-09-06): Step C.2.0 is complete.
  Runtime-verified evidence covers normal site-context switching,
  Forecast.Solar empty-site fail-closed behavior, namespaced Store ownership,
  persistence across restart, and absence of cross-site persistence
  contamination. Concurrency guards remain test-verified only when no natural
  in-flight race is observed. The next scope is Step C.2.1: producer-contract
  fixtures/design for immutable Forecast.Solar and Open-Meteo frames. No C.2.1
  implementation is included here.
- VERIFIED (runtime release, 0.0.634, 2026-09-12): Step C.2.2 Forecast.Solar
  immutable canonical capture is complete. The exact release commit was
  `2f83eec`. After a normal Home Assistant Core restart, a natural
  Forecast.Solar burst while Fiskvik was active produced six source events but
  only two new canonical revisions: one each for the changed
  `remaining_today_kwh` and `power_now_kw` observations. Their `target_point`
  values matched the real HA observation timestamps. The following unchanged
  events were deduplicated and created no additional revisions.
- VERIFIED (runtime release, 0.0.634, 2026-09-12): The final C.2.2
  post-burst WAL-consistent audit reported `integrity_check=ok`, 533 canonical
  frames, 4,857 canonical points, 487 Forecast.Solar frames, zero duplicate
  `point_id`, zero duplicate `(semantic_key, revision)`, zero broken
  supersedes chains, zero non-null Forecast.Solar `published_at`, 487
  Vikarbodarna Forecast.Solar frames, and zero Fiskvik Forecast.Solar frames.
  No new defined Forecast.Solar persistence errors were found in the
  post-restart burst log scan. `tomorrow_kwh` and `peak_time_tomorrow`
  retained their D+1 target semantics.
- VERIFIED (scope boundary, 0.0.634, 2026-09-12): Site-independent
  Forecast.Solar collection, Fiskvik empty-site isolation, concurrent
  persistence serialization, HA observation identity, capture-relative target
  semantics, and post-restart replay/persistence are runtime verified.
  C.2.2 is closed; no 0.0.635 release is required for this scope.
- VERIFIED (non-regression, 0.0.634, 2026-09-12): Solar Evidence remained
  unchanged during the C.2.2 gate: 39 days, Open-Meteo progress 14, Forecast.Solar
  common progress 13, and the recorded full and semantic hashes were unchanged
  from the pre-release baseline. The known Evidence `collected_at`
  immutability issue remains a separate known fail and was not changed or
  reclassified by C.2.2.
- VERIFIED (scope boundary, 2026-09-12): The next scope after C.2.2 is the
  next immutable external-input foundation milestone. It must preserve the
  locked C.2.1 dataset identities, `known_at`/decision-time replay rules,
  source-generation provenance, and Solar Evidence non-regression contract.
- VERIFIED (release/recovery, 0.0.636, 2026-09-13): The exact release commit
  is `c16b18a9d1e6ee3719ac7136837d579dc3c2d5de`, with `HEAD == origin/main`.
  The release commit only bumps the manifest from 0.0.635 to 0.0.636; the
  recovery was deployed as a full eight-file runtime set so the previously
  observed hybrid deployment could not recur. All eight deployed SHA-256
  values matched the release commit before the approved normal Core restart.
- VERIFIED (runtime, 0.0.636, 2026-09-13): The previous hybrid deployment
  failure is resolved. After restart, Vikarbodarna location migration was
  present and verified with timezone `Europe/Stockholm`, provenance
  `open_meteo_namespaced_store_and_binding`, and its persisted location
  fingerprint. Fiskvik remained without a legitimate Open-Meteo location or
  binding and remained a clean room with zero Open-Meteo frames.
- VERIFIED (runtime, 0.0.636, 2026-09-13): Vikarbodarna has an immutable
  Open-Meteo canonical frame for `solar.irradiance.forecast` with 72 points,
  `published_at=null`, site scope, strong source identity, and source
  generation `om-04f53ab963d11e9b9707a6b159969053`. The generation records
  `open_meteo_request_contract`, `native_bucket`, 3600 seconds, and verified
  timezone state.
- VERIFIED (runtime, 0.0.636, 2026-09-13): The post-restart natural hourly
  cadence ran through the existing read-only collector-state websocket at
  `2026-09-13T00:00:12` local time with `trigger=hourly_cadence`, exactly one
  target, target site Vikarbodarna, and `status=success`. This proves the
  site-independent scheduler path without manual capture or active-site
  substitution.
- VERIFIED (runtime, 0.0.636, 2026-09-13): The WAL-consistent post-cadence
  audit reported `integrity_check=ok`, 557 frames, 5,009 points, zero
  duplicate point IDs, zero duplicate semantic-key/revision pairs, zero
  broken supersedes chains, two Vikarbodarna Open-Meteo frames, and zero
  Fiskvik Open-Meteo frames. The latest frame was revision 2 in the same
  source generation and retained explicit `quality=partial` provider gaps;
  no synthetic points or interpolation were introduced.
- VERIFIED (scope boundary, 0.0.636, 2026-09-13): Solar Evidence remained
  non-regressed. The locked progress values remain 39 total days, 14
  Open-Meteo progress days, 13 Forecast.Solar common days, and 14
  `audit_complete` rows. The distinction between 39 raw
  `open_meteo_status=complete` rows and 14 composite progress rows is
  intentional. The known `collected_at` immutability issue remains a
  separate scope and was not changed.
- COMPLETE (C.2.4, runtime closure, 2026-09-13): The Open-Meteo immutable
  canonical producer is runtime verified through startup capture, natural
  hourly cadence, source-generation metadata, revision/deduplication,
  restart persistence, site-independent targeting, Fiskvik clean-room
  isolation, WAL integrity, and Solar Evidence non-regression. Docs closure
  is complete for the runtime scope; the unrelated E.ON thread-safety warning
  remains a separate follow-up and is not reclassified here.
- VERIFIED (design/fixtures, 2026-09-06): Step C.2.1 is complete and the
  external-input contract is locked in
  `docs/architecture/C2_1_EXTERNAL_INPUT_CONTRACT_V1.md` and its fixture/test
  files. C.1 schema v1 is sufficient; no migration is required. Forecast.Solar
  canonical observations are separate from the Evidence-v1 day-ahead
  consumer-freeze policy. Open-Meteo manager forecasts and the Evidence
  `previous_day1` path have separate dataset identities and revision chains;
  no canonical producer was added for the Evidence path. Unsupported
  Forecast.Solar roles fail closed, aggregate 12/24-hour roles are never
  expanded into fabricated hourly points, and GTI is not conflated with
  derived potential DC.
- VERIFIED (design/fixtures, 2026-09-06): C.2.1 fixtures cover source
  generation versus semantic target versus revision identity, explicit
  `known_at`/`captured_at`/target separation, null `published_at` when no
  provider publication timestamp exists, site provenance under cache
  deduplication, and Europe/Stockholm 23-hour/25-hour local-day conversion.
  The fixtures are pure standard-library tests and do not write HA, Store, or
  canonical runtime data.
- VERIFIED (scope boundary, 2026-09-06): Solar Evidence non-regression is a
  hard C.2 requirement. The evidence-v1 Store, frozen baselines, historical
  rows, `previous_day1` fetch, consumers, and counters are untouched; counts
  must not decrease from Open-Meteo 8/21 and Forecast.Solar common 7/14.
  The next scope is Step C.2.2: Forecast.Solar immutable canonical producer.
  C.2.2 is not started.
- VERIFIED (release, 0.0.626, 2026-09-06): E.ON facility-state indexing,
  site-explicit runtime resolution, unique legacy-binding reconciliation,
  active-site websocket/public-state resolution, and site-scoped economic
  frame provenance are released and runtime accepted. The unrelated global
  multi-facility selection risk remains outside this scope.
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
- VERIFIED (runtime, 0.0.624, 2026-09-06): Current electricity-provider price
  eligibility is independent from grid-contract status. An attributed
  operational provider contract contributes its verified variable cost even
  when the site grid contract is future; future grid terms remain preview-only
  and do not suppress the provider adjustment. Backend price serialization
  uses the internal provider snapshot while frontend public state remains
  sanitized.
- INFERRED (current-codebase statement): Deterministic, read-only shadow
  calculations; no physical battery write path
- VERIFIED (static, 2026-09-05): P0-AUDIT-1 provides a temporary, source-agnostic
  24-hour cadence audit for the configured logical roles. It snapshots active
  source generations from SiteIdentity, passively observes report/change events,
  and exposes state/start/stop/cleanup diagnostics without writing physical
  device state or becoming the canonical long-term collector.
- VERIFIED (runtime, audit `3f79c0ac-404e-4f4c-a02f-ad1addde158d`): The
  24-hour cadence audit completed with `success=true` and
  `status=completed_with_runtime_gap`. It met the minimum 24-hour window,
  observed homogeneous source generations, had no missing roles or unavailable
  periods, and observed 27 restarts with a separate 1,396.690983-second
  runtime gap. This evidence applies only to the current source generations;
  no universal cadence, jitter, stale threshold, maximum hold, or availability
  policy was inferred. Every new source generation requires separate
  characterization.

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
  data audit for planning. The canonical site-independent collector now exists
  and is runtime-verified for telemetry, but the P0 risk remains for complete
  long-term coverage, source-generation-specific quality/cadence policy, and
  inactive-site external/model-input collection with provenance and `known_at`.

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

- IRREVERSIBLE DATA RISK (P0): Recorder/raw model-relevant history remains
  short-retained, while complete external/model-input coverage and
  source-generation-specific quality/cadence policy are not yet fully verified.
  Load, PV, grid, battery, SOC, price, tariff, provider, weather and forecast
  history needed for future replay must be captured with provenance before it
  expires.
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

## C.2.3 Open-Meteo producer contract

- VERIFIED (runtime evidence closure, 2026-09-12): Vikarbodarna has
  `collection_enabled=true`, a persisted Open-Meteo binding, and deterministic
  persisted PV geometry: two sources totaling 9.45 kWp at tilt 30° and
  azimuth 225°. The existing runtime cache had one section and 67 monotonic
  hourly points; its source timestamps were naive local ISO text with API
  timezone `Europe/Stockholm` and offset metadata 7200 seconds.
- VERIFIED (runtime evidence closure, 2026-09-12): Fiskvik has
  `collection_enabled=true` but no solar entities, no persisted solar array
  geometry, no Open-Meteo binding, and no namespaced Open-Meteo Store. It must
  remain a clean room with zero Open-Meteo canonical frames until legitimate
  source/configuration exists.
- COMPLETE (C.2.3A): site-explicit geometry reconstruction and runtime cache
  evidence are closed. DST behavior remains design/fixture verified only; the
  observed cache horizon did not cross a DST transition.
- COMPLETE (C.2.3B): Open-Meteo immutable producer contract is locked in
  `docs/architecture/C2_3_OPEN_METEO_PRODUCER_CONTRACT_V1.md` with deterministic
  fixtures and pure tests. The contract uses per-normalized-section frames,
  explicit source generation and semantic/revision identities, raw GTI without
  clamp or derived potential-DC canonicalization, UTC valid_at with fail-closed
  DST handling, and `known_at <= decision_at` replay.
- NON-REGRESSION LOCK: C.2.4 must not change Solar Evidence, previous_day1,
  evidence-v1 qualification, frozen Forecast.Solar baselines, historical rows,
  counters, or consumers. The established baseline remains 39 days, 14
  Open-Meteo-complete, 13 Forecast.Solar-common with the recorded full and
  semantic hashes.
- COMPLETE (C.2.3C, docs/fixtures/tests, 2026-09-12): The B-contract
  correction is locked before production implementation. Open-Meteo location
  is persisted as verified site-scoped configuration under
  `site_configs[site_id].location` with latitude, longitude, IANA timezone,
  provenance, verification state, and deterministic fingerprint. Missing or
  unverified location is fail-closed; current HA global location, active site,
  grid address, and entity names are never fallbacks for background collection.
- COMPLETE (C.2.3C): Raw-GTI source generation is authoritative from the
  canonical request fingerprint, not existing installation or binding
  fingerprints. Capacity/source-string/entity changes remain installation
  provenance and binding validation only when request semantics are unchanged.
  Location, timezone, geometry, provider, model, variables, endpoint, horizon,
  or contract changes start a new generation at revision 1 with no
  cross-generation supersedes; historical coordinates remain immutable.
- COMPLETE (C.2.3C): The future Vikarbodarna migration is one-time,
  deterministic, provenance-explicit, idempotent, and fail-closed on
  store/binding disagreement. It may use the existing Vikarbodarna namespaced
  Open-Meteo Store evidence for `62.20646687401988`,
  `17.490212917327884`, and `Europe/Stockholm`, but must never copy those
  coordinates to Fiskvik. Fiskvik remains a zero-target clean room until its
  own verified location, geometry, and binding exist.
- COMPLETE (C.2.3C): Deterministic contract fixtures/tests cover inactive-site
  protection from global-location changes, identity separation, provenance
  changes, generation changes, Fiskvik zero-target behavior, and migration
  preconditions. No production code, canonical schema, runtime data, Evidence
  store, version, deploy, or restart changed.
- NEXT: C.2.4 production implementation is blocked until this amendment is
  respected by the implementation. No manifest bump, deploy, or restart belongs
  to C.2.3C.

## C.2.4 Open-Meteo immutable canonical producer

- COMPLETE / RUNTIME VERIFIED (0.0.636, 2026-09-13): The site-explicit
  Open-Meteo canonical producer is deployed and accepted on real Home
  Assistant runtime without changing the C.1 schema or Solar Evidence paths.
- The producer uses a deep site-configuration snapshot, explicit verified
  site-scoped location, persisted PV geometry, and an explicit Open-Meteo
  binding. Missing or unverified location, geometry, or binding is fail-closed;
  Fiskvik therefore remains zero-target/zero-frame unless it receives its own
  legitimate configuration.
- The existing Vikarbodarna namespaced Open-Meteo Store can seed its own
  location only when the same-site Store, binding fingerprint, finite
  coordinates, and valid API timezone agree. The migration is idempotent and
  never copies location to another site.
- Canonical capture uses a shared explicit-target raw HTTP fetch beneath both
  the mutable manager and immutable collector. Canonical normalization preserves
  finite negative GTI, source timestamp text, provider timezone metadata, and
  aware UTC valid_at; invalid/DST-ambiguous points are quality gaps with no
  fabricated values or interpolation.
- Frames use open_meteo.manager_forecast.v1 and solar.irradiance.forecast,
  are site-scoped, carry deterministic request generation/semantic identity,
  have published_at = null, and use immutable content-based
  deduplication/revisions. Manager-only derived/clamped fields remain outside
  canonical points.
- Collection is active-site independent, uses a dedicated Open-Meteo capture
  lock, does not hold the canonical flush lock during HTTP, revalidates targets
  before persistence, and has startup/hourly diagnostics.
- VERIFIED (runtime closure): The accepted release is `0.0.636` from commit
  `c16b18a9d1e6ee3719ac7136837d579dc3c2d5de`. Static gates, exact eight-file
  deployment hashes, Core restart, startup capture, natural hourly cadence,
  source-generation metadata, replay-visible canonical frames, restart
  persistence, clean-room isolation, and Evidence non-regression all pass.
- VERIFIED (runtime closure): The natural cadence status was observed through
  the existing `canonical_collector_state` command, not through a new test
  endpoint and not through a manual producer invocation. The accepted
  `quality=partial` frame represents explicit provider gaps and remains
  truthful; no interpolation or fabricated values are permitted.
- SEPARATE FOLLOW-UP: An E.ON `async_create_task` from a non-event-loop
  thread warning remains outside C.2.4 and must not be silently folded into
  this release closure.
- NEXT: Continue with the next immutable external-input foundation scope.
  Preserve the C.2.1 dataset identities, `known_at <= decision_at`, source
  generations, Solar Evidence non-regression contract, and the Fiskvik
  zero-history clean-room invariant.

## C.3 Weather / SMHI immutable external-input foundation

- COMPLETE (C.3A, read-only source/runtime/consumer audit, 2026-09-13): The
  current HA weather source is SMHI through the site-explicit Vikarbodarna
  binding. Current conditions and hourly forecasts are separate source
  contracts; the active site does not select background collection targets.
  Fiskvik has no legitimate weather binding and therefore remains a zero-target
  and zero-frame clean room.
- COMPLETE (C.3B, contract/design/fixtures/tests, 2026-09-13): The immutable
  weather contract locks `smhi.current_weather.v1` and
  `smhi.hourly_forecast.v1` as separate dataset identities with separate
  revision chains. Source generation includes only source-defining semantics,
  while values and capture times remain observation data.
- The current-weather contract uses a current snapshot target with no
  fabricated `valid_at`; HA `last_updated` is retained only as source
  provenance. The hourly contract stores one response vintage per frame and
  one point per forecast datetime with explicit UTC `valid_at`. The hourly
  frame semantic stream is stable across revisions; forecast datetimes belong
  to point identity, not frame identity.
- `captured_at`, `fetched_at`, `known_at`, `published_at`, and `valid_at` stay
  semantically separate. Producers must satisfy `known_at >= captured_at` and,
  when present, `known_at >= fetched_at`; replay retains the hard invariant
  `known_at <= decision_at`. No publication timestamp is fabricated.
- No-binding behavior is fail-closed: no target, provider call, frame, or
  Fiskvik attribution is created. No historical backfill is included. Solar
  Shadow and Solar Evidence stores, rows, baselines, qualification, counts,
  and consumers are explicitly untouched by C.3B.
- C.3B closure has no producer, runtime Store/DB migration, version bump,
  deploy, or restart. Focused contract tests passed 11/11; the closure gate
  must also include the full repository test and validation suite.
- NEXT: C.3C is not started and is not implementation-authorized. Any future
  producer must preserve these identities, site/source provenance, no-lookahead
  semantics, Fiskvik zero-frame behavior, and Solar Evidence non-regression.
