# Open-Meteo causal day-ahead Single Run contract v1

Status: design-only contract. No producer is implemented by this document.

## Dataset identity

- Dataset: `open_meteo.single_run_day_ahead_pv.v1`
- Role: `solar.irradiance.day_ahead_pv_forecast`
- Provider: Open-Meteo Single Runs API
- Endpoint: `https://single-runs-api.open-meteo.com/v1/forecast`
- Model identity: an explicitly selected Open-Meteo model; the producer must
  store the provider model identifier returned/selected by the request.
- One frame represents one explicit model-run vintage for one site and one
  target local calendar day. It is not `evidence_previous_day1.v1` and not
  `open_meteo.manager_forecast.v1`.

Open-Meteo documents `run` as the UTC model initialisation time. It is not the
time at which the result becomes available. The producer must therefore never
use `run_initialization_at` as `known_at`.

Authoritative provider references:

- https://open-meteo.com/en/docs/single-runs-api
- https://open-meteo.com/en/docs/metno-api

## Decision-time contract

For target local day `D`, `decision_at` is the absolute instant corresponding
to local midnight at the start of `D` in the verified site IANA timezone.
Timezone rules, including DST, are used to derive the instant; a fixed UTC
offset is not used.

A frame is causally eligible only when:

```text
known_at <= decision_at
```

This is the existing replay invariant. A run initialised before `decision_at`
but first acquired after it is `VERIFIED_POST_DECISION`, not eligible.

## Time fields

All fields are stored as offset-aware UTC instants after normalization.

- `run_initialization_at`: UTC initialization time named by the `run` request.
- `provider_response_received_at`: completion time of the successful response.
- `captured_at`: time the complete normalized frame is persisted.
- `known_at`: conservative earliest instant this system possessed the complete
  normalized frame. For v1, with no provider availability timestamp, this is
  `provider_response_received_at`; it is never backdated to run initialization.
- `target_valid_from` / `target_valid_to`: the two timezone-derived UTC
  boundaries for local day `D`.
- `decision_at`: the target-day-start instant used for replay selection.

The contract requires `known_at >= provider_response_received_at` and
`captured_at >= provider_response_received_at`. The implementation may use
the same completion boundary for response receipt, capture and known time.

## Frame contents

Each frame must bind:

- `site_id`, verified site timezone and location/config fingerprint
- dataset, role, provider, exact model identifier and transformation version
- `run_initialization_at`
- target local date and `target_valid_from` / `target_valid_to`
- latitude, longitude, tilt, azimuth and configured PV capacity
- requested GTI variable and request contract identity
- complete normalized target-day hourly GTI points, or a cryptographic digest
  that binds the derived value to the exact retained response
- derived target-day PV kWh
- `provider_response_received_at`, `captured_at`, `known_at`, `decision_at`
- `source_generation_id`, immutable `frame_fingerprint` and revision

`active_site_id` is never part of source identity or eligibility.

## Request and transformation contract

The request must use the Single Runs endpoint with an explicit `run` and an
explicit model, site geometry, `timezone=Europe/Stockholm` (or the verified
site timezone), and the exact GTI variable selected by the producer contract.
The target-day interval is requested/selected from the returned hourly points;
the response must contain the complete local-day interval after timezone
normalization.

The v1 PV transformation is:

1. normalize provider GTI to `W/m²` without clamping or interpolation;
2. convert each valid hourly mean to `kWh/m²` using its actual interval;
3. sum the target local-day intervals in UTC;
4. multiply by the site-configured PV capacity in `kWp`;
5. store the derived result in `kWh` with transformation version identity.

Capacity, tilt and azimuth are site configuration, not global constants. A
23-hour or 25-hour local day is accepted only when every required local-day
interval is present exactly once after UTC/DST normalization. Missing, null,
non-finite, duplicate, non-monotonic or partial points fail closed.

## Generation, frame identity and revisions

`source_generation_id` is derived from source-defining semantics only:

- provider adapter and contract version
- dataset and model identity
- site binding/location/timezone identity
- latitude/longitude, tilt, azimuth and capacity semantics
- requested variable and transformation/normalization versions

It excludes run time, target day, values, capture/known times, frame
fingerprint, revision and active site.

Run vintages use the same generation and remain separate frames. Same run and
same semantic knowledge deduplicates. Same run with a materially changed
response creates the next immutable revision. A different run creates a
different frame and does not supersede across generations. Earlier causal
frames are never overwritten.

For replay, select the newest candidate with `known_at <= decision_at`, ordered
by `(known_at, run_initialization_at, frame_fingerprint)` ascending and taking
the final item. Ties with different fingerprints at the same ordering boundary
are `AMBIGUOUS` and fail closed.

## Machine-readable eligibility

- `VERIFIED_PRE_DECISION`: complete provenance, exact dataset/role/site/generation,
  valid target coverage, and `known_at <= decision_at`.
- `VERIFIED_POST_DECISION`: otherwise valid frame with `known_at > decision_at`.
- `AMBIGUOUS`: conflicting candidates cannot be deterministically selected.
- `MISSING`: no candidate for the requested site/dataset/target.
- `INSUFFICIENT_PROVENANCE`: required identity or timing fields are absent.

Run time, numeric equality, provider name or an expected provider schedule can
never establish `VERIFIED_PRE_DECISION` by themselves.

## Collection and lifecycle requirements

The later producer must enumerate explicit `collection_enabled` site targets,
not the active site. It must be lifecycle-owned, have one cancellable daily
capture mechanism, survive restart without overwriting history, and be
idempotent. It must capture any legitimately available pre-decision run; it
must not rely on an arbitrary scheduler time or pretend that a post-cutoff
startup catch-up was pre-decision knowledge.

## Relation to existing data

`evidence-v1` and `open_meteo.evidence_previous_day1.v1` remain unchanged and
retrospective. `open_meteo.manager_forecast.v1` remains the manager/cache
dataset. Neither may satisfy this Single Run role. Existing 20-day Evidence
rows receive no backfill, no fabricated `known_at`, and no new identity.

The causal model population requires both Forecast.Solar and this dataset to
return `VERIFIED_PRE_DECISION` for the same site and decision contract.

No C.1 schema migration is required by this design; the existing immutable
frame fields are sufficient. A future implementation must still use the
existing canonical writer and replay reader rather than an ad-hoc store.
