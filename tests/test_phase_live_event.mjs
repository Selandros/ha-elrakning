import assert from "node:assert/strict";
import {
  buildPhaseLiveMeterPoint,
  createMeterPowerHistoryState,
  mergeMeterPowerHistoryPoint,
} from "../custom_components/elrakning/frontend/elrakning-panel.js";

const mapping = {
  invert_power: false,
  phase_source_entities: {
    current: { l1: "sensor.current_l1", l2: "sensor.current_l2", l3: "sensor.current_l3" },
    voltage: { l1: "sensor.voltage_l1", l2: "sensor.voltage_l2", l3: "sensor.voltage_l3" },
    active_power: { l1: "sensor.power_l1", l2: "sensor.power_l2", l3: "sensor.power_l3" },
  },
};

const states = {
  "sensor.current_l1": { state: "4", attributes: { device_class: "current", unit_of_measurement: "A" } },
  "sensor.current_l2": { state: "5", attributes: { device_class: "current", unit_of_measurement: "A" } },
  "sensor.current_l3": { state: "6", attributes: { device_class: "current", unit_of_measurement: "A" } },
  "sensor.voltage_l1": { state: "234", attributes: { device_class: "voltage", unit_of_measurement: "V" } },
  "sensor.voltage_l2": { state: "233.9", attributes: { device_class: "voltage", unit_of_measurement: "V" } },
  "sensor.voltage_l3": { state: "231.9", attributes: { device_class: "voltage", unit_of_measurement: "V" } },
  "sensor.power_l1": { state: "1200", attributes: { device_class: "power", unit_of_measurement: "W" } },
  "sensor.power_l2": { state: "0.8", attributes: { device_class: "power", unit_of_measurement: "kW" } },
  "sensor.power_l3": { state: "-400", attributes: { device_class: "power", unit_of_measurement: "W" } },
};

const event = {
  data: {
    entity_id: "sensor.voltage_l1",
    new_state: { ...states["sensor.voltage_l1"], last_updated: "2026-10-08T08:05:00.000Z" },
  },
};
const point = buildPhaseLiveMeterPoint(event, mapping, states);
assert.deepEqual(point, {
  entity_id: "sensor.voltage_l1",
  timestamp: "2026-10-08T08:05:00.000Z",
  phase_current_a: { l1: 4, l2: 5, l3: 6 },
  phase_voltage_v: { l1: 234, l2: 233.9, l3: 231.9 },
  phase_active_power_kw: { l1: 1.2, l2: 0.8, l3: -0.4 },
});

const history = {
  ...createMeterPowerHistoryState("2026-10-08"),
  phase_history: {
    current: { l1: { points: [{ timestamp: "2026-10-08T08:00:00.000Z", value: 3 }] } },
    voltage: { l1: { points: [{ timestamp: "2026-10-08T08:00:00.000Z", value: 234 }] } },
    active_power: { l1: { points: [{ timestamp: "2026-10-08T08:00:00.000Z", value: 1.1 }] } },
  },
};
const merged = mergeMeterPowerHistoryPoint(history, point, "sensor.grid_power").history;
assert.equal(merged.phase_history.current.l1.points.at(-1).timestamp, "2026-10-08T08:05:00.000Z");
assert.equal(merged.phase_history.voltage.l1.points.at(-1).value, 234);
assert.equal(merged.phase_history.active_power.l1.points.at(-1).value, 1.2);

const unavailablePhase = buildPhaseLiveMeterPoint({ data: { entity_id: "sensor.voltage_l1", new_state: { ...event.data.new_state, state: "unknown" } } }, mapping, states);
assert.equal(unavailablePhase.phase_voltage_v.l1, undefined);
assert.equal(unavailablePhase.phase_voltage_v.l2, 233.9);
assert.equal(buildPhaseLiveMeterPoint({ data: { entity_id: "sensor.voltage_l1", new_state: { ...event.data.new_state, last_updated: null } } }, mapping, states), null);

console.log("passed live phase state-event append regression test");
