# C.2.3B Open-Meteo immutable producer contract v1

Status: locked design and deterministic fixtures. No producer is implemented by this document.

## Scope and isolation

The canonical dataset is `open_meteo.manager_forecast.v1` with logical role
`solar.irradiance.forecast`, classification `forecast`, and unit `W/m²`.
`open_meteo.evidence_previous_day1.v1` remains a separate dataset and revision
chain. This contract does not change `solar_evidence.py`, Evidence-v1,
previous_day1, frozen Forecast.Solar baselines, counters, or historical rows.

Canonical collection is site-explicit. `active_site_id` is UI/configuration
context only and is never an eligibility or collection selector.

## Site-explicit target eligibility

The target resolver reads `site_identity.site_configs[site_id]`, requires
`collection_enabled == true`, and derives normalized sections from persisted
`power.solar_entities` and `power.solar_array_metadata`, plus the immutable HA
global latitude, longitude, and timezone. An existing Open-Meteo binding is
required as binding/provenance validation, but it does not supply missing
geometry and it does not make an otherwise incomplete site eligible.

A target is eligible only when latitude, longitude, at least one solar entity,
and complete finite section geometry (`peak_power_kwp`, tilt, azimuth) are
present and deterministic. Missing data is fail-closed: no request, no cache,
and no canonical frame. Current Fiskvik therefore produces zero targets and
zero canonical Open-Meteo frames.

The resolver must not activate a site, mutate PowerManager, render UI, or infer
geometry. Section grouping is by normalized source-defining request geometry;
source strings remain provenance and do not by themselves define generic source
identity.

## Request and source-generation identity

Each normalized section request contains only source-defining semantics:

```text
dataset=open_meteo.manager_forecast.v1
adapter_contract_version
endpoint=https://api.open-meteo.com/v1/metno
provider=open-meteo
model=metno
variables=[global_tilted_irradiance]
forecast_days=3
timezone_request=auto
site_id
latitude
longitude
tilt_deg
open_meteo_azimuth_deg
```

The deterministic section/request fingerprint is calculated from canonical JSON
of those fields. It becomes the source-generation identity together with the
site binding context and contract version. `peak_power_kwp` and
`source_strings` are provenance; they do not create a new raw-GTI generation
when request location/orientation/model are unchanged. A binding or request
contract change creates a new generation. Ordinary refresh, fetched time,
capture time, known time, values, `generationtime_ms`, cache `frame_id`, and
entity renames alone do not.

The frame semantic key is:

```text
open_meteo.manager_forecast.v1|site_id|source_generation_id|
solar.irradiance.forecast|section_request_fingerprint
```

The point key is `valid_at_utc` within that section frame. The frame represents
one complete provider response for one normalized request section; it contains
many hourly points. This per-section form matches the existing one-request-per-
section transport, isolates a failed section, permits unchanged-section
deduplication, and does not depend on array position. Reordering sections does
not change identities. A changed section revises only its own semantic chain.

## Revisions and replay

Identical request contract and identical raw point knowledge are deduplicated,
regardless of fetch/capture time. A changed value for the same generation,
section, and UTC target creates revision N+1 and supersedes revision N. A new
source generation starts at revision 1 and has no supersedes link across
generations. `UNIQUE(semantic_key, revision)`, point uniqueness, and the existing
same-semantic supersedes constraints remain authoritative.

`known_at` is the earliest local time the complete normalized response is
available to the decision system. Replay includes only frames with
`known_at <= decision_at`; later revisions are excluded. `frame_id` is an
immutable storage identity, never semantic identity.

## Times and timezone

`fetched_at` is the actual HTTP response-completion time. `captured_at` is the
local immutable-capture time after the complete section candidate is normalized;
for this synchronous producer it may equal `fetched_at` when recorded at the
same completion boundary. `known_at` is the same or later local availability
time and must satisfy the schema invariant `known_at >= captured_at`.

`published_at` is null: no genuine Open-Meteo publication timestamp is present.
`generationtime_ms` is performance metadata only.

The exact source timestamp text and API timezone metadata are retained in point
provenance. Naive local timestamps are resolved with the returned IANA timezone
using `ZoneInfo`, then stored as offset-aware UTC `valid_at`. A nonexistent
spring timestamp is a quality gap, never fabricated. An ambiguous autumn
timestamp is accepted only when response ordering/duplicates uniquely establish
a strictly increasing UTC sequence; otherwise it is a quality gap. The fixed
`utc_offset_seconds` value is never applied blindly across a DST transition.

## Raw values and quality

The canonical producer consumes the provider response before runtime-cache
clamping or derived calculations. Every finite provider GTI value, including a
negative finite value, is preserved exactly; it is not clamped. Null, NaN,
infinite, missing, malformed, duplicate, non-monotonic, or cadence-invalid
points are not fabricated. They are represented as explicit gap details in the
frame quality/provenance payload and no point is inserted for the bad value.

An HTTP failure for one section produces no frame for that section; other
independently successful sections may be captured. No `irradiance_kwh_m2`,
`potential_dc_kwh`, peak-power-scaled value, or other derived output is a
canonical point in this dataset.

## Shared fetch primitive and non-regression

The future implementation has three layers: a pure site-explicit request
builder, a provider fetch/normalization primitive, and two consumers (mutable
manager cache and immutable CanonicalCollector writer). Generic storage knows
only the locked dataset/role/frame contract. Neither consumer may switch the
active site or use cache identity as ownership.

The C.2.4 implementation must not modify `solar_evidence.py`, the previous_day1
request, Evidence-v1 qualification, frozen Forecast.Solar baselines, historical
rows, counters, or consumers. Baseline acceptance remains 39 days, 14
Open-Meteo-complete, 13 Forecast.Solar-common with the established full and
semantic hashes.

## Schema and acceptance

C.1 schema v1 is sufficient: frame metadata carries dataset/site/generation,
semantic key, revisions, timestamps, quality and provenance; points carry
point_key, UTC valid_at, value/unit, quality and provenance. No migration is
required.

Before C.2.4 release, pure tests must cover site eligibility, Fiskvik empty
configuration, section-order stability, multi-section identity, generation and
revision rules, timestamp/DST fail-closed behavior, raw negative GTI, malformed
gaps, replay filtering, deduplication, schema constraints, and Evidence
non-regression. Runtime must verify WAL integrity, no duplicate point or
semantic revisions, valid supersedes, site-independent collection, Vikarbodarna
frames, Fiskvik zero frames without legitimate source, restart persistence, and
unchanged Evidence hashes/counts.

This is a design-only scope. No production code or runtime data is changed.
