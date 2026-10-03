import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { axisCollisionInset, buildCostFieldMarkup, buildCostFieldModel, buildHourlyBarEdges, buildHourlyBoundaryHours, buildNormalLoadProfile, buildPriceCategoryBands, buildPriceChartGeometry, buildPriceStepAreaPaths, buildPriceStepSegments, priceAxisGutter, selectHourlyPricePeriods } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const panelSource = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const assertClose = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} !== ${expected}`);
assert.match(panelSource, /preserveAspectRatio="none" viewBox="0 0 \$\{width\} \$\{height\}" role="img" aria-label="Elpris/);
assert.match(panelSource, /class="price-cost-field/);
assert.match(panelSource, /buildCostFieldMarkup\(periods, prices, normalLoadProfile, meterRange/);
assert.match(panelSource, /buildNormalLoadProfile\(/);
assert.match(panelSource, /gradientUnits="userSpaceOnUse"/);
assert.match(panelSource, /data-cost-field-status="insufficient_history"/);
assert.match(panelSource, /\.price-cost-field \{[\s\S]*opacity: \.34;/);
assert.doesNotMatch(panelSource, /price-level-gradient|price-step-area|price-step-line|y\(average\)/);
assert.match(panelSource, /data-price-now-marker/);

const selectedDate = new Date("2026-10-03T12:00:00+02:00");
const history = [];
for (let dayOffset = 1; dayOffset <= 7; dayOffset += 1) {
  const historyDay = new Date(selectedDate);
  historyDay.setDate(historyDay.getDate() - dayOffset);
  const day = historyDay.toISOString().slice(0, 10);
  history.push({ timestamp: `${day}T10:00:00+02:00`, import_kw: 2 + dayOffset / 10 });
  history.push({ timestamp: `${day}T10:15:00+02:00`, import_kw: 5 });
}
history.push({ timestamp: "2026-10-04T10:00:00+02:00", import_kw: 99 });
const loadProfile = buildNormalLoadProfile(history, selectedDate, { siteId: "site-a", historySiteId: "site-a" });
assert.equal(loadProfile.available, true);
assert.equal(loadProfile.observation_counts[40], 7);
assertClose(loadProfile.samples[40], 2.4);
assert.equal(buildNormalLoadProfile(history, selectedDate, { siteId: "site-a", historySiteId: "site-b" }).reason, "site_mismatch");
assert.equal(buildNormalLoadProfile(history, selectedDate, { siteId: "site-a", historySiteId: "site-a" }).samples[40], 2.4);
const fallbackHistory = [
  { timestamp: "2026-10-01T02:00:00+02:00", import_kw: 1 },
  { timestamp: "2026-10-02T06:00:00+02:00", import_kw: 2 },
  { timestamp: "2026-10-02T18:00:00+02:00", import_kw: 10 },
];
const tierBProfile = buildNormalLoadProfile(fallbackHistory, selectedDate, { siteId: "site-a", historySiteId: "site-a" });
assert.equal(tierBProfile.available, true);
assert.equal(tierBProfile.tier, "B");
assert.equal(tierBProfile.fallback_source, "tier_b_all_prior_observations");
assertClose(tierBProfile.fallback_load_kw, 2);
const tierCProfile = buildNormalLoadProfile([
  { timestamp: "2026-10-03T08:00:00+02:00", import_kw: 1 },
  { timestamp: "2026-10-03T09:00:00+02:00", import_kw: 3 },
  { timestamp: "2026-10-03T10:00:00+02:00", import_kw: 5 },
  { timestamp: "2026-10-03T13:00:00+02:00", import_kw: 99 },
], selectedDate, { siteId: "site-a", historySiteId: "site-a", now: new Date("2026-10-03T12:00:00+02:00") });
assert.equal(tierCProfile.available, true);
assert.equal(tierCProfile.tier, "C");
assert.equal(tierCProfile.fallback_source, "tier_c_selected_day_to_now");
assertClose(tierCProfile.fallback_load_kw, 3);
assert.equal(buildNormalLoadProfile(
  [{ timestamp: "2026-10-02T23:00:00+02:00", import_kw: 99 }],
  new Date("2026-10-02T12:00:00+02:00"),
  { siteId: "site-a", historySiteId: "site-a", now: new Date("2026-10-03T12:00:00+02:00") },
).available, false);

const costPeriods = [
  { start: "2026-10-03T10:00:00+02:00", end: "2026-10-03T11:00:00+02:00" },
  { start: "2026-10-03T11:00:00+02:00", end: "2026-10-03T12:00:00+02:00" },
];
const costProfile = { available: true, samples: { 40: 2, 44: 2 }, observation_counts: { 40: 7, 44: 7 } };
const costModel = buildCostFieldModel(costPeriods, [10, 100], costProfile, 10);
assert.equal(costModel.available, true);
assertClose(costModel.entries[0].expected_cost_rate_sek_per_hour, 0.2);
assertClose(costModel.entries[1].expected_cost_rate_sek_per_hour, 2);
assert.equal(costModel.entries[0].price_sek_per_kwh, 0.1);
assert.equal(buildCostFieldModel([costPeriods[0]], [0], costProfile, 10).entries[0].price_sek_per_kwh, 0);
const neutralField = buildCostFieldMarkup(costPeriods, [10], { available: false }, 10, { left: 10, top: 5 }, 100, 100, (timestamp) => timestamp);
assert.match(neutralField.markup, /insufficient_history/);
const fallbackField = buildCostFieldMarkup(costPeriods, [10, 100], tierBProfile, 10, { left: 10, top: 5 }, 100, 100, (timestamp) => new Date(timestamp).getTime());
assert.match(fallbackField.markup, /data-cost-field-status="fallback"/);
const costField = buildCostFieldMarkup(costPeriods, [10, 100], costProfile, 10, { left: 10, top: 5 }, 100, 100, (timestamp) => new Date(timestamp).getTime());
assert.match(costField.markup, /data-cost-field="available"/);
assert.match(costField.markup, /stop-color="#22C55E"/);
assert.match(costField.markup, /stop-color="#FBBF24"/);
assert.match(costField.markup, /stop-color="#EF4444"/);
assert.match(costField.markup, /offset="11(?:\.[0-9]+)?%"/, "expensive periods must move the green threshold down");
const zeroPriceField = buildCostFieldMarkup([costPeriods[0]], [0], costProfile, 10, { left: 10, top: 5 }, 100, 100, (timestamp) => new Date(timestamp).getTime());
assert.equal((zeroPriceField.markup.match(/stop-color="#22C55E"/g) || []).length, 2);

const hourly = buildPriceChartGeometry(960, 350, { containerWidth: 960, rightAxisGutter: 0 });
const hourStart = hourly.plot.left;
const hourEnd = hourly.width - hourly.plot.right;
const hourX = (timestampRatio) => hourStart + timestampRatio * (hourEnd - hourStart);
assert.equal(hourX(0), hourStart);
assert.equal(hourX(1), hourEnd);
assert.equal(hourly.plotLeft, hourly.leftInset);
assert.equal(hourly.plotRight, hourly.contentRight);
assert.equal(hourX(1), hourly.plotRight);
assert.equal(axisCollisionInset(0, 8, 0), 8);
assert.equal(axisCollisionInset(20, 8, 4), 24);
assert.equal(axisCollisionInset(20, 8, 40), 0);
const noRightAxis = buildPriceChartGeometry(960, 350, { leftAxisLabels: ["0 kW"] });
const shortRightAxis = buildPriceChartGeometry(960, 350, { leftAxisLabels: ["0 kW"], rightAxisLabels: ["0"] });
const wideRightAxis = buildPriceChartGeometry(960, 350, { leftAxisLabels: ["0 kW"], rightAxisLabels: ["0 öre/kWh", "100 öre/kWh"] });
assert.equal(noRightAxis.rightInset, 0);
assert.equal(noRightAxis.plotRight, noRightAxis.contentRight);
assert.equal(noRightAxis.plotLeft, noRightAxis.leftInset);
assert.ok(shortRightAxis.plotRight < noRightAxis.plotRight);
assert.ok(wideRightAxis.plotRight < shortRightAxis.plotRight);
const noLeftAxis = buildPriceChartGeometry(960, 350, { contentLeft: 40, contentRight: 920, leftAxisLabels: [], rightAxisLabels: [] });
const shortLeftAxis = buildPriceChartGeometry(960, 350, { contentLeft: 40, contentRight: 920, leftAxisLabels: ["0"], rightAxisLabels: [] });
const wideLeftAxis = buildPriceChartGeometry(960, 350, { contentLeft: 40, contentRight: 920, leftAxisLabels: ["0 kWh"], rightAxisLabels: [] });
assert.equal(noLeftAxis.leftInset, 0);
assert.equal(noLeftAxis.plotLeft, noLeftAxis.contentLeft);
assert.equal(noLeftAxis.plotRight, noLeftAxis.contentRight);
assert.ok(shortLeftAxis.plotLeft > noLeftAxis.plotLeft);
assert.ok(wideLeftAxis.plotLeft > shortLeftAxis.plotLeft);
assert.equal(shortLeftAxis.plotRight, shortLeftAxis.contentRight);
const shortRightOnly = buildPriceChartGeometry(960, 350, {
  contentLeft: 40,
  contentRight: 920,
  leftAxisLabels: [],
  rightAxisLabels: ["0"],
});
const wideRightOnly = buildPriceChartGeometry(960, 350, {
  contentLeft: 40,
  contentRight: 920,
  leftAxisLabels: [],
  rightAxisLabels: ["0 öre/kWh", "100 öre/kWh"],
});
assert.equal(shortRightOnly.plotLeft, shortRightOnly.contentLeft);
assert.ok(shortRightOnly.plotRight < shortRightOnly.contentRight);
assert.ok(wideRightOnly.plotRight < shortRightOnly.plotRight);
assert.equal(priceAxisGutter([]), 0);
const dayStart = "2026-08-31T00:00:00+02:00";
const dayEnd = "2026-09-01T00:00:00+02:00";
const firstHour = buildHourlyBarEdges("2026-08-31T00:00:00+02:00", "2026-08-31T01:00:00+02:00", dayStart, dayEnd, 100, 900);
const lastHour = buildHourlyBarEdges("2026-08-31T23:00:00+02:00", "2026-09-01T00:00:00+02:00", dayStart, dayEnd, 100, 900);
assert.equal(firstHour.left, 100);
assertClose(firstHour.right, 100 + 800 / 24);
assertClose(lastHour.left, 100 + 800 * 23 / 24);
assert.equal(lastHour.right, 900);
const geometryLastHour = buildHourlyBarEdges("2026-08-31T23:00:00+02:00", "2026-09-01T00:00:00+02:00", dayStart, dayEnd, hourly.plotLeft, hourly.plotRight);
assert.equal(geometryLastHour.right, hourly.plotRight);

const dayBands = buildPriceCategoryBands(100, 900, 3);
assert.deepEqual(dayBands.map((band) => Math.round(band.center * 1000) / 1000), [233.333, 500, 766.667]);
assert.ok(dayBands.every((band) => band.start < band.center && band.center < band.end));

const monthBands = buildPriceCategoryBands(100, 900, 2);
assert.equal(monthBands[0].center, 300);
assert.equal(monthBands[1].center, 700);

const yearBands = buildPriceCategoryBands(100, 900, 1);
assert.equal(yearBands[0].center, 500);
assert.notEqual(yearBands[0].center, yearBands[0].start);

const narrowLabels = buildPriceChartGeometry(960, 350, {
  dualAxis: true,
  leftAxisGutter: 48,
  rightAxisGutter: 72,
  containerWidth: 960,
});
const wideRightLabels = buildPriceChartGeometry(960, 350, {
  dualAxis: true,
  leftAxisGutter: 48,
  rightAxisGutter: 120,
  containerWidth: 960,
});
assert.equal(wideRightLabels.rightInset, 120);
assert.equal(wideRightLabels.plotRight, 960 - 120);
assert.ok(wideRightLabels.plotWidth < narrowLabels.plotWidth);

const stepPeriods = [
  { start: "2026-10-03T00:00:00+02:00", end: "2026-10-03T01:00:00+02:00" },
  { start: "2026-10-03T01:00:00+02:00", end: "2026-10-03T02:00:00+02:00" },
  { start: "2026-10-04T00:00:00+02:00", end: "2026-10-04T01:00:00+02:00" },
];
const stepBase = new Date(stepPeriods[0].start).getTime();
const stepSegments = buildPriceStepSegments(
  stepPeriods,
  [10, 20, 30],
  (timestamp) => (timestamp - stepBase) / 3600000,
  (value) => value,
  (value) => value < 15 ? "cheap" : value > 25 ? "expensive" : "normal",
);
assert.deepEqual(stepSegments.map((item) => item.category), ["cheap", "normal", "expensive"]);
assert.match(stepSegments.find((item) => item.category === "normal").path, /M 1 10 L 1 20 M 1 20 L 2 20/);
assert.equal(buildPriceStepAreaPaths(stepPeriods, [10, 20, 30], (timestamp) => (timestamp - stepBase) / 3600000, (value) => value, 0).length, 2);
assert.deepEqual(selectHourlyPricePeriods(stepPeriods, new Date("2026-10-03T12:00:00+02:00")).length, 2);

console.log("price chart geometry tests passed");
