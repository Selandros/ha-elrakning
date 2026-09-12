# C.3B Weather/SMHI immutable external-input contract

Status: locked design and deterministic fixtures; no weather producer is
implemented by this scope.

This contract is based on the C.3A read-only audit. SMHI current conditions and
hourly forecast responses are separate immutable datasets. They must never
share a semantic or revision chain, even though both are obtained through the
same Home Assistant weather entity and provider binding.

## Dataset matrix

| Source | Dataset identity | Scope | Logical role | Target semantics | Replay use | Revision chain |
|---|---|---|---|---|---|---|
| SMHI current conditions | `smhi.current_weather.v1` | `site` | `weather.current_conditions` | Snapshot of the provider/current-conditions state as known at capture; no fabricated `valid_at` | Decision-input snapshot only | Only with the same site, generation and normalized current payload |
| SMHI hourly forecast | `smhi.hourly_forecast.v1` | `site` | `weather.forecast.hourly` | One point per provider forecast `datetime`, normalized to UTC `valid_at` | Forecast vintage selected by `known_at <= decision_at`, then points by `valid_at` | Only with the same site, generation, request contract and semantic target |

The dataset identity is not inferred from the provider name alone. Current and
forecast responses have different temporal meaning and therefore remain
separate even when they use the same entity and config entry.

## Source and site contract

The first supported source is the explicit site weather binding discovered from
the SMHI config entry and entity registry. The current verified binding uses:

- provider/integration: `smhi`
- Home Assistant config entry identity: persisted in the site binding
- weather entity: `weather.smhi_home`
- role sensors: the binding's explicit `sensor_entities` mapping
- site ownership: the site's binding and `site_id`, never `active_site_id` alone

No binding means no collection target, no service call and no weather frame.
`collection_enabled` controls whether a site can be a background target. A
site may be active in the UI without becoming the only collection target.
Fiskvik remains a zero-target/zero-frame fixture until it has its own legitimate
weather binding.

Transport/cache deduplication may be shared only as an optimization. It must
not remove site provenance, binding identity or source-generation identity from
the frame.

## Current-conditions frame

The current frame is a provider/current-conditions snapshot, not a canonical
physical weather observation. It contains the normalized fields actually
available from the HA weather state and explicit SMHI role sensors. Missing
fields remain missing; no zero-fill, interpolation or provider timestamp is
fabricated.

Required temporal semantics:

- `captured_at`: time Elräkning captures/normalizes the current snapshot
- `known_at`: equal to the conservative capture time
- `fetched_at`: null unless a real provider fetch time is exposed
- `published_at`: null unless a real provider publication time is exposed
- `valid_at`: null; current-state `last_updated` is provenance metadata only
- `ha_state_last_updated`: optional provenance metadata, never `known_at` or a
  claimed provider observation time

An unchanged normalized current payload deduplicates. A changed payload creates
the next revision in the same generation and semantic target.

## Hourly forecast frame

The hourly frame represents one provider/service-response vintage. Every valid
forecast item becomes one point; the provider `datetime` is the point's target
time.

Required temporal semantics:

- `valid_at`: the offset-aware forecast item's `datetime`, normalized to UTC
- `captured_at`: local capture/normalization time
- `fetched_at`: time immediately after the successful `weather.get_forecasts`
  response is received
- `known_at`: conservative `captured_at`; it must never be earlier than the
  successful response being available to Elräkning
- `published_at`: null unless the provider exposes a real publication time
- source timestamp/offset: preserved in point provenance where available

Naive or malformed forecast datetimes are rejected as quality gaps. They are
not assigned an assumed Stockholm offset. Missing or malformed values are not
replaced with defaults and do not produce synthetic points.

## Source generation and semantic identity

The source-generation fingerprint includes only source-defining semantics:

- provider/integration identity
- HA config-entry identity
- bound weather entity identity
- site binding identity
- request contract (`weather.get_forecasts`, `hourly`)
- adapter/normalization contract version
- relevant explicit role mapping for the current dataset

Site ID is ownership scope and part of the semantic identity, not a reason to
share frames between sites. Values, weather conditions, forecast values,
`last_updated`, fetch/capture times and other volatile observations do not
create a new source generation. Binding/entity/config replacement or a
semantic request/normalization change does.

The semantic key contains dataset identity, site scope, source generation,
logical role and target descriptor. For an hourly frame the target descriptor
is the stable `forecast_request_vintage` descriptor for the source/request
stream; individual forecast datetimes belong in point keys and `valid_at`, not
in the frame semantic key. For the current frame it is the fixed
`current_snapshot` descriptor. It does not contain values, capture times,
knowledge times or revision. A new generation starts at revision 1 and does
not supersede a previous generation. The two dataset identities therefore
cannot share a semantic key or a revision chain.

## Revision, replay and look-ahead

For a forecast target, a later knowledge state is a new revision only when the
normalized semantic payload for that target changes. An identical response
deduplicates even if captured again later. A current frame uses the same rule
for its normalized current payload.

Replay may select only frames satisfying:

```text
known_at <= decision_at
```

For hourly forecast frames, the selected frame's points are then filtered by
the replay interval using `valid_at`. A forecast known at 11:00 for 15:00 must
not be visible to a decision at 10:30, even if its `valid_at` is in the future.

## Quality and failure rules

- no weather binding: no target, no call, no frame
- current and hourly statuses/quality are independent
- hourly service failure must not be reported as hourly success merely because
  current state was available
- malformed/missing forecast datetime: no point
- missing optional weather field: preserve other fields, do not fabricate
- no interpolation, clamping, zero-fill or synthetic hourly points
- `published_at = null` when provider publication time is unavailable

The storage invariant also requires `known_at >= captured_at` and, when
`fetched_at` exists, `known_at >= fetched_at`. The producer must capture the
response before assigning these timestamps so the frame cannot claim knowledge
before the response was locally available.

The current runtime adapter currently swallows hourly service exceptions. That
is a C.3C observability requirement; this C.3B contract does not add logging or
change production behavior.

## Solar Shadow and Evidence boundaries

Solar Shadow currently consumes mutable `SolarWeatherManager.public_state()`
and stores a bounded copy in its own Store. C.3B does not migrate that Store,
change its values, or redefine Solar Evidence. A future producer must be
additive and preserve the existing Solar Shadow/Evidence semantics until a
separate migration/non-regression gate is approved.

No legacy current-state or hourly response may be backfilled as native
immutable weather frames without explicit provenance and resolution semantics.

## C.3B acceptance contract

Fixtures must prove:

1. the two dataset identities never share a revision chain;
2. site and binding identity are part of scope and generation;
3. `known_at <= decision_at` selects the correct forecast vintage;
4. `valid_at` is separate from `known_at`;
5. naive/malformed datetimes fail closed;
6. unchanged payloads deduplicate and changed payloads revise;
7. no-binding sites produce zero targets/frames;
8. Fiskvik is a zero-weather-frame fixture;
9. DST-aware offset timestamps normalize to UTC without inventing a timezone;
10. Solar Shadow and Solar Evidence are non-regression boundaries;
11. fixtures are pure local tests and perform no HA, Store, SQLite or network
    writes.

No C.3 production implementation is authorized by this contract scope.
