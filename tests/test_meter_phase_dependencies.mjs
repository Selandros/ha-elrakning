import assert from "node:assert/strict";
import { phaseChartDomNeedsRender, phaseMeterStateDependenciesChanged } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const base = {
  facility: { fuse_ampere: 16 },
  provider_name: "E.ON",
  device_name: "Meter",
  configured: true,
  power_entity: "sensor.grid_power",
  energy_import_entity: "sensor.import",
  phase_current_a: { l1: 1, l2: -2, l3: 3 },
  phase_voltage_v: { l1: 230, l2: 231, l3: 232 },
  phase_active_power_kw: { l1: 0.1, l2: -0.2, l3: 0.3 },
  phase_source_entities: {
    current: { l1: "sensor.l1_current", l2: "sensor.l2_current", l3: "sensor.l3_current" },
    voltage: { l1: "sensor.l1_voltage", l2: "sensor.l2_voltage", l3: "sensor.l3_voltage" },
    active_power: { l1: "sensor.l1_power", l2: "sensor.l2_power", l3: "sensor.l3_power" },
  },
};

assert.equal(phaseMeterStateDependenciesChanged(null, base, null), true);
assert.equal(phaseMeterStateDependenciesChanged(base, { ...base, provider_name: "Other" }, null), false);
assert.equal(phaseMeterStateDependenciesChanged(base, { ...base, device_name: "Other" }, null), false);
assert.equal(phaseMeterStateDependenciesChanged(base, { ...base, energy_import_entity: "sensor.other" }, null), false);
assert.equal(phaseMeterStateDependenciesChanged(base, { ...base, phase_current_a: { ...base.phase_current_a, l2: -2.5 } }, null), true);
assert.equal(phaseMeterStateDependenciesChanged(base, { ...base, phase_voltage_v: { ...base.phase_voltage_v, l1: 229 } }, null), true);
assert.equal(phaseMeterStateDependenciesChanged(base, { ...base, phase_active_power_kw: { ...base.phase_active_power_kw, l3: 0.4 } }, null), true);
assert.equal(phaseMeterStateDependenciesChanged(base, { ...base, phase_source_entities: { ...base.phase_source_entities, current: { ...base.phase_source_entities.current, l1: "sensor.other" } } }, null), true);
assert.equal(phaseMeterStateDependenciesChanged(base, { ...base, facility: { fuse_ampere: 20 } }, null), true);

const eonFallback = { ...base, facility: { fuse_ampere: null }, fuse_ampere: null };
const sameResolvedFuse = { ...eonFallback, facility: { fuse_ampere: null }, fuse_ampere: null };
assert.equal(phaseMeterStateDependenciesChanged(eonFallback, sameResolvedFuse, { facility: { fuse_ampere: 16 } }), false);
assert.equal(phaseMeterStateDependenciesChanged(base, { ...base, fuse_ampere: 20 }, { facility: { fuse_ampere: 16 } }), false);
assert.equal(phaseMeterStateDependenciesChanged(eonFallback, { ...eonFallback, fuse_ampere: 20 }, null), true);

assert.equal(phaseMeterStateDependenciesChanged(base, { ...base, phase_current_a: null }, null), true);
assert.equal(phaseMeterStateDependenciesChanged({ ...base, phase_current_a: null }, base, null), true);

let phaseDom = { rendered: true, querySelector: (selector) => phaseDom.rendered && selector === ".phase-history-svg, .phase-history-empty" ? {} : null };
assert.equal(phaseChartDomNeedsRender(phaseDom), false);
phaseDom.rendered = false;
assert.equal(phaseChartDomNeedsRender(phaseDom), true);
phaseDom.rendered = true;
assert.equal(phaseChartDomNeedsRender(phaseDom), false);
assert.equal(phaseMeterStateDependenciesChanged(base, { ...base }, null), false);
console.log("passed meter phase dependency invalidation test");
