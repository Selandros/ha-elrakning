import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { axisCollisionInset, buildHourlyBarEdges, buildHourlyBoundaryHours, buildPriceCategoryBands, buildPriceChartGeometry, buildPriceStepAreaPaths, buildPriceStepSegments, priceAxisGutter, selectHourlyPricePeriods } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const panelSource = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
assert.match(panelSource, /preserveAspectRatio="none" viewBox="0 0 \$\{width\} \$\{height\}" role="img" aria-label="Elpris/);
assert.match(panelSource, /class="price-step-line \$\{category\}"/);
assert.match(panelSource, /<linearGradient id="price-level-gradient" gradientUnits="userSpaceOnUse" x1="0" y1="\$\{plot\.top \+ plotHeight\}" x2="0" y2="\$\{plot\.top\}">/);
assert.match(panelSource, /stop-color="var\(--el-price-cheap-color\)"/);
assert.match(panelSource, /stop offset="32%" stop-color="#E4B84A"/);
assert.match(panelSource, /stop offset="68%" stop-color="#E4B84A"/);
assert.match(panelSource, /stop offset="100%" stop-color="#F25F67"/);
assert.match(panelSource, /\.price-step-area \{[\s\S]*fill: url\(#price-level-gradient\);/);
assert.match(panelSource, /\.price-step-area \{[\s\S]*fill-opacity: \.28;/);
assert.match(panelSource, /\.price-step-line \{[\s\S]*stroke: url\(#price-level-gradient\);/);
assert.match(panelSource, /\.price-step-line \{[\s\S]*stroke-width: \.8;[\s\S]*opacity: \.32;/);
assert.doesNotMatch(panelSource, /\.price-step-line\.(?:cheap|normal|expensive) \{/);
assert.match(panelSource, /data-price-now-marker/);

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
const assertClose = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} !== ${expected}`);
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
