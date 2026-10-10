# Elräkning App shadow contract v1

Status: Phase 2 read-only shadow transport. The existing Home Assistant
integration and its canonical storage remain the sole source of truth. The
App receives only validated site-scoped snapshots from existing immutable
frames; no production entities, plans, storage rows or control paths use the
App.

## Boundary

The App is a separate Home Assistant App/add-on process. It has no Home
Assistant token in Phase 1 and cannot call HA services. The Core client uses a
dedicated bearer token configured only for this local boundary. The App has no
broad CORS policy, no ingress requirement, and no host port mapping. Its
listener is reachable only on the add-on's internal network when the App is
explicitly installed and configured.

The App server has only three endpoints:

- `GET /v1/health/live`: process liveness;
- `GET /v1/health/ready`: transport readiness and explicit shadow-only flags;
- `POST /v1/snapshots`: bounded, read-only StateSnapshot ingress.

The App stores only a bounded in-memory shadow buffer. It does not write
canonical data, call HA services, run HiGHS, or produce an AppResult yet.

## Contract invariants

`contract_version`, exact `site_id`, exact `source_generation_id`, source
identity, unit/sign, observed/captured/known timestamps, quality and status
are required. `known_at <= decision_at` is rejected when violated. Available
values must be finite numeric values; unavailable values remain null and are
never zero-filled.

An eventual AppResult must carry exact site/generation identity, provenance,
revision, SHA-256 fingerprint, validity interval, `known_at`, fail-closed
status and bounded diagnostics. Core must reject mismatches and stale results.

## Failure and security model

The Core client is disabled by default. Phase 2 transport is gated by
diagnostic stage 15 or later and is enabled only through the
integration's supported config-entry OptionsFlow, which stores the explicit
flag, local URL and bearer token in Home Assistant's config-entry options.
When enabled, setup performs one bounded health gate. Existing immutable
frames can trigger a coalesced, site-scoped snapshot submission; incomplete
frames are skipped fail-closed. Each request has a one-second timeout and
failures return an unavailable result without raising into HA setup or the
event loop. There is no polling task. The App token is separate from any HA
token and is not persisted in the repository.

The App uses no worker pool in Phase 1. Request headers/body and per-site
snapshot retention are bounded. The process has no physical-write endpoint.

## Shadow gate

Further Phase 2 work may add pure optimizer/forecast/replay execution only
after the same validated snapshots can be compared against the Core motor using exact
fingerprints, source selection, provenance and fail-closed outcomes. No
cutover, dual-writer storage or physical control is allowed before those
comparisons are green.
