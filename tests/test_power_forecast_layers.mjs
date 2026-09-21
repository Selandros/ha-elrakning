import assert from "node:assert/strict";
import fs from "node:fs";
import { selectPowerForecastPoints } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const panel = fs.readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const now = new Date("2026-09-20T12:07:00+02:00");

const source = {
  forecast_frames: [
    {
      frame_id: "old",
      known_at: "2026-09-20T08:00:00Z",
      points: [{ valid_at: "2026-09-20T12:15:00+02:00", value_kw: 1 }],
    },
    {
      frame_id: "new",
      known_at: "2026-09-20T12:01:00Z",
      points: [
        { valid_at: "2026-09-20T12:15:00+02:00", value_kw: 2 },
        { valid_at: "2026-09-20T12:30:00+02:00", value_kw: 3 },
      ],
    },
  ],
};
assert.deepEqual(selectPowerForecastPoints(source, { selectedDate: now, now }), [
  { timestamp: Date.parse("2026-09-20T12:15:00+02:00"), value_kw: 2, forecast: true },
  { timestamp: Date.parse("2026-09-20T12:30:00+02:00"), value_kw: 3, forecast: true },
]);

const past = new Date("2026-09-19T12:07:00+02:00");
assert.deepEqual(selectPowerForecastPoints(source, { selectedDate: past, now }), []);

for (const [key, className] of [
  ["import", "chart-meter-import"],
  ["export", "chart-meter-export"],
  ["solar", "chart-power-solar"],
  ["consumption", "chart-power-consumption"],
  ["charging", "chart-power-charging"],
  ["discharging", "chart-power-discharging"],
]) {
  assert.match(panel, new RegExp(`powerForecastLinesFor\\("${key}", "${className}", visibleLayers\\.${key}\\)`));
}
for (const key of ["import", "export", "solar", "consumption", "charging", "discharging"]) {
  assert.match(panel, new RegExp(`forecastSource\\("${key}",`));
}
assert.match(panel, /power_forecast: response\?\.power_forecast/);
assert.match(panel, /schema: "ella_power_forecast\.v1"/);
assert.match(panel, /chart-power-forecast\s*\{[\s\S]*?stroke-dasharray: 8 5;/);
assert.match(panel, /return !forecastPointIsMarked\(point\)/);
assert.match(panel, /if \(loadForecastPoints\.length\) powerForecastPoints\.consumption = loadForecastPoints/);
assert.doesNotMatch(panel, /buildMeterDisplayAreaMarkup\([^\n]*chart-power-forecast/);

console.log("power forecast layer selection/render regression: PASS");
