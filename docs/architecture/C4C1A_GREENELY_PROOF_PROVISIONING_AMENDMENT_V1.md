# C.4C.1A Greenely proof-provisioning audit amendment v1

Status: design/fixtures/pure-tests only. This amendment does not authorize
production code, a version bump, schema migration, deploy, restart, provider
requests, Store writes, SQLite writes, or backfill.

## Precedence and scope

C.4B, C.4C, and C.4C.1 remain locked. C.4C.1A adds and supersedes only the
proof-provisioning and audit-evidence semantics described here. Occurrence
identity, HMAC, replay, economics, timezone semantics, and the C.1 schema are
unchanged.

The existing local C.4C.1 production implementation remains uncommitted and
blocked until its separate correction/re-review passes.

## Provider relation and installation proof

Before a proof can become `EXPLICITLY_VERIFIED`, provisioning must establish
the provider-native relation:

```text
bound Greenely facility -> exact Greenely contract
```

The relation is established from the provider contract's `facility_id` and
the current bound facility. Operator input, equal strings, PDF address
similarity, or the PDF installation identifier alone cannot establish it.
The provider lookup is transient provider-adapter context; it is not persisted
as raw identity in the proof.

The separate meter-to-invoice-installation relation is valid only with an
explicit proof. A missing, stale, ambiguous, or unverified proof yields
`INSUFFICIENT_EVIDENCE` and zero canonical candidates.

The proof is site-scoped attribution state. It is not global manager state and
never depends on `active_site_id`.

## Persisted proof record

The persisted record uses bounded identities and the following exact fields:

```text
proof_schema_version
relation
verification_state
verification_method
site_binding_fingerprint
provider
config_entry_identity
facility_identity_fingerprint
contract_identity_fingerprint
facility_meter_id_fingerprint
contract_meter_id_fingerprint_or_state
invoice_installation_identity_fingerprint
verified_at
parser_identity
normalization_identity
fingerprint_version
verification_actor
evidence_reference
evidence_digest
proof_semantic_identity
proof_audit_identity
proof_fingerprint
```

Raw facility IDs, contract IDs, meter IDs, Anl.id values, credentials, JWTs,
signed URLs, and HMAC key material are not persisted in this record.

`verification_actor` is derived from the authenticated Home Assistant service
context, never accepted as a caller-supplied identity. It represents the
administrator who accepted the verification and is never copied into
canonical economics frames.

For `explicit_out_of_band_invoice_verification`, `evidence_reference` is an
opaque audit reference and `evidence_digest` is a deterministic digest of a
versioned verification-evidence package. The digest must not be merely a
digest of one raw identifier. Missing or malformed actor, reference, or digest
prevents `EXPLICITLY_VERIFIED`.

## Semantic versus audit identity

`proof_semantic_identity` contains the attribution-defining facts:

```text
relation
provider/config-entry identity domain
site binding identity
facility identity
contract identity/scope
facility meter identity fingerprint/state
contract meter identity fingerprint/state
invoice installation identity fingerprint
verification method
proof schema/version
fingerprint algorithm/version
parser attribution identity
normalization attribution identity
```

It participates in source-generation identity because changing it can change
which invoice installation facts are eligible for attribution.

`proof_audit_identity` contains the audit trail:

```text
verification_actor
verified_at
evidence_reference
evidence_digest
```

These fields are retained for auditability but do not change source generation
when the semantic relation is unchanged. A changed evidence package that
changes the verified semantic relation must produce a new semantic proof
identity and therefore a new source generation. Audit-only replacement does
not rewrite historical frames.

## Provisioning state machine

The future operation is:

1. authenticate the Home Assistant service call;
2. require an explicit `site_id` and an administrator;
3. read the current site binding;
4. compare the supplied expected binding fingerprint;
5. require provider `greenely`;
6. resolve the bound provider facility;
7. resolve the exact provider contract;
8. verify that the contract exists, is unambiguous, and belongs to the bound facility;
9. validate out-of-band evidence metadata and the allowed verification method;
10. construct bounded semantic proof identity;
11. construct audit evidence identity;
12. validate the complete proof;
13. persist site-scoped proof;
14. re-read the current binding and confirm it is unchanged;
15. only then treat the proof as `EXPLICITLY_VERIFIED`.

Provider lookup failure, missing/ambiguous contract, facility mismatch, stale
binding, or a binding change during lookup causes rejection and no verified
proof persistence. `active_site_id` is not used.

## Invalidation and source generation

The proof becomes unusable after a provider, config-entry, site binding,
facility, contract scope, meter identity/state, installation identity, proof
schema, fingerprint version, parser-attribution, or normalization-attribution
semantic change. Audit-only actor/time/reference changes do not silently alter
attribution semantics.

Source generation includes the proof semantic identity/state/version and the
key identity domain when they affect source semantics. It excludes the actor,
audit reference, evidence digest, `verified_at`, occurrence/OCR, billing
period, values, `captured_at`, `fetched_at`, `known_at`, frame ID, and revision.
Raw occurrence identity remains a target identity and never creates a source
generation.

No C.1 schema migration is required. Canonical Greenely economics frame shape
is unchanged.

## Privacy and clean room

Proof and audit state must not contain raw OCR, raw Anl.id, raw meter IDs
unless separately justified as unavoidable, credentials, JWTs, signed PDF
URLs, or HMAC material. Canonical frame provenance must not expose actor,
evidence reference, or evidence digest under this amendment.

Fiskvik remains a clean room: missing invoice evidence, proof, occurrence,
timezone, or component evidence produces zero historical/current Greenely
economics frames. Future contract metadata remains future metadata only.

## Required pure fixtures and tests

The fixture contract covers provider relation success/failure, wrong and
ambiguous contracts, lookup failure, authenticated actor requirements, allowed
and unknown methods, complete/missing/malformed audit evidence, deterministic
semantic and audit identities, source-generation effects, active-site
independence, stale bindings, bounded output, and C.1 compatibility.

The tests are pure data tests only. They do not call Home Assistant, Greenely,
the network, Store, SQLite, or the production collector.

Final classification:

```text
C.4C.1A PROOF PROVISIONING AMENDMENT: READY FOR REVIEW
C.4C.1 production implementation: BLOCKED / NOT AUTHORIZED FOR COMMIT
0.0.639 natural 00:05 Evidence gate: SEPARATE / UNTOUCHED
```
