# Elräkning project instructions

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
retention/data risks, and roadmap dependencies. Do not use old conversation
memory as authority over repository memory.

### During and after work

Check continuously whether a new architecture dependency, data requirement,
sensor or physical semantic, invariant, safety rule, lifecycle rule,
backtest/provenance constraint, health/degradation/calibration fact, economic
rule, performance constraint, or model data-retention need should become
permanent knowledge. After the task, compare what was known before with what
was learned, whether CURRENT_STATE changed, whether an UNKNOWN became VERIFIED,
and whether a new risk or decision was found.

Use these statuses when relevant:

- `MEMORY OK`: memory covers the scope and no durable gap was found.
- `MEMORY UPDATE REQUIRED`: durable knowledge, an accepted decision, a
  verified implementation property, or a changed current state must be stored.
  Report what was found, why it matters, the recommended file, and proposed
  wording. Do not promote speculation to a decision.
- `MEMORY INCOMPLETE FOR SAFE IMPLEMENTATION CONTINUITY`: a missing or
  contradictory contract could cause incompatible implementation, site/source
  mixing, backtest leakage, unsafe control, or premature physical storage
  decisions. Flag it near the beginning, describe the missing information and
  required decision/verification, and do not implement across the gap.
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

`ELRAKNING_MASTERPLAN.md` contains future goals and locked direction,
`ARCHITECTURE_DECISIONS.md` contains durable decisions and invariants, and
`CURRENT_STATE.md` contains current implementation and evidence. Keep these
levels separate. Update CURRENT_STATE when implementation or a milestone
changes; update ARCHITECTURE_DECISIONS for an accepted durable decision; update
the masterplan when roadmap or vision changes. A memory regression or
irreversible data risk must be prominent, not hidden in a report conclusion.
