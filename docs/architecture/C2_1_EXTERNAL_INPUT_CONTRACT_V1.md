# C.2.1 External input source contracts and fixtures

Status: locked design and deterministic fixtures; no producer is implemented.

This document separates canonical source facts from Solar Evidence-v1 consumer
selection. Evidence is not the canonical Forecast.Solar source contract.

Canonical observation != Evidence frozen baseline.

## Dataset matrix

| Source/provider | Request contract | Dataset identity | Target semantics | Canonical logical role | Evidence usage | Share revision chain? |
|---|---|---|---|---|---|---|
| Forecast.Solar live/current | Home Assistant Forecast.Solar entities resolved through the site binding and role mapping; no provider HTTP fetch by Elräkning | `forecast_solar.observed_facts.v1` | Role-specific current or forecast fact; target descriptor is part of the semantic key | `forecast_solar.*` | Indirect underlay only | YES within the same dataset, site, generation and target; NO across generations |
| Forecast.Solar day-ahead baseline | Same observed Forecast.Solar entity facts; Evidence selects the existing `capture_type=day_ahead` item captured before the target-day start | No separate canonical dataset; it is a consumer freeze policy over `forecast_solar.observed_facts.v1` | Target local calendar day; Evidence selection is not source semantics | `forecast_solar.daily_energy` when the underlying fact is proven daily energy | Frozen Evidence-v1 baseline | NO to the Evidence row; canonical observations may retain all legitimate knowledge revisions |
| Open-Meteo manager forecast | `https://api.open-meteo.com/v1/metno`; `global_tilted_irradiance`; `forecast_days=3`; `timezone=auto`; site geometry/installation parameters | `open_meteo.manager_forecast.v1` | Future hourly forecast targets from the manager request; target time is normalized to explicit UTC | `solar.irradiance.forecast` | Not direct Evidence input | YES only within this manager dataset, site and generation |
| Open-Meteo Evidence previous_day1 | `https://previous-runs-api.open-meteo.com/v1/forecast`; `global_tilted_irradiance_previous_day1`; `models=metno_seamless`; `start_date=end_date=target_date`; `timezone=Europe/Stockholm`; Evidence geometry | `open_meteo.evidence_previous_day1.v1` | Completed target local calendar day reconstructed from the previous-day run | Evidence-specific input, not a C.2.1 canonical producer | Direct Solar Evidence-v1 input and isolation/non-regression evidence only | NO to the manager dataset and NO to canonical manager revisions |

The same provider name is not sufficient to share a dataset or revision chain.
Request endpoint, model, variables, geometry, timezone, target semantics and
transformation semantics are source-contract identity.

## Forecast.Solar role contract

The following roles are locked only where the current integration proves their
meaning. Roles marked unsafe are not captured by C.2.2 until a provider/entity
semantic audit proves the target interval.

| Role | Unit/value | Target and validity | Site-timezone rule | Status |
|---|---|---|---|---|
| `today_kwh` | numeric `kWh` energy | Local calendar day; `valid_from` local midnight and `valid_to` next local midnight | Convert the two offset-aware local boundaries to UTC; DST day length is 23/24/25 hours as applicable | SAFE |
| `tomorrow_kwh` | numeric `kWh` energy | Next local calendar day; same interval rule as `today_kwh` | Same DST rule | SAFE |
| `remaining_today_kwh` | numeric `kWh` aggregate | Capture-relative remainder from `captured_at` to the next local midnight; it is not the same fact as `today_kwh` | Requires verified site timezone; retain capture-relative target descriptor | SAFE with explicit capture-relative key |
| `power_now_kw` | numeric `kW` power | Instantaneous/current observation at `valid_at=captured_at` | Timestamp is UTC; source local timezone remains provenance | SAFE |
| `peak_time_today` | timestamp-valued forecast fact | Predicted peak timestamp for the current local calendar day | Preserve the source offset and normalized UTC timestamp; target day is local | SAFE as timestamp value |
| `peak_time_tomorrow` | timestamp-valued forecast fact | Predicted peak timestamp for the next local calendar day | Same rule as `peak_time_today` | SAFE as timestamp value |
| `this_hour_kwh` | numeric `kWh` | Provider semantics do not prove whether this is the current local clock-hour or another provider bucket | Must not infer a bucket | UNKNOWN/UNSAFE |
| `next_hour_kwh` | numeric `kWh` | Provider bucket boundary is not proven by the current adapter | Must not infer a bucket | UNKNOWN/UNSAFE |
| `power_next_hour_kw` | numeric `kW` aggregate/forecast | Exact interval and provider bucket semantics are not proven | Must not infer a bucket | UNKNOWN/UNSAFE |
| `power_next_12_hours_kw` | numeric `kW` aggregate | Aggregate target/averaging semantics are not proven; it is not expanded into points | No synthetic interval | UNKNOWN/UNSAFE |
| `power_next_24_hours_kw` | numeric `kW` aggregate | Aggregate target/averaging semantics are not proven; it is not expanded into points | No synthetic interval | UNKNOWN/UNSAFE |

For safe roles, a canonical observation has `captured_at` and `known_at` from
the HA observation. There is no provider `fetched_at` or `published_at` in the
current entity path, so those fields remain null rather than being invented.
`known_at` is never used as target identity and must satisfy
`known_at <= decision_at` for replay inclusion.

## Identity, generation and revision

The source generation fingerprint is the SHA-256 of canonical JSON containing:

```text
provider/source adapter identity
config entry identity
site binding identity and installation context
role-to-entity mapping
source contract version
adapter/normalization version
site timezone state
```

Volatile values, capture timestamps, forecast values and Evidence counters are
excluded. A changed binding, installation, mapping, contract or adapter creates
a new source generation. An ordinary refresh does not.

The C.1 storage implementation uses `UNIQUE(semantic_key, revision)` and
requires `supersedes_frame_id` to point to revision minus one of the same
semantic key. Therefore `source_generation_id` is a revision partition inside
the semantic identity, not a cross-generation supersedes chain. The semantic
key is deterministic and contains:

```text
dataset identity | site scope | source generation | logical role | target descriptor
```

It never contains `captured_at`, `fetched_at`, `known_at`, value, or revision.
For the same generation and target, a new knowledge state is revision N+1. A
new generation starts revision 1 with no supersedes link to the old generation.

## Open-Meteo manager contract

The manager frame is site-scoped and contains endpoint, provider/model,
installation geometry/fingerprint, requested variables, timezone request,
forecast horizon, request fingerprint, `fetched_at`, `captured_at`, and
`known_at`. `published_at` is null unless the provider supplies a real
publication timestamp. Each point contains explicit UTC `valid_at`, original
source timestamp/offset, GTI in `W/m²`, and quality/provenance.

Raw GTI and potential DC are not the same source fact. Until a separate derived
dataset contract is implemented, potential DC is not canonicalized. If it is
later captured, it must use a separate logical role/dataset and explicit
derived classification.

The current manager's mutable HA Store remains a runtime cache. C.2.1 does not
make it an immutable producer and does not migrate it or Solar Evidence data.
If transport or HTTP response caching is deduplicated later, the site binding,
site_id, installation fingerprint and source generation remain part of the
canonical frame provenance; cache identity must never become site ownership.
Malformed/missing values remain quality gaps; no interpolation, clamping,
zero-fill or synthetic hourly points are allowed in the canonical producer.

## Evidence non-regression

The `solar_evidence` Store, evidence-v1 qualification, historical rows,
previous_day1 fetch, frozen baseline selection, counters and consumers are
untouched. The current minimum evidence counts (Open-Meteo 8/21 and
Forecast.Solar common 7/14) must be preserved before and after any later
producer release. A canonical producer must be additive and must not migrate
or rewrite Evidence rows. If compatibility requires changing the Evidence
definition, stop and create a separate architecture decision.

## C.1 schema sufficiency

C.1 schema v1 is sufficient for these contracts: frame metadata carries the
dataset, site, source generation, timestamps, classification, quality and
provenance; points carry `valid_at`, value/unit and point provenance. No schema
migration is required for C.2.1. C.2.2 and C.2.4 writers remain separate
scopes.

The fixture suite is pure standard-library validation. It does not import Home
Assistant, instantiate a production manager, open canonical SQLite, write a
Store, or perform network/runtime actions.
