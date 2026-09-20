# ELLA masterplan

Status: authoritative target architecture and staged implementation plan.

Updated: 2026-09-20

This document describes what ELLA is being built toward. It must not be read
as evidence that a future stage is implemented. Verified implementation and
runtime facts remain in `docs/architecture/CURRENT_STATE.md`.

## 1. Product definition

ELLA is a capability-driven, site-scoped energy planner. It is not a price
block widget and not a solar or battery feature. For the current site, ELLA
uses exactly the verified data and capabilities that are present and valid,
and progressively degrades when layers are absent.

The same planner serves every site. A site gets a different plan because its
verified capability set, observations, constraints and learned parameters
differ, never because generic code recognizes a site name.

Examples:

- Vikarbodarna is the full reference and learning site when its verified
  electricity, grid, total-load, historical, solar, battery/SOC and later
  individual-load inputs are available.
- Fiskvik remains fully useful with electricity, grid, total consumption and
  individual loads even when it has no solar or battery. ELLA can plan load
  shifting and prioritisation there.
- Missing solar or ESS does not make a site “without ELLA”. It removes only
  the decisions and explanations that require those capabilities.

The long-term product is always-on as a planner. A user toggle is not the
product eligibility mechanism. The manual ELLA binding introduced during
0.0.657/0.0.658 is historical transition state only. Capability eligibility
must come from verified site-scoped data/bindings.

## 2. Non-negotiable invariants

1. Every observation, capability, model, plan, block and learning result is
   bound to exactly one `site_id` and, where applicable, one resource ID.
2. Vikarbodarna may be a reference site for method development and evaluation,
   but its numeric history, model parameters, corrections and battery
   behaviour never leak to Fiskvik or another site.
3. Generalise algorithms, schemas and contracts, not a site's numeric
   behaviour. Fiskvik learns from Fiskvik observations.
4. `No capability -> no execution expectation.`
5. `No observation -> no learning signal.`
6. `No actuator -> no actuation failure.` A recommendation without an
   actuator is `NOT_APPLICABLE` or `recommend_only`, never an execution error.
7. Missing, stale, ambiguous, partial or wrong-site data is absent or
   unavailable. It is never zero-filled, copied from another site, or silently
   relabelled.
8. `known_at`, `observed_at`, target interval, source generation, provenance,
   quality and model version remain distinct and reproducible.
9. Planner and actuation are separate contracts. Device data never grants
   write permission.
10. Hard safety constraints and explicit site/user permissions always override
    optimisation. No implicit actuator activation is allowed.
11. Background collection and planning enumerate eligible sites explicitly;
    `active_site_id` is never an implicit backend site selector.
12. Existing Greenely proof/economics, Solar Evidence, Single Run, canonical
    integrity and clean-room guardrails remain intact.

## 3. Historical boundary and accepted foundation

The following is historical context, not the new target architecture:

| Boundary | Historical result | What remains valid |
|---|---|---|
| 0.0.657 | Not accepted because Fiskvik retained stale ELLA rendering; explicit manual planner binding was introduced as a transition mechanism. | Fingerprinted binding hardening and fail-closed site isolation principles. |
| 0.0.658 | Accepted site-switch isolation: bound-to-unbound state clears and late responses cannot repopulate it. | Generation/token protection and site-scoped stale-state clearing. |
| 0.0.660 | Accepted capability-driven price-only planner using verified Nord Pool provenance; Fiskvik could plan without the legacy ELLA binding. | Price capability provenance and deterministic site-scoped plan IDs. |
| 0.0.662 | Accepted price-only card shell and graph selection interaction. | Cards, selection clearing and site-switch protections. |
| 0.0.668–0.0.669 | Accepted actual/forecast/historical-model load enrichment and provenance-safe block totals. | Per-slot precedence and no zero-fill. |
| 0.0.670 onward | Accepted price-card DOM/spacing and later narrow dashboard spacing fixes. | The current dashboard visual baseline, not a planner eligibility rule. |
| 0.0.692 | Latest runtime baseline for this reset: dashboard spacing patch deployed and runtime healthy. | All accepted capture, planner, load, provenance and site-isolation behavior above. |
| 0.0.694 | First Stage 1 capability/load foundation deployment; not accepted because runtime exposed legacy ELLA-binding eligibility and incomplete capability semantics. | The versioned inventory/load-registry direction and no-write boundary were retained. |
| 0.0.695 | Corrective Stage 1 deployment; not accepted as a further startup forecast-capture legacy-binding gate was found after deployment. | Fingerprinted bindings, multi-resource inventory and configured-versus-available entity semantics were retained. |
| 0.0.696 | Stage 1 capability registry and individual-load foundation accepted after authenticated two-site runtime verification. | Site-scoped capability inventory, explicit binding verification, no-write invariants and deterministic resource preservation. |

The historical “price-only first, solar next, ESS later” roadmap is superseded
as a product ordering. Solar and ESS remain capabilities in the same planner,
but individual-load and action foundations now come first.

## 4. Capability model

Capabilities are verified, site-scoped facts. They are discovered from
canonical data, explicit resource/configuration contracts and runtime health;
they are never inferred from a site name, a generic `site_configured` flag,
an unrelated solar/meter/grid/Greenely binding, or a UI toggle.

The initial capability vocabulary is:

- spot/electricity market price;
- grid tariff, time-differentiated network cost and demand/peak component when
  actually modelled;
- total house consumption;
- individual load measurement;
- individual load actuator/control endpoint;
- solar actual and solar forecast;
- battery/ESS actual, SOC, capacity and limits;
- battery/ESS actuator/control rights;
- EV/charger, deadline and target;
- weather or other inputs only when relevant, verified and quality-gated.

Each capability record must carry at least a stable capability/resource ID,
site ID, contract/version, source identity and generation, verification state,
quality/staleness, units/sign convention where relevant, valid interval and
whether it is `observe_only`, `recommend_only` or `controllable`. Control
rights are never implied by measurement capability.

The planner consumes a capability snapshot. Replanning occurs when a verified
capability appears, disappears, becomes stale, changes generation or changes
its explicit permission/constraint set.

## 5. Economic signal and cost stack

The UI `Handel/Nät` switch is presentation only. It must never select or
disable ELLA's optimisation signal.

ELLA uses all verified relevant marginal costs for the current site:

- Nord Pool/spot or verified electricity price when that is the only valid
  economic layer;
- electricity price plus the site's verified time-dependent grid cost when
  the grid layer is modelled;
- future tax, demand tariff, export compensation, degradation or other costs
  only when their effective period, units and provenance are verified.

Missing cost components remain missing. They are not mirrored from another
site or estimated as zero. A plan must identify which cost layers were used.

## 6. Individual loads are first-class planning objects

An individual load record must support, as applicable:

- stable `load_id` and display name;
- measurement sensor(s), or explicit `none`;
- actuator/control endpoint, or explicit `none`;
- criticality/priority;
- flexibility: fixed, reducible, shiftable, interruptible or a more precise
  contract value;
- control mode: `observe_only`, `recommend_only` or `controllable`;
- measured or nominal power and energy need when verified;
- deadline/ready-by;
- allowed time windows;
- minimum runtime and minimum off-time;
- comfort and safety constraints;
- maximum starts/cycles/ramp limits where relevant;
- provenance, quality and staleness.

Criticality, flexibility and control rights are separate dimensions. One
priority list is not sufficient.

The planner must be able to keep critical loads running, reduce or pause
lower-priority flexible loads, move loads to better periods, and recommend a
move when no actuator exists. It may control a load only when a valid control
capability and explicit permission are present. “Reduce consumption” is not a
complete action: the plan identifies the load or remains a recommendation
without claiming a generic reduction.

## 7. Total load, decomposition and optional layers

Total-load forecasting remains valid without individual loads. When individual
measurements exist, ELLA may model known loads and a residual/base-load
component, but it must not attribute unmeasured consumption to a device.

For each 15-minute slot, a load estimate may use only this precedence:

1. verified canonical actual for an elapsed slot;
2. verified forward `load_forecast.v1` for a future slot;
3. the existing verified site-scoped historical model when it supports the
   local time/weekday bucket;
4. unavailable when none supports the slot.

Mixed totals retain slot-level provenance. Actual is never labelled as
forecast and model estimate is never labelled as actual. No gap becomes zero.

Solar is optional. When actual/forecast solar exists, net load is
`load - solar`. Forecast error/bias may be learned only when both forecast and
actual are verified. Solar uncertainty affects confidence/reserve; it is not
presented as exact production.

## 8. Battery/ESS capability boundary

A real battery plan requires, at minimum, verified current SOC, usable
capacity, min/max SOC and reserve, max charge/discharge power, efficiency/losses
when known or safely learned, grid-charge permission, and actuator availability
with control rights.

ESS records are per physical resource. Aggregate UI values are derived only
from valid per-ESS records. Unknown usable capacity excludes an ESS from a
capacity-weighted aggregate and marks the aggregate incomplete; it is not
treated as zero.

Actions include `charge`, `standby/hold`, `discharge` and
`reserve/keep capacity`. Standby is an active decision, for example preserving
capacity for a later peak. An unavailable ESS capability removes ESS actions
but does not remove price/load planning for the site.

## 9. Horizon, history and replanning

ELLA uses canonical site history as far back as quality and retention permit.
Forecasts extend forward only over verified horizons. Tomorrow's spot price is
used only after it is actually published and verified. Before publication,
ELLA may plan from other known layers but may not fabricate tomorrow's price.

Every plan stores `known_at` and source/model provenance so the decision-time
knowledge can be reconstructed. New prices, forecasts, material observed
deviation, capability changes and explicit valid state changes may trigger a
deterministic replan. Replanning must not rewrite an old plan snapshot.

## 10. Plan and action contracts

The generic plan contract is site-scoped and versioned. A plan carries a
stable plan ID, plan/model version, generated/decision time, horizon, source
generation references, capability snapshot, constraints and immutable plan
blocks.

Each block carries at least a stable `plan_block_id`, site ID, start/end,
primary action/category, short title/reason, verified input/capability
references, relevant price/cost/load/solar/SOC/power/energy values when
present, constraints/reserves and separate execution status when an actuator
contract exists.

Unknown fields are absent or explicitly unknown, never invented. A plan may
contain multiple internal sub-actions, but the normal UI exposes one primary
action and a short human reason.

### 10.1 Segmentation

The current implementation groups contiguous 15-minute price labels and can
therefore produce seven cards from 96 periods. That is current behaviour, not
the future product rule.

The target rule is: create a new block when ELLA's plan materially changes,
not at a fixed number of cards and not once per quarter-hour. A boundary may
be caused by a material cost-regime change, primary action change, battery
charge/standby/discharge change, SOC/reserve boundary, solar surplus/deficit
change, load/flexible-load action, individual load transition, deadline or
network tariff constraint. Adjacent slots with the same decision, reason and
constraints should be coalesced.

## 11. Clean card UI contract

The normal card is deliberately compact:

```text
00:00–06:00 · Billig prisperiod
Ladda batteriet
Inför morgonens pristopp
```

The three front-facing levels are time/cost context, primary action and a
short human reason. Provenance, mixed/actual/forecast, confidence, execution
technology and long numeric diagnostics do not belong on the normal front.
Normal operation is a valid action. The card must never imply execution when
the action was only planned or recommended.

The plan rail remains a sibling below the complete price card, including
chart, legend and period controls. It uses existing dashboard tokens and
site-safe stale-response/generation protection. A card is clickable and
selection highlights its exact interval in the relevant graph without changing
graph data. Outside click, scroll, site switch, date change and plan revision
clear or safely replace selection.

## 12. Debug and “Visa data” contract

When Debug is active, clicking an ELLA card exposes `Visa data` using the same
pattern as other cards. `Kopiera data` returns complete copyable JSON/text for
that block.

The payload is a decision-time snapshot: exactly what ELLA knew when the plan
was created, not a fresh read of sensors when the dialog opens. Where present,
it may include site/plan/block IDs, planner/model version, start/end,
generated/known time, effective prices and cost components, total-load and
individual-load inputs, solar, ESS, proposed actions, constraints, actuator
mode/status, expected impact, counterfactual fields and learning eligibility.
Unavailable fields are absent or explicitly unavailable. Credentials, raw
provider secrets and unnecessary personal data are excluded.

## 13. Learning and evaluation loop

The explicit loop is:

```text
Predict -> Plan -> Observe -> Explain error -> Learn -> Replan
```

Three dimensions remain separate: forecast/model quality, planner/decision
quality, and execution/actuator quality.

If ELLA recommends battery charging but no actuator exists, this is not an
execution failure. Sensors may still show what happened. If the model and
inputs are strong enough, ELLA may estimate a counterfactual result for “if
the plan had been followed”; that result is model/counterfactual, not actual.
If an actuator exists and a command fails, execution quality is classified
separately. If an observation is missing, there is no learning update for that
signal. Learning never widens hard device/safety constraints.

## 14. Control safety

The progression per capability/load is `Observe -> Recommend -> Control`.
There is no implicit activation, no vendor-specific control assumption and no
write path in the architecture reset or early stages. A later actuator must
be vendor-neutral, explicitly permitted, site/resource scoped, guarded,
acknowledged and fail-closed. Without dispatch, status is
`NOT_APPLICABLE`/`recommend_only`, never a claim of physical execution.

## 15. Staged roadmap and gates

The stages below supersede the older solar-first/ESS-later ordering. Each is a
separate release scope; no megarelease is implied.

### Stage 0 — Architecture reset and contracts

Entry: accepted 0.0.692 foundation, existing site isolation, canonical
provenance, price-only planner and load enrichment.

Deliver: capability registry contract, site isolation rules, plan/action schema,
individual-load schema, learning/evaluation semantics and clean card/debug
contract.

Exit: contracts are versioned and vendor-neutral; unknown/quality/provenance
semantics are explicit; legacy binding is transition history only; no future
stage is presented as implemented.

Tests: schema fixtures, missing/stale/wrong-site/partial input, absent
actuator, recommend-only, no fabricated values, deterministic IDs and debug
snapshot reproducibility.

### Stage 1 — Capability registry and individual-load foundation

Entry: Stage 0 contracts accepted.

Deliver: backend capability/resource model and explicit load configuration for
measurement, actuator, criticality, flexibility, control mode and constraints.
No actuator writes.

Exit: each load is site-scoped and independently verifiable; observe,
recommend and controllable modes are distinct; Fiskvik can model its own
loads without Vikarbodarna data; absent control yields recommendation or no
execution expectation. Runtime acceptance for 0.0.696 additionally confirmed
that legacy ELLA binding is transition history only, price-only planning does
not require it, explicit bindings require valid fingerprints, multi-resource
roles are preserved, and configured-but-missing entities remain unavailable.

Tests: enable/disable/invalid capability, stale/wrong-site load, missing
measurement, absent actuator, recommend-only, constraint validation,
cross-site isolation and deterministic reconfiguration.

### Stage 2 — Unified 15-minute site state and forecasts

Entry: capability and load resource identity are stable.

Deliver: one site state for total and individual loads, effective cost stack,
optional solar, optional ESS, quality/provenance/known-at and forecast frames.
Reuse canonical load model and existing price provenance.

Exit: no duplicate forecast model, no zero-fill, deterministic replay,
actual/forecast/model precedence preserved, and optional layers disappear
cleanly when absent.

Tests: full/partial/stale forecasts, actual gaps, wrong-site data, DST,
published versus unpublished tomorrow price, no observation/no learning,
site isolation and deterministic replan triggers.

### Stage 3 — Action planner in shadow/recommend-only mode

Entry: Stage 2 has a qualifying site state.

Deliver: materially-change-based action segmentation for load shifting,
reduction and prioritisation; solar/net-load decisions when available; battery
charge/hold/discharge/reserve concepts only when ESS capabilities qualify.
Clean cards expose primary action and short reason.

Exit: plans are immutable, site-scoped, reproducible and constraint checked;
absent actuators yield recommend-only/`NOT_APPLICABLE`; no write service
exists; Fiskvik remains useful without solar/ESS.

Tests: missing capability, stale/partial data, absent actuator,
recommend-only, wrong-site data, deterministic replan, action-boundary
segmentation, no fabricated values and exact card/graph interval selection.

### Stage 4 — Debug snapshot and explainability

Entry: Stage 3 plan blocks and stable revisions.

Deliver: Debug `Visa data` and `Kopiera data` for a plan block using a stored
decision-time snapshot.

Exit: copied payload reproduces decision inputs and provenance; opening the
dialog does not substitute current sensor state; secrets and unnecessary PII
are excluded.

Tests: snapshot reproducibility after state changes/restart, missing optional
capability, wrong-site rejection, redaction, stable JSON and copy output.

### Stage 5 — Evaluation and site-scoped learning loop

Entry: qualifying plans, observations and decision snapshots exist.

Deliver: forecast/model, planner/decision and execution scorecards; error
explanation; site-scoped calibration; deterministic replan; counterfactual
evaluation when inputs are strong enough.

Exit: actual and counterfactual are visibly distinct; no execution failure is
assigned without an actuator; no learning update occurs without observation;
model promotion cannot widen safety constraints.

Tests: forecast error, planner regret, actuator-failure separation, missing
observation, counterfactual insufficiency, site leakage, replay determinism,
rollback and seasonal/site holdout evaluation.

### Stage 6 — Solar/ESS enrichment and physical calibration

Entry: Stage 5 quality evidence and verified site-specific capabilities.

Deliver: solar bias/uncertainty and per-ESS physical calibration, including
SOC, usable capacity, limits, efficiency, reserve and planned trajectory.
Only capable sites receive these actions; Fiskvik remains fully functional
without them.

Exit: no cross-site parameter transfer, bounded energy balance, unknown
capacity/limits fail closed, and planned SOC comes from the planner's model.

Tests: actual/forecast overlap, solar uncertainty, ESS efficiency/loss,
multiple ESS, stale SOC, reserve/limit violation, temperature/derating and
counterfactual replay.

### Stage 7 — Controlled execution

Entry: explicit site/resource permissions, accepted shadow/backtest evidence
and a vendor-neutral actuator contract.

Deliver: guarded per-load/per-ESS dispatch, acknowledgement, timeout,
idempotency, rate limits, failure classification, rollback and safe fallback.

Exit: writes occur only through explicitly armed actuator capabilities;
execution is acknowledged or marked failed; planner and execution quality
remain separate; any boundary violation stops further commands.

Tests: supervised hardware-in-loop or adapter tests, wrong-site prevention,
stale state, permission removal, duplicate command, timeout, actuator failure,
rollback, manual override and zero-write tests on unarmed sites.

## 16. Acceptance philosophy for every future stage

Every implementation release must explicitly test, where applicable: missing
capability; stale/partial data; wrong-site data and Vikarbodarna/Fiskvik
isolation; absent actuator and recommend-only semantics; actuator failure when
an actuator exists; no observation means no learning; deterministic plan IDs,
segmentation and replan; no fabricated values or hidden zero-fill; reproducible
decision-time debug snapshot; and preservation of Greenely, Solar Evidence,
Single Run, canonical integrity and battery-write guardrails.

Runtime acceptance must distinguish static tests, deployed runtime state and
authenticated UI evidence. A stage is not accepted merely because code exists
or cards render.

## 17. Current implementation boundary

At accepted runtime baseline 0.0.696, the implementation includes the Stage 1
site-scoped capability inventory and persistent individual-load foundation on
top of the existing capability-driven price-block planner, canonical load
enrichment and dashboard/card interaction. It is not yet the vNext action
planner, unified site-state model, individual-load controller, learning loop
or physical control architecture described above.

The current seven-card result is explained by the current third-based price
classification and contiguous grouping. It is not itself a defect. Future
card count must emerge from material action changes and constraints.

Stage 0 architecture/contracts and Stage 1 capability/load foundation are
implemented and accepted. The next active implementation scope is **Stage 2 —
Unified 15-minute site state and forecasts**. Solar-first and ESS-first
implementation remain superseded as ordering decisions; they are optional
capabilities within the staged architecture and must not bypass Stage 2.
