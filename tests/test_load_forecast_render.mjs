import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { selectLoadForecastPoints } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const panel = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
assert.doesNotMatch(panel, /actualBeforeForecast|loadForecastPoints\.unshift/);

const siteId = "site-a";
const oldV1 = {
  site_id: siteId, logical_role: "load.forecast", frame_id: "old-v1", revision: 9,
  known_at: "2026-09-20T21:00:00+02:00", quality: { model_version: "load-profile-v1" },
  points: [
    { valid_at: "2026-09-20T20:45:00+02:00", value: 1000 },
    { valid_at: "2026-09-20T21:00:00+02:00", value: 1000 },
  ],
};
const currentV2 = {
  site_id: siteId, logical_role: "load.forecast", frame_id: "current-v2", revision: 2,
  known_at: "2026-09-20T19:00:00+02:00", quality: { model_version: "load-profile-v2" },
  points: [
    { valid_at: "2026-09-20T20:30:00+02:00", value: 1200 },
    { valid_at: "2026-09-20T20:45:00+02:00", value: 1300 },
    { valid_at: "2026-09-20T21:00:00+02:00", value: 1400 },
  ],
};
const selectedDate = new Date("2026-09-20T12:00:00+02:00");

const at2041 = selectLoadForecastPoints([oldV1, currentV2], {
  siteId, selectedDate, now: new Date("2026-09-20T20:41:00+02:00"),
});
assert.deepEqual(at2041.map((point) => point.timestamp), [
  new Date("2026-09-20T20:45:00+02:00").getTime(),
  new Date("2026-09-20T21:00:00+02:00").getTime(),
]);
assert.equal(at2041[0].value_kw, 1.3);

const at2045 = selectLoadForecastPoints([oldV1, currentV2], {
  siteId, selectedDate, now: new Date("2026-09-20T20:45:00+02:00"),
});
assert.equal(at2045[0].timestamp, new Date("2026-09-20T21:00:00+02:00").getTime());

const at2054 = selectLoadForecastPoints([oldV1, currentV2], {
  siteId, selectedDate, now: new Date("2026-09-20T20:54:00+02:00"),
});
assert.equal(at2054[0].timestamp, new Date("2026-09-20T21:00:00+02:00").getTime());
assert.ok(at2054.every((point) => point.timestamp >= new Date("2026-09-20T21:00:00+02:00").getTime()));

assert.deepEqual(selectLoadForecastPoints([oldV1, currentV2], {
  siteId, selectedDate: new Date("2026-09-19T12:00:00+02:00"), now: new Date("2026-09-20T20:41:00+02:00"),
}), []);

const future = selectLoadForecastPoints([oldV1, currentV2], {
  siteId, selectedDate: new Date("2026-09-21T12:00:00+02:00"), now: new Date("2026-09-20T20:41:00+02:00"),
});
assert.equal(future.length, 0);

const futureFrame = {
  ...currentV2,
  frame_id: "future-v2",
  known_at: "2026-09-20T20:00:00+02:00",
  points: [{ valid_at: "2026-09-21T00:00:00+02:00", value: 1500 }],
};
const futurePoints = selectLoadForecastPoints([currentV2, futureFrame], {
  siteId, selectedDate: new Date("2026-09-21T12:00:00+02:00"), now: new Date("2026-09-20T20:41:00+02:00"),
});
assert.equal(futurePoints.length, 1);
assert.equal(futurePoints[0].value_kw, 1.5);

const foreign = selectLoadForecastPoints([{ ...currentV2, site_id: "site-b" }], {
  siteId, selectedDate, now: new Date("2026-09-20T20:41:00+02:00"),
});
assert.deepEqual(foreign, []);

console.log("load forecast render selection regression passed");
