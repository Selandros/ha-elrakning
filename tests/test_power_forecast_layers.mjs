import assert from "node:assert/strict";
import fs from "node:fs";
import {
  buildForecastSegments,
  buildThresholdClippedSegments,
  mergePowerHistoryEnrichmentState,
  selectPowerForecastPoints,
} from "../custom_components/elrakning/frontend/elrakning-panel.js";

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
const actualPoints = [
  { timestamp: "2026-09-20T12:00:00Z", value_kw: 1, raw_timestamp: "2026-09-20T12:00:00Z" },
  { timestamp: "2026-09-20T12:05:00Z", value_kw: 1.2, raw_timestamp: "2026-09-20T12:05:00Z" },
];
const forecastPoints = [
  { timestamp: "2026-09-20T12:30:00Z", value_kw: 1.4 },
  { timestamp: "2026-09-20T12:45:00Z", value_kw: 1.6 },
];
const allForecastSeries = Object.fromEntries(["solar", "consumption", "charging", "discharging", "import", "export"].map((key) => [
  key,
  { available: true, forecast_points: forecastPoints },
]));
const merged = mergePowerHistoryEnrichmentState({
  response: { power_forecast: { available: true, series: allForecastSeries } },
  existingState: { series: { solar: { points: actualPoints } } },
});
assert.deepEqual(Object.keys(merged.power_forecast.series).sort(), ["charging", "consumption", "discharging", "export", "import", "solar"]);
assert.equal(buildThresholdClippedSegments(actualPoints, "value_kw").length, 1, "actual series must produce a render segment");
for (const series of Object.values(merged.power_forecast.series)) {
  assert.equal(buildForecastSegments(series.forecast_points, "value_kw").length, 1, "each forecast series must produce its own render segment");
}
assert.match(panel, /\$\{className\} chart-power-forecast/);
assert.match(panel, /powerLinesFor\("solar", "chart-power-solar", visibleLayers\.solar\)[\s\S]*powerForecastLinesFor\("solar", "chart-power-solar", visibleLayers\.solar\)/);
assert.match(panel, /powerLinesFor\("consumption", "chart-power-consumption", visibleLayers\.consumption\)[\s\S]*powerForecastLinesFor\("consumption", "chart-power-consumption", visibleLayers\.consumption\)/);
assert.match(panel, /const forecastSeries = Object\.fromEntries\(\["solar", "consumption", "charging", "discharging", "import", "export"\]/);
assert.match(panel, /mergePowerHistoryEnrichmentState\(/);
assert.match(panel, /schema: "ella_power_forecast\.v1"/);
assert.match(panel, /chart-power-forecast\s*\{[\s\S]*?stroke-dasharray: 8 5;/);
assert.match(panel, /return !forecastPointIsMarked\(point\)/);
assert.match(panel, /if \(loadForecastPoints\.length\) powerForecastPoints\.consumption = loadForecastPoints/);
assert.doesNotMatch(panel, /buildMeterDisplayAreaMarkup\([^\n]*chart-power-forecast/);

console.log("power forecast layer selection/render regression: PASS");
