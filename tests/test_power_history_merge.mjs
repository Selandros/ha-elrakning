import assert from "node:assert/strict";
import { mergePowerHistoryPoint } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const point = (timestamp, value) => ({ timestamp, value_kw: value });

const empty = mergePowerHistoryPoint([], point("2026-08-30T10:00:00.000Z", 1), Date.parse("2026-08-30T10:00:00.000Z"));
assert.deepEqual(empty, [point("2026-08-30T10:00:00.000Z", 1)]);

const ordered = [point("2026-08-30T10:00:00.000Z", 1), point("2026-08-30T10:01:00.000Z", 2)];
const orderedResult = mergePowerHistoryPoint(ordered, point("2026-08-30T10:02:00.000Z", 3), Date.parse("2026-08-30T10:02:00.000Z"));
assert.deepEqual(orderedResult, [...ordered, point("2026-08-30T10:02:00.000Z", 3)]);
assert.notStrictEqual(orderedResult, ordered);

const duplicateLast = mergePowerHistoryPoint(orderedResult, point("2026-08-30T10:02:00.000Z", 4), Date.parse("2026-08-30T10:02:00.000Z"));
assert.deepEqual(duplicateLast, [ordered[0], ordered[1], point("2026-08-30T10:02:00.000Z", 4)]);
assert.notStrictEqual(duplicateLast, orderedResult);

const outOfOrder = mergePowerHistoryPoint([ordered[0], orderedResult[2]], point("2026-08-30T10:01:30.000Z", 2.5), Date.parse("2026-08-30T10:01:30.000Z"));
assert.deepEqual(outOfOrder.map(({ timestamp }) => timestamp), [
  "2026-08-30T10:00:00.000Z",
  "2026-08-30T10:01:30.000Z",
  "2026-08-30T10:02:00.000Z",
]);

const duplicateEarlier = mergePowerHistoryPoint(outOfOrder, point("2026-08-30T10:01:30.000Z", 5), Date.parse("2026-08-30T10:01:30.000Z"));
assert.deepEqual(duplicateEarlier, [
  ordered[0],
  point("2026-08-30T10:01:30.000Z", 5),
  orderedResult[2],
]);

const solar = [point("2026-08-30T10:00:00.000Z", 7)];
const consumption = [point("2026-08-30T10:00:00.000Z", 8)];
const solarResult = mergePowerHistoryPoint(solar, point("2026-08-30T10:01:00.000Z", 9), Date.parse("2026-08-30T10:01:00.000Z"));
assert.deepEqual(consumption, [point("2026-08-30T10:00:00.000Z", 8)]);
assert.deepEqual(solarResult, [...solar, point("2026-08-30T10:01:00.000Z", 9)]);

console.log("passed power history merge fast-path/fallback tests");
