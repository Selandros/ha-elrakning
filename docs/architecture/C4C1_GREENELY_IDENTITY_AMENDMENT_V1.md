# C.4C.1 Greenely identity amendment v1

Status: design/fixtures/tests draft only. This amendment does not authorize a
producer, version bump, schema migration, deploy, restart, provider request,
Store write, canonical database write, or backfill.

## Decision status and precedence

C.4B and C.4C remain locked. This document supersedes only the Greenely
installation-attribution and invoice-identity wording explicitly listed below.
The following remain unchanged: economic component boundaries, dataset
separation, temporal fields, `known_at <= decision_at`, replay behavior,
clean-room eligibility, source/provider agnosticism, and immutable storage
semantics.

This amendment is **IDENTITY AMENDMENT READY FOR REVIEW**. The repository and
Home Assistant audit selected an HA-native, private, atomic persistence model
for the pseudonymization key. This resolves the storage-model question without
authorizing production implementation. Production must not silently fall back
to plain SHA or derive a key from a password, JWT, OCR value, or volatile
process state.

## Superseded identity wording

Only these clauses are superseded after this amendment is formally approved:

1. C.4B/C.4C `stable invoice identity` / `invoice_key` becomes a
   `provider_invoice_occurrence_reference` plus an opaque
   `invoice_occurrence_identity`; it is not asserted to be a logical invoice
   identity.
2. C.4C `pdf_installation_id` becomes eligible only when a valid explicit
   `greenely_meter_to_invoice_installation_proof` exists. Equal strings alone
   remain insufficient.
3. C.4B/C.4C invoice target descriptors use occurrence identity plus billing
   period and component role. Different occurrences never share a target or
   supersedes link without explicit provider linkage.

No other C.4B/C.4C statement is changed by this draft.

The amendment fits the existing C.1 frame/generation model: it uses the
existing `source_generation_id`, `semantic_key`, `revision`,
`supersedes_frame_id`, site scope, timestamps, provenance and point records.
No C.1 schema migration or new storage column/table is required for this
identity amendment.

## Terminology

`provider_invoice_occurrence_reference` is the raw provider field
`ocr_number`. Runtime evidence found it on 52 Vikarbodarna invoices, stable
across two GETs and unique across those observed invoices. That does not prove
logical invoice/document identity or correction/reissue semantics.

`invoice_occurrence_identity` is the opaque, deterministic internal target
identity derived from provider namespace, contract identity and the provider
occurrence reference. It is a target identity, never a source-generation
identity.

`greenely_meter_to_invoice_installation_proof` is explicit site-scoped proof
that a provider facility/contract meter identity was verified against the
invoice installation identity. Runtime equality is not proof.

Proof states are `UNVERIFIED` and `EXPLICITLY_VERIFIED`. Only the latter may
make an installation section eligible for canonical attribution.

## Installation attribution proof

The conceptual proof record contains only bounded fingerprints and provenance,
not raw installation identifiers:

```text
proof_schema_version
relation = greenely_meter_id_to_invoice_installation_id
verification_state
verification_method
site_binding_fingerprint
provider = greenely
config_entry_identity
facility_identity_fingerprint
contract_identity_fingerprint
facility_meter_id_fingerprint
contract_meter_id_fingerprint_or_state
invoice_installation_identity_fingerprint
verified_at
parser_identity
normalization_identity
```

Acceptable methods are distinct:

- `provider_native_semantic_proof`: a provider response or provider document
  explicitly binds the API installation identity to the invoice installation
  identity;
- `explicit_out_of_band_invoice_verification`: an operator-approved,
  documented comparison of the bound facility/contract identity and the
  invoice installation section, retaining who/what was verified, when, the
  binding fingerprint and opaque identity fingerprints. A statement that two
  values merely “look equal” is not sufficient.

The proof belongs to the site-scoped Greenely binding/attribution state, not a
global manager cache or invoice row. The existing `site_identity.py` already
supports site-scoped dictionary bindings and deterministic binding fingerprints,
but it has no proof schema or validator. A future implementation therefore
requires a binding-contract amendment and explicit validation; this draft does
not change `site_identity.py`.

Proof is unusable after a site/facility rebind, contract-scope mismatch or
rebind, facility meter change, contract meter change within proof scope,
provider/config-entry change, attribution-relevant binding fingerprint change,
proof schema/version replacement, or parser/normalization identity change that
changes attribution semantics. `active_site_id` is never part of proof.
Runtime equality cannot upgrade `UNVERIFIED` to `EXPLICITLY_VERIFIED`.
Without valid proof, attribution is `INSUFFICIENT_EVIDENCE` and candidate count
is zero.

## Occurrence target and revision semantics

The normalized occurrence reference is validated as present, non-blank and
provider-native. No additional format rule is invented until provider evidence
supports one.

- same occurrence identity, billing-period/component target and normalized
  knowledge: deduplicate;
- same occurrence identity with changed normalized knowledge: revision N+1 in
  the same generation, superseding the previous revision;
- different occurrence identity: new target, revision 1, no supersedes link;
- two occurrences may share a billing period;
- no latest-wins rule exists across occurrences;
- no cross-occurrence supersedes/reissue relation is inferred;
- duplicate occurrence reference within one contract response is ambiguous and
  rejected;
- the same raw reference under different contracts produces distinct opaque
  identities because contract identity participates;
- missing, blank or invalid occurrence reference fails closed.

## Privacy key model

Plain SHA is not an acceptable privacy boundary for a low-entropy payment
reference. The intended construction is a deterministic HMAC over a canonical
provider namespace, contract identity and occurrence reference. The HMAC key
must be stable across restart, ordinary reload and preferably backup/restore;
must not derive from Greenely credentials, JWTs, OCR, or process memory; and
must never be logged or exposed in provenance/UI.

The selected V1 production model is one random 256-bit key per Elräkning
config-entry identity domain, persisted with Home Assistant's `Store` using
`private=True` and `atomic_writes=True`. The record is versioned and contains
the key material, a non-secret `key_id`/identity-domain ID, and `created_at`.
The key material is never returned through diagnostics, websocket/UI payloads,
provenance, source-generation data, or logs. The private Store is an HA
configuration artifact, not a provider credential and not a canonical data
record.

The key lifecycle is fail-closed:

- no key plus no dependent `greenely.invoice_economics.v1` history: generate
  once and durably save before any collection;
- key plus dependent history: continue in the same identity domain;
- key plus no history: valid empty domain;
- no key plus dependent history: do not generate a replacement; stop eligible
  capture and report the missing-key state;
- restored key plus matching database: continue;
- database without its key: do not attach it implicitly;
- key without a database: do not import or attach history implicitly.

V1 rotation is unsupported. There is no automatic/manual rotation, re-key
migration, or cross-key matching. A lost key requires restoration of the
matching backup or remains fail-closed. Future rotation needs a separate
contract and identity domain.

`key_id` is non-secret and participates in source-generation identity so a
different key domain cannot silently share generations. The key material is
not a source-generation input. HMAC-SHA-256 uses a versioned canonical JSON
message containing the provider namespace, config-entry identity domain,
contract identity, and provider occurrence reference. Its required fields are
versioned by `identity_version`; no mutable timestamps or billing dates are
inputs when the occurrence reference exists. The full digest is the opaque
occurrence identity; raw OCR is neither emitted nor used as a source-generation
field.

This is a design selection only. No production occurrence identity may be
generated by this amendment, and no Store is written by the fixtures/tests.

## Source generation and replay

Occurrence identity, raw OCR, billing period, values, capture/fetch/known times,
frame IDs and revisions are excluded from source-generation identity.

Source generation retains the locked source semantics: provider adapter,
config-entry, site binding, facility, contract, dataset, parser,
normalization, VAT, unit and verified-timezone identities. Installation-
attribution proof identity/state/version and the pseudonymization key
identity-domain ID must participate in the source-defining binding fingerprint
when changing them could alter eligibility.
The opaque proof fingerprint itself is provenance, not an occurrence target.
Raw occurrence identity never creates a generation; facility/contract rebinding
does. A proof-semantic replacement must create a new generation if it changes
which installation facts can be attributed. Generations never cross-supersede.

Replay retains `known_at <= decision_at`. A later occurrence cannot rewrite an
earlier decision. If two occurrences cover the same billing period, both remain
distinct facts when individually eligible; selection of one is a separate
future read/model contract.

## Clean room and scope impact

Fiskvik remains zero-frame under the current state because generic eligibility
requires collection enabled, a legitimate binding, invoice evidence, valid
installation proof, valid occurrence identity, verified timezone and component
evidence. FUTURE/no-invoice remains zero. ENDED/INACTIVE does not invalidate a
historically attributed occurrence. No site ID is hardcoded.

If approved later, the future file scope is:

1. identity/binding contract: `site_identity.py` and its focused tests, plus
   the provider attribution adapter if separated;
2. producer: the future Greenely adapter/producer, `external_input_frames.py`
   only where generic frame construction is required;
3. pure unittest fixtures/tests for proof, occurrence, generation, replay,
   privacy and clean-room behavior;
4. this amendment and its fixture/test closure.

The first implementation must leave generic history consumers, Solar Evidence,
current UI, unrelated provider managers, storage schema and existing Greenely
refresh behavior untouched.

## Required design fixtures

Fixtures must cover exact proof binding and invalidation, occurrence
deduplication/revision, two occurrences in one billing period, new OCR without
supersedes, duplicate/missing/blank/invalid OCR, cross-contract separation,
key lifecycle/recovery, key-domain separation, generation behavior, replay
filtering, Fiskvik clean room, and absence of raw OCR/Anl.id from canonical
outputs. The test-only HMAC key is synthetic; it models the selected production
contract but never creates a production key or Store record.

Final classification:

```text
IDENTITY AMENDMENT READY FOR REVIEW
C.4C.1 PRODUCTION IMPLEMENTATION: NOT AUTHORIZED
0.0.639 NATURAL 00:05 EVIDENCE GATE: SEPARATE / UNTOUCHED
```
