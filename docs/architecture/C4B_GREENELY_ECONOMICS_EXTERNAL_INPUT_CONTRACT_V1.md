# C.4B Greenely immutable economics external-input contract

Status: design/fixture contract for review. This scope is documentation and
pure contract tests only. It does not authorize a Greenely canonical producer,
version bump, Store/database migration, deploy, network call or Home Assistant
restart.

This contract is based on the C.4A read-only audit. Greenely invoice economics
and the decision-time current tariff snapshot are different facts with
different temporal meaning. They therefore use separate dataset identities and
must never share a semantic key, revision chain or supersedes chain.

## Dataset matrix

| Source fact | Dataset identity | Scope | Logical roles | Target semantics | Classification | Replay use |
|---|---|---|---|---|---|---|
| Provider-issued, facility-attributed invoice parsed by the bounded Greenely invoice adapter | `greenely.invoice_economics.v1` | `site` | `economic.provider.import.variable`, `economic.provider.fixed.subscription` | One attributed invoice/billing-period component. Billing-period validity is used only when its UTC boundaries can be resolved from explicit source calendar dates and a verified site timezone. | `published` | Historical provider economics that were actually known by `decision_at` |
| Current eligibility snapshot derived from the latest attributed invoice economics plus the explicitly bound Greenely contract state | `greenely.current_tariff_snapshot.v1` | `site` | `economic.provider.import.variable`, `economic.provider.fixed.subscription` | Snapshot valid only at the capture instant; it does not claim that the latest invoice tariff applied before or after that snapshot. | `derived` | Current decision input selected by `known_at <= decision_at`; never historical tariff backfill |

The same numeric rate may legitimately appear in both datasets. That does not
make the records the same fact. Invoice economics describes a provider-issued
billing-period fact. The current snapshot describes what Elräkning can
conservatively use as a current provider-tariff input at one decision-time
snapshot.

## Site, facility, contract and invoice attribution

Every Greenely economics frame is site-scoped and requires an explicit
`elhandel` site binding. Producer ownership is resolved from the collection
site configuration and the binding, never from `active_site_id`.

A supported target must prove all applicable identity levels:

- `site_id` and `collection_enabled=true`
- provider adapter `greenely`
- Home Assistant/config-entry identity for the Greenely provider integration
- bound Greenely `facility_id`
- Greenely contract identity for the source agreement
- for invoice economics: stable invoice identity/key attributed to that same
  contract and facility
- for a current snapshot: the exact attributed invoice summary used as tariff
  evidence plus the contract whose current eligibility was evaluated

A facility mismatch, contract mismatch, invoice mismatch, missing binding or
ambiguous attribution fails closed. It must not fall back to the active site,
active provider namespace, address similarity, latest global invoice, or any
other heuristic.

Facility identity is site ownership context. Contract identity is source-
generation context. Invoice identity is an invoice-economics target, not a new
source generation by itself.

## Economic component boundary

The canonical provider-economics components in C.4B are deliberately narrow:

- `economic.provider.import.variable`: Greenely's variable retailer component,
  with explicit `SEK/kWh` unit and VAT basis
- `economic.provider.fixed.subscription`: Greenely's fixed subscription fee,
  with explicit `SEK/month` unit and VAT basis

The following are not provider-economics source truth in these datasets:

- Nord Pool spot price or an invoice's weighted spot average
- invoice credits, credit balance or discounts applied at settlement level
- `amount_due`, gross invoice total or payment state
- a summed `customer_price`
- grid/network economics

Nord Pool remains the shared market-price source. Credits and `amount_due` are
settlement/accounting facts and require a separate future contract if they are
made canonical. `customer_price` remains a derived read/model-time result from
independent components and is never persisted here as a second source of
truth.

No missing economic component is zero-filled or reconstructed from invoice
totals, customer price, credits, spot average, or another component.

## Invoice economics temporal contract

An invoice-economics record preserves the source billing-period dates exactly
as provenance. A source calendar date is not automatically a UTC timestamp.

For an invoice whose `period_start` and `period_end` are explicit local
calendar dates:

- if the site's timezone is `verified`, the billing interval may be resolved
  deterministically as local `period_start 00:00` inclusive through local
  `(period_end + 1 day) 00:00` exclusive, with both boundaries converted to
  UTC using that verified timezone;
- the resolved `valid_from` is the billing-period start and `valid_to` is the
  exclusive billing-period end;
- a point's required `valid_at` is the resolved `valid_from` and is only a
  storage anchor for that interval component; the frame interval remains the
  authoritative validity semantics;
- if the timezone is not verified, malformed, or the source period is missing,
  the producer must not invent UTC boundaries. In C.4B such a component is not
  eligible for an invoice-economics canonical point/frame.

The billing interval proves only that the invoiced rate/component was applied
for that billed period. It does not prove an open-ended tariff before or after
that interval.

`effective_from` has a separate meaning. Greenely contract `start_date`, when
it is an explicit Unix-epoch source value, may be normalized to aware UTC and
preserved as `contract_effective_from` provenance for contract eligibility.
It must not be copied into invoice `valid_from` or used to backdate the latest
invoice rate.

Required knowledge timestamps:

- `captured_at`: when Elräkning builds the immutable economics knowledge
- `known_at`: conservative local knowledge time; for the current C.4A path it
  is `captured_at` unless a stronger earlier availability time is explicitly
  and safely modeled
- `fetched_at`: null unless the exact relevant Greenely response/PDF fetch time
  is directly observed by the future producer; manager `last_update`, invoice
  date and parser completion time are provenance, not fabricated fetch time
- `published_at`: null unless Greenely supplies a real publication timestamp

Storage invariants remain `known_at >= captured_at`, and when `fetched_at` is
present, `known_at >= fetched_at`.

## Current tariff snapshot temporal contract

`greenely.current_tariff_snapshot.v1` exists because the current runtime price
path can conservatively use a facility/contract/invoice-attributed tariff from
the latest parsed invoice while that exact bound contract is currently
eligible.

It is intentionally a snapshot, not a tariff history reconstruction:

- `valid_from = null`
- `valid_to = null`
- point `valid_at = captured_at`
- `known_at = captured_at` under the current audited path
- `fetched_at = null` unless the future producer directly observes the relevant
  source fetch completion
- `published_at = null` unless a real provider publication time is available
- `contract_effective_from` may be provenance/eligibility input but never the
  snapshot's `valid_from`

The snapshot is eligible only when the summary is attributed to the bound
facility, contract and invoice and that contract is effective at the snapshot
time. Provider status strings alone are not sufficient. An explicit future
`start_date` makes the contract FUTURE for Elräkning eligibility even if the
provider status label is ambiguous or misleading.

A current snapshot captured today must never be replayed as proof that the same
tariff was current yesterday. Historical replay can see it only from its own
`known_at` onward and only as the snapshot fact that was actually captured.

## Fiskvik clean-room contract

Fiskvik remains a strict clean room for Greenely historical economics in C.4B.
The audited runtime has a distinct bound Greenely facility with zero invoices,
zero consumption samples and no invoice summary. Its explicit contract start is
future relative to the C.4A audit.

Therefore the deterministic fixture requires:

- historical Greenely invoice-economics frames: `0`
- current Greenely tariff-snapshot frames: `0`
- historical Greenely consumption used as economics provenance: `0`
- no inheritance from Vikarbodarna, shared credentials or the active provider
  namespace
- only explicit FUTURE contract metadata may be retained as future metadata;
  it is not current economics and does not create historical/current tariff
  frames

A future contract becoming effective later does not authorize retrospective
backfill. New economics may begin prospectively when legitimate source facts
become available and their own `known_at` is recorded.

## No historical tariff reconstruction from current state

The existing durable Greenely history contains many invoice metadata records,
but the audited Store does not retain the parsed variable/fixed tariff for each
historical invoice. The latest attributed summary is not evidence for older
invoice periods.

C.4B therefore explicitly forbids:

- copying today's/latest invoice tariff over older invoice metadata;
- inferring old variable/fixed rates from `amount_due`, credits, invoice total,
  Nord Pool prices or consumption;
- treating the current snapshot as a historical tariff interval;
- creating synthetic `known_at`, `fetched_at`, publication time or UTC period
  boundaries for historical invoices.

Historical backfill is allowed only in a separate future scope when the exact
source invoice economics can be re-obtained and attributed, and the capture vs
historical-availability semantics are explicitly modeled. C.4B itself performs
no backfill.

## Source generation and semantic identity

The Greenely source-generation fingerprint contains only source-defining
semantics:

- provider/adapter identity `greenely`
- config-entry identity
- site ownership/binding identity
- bound facility identity
- Greenely contract identity
- dataset identity
- adapter/parser/normalization contract version relevant to that dataset
- VAT/unit interpretation contract
- for `greenely.invoice_economics.v1` only: verified site timezone identity
  (timezone name plus verification state), because it defines the calendar-date
  to UTC billing-interval transformation

Invoice identity, values, billing dates, invoice amount, credits, spot values,
`captured_at`, `fetched_at`, `known_at` and revision are not source-generation
fields. The current-snapshot generation does not inherit the invoice-only site
timezone field because it performs no local-calendar validity conversion. A new invoice under the same facility/contract is a new target in the
same generation. Rebinding the site, replacing the facility or contract, or
changing parsing/normalization semantics creates a new generation.

The semantic key is deterministic:

```text
dataset identity | site_id | source generation | logical role | target descriptor
```

Invoice target descriptor = stable attributed invoice identity plus component
role/billing-period identity. Current snapshot target descriptor = stable
`current_tariff_snapshot` for that dataset/site/generation/role. Volatile
values and capture/knowledge times are never key material.

Within the same semantic key, identical normalized knowledge deduplicates and a
changed fact creates revision N+1. A new source generation starts at revision 1
and never supersedes the previous generation. `supersedes_frame_id` therefore
never crosses datasets, sites, generations, contracts or invoice targets.

## Replay contract

All economics replay obeys the hard C.1 gate:

```text
known_at <= decision_at
```

For invoice economics, interval applicability additionally requires the
resolved billing interval to contain the replay target time when interval use is
requested. For current snapshots, `valid_at` is the capture instant and the
record must not be expanded backward into a historical interval.

A correction learned after a historical decision stays invisible to that
decision even if it refers to an older billing period.

## Active-site and collection contract

`active_site_id` is UI/read context only. It is never Greenely producer
ownership. A future C.4C collector must enumerate explicit
`collection_enabled` site bindings and preserve site/facility attribution for
every target.

The current active-site-bound Greenely refresh implementation is not silently
reclassified as site-independent collection by C.4B. C.4B defines producer
ownership semantics only; implementing multi-site provider fetch/capture is a
separate production/runtime gate.

Shared credentials may be reused as transport authorization, but credentials,
active provider namespace and transport cache identity must never decide frame
ownership.

## C.1 schema sufficiency

The existing C.1 external-frame model is sufficient:

- frame: site scope, source generation, semantic key/revision/supersedes,
  classification, `published_at`, `fetched_at`, `known_at`, `captured_at`,
  `valid_from`, `valid_to`, quality and provenance;
- point: mandatory UTC `valid_at`, value, unit, quality and bounded component
  provenance.

No schema migration is required by C.4B. Invoice components whose required UTC
billing-period anchor cannot be truthfully resolved simply fail closed rather
than forcing a schema change or fabricated point timestamp.

## C.4B acceptance contract

Fixtures/tests must prove:

1. `greenely.invoice_economics.v1` and
   `greenely.current_tariff_snapshot.v1` are separate dataset/revision chains;
2. site, facility and contract define ownership/generation while invoice
   identity defines the invoice target;
3. invoice facility/contract/invoice attribution fails closed when ambiguous;
4. provider variable and fixed components are separate from Nord Pool spot,
   credits, `amount_due`, grid economics and derived customer price;
5. verified-site-timezone billing dates may resolve to DST-correct UTC interval
   boundaries, while unknown timezone cannot fabricate them;
6. `contract_effective_from`, invoice `valid_at`, `known_at` and `fetched_at`
   remain separate semantics;
7. current snapshots use capture-instant validity and cannot backfill history;
8. Fiskvik has zero historical/current Greenely economics frames and only
   explicit FUTURE metadata;
9. identical normalized knowledge deduplicates, changed knowledge revises, and
   a new generation starts revision 1 with no cross-generation supersedes;
10. replay excludes knowledge learned after `decision_at`;
11. `active_site_id` is excluded from producer ownership and generation;
12. C.1 schema fields are sufficient and no migration is required;
13. fixtures are pure local tests and perform no Home Assistant, Store, SQLite,
    network, production-code, version, deploy or restart action.

No C.4 production implementation is authorized by this contract scope.
