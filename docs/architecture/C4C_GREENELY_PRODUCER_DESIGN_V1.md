# C.4C Greenely immutable provider-economics producer design

Status: design and fixture gate only. This document does not authorize a
production producer, version bump, schema migration, deploy, restart, Store
write, canonical database write, provider backfill, or network call.

## Purpose and scope

C.4C defines the producer boundary for the locked C.4B datasets:

- `greenely.invoice_economics.v1`
- `greenely.current_tariff_snapshot.v1`

The datasets remain separate facts, semantic keys, revision chains, and
supersedes chains. The producer must be provider-agnostic outside the isolated
Greenely adapter boundary and must use explicit site bindings rather than
`active_site_id`, a shared credential namespace, or a mutable active manager
state as ownership.

This scope freezes design and fixtures only. It intentionally does not add a
producer or modify the existing provider refresh path.

## Identity proof model

The normalized provider context keeps these identities separate:

| Field | Meaning |
|---|---|
| `site_id` | Elräkning collection owner |
| `configured_facility_id` | Facility identity from the site binding |
| `api_facility_id` | Facility identity returned by the provider API |
| `facility_meter_id` | Meter/install identity exposed by the facility response |
| `contract_id` | Provider contract identity |
| `contract_facility_id` | Contract facility reference when the provider returns it |
| `invoice_key` | Stable invoice identity within its contract context |
| `invoice_contract_id` | Contract identity attached to the invoice response |
| `pdf_installation_id` | Provider invoice `Anl.id` or equivalent installation section identity |
| `verified_site_timezone` | Timezone used for invoice local-calendar conversion |

The producer must not silently equate `facility_id`, `meter_id`, contract
facility references, and invoice `Anl.id`. An equivalence is usable only when
the provider response or an explicit binding proves it. Every candidate has an
attribution status:

- `ATTRIBUTED`
- `AMBIGUOUS`
- `MISMATCH`
- `INSUFFICIENT_EVIDENCE`

Only `ATTRIBUTED` candidates may reach canonical storage. `ATTRIBUTED` requires
an unambiguous site-binding, facility, contract, invoice and installation
section chain; equal identifier strings alone are not proof of equivalence.

## Component-level invoice attribution

The provider response is normalized in this order:

```text
site binding
  -> provider facility
  -> provider contract
  -> invoice identity
  -> invoice installation section
  -> economic component
```

One invoice can contain one or several installation sections. The producer
must create a component candidate only when the selected installation identity
is unambiguous:

- one exact selected installation match: accept that section;
- zero matches: reject;
- more than one plausible match: reject as ambiguous;
- missing identity proof: reject;
- facility or contract mismatch: reject.

There is no fallback to the first section, address similarity, latest global
invoice, active site, or active provider namespace. An invoice is not a site
identity.

The current code's `facility.get("meter_id")` must not be assumed to equal an
invoice `Anl.id`; that relation is an explicit design input to be proven by a
future adapter fixture or runtime evidence.

## Dataset and request identity matrix

| Dataset | Source fact | Target | Canonical roles | Evidence relation | Revision chain |
|---|---|---|---|---|---|
| `greenely.invoice_economics.v1` | Attributed provider-issued invoice component | Invoice identity + billing period + component role | `economic.provider.import.variable`, `economic.provider.fixed.subscription` | Not an Evidence-v1 source | Own chain |
| `greenely.current_tariff_snapshot.v1` | Attributed current eligibility snapshot | `current_tariff_snapshot` + component role | Same two provider component roles | Not an Evidence-v1 source | Own chain |

The two datasets never share semantic keys, revisions, or supersedes links.
Invoice identity, billing period, PDF section and values are target/provenance
data, not source-generation identity.

## Economic component boundary

The only canonical provider-economic roles in this design are:

- `economic.provider.import.variable`, unit `SEK/kWh`, with explicit VAT basis;
- `economic.provider.fixed.subscription`, unit `SEK/month`, with explicit VAT
  basis.

Nord Pool spot, invoice weighted spot average, credits, settlement discounts,
`amount_due`, gross invoice totals, grid economics and derived customer price
are excluded source facts. They require a separate contract or remain derived
at read/model time. Missing provider components remain unavailable and are not
zero-filled or reconstructed from totals.

## Temporal and replay contract

For invoice economics:

- preserve provider billing calendar dates exactly as source provenance;
- resolve local start at 00:00 inclusive and the day after period end at 00:00
  exclusive only with a verified site timezone;
- store the resolved UTC interval and `valid_at = valid_from`;
- `captured_at` is when the producer observes the fully attributed normalized
  fact;
- `known_at` is the conservative knowledge boundary and is no earlier than
  `captured_at` under the C.4B contract;
- `fetched_at` is present only when the exact provider fetch completion time is
  directly observed;
- `published_at` is null unless the provider supplies a trustworthy
  publication timestamp.

Without a verified timezone, the invoice candidate fails closed and no
canonical invoice frame is created. No UTC boundary is guessed. A historical
invoice may still be eligible based on its own attribution and billing period
even when its contract is later ended or inactive; current-contract eligibility
is not a general invoice-frame filter.

For current tariff snapshots:

- `valid_from` and `valid_to` are null;
- `valid_at = captured_at`;
- `known_at = captured_at` under the current contract;
- the snapshot is not expanded backwards into historical tariff coverage;
- a future contract is preview/future metadata only until its effective
  eligibility is proven.

Replay may select only frames satisfying:

```text
known_at <= decision_at
```

A later correction to an older invoice remains invisible to an earlier
decision. Same normalized knowledge deduplicates; changed knowledge for the
same target creates the next revision in the same generation.

## Source generations and target identity

The generation fingerprint contains only source-defining semantics:

- provider adapter and config-entry identity;
- site-binding identity;
- facility and contract identity;
- dataset identity;
- parser/normalization contract versions;
- VAT and unit semantics;
- verified timezone identity/state for invoice economics.

It excludes `economic_values`, invoice identity, invoice number, billing dates,
`captured_at`, `fetched_at`, `known_at`, `revision`, and `frame_id`.

The semantic key is:

```text
dataset | site_id | source_generation_id | logical_role | target_descriptor
```

Invoice target descriptors contain stable attributed invoice identity,
billing-period identity, and component role. Snapshot target descriptors use a
stable current-snapshot descriptor and component role.

A facility, contract, binding, parser, normalization, VAT, unit, or verified
timezone change that changes source semantics creates a new generation at
revision 1. The new generation never supersedes a previous generation.

## Collection ownership and site isolation

The future producer enumerates `collection_enabled` site configurations and
their explicit `elhandel` bindings. Each target carries its `site_id`, binding,
facility, contract and source-generation context through the complete fetch,
normalize and persist path.

`active_site_id` is UI/read context only. Shared credentials may authorize
transport but never determine ownership. A site with no valid binding, no
invoice evidence, a FUTURE-only contract, or ambiguous attribution produces no
historical/current economics frame.

An active site without a legitimate Greenely binding is not an economics target.
An inactive site with `collection_enabled=true` and a legitimate binding is a
valid collection target.

Fiskvik remains a clean room under the audited state: zero invoice-economics
frames, zero current-tariff-snapshot frames, and no inherited data from
Vikarbodarna. Explicit future contract metadata is allowed but is not a
current or historical economics frame.

## First implementation boundary after this gate

The smallest safe production slice is invoice-economics candidate building
and persistence after the identity fixtures pass. It must include:

1. pure provider-context normalization and fail-closed attribution;
2. explicit collection-enabled target enumeration;
3. C.1 frame/point construction with immutable revision semantics;
4. readback/replay filtering by `known_at`;
5. real Vikarbodarna acceptance and Fiskvik zero-frame acceptance.

`current_tariff_snapshot.v1` is a separate follow-up slice after invoice
attribution is runtime-proven. No historical backfill is included.

## Acceptance boundary for this design gate

Fixtures and tests must cover one-installation and multi-installation invoices,
identity mismatch and ambiguity, verified and unknown timezone, DST boundaries,
future contracts, deduplication, revisions, generation replacement, replay
filtering, rebinding, inactive-site collection, and the Fiskvik clean room.

The fixtures are sanitized pure data. They must not call Home Assistant,
Greenely, the network, Store, SQLite, the production collector, or any runtime
write path.
