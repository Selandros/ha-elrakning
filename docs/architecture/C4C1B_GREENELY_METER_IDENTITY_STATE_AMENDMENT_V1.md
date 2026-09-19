# C.4C.1B Greenely meter-identity state amendment v1

Status: implementation amendment for explicit out-of-band proof only.

This amendment does not create provider-native meter evidence. It adds one
bounded fail-closed representation for the case where the provider response
does not expose a meter identity and the operator's versioned evidence package
explicitly records that absence.

## Allowed facility meter representation

Exactly one of these fields must be supplied:

- `facility_meter_id_fingerprint`: a bounded fingerprint of a verified meter
  identity; or
- `facility_meter_identity_state`:
  `provider_meter_identity_unavailable_v1`

No free-form state, raw meter identifier, raw installation identifier or
caller-supplied fallback is accepted. The contract meter field remains
`contract_meter_id_fingerprint_or_state` and must still be non-empty.

The unavailable state means only that the provider-side meter identity was not
available in the evidence scope. It does not assert that the facility meter
and invoice installation are equal. The invoice installation fingerprint must
still be supplied from explicit out-of-band invoice evidence.

## Compatibility and safety

- provider-native lookup and facility-to-contract verification are unchanged;
- proof remains site-scoped and requires authenticated admin service context;
- proof remains fail-closed if both facility representations are present,
  both are absent, or the state is unknown;
- raw IDs and credentials are never persisted;
- C.1 schema, canonical frame format, Evidence-v1, Single Run and existing
  provider economics semantics are unchanged;
- no proof is provisioned by this amendment itself.
