import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildCostAnalysisSeries, buildCostChartGeometry, buildCostChartTooltipFields, buildCostMonthComparison, buildCostReferenceComparisons, buildInvoiceMonthHistory, nextCalendarMonth, normalizeInvoiceMonth } from "../custom_components/elrakning/frontend/elrakning-panel.js";

assert.equal(nextCalendarMonth("2026-12"), "2027-01");
assert.equal(normalizeInvoiceMonth("Aug 2026"), "2026-08");
assert.equal(normalizeInvoiceMonth("Okt 2025-nov 2025"), null);
const monthHistory = buildInvoiceMonthHistory({
  month: "2026-09",
  total_so_far_sek: 120,
  estimated_month_total_sek: 240,
  forecast_confidence: "partial_data",
  trade: { total_so_far_sek: 70 },
  grid: { total_so_far_sek: 50 },
}, {
  trade: [{ month: "Aug 2026", period_cost_before_credits_sek: 100 }],
  grid: [{ month: "Aug 2026", period_cost_before_credits_sek: 60 }],
});
assert.deepEqual(monthHistory.map((item) => item.month), ["2026-09", "2026-08"]);
assert.equal(monthHistory[1].coverage, "complete");
assert.equal(monthHistory[1].total_sek, 160);
assert.equal(buildCostMonthComparison(monthHistory[1], monthHistory[0]).available, false);
assert.equal(buildCostMonthComparison({ month: "2026-08", coverage: "complete", total_sek: 160 }, { month: "2026-07", coverage: "complete", total_sek: 200 }).difference_sek, -40);
const twelveMonths = Array.from({ length: 13 }, (_, index) => ({ month: `202${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`, period_cost_before_credits_sek: 100 + index }));
assert.equal(buildInvoiceMonthHistory({ month: "2026-09", total_so_far_sek: 10 }, { trade: twelveMonths, grid: [] }).length, 12);
const references = buildCostReferenceComparisons([
  { month: "2026-09", coverage: "partial", total_sek: 100 },
  { month: "2026-08", coverage: "complete", total_sek: 80 },
  { month: "2026-07", coverage: "complete", total_sek: 120 },
  { month: "2026-06", coverage: "partial", total_sek: 200 },
], "2026-09", 100);
assert.equal(references[0].difference_sek, 20);
assert.equal(references[1].available, true);
assert.equal(references[1].sample_count, 2);
assert.equal(references[2].sample_count, 2);

const septemberGeometry = buildCostChartGeometry(960, { left: 48, right: 12 }, 30);
assert.equal(septemberGeometry.x(1), 48);
assert.equal(septemberGeometry.x(30), 948);
assert.equal(septemberGeometry.x(15), 48 + (14 / 29) * 900);
const februaryGeometry = buildCostChartGeometry(960, { left: 48, right: 12 }, 28);
assert.equal(februaryGeometry.x(1), 48);
assert.equal(februaryGeometry.x(28), 948);

assert.deepEqual(buildCostChartTooltipFields({
  actual: 28.05,
  forecast: null,
}), [{ label: "Kostnad hittills", value: 28.05 }]);

assert.deepEqual(buildCostChartTooltipFields({
  estimated: null,
  actual: null,
  forecast: 165.4,
  previous: undefined,
}), [{ label: "Prognos", value: 165.4 }]);

const series = buildCostAnalysisSeries({
  month: "2026-09",
  total_so_far_sek: 28.05,
  estimated_month_total_sek: 307.26,
  rows: [
    { end: "2026-09-03T12:00:00+02:00", trade_cost_sek: 10, grid_cost_sek: 18.05 },
  ],
}, null, new Date("2026-09-03T12:00:00+02:00"));

assert.equal(series.actual.at(-1).value, 28.05);
assert.equal(series.forecast.at(-1).value, 307.26);

const dailySeries = buildCostAnalysisSeries({
  month: "2026-09",
  total_so_far_sek: 60,
  estimated_month_total_sek: 300,
  rows: [
    { end: "2026-09-01T23:45:00+02:00", trade_cost_sek: 10, grid_cost_sek: 0 },
    { end: "2026-09-02T23:45:00+02:00", trade_cost_sek: 20, grid_cost_sek: 0 },
    { end: "2026-09-03T12:00:00+02:00", trade_cost_sek: 30, grid_cost_sek: 0 },
  ],
}, null, new Date("2026-09-03T12:00:00+02:00"));

assert.deepEqual(dailySeries.actual.map((point) => point.day), [1, 2, 3]);
assert.equal(dailySeries.actual.at(-1).value, 60);
assert.equal(dailySeries.forecast[0].day, 3);
assert.equal(dailySeries.forecast.at(-1).day, 30);
assert.equal(dailySeries.forecast.at(-1).value, 300);
assert.ok(dailySeries.forecast.length > 2);
assert.ok(dailySeries.forecast.every((point, index, points) => index === 0 || point.day === points[index - 1].day + 1));
assert.deepEqual(dailySeries.estimated.map((point) => point.day), Array.from({ length: 30 }, (_, index) => index + 1));
assert.equal(dailySeries.estimated.at(-1).value, 300);

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const costRender = source.slice(source.indexOf("  _renderCostChart(chart, series)"), source.indexOf("  _bindCostCard()"));

assert.match(costRender, /buildCostChartTooltipFields\(\{/);
assert.match(costRender, /buildCostChartGeometry\(width, plot, series\.days_in_month\)/);
assert.match(costRender, /getScreenCTM\?\.\(\)/);
assert.match(costRender, /data-cost-axis-day/);
assert.match(costRender, /cost-chart-svg" preserveAspectRatio="none"/);
assert.match(costRender, /tick\.style\.left = `\$\{screenMatrix\.a \* x\(day\)/);
assert.doesNotMatch(costRender, /chart-axis-overlay-x" style="left:/);
assert.match(costRender, /<g class="cost-chart-hover" aria-hidden="true"><\/g>/);
assert.match(costRender, /svg\.addEventListener\("pointerdown", update\)/);
assert.match(costRender, /svg\.addEventListener\("pointermove", update\)/);
assert.match(costRender, /svg\.addEventListener\("pointerleave", clear\)/);
assert.match(costRender, /svg\.addEventListener\("pointercancel", clear\)/);
assert.match(costRender, /chart\.innerHTML =/);
assert.match(source, /\.cost-chart \{[\s\S]*min-height: 144px;/);
assert.match(source, /\.cost-details \{[\s\S]*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);/);
assert.match(source, /@container \(max-width: 600px\) \{[\s\S]*\.cost-details \{ grid-template-columns: repeat\(2, minmax\(0, 1fr\)\); \}/);
assert.match(source, /data-cost-history-list/);
assert.match(source, /data-cost-history-chart/);
assert.match(source, /data-cost-previous/);
assert.match(source, /data-cost-next/);
assert.match(source, /cost-main-grid/);
assert.match(source, /Ingen daglig serie tillgänglig för vald månad/);
assert.match(source, /buildInvoiceMonthHistory\(estimate/);
assert.match(source, /buildCostReferenceComparisons\(monthHistory, selectedMonth, selectedCost\)/);
assert.match(source, /cost-history-month/);

console.log("cost chart interaction and compact layout regression passed");
