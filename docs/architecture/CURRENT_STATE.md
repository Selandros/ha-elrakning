# Elräkning – Current State

Updated: 2026-09-20

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
- COMPLETE (C.3C, immutable SMHI producer, 2026-09-13): The exact release
  commit is `5a84b00b16ce5c00dc5d926191030b45199e5f13`, version `0.0.637`.
  The release adds site-explicit immutable SMHI current-weather and hourly
  forecast capture without changing the canonical schema, Solar Evidence,
  Solar Shadow, Forecast.Solar, Open-Meteo, or provider paths.
- VERIFIED (C.3C runtime, 0.0.637, 2026-09-13): After a normal Core restart,
  Fiskvik was the active site while the collector selected exactly one weather
  target, Vikarbodarna. The runtime capture reported one hourly
  `weather.get_forecasts` service call for Vikarbodarna and zero Fiskvik
  weather targets, calls, or frames. This proves site-independent collection
  for the SMHI producer and fail-closed empty-site behavior.
- VERIFIED (C.3C canonical runtime, 0.0.637, 2026-09-13): The WAL-consistent
  canonical database reported `integrity_check=ok`, 16 source generations,
  602 external frames, 5,301 external points, zero duplicate point IDs, zero
  duplicate semantic-key/revision pairs, and no broken supersedes links.
  Vikarbodarna has one current-weather frame and one 60-point hourly-weather
  frame after restart; Fiskvik has zero weather frames. The hourly generation
  is `native_bucket / 3600 / verified`; the current generation is
  `event_stream / unknown` as specified by the contract.
- VERIFIED (C.3C timestamp/replay evidence, 0.0.637, 2026-09-13): Weather
  frames satisfy `known_at >= captured_at` and, where present,
  `known_at >= fetched_at`; current weather has no fabricated `valid_at`, and
  hourly points retain explicit UTC valid times. Existing C.1 replay semantics
  remain unchanged and no schema migration was introduced.
- VERIFIED (C.3C non-regression, 0.0.637, 2026-09-13): The site-scoped Solar
  Evidence store remains at 39 daily rows, 14 Open-Meteo progress days, 13
  Forecast.Solar common days, and 14 completed audit rows. Evidence/Shadow
  data, historical rows, baselines, counters, and consumers were not changed.
  The known `collected_at` immutability issue remains a separate known fail.
- C.3C is closed. No further code, Store, database, deploy, or restart is
  required for this scope. The next scope remains the next immutable
  external-input foundation milestone.

## C.4 Greenely immutable provider-economics foundation

- COMPLETE (C.4A, read-only source/runtime/consumer audit, 2026-09-13): The
  current Greenely runtime has explicit site-scoped `elhandel` bindings and
  separate durable facility/provider namespaces. Vikarbodarna has attributed
  invoice/tariff history; Fiskvik has zero historical invoices, zero historical
  consumption samples, no attributed current summary, and only a future
  Greenely contract start. Provider refresh remains active-site-bound today, so
  no current implementation claim is made that Greenely collection is already
  site-independent.
- COMPLETE / CONTRACT LOCKED (C.4B, design/fixtures/tests, 2026-09-13):
  `docs/architecture/C4B_GREENELY_ECONOMICS_EXTERNAL_INPUT_CONTRACT_V1.md`
  freezes `greenely.invoice_economics.v1` and
  `greenely.current_tariff_snapshot.v1` as separate site-scoped dataset
  identities with separate semantic/revision/supersedes chains.
- C.4B requires explicit site, facility and contract attribution; invoice
  economics additionally requires stable invoice attribution. Producer
  ownership must come from `collection_enabled` site configuration plus the
  explicit `elhandel` binding. `active_site_id`, shared credentials and the
  active provider namespace are not ownership identity.
- Provider economics are component facts only. Greenely variable retailer cost
  and fixed subscription remain separate from Nord Pool spot, weighted invoice
  spot, credits/settlement adjustments, `amount_due`, grid economics and the
  derived customer price. Missing components remain unavailable and are never
  zero-filled or reconstructed from totals.
- Temporal semantics are locked: contract `effective_from`, invoice validity,
  point `valid_at`, `captured_at`, `known_at` and `fetched_at` are distinct.
  Invoice calendar dates may become UTC validity only with a verified site
  timezone; otherwise invoice economics fail closed rather than inventing
  boundaries. A current tariff snapshot is valid only at capture time and must
  never be expanded backward into historical tariff coverage.
- Fiskvik remains a Greenely economics clean room in C.4B: zero historical
  invoice-economics frames and zero current-tariff-snapshot frames under the
  audited state. Explicit FUTURE contract metadata may be retained as future
  metadata but is not current or historical economics and does not authorize
  retrospective backfill.
- C.4B preserves the C.1 immutable external-frame model and hard replay rule
  `known_at <= decision_at`. Same normalized knowledge deduplicates; changed
  knowledge within one semantic target revises; facility/contract or relevant
  normalization replacement creates a new source generation starting at
  revision 1 without cross-generation supersedes. C.1 schema v1 is sufficient;
  no migration is required.
- VERIFIED (C.4B local closure gate, 2026-09-13): the scope contains only the
  contract document, deterministic JSON fixtures, contract tests and this
  current-state closure entry. Focused C.4B tests pass 17/17; no production
  code, manifest version, Home Assistant Store, canonical database, network
  behavior, deploy or restart is changed by C.4B.
- C.4C.1 implementation is LOCAL ONLY / NOT RELEASED (2026-09-13): the first
  production slice is implemented for `greenely.invoice_economics.v1` only.
  It uses explicit `collection_enabled` site targets, verified site timezone,
  explicit Greenely binding/proof, all-section invoice attribution, opaque
  occurrence identity, immutable C.1 frames and source-generation identity.
  It does not implement current tariff snapshots, backfill, customer-price
  changes, grid/E.ON economics, frontend changes, Evidence/Shadow changes or
  schema migration.
- The local slice includes the privileged proof-provisioning service, durable
  pseudonymization key domain with fail-closed missing-key history detection,
  deterministic invoice candidate selection, exact local-calendar UTC bounds,
  and producer fetch/capture timestamps. `active_site_id` is not used for
  ownership. FUTURE/no-invoice/ambiguous/unproven attribution remains empty.
- VERIFIED (static, local C.4C.1 correction, 2026-09-13): The proof
  provisioning path now performs an independent `Store.async_load()` after
  persisting the site-scoped proof, resolves the same site's current
  `elhandel` binding from the freshly loaded state, and fails closed with
  `stale_binding` if its fingerprint no longer matches the accepted binding.
  This closes the post-persist binding race without rollback, schema change,
  provider-specific logic, or changes to Evidence/Shadow behavior.
- VERIFIED (static, local C.4C.1 closure review, 2026-09-13): The corrected
  A→B post-save binding race and A→A control are covered by executable tests;
  the final read-only C4C.1 review reported no findings across A–V. Focused
  C4C.1 producer/proof tests pass 36/36 and the full Python suite passes
  500/500. All MJS tests, compileall, JSON validation, and `git diff --check`
  pass. Existing ResourceWarnings from unrelated test database cleanup remain
  known and are not introduced by this scope.
- C.4C.1 is READY FOR COMMIT PREPARATION, but is not committed, pushed,
  version-bumped, deployed, restarted, or runtime-verified. `CURRENT_STATE`
  is updated before commit as required by the scope review. The next action
  requires explicit commit authorization; `0.0.640` release/deploy/restart
  remain unauthorized. The separate 0.0.639 natural 00:05 Evidence gate is
  untouched and pending.

## 0.0.639 Site-independent solar collection fix

- IMPLEMENTED / STATIC VERIFIED (2026-09-13): Forecast.Solar `day_ahead` and
  `first_today` baseline capture uses explicit `collection_enabled` site
  targets. Solar Evidence daily, startup and backfill collection uses the same
  explicit site-target model. Vikarbodarna can continue collection while
  Fiskvik is the active site; Fiskvik without a legitimate binding/PV mapping
  produces no target and no fabricated data.
- UI and live managers remain active-site-contextual. Canonical telemetry,
  canonical Forecast.Solar, canonical Open-Meteo, and SMHI producers were not
  changed by this fix. The Evidence-v1 definition, counters, `previous_day1`
  request, and immutable Evidence rows were not changed.
- Context concurrency is protected by the Forecast baseline lock and Evidence
  collection lock. Deterministic asyncio gate tests cover capture/restore
  ordering and namespaced ownership; the Evidence lock may bound a site switch
  behind one in-flight collection operation.
- Static release gates pass for version `0.0.639`. Runtime verification is
  PENDING until deployment. Final acceptance requires a natural 00:05 runtime
  collection and Evidence non-regression verification.

## Current release closure

- VERIFIED (runtime, 0.0.639, 2026-09-14): The natural local 00:05 Solar
  Evidence run produced and persisted the Vikarbodarna completed-day result
  with `audit_complete=true`, complete Open-Meteo data and a Forecast.Solar
  common result while Fiskvik was the current UI site. Fiskvik had no Evidence
  binding and no namespaced Evidence Store. Site-independent target selection
  is implemented and the result is attributed to Vikarbodarna. The exact
  active site at 00:05 and a complete historical log window remain documented
  observability limitations, not behavior failures. Evidence progress is
  16/21 Open-Meteo and 15/14 Forecast.Solar common; no Evidence rows were
  rewritten by this gate.
- VERIFIED (release/deploy/runtime, 0.0.640, 2026-09-14): The release commit
  is `5da2d9e7fca34f90e13eff7d15f813af50d6a9e5`, containing only the manifest
  patch from 0.0.639 to 0.0.640. It is pushed with `HEAD == origin/main` and
  tracked tree clean except for the two intentional user documents. The exact
  release payload was deployed with 56/56 SHA-256 matches before one normal
  Home Assistant Core restart; HA is running and serves manifest version
  0.0.640. No schema migration or canonical data mutation was performed.
- VERIFIED (runtime, 0.0.640, 2026-09-14): Site registry and Evidence state
  survived restart. Fiskvik remains the active site and has no Evidence
  binding; Vikarbodarna retains its site-scoped completed-day Evidence result.
  A WAL-consistent canonical SQLite read-only snapshot reported
  `integrity_check=ok`, 7,233 external points, zero duplicate point IDs and
  zero `greenely.*` frames. The canonical schema opened without migration.
- VERIFIED (release boundary, 0.0.640, 2026-09-14; historical): C.4C.1
  production code was live and remained fail-closed because no Greenely proof
  was provisioned at that release boundary. This status is superseded by the
  current runtime reconciliation below.
  Greenely invoice-economics eligibility is `NOT YET ELIGIBLE`; no Greenely
  economics frame was created and Fiskvik remains a clean room. Proof
  provisioning, Greenely invoice capture and runtime activation are separate
  future work.
- COMPLETE (0.0.639 natural 00:05 gate, 2026-09-14): The gate is closed as
  PASS with the documented active-site and log-window observability
  limitations. 0.0.640 is released, deployed and runtime-loaded. The next
  scope is explicit Greenely proof activation; no CURRENT_STATE change is
  included in that scope until separately authorized.

## 0.0.641 causal solar provenance release

- COMPLETE (release/deploy, 0.0.641, 2026-09-19): Implementation commit
  `14e2364692ae1a5245611ce4c98fe761338a4fae` and release commit
  `eba7d95048bead5d06e7e97187c3d0be102adb5e` are deployed. The exact clean
  `custom_components/elrakning/` payload contained 58 files and all 58
  SHA-256 values matched before and after one normal Home Assistant Core
  restart. Manifest/runtime version is `0.0.641`. No second restart, manual
  collector call, backfill, Greenely proof provisioning, schema change, or
  persistent-data cleanup was performed.
- VERIFIED (runtime integrity, 0.0.641, 2026-09-19): HA Core returned healthy
  after restart. A WAL-consistent read-only canonical snapshot reported
  `integrity_check=ok`, existing schema migrations v1/v2 only, zero duplicate
  point IDs, zero duplicate frame semantic-key/revision pairs, and zero broken
  supersedes links. Both sites remain in the persistent site registry.
- VERIFIED (site isolation, 0.0.641, 2026-09-19): Vikarbodarna retains its
  verified location, Open-Meteo binding, solar geometry and namespaced Stores.
  Fiskvik remains without verified location/Open-Meteo binding/solar geometry;
  its Open-Meteo, Forecast.Solar and provenance Stores remain absent. No
  fabricated Fiskvik frames were observed.
- VERIFIED (Forecast.Solar and legacy preservation, 0.0.641, 2026-09-19):
  Vikarbodarna Forecast.Solar roles and existing weather/evidence stores remain
  present, while the canonical database contains no Forecast.Solar frames for
  Fiskvik. Evidence-v1, previous_day1 and the frozen historical population were
  not manually triggered, rewritten or backfilled. The known E.ON/elhandel
  `async_create_task` thread warnings remain a separate pre-existing scope.
- VERIFIED (services.yaml classification, 0.0.641, 2026-09-19): No
  `services.yaml` exists in the deployed 0.0.641 tree, the saved 0.0.640
  backup, the repository, or repository history. The HA message is therefore
  a baseline missing-service-description warning, not a 0.0.641 regression.
  Runtime service registration remains implemented in Python; no service was
  invoked during this gate.
- VERIFIED (Single Run lifecycle, static/runtime load, 0.0.641, 2026-09-19):
  `CanonicalCollector` owns one startup task and one hourly time trigger at
  `minute=0, second=12`; the single-run capture is protected by its own lock
  and shares the collector's storage flush lock. Setup diagnostics recorded
  `integration_start`, provider startup and normal refresh events. Vikarbodarna
  satisfies the target eligibility requirements; Fiskvik fails closed because
  it lacks verified location, binding and solar geometry.
- NOT OBSERVED (natural Single Run frame, 0.0.641, 2026-09-19; historical): The first
  naturally scheduled opportunity after restart produced no
  `open_meteo.single_run_day_ahead_pv.v1` frame. No public capture status or
  provider failure reason was exposed by the existing runtime read surface, so
  no reason was fabricated. Canonical integrity and site isolation remained
  healthy after the opportunity. The locked release gate permits closure with
  this honest evidence limitation; the producer is live and awaiting its first
  natural frame.
- SUPERSEDED: A later read-only runtime audit verified the natural Single Run
  frame; the historical observation above remains unchanged as a record of
  the 0.0.641 gate.
- COMPLETE (0.0.641 runtime closure): Release, deploy, restart, lifecycle
  load, canonical integrity, site isolation and legacy non-regression gates
  pass. `CURRENT_STATE` is now the authoritative record; no locked contract or
  architecture decision was changed. Next work is to observe a natural valid
  Single Run frame, not to invoke a manual capture.

## 0.0.642 Solar Evidence collected_at fix

- IMPLEMENTED (0.0.642, local release scope): The Solar Evidence day-row merge
  now preserves an existing `collected_at` value on recapture. The first
  collection timestamp is therefore immutable, while the existing behavior for
  completing an incomplete day remains unchanged. No historical row was
  rewritten, backfilled or migrated by this fix.
- VERIFIED (focused regression): A recapture with a different collection time
  retains the original `collected_at`, `actual_kwh` and frozen
  `forecast_solar_frozen_kwh` values while allowing the existing status merge.
  Evidence-v1, frozen baselines and previous_day1 semantics are otherwise
  unchanged. Greenely and Single Run are separate scopes.
- COMPLETE (0.0.642 release): The fix is committed and pushed. HA deploy and
  Core restart were handled in the separate runtime gate below.

- VERIFIED (0.0.642 runtime, 2026-09-19): The exact 58-file Git payload was
  deployed after all remote SHA-256 checks passed. Remote manifest/runtime is
  `0.0.642`, `ha core check` passed, and one normal Home Assistant Core restart
  completed successfully. Vikarbodarna and Fiskvik remain in the site registry.
  Vikarbodarna's namespaced Forecast.Solar, Open-Meteo, Solar Evidence and
  provenance Stores remained byte-identical across deploy/restart; Fiskvik
  remains without those namespaced stores. No Greenely activation, manual
  Evidence collection, manual Single Run trigger, canonical-data cleanup or
  database write was performed.
- VERIFIED WITH LIMITATION (0.0.642 runtime): The post-restart HA log scan
  showed no new Elräkning traceback or privacy leakage. The repeated
  `services.yaml` warning is the same baseline warning as 0.0.641. Direct
  post-restart SQLite `PRAGMA integrity_check` was not independently executed
  because the HA host exposes neither `sqlite3` nor `python3`; the canonical
  database files were not touched and the prior WAL-consistent integrity
  result remains the last direct database evidence. No natural Single Run
  frame was observed during this deploy/restart window.

## 0.0.643 E.ON/elhandel thread-safe scheduling fix

- ROOT CAUSE VERIFIED (0.0.642 runtime): HA logged wrong-thread calls from
  `elnat/eon_manager.py:81` and `elhandel/lifecycle.py:49/56`. The traceback
  entered through `concurrent.futures.thread.py`; the affected callbacks then
  called `hass.async_create_task`, causing blocked task creation and
  `coroutine was never awaited` warnings.
- IMPLEMENTED (0.0.643): The affected E.ON/elhandel scheduling paths now use
  HA's thread-safe `hass.create_task` API. Refresh ownership, interval
  subscriptions, provider data, auth, bindings, stores and site semantics are
  unchanged. Focused worker-thread regression tests cover E.ON startup/interval
  callbacks and the shared elhandel lifecycle.
- RELEASE STATUS: `0.0.643` is released, deployed and runtime-verified for
  this minimal fix. Solar Evidence, Single Run, Greenely and canonical schema
  are separate and unchanged.
- VERIFIED (0.0.643 runtime): Release commit
  `2ffb99aa45f71f35b875c937ffe1ea30d3a881b2` was deployed as an exact
  58-file payload; all source hashes matched after one normal Core restart and
  the runtime manifest reported `0.0.643`. The post-restart log window has no
  new E.ON/elhandel wrong-thread `async_create_task` or `never awaited`
  warning; the remaining matching lines are older log history.
- VERIFIED (0.0.643 runtime): Both sites remain in the registry, Vikarbodarna
  retains its namespaced solar stores, Fiskvik remains the clean-room site, and
  no Greenely proof/economics activation or manual Evidence/Single Run capture
  occurred. The existing `services.yaml` error is baseline: `services.yaml`
  is absent in both the 0.0.642 rollback payload and the repository release
  payload. The canonical database was not modified; direct post-restart
  SQLite integrity execution remains unavailable on the HA host, so the prior
  WAL-consistent integrity result is the last direct DB evidence. No natural
  Single Run frame was observed during this window.

## 0.0.644 services.yaml packaging fix

- ROOT CAUSE VERIFIED: Elräkning registers the existing
  `elrakning.greenely_proof_provision` service from
  `greenely_invoice_economics.py`, while no `services.yaml` has ever existed
  in the repository or release payload. Home Assistant therefore attempts to
  load the service description and reports the missing-file error.
- IMPLEMENTED: Added metadata for that existing service and
  all twelve existing required fields. No service handler, schema, service
  semantics, provider data, site state, storage, Solar Evidence, Single Run,
  Greenely proof state or canonical schema was changed.
- COMPLETE (0.0.644 release/runtime): Release `bc08d99b0d801adfd9b3832bc00223e31c9df6ab`
  was deployed as an exact 59-file payload with all source hashes matching
  after one normal Core restart. Manifest/runtime is `0.0.644` and
  `ha core check` passed.
- VERIFIED (0.0.644 runtime): The post-restart log window contains no new
  `Failed to load services.yaml for integration: elrakning` message and no
  new Elräkning traceback. The last matching services.yaml lines belong to
  the pre-deploy log history. Both sites and existing namespaced stores remain
  present; Fiskvik remains clean-room and Greenely remains fail-closed. No
  Solar Evidence or Single Run operation was manually invoked, and no natural
  Single Run frame was observed. The 0.0.643 rollback is preserved outside the
  discovery path.

## 0.0.645 Greenely privacy sanitization and baseline-test contract alignment

- IMPLEMENTED: Greenely consumption normalization now emits only the locked
  normalized timestamp/localtime/usage fields and cannot copy arbitrary source
  scalar fields such as email into samples or summaries. Greenely contract
  sanitization now removes customer, meter and account identifiers in addition
  to existing credentials, BankID and signed-document fields while retaining
  the separate facility binding identity needed for attribution.
- VERIFIED: The remaining seven 0.0.644 baseline failures were classified as
  two production privacy bugs and five stale test expectations. Tests were
  updated only where they asserted obsolete implementation location or
  provider-neutral internal-shape expectations. E.ON provider identifiers and
  semantic source fields remain preserved under the existing provenance
  contract; only authentication secrets are redacted there.
- LOCAL GATE PASS: Python `632 passed, 46 subtests, 0 failed`; MJS `28/28`;
  compileall, JSON, YAML and `git diff --check` pass. No schema migration,
  Evidence/Single Run change, Greenely proof activation, or canonical-data
  rewrite is included.
- VERIFIED (0.0.645 runtime): Release `15b5edab960e52ced8276d40505f31cdc31478d5`
  was deployed as an exact 59-file payload with all remote hashes matching
  before one normal Core restart. Manifest/runtime is `0.0.645`; Core returned
  with `boot: true`. Both sites remain present. Vikarbodarna's namespaced
  stores remain present and Fiskvik has no namespaced Open-Meteo, Forecast.Solar
  or Solar Evidence stores. Greenely remains fail-closed with no invoice,
  summary or consumption state attributed to either stored facility namespace.
- VERIFIED (0.0.645 runtime): The post-restart scan found no new Elräkning
  traceback or Greenely source-privacy leakage. No Evidence or Single Run
  operation was manually invoked; no natural Single Run frame was observed.
  Unrelated Home Assistant/custom `greenely` and other integration warnings in
  the restart log are outside this release scope.

## 0.0.646 Greenely source PII hardening

- ROOT CAUSE VERIFIED (read-only runtime audit): Existing Greenely provider
  source state still retained personal source fields such as email/name,
  phone/IP and address fields. The site binding still contains only the
  configured facility identity; no provider-proven contract/meter/install to
  invoice-installation (`Anl.id`) relation is present.
- IMPLEMENTED: Greenely source sanitization now removes those personal source
  fields together with customer/meter/account identifiers and existing secret
  fields, while retaining the separate facility binding identity required for
  attribution. This is forward-only; no existing Store or invoice history was
  rewritten and Greenely economics remains fail-closed.
- IMPLEMENTATION STATUS: Local release gates pending. Single Run has since
  produced one natural, valid Vikarbodarna frame; no Fiskvik frame exists.

## 0.0.647 Greenely legacy Store privacy migration

- ROOT CAUSE VERIFIED: 0.0.646 hardened future Greenely source captures but
  did not rewrite already persisted Greenely records. The existing electricity
  Store is version 2 and has no separate HA migration hook.
- IMPLEMENTED: `StorageManager.async_load()` now applies an idempotent,
  Greenely-only load migration to every facility namespace's active and
  history record. It reuses the Greenely sanitizer, preserves required
  facility/provider/contract/invoice economics and normalized consumption, and
  leaves all other providers unchanged. The Store version and other
  namespaces are unchanged; no canonical/Evidence/Single Run data is touched.
- VERIFIED: Focused migration tests cover active/history PII removal,
  retention of safe attribution/economics fields, idempotence, provider
  isolation and fail-closed state preservation. Full local gate is green.
- VERIFIED (0.0.647 runtime): Release `728557b283ef0d6a0f09caf4b2def67390dd80c8`
  was deployed as an exact 59-file payload with all hashes matching before
  one normal Core restart. Manifest/runtime is `0.0.647`; both sites remain
  present; rollback `0.0.646` is preserved. Greenely forbidden source keys
  are absent from active and history records in all facility namespaces.
  Vikarbodarna retains its provider attribution, 52 invoice records and 1153
  normalized consumption samples; Fiskvik remains zero-history and
  fail-closed. No Greenely proof/economics activation occurred.
- VERIFIED (0.0.647 runtime): A new WAL-consistent read-only canonical
  snapshot returned `PRAGMA integrity_check = ok`, one unchanged natural
  Open-Meteo Single Run frame for Vikarbodarna and zero duplicate point IDs.
  No canonical, Evidence or Single Run mutation was performed by the audit;
  no new Elräkning traceback was observed.

## 0.0.648 Greenely facility meter-identity state amendment

- ROOT CAUSE VERIFIED: C.4C.1A explicit out-of-band proof required a
  `facility_meter_id_fingerprint` even when the provider does not expose a
  facility meter identity. The existing contract had a state form for the
  contract meter, but no bounded state for the facility meter.
- IMPLEMENTED: The proof boundary now accepts exactly one of a verified
  facility-meter fingerprint or the bounded state
  `provider_meter_identity_unavailable_v1`. Unknown/free-form states, both
  representations, and missing representations remain fail-closed. Provider
  native lookup, site/contract verification, invoice installation evidence,
  Greenely economics, Evidence-v1, Single Run and canonical schema are
  unchanged.
- VERIFIED: Release commit `10ea758e8fb6401e47212260aa77904f9081a053`
  contains exactly the bounded implementation, contract fixture, service
  metadata and focused tests. Manifest/runtime is `0.0.648`; the full local
  gate is `637 passed, 46 subtests, 0 failed`, MJS `28/28`, compileall,
  JSON/YAML validation and diff-check pass.
- VERIFIED (0.0.648 runtime): An exact 59-file payload matched all remote
  hashes before one normal Core restart. Core returned healthy, the
  `services.yaml` load error count is zero, no new Elräkning setup/import
  error was observed, and no new E.ON thread warning was observed. A unique
  `0.0.647` rollback backup is preserved outside the discovery path.
- VERIFIED (0.0.648 runtime): Both Store files remain present and the
  forbidden Greenely PII-key count is zero in each. No proof provisioning,
  Evidence collection or Single Run trigger was invoked; Greenely economics
  remains fail-closed. The existing natural Single Run status is unchanged.
- HISTORICAL OPEN STATUS: The bounded amendment enabled a legitimate
  authenticated admin proof-provisioning request but did not provision proof
  at the 0.0.648 boundary. This status is superseded by the current runtime
  reconciliation below; invoice occurrence/correction semantics remain a
  separate future design scope.

## 0.0.649 Greenely contract-meter identity state amendment

- ROOT CAUSE VERIFIED: The provider snapshot exposed no contract-meter
  identity. The prior `contract_meter_id_fingerprint_or_state` path accepted
  any non-empty string, so it had no bounded distinction between a canonical
  fingerprint and an unavailable provider state.
- IMPLEMENTED: Contract scope now has its own exact state,
  `provider_contract_meter_identity_unavailable_v1`. The existing facility
  state is not reusable for contract scope. Contract input accepts only that
  state or a 64-character lowercase `sha256-v1` fingerprint; free text,
  malformed fingerprints and raw identities fail closed.
- VERIFIED: Normalized contract-meter identity/state participates in proof
  semantic identity and therefore source-generation identity. Invoice
  occurrence, correction and reissue semantics remain separate. No Store
  migration, schema change, provider-native lookup change, Evidence change or
  Single Run change was made.
- VERIFIED (0.0.649 runtime): Release commit `bd24e767526f844c93d8a874830155df3bf8c0f5`
  was deployed as an AppleDouble-free exact 59-file payload with all hashes
  matching before one normal Core restart. Core returned healthy; manifest is
  `0.0.649`; services/setup errors and new proof-provisioning log markers were
  absent. Two rollback backups are preserved outside the discovery path.
- VERIFIED (0.0.649 runtime): Greenely forbidden PII-key counts remain zero,
  both sites remain preserved, and no proof provisioning, Evidence collection
  or Single Run trigger was invoked. Greenely economics remains fail-closed.
- READ-ONLY PROOF READINESS (historical 0.0.649 state): The bounded provider snapshot established the
  facility/contract/invoice and out-of-band installation-fingerprint chain,
  while contract-meter identity is explicitly unavailable under the new
  bounded state. No proof record exists. Provisioning still requires an
  authenticated Home Assistant admin service context and a complete bounded
  evidence package; invoice occurrence/correction/reissue remains open and
  separate.

## 0.0.650 Greenely evidence-package contract alignment

- ROOT CAUSE VERIFIED: The locked C4C1A pure contract required the exact
  `c4c1a-evidence-package-v1` five-key package, while production checked only
  for a different `contract_version` key.
- IMPLEMENTED: Production now requires exact package keys, exact package
  version, the single allowed comparison procedure, the locked proof relation,
  timezone-aware evidence `recorded_at`, deterministic lowercase SHA256
  semantic identity matching the normalized proof inputs, and a canonical
  digest. Extra keys, raw identity keys, unknown procedure/relation, malformed
  timestamps, arbitrary semantic identities and digest mismatches fail closed.
  Facility/contract meter-state semantics are unchanged.
- VERIFIED: Release commit `6786e0b1a478be0961f2e22c12ae8eb1474282d9` passed
  `641 passed, 46 subtests, 0 failed`, MJS `28/28`, compileall, JSON/YAML
  validation and diff-check. The exact AppleDouble-free 59-file payload
  matched before one normal Core restart.
- VERIFIED (0.0.650 runtime): Core returned healthy with manifest `0.0.650`;
  services/setup errors were zero, no proof record or proof-provisioning log
  marker appeared, Greenely forbidden PII-key counts remained zero, and the
  three rollback backups remain outside the discovery path. No Evidence or
  Single Run trigger was invoked.
- SITE READINESS (historical 0.0.650 release-boundary state): Vikarbodarna
  had the bounded facility/contract/invoice and original-invoice installation
  evidence, but proof remained unprovisioned pending authenticated Home
  Assistant admin context and explicit evidence recording time. Fiskvik had
  verified provider facility/contract scope but zero invoices and zero
  consumption evidence; it was explicitly ineligible and remained clean-room.
  This status is superseded by the current runtime reconciliation below.

## 0.0.651 Estimated invoice month-end forecast

- ROOT CAUSE VERIFIED: `Estimerad faktura` already used the full-month field
  `estimated_month_total_sek`, but sparse early-month coverage was extrapolated
  only from the current observed daily import. The estimate therefore revised
  sharply as more observations arrived.
- IMPLEMENTED: Billing history now reads a bounded trailing 28-day Recorder
  window. Complete local calendar days form a historical daily-kWh baseline;
  the current rate is blended with weight `min(1, covered_days / 14)`. Without
  history, the prior current-observation fallback remains explicit and
  low-confidence. Known future price periods are used for the remaining
  variable cost, with observed-price fallback only beyond that horizon. Full
  monthly fixed fees are included once, while `total_so_far_sek` remains
  separate.
- IMPLEMENTED: The billing websocket returns future price periods through the
  local month boundary and additive baseline points/coverage diagnostics. No
  provider, schema, Store, Evidence, Greenely, Forecast.Solar or Single Run
  data path was changed.
- VERIFIED: Release commit `99fb67a1a0db4a446f87f1eed58d112006f2e0cb`
  contains the six-file implementation/test/version scope. Full Python is
  `641 passed, 46 subtests, 0 failed`; all `28/28` MJS tests, compileall,
  JSON/YAML validation and diff-check pass.
- VERIFIED (0.0.651 runtime): The exact AppleDouble-free 59-file payload
  matched all remote hashes before one normal Core restart. Manifest/runtime
  is `0.0.651`; Core returned healthy; the canonical WAL/SHM snapshot has
  `PRAGMA integrity_check = ok`; and the 0.0.650 rollback is preserved
  outside the discovery path. Site Stores remain present, with no new
  services.yaml error, Elräkning traceback or Forecast.Solar persistence error
  observed.
- RUNTIME SCOPE: The production estimator and its sanitized `Visa data`
  metadata are deployed. A fresh authenticated visual read of the live
  numeric card was not performed in this gate; acceptance rests on the
  deterministic model tests, exact deployment hashes and startup/runtime
  checks. Greenely proof/economics, Fiskvik clean-room, Evidence and natural
  Single Run state were left untouched.

## Current runtime reconciliation after 0.0.651

- VERIFIED (read-only current runtime): Vikarbodarna's Greenely proof is
  provisioned through an authenticated Home Assistant admin service context.
  The production `validated_greenely_proof()` validator returns a valid proof
  with `verification_state=EXPLICITLY_VERIFIED`.
- VERIFIED (read-only current runtime): Vikarbodarna has 2 canonical
  `greenely.invoice_economics.v1` frames. Both are `quality=good` and
  `classification=measured`; duplicate semantic/revision count is zero.
  No Greenely economics frame exists for Fiskvik.
- VERIFIED (read-only current runtime): Vikarbodarna has 1 natural
  `open_meteo.single_run_day_ahead_pv.v1` canonical frame with quality,
  `known_at` and valid target interval present. Its duplicate
  semantic/revision count is zero. Fiskvik has zero Single Run frames.
- VERIFIED (read-only current runtime): Fiskvik remains clean-room: no
  Greenely proof, no Greenely economics frame, and no Single Run frame. The
  existing site-independent collection behavior is preserved.
- VERIFIED (read-only current runtime): A WAL-consistent canonical snapshot
  reports `PRAGMA integrity_check=ok`. No new Elräkning traceback, services.yaml
  error, economics error or Single Run/Open-Meteo error was found in the
  narrow current log scan.
- EVIDENCE LIMITATION (not a product failure): A fresh authenticated visual
  read of the numeric `Estimerad faktura` dashboard value remains
  `NOT OBSERVED`. The 0.0.651 estimator and its deterministic test/runtime
  path are deployed; this limitation does not invalidate the model result.
- OPEN FUTURE DESIGN (separate): Greenely invoice occurrence,
  correction/reissue identity semantics remain open. They do not invalidate
  the verified installation proof or the two current Vikarbodarna economics
  frames.

## 0.0.657 ELLA site-gating release — superseded

- NOT ACCEPTED / SUPERSEDED: The 0.0.657 release (`efbf725`, hardened by
  `5c376bf` and `5ec5340`) introduced the explicit, versioned, fingerprinted
  planner-only ELLA capability and backend production gate, but runtime UI
  observation found stale ELLA rendering after a bound-to-unbound SPA site
  switch. Fiskvik could retain the prior ELLA presentation. No closure was
  recorded for this release.

## 0.0.658 ELLA site-switch state isolation

- ROOT CAUSE VERIFIED: Site activation updated the frontend site identity but
  did not immediately reconcile ELLA-specific state. The unbound render path
  returned without clearing the ELLA rail, readiness/selection state or stale
  load-forecast response context.
- IMPLEMENTED: Site changes now advance a frontend site-context generation,
  clear ELLA state on context changes, discard late power-history responses
  from the previous site, and render visibility directly from the current
  site's verified binding. No site name or provider is hardcoded. Backend
  planner-only binding and load-forecast production gates are unchanged.
- VERIFIED: Release commit `1bce7e236622be01f1d80f1c198a0fcc270d86ea`
  passed `655 passed, 46 subtests, 0 failed`, all MJS tests, compileall,
  JSON/YAML validation and diff-check. The exact 60-file AppleDouble-free
  payload matched before one normal Core restart; rollback for 0.0.657 is
  preserved outside the discovery path.
- VERIFIED (runtime, 0.0.658): Core and HTTP remained healthy, manifest is
  `0.0.658`, and no new Elräkning traceback or thread-safety warning appeared
  in the relevant post-restart log scan.
- VERIFIED (runtime binding): Vikarbodarna has one explicit verified ELLA
  planner binding whose canonical fingerprint matches and whose
  `actuator_write_enabled` is false. Fiskvik has no ELLA binding.
- VERIFIED (same authenticated Safari session): Vikarbodarna showed ELLA
  with two cards; after switching to Fiskvik, the ELLA section was hidden and
  its card rail contained zero cards; switching back to Vikarbodarna restored
  the ELLA section and its two cards. No service call, battery write or
  automatic binding was used.
- DESIGN LIMITATION: This release does not add a real day planner, ESS digital
  twin or actuator. ELLA remains planner-capability gated and actuator-write
  disabled.

## 0.0.660 ELLA A1 capability-driven price-only planner

- NOT ACCEPTED / SUPERSEDED: `0.0.659` failed runtime acceptance because the
  price-only planner read provenance from a coordinator attribute that is not
  present in the real runtime. The resulting `missing_price_provenance` state
  prevented valid plans.
- IMPLEMENTED AND VERIFIED: `0.0.660` reads the verified Nord Pool binding
  from the public `SiteIdentityManager.global_binding("nord_pool")` contract,
  recomputes and compares its canonical binding fingerprint, and fails closed
  when provenance is missing or mismatched. Legacy ELLA binding remains only as
  transition/history state and is not required for price-only eligibility.
- VERIFIED (release): Commit
  `d6697f36907cf5ac8f5122e1cd9f51ecc1c8b6f4`; Python `661 passed`, `46
  subtests`, `0 failed`; focused planner/provenance tests `21 passed`; MJS,
  compileall, JSON/YAML validation and diff-check pass. The exact 61-file
  payload matched SHA256 `61/61`; HA Core check passed; exactly one normal Core
  restart was performed; HTTP returned `200` and no new Elräkning traceback or
  thread-safety warning was observed.
- VERIFIED (authenticated runtime): Fiskvik, with
  `ella_binding_verified=false`, returned an available
  `ella.price_only_plan.v1` with `plan_version=price-only-v1`, verified price
  capability from `nord_pool.price_periods.v1`, 96 periods and 7 deterministic
  price-only blocks. The blocks contained no load, solar, battery or SOC
  fields.
- VERIFIED (authenticated runtime): Vikarbodarna, with its existing verified
  ELLA transition binding, returned the same available A1 dataset and 7
  price-only blocks from its own site-scoped planner response. The shared SE2
  Nord Pool source was represented by the verified source generation, while
  stable plan-block identities remained site-scoped and differed between the
  two sites.
- VERIFIED (authenticated runtime): The transition Vikarbodarna -> Fiskvik
  -> Vikarbodarna returned a planner result whose site matched the active site
  after each activation. No stale or cross-site planner result was observed.
- SCOPE CLOSED: A1 is limited to capability-driven price-only planning. It
  does not implement the future UI shell, load-aware or solar-aware
  enrichment, ESS planning, digital twin, actuator or dispatch. The accepted
  `0.0.658` stale-response/site-isolation protections remain the safety
  foundation.

## 0.0.662 ELLA price-only UI shell and selection closure

- NOT ACCEPTED / SUPERSEDED: `0.0.661` is superseded by `0.0.662` for the
  price-only card layout and selection UX. It is not the final accepted
  runtime baseline for that scope.
- ACCEPTED RUNTIME/UI BASELINE: `0.0.662`, release commit
  `77e62cc085e471eefbd01f0ce204ac4adeb0b2d5`, manifest/runtime `0.0.662`.
  Python `661 passed`, `46 subtests`, `0 failed`; MJS `29/29`; compileall,
  JSON/YAML validation and diff-check passed. The clean pre-restart payload
  matched SHA256 `61/61`; HA Core check passed; exactly one normal Core
  restart was performed; HTTP returned `200`; no new Elräkning traceback or
  thread-safety warning was observed.
- VERIFIED (authenticated UI runtime): seven price-only plan cards rendered
  in a dedicated rail below the price chart. The chart plot area was
  `top=270.77, bottom=565.77`; the rail was `top=575.77, bottom=697.77`,
  with `railBelowChart=true`.
- VERIFIED (authenticated UI runtime): selecting a card created the exact
  plan-block selection band; selecting the same card again cleared it;
  pointer interaction outside the cards and wheel/scroll interaction cleared
  it immediately. A real Vikarbodarna -> Fiskvik site switch cleared the
  selected card and selection band before applying Fiskvik's seven cards;
  no stale Vikarbodarna selection remained.
- This closure verifies only the price-only UI shell and graph-selection
  interaction. Load-aware, solar-aware, ESS/battery, actuator and dispatch
  stages remain unimplemented and are not implied by this status.

## 0.0.668–0.0.669 Load-aware plan cards and spacing closure

- ACCEPTED RUNTIME BASELINE: `0.0.669`, release commit `8d01c4c`.
  The release gate passed with Python `671 passed`, `46 subtests`, `0
  failed`, MJS `29/29`, compileall, JSON/YAML validation and diff-check.
  The clean payload matched SHA256 `61/61`; HA Core check passed, exactly
  one normal Core restart was performed, HTTP returned `200`, and no new
  Elräkning traceback or thread-safety warning was observed.
- IMPLEMENTED IN `0.0.668`: plan-block load totals use the established
  canonical load model with deterministic per-slot precedence
  `actual > forward forecast > historical model`. Mixed totals are allowed
  and carry explicit provenance; missing slots are never zero-filled. The
  historical model fallback is the existing site-scoped load-profile model,
  not a separate Recorder/UI shortcut.
- SUPERSEDED FOR LAYOUT ONLY: `0.0.668` established the historical-model
  fallback and runtime load/provenance behavior, but its effective vertical
  rail spacing remained too large. `0.0.669` changes only the
  price-section/rail DOM layout and spacing; planner, load, provenance,
  selection and site-isolation semantics are unchanged.
- VERIFIED (authenticated Safari runtime, Vikarbodarna): all `7/7`
  price-only plan blocks had numeric load totals. The observed provenance
  sequence was `actual, mixed, model, model, mixed, forecast, forecast`.
  The current `11:30–13:45` block remained centered with rail center
  `622.5`, card center `602.5`, delta `-20 px` and `scrollLeft=763`.
- VERIFIED (authenticated Safari runtime): chart-frame-to-rail spacing was
  approximately `20.5 px` and price-section-to-rail spacing `20.0 px`; the
  rail remained structurally outside the price section. Site-scoped,
  provenance-aware and fail-closed semantics remain in force: no zero-fill,
  no cross-site load leakage, and no solar/ESS/actuator behavior was added.
- CURRENT ROADMAP STATE: A1 price-only planning, the price-card UI shell,
  and stage B load-aware enrichment are accepted runtime behavior. Solar/
  net-load enrichment, ESS planning and physical actuator/dispatch remain
  future stages and are not implemented by this state.

## 0.0.670 Price-card DOM order and spacing closure

- NOT FINAL / SUPERSEDED FOR VISUAL LAYOUT: `0.0.669` reduced the gap but
  placed the graph controls after the ELLA rail. That made the rail appear
  visually inside the price graph even though the planner and load behavior
  were correct.
- ACCEPTED RUNTIME SPACING BASELINE: `0.0.670`, release commit
  `5f47486026754cb5b818060825dea1451627adde`, manifest/runtime `0.0.670`.
  Python `671 passed`, `46 subtests`, `0 failed`; MJS `29/29`; compileall,
  JSON/YAML validation and diff-check passed. The clean payload matched
  SHA256 `61/61`; HA Core check passed; exactly one normal Core restart was
  performed; HTTP returned `200`; and no new Elräkning traceback or
  thread-safety warning was observed.
- VERIFIED (authenticated Safari runtime): `.price-section` was
  `top=203.69, bottom=630.75`; `.price-chart-frame` ended at `565.77`;
  `.price-controls` was inside `.price-section` from `top=565.77` to
  `bottom=630.25`; and the legend and period picker were inside
  `.price-controls`. The price-plan rail began at `650.75` as a sibling
  after the closed price section, giving exactly `20 px` spacing.
- DOM acceptance: complete price card (heading/statistics, chart, legend and
  period controls) -> `20 px` gap -> ELLA plan rail -> normal dashboard
  spacing. `railInsidePrice=false`; no graph control occurs after the rail.
- Scope: this release changed only frontend DOM/CSS ordering and its
  regression test. Planner, load, provenance, centering, selection,
  site-isolation and backend behavior were unchanged. No solar, ESS or
  actuator behavior is implied.
