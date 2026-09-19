# Open-Meteo Single Run status precedence amendment v1

Status: contract-only amendment. This document does not change the producer,
reader implementation, canonical schema, persistence, or existing data.

## Scope

Status classification starts only after candidate scope filtering. A frame is
scope-matching only when it matches the requested:

- `site_id`
- dataset identity
- `source_generation_id`
- target local day and target interval
- source/model logical role

Frames outside the requested scope are ignored completely. In particular, an
incomplete frame from another site, dataset, target, or generation cannot
poison a valid result for the requested query.

## Required precedence

Apply these rules in order:

1. Zero scope-matching candidates returns `MISSING`.
2. Any scope-matching candidate with missing, invalid, or unverifiable
   mandatory causal provenance returns `INSUFFICIENT_PROVENANCE`. This has
   precedence over `VERIFIED_PRE_DECISION`, `VERIFIED_POST_DECISION`, and
   `AMBIGUOUS`.
3. Otherwise partition valid candidates into `known_at <= decision_at`
   (pre-decision) and `known_at > decision_at` (post-decision).
4. If any valid pre-decision candidate exists, apply the existing ordering
   unchanged: sort by `(known_at, run_initialization_at, frame_fingerprint)`
   ascending and select the final candidate. Different fingerprints at the
   same top ordering boundary return `AMBIGUOUS`.
5. If only valid post-decision candidates exist, return
   `VERIFIED_POST_DECISION`.

The amendment therefore fixes the mixed cases explicitly:

- valid post-decision plus same-scope insufficient provenance =>
  `INSUFFICIENT_PROVENANCE`;
- valid pre-decision plus same-scope insufficient provenance =>
  `INSUFFICIENT_PROVENANCE`.

`MISSING` remains distinct from `INSUFFICIENT_PROVENANCE`: the former means
that no frame matched the query scope, while the latter means that at least one
frame matched the scope but its causal provenance cannot be trusted.

## Tie rule

The base contract's tie rule is unchanged. `known_at`, then
`run_initialization_at`, then `frame_fingerprint` determine the ordering.
Different fingerprints at the same top ordering boundary are ambiguous and
fail closed. This amendment adds no tie-breaker.

## Model eligibility

Only `VERIFIED_PRE_DECISION` is source-side model eligible. The following are
not eligible:

- `VERIFIED_POST_DECISION`
- `AMBIGUOUS`
- `MISSING`
- `INSUFFICIENT_PROVENANCE`

Two-source training requires independent `VERIFIED_PRE_DECISION` results for
Forecast.Solar and Open-Meteo Single Run. The old
`open_meteo.evidence_previous_day1.v1` dataset cannot satisfy the Single Run
requirement.

## Compatibility and non-effects

This is a contract-only amendment:

- schema migration: none;
- persistence change: none;
- frame format change: none;
- producer change: none;
- old data rewrite: none;
- Evidence-v1 change: none.

The amendment must be implemented by a later, separately scoped reader change.
