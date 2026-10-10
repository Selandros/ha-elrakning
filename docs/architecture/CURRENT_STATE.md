# Elräkning – Current State

Updated: 2026-10-10

## 0.0.1112 Phase 2 App hostname discovery

- FIXED: the Core shadow client no longer assumes the unqualified
  `elrakning-app` hostname. Blank/default configuration and that legacy alias
  are resolved from Home Assistant's cached Supervisor App list using the
  generated `{repository-id}_{slug}` hostname, with underscores replaced by
  hyphens.
- SAFETY: discovery is in-memory and bounded; no Supervisor network request,
  token, IP address or repository id is hardcoded. Ambiguous or unavailable
  discovery fails closed. Explicit fully qualified URLs remain supported.
- PRESERVED: the App remains version 0.0.1092, shadow-only, read-only and
  separate from the Core source of truth; no physical control or writes were
  added.

## 0.0.1111 Phase 2 read-only App shadow transport

- IMPLEMENTED: Stage 15 now performs a bounded authenticated App health gate
  when the explicit shadow option is enabled. Missing or invalid configuration
  remains fail-closed and creates no App traffic.
- IMPLEMENTED: existing site-scoped immutable canonical frames may trigger a
  coalesced read-only snapshot submission. The adapter rejects incomplete
  observed-time, source-identity or sign-semantics rather than fabricating
  values. Empty clean-room state produces zero snapshots.
- PRESERVED: Core canonical storage remains the source of truth. App results
  are never consumed by entities, optimizer, scheduler, commands or physical
  control. The App remains version 0.0.1092 because its endpoint and contract
  did not change.
- OBSERVABILITY: bounded App-shadow state is exposed through the existing
  diagnostics websocket without tokens, headers or payload secrets.

## 0.0.1100 clean-room Add-flow path

## 0.0.1103 clean-install reference normalization

## 0.0.1104 clean-install manifest read isolation

- CORRECTED: the bounded `SHA256SUMS` read used for reset provenance now runs
  through Home Assistant's executor. Reset orchestration remains awaited and
  fail-closed, but the setup event loop no longer performs synchronous file
  I/O for the archive manifest.

- ROOT CAUSE VERIFIED: the submitted entry contained the UI field name plus
  the path (`clean_install_archive_reference /config/...`) as one string.
  The validator correctly rejected that non-existent path as incomplete.
- CORRECTED: one exact, bounded field-name prefix is stripped before the
  normal in-config path and `SHA256SUMS` validation. The canonical path and
  manifest digest are what the reset receipt records; arbitrary prefixes or
  invalid paths remain fail-closed.

- IMPLEMENTED: the new-entry ConfigFlow now collects a bounded archive
  reference, explicit clean-install confirmation, and diagnostic stage 0
  before creating the entry. It stores only config-entry options; no site
  stores are touched by the flow.
- SAFETY: a new clean installation cannot select a later diagnostic stage,
  and setup still consumes the pending reset before legacy managers or heavy
  subsystems. The existing disabled entry is not modified.
- UI GATE: Home Assistant 2026.10 does not expose OptionsFlow on the disabled
  entry detail page observed in runtime. The supported path is to delete only
  that disabled entry in the UI, then add Elräkning again and complete the
  clean-room form. Quarantined files and backups are outside this metadata
  operation and remain untouched.

## 0.0.1099 deployment-layout gate

- IMPLEMENTED: `scripts/check_custom_components_layout.py` and regression
  tests reject rollback, hidden backup, and loose Python entries below the
  Home Assistant `custom_components` importer root.

## 0.0.1098 config-flow deployment-layout correction

- VERIFIED: the `Invalid handler specified` report was caused by a rollback
  directory left directly below Home Assistant's `custom_components` root.
  HA attempted to import that directory as a component and failed with
  `No module named 'custom_components.'`.
- The Elräkning manifest and `ConfigFlow`/`OptionsFlow` registration were
  valid. The fix moves only the misplaced rollback directory out of the
  discovery root; it does not change options, sites, or source-of-truth.
- Deployment invariant: rollback/staging paths belong under the Elräkning
  rollback or quarantine area, never below `custom_components`. The layout
  gate rejects hidden backup directories, rollback directories, and loose
  Python files at that importer root.

## 0.0.1097 staged clean-install diagnostic checkpoint

- IMPLEMENTED: an optional, bounded `diagnostic_stage` config-entry option
  supports reversible staged bring-up from zero-site bootstrap through the
  existing runtime boundaries. Missing option preserves normal production
  setup unchanged.
- STAGES: 0 bootstrap/diagnostics, 1 frontend/websocket, 2 identity shell,
  3 runtime stores/services, 4 provider bindings, 5 canonical/provider
  recovery, 6 forecast resources, 7 load/readiness, 8 replay/optimizer path,
  and 9 App shadow boundary. Each paused stage records start/completion and
  duration through the existing bounded runtime checkpoint path.
- SAFETY: stages 0–8 do not create the App shadow client; malformed stage
  options fail closed; highspy remains diagnostic-disabled and optimizer
  requests remain unavailable. Physical control, storage ownership and
  source-of-truth semantics are unchanged.
- RUNTIME GATE: no deployment or activation was performed in this release;
  active Supervisor recovery jobs and an unresponsive Core remain a runtime
  blocker. The first manual step after a safe deployment is to set the
  pending clean-install marker and `diagnostic_stage=0` through OptionsFlow
  while the entry is disabled.

## 0.0.1096 clean-install preflight checkpoint

- IMPLEMENTED: OptionsFlow stores a bounded pending clean-install marker in
  config-entry options while the entry may remain disabled. The marker is
  consumed as the first stateful setup step, before frontend registration,
  managers, providers, canonical storage, replay or forecast setup.
- IMPLEMENTED: the admin-only `elrakning.clean_install_reset` service now sets
  the same next-start marker instead of mutating site stores immediately.
- VALIDATION: setup requires an in-config archive directory with bounded,
  non-empty `SHA256SUMS` metadata, then records its manifest digest and a
  completed reset receipt in config-entry options. README files remain
  optional documentation and are not used as provenance.
- PRESERVED: legacy Ella/site/replay/canonical stores remain untouched and are
  archive/quarantine data only. A new first site must be created and activated
  explicitly; no legacy entity, provider, FusionSolar identity or source
  generation is inferred or remapped.
- SAFETY: invalid markers fail closed before normal setup. Empty-state startup
  skips E.ON cached-import recovery and tariff persistence without an active
  site. The reset is single-reference, idempotent and rejects a conflicting
  archive reference. No physical writes, shadow cutover or App behavior is
  changed.
- RUNTIME PREPARATION: full HA backup `25c57b4f` and a separate legacy bundle
  were created on 2026-10-10 while Elräkning was disabled. SQLite integrity
  inspection remains pending because the HA SSH namespace has no `sqlite3`.

## 0.0.1094 diagnostic highspy-isolation checkpoint

- IMPLEMENTED: setup/import checkpoints now record bounded UTC timestamp,
  thread and duration for the integration lifecycle, including E.ON cached
  import recovery and the main setup phases. A low-overhead event-loop
  heartbeat reports only material lag and is cancelled/awaited on unload.
- DIAGNOSTIC MODE: the Core optimizer does not import `highspy` during module
  import or setup. Optimizer requests fail closed with an explicit unavailable
  result while `websocket_economic_optimizer()` records bounded request/build
  checkpoints. Existing Core source-of-truth and data semantics are unchanged.
- TOOLING: a read-only external watcher samples Core/Supervisor state, jobs,
  HTTP liveness, resource stats and relevant crash/error signals. It does not
  restart, mutate configuration, or alter runtime state.
- SCOPE: Elräkning remains disabled for the controlled activation test. No
  shadow cutover, storage/provider migration, or physical control is enabled.

## 0.0.1093 OptionsFlow compatibility checkpoint

- ROOT CAUSE VERIFIED: Home Assistant Core 2026.10 owns the read-only
  `OptionsFlow.config_entry` property. The integration assigned that property
  in its constructor, so opening OptionsFlow raised an `AttributeError` before
  the form could be returned and left the frontend spinner active.
- CORRECTED/TESTED: the flow now uses Home Assistant's lifecycle-provided
  `config_entry` property. Shadow remains disabled by default and no App,
  entity, decision or source-of-truth behavior changes.

## 0.0.1092 Phase 1 App repository packaging checkpoint

- IMPLEMENTED: the App repository now has root `repository.yaml` metadata and a
  standalone App build context. The Dockerfile no longer depends on the Core
  repository root or the removed legacy build metadata. It declares the
  current explicit base image, Python runtime and App labels, and the bounded
  contract validator is included in the App image without adding dependencies
  or changing runtime semantics.
- PRESERVED: the App remains manual-boot, shadow-only, read-only, disabled by
  default in Core, and separate from canonical storage, provider ingestion,
  optimizer, physical control and the existing source-of-truth.

## 0.0.1089 Phase 1 hybrid shadow boundary

- IMPLEMENTED: a separate, dependency-free Home Assistant App/add-on
  skeleton exposes bounded liveness/readiness and authenticated read-only
  StateSnapshot ingress. The contract is versioned and rejects wrong
  contract/site/generation context, stale validity, invalid provenance,
  `known_at > decision_at`, malformed values and unavailable-as-zero payloads.
- CORE ADAPTER: the integration creates a disabled-by-default bounded client
  during setup and removes it during unload. The supported OptionsFlow stores
  the explicit enable flag, local URL and bearer token in config-entry options.
  It performs no network request, polling, HA service call or result
  projection unless explicitly enabled in a later shadow deployment. App-down
  handling is fail-closed and bounded to one second.
- ISOLATION: the add-on has no host port mapping, no HA token, no physical
  control endpoint, no canonical storage writer and no HiGHS/optimizer import.
  Its in-memory snapshot buffer is bounded by site and snapshot count.
- GATE: the existing Core integration and canonical storage remain the sole
  source of truth. This release contains no cutover, dual writer or physical
  command path; Phase 2 shadow computation starts only after contract/runtime
  equivalence tests are green.

## 0.0.1088 E.ON canonical persistence executor-safety checkpoint

- ROOT CAUSE VERIFIED IN CODE: `_async_persist_provider_imports()` performed
  synchronous canonical SQLite recovery, persistence and reconciliation inside
  an async Home Assistant call path, including cached recovery during setup.
- IMPLEMENTED/TESTED: site-scoped provider snapshots are captured on the HA
  loop and the complete synchronous persistence/reconciliation chain runs in
  `hass.async_add_executor_job`. A manager-local async lock preserves the
  previous single-flight ordering while the executor work is active.
- PRESERVED: setup/refresh await ordering, immutable recovery semantics,
  exact-site binding, deterministic provider data, fail-closed behavior and
  all prior P1, replay, history, phase and frontend behavior. The executor
  helper receives plain captured data and performs no HA API calls.

## 0.0.1087 load-forecast startup lifecycle checkpoint

- ROOT CAUSE VERIFIED: `_async_capture_load_forecasts()` was created with
  `hass.async_create_task()` during config-entry setup, so Home Assistant kept
  it in the bootstrap completion barrier while it performed long-running
  forecast and canonical-storage work.
- IMPLEMENTED/TESTED: startup and cadence captures now share one
  site-independent single-flight owner created through Home Assistant's
  background-task API. Repeated triggers coalesce, exceptions are consumed by
  the owner, and unload cancels and awaits the active task.
- PRESERVED: forecast calculations, storage semantics, source provenance,
  site selection, fail-closed behavior, executor-backed blocking I/O and all
  prior P1, replay, history and frontend behavior.

## 0.0.1086 monthly forecast loop-safety checkpoint

- ROOT CAUSE VERIFIED: forecast update listeners could execute from a
  `SyncWorker` after an event was fired off the Home Assistant loop. The owner
  then called `async_create_background_task` directly, producing wrong-loop,
  pending-task and never-awaited coroutine failures.
- IMPLEMENTED/TESTED: event-driven scheduling is marshalled onto the active HA
  loop before owner state or the forecast coroutine is touched. The shared
  task proxy also supports single-flight completion callbacks when a defensive
  worker-thread caller remains. Unload cancellation and coalescing are
  preserved.
- SCOPE: no forecast values, storage semantics, site selection, replay logic or
  frontend rendering were changed.

## 0.0.1085 frontend history recomputation performance checkpoint

- ROOT CAUSE VERIFIED: raw history canonicalization searched the complete point
  array for every five-minute slot. Daily energy recomputation repeated that
  O(slots × points) work across six series, while live maxima formatted every
  point through locale conversion.
- IMPLEMENTED/TESTED: canonical meter slots now use a stable chronological
  nearest-point index, preserving null, zero, tie, gap and timestamp semantics.
  Daily maxima use one local-day interval instead of per-point locale formatting.
  No source selection, integration, rendering or energy semantics changed.
- BENCHMARK: the 10,000-point recomputation benchmark decreased from about
  4.35 s to 21–25 ms locally; the 20,000-point maxima benchmark decreased from
  about 59–72 ms to 16–29 ms. The regression test checks semantic equivalence.

## 0.0.1084 replay site isolation and timeout recovery checkpoint

- ROOT CAUSE VERIFIED: one global 20-minute replay timeout wrapped the complete
  multi-site run. A blocked site therefore delayed every later site, while
  cancellation of an executor-backed canonical read could leave the worker
  thread waiting on the shared SQLite connection lock. Coalesced triggers then
  started the same blocked work again after every timeout.
- IMPLEMENTED/TESTED: replay work now has one bounded single-flight task per
  site. Timed-out executor work is shielded and retained until it really ends,
  so the same site is not duplicated; other sites run independently. Replay
  reads use a site-local read-only SQLite connection and never write or migrate
  the canonical store. Store writes remain serialized, and unload cancels all
  retained site tasks deterministically.
- PRESERVED: exact-site causal selection, immutable storage, fail-closed
  qualification, bounded coalescing, read-only Step 9 semantics, and all
  0.0.1076–0.0.1083 energy, phase and frontend behavior.

## 0.0.1083 current-day phase history refresh checkpoint

- ROOT CAUSE VERIFIED: completed `meter_power_history` results were cached by
  the local date without a freshness boundary. Reopening the panel after a
  long interval therefore reused the first Recorder snapshot and appended
  only the newest live point.
- IMPLEMENTED/TESTED: current-day history continues to deduplicate concurrent
  in-flight requests, but completed current-day results are fetched again on
  a later request. Invalid or fabricated points are not introduced, while
  bounded completed-cache behavior remains available for non-current dates.
- PRESERVED: full local-day Recorder interval, deterministic phase merge,
  live-event continuity, gap handling, exact source mapping, and the
  0.0.1076–0.0.1082 P1/import and chart fixes.

## 0.0.1082 phase chart live-event continuity checkpoint

- ROOT CAUSE VERIFIED IN CODE: the frontend subscribed to the generic
  `state_changed` stream only for configured accumulated import/export
  entities. Phase state changes therefore had no direct frontend append path;
  the phase chart could retain its initial Recorder series while live header
  values changed through the existing meter event/state path.
- IMPLEMENTED/TESTED: phase-source state changes are normalized into the same
  bounded phase-history merge used by `elrakning_meter_power_update`. Existing
  timestamps are replaced rather than duplicated, finite values only are
  accepted, and missing/invalid values do not become zeroes.
- PRESERVED: Recorder history bootstrap, exact source mapping, current/import
  semantics, no fabricated interpolation, existing phase gap handling,
  0.0.1076–0.0.1081 P1 and chart behavior, and frontend-only deployment
  semantics.

## 0.0.1081 P1 import/live consumption precedence checkpoint

- IMPLEMENTED/TESTED: The frontend meter merge keeps verified canonical/provider
  import fallback points but lets numeric current meter samples win at matching
  timestamps. This keeps Köp aligned with Last when both resolve to the same
  mapped grid-power source, without fabricating values or zero-filling gaps.
- PRESERVED: Canonical history remains the fallback for missing meter samples,
  exact-site/date isolation, signed import/export semantics, gap breaking and
  existing P1/provider provenance rules.

## 0.0.1073 idempotent E.ON cache recovery checkpoint

- IMPLEMENTED/TESTED: E.ON cached historical recovery isolates an immutable
  revision conflict per observation instead of aborting the complete startup
  batch. Existing canonical rows are never overwritten or deleted; exact
  replays remain idempotent and legitimate storage revisions remain governed
  by the canonical immutability rules.
- PRESERVED: exact-site binding, source provenance, deterministic recovery and
  fail-closed handling of changed facts.

## 0.0.1072 canonical P1 import precedence checkpoint

- IMPLEMENTED/TESTED: Verified site-bound local grid-power history is preferred
  over overlapping provider/reconciled import intervals. Canonical energy
  history is reused for billing when the meter-history path has no usable
  points, while provider history remains available for earlier coverage and
  safe gaps.
- IMPLEMENTED/TESTED: Missing actual import remains unavailable rather than
  being converted to zero. Frontend rendering prefers verified canonical
  energy history and falls back to raw meter history only when canonical
  coverage is absent.
- PRESERVED: Signed import/export semantics, exact-site isolation, fail-closed
  behavior and existing price/forecast separation.

Status labels: `VERIFIED` means directly supported by the recorded
static/runtime evidence; `INFERRED` means derived from documented code or
architecture; `UNKNOWN` means not established by the permanent evidence.

## 0.0.990 replay/monthly-forecast lifecycle correction

- ROOT CAUSE VERIFIED: monthly-forecast event listeners were active before the
  setup path assigned the shared task owner. An event in that setup window
  created an owner/task which was then overwritten by setup, leaving the task
  without a strong owner reference. HA subsequently reported
  `Task was destroyed but it is pending` for `elrakning_monthly_forecast`.
- CORRECTED/TESTED: setup and event scheduling now use one shared owner factory
  and preserve an owner created by an early event. Existing coalescing,
  cancellation, fail-closed forecast behavior and read-only semantics are
  unchanged.
- RUNTIME GATE: the pre-fix 0.0.989 HA log contains three pending-task errors
  at 19:05:50, 19:06:15 and 19:15:42 on 2026-10-03. Post-deploy absence of
  new replay/monthly-forecast pending-task errors remains required for closure.

## 0.0.962 canonical historical revision checkpoint

- CORRECTED/TESTED: Immutable provider observations now append a new canonical
  revision for strictly additive provenance enrichment when the immutable site,
  role, source generation, interval, resolution, value, quality and units are
  unchanged. Repeated enrichment is idempotent.
- PRESERVED: Value, interval, site, source-generation, quality and semantic
  changes remain fail-closed as `canonical_historical_revision_conflict`.
  Historical rows are never updated or deleted; readers select the latest
  revision for the semantic observation.
- RUNTIME ROOT CAUSE: 0.0.961 startup cached-import recovery encountered an
  E.ON `grid.energy_import` revision-1 collision where the existing 2 October
  buckets had the same actual kWh facts but older provenance omitted `padded`
  and `provider_actual`. No temperature-frame conflict was involved.

## 0.0.932 E.ON DAY and provider-trend checkpoint

- IMPLEMENTED/TESTED: The E.ON adapter now collects and normalizes verified
  `DAY` transfer responses through the same site-scoped padded/actual path as
  MONTH, HOUR and QUARTER_HOUR. Missing or padded data remains unavailable.
- IMPLEMENTED/TESTED: `/energy/trend` is persisted as a separate provider
  trend state with request, captured/known timestamps and installation-scoped
  provenance. It is explicitly unavailable as canonical actual data and as a
  forecast input; benchmark scoring remains a later separate design.

## 0.0.931 E.ON quarter-hour transfer checkpoint

- IMPLEMENTED/TESTED: The isolated E.ON provider adapter accepts the verified
  `QUARTER_HOUR` transfer aggregation and preserves exact provider timestamps,
  timezone offsets, actual versus padded points, and provider provenance in
  the per-facility state. Padded points are never included in actual totals;
  missing slots remain missing rather than being fabricated.
- PRESERVED: Existing MONTH and HOUR transfer paths are unchanged. Complete
  96-point daily and DST 92/96/100-point runtime evidence remains UNKNOWN and
  is not inferred from partial provider responses.

## 0.0.918 replay lifecycle checkpoint

- CORRECTED/TESTED: A replay task has a bounded 20-minute lifecycle timeout,
  based on the observed normal 12–15 minute production duration. Timeout,
  exception and cancellation paths all publish terminal diagnostics and then
  release coalesced pending work.
- IMPROVED/TESTED: Site start/completion diagnostics identify the last
  site-level phase without exposing telemetry or credentials.

## 0.0.917 Step 9 site-holdout semantics checkpoint

- CORRECTED/TESTED: The runtime site holdout requires at least one complete,
  causal, qualified window with explicit site identity. A second qualified
  physical site is not required by the canonical Step 9 contract.
- PRESERVED: Incomplete, contaminated or foreign-site descriptors remain
  excluded from the qualified evidence set; exact-site isolation and
  fail-closed behavior remain mandatory.
- OPEN RUNTIME GATES: Season and DST evidence remain pending. A separate
  physical site is not fabricated; Fiskvik remains fail-closed until it has
  legitimate site-scoped canonical inputs.

## 0.0.904 multi-site background and attention checkpoint

- IMPLEMENTED/TESTED: Monthly forecast input assembly iterates explicit
  `collection_enabled` site IDs rather than `active_site_id`, and resolves
  grid/electricity provider state from the requested site's binding/storage.
  An unconfigured current site therefore cannot suppress a configured
  background site or provide it with another site's tariff state.
- IMPLEMENTED/TESTED: The site-identity response exposes a bounded
  `ella.site_attention.v1` contract containing only safe metadata for
  explicit provider reauthentication/configuration action. Healthy and
  self-healing background states remain silent; foreign telemetry, source
  generations, provider consumption, economics and artifacts are excluded.
- VERIFIED/STATIC: Canonical collectors, solar/evidence capture, load forecast,
  replay and Greenely economics target explicit site IDs independently of the
  active UI site. Physical control remains disabled.

## 0.0.892 Step 9 runtime holdout pipeline checkpoint

- IMPLEMENTED/TESTED: Runtime replay now enumerates bounded candidate windows
  from exact-site canonical immutable frames and actual history. Descriptors
  retain decision/horizon identity, source generations, frame identities,
  maturity, actual coverage, causal status and publication-cutoff evidence.
- IMPLEMENTED/TESTED: Holdout categories report `qualified`, `pending`,
  `unavailable` or `disqualified` with explicit reasons and evidence
  references. Synthetic `deterministic_fixture` records are no longer used by
  the runtime runner as holdout evidence.
- IMPLEMENTED/TESTED: Qualified runtime runs include the canonical optimizer
  adapter when its inputs are available, plus evaluation-only actual,
  hindsight and regret evidence. Missing metrics remain unavailable.
- OPEN RUNTIME GATE: deployment must still produce real candidate windows and
  persistent artifact readback. Step 9 is not complete until the required
  real holdout categories and duplicate deterministic runtime readback are
  verified on Home Assistant.

## Canonical roadmap status

- The only active roadmap is `docs/architecture/ELRAKNING_MASTERPLAN.md`,
  Masterplan v2, steps 0–14.
- Runtime baseline `0.0.806` is stable after the Step 9 cross-day causal frame
  resolver and replay-runtime hardening.
  Step 6 — Forecast & baseline behavior and Step 7 — ESS Digital Twin &
  Battery Health and Step 8 — Economics & deterministic optimizer are COMPLETE;
  Step 9 — Replay, backtest, benchmarks & regret is ACTIVE/PARTIAL;
  Step 10 — Shadow & advisory planning is PARTIAL/IMPLEMENTED for category A
  read-only advisory plans, immutable snapshots, provenance and fail-closed UI;
  category B shadow evaluation is explicitly gated by Step 9 qualified live
  replay/artifact evidence.
  Step 11 — Learning, calibration & drift is PARTIAL/IMPLEMENTED for
  site-scoped causal learning governance, deterministic drift status, candidate
  identity and fail-closed promotion/rollback gates; live promotion remains
  gated by Step 9/10 evidence.
  steps 0–5 are established foundation with remaining
  hardening, retention, and multi-site details tracked explicitly.
- Runtime/Operations/Hardening is cross-cutting, not a separate stage.
- Stage/Phase labels in the historical sections below describe former release
  milestones only and are not active roadmap instructions.

## 0.0.791 Masterplan v2 Step 9 artifact checkpoint

- IMPLEMENTED/TESTED: `ella_replay_artifact.v1` is an immutable, exact-site
  artifact contract with run/dataset/source/model/calibration/parameter
  identities, qualification/contamination state, scorecards and provenance.
  `ReplayArtifactStore` uses the existing Home Assistant Store pattern, rejects
  schema mismatches fail-closed, deduplicates fingerprints and retains at most
  128 artifacts per site. Read-only append/list websocket commands are exposed;
  no execution path exists.
- IMPLEMENTED/TESTED: deterministic holdout qualification covers season, site,
  DST, gaps, source-generation changes and publication cutoffs. Contaminated
  or incomplete cases cannot qualify.
- IMPLEMENTED/TESTED: an internal canonical-storage runner selects a mature
  causal 96-slot window, resolves exact-site ESS facts and timestamped initial
  state, builds an artifact and persists it through the existing Home Assistant
  Store API. It has no execution or actuator path.
- CORRECTED/TESTED: artifact horizon slot counts use one replay horizon rather
  than summing baseline point counts, and actual outcome counts are restricted
  to replay slots.
- OPEN RUNTIME GATE: no artifact has yet been published/read back through the
  deployed HA runtime, and live holdout evidence is not claimed without that
  verification. Step 9 remains ACTIVE/PARTIAL.

## 0.0.785 Masterplan v2 Step 9 baseline checkpoint

- IMPLEMENTED/TESTED: fixed, cheapest-price and threshold battery baselines
  are explicit parameterized replay consumers. They preserve the canonical
  sign convention, ESS bounds, deterministic ordering and fail closed when
  required price inputs are absent. They have no runtime execution path.
- RUNTIME-VERIFIED: the historical Vikarbodarna replay selected the latest
  mature qualified load frame known at `2026-09-24T20:08:31Z`, paired only with
  causal qualified solar and price frames, and evaluated 96/96 actual outcomes.
  Two identical runs were qualified and produced the same fingerprint
  `237fe7b6ad35d8ca3e8a2d9655adb53f07c3e41987faff8dad759fd1f6bcab38` and
  identical scorecards. The current partial load frame remains separately
  fail-closed and was not used by the historical replay.
- OPEN: persistent benchmark artifacts, hindsight oracle isolation, optimizer
  comparison, forecast/optimizer regret, complete metrics and seasonal/site/
  DST/gap/source-change/publication-cutoff holdouts.

## 0.0.784 Masterplan v2 Step 9 replay foundation checkpoint

- IMPLEMENTED/TESTED: `ella_replay_benchmark.v1` is a pure, non-persistent,
  site-scoped causal replay artifact. It selects immutable frames with
  `known_at <= decision_at`, excludes future and wrong-site inputs, rejects
  ambiguous or unqualified selected frames, carries source-generation,
  model/calibration/schema identity, and emits a deterministic run fingerprint.
- IMPLEMENTED/TESTED: no-battery and self-consumption-only baselines use the
  canonical positive-grid-import/negative-grid-export balance and canonical
  positive-discharge/negative-charge battery sign. Scorecards expose cost,
  import/export, throughput/EFC where applicable, reserve/constraint/safety
  qualification and truthful unavailable cost status.
- IMPLEMENTED/TESTED: exact-site isolation, publication cutoff, source
  replacement, stale/gap/incomplete input, ambiguity, DST slot shape and
  deterministic output are covered by focused tests. No execution or actuator
  path is present, and actual outcomes are never used in decision selection.
- RUNTIME STATUS: release `0.0.784` ships the pure foundation and its remote
  payload is verified after deployment. Authenticated live replay execution
  against the current Vikarbodarna forecast could not be completed from the
  available non-interactive verification path; no runtime claim is made for
  that artifact. The full benchmark family, holdouts, regret and live replay
  artifact verification remain open.

## 0.0.758 Masterplan v2 Step 6 closure

- VERIFIED (release/runtime, 2026-09-26): Step 6 — Forecast & baseline
  behavior closed on `0.0.758`, commit
  `4357d4aade6c53c8c6c22383165258d46eb59a4a`. The power payload now names
  the `baseline_forecast` layer explicitly and keeps it separate from actual
  history and `ella_plan`; all six flow series retain slot-level source,
  classification and provenance.
- VERIFIED (tests): 784 Python tests and 46 subtests passed, all MJS tests,
  compileall, JSON validation and `git diff --check` passed. Regression
  coverage includes causal cutoff, site/source-generation isolation,
  canonical battery sign/grid balance, active solar-generation selection,
  load-frame provenance and deterministic baseline behavior.
- VERIFIED (deployment): the exact tracked integration payload matched remote
  SHA256 hashes; `ha core check` passed; exactly one normal Core restart was
  issued; the deployed manifest and panel both returned HTTP 200 and manifest
  version `0.0.758`; the served panel hash matched the deployed file.
- VERIFIED (runtime fallback evidence): fresh Vikarbodarna canonical storage
  remained site-scoped with the corrected active battery generation and causal
  Open-Meteo single-run frames. Persistent power-learning contained 375
  combined matured records with bounded context calibration. A current-day
  single-run frame was absent at the snapshot time, so the baseline correctly
  remained partial/short-horizon instead of inventing slots. This is runtime
  fail-closed evidence, not a claim that every source horizon was live-filled.
- No Stage 7+ implementation, optimizer, actuator behavior or execution gate
  changed. The Step 7 twin is read-only and does not enable physical control.

## 0.0.765 Masterplan v2 Step 7 closure

- VERIFIED (tests): the new `ella_ess_digital_twin.v1` contract is deterministic,
  exact-site and active-generation scoped. It exposes observed battery power,
  SOC and capacity, bounded throughput, and explicit unavailable states for
  missing resource mapping, EFC/SOH, efficiency/loss, temperature and derating.
- VERIFIED (tests): a mapped ESS trajectory obeys capacity, power, efficiency
  and reserve bounds; active-generation ambiguity fails closed; no actuator
  write path is exposed or enabled.
- VERIFIED (runtime replay, fresh Vikarbodarna canonical DB): the corrected
  battery generation, SOC and 25 kWh capacity are present. The source ledger
  does not provide one shared verified resource mapping for all three roles, so
  aggregate state, EFC/SOH, energy-balance efficiency/loss and derating remain
  unavailable by contract. Active battery throughput was 475.03 kWh across
  1,864 qualified 15-minute samples. No physical fact was fabricated.
- RELEASE: `0.0.765` contains the Step 7 read-only twin and is the new runtime
  baseline; Step 8 is the next main scope. Deployment evidence is recorded in
  the release report for this version.

## 0.0.768 Masterplan v2 Step 8 implementation checkpoint

- IMPLEMENTED/TESTED: `economic_optimizer.py` exposes the separate
  `ella_economic_optimizer.v1` read-only contract using pinned HiGHS 1.15.1.
  It validates causal 15-minute 24–36 hour inputs, verified ESS state and
  bounds, negative import prices, export value, efficiency and reserve
  constraints, mutually exclusive battery/grid directions and explicit
  replanning policy values. Outputs carry
  deterministic input fingerprints, objective breakdown and constraint
  provenance; no execution eligibility or write path is exposed.
- RUNTIME-VERIFIED: Core ABI is CPython 3.14.6 on aarch64 Linux, and matching
  highspy wheels are published for the target ABI. Vikarbodarna is not
  optimizer-eligible at this checkpoint: the current E.ON economics snapshot
  is not decision-time active and the live ESS roles do not form one verified
  aggregate resource contract. The runtime command therefore remains
  fail-closed until those existing site facts are valid.
- STATUS: Step 8 is not complete. No economics or ESS facts were fabricated,
  and no historical evidence was backfilled.

## 0.0.769 Masterplan v2 Step 8 economics policy checkpoint

- IMPLEMENTED/TESTED: Missing per-slot export compensation is normalized by the
  explicit derived policy `spot_price_sek_per_kwh * 0.75`. Explicit provider or
  site export compensation always wins; missing spot price remains unavailable.
  The result carries derived-fallback provenance and does not treat the policy
  as provider fact or double-count fixed fees.
- VERIFIED: The E.ON tariff snapshot remains authoritative but future-dated
  (`source_start_date=2026-10-01`); it is not labeled current before that date.
- STATUS: Step 8 remains PARTIAL. Runtime closure still requires verified
  reserve/min-SOC, charge/discharge hard limits, efficiency and explicit
  replanning/rate-limit policy values for the active ESS.

## Release and repository

## 0.0.775 Masterplan v2 Step 8 facts/policy checkpoint

- IMPLEMENTED/TESTED: `ella_ess_facts.v1` is a generic HA Store with exact
  site/resource scope, auditable source priority, idempotent append/update
  semantics, and authenticated WebSocket import/list operations. No
  site-specific values are stored in Git.
- IMPLEMENTED/TESTED: the read-only optimizer can consume exact-resource
  imported reserve/capacity/power facts, use deterministic product-policy
  replanning defaults derived from resolved caps, and use a clearly separate
  bounded planning-efficiency assumption. Step 7 physical efficiency remains
  unknown and is never widened by the planning assumption.
- IMPLEMENTED/TESTED: Economic inputs now require explicit decision-time
  provenance and valid_from/valid_to coverage. A future tariff fails closed
  instead of being mislabeled current.
- IMPLEMENTED/TESTED: A separate site-scoped economic applicability override
  can reference an existing provider agreement without copying its tariff
  values, changing provider `valid_from`, or backdating historical replay.
- IMPLEMENTED/TESTED: The optimizer accepts the override only when its
  provider reference, decision-time `known_at` and `effective_from` are valid;
  otherwise the future provider tariff remains fail-closed.
- IMPLEMENTED/TESTED: The runtime optimizer WebSocket now derives the economics
  metadata and deterministic provider reference from the active E.ON agreement
  and tariff component set before resolving the site override. Provider
  `valid_from` remains preserved separately.
- IMPLEMENTED/TESTED: Authenticated override import derives the provider
  reference server-side from the active E.ON binding when omitted; no manual
  fingerprint entry is required.
- HISTORICAL CHECKPOINT (0.0.771): The active Vikarbodarna site/resource contained
  six imported facts with the expected source priorities; planning efficiency
  remains explicitly planning-only. The optimizer still fails closed before
  the E.ON tariff `valid_from=2026-10-01`.
- STATUS AT THAT CHECKPOINT: Step 8 remained PARTIAL because the explicit
  active-site planning applicability decision had not yet been imported. This
  historical status was superseded by the authenticated 0.0.775 runtime
  closure below.

## 0.0.775 Masterplan v2 Step 8 runtime closure

- VERIFIED (runtime, 2026-09-26): Authenticated
  `elrakning/economic_optimizer` execution for Vikarbodarna used 96 causal
  15-minute Step 6 load/solar baseline slots, the exact shared ESS resource
  and the existing E.ON economics agreement.
- VERIFIED: The site-scoped applicability override was persisted with
  `known_at/effective_from=2026-09-26T15:26:30.184000+00:00`; provider
  `valid_from=2026-10-01` and provider provenance remained unchanged.
- VERIFIED: The optimizer returned `available=true`, 96 points, HiGHS
  deterministic MIP output, objective breakdown, constraint provenance and
  `execution_eligible=false`. Missing explicit export compensation used the
  derived `spot_price * 0.75` policy with derived provenance.
- VERIFIED: Repeating the identical authenticated call produced equal
  fingerprint, points and objective. No actuator or execution operation was
  invoked. Step 8 is COMPLETE; Step 9 is ACTIVE/NEXT.

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

## Historical architecture roadmap

The former 0–17 implementation order and the ELLA Phase/Stage roadmaps are
retained in Git history as evidence only. Their requirements have been
reconciled into the canonical Masterplan v2; do not treat their old headings
or milestone names below as active scope.

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

## 0.0.692 latest runtime baseline and architecture reset

- VERIFIED (runtime): `0.0.692`, release commit `b3b730f`, is deployed and
  served by Home Assistant. The release contains only the narrow dashboard
  spacing scope following the accepted 0.0.670 price-card DOM baseline. Its
  tracked implementation changes are not evidence that the future ELLA
  architecture is implemented.
- VERIFIED (release gate): Python `671 passed`, `46 subtests`, `0 failed`;
  all MJS tests, compileall, JSON/YAML validation and diff-check passed. The
  clean payload matched `61/61` SHA256 values, `ha core check` passed, exactly
  one normal Core restart was performed, HTTP returned `200`, and the relevant
  Elräkning/thread-safety log scan was clean. `HEAD == origin/main` at
  `b3b730f`; the known untracked user artifacts remain untouched.
- VERIFIED (scope): The accepted runtime remains capability-driven price-only
  planning with canonical load enrichment, site isolation, stale-response
  protection and the established card/graph interaction. It does not yet
  implement individual-load planning, action-based segmentation, decision-time
  debug snapshots, the learning/evaluation loop, solar/ESS action enrichment
  or physical actuation.
- HISTORICAL ROADMAP RESET: At the 0.0.692 documentation boundary, the
  authoritative next scope became the ELLA masterplan's Stage 0
  architecture/contracts reset, followed by Stage 1 capability registry and
  individual-load foundation. The former solar-first/ESS-later ordering was
  superseded. Stage 0 and Stage 1 are now closed by the later acceptance below.

## 0.0.694–0.0.696 Stage 1 capability registry and individual-load foundation

- `0.0.694` was the first Stage 1 deployment. It was not accepted because
  legacy ELLA binding still incorrectly gated Fiskvik planner/load eligibility,
  solar forecast capability was conflated with current-plan usage, and one
  logical role could collapse multiple active resources.
- `0.0.695` corrected those inventory semantics, but was not accepted because
  startup forecast capture retained a separate legacy ELLA-binding gate.
- `0.0.696`, commit `2f541cf0623c9c709e7b47db23583525d162a14d`, is the accepted
  Stage 1 runtime baseline. It removes the remaining legacy binding gate from
  forecast capture while preserving legacy ELLA binding data as transition
  state only. No planner price classification/action algorithm was changed.
- Stage 1 provides `ella_capability_inventory.v1` and the persistent,
  site-scoped `ella_load_registry.v1`, with read-only capability inventory and
  explicit site-scoped load list/state/upsert/remove websocket contracts.
  Inventory is derived from existing verified site data; it does not duplicate
  raw source datasets and introduces no dashboard card.
- Authenticated runtime acceptance confirmed for Vikarbodarna
  (`76f92eea-5720-4c19-9b43-17028d19a0a4`): price, retail/grid, house actual
  and forecast, grid power/import/export, solar actual and forecast, and
  battery power/SOC/capacity were available as reported capabilities; both
  active solar resources were preserved. Solar and battery capabilities were
  explicitly marked unused by the current planner, and execution plus actuator
  writes remained false.
- Authenticated runtime acceptance confirmed for Fiskvik
  (`66edee1e-ee32-4511-8e9d-4fc96947c861`) after a real site activation:
  price-only planning remained eligible without legacy ELLA binding;
  `ella_plan` returned the correct site-scoped seven-block plan; load forecast
  failed closed as `no_supported_history` rather than `ella_unbound`; solar,
  forecast and battery layers were unavailable without verified site sources.
  No fabricated values or cross-site data were observed, and Vikarbodarna was
  restored as the active site after the audit.
- Stage 1 runtime invariants are accepted: explicit binding plus valid
  fingerprint is authoritative, address/name heuristics are not used; legacy
  ELLA binding is historical transition state only; configured and runtime-
  available entities are distinct; all actuator execution remains disabled.
- At that historical point, the next implementation scope was **Stage 2 —
  Unified 15-minute site state and forecasts**. This former milestone
  preserved the accepted site isolation, provenance, fail-closed and no-write
  boundaries; it is now mapped to v2 foundation and forecast scope.

## 0.0.697–0.0.698 Stage 2 unified 15-minute site state and forecasts

- `0.0.697` was the first Stage 2 deployment and was not accepted. Runtime
  verification found that Fiskvik failed at the timezone gate, `net_load` was
  hardcoded unavailable even for compatible multi-PV elapsed slots, and
  `source_facts` exposed unbounded historical Forecast.Solar frames.
- `0.0.698` is the accepted Stage 2 runtime baseline after authenticated
  Safari/WS verification on both sites. It preserves the existing planner and
  seven-card segmentation; this release adds only the unified read-only state
  foundation.
- The accepted `ella_site_state.v1` contract returns a site-scoped,
  deterministic 15-minute state with explicit `known_at`, timezone provenance,
  horizon and source identities. Vikarbodarna returned 96 slots with 57
  actual, 15 historical-model and 24 forward-forecast load slots; all 96
  price slots were available.
- Vikarbodarna runtime confirmed complete multi-resource solar aggregation in
  70 elapsed slots, preservation of both PV generation identities, and
  `net_load` in 57 compatible elapsed slots using the explicit
  `positive_import_need_negative_surplus` sign convention. Future slots remain
  unavailable when no slot-resolved solar forecast exists; coarse Forecast.Solar
  facts are never distributed into fabricated quarter-hours.
- Vikarbodarna ESS power/SOC/capacity remain facts-only for compatible elapsed
  slots, with no future trajectory. `execution_eligible=false` and
  `actuator_writes_enabled=false` remain invariant.
- Fiskvik returned a valid 96-slot price-only state using
  `timezone_source=home_assistant_config_default` because its site timezone is
  absent. Load was unavailable for all slots with
  `no_verified_actual_forecast_or_model`; solar, ESS, net_load, source facts
  and economic facts were explicitly unavailable/empty without fabricated
  zeros. Only the shared verified Nord Pool price generation was present; no
  Vikarbodarna resources leaked into the state.
- Stage 2 runtime acceptance also confirmed bounded, deduplicated
  horizon-relevant `source_facts` (six relevant Vikarbodarna facts for the
  verified requested date), truthful unresolved economic-frame handling and
  no actuator/device writes.
- Stage 2 is closed and accepted. At that historical point, the next scope was
  **Stage 3 — Action planner in shadow/recommend-only mode**; this former
  milestone is now mapped to v2 steps 6 and 10.

## 0.0.702 Stage 3 action planner in shadow/recommend-only mode

- `0.0.702`, implementation commit
  `3e9afae9a49f376b6ebb635cf48c53f4a95655fa`, is the accepted Stage 3
  runtime baseline after authenticated Safari/WS verification on Vikarbodarna
  and Fiskvik. The action contract is `ella_action_plan.v1`, version
  `action-shadow-v1`, and remains immutable, deterministic and site-scoped.
- Both sites returned `available=true`, shadow execution semantics,
  `execution_eligible=false` and `actuator_writes_enabled=false`. No actuator
  or device writes are part of this stage.
- Runtime returned eight action blocks on each site. Elapsed blocks are
  `normal_operation` with `NOT_APPLICABLE` and the reason
  `Observerat tidsfönster; ingen retroaktiv rekommendation.`. Vikarbodarna's
  final future block was `18:30–00:00` local, `Dyr prisperiod`,
  `normal_operation`, with no qualified flexible resource requiring action
  and `NOT_APPLICABLE` execution status.
- The current site configuration has an empty `ella_load_registry.v1` on both
  Vikarbodarna and Fiskvik. Consequently, live runtime evidence correctly
  demonstrates fail-closed `normal_operation`; it does not demonstrate a
  positive live `run_flexible_loads` or `defer_flexible_loads` recommendation.
  Positive run/defer and `source_control_mode` behavior is covered by the
  accepted Stage 3 test fixtures and awaits a real configured load for live
  site evidence. This is a site-configuration limitation, not a Stage 3
  planner defect.
- ESS actions remain absent by design. The runtime reports
  `missing_verified_ess_policy_constraints` with missing
  `soc`, `usable_capacity`, `min_soc`, `max_soc`, `reserve_soc`,
  `max_charge_power`, `max_discharge_power`, `grid_charge_permission` and
  `efficiency`. No battery action is fabricated.
- Normal ELLA cards use the accepted three-level front contract: time and
  price context, primary action and short reason. Technical provenance,
  load values and execution/debug status remain off the card front. Runtime
  card intervals matched the action blocks, including the `18:30–00:00`
  split, and clicking it selected the exact UTC interval
  `2026-09-20T16:30:00+00:00` to `2026-09-20T22:00:00+00:00` in the price and
  SOC charts. Current-card centering remains edge-clamped at maximum scroll;
  that is the expected geometry limitation for the final card, not a failure.
- Stage 3 is closed and accepted. At that historical point, the next scope was
  **Stage 4 — Debug snapshot and explainability**. That former milestone used
  existing Debug mode only: clicking an ELLA card exposed `Visa data` and
  `Kopiera data` backed by a stored decision-time snapshot, not mutable
  current sensor state. The payload must include the exact site, block,
  revision, provenance, actions, constraints, capability availability and
  missing/ineligible reasons, and be suitable for copying into ChatGPT.
  Stage 5 learning/evaluation is not part of that scope.

## 0.0.703–0.0.714 Stage 4 and Stage 5 acceptance closure

- Stage 4 debug snapshots and explainability were implemented and runtime-
  verified through the 0.0.703–0.0.705 correction series. Existing Debug mode
  uses immutable decision-time snapshots and remains separate from the normal
  clean card front.
- Stage 5 is runtime accepted on `0.0.714`, commit
  `8a9fab7a6941d25200f2d9f9277442719399f754`. Forecast/model quality,
  planner/decision quality and execution quality remain separate, with
  site-scoped bounded learning and no actuator writes.
- The 0.0.713 post-restart slot `2026-09-20 21:30–21:45 CEST` produced a
  Vikarbodarna `house.consumption` observation with value
  `760.0104206977779 W`, coverage approximately `1.0`, and
  `learning_eligible=true`. Its evidence was classified
  `partial_high_coverage`; the intraday factor correctly remained `1.0` with
  `insufficient_support` after one eligible evidence point.
- 0.0.713 then exposed a storage-boundary defect on the following
  `21:45–22:00 CEST` flush: floating-point coverage marginally above `1.0`
  violated the SQLite contract and rolled back that flush. No learning
  evidence was fabricated from the failed interval.
- 0.0.714 clamps computed coverage deterministically to `[0, 1]`. Its full
  post-restart interval `2026-09-20 22:15–22:30 CEST` produced exactly one
  revision for the same site/role/generation, value `698.4902961477778 W`,
  unit `W`, `coverage_ratio=1.0`, `quality_status=good`,
  `boundary_carry_used=true`, `hold_seconds=360`, and
  `invalid_boundary_count=0`. The row was known at
  `2026-09-20T20:30:05.172953Z`; its last exposed event timestamp was
  `2026-09-20T20:25:19.562921Z`, before the interval end.
- Learning state increased deterministically from one to two eligible
  intraday evidence points without duplicates. The new point had baseline
  `1230.5523266980267 W`, actual `698.4902961477778 W`, ratio
  `0.5676234004790801`, coverage `1.0`, and qualification
  `good_high_coverage`. `intraday_factor` remained `1.0` with
  `insufficient_support`; support was not sufficient to promote a correction.
  No observation still produces no learning update.
- Exact predecessor age and first-event timestamp are not persisted in the
  canonical row. They are therefore not claimed as runtime facts. Frozen
  predecessor selection, next-quarter race isolation, bounded 360-second
  hold, invalid-boundary handling, generation isolation, restart-empty-cache,
  idempotence and coverage-clamp semantics are covered by automated tests.
  No older canonical rows or Stage 4 snapshots were rewritten.
- Runtime remains fail-closed for planner/execution quality:
  counterfactual evaluation is unavailable when individual loads are absent
  or ESS policy constraints are incomplete, execution is `NOT_APPLICABLE`
  without an actuator, and `execution_eligible=false` plus
  `actuator_writes_enabled=false` remain invariants. No actuator or device
  writes occurred.
- Stage 5 is closed and accepted. At that earlier closure boundary, the next
  scope was **Stage 6 — Solar/ESS enrichment and physical calibration**.
  Solar-first and ESS-first remain capability-scoped and must not bypass the
  accepted site-state, action and learning foundations.

## 0.0.715 Stage 6 runtime acceptance and closure

- Stage 6 is runtime accepted on `0.0.715`, implementation commit
  `9c5f7a3e8fa92cf2a67064f7dd881ccce6179b7a`. Deployment evidence was
  independently verified: 68/68 payload hashes matched, `ha core check`
  passed, exactly one normal Core restart completed, the runtime manifest
  returned HTTP 200, and no new Elräkning-specific log errors were observed.
- Authenticated Vikarbodarna runtime returned `ella_stage6_state.v1`. Solar
  calibration was correctly fail-closed: `available=false`, neutral factor
  `1`, support `0`, uncertainty `unknown`, reason
  `no_slot_resolved_forecast_overlap`, and no resource calibration entries.
  This is not a live learned solar factor; eligible overlap and promotion
  paths remain test-only evidence.
- Vikarbodarna exposed verified ESS physical facts through
  `ella_ess_physical_state.v1`: battery power `-687 W`, SOC `49 %`, and
  capacity `25 kWh`, all observed at `2026-09-20T21:00:00+00:00` with their
  respective source generations. Persisted canonical rows had
  `resource_id=null`; the runtime therefore preserved role/source facts but
  did not infer a per-ESS pairing or aggregate mapping.
- ESS policy remained explicitly separate and unavailable. Missing fields
  were `min_soc`, `max_soc`, `reserve_soc`, `max_charge_power`,
  `max_discharge_power`, `grid_charge_permission` and `efficiency`.
  Charge, grid-charge and discharge were ineligible; hold was a meaningful
  physical-state semantic but not executable. Planned SOC trajectory was
  unavailable with explicit missing physical/policy inputs; no future SOC was
  fabricated.
- The immutable Stage 4 debug snapshot contained the decision-time Stage 6
  solar calibration, ESS facts, policy gaps, action-specific eligibility and
  unavailable trajectory. It was not reconstructed from live values at click
  time. Global invariants remained `execution_eligible=false` and
  `actuator_writes_enabled=false`.
- Authenticated Fiskvik runtime remained available for site state and planner
  behavior while reporting solar calibration unavailable with
  `solar_forecast_unavailable`, no ESS physical resources/facts, no
  trajectory, and no fabricated values. Payload isolation checks found no
  Vikarbodarna site, battery-generation or solar-generation identifiers.
- Multi-ESS identity/aggregation, solar calibration promotion and uncertainty,
  valid planned SOC energy balance, efficiency/loss calibration, stale SOC,
  reserve/limit violations, temperature/derating and counterfactual replay
  were not live-exercisable. They remain test-only evidence and are not
  represented as live runtime acceptance.
- Stage 6 is closed and accepted. No manifest change, deploy or restart was
  performed during that docs closure. At that earlier closure boundary, the
  next scope was **Stage 7 — Controlled execution**; its implementation and
  acceptance are recorded below.

## 0.0.716–0.0.717 Stage 7 controlled execution acceptance and closure

- Stage 7 initial implementation was released as `0.0.716`, commit
  `2ca2177a98391658547ec3caad619c0d31ea2e60`. It added persistent,
  site/resource-scoped permissions defaulting off, a bounded idempotent
  command ledger, rate limiting, acknowledgement/readback, timeout and
  failure classification, manual override, rollback/safe fallback and a
  circuit breaker behind an explicit vendor-neutral adapter boundary.
- `0.0.717`, commit `556c4a8e97b15a2a63e9db9366449ab26e225b6a`, was the narrow
  corrective release. It fixed Stage 4 debug-snapshot retention: the latest
  14 plans per site are selected chronologically from `generated_at` with
  deterministic `decision_at`/`known_at` fallback, while legacy timestamp-less
  snapshots sort before valid timestamped plans. Snapshot payloads and hashes
  remain immutable, and retention is site-scoped.
- Release gates for `0.0.717` passed: 751 Python tests plus 46 subtests, all
  MJS tests, compileall/JSON/diff checks, 69/69 remote hashes, `ha core check`,
  exactly one normal restart, HTTP 200 manifest `0.0.717` and no new
  Elräkning-specific log errors.
- Authenticated runtime acceptance on 2026-09-21 verified Vikarbodarna
  (`76f92eea-5720-4c19-9b43-17028d19a0a4`) with zero permissions, zero command
  ledger entries, zero breaker entries, no manual override,
  `execution_eligible=false` and `actuator_writes_enabled=false`. Its current
  shadow plan and exact debug request matched site, plan, revision and block;
  the immutable snapshot hash was
  `823f1be074497d986691b9af7cc34877d331bc6802cf31f157f1c04375d20792`.
- Fiskvik (`66edee1e-ee32-4511-8e9d-4fc96947c861`) showed the same default-off
  zero-write state. Its shadow plan and exact debug request matched all IDs;
  its immutable snapshot hash was
  `182617632c061d8a6e11dcdcc2bbfde58be1d741fa16e22262a5e1487deaa821`.
- Retention proof after new plans were generated: Vikarbodarna held 166
  snapshots across exactly 14 plan IDs, including 26 blocks from the new
  plan; Fiskvik held 66 snapshots across 6 plan IDs, including 26 blocks from
  its new plan. The former lexical-retention regression is therefore closed.
- Live acceptance is intentionally zero-write because no explicitly armed
  verified actuator exists on either site. Adapter success/acknowledgement,
  timeout, idempotency, rate-limit, manual-override, rollback and
  circuit-breaker behavior is accepted as deterministic adapter-test evidence,
  not as fabricated live hardware execution. No live permission was armed and
  no physical command was issued. Planner and execution quality remain
  separate.
- This records the historical closure of the former ELLA Stage 0–7 roadmap.
  It is superseded as the active roadmap by Masterplan v2; its runtime
  evidence remains mapped into the v2 foundation, shadow, diagnostics, and
  safety scope. The active v2 step is 6 and step 7 is next. This historical
  closure must not be read as claiming that the older Stage labels were the
  complete long-term Energy Intelligence plan.
## 0.0.933 E.ON provider import fallback checkpoint

- E.ON actual transfer buckets are persisted only as site-scoped `grid.energy_import` observations.
- Priority is local canonical grid/import data, then actual E.ON QUARTER_HOUR, HOUR, DAY and MONTH buckets.
- Padded provider points are rejected; coarse buckets are never disaggregated.
- E.ON trend remains separate and is not actual or forecast input.
