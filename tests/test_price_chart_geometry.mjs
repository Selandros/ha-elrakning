import assert from "node:assert/strict";
import { buildPriceCategoryBands, buildPriceChartGeometry } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const hourly = buildPriceChartGeometry(960, 350, { containerWidth: 960 });
const hourStart = hourly.plot.left;
const hourEnd = hourly.width - hourly.plot.right;
const hourX = (timestampRatio) => hourStart + timestampRatio * (hourEnd - hourStart);
assert.equal(hourX(0), hourStart);
assert.equal(hourX(1), hourEnd);

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
assert.equal(wideRightLabels.plotRight, 120);
assert.ok(wideRightLabels.plotWidth < narrowLabels.plotWidth);

console.log("price chart geometry tests passed");
