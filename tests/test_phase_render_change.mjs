import assert from "node:assert/strict";
import { createMeterPowerHistoryState, mergeMeterPowerHistoryPoint } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const event = (timestamp, current = 1) => ({
  timestamp,
  entity_id: "sensor.phase_l1",
  phase_current_a: { l1: current },
});

let result = mergeMeterPowerHistoryPoint(
  { ...createMeterPowerHistoryState("2026-08-30") },
  event("2026-08-30T12:00:00.000Z"),
  "sensor.grid_power",
);
assert.equal(result.phaseRenderChanged, true);
const firstPoint = result.history.phase_history.current.l1.points[0];
const firstPoints = result.history.phase_history.current.l1.points;

result = mergeMeterPowerHistoryPoint(result.history, event("2026-08-30T12:05:00.000Z"), "sensor.grid_power");
assert.equal(result.phaseRenderChanged, true);

const beforeDuplicate = result.history;
const beforeDuplicatePoints = beforeDuplicate.phase_history.current.l1.points;
const beforeDuplicatePoint = beforeDuplicatePoints.at(-1);
result = mergeMeterPowerHistoryPoint(beforeDuplicate, event("2026-08-30T12:05:00.000Z", -1), "sensor.grid_power");
assert.equal(result.phaseRenderChanged, false);
assert.strictEqual(result.history.phase_history.current.l1.points, beforeDuplicatePoints);
assert.strictEqual(result.history.phase_history.current.l1.points.at(-1), beforeDuplicatePoint);
assert.equal(result.history.phase_history.current.l1.points.at(-1).value, 1);

const voltagePoints = [{ timestamp: "2026-08-30T12:05:00.000Z", value: 230 }];
const olderHistory = {
  ...beforeDuplicate,
  phase_history: {
    ...beforeDuplicate.phase_history,
    voltage: { l1: { points: voltagePoints } },
  },
};
result = mergeMeterPowerHistoryPoint(olderHistory, event("2026-08-30T12:00:00.000Z"), "sensor.grid_power");
assert.equal(result.phaseRenderChanged, false);
assert.strictEqual(result.history.phase_history.current.l1.points, olderHistory.phase_history.current.l1.points);

result = mergeMeterPowerHistoryPoint(olderHistory, event("2026-08-30T12:00:00.000Z", 2), "sensor.grid_power");
assert.equal(result.phaseRenderChanged, true);
assert.deepEqual(result.history.phase_history.current.l1.points.map((point) => point.timestamp), [
  "2026-08-30T12:00:00.000Z",
  "2026-08-30T12:05:00.000Z",
]);
assert.equal(result.history.phase_history.current.l1.points[0].value, 2);
assert.strictEqual(result.history.phase_history.voltage.l1.points, voltagePoints);

const invalid = mergeMeterPowerHistoryPoint(result.history, event("2026-08-30T12:10:00.000Z", "not-a-number"), "sensor.grid_power");
assert.equal(invalid.phaseRenderChanged, false);
assert.equal(invalid.history.phase_history.current.l1.points.length, 2);

const metadataHistory = {
  ...createMeterPowerHistoryState("2026-08-30"),
  phase_history: { current: { l1: { points: [{ timestamp: "2026-08-30T12:00:00.000Z", value: 1, raw_value: 100 }] } } },
};
const metadataResult = mergeMeterPowerHistoryPoint(metadataHistory, event("2026-08-30T12:00:00.000Z", 1), "sensor.grid_power");
assert.equal(metadataResult.phaseRenderChanged, false);
assert.equal(metadataResult.history.phase_history.current.l1.points[0].raw_value, 100);

const equivalentTimestampHistory = {
  ...createMeterPowerHistoryState("2026-09-01"),
  phase_history: { current: { l1: { points: [{ timestamp: "2026-09-01T10:00:00+00:00", value: 1, raw_value: 100 }] } } },
};
let equivalentTimestampResult = mergeMeterPowerHistoryPoint(
  equivalentTimestampHistory,
  event("2026-09-01T10:00:00.000Z", 1),
  "sensor.grid_power",
);
assert.equal(equivalentTimestampResult.phaseRenderChanged, false);
assert.equal(equivalentTimestampResult.history.phase_history.current.l1.points.length, 1);
assert.equal(equivalentTimestampResult.history.phase_history.current.l1.points[0].raw_value, 100);

equivalentTimestampResult = mergeMeterPowerHistoryPoint(
  equivalentTimestampHistory,
  event("2026-09-01T10:00:00.000Z", 2),
  "sensor.grid_power",
);
assert.equal(equivalentTimestampResult.phaseRenderChanged, true);
assert.equal(equivalentTimestampResult.history.phase_history.current.l1.points.length, 1);
assert.equal(equivalentTimestampResult.history.phase_history.current.l1.points[0].value, 2);
assert.equal(equivalentTimestampResult.history.phase_history.current.l1.points[0].timestamp, "2026-09-01T10:00:00+00:00");

const offsetTimestampHistory = {
  ...createMeterPowerHistoryState("2026-09-01"),
  phase_history: { current: { l1: { points: [{ timestamp: "2026-09-01T12:00:00+02:00", value: 1 }] } } },
};
const offsetTimestampResult = mergeMeterPowerHistoryPoint(
  offsetTimestampHistory,
  event("2026-09-01T10:00:00.000Z", 1),
  "sensor.grid_power",
);
assert.equal(offsetTimestampResult.phaseRenderChanged, false);
assert.equal(offsetTimestampResult.history.phase_history.current.l1.points.length, 1);

const oneMillisecondResult = mergeMeterPowerHistoryPoint(
  equivalentTimestampHistory,
  event("2026-09-01T10:00:00.001Z", 1),
  "sensor.grid_power",
);
assert.equal(oneMillisecondResult.phaseRenderChanged, true);
assert.equal(oneMillisecondResult.history.phase_history.current.l1.points.length, 2);

assert.strictEqual(firstPoint, firstPoints[0]);
console.log("passed phase render change semantics test");
