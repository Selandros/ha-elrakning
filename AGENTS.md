# Elräkning project instructions

## Current roadmap checkpoint

Masterplan v2 step 8 — Economics & deterministic optimizer is complete on
runtime baseline `0.0.805`; step 9 — Replay, backtest, benchmarks & regret is
the active main scope with its causal replay foundation implemented but not
closed. Step 10 — Shadow & advisory planning is PARTIAL/IMPLEMENTED for
read-only advisory plans and immutable snapshots; deeper shadow evaluation is
gated by qualified Step 9 live evidence. `actual -> baseline_forecast -> ella_plan` remains
the layer contract, and physical control remains gated by step 14.

## Architecture memory

Before planning or modifying work involving data/history/storage, multi-site,
forecasting, AI/ML, battery, battery health, degradation, price history,
calibration, shadow mode, backtesting, optimization/MPC, peak shaving,
flexible loads, or real control, read:

1. `docs/architecture/ELRAKNING_MASTERPLAN.md`
2. `docs/architecture/ARCHITECTURE_DECISIONS.md`
3. `docs/architecture/CURRENT_STATE.md`

Treat `ARCHITECTURE_DECISIONS.md` as established project decisions unless the
user explicitly asks to reconsider one. Do not silently replace the global
model architecture with site-specific AI models.

When implementation changes the documented architecture or completes a
milestone, update `CURRENT_STATE.md` in the same scoped change. Add genuinely
new durable decisions to `ARCHITECTURE_DECISIONS.md`; do not rewrite history
merely to match current implementation.

## Project rules

- Keep changes strictly scoped to the request.
- Preserve existing test, release, deployment, and runtime-verification gates.
- Do not claim runtime or physical verification without direct evidence.
- Keep secrets and credentials out of repository documentation.

### Source/provider agnosticism — hard rule

- Never hardcode a runtime dependency on a specific sensor/entity ID, hardware
  vendor, Home Assistant integration/platform, electricity retailer, grid
  company, tariff provider, forecast provider, meter, inverter, battery, or
  other replaceable external source into shared Elräkning logic.
- Core logic and UI must address stable logical roles/capabilities and resolve
  the current source through explicit site/source bindings, mappings,
  registries, adapters, or equivalent runtime configuration.
- Vendor/provider-specific behavior is allowed only inside a clearly isolated
  adapter/provider boundary. It must not leak into generic collection,
  history, diagnostics, forecasting, optimization, model, or presentation
  contracts.
- Entity IDs, unique IDs, device IDs, config-entry IDs, provider names, and
  vendor-specific identifiers are observations/configuration, never durable
  architecture keys unless their scope explicitly requires that exact adapter.
- A source may be renamed, replaced, removed, split, combined, or migrated to
  another vendor/provider without breaking unrelated Elräkning functionality.
  Missing or changed sources must degrade explicitly and safely rather than
  silently switching semantics or crashing shared functionality.
- New work must actively check for hidden assumptions about today's sources.
  Tests for generic functionality must cover source replacement/rebinding and
  at least one materially different provider/integration shape where relevant.
- Current installations such as FusionSolar/Huawei, Growatt, HomeWizard, a
  particular electricity retailer, or a particular grid company are runtime
  examples, not permanent product assumptions.

## Release and verification gates

- An observable change requires a patch-version bump.
- Never deploy changed content under the same version.
- Keep one issue/scope per release; do not add opportunistic cleanup.
- Tests must pass before release, and commits must contain only intended files.
- Push and deploy are pre-approved only within the agreed scope; do not stop
  for additional approval inside that scope.
- Backend changes may require a Home Assistant Core restart for activation.
- Verify the actually served/runtime version after deployment.
- For frontend changes, verify the actually served bundle, not only the local
  file. Verify remote/deployed hashes where the workflow supports it.
- After release, require a clean working tree and `HEAD == origin/main`.
- UI changes require actual visual runtime verification before PASS is claimed;
  green static tests are not visual evidence.
- Do not use cache hacks, cookie clearing, or same-version redeploy as a
  release strategy.
- If visual acceptance fails, stay within the same scope, make the smallest
  correction, bump to a new patch, deploy, and verify again.
- Keep logging out of motor/engine files when the existing central logging
  architecture provides the appropriate path. Consider CPU efficiency.

## Memory Maintenance Protocol

For architecture, data, sites, forecasting, battery, storage, optimization,
automation, or future-function work, use the permanent memory throughout the
task, not only once at the beginning.

### Before work

Read `AGENTS.md`, `docs/architecture/ELRAKNING_MASTERPLAN.md`,
`docs/architecture/ARCHITECTURE_DECISIONS.md`, and
`docs/architecture/CURRENT_STATE.md`. Identify applicable locked decisions,
current implementation, blockers, verified assumptions, UNKNOWN items,
retention/data risks, roadmap dependencies, and any source/provider-specific
assumptions that could violate the source-agnostic architecture rule. Do not
use old conversation memory as authority over repository memory.

### During and after work

Check continuously whether a new architecture dependency, data requirement,
sensor or physical semantic, invariant, safety rule, lifecycle rule,
backtest/provenance constraint, health/degradation/calibration fact, economic
rule, performance constraint, source/provider assumption, or model
data-retention need should become permanent knowledge. After the task, compare
what was known before with what was learned, whether CURRENT_STATE changed,
whether an UNKNOWN became VERIFIED, whether a new risk or decision was found,
and whether any new code accidentally couples generic behavior to today's
entity IDs, vendors, integrations, retailers, grid companies, or providers.

Use these statuses when relevant:

- `MEMORY OK`: memory covers the scope and no durable gap was found.
- `MEMORY UPDATE REQUIRED`: durable knowledge, an accepted decision, a
  verified implementation property, or a changed current state must be stored.
  Report what was found, why it matters, the recommended file, and proposed
  wording. Do not promote speculation to a decision.
- `MEMORY INCOMPLETE FOR SAFE IMPLEMENTATION CONTINUITY`: a missing or
  contradictory contract could cause incompatible implementation, site/source
  mixing, backtest leakage, unsafe control, premature physical storage
  decisions, or hard coupling to a replaceable source/provider. Flag it near
  the beginning, describe the missing information and required
  decision/verification, and do not implement across the gap.
- `IRREVERSIBLE DATA RISK`: relevant data is not collected, short-retained,
  in-memory only, overwritten, missing provenance/`known_at`, or otherwise at
  risk of permanent loss. Report data, source, retention, value, whether it can
  be recreated, priority, collection recommendation, resolution, retention,
  and provenance/`known_at` requirements. If irrecoverable and plausibly
  model-relevant, default to P0 until disproven.

“Collect more rather than lose irreplaceable model history” does not mean
unbounded payload logging, credential storage, blind duplication, debug noise,
or permanent second-level data. Balance information value against storage,
performance, and complexity, while preserving uncertain model-relevant data
until safe downsampling is understood.

### Memory follows reality

`ELRAKNING_MASTERPLAN.md` contains the canonical Masterplan v2, active step,
future goals, and locked direction; `ARCHITECTURE_DECISIONS.md` contains
durable decisions and invariants; and `CURRENT_STATE.md` contains current
implementation and evidence. Keep these levels separate. Update CURRENT_STATE
when implementation or a milestone changes; update ARCHITECTURE_DECISIONS for
an accepted durable decision; update the masterplan when roadmap or vision
changes. A memory regression or irreversible data risk must be prominent, not
hidden in a report conclusion.

### External architecture material

When external studies or planning documents are supplied, compare them against
the four permanent files and promote only durable, accepted requirements.
Keep recommendations, runtime findings, and implementation unknowns separate;
never turn an unverified proposal into a verified current-state claim.

For data-foundation work, the memory review must explicitly cover canonical
record fields, source generations, quality/provenance, retention, `known_at`,
replay/backtest integrity, safe fallback, hardware limits, source/provider
agnosticism, source replacement/rebinding, and irreversible data risk. A
checklist is incomplete if it names a component but omits the evidence and
safety gates required to trust it.
