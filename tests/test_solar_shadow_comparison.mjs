import assert from "node:assert/strict";
import { buildSolarDailyHistory } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const now = new Date("2026-09-01T23:59:00+02:00");
const points = Array.from({ length: 288 * 7 }, (_, index) => {
  const timestamp = new Date(now.getTime() - (288 * 7 - 1 - index) * 5 * 60 * 1000);
  return { timestamp: timestamp.toISOString(), value_kw: 1.645669 };
});
const baselines = {
  "2026-08-28": 12,
  "2026-08-29": 18.829,
  "2026-08-30": 16.571,
  "2026-08-31": 16.602,
  "2026-09-01": 37.874,
};
const shadowDays = [
  { target_date: "2026-08-28", candidate_forecast_kwh: 11.5, candidate_comparison_available: true },
  { target_date: "2026-09-01", candidate_forecast_kwh: 37.874, candidate_replay_available: true, candidate_comparison_available: false },
];
const days = buildSolarDailyHistory(
  points,
  baselines,
  now,
  7,
  { today_kwh: 46.941, remaining_today_kwh: 0 },
  shadowDays,
);
const byDate = Object.fromEntries(days.map((day) => [day.date, day]));

for (const date of ["2026-08-29", "2026-08-30", "2026-08-31", "2026-09-01"]) {
  assert.equal(byDate[date].utilizationPercent, null, `${date} must not expose legacy accuracy`);
}
assert.ok(Number.isFinite(byDate["2026-08-28"].utilizationPercent));
assert.equal(byDate["2026-08-28"].forecastComparisonExpectedKwh, 11.5);
assert.equal(byDate["2026-09-01"].forecastAccuracyPercent, null);

console.log("solar shadow comparison availability semantics passed");
