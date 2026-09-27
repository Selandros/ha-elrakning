# Elräkning – Canonical Masterplan v2

Status: canonical roadmap from 2026-09-26. This file is the only active
Elräkning roadmap. Historical 0–17, ELLA Phase 0–9 and ELLA Stage 0–7 plans
are superseded; their commits remain available in Git history.

## Baseline and active scope

- Stable runtime baseline: `0.0.791`.
- Steps 0–5: foundation established, with remaining retention, hardening and
  multi-site details tracked inside their contracts rather than treated as
  fully complete without evidence.
- Step 6 — Forecast and baseline behavior is complete.
- **Active step: 9 — Replay, backtest, benchmarks and regret.**
- Step 7 — ESS Digital Twin and Battery Health is complete on `0.0.765`.
- Runtime/Operations/Hardening is cross-cutting, not a roadmap step.
- No physical control is permitted before step 14 is accepted.

## Cross-cutting invariants

1. One generalizable model/motor serves all sites; site-specific data is
   context and calibration, never a separate hidden AI model.
2. `actual -> baseline_forecast -> ella_plan` are separate layers. Actual
   observations are never overwritten, baseline behavior is not an ELLA
   command, and an ELLA plan is not actual behavior.
3. The six canonical power-flow layers are Köp, Sälj, Sol, Last, Laddning and
   Urladdning. Each value retains source, classification and provenance.
4. `Observe -> Recommend -> Control` is explicit. Missing, stale, ambiguous or
   wrong-site data is unavailable or fail-closed, never fabricated or zero-
   filled.
5. `active_site_id` is presentation context only. Background collection and
   planning use explicit site IDs and `collection_enabled` state.
6. Every model-relevant record preserves site/source identity, source
   generation, units/sign convention, quality, timestamps, target validity,
   provenance and `known_at` where applicable.
7. Replay and backtest paths obey `known_at <= decision_at`. Immutable frames
   and old plan/snapshot payloads are not rewritten.
8. Planner and execution quality are separate. No actuator permission is
   implied by telemetry, recommendation or forecast availability.
9. Forecast/Solar Evidence/source precedence and persistent learning remain
   site-scoped and deterministic. Safety limits are never widened by learning.

## Roadmap steps

### 0 — Governance, invariants & scope

Unify product boundaries, safety rules, source/provider agnosticism, evidence
levels, site isolation, no-fabrication and observe/recommend/control semantics.

Acceptance: all later contracts distinguish measured, derived, estimated,
forecast, unavailable, stale, gapped and test-only data; no future step is
claimed complete without runtime evidence.

Status: foundation established; historical Stage 0 scope is absorbed here.

### 1 — Canonical data & source lifecycle

Define logical roles, canonical units/signs, source generations, site/resource
identity, meter reset/rollover, replacement/rebinding and immutable historical
semantics.

Acceptance: exact site/source generation and provenance are preserved; source
replacement never silently rewrites historical meaning; wrong-site data fails
closed.

Status: foundation established; some role-specific and multi-resource coverage
remains bounded by available runtime capability.

### 2 — Long-term storage & collection

Persist model-relevant 15-minute/daily data and immutable input frames with
restart-safe, idempotent, site-independent collection. Retention, durability,
recovery and Recorder/LTS boundaries must be explicit.

Acceptance: enabled sites collect independently of the active UI site;
storage survives restart/recovery; retention and query behavior are measured;
Fiskvik remains a clean room when sources are absent.

Status: foundation established, with remaining retention and source-specific
cadence details not promoted without evidence.

### 3 — External inputs & causal frames

Provide immutable, decision-time frames for prices, tariffs/economics,
Forecast.Solar, Open-Meteo, SMHI/weather, PVGIS and Solar Evidence. Preserve
publication state, `known_at`, source generation, revisions and precedence.

Acceptance: replay never sees information unavailable at decision time;
Forecast.Solar/Open-Meteo/Solar Evidence datasets remain distinct; missing
coverage is explicit and no coarse source is expanded into fabricated slots.

Status: foundation established through the external-input contracts and
runtime gates; full consumer coverage remains dataset-specific.

### 4 — History & energy semantics

Make canonical board history reusable across price, sol, last, köp/sälj,
battery, SOC and phases for Hour/Day/Month/Year. Preserve timezone/DST,
counter deltas, period/site identity, actual-vs-derived classification and
same-window energy formulas.

Acceptance: current-day summaries cannot be corrupted by a selected historical
date; cumulative counters are converted to truthful day deltas; missing or
mismatched sources produce unavailable values rather than false percentages.

Status: foundation established; remaining UI/data combinations require their
own evidence.

### 5 — Capability & site/resource model

Represent site-scoped capabilities and resources, including load registry,
ESS resources, observe/recommend/control modes, optional solar/ESS and Fiskvik
cold-start behavior. Shared engines must use local site calibration only.

Acceptance: every resource is independently verifiable; capability absence
removes only dependent behavior; no cross-site values or parameters leak.

Status: foundation established through the former capability and site-state
work; positive live flexible-load and complete multi-ESS cases remain limited
by current site configuration.

### 6 — Forecast & baseline behavior (COMPLETE)

Build the read-only forecast layer for Last, Sol, signed battery behavior and
derived Köp/Sälj. Keep actual history separate and expose the six canonical
power-flow layers with slot-aligned provenance. Baseline forecast means the
autonomous behavior likely to occur without ELLA intervention; it is not a
controller simulation.

Inputs include causal load forecasts, Solar Evidence/source precedence,
Open-Meteo/Forecast.Solar/PVGIS/SMHI data where valid, current observable
state, historical behavior and site calibration.

Acceptance: no future leakage; full legitimate horizon where sources support
it; no fabricated or zero-filled missing components; actual/forecast cutoff is
correct; battery sign and grid balance are canonical; same data supports
runtime payload, graph and provenance.

Persistent frozen forecast evidence, matured target-slot evaluation,
context-level calibration and bounded learning belong here. Learning must not
change execution safety constraints.

Status: complete on `0.0.758`, commit `4357d4aade6c53c8c6c22383165258d46eb59a4a`.
The released contract explicitly identifies `baseline_forecast` as separate
from actual and `ella_plan`, preserves frame/source-generation/quality
provenance through the load and power payloads, and restricts autonomous
battery context training to active site-scoped solar generations. The release
passed the full regression gates and was deployed with exact tracked-payload
hash equality, `ha core check`, one normal Core restart, HTTP 200
manifest/panel checks and no new Elräkning-specific errors. Runtime fallback
verification against the fresh Vikarbodarna canonical DB confirmed site
isolation, canonical battery sign/grid balance, persistent matured power
evaluation and bounded context calibration. Missing causal single-run source
frames remain unavailable rather than being fabricated; this is the intended
partial-horizon behavior.

### 7 — ESS Digital Twin & Battery Health

Implement per-ESS physical state and deterministic digital-twin semantics:
SOC, usable/nominal capacity, limits, efficiency, standby loss, energy
balance, throughput/EFC, SOH, temperature and derating when verified.

Acceptance: no aggregate without verified resource mapping; trajectory obeys
capacity/power/efficiency/reserve constraints; unknown physical facts remain
unknown; health/calibration is bounded and cannot widen hard limits.

Status: COMPLETE on `0.0.765`. The read-only twin exposes exact-site,
active-generation observed ESS facts, throughput and deterministic bounded
trajectory semantics. Resource aggregation, EFC/SOH, efficiency/loss,
temperature and derating remain explicitly unavailable when runtime lacks a
verified physical mapping or source; no unknown fact is inferred.

### 8 — Economics & deterministic optimizer

Normalize spot, provider, grid, tax, VAT, fixed fees, export value,
degradation and peak-policy inputs without double counting. Build deterministic
LP/MILP/MPC planning at 15-minute resolution over 24–36 hours with bounded
replanning, hysteresis and rate limits.

When explicit export compensation is absent, the optimizer uses the explicit
derived policy `spot_price_sek_per_kwh * 0.75`; this is marked as derived
provenance, never provider fact. Explicit export compensation wins immediately,
and a missing spot price remains fail-closed. This policy does not disable export
and preserves future explicit export pricing.

Acceptance: economic inputs are decision-time valid; negative prices/export
are represented; optimizer output is reproducible, constrained and separate
from baseline forecast and execution.

Status: COMPLETE on runtime baseline `0.0.775` after authenticated
Vikarbodarna verification on 2026-09-26. The separate read-only HiGHS
deterministic MIP core produced a 96-slot plan from causal Step 6 load/solar
baseline inputs, the exact shared ESS resource and the existing E.ON agreement.
The site-scoped planning-applicability override became effective at its recorded
decision time without changing provider `valid_from=2026-10-01` metadata.
Two identical runtime calls produced identical fingerprints, points and
objective breakdowns. The plan preserved explicit derived export fallback
(`spot_price * 0.75`), exact site/resource provenance, constrained ESS behavior
and `execution_eligible=false`. No physical control or actuator path was used.
The former Stage 3 planner does not equal this optimizer.

### 9 — Replay, backtest, benchmarks & regret (ACTIVE/NEXT)

Run chronological, causal replay against no-battery, self-consumption,
fixed/cheapest/threshold, optimizer and hindsight-oracle baselines. Report
forecast regret separately from optimizer regret, including cost, import,
export, peak, throughput, EFC, reserve, degradation and safety metrics.

Acceptance: seasonal/site holdouts, DST, gaps, source changes and publication
cutoffs are covered; contaminated or incomplete runs are non-qualifying.

Status: ACTIVE. The causal replay foundation, explicit fixed/cheapest/threshold
baselines, the read-only Step 8 optimizer adapter and evaluation-only hindsight
oracle contract are implemented in `replay_benchmark.py` and
covered by deterministic unit tests. The full benchmark suite is not complete;
the historical Vikarbodarna foundation replay is runtime-verified, while the
The persistent artifact/store contract, bounded retention, schema fail-closed
handling and holdout matrix contract are now implemented and tested. An
internal canonical-storage runner now selects a mature causal 96-slot window,
resolves exact-site ESS facts and timestamped initial state, builds an artifact
through the existing Store API and emits bounded readback evidence; live
deployment verification remains the closure gate.
Evaluation scorecards now expose actual-outcome peak/tariff/throughput/EFC
metrics with explicit unavailable degradation provenance, and plan evaluation
is separate from causal decisions. No execution or actuator path is included.

### 10 — Shadow & advisory planning

Produce immutable, explainable plans and advisory UI without physical writes.
Keep baseline forecast, actual and ELLA plan distinct; support card-to-graph
selection, planned-vs-actual and confidence/source explanation.

Acceptance: plan inputs are reproducible from decision-time snapshots; stale
plans expire safely; UI never implies execution when only recommendation exists.

Status: partial/implemented through former planner, snapshot and advisory
work; full MPC shadow evaluation remains open.

### 11 — Learning, calibration & drift

Maintain site-scoped forecast/planner evaluation, frozen evidence, matured
slots, error metrics, bounded calibration, drift detection, model candidates,
promotion gates and rollback. Keep global model structure separate from site
calibration.

Acceptance: no observation means no learning; no sign-mismatched ratio evidence
promotes calibration; low support shrinks to neutral; safety constraints cannot
be widened; old plans remain reproducible.

Status: partial. Stage 5 learning/calibration exists, but full drift and
promotion governance is not complete.

### 12 — Explainability & diagnostics

Keep immutable decision snapshots, Debug/Storage evidence, provenance,
bounded diagnostics, copy/clear behavior and runtime lifecycle observability.

Acceptance: diagnostics distinguish frontend/backend/request generations,
stale responses, errors and terminal cleanup without secrets or unbounded
payloads. Debug never reconstructs old decisions from live state.

Status: implemented/hardened through `0.0.757`; future changes are cross-cutting
operations, not a separate stage.

### 13 — Safety & controlled execution

Provide the separate fast peak/fuse safety loop, vendor-neutral adapters,
explicit permissions, acknowledgement, timeout, idempotency, rate limits,
manual override, rollback, safe fallback and circuit breaker.

Acceptance: stale/invalid state, wrong site, missing permission, failed ack or
boundary violation yields no write and stops safely. Unarmed sites remain
zero-write.

Status: execution boundary and adapter tests exist; physical safety loop and
live armed actuator remain incomplete.

### 14 — Physical-control gate

Allow physical control only after the digital twin, replay, benchmarks,
shadow evidence, health/safety gates and verified actuator/resource contract
are accepted. Physical control is the final gate, not an automatic consequence
of Stage 7 history.

Acceptance: supervised rollout, explicit arming, live revalidation,
acknowledged commands, rollback and proof of no wrong-site or unsafe writes.

Status: not complete; no physical control is currently allowed.

## Historical migration and crosswalk

The following are historical inputs, not active roadmaps:

- Old Energy Intelligence `Implementation order 0–17` is absorbed into v2
  steps 0–14.
- ELLA Phase 0–9 is absorbed into v2 contracts, forecast, optimizer, shadow,
  learning and safety sections.
- ELLA Stage 0–7 is historical implementation structure, not the current
  roadmap. Its capability, planner, snapshot, learning, ESS and execution
  requirements remain evidence for the corresponding v2 steps.

The former Stage 3 planner does not satisfy v2 step 8's full deterministic
optimizer. Former Stage 6 physical facts do not satisfy v2 step 7's complete
digital twin. Former Stage 7 execution boundary does not satisfy v2 step 14's
physical-control gate.

## Cross-cutting operations and hardening

Performance, history/enrichment separation, day-switch stale guards,
diagnostics persistence, request deduplication, safe cancellation, frontend
render resilience and release verification are cross-cutting operations. They
must protect the `0.0.757` baseline but are not roadmap stages and must not
silently change forecast, learning, safety or actuator semantics.

## Unified acceptance rules

- Static tests, runtime evidence and test-only adapter evidence are reported
  separately.
- Every release preserves site isolation, source/provider agnosticism,
  no-fabrication, actual/forecast separation, causal replay and zero-write
  defaults until step 14 is accepted.
- A capability is not considered runtime-accepted because a fixture or fake
  adapter exists.
- Any future roadmap change must update this file rather than creating another
  active roadmap.
