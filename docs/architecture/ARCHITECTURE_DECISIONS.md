# Elräkning – Architecture Decisions

## AD-001 Global intelligence

Elräkning shall build one shared, generalizable Energy Intelligence. It shall
not build separate AI, forecast, or battery models for Vikarbodarna, Fiskvik,
or other sites.

Data from multiple sites may train shared models. Site-specific information is
context, configuration, physical parameters, calibration, and live state; it
is not a separate site model.

## AD-002 Active site

`active_site_id` is UI/configuration context only. It must never determine
which site collects data. Background collection is controlled separately, for
example by `collection_enabled`.

## AD-003 Historical data

Model-relevant history has priority. If history is not collected, it cannot be
reconstructed later. When uncertain, preserve compact, provenance-rich data.

## AD-004 Battery control

Economic battery control shall be deterministic MPC/LP/MILP. ML/AI may be
used primarily for forecasting, calibration, and battery-health/degradation
estimation. Safety limits must never be ML decisions.

## AD-005 Shadow first

No physical battery control before shadow mode, replay/backtesting, and safety
gates are established. Shadow mode has zero write-path to the real Huawei
battery at Vikarbodarna.

## AD-006 Battery health

Battery health is a first-class concern. Collect SOH, usable capacity,
throughput, equivalent full cycles, SoC exposure, temperature, efficiency,
and relevant BMS/derating data where available.

## AD-007 Battery price history

Product replacement price is global, versioned product metadata. Actual
purchase price is installation/site-specific. Historical prices must never be
overwritten.

## AD-008 Calibration

Calibration is need-driven, not a blind fixed interval. Battery Health
determines when recalibration is needed; the optimizer chooses an economically
appropriate opportunity.

## AD-009 Backtest integrity

Backtests may use only information available at decision time. The hard rule
is `known_at <= decision_at`.

## AD-010 Site and source lifecycle

`site_id` is an immutable UUID. Site name is mutable metadata; renaming does
not create a new site. A sensor/entity rename does not create a new source
generation when stable source identity is unchanged.

A physical source replacement creates a new logical source generation carrying
site, role, source identity, relevant entity identity, effective dates, and
provenance. Historical generations are append-only: remove, replace, or move
never deletes historical data. Unknown historical `effective_from` remains
unknown. Shared external sources may be referenced by multiple site bindings
without being owned by one site.

## AD-011 Site-independent collection

`active_site_id` is UI, presentation, and configuration context only.
`collection_enabled` is explicit per-site state. Background collection runs
for explicit site IDs, is restart-safe and idempotent, may collect multiple
sites in parallel, and must not cause frontend rendering for inactive sites.
Collectors should be lightweight and may reuse Recorder for raw live history
when safe, but permanent model history must not depend solely on Recorder.

## AD-012 Canonical model-data contract

The canonical contract is conceptual and versioned; it does not select a
physical database implementation. Where relevant, records must carry schema
version, dataset/type, site, role, source identity/fingerprint,
installation/configuration fingerprint, interval and observation timestamps,
capture/fetch/known times, target validity, value/unit, measured/derived/
estimated/forecast classification, quality/stale/unavailable/gap state,
provenance, and model/protocol version. Timestamp storage must be reproducible
across timezone and DST. Deduplication is dataset-semantic, not a universal
key that can collide between roles, sources, or measurements.

## AD-013 Retention and information value

It is better to collect too much model-relevant data initially than to discover
later that irreplaceable history was never collected. Retention remains
information-value driven and must specify owner, resolution, retention,
aggregation/downsampling, provenance, and whether Recorder is sufficient.
The initial direction is generous justified raw retention, selective one-minute
data, medium-term five-minute data, very long-lived canonical 15-minute data,
and very long-lived daily/event summaries. Irreversible downsampling is not
allowed before the original value is understood.

## AD-014 Battery Health and price history

Battery Health is first-class. Where exposed, collect reported SOH, capacities,
charge/discharge energy, throughput, EFC, SoC exposure, C-rate, temperature,
efficiencies, cell spread, BMS limits/derating, cycle counters,
balancing/calibration observations, and health events. Preserve site,
product/device identity, source, observed time, relevant `known_at`, quality,
and estimator version. Reported BMS SOH and estimated health remain distinct;
health may affect degradation/calibration, never hard safety limits.

Replacement prices are global, versioned, append-only product metadata.
Actual purchase price remains site/install-specific. Price revisions retain
immutable identity, product, price/currency, VAT and scope semantics, effective
interval, `known_at`, source, and notes.

## AD-015 Shared model lifecycle and backtest integrity

Datasets, forecasts, calibration, simulator, and optimizer artifacts must be
traceable through versions, training snapshots, parameter fingerprints, input
frame IDs, creation time, `known_at`, validation/promotion status, and rollback
path. A/B shadow runs use exactly the same immutable input frame. Promotion
requires explicit backtest, shadow, and safety gates.

Backtests must make timezone/DST explicit, never fill missing data with future
information, and use the oracle only as a theoretical upper bound. Report
forecast-driven regret separately from perfect-forecast regret.

## AD-016 NAS and diagnostics

NAS is optional archival/backup infrastructure, not live truth. Runtime/model
storage remains local HA storage while practical, and runtime must survive NAS
unavailability. NAS may hold versioned backups, cold archives, immutable input
frames, training datasets, and audit artifacts.

Future read-only diagnostics may expose store/site identity, record and byte
counts, oldest/newest timestamps, growth, retention, schema, quality/gaps,
largest datasets, warnings, and Recorder size separately. Credentials and
secrets must not be exposed.

## AD-017 Data-foundation acceptance gates

No forecast, optimizer, shadow, or backtest implementation may be treated as
trustworthy until the model data has a versioned canonical contract,
source/site identity, sign convention, quality/provenance, retention policy,
and explicit `known_at` semantics. The foundation must distinguish measured,
derived, estimated, forecast, unavailable, stale, gapped, duplicate, and
interpolated values.

The first data gate is a read-only audit of real source entity IDs, Recorder
coverage, long-term-statistics coverage, common overlap, and physical
semantics. Runtime evidence must remain separate from static inference. The
verified `sensor.total_consumption` balance is a gross-load candidate for the
observed regimes, but its source provenance and long-term retention still need
explicit documentation before it becomes a universal canonical source.

## AD-018 Replay, safety, and reproducibility gates

Backtest/replay infrastructure precedes optimizer quality claims. Replay must
be chronological and expose only frames satisfying `known_at <= decision_at`.
Timezone/DST transitions, price-publication state, missing data, source
changes, and meter resets are explicit test cases. Runs retain dataset,
source/site, calibration, model, parameter, schema, and deterministic-seed
identities so results can be reproduced and rolled back.

Shadow mode is contractually zero-write: any attempted physical write is an
error. Future real-control paths require deterministic hard limits,
stale/invalid-input rejection, safe fallback, command acknowledgement and
timeout handling, deduplication/hysteresis, and proof that no command can
target the wrong site. Flexible loads must define role, availability,
deadlines, interruption limits, manual override, and a failsafe state before
they enter optimization.

## AD-019 Evaluation and information preservation

Optimizer evaluation must include no-battery, self-consumption-only,
cheapest-hours/threshold, MPC, and perfect-hindsight-oracle baselines. Report
cost/savings, import/export, peak/tariff impact, throughput/EFC,
degradation-adjusted savings, self-sufficiency, reserve/constraint
violations, command reversals, and regret. Forecast-driven regret must be
separated from optimizer-driven regret.

Model-relevant raw/detail data may be retained generously while growth is
measured, then downsampled only after its value is understood. Canonical
15-minute and daily/event data are long-lived targets; price, forecast,
quality, calibration, health, command, and source-change events retain their
provenance and effective/known times. This is an explicit P0 concern while
Recorder retention remains short or unverified.

## AD-020 Source/provider agnosticism

Elräkning's shared architecture is source- and provider-agnostic. Generic
logic must never depend directly on today's sensor/entity IDs, hardware vendor,
Home Assistant integration/platform, electricity retailer, grid company,
tariff provider, forecast provider, inverter, battery, meter, or other
replaceable external source.

Stable logical roles and capabilities are the contract. The current source for
a role is resolved through explicit site/source bindings, mappings,
registries, adapters, or equivalent runtime configuration. Vendor- or
provider-specific handling is permitted only behind an isolated adapter or
provider boundary and must not leak into generic collection, diagnostics,
history, forecasting, optimization, model, or presentation contracts.

Entity IDs, unique IDs, device IDs, config-entry IDs, provider names, and
vendor-specific identifiers are provenance/configuration observations, not
permanent architecture keys. A source may be renamed, replaced, removed,
split, combined, or migrated to another vendor/provider without breaking
unrelated functionality. Source changes must either preserve semantic
continuity explicitly or create a new source generation; they must never be
silently merged because an entity name happens to remain stable.

Generic functionality must fail or degrade explicitly when a required role is
missing or incompatible. It must not silently substitute another source with
unknown semantics. Tests for generic functionality must cover replacement or
rebinding and, where relevant, materially different provider/integration
shapes.

Current installations and providers, including FusionSolar/Huawei, Growatt,
HomeWizard, current electricity retailers, and current grid companies, are
runtime examples only. They are not permanent Elräkning product assumptions.
