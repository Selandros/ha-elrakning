# Elräkning – Energy Intelligence Masterplan

## Purpose

Elräkning should become a general, site-portable Energy Intelligence system
for forecasting, simulation, optimization, and eventually safe automation.
It must use one shared model/motor architecture, with site profiles and
calibration as explicit context.

The governing data principle is:

> When uncertain, preserve model-relevant data with provenance. Missing
> historical data cannot be recreated later.

## Operating sites

### Vikarbodarna

Development, validation, shadow, replay, and calibration site with PV,
battery, house load, grid, prices, and weather. The physical Huawei battery
must remain read-only to the development system.

### Fiskvik

Future operating site. P1 and smartplugs arrive before PV/battery. It should
collect load data from day one and later reuse the shared engines with a local
site profile and calibration.

The UI-active site and collection-enabled sites are separate concepts.

Site identity is immutable while site names are mutable metadata. Physical
source replacement creates a new logical generation with explicit provenance
and effective dates; unknown historical effective dates remain unknown. Shared
external sources may be referenced by multiple site bindings without becoming
owned by one site.

## System layers

1. HA live state
2. Recorder history
3. compact model-data aggregates
4. immutable forecast/price/weather input frames
5. deterministic physical simulator
6. forecast models and calibration
7. MPC optimizer
8. shadow evaluation and benchmarks
9. safety layer
10. hardware-specific control adapters
11. frontend presentation

Operational data makes the current panel work. Model data makes future replay,
training, and validation possible. They must not be conflated.

## Data contract

Model-relevant observations should carry:

- `site_id`
- `source_id` and source fingerprint
- installation/configuration fingerprint
- `observed_at`
- `captured_at` where applicable
- `fetched_at` where applicable
- `known_at` for information available to a decision
- target timestamp/date
- value and unit
- measured/derived/estimated classification
- quality, stale, unavailable, and gap indicators
- model/protocol version where relevant

Backtest invariant:

```text
known_at <= decision_at
```

The contract is conceptual and versioned rather than tied to a database
implementation. Records must preserve site, role, source and installation
identity, interval and observation timestamps, capture/fetch/known times where
applicable, target validity, value/unit, measured/derived/estimated/forecast
classification, quality/stale/unavailable/gap state, provenance, and relevant
model/protocol versions. Timestamp storage must remain reproducible over
timezone and DST changes. Deduplication is defined per dataset semantics, not
by a universal key.

The normative P0-DATA-1 design is recorded in
`docs/architecture/P0_DATA_CONTRACT_V1.md`. It freezes the storage-neutral
record envelope, source-generation and provenance semantics, UTC/timezone/DST
rules, quality and no-fabrication rules, truthful Recorder/LTS bootstrap, and
the `known_at <= decision_at` backtest gate. It closes contract design only;
storage selection and the long-term collector remain subsequent gates.

## Forecast engines

### Load

Start with robust baselines using hour-of-day, weekday/weekend, season,
temperature, recent load, holidays, and anomaly handling. Add site-specific
calibration for base load and temperature sensitivity. Smartplug data can
later decompose flexible loads.

### Solar

- PVGIS: physical reference profile
- Forecast.Solar: external operational forecast and frozen comparisons
- Open-Meteo: weather/irradiance forecast input
- actual PV: outcome/facility measurement
- Solar Shadow: candidate evaluation
- Solar Evidence: locked evidence protocol

Physical geometry is generalizable. Clipping, shading, inverter limits, and
local bias are site calibration.

### Price

Nord Pool is a global source. Provider markups, grid tariffs, taxes, fixed
fees, export compensation, and site contracts are site-specific. Published
future prices are valid only from their actual availability time onward.

## Battery digital twin

### V1

- usable capacity
- SoC
- reserve/min/max SoC
- charge/discharge power limits
- separate charge/discharge efficiency
- standby loss
- simulated import/export balance
- degradation cost per throughput kWh

### V2

- SoC-dependent limits
- power-dependent efficiency
- temperature derating
- minimum command duration
- measured usable capacity
- inverter operating losses

### V3

- richer temperature/aging behavior
- ramp-rate constraints
- detailed BMS derating
- nonlinear efficiency curves where measurements justify them

## Optimization

Use deterministic constrained MPC/LP/MILP for economic planning:

- 24–36 hour horizon
- 15-minute economic steps
- reoptimization approximately every 15 minutes or after material state/input
  changes
- hysteresis and command-rate limits
- only the first action is authoritative; the remainder is replanned

Objective should include import cost, export revenue, grid/power tariffs,
provider costs, battery degradation, reserve value, lost export opportunity,
and risk of future expensive import.

Peak/fuse protection is a separate fast safety loop, not a replacement for
economic MPC.

## Shadow mode and replay

Shadow mode has zero write capability. Each decision records the input frame
IDs, decision time, known-at times, model version, plan, simulated SoC,
simulated grid flow, predicted cost, actual outcome, and reason/objective
breakdown.

Counterfactual replay must use actual PV and house load as observations while
applying only the virtual battery's decisions. The real battery's observed
grid effect must not be mistaken for the virtual battery outcome.

## Benchmarks

Compare:

- no battery
- self-consumption only
- fixed schedule
- cheapest-hours schedule
- threshold arbitrage
- perfect-hindsight oracle
- Elräkning MPC

Report total cost, savings, import/export, peak power, throughput, equivalent
full cycles, self-consumption, self-sufficiency, curtailed PV,
degradation-adjusted savings, reserve violations, command count, and regret
versus the oracle.

## Flexible loads

Treat batteries and flexible loads as one optimization problem with separate
capability adapters. A flexible load needs a role, priority, required energy,
power range, time window, minimum on/off times, maximum deferral, manual
override, availability, and failsafe state.

## Safety and future real control

No real control before shadow, replay, benchmarks, and safety gates pass.
Future control must fail safe on stale/invalid SoC, invalid meter data,
communication loss, unavailable inverter, command timeout, failed
acknowledgement, HA restart, optimizer failure, reserve violation, or manual
override.

The optimizer must never select a wrong site, exceed hardware limits, bypass a
reserve, continue writing after a communication failure, or use future data.

Hardware adapters expose generic capabilities and validated actions; the
optimizer must not know Huawei, Growatt, Sungrow, or another vendor's API.

## Collection and retention strategy

Priority is compact long-term model value:

- P0: 15-minute load/PV/grid/battery/SOC, quality, provenance, and frozen
  forecast/price/weather frames
- P1: short-retention 5-minute data, battery throughput, phase data, and daily
  quality summaries
- P2: P1 day-one data and smartplug roles/events/constraints
- P3: 1-minute experiments and detailed diagnostics only when justified

Do not duplicate Recorder data without adding durable provenance, normalized
semantics, or replay value. Use short high-resolution retention and long
15-minute/daily retention where appropriate.

The initial retention direction is deliberately conservative: preserve raw
model-relevant data longer than today's Recorder window where its value is
uncertain; use one-minute data selectively, five-minute data medium-term,
canonical 15-minute data long-term, and daily/event summaries for very long
retention. Every dataset must later declare owner, resolution, retention,
aggregation/downsampling, provenance, and whether Recorder is sufficient.
Do not irreversibly downsample before the original value is understood.

## Battery Health, prices, and calibration

Battery Health is a first-class dataset. Where available, preserve reported and
estimated health separately, including SOH, capacities, energy, throughput,
EFC, SoC exposure, C-rate, temperature, efficiencies, cell spread, BMS
limits/derating, cycle counters, balancing observations, warnings, source,
site/product identity, quality, and estimator version.

Replacement prices are global, immutable, versioned product metadata. Actual
purchase price is site/install-specific. V1 degradation cost is a documented
positive approximation such as replacement value divided by expected lifetime
throughput; it is not an exact physical degradation model. Calibration is
need-driven and may be simulated/recommended in shadow only.

## Model lifecycle and diagnostics

Datasets, forecasts, calibration, simulator, and optimizer artifacts must be
reproducible through versions, immutable input-frame IDs, parameter
fingerprints, known-at semantics, validation/promotion status, and rollback
path. A/B shadow runs use the same immutable frame. Debug/Storage diagnostics
are read-only and should expose store identity, site scope, records, bytes,
time range, growth, retention, schema, quality/gaps, warnings, and Recorder
size separately without secrets.

NAS is optional archival/backup infrastructure and never live truth. The local
HA storage remains the normal runtime/model store while practical; runtime must
survive NAS unavailability.

## Implementation order

0. canonical data contract and architecture
1. long-term storage foundation
2. site-independent background collection
3. known-at and immutable forecast/price/weather frames
4. quality and provenance
5. Recorder/statistics coverage verification and raw load semantics
6. backtest/replay infrastructure
7. deterministic battery digital twin
8. baseline strategies and KPI suite
9. optimizer V1
10. live shadow mode
11. forecast and calibration improvements
12. Battery Health, degradation, and calibration maturation
13. Fiskvik P1/smartplug expansion
14. flexible-load optimization
15. fast peak/fuse safety controller
16. real-control adapter and safety review
17. only then consider physical control

Peak/fuse safety work may proceed in parallel earlier, but physical control is
still gated on its completion and verification.

## Completeness gates for the data and control foundation

The following are required acceptance details, not optional implementation
decoration:

- Every canonical observation preserves role, source generation, installation
  fingerprint, unit, sign convention, interval, timezone/DST-safe timestamps,
  quality, provenance, and schema version.
- Cumulative meters track generation, reset, rollover, and source changes;
  source replacement never rewrites historical observations.
- Forecast and price frames preserve publication/availability state and
  `known_at`; later corrected provider data must not replace the frame used by
  an earlier decision.
- Replay tests cover missing/stale data, DST, source changes, meter resets,
  price publication timing, and `known_at <= decision_at`.
- Optimizer evaluation includes rule-based baselines and a hindsight oracle;
  forecast regret and optimizer regret are reported separately.
- Forecast evaluation is segmented by normal days, cold days, weekends, and
  anomalies, with uncertainty represented as intervals or scenarios rather
  than a single unexplained value.
- Battery evaluation includes degradation-adjusted savings, SOH/health trend,
  throughput/EFC, reserve violations, and command stability.
- Shadow mode rejects every physical write. Any future control adapter must
  validate capabilities, hard limits, stale state, acknowledgement, timeout,
  communication health, site identity, and safe fallback before acting.
- Flexible loads require explicit roles, availability, deadlines, interruption
  limits, manual override, actuator safety, and failsafe behavior.
- Storage implementation is chosen using measured growth, query performance,
  backup/restore behavior, and provenance needs; JSON is not assumed suitable
  for every multi-year time series.

These gates preserve the distinction between architecture direction,
implementation details, and runtime evidence. Unknown database format,
collector implementation, solver, or Recorder coverage may remain open when
the contract and safety invariants are fixed; an unknown that would force
incompatible architecture choices is a memory blocker.
