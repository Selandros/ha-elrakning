# P0 canonical long-term data contract v1

Status: design-only, normative, storage-neutral.

This contract defines the durable shape and invariants for future long-term
collection. It does not choose a database, serializer, retention mechanism,
collector schedule, or runtime implementation.

## Datasets

- `energy_observation`: prospective collector-owned site data at canonical
  900-second UTC intervals.
- `historical_energy_observation`: truthful Recorder/LTS/bootstrap evidence;
  its resolution remains the resolution actually represented by the source.
- `external_input_frame`: immutable price, tariff, weather, and forecast
  snapshots, including the availability information known to Elräkning.

All records use the versioned envelope in the machine-readable contract.
`site_id`, logical role, source generation, identity strength/fingerprint,
timestamps, quality, and provenance are explicit. Entity IDs and provider
names are address/provenance, never generic semantic keys.

## Canonical semantics

The minimum P0 roles are `house.consumption`, `solar.production`,
`grid.power/import`, `battery.power`, and `battery.soc`. Power is canonical
W with time-weighted means: grid positive is import and negative is export;
battery positive is discharge/supply and negative is charge. SOC is percent,
0..100, using `last_valid`.

Live canonical energy intervals are UTC-aligned 900-second intervals. Local
site time is presentation/context only. A site has explicit timezone state:
`verified`, `migrated_unverified`, or `unknown`. UTC collection may continue
with `unknown` when timestamps are UTC or offset-aware, but local calendar,
tariff, weekday, DST, and naive-local conversion are forbidden until the
timezone is verified. Existing sites may snapshot HA's global timezone once as
`migrated_unverified`; that is not proof of physical site timezone.

## Time, knowledge, and quality

`captured_at` is when Elräkning had all inputs for a record revision;
`fetched_at` is API/history arrival; `known_at` is the earliest decision-safe
availability time. `known_at` must not be backdated by provider publication
time, and a decision input must satisfy `known_at <= decision_at`.

`0` means verified zero; `null` means unknown. Unknown, unavailable, gap,
and stale are distinct quality states. Missing actual data remains missing.
No actual data is interpolated, forward-filled, zero-filled, fabricated, or
upsampled from a native aggregate. An explicit estimated dataset is required
if imputation is ever needed for a model.

## History, identity, and shared sources

Records are immutable. A correction of the same semantic identity creates a
new revision with `supersedes_record_id`; a source replacement creates a new
source generation and never uses supersedes to rewrite continuity. Historical
identity may be `uncertain` when continuity cannot be proven.

Global external generations have `source_scope=global` and
`owner_site_id=null`; multiple sites may reference the same exact market,
weather, or forecast stream. A provider is not itself a generation: different
site query context, area, currency, coordinates, or other source-defining
context creates a distinct generation. Site-specific economic layers remain
site-scoped and may reference global frames.

`active_site_id` is never collection identity. Future collection uses explicit
site IDs and `collection_enabled`.

## Backfill rule

Recorder event streams may produce a 900-second historical aggregate only when
real coverage and timing support it; it remains historical data. Native HA LTS
hourly means remain hourly (`source_resolution_seconds=3600`) and must never
be expanded into four equal 15-minute records. Historical `known_at` is import
time unless stronger evidence exists; source timestamps do not manufacture
historical availability.

## Acceptance

The fixture suite covers house load, two simultaneous PV sources, signs,
SOC, new sites, source replacement, Recorder/LTS bootstrap, shared global and
site-specific external frames, forecast vintages/corrections, timezone/DST,
quality distinctions, no-fabrication, revisions, and active-site isolation.
`tests/test_p0_data_contract_design.py` is a pure standard-library validator;
it imports no Home Assistant, product code, collector, or storage backend.

This design closes P0-DATA-1. It does not close the P0 data gate: the
long-lived canonical collector and physical storage decision are still next,
and irreversible-data risk remains active until collection starts.
