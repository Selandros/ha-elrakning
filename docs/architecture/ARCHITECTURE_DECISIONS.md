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
