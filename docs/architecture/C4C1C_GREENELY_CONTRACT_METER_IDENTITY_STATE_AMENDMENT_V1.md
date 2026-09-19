# C.4C.1C Greenely contract-meter identity state amendment v1

Status: minimal fail-closed contract amendment.

The facility-meter identity scope and contract-meter identity scope are
separate. The facility state `provider_meter_identity_unavailable_v1` is not
valid for the contract scope.

## Allowed contract representation

`contract_meter_id_fingerprint_or_state` must be exactly one of:

- a canonical `sha256-v1` fingerprint: 64 lowercase hexadecimal characters;
- `provider_contract_meter_identity_unavailable_v1`.

Blank values, arbitrary strings, free-form explanations and raw provider or
installation identifiers are rejected. The unavailable state means only that
the provider contract response did not expose a contract-meter identity in
the bounded evidence scope. It does not assert any meter-to-invoice relation.

The normalized value is used in proof semantic identity and therefore in
source-generation identity. Changing the fingerprint or bounded state makes
the semantic proof identity different.

Invoice occurrence, correction and reissue identity remain separate and are
not resolved by this amendment.

No provider-native lookup, Store schema, canonical frame, Evidence-v1,
Single Run or proof provisioning flow is activated by this amendment.
