import assert from "node:assert/strict";
import { buildSolarDailyHistory, buildSolarHistoryTooltipFields } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const now = new Date("2026-09-01T23:59:00+02:00");
const points = Array.from({ length: 288 }, (_, index) => ({
  timestamp: new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, index * 5).toISOString(),
  value_kw: 1.645669,
}));

const completed = buildSolarDailyHistory(
  points,
  { "2026-09-01": 37.874 },
  now,
  1,
  { today_kwh: 46.941, remaining_today_kwh: 0 },
)[0];
assert.equal(completed.forecastComparisonBasis, "full_day_forecast");
assert.equal(completed.forecastComparisonExpectedKwh, 37.874);
assert.equal(completed.forecastComparisonActualKwh, completed.producedKwh);
assert.ok(completed.forecastAccuracyPercent < 100);
assert.ok(completed.forecastAccuracyPercent > 95);
assert.ok(completed.forecastDeviationPercent > 0);
assert.ok(buildSolarHistoryTooltipFields(completed, { today_kwh: 46.941, remaining_today_kwh: 0 }, now)
  .some((field) => field.label === "Prognosträff"));
assert.ok(!buildSolarHistoryTooltipFields(completed, { today_kwh: 46.941, remaining_today_kwh: 0 }, now)
  .some((field) => field.label.includes("hittills")));

const active = buildSolarDailyHistory(
  points,
  { "2026-09-01": 37.874 },
  now,
  1,
  { today_kwh: 46.941, remaining_today_kwh: 10 },
)[0];
assert.equal(active.forecastComparisonBasis, "forecast_so_far");
assert.equal(active.forecastComparisonExpectedKwh, 36.941);

const missingBaseline = buildSolarDailyHistory(
  points,
  {},
  now,
  1,
  { today_kwh: 46.941, remaining_today_kwh: 0 },
)[0];
assert.equal(missingBaseline.forecastComparisonBasis, "full_day_forecast_unavailable");
assert.equal(missingBaseline.forecastComparisonExpectedKwh, null);
assert.equal(missingBaseline.forecastAccuracyPercent, null);
assert.ok(!buildSolarHistoryTooltipFields(missingBaseline, { today_kwh: 46.941, remaining_today_kwh: 0 }, now)
  .some((field) => field.label.includes("Prognos")));

console.log("solar forecast completion/discovery semantics passed");
