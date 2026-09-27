import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildCostAnalysisSeries, buildCostChartGeometry, buildCostChartTooltipFields, buildCostMonthComparison, buildCostReferenceComparisons, buildInvoiceMonthHistory, buildPreviousMonthActual, costHistoryDisplayOrder, nextCalendarMonth, normalizeInvoiceMonth } from "../custom_components/elrakning/frontend/elrakning-panel.js";

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
  trade: [{ month: "Aug 2026", period_cost_before_credits_sek: 100, vat_included: true }],
  grid: [{ month: "Aug 2026", period_cost_before_credits_sek: 60, vat_included: true }],
});
assert.deepEqual(monthHistory.map((item) => item.month), ["2026-09", "2026-08"]);
assert.equal(monthHistory[1].coverage, "complete");
assert.equal(monthHistory[1].total_sek, 160);
assert.equal(buildCostMonthComparison(monthHistory[1], monthHistory[0]).available, false);
assert.equal(buildCostMonthComparison({ month: "2026-08", coverage: "complete", total_sek: 160 }, { month: "2026-07", coverage: "complete", total_sek: 200 }).difference_sek, -40);
const zeroInvoice = buildInvoiceMonthHistory({ month: "2026-09", total_so_far_sek: 10 }, {
  trade: [{ month: "Aug 2026", amount_due_sek: 0, vat_included: true, revision: 1, _invoice_key: "zero-trade" }],
  grid: [{ month: "Aug 2026", amount_due_sek: 0, vat_included: true, revision: 1, _invoice_key: "zero-grid" }],
});
assert.equal(zeroInvoice[1].coverage, "complete");
assert.equal(zeroInvoice[1].total_sek, 0);
assert.deepEqual(costHistoryDisplayOrder(zeroInvoice).map((item) => item.month), ["2026-08", "2026-09"]);
const missingAmount = buildInvoiceMonthHistory({ month: "2026-09", total_so_far_sek: 10 }, {
  trade: [{ month: "Aug 2026", amount_due_sek: null, period_cost_before_credits_sek: null }],
  grid: [],
});
assert.deepEqual(missingAmount.map((item) => item.month), ["2026-09"]);
const revisedInvoice = buildPreviousMonthActual({
  trade: [
    { month: "Aug 2026", amount_due_sek: 25, revision: 1, _invoice_key: "old" },
    { month: "Aug 2026", amount_due_sek: 0, vat_included: true, revision: 2, _invoice_key: "new" },
  ],
  grid: [{ month: "Aug 2026", amount_due_sek: 0, vat_included: true, revision: 1 }],
}, "2026-09");
assert.equal(revisedInvoice.trade.total_sek, 0);
assert.equal(revisedInvoice.total_sek, 0);
const tradeOnlyPartial = buildPreviousMonthActual({
  trade: [{ month: "Aug 2026", amount_due_sek: 25, _invoice_key: "trade-only" }],
  grid: [],
}, "2026-09");
assert.equal(tradeOnlyPartial.coverage, "partial");
assert.equal(tradeOnlyPartial.known_amount_gross_sek, 25);
assert.deepEqual(tradeOnlyPartial.sources_present, ["elhandel"]);
assert.deepEqual(tradeOnlyPartial.sources_missing, ["elnät"]);
const zeroTradePartial = buildPreviousMonthActual({
  trade: [{ month: "Aug 2026", amount_due_sek: 0, _invoice_key: "zero-trade-only" }],
  grid: [],
}, "2026-09");
assert.equal(zeroTradePartial.coverage, "partial");
assert.equal(zeroTradePartial.known_amount_gross_sek, 0);
const noInvoiceActual = buildPreviousMonthActual({ trade: [], grid: [] }, "2026-09");
assert.equal(noInvoiceActual.coverage, "missing");
assert.equal(noInvoiceActual.known_amount_gross_sek, null);
const mixedTaxBasis = buildPreviousMonthActual({
  trade: [{ month: "Aug 2026", amount_due_sek: 10 }],
  grid: [{ month: "Aug 2026", net_amount_sek: 20, vat_rate_percent: 25 }],
}, "2026-09");
assert.equal(mixedTaxBasis.coverage, "partial");
assert.equal(mixedTaxBasis.total_sek, null);
assert.equal(mixedTaxBasis.tax_compatible, false);
const upgraded = buildPreviousMonthActual({
  trade: [{ month: "Aug 2026", amount_due_sek: 10, vat_included: true }],
  grid: [{ month: "Aug 2026", amount_due_sek: 20, vat_included: true }],
}, "2026-09");
assert.equal(upgraded.coverage, "complete");
assert.equal(upgraded.total_sek, 30);
const multiMonthInvoice = buildInvoiceMonthHistory({ month: "2026-09", total_so_far_sek: 10 }, {
  trade: [{ month: "Aug 2026-Sep 2026", amount_due_sek: 100 }],
  grid: [],
});
assert.deepEqual(multiMonthInvoice.map((item) => item.month), ["2026-09"]);
assert.equal(buildCostMonthComparison({ month: "2026-08", coverage: "complete", total_sek: 0 }, { month: "2026-07", coverage: "complete", total_sek: 50 }).difference_sek, -50);
assert.equal(buildCostReferenceComparisons([{ month: "2026-09", coverage: "complete", total_sek: 25 }, { month: "2026-08", coverage: "complete", total_sek: 0 }], "2026-09", 25)[0].available, true);
const estimatedCurrentComparisons = buildCostReferenceComparisons([
  { month: "2026-09", current: true, coverage: "partial", estimated_total_sek: 240, comparison_components: { elhandel: { value_sek: 110, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
  { month: "2026-08", coverage: "complete", total_sek: 200 },
  { month: "2026-07", coverage: "complete", total_sek: 220 },
  { month: "2026-06", coverage: "complete", total_sek: 180 },
], "2026-09", null);
assert.equal(estimatedCurrentComparisons[0].available, true);
assert.equal(estimatedCurrentComparisons[0].difference_sek, 40);
assert.equal(estimatedCurrentComparisons[0].current_value_source, "estimated_month_total_sek");
assert.equal(estimatedCurrentComparisons[1].available, true);
assert.equal(estimatedCurrentComparisons[2].available, true);
const componentFallbackComparisons = buildCostReferenceComparisons([
  { month: "2026-09", current: true, coverage: "partial", estimated_total_sek: 240, comparison_components: { elhandel: { value_sek: 110, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
  { month: "2026-08", coverage: "partial", comparison_components: { elhandel: { value_sek: 80, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
  { month: "2026-07", coverage: "partial", comparison_components: { elhandel: { value_sek: 100, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
  { month: "2026-06", coverage: "partial", comparison_components: { elhandel: { value_sek: 60, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
], "2026-09", null);
assert.equal(componentFallbackComparisons[0].available, true);
assert.equal(componentFallbackComparisons[0].basis_label, "Elhandel");
assert.equal(componentFallbackComparisons[0].difference_sek, 30);
assert.equal(componentFallbackComparisons[1].difference_sek, 30);
assert.equal(componentFallbackComparisons[2].difference_sek, 30);
const componentZeroComparison = buildCostReferenceComparisons([
  { month: "2026-09", current: true, coverage: "partial", estimated_total_sek: 0, comparison_components: { elhandel: { value_sek: 0, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
  { month: "2026-08", coverage: "partial", comparison_components: { elhandel: { value_sek: 0, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
], "2026-09", null);
assert.equal(componentZeroComparison[0].available, true);
assert.equal(componentZeroComparison[0].difference_sek, 0);
assert.equal(componentZeroComparison[0].difference_percent, null);
const componentHistory = buildInvoiceMonthHistory({
  month: "2026-09",
  estimated_month_total_sek: 240,
  forecast_confidence: "partial_data",
  trade: { variable_cost_sek: 50, fixed_fee_sek: 20, total_so_far_sek: 30 },
  forecast_remaining_trade_variable_sek: 40,
}, {
  trade: [{ month: "Aug 2026", amount_due_sek: 80, vat_included: true, currency: "SEK" }],
  grid: [],
});
assert.equal(componentHistory[0].comparison_components.elhandel.value_sek, 110);
assert.equal(componentHistory[1].comparison_components.elhandel.value_sek, 80);
const incompatibleComponent = buildCostReferenceComparisons([
  { month: "2026-09", current: true, coverage: "partial", estimated_total_sek: 240, comparison_components: { elhandel: { value_sek: 110, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
  { month: "2026-08", coverage: "partial", comparison_components: { elhandel: { value_sek: 80, basis_key: "elhandel_gross", currency: "EUR", tax_basis_class: "gross" } } },
], "2026-09", null);
assert.equal(incompatibleComponent[0].available, false);
const twelveMonths = Array.from({ length: 13 }, (_, index) => ({ month: `202${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`, period_cost_before_credits_sek: 100 + index, vat_included: true }));
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
const comparablePartialReferences = buildCostReferenceComparisons([
  { month: "2026-09", coverage: "partial", known_amount_gross_sek: 100, source_signature: "SEK:gross_invoice_total", tax_compatible: true },
  { month: "2026-08", coverage: "partial", known_amount_gross_sek: 80, source_signature: "SEK:gross_invoice_total", tax_compatible: true },
  { month: "2026-07", coverage: "complete", total_sek: 120, source_signature: "SEK:gross_invoice_total", tax_compatible: true },
  { month: "2026-06", coverage: "complete", total_sek: 200, source_signature: "SEK:gross_normalized_from_net_plus_vat", tax_compatible: true },
], "2026-09", 100);
assert.equal(comparablePartialReferences[0].available, true);
assert.equal(comparablePartialReferences[1].sample_count, 2);
assert.equal(comparablePartialReferences[2].sample_count, 2);
assert.deepEqual(costHistoryDisplayOrder([{ month: "2026-09" }, { month: "2026-08" }, { month: "2026-07" }]).map((item) => item.month), ["2026-07", "2026-08", "2026-09"]);

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
assert.match(source, /data-cost-history-chart/);
assert.doesNotMatch(source, /data-cost-history-list|cost-history-month/);
assert.match(source, /const displayHistory = costHistoryDisplayOrder\(monthHistory\)/);
assert.match(source, /historyChart\.replaceChildren\(\.\.\.displayHistory\.map/);
assert.doesNotMatch(source, /data-cost-previous/);
assert.doesNotMatch(source, /data-cost-next/);
assert.match(source, /historyChart.addEventListener\("click"/);
assert.match(source, /itemElement.setAttribute\("aria-selected", String\(item.month === selectedMonth\)\)/);
assert.match(source, /itemElement.dataset.costMonth = item.month/);
assert.match(source, /document.createElement\("button"\)/);
assert.match(source, /cost-history-bar-item\.selected/);
assert.match(source, /cost-history-bar-value/);
assert.match(source, /amount\.textContent = hasValue \? this\._formatSek\(value\) : "–"/);
assert.match(source, /itemElement\.append\(label, bar, amount\)/);
assert.match(source, /const hasValue = item\.coverage !== "missing" && Number\.isFinite\(value\)/);
assert.match(source, /const valueForItem = \(item\) => item\.current/);
assert.match(source, /Number\(item\.estimated_total_sek\)/);
assert.match(source, /cost-history-bar-item\.estimated/);
assert.match(source, /Beräknad månadskostnad/);
assert.match(source, /<div class="card-heading cost-card-heading"><h2 id="cost-title">Kostnad<\/h2><\/div>/);
assert.doesNotMatch(source, /data-cost-period|cost-subtitle|Översikt över kostnad, prognos och fakturahistorik/);
const costKpiRender = source.slice(source.indexOf("const currentRows ="), source.indexOf("status.textContent", source.indexOf("const currentRows =")));
assert.equal((costKpiRender.match(/\["(?:Beräknad månadskostnad|Kostnad hittills|Beräknat återstående)"/g) || []).length, 3);
assert.match(source, /const currentRows = \[/);
assert.match(source, /\["Beräknad månadskostnad", estimate\.estimated_month_total_sek\]/);
assert.match(source, /\["Kostnad hittills", estimate\.total_so_far_sek\]/);
assert.match(source, /\["Beräknat återstående", estimate\.forecast_remaining_total_sek\]/);
assert.doesNotMatch(costKpiRender, /cost-kpi-secondary/);
assert.doesNotMatch(source, /Prognos för hela innevarande månaden|Från månadens början till nu|Prognos från nu till månadens slut/);
assert.match(source, /cost-history-bar-item\.estimated/);
assert.doesNotMatch(costKpiRender, /Mot förra månaden/);
assert.doesNotMatch(source, /cost-detail-secondary/);
assert.match(source, /\["Elhandel", estimate\.trade\?\.total_so_far_sek\]/);
assert.match(source, /\["Import", Number\.isFinite\(Number\(estimate\.imported_kwh_so_far\)\)/);
assert.match(source, /\["Snittpris", Number\.isFinite\(Number\(estimate\.total_weighted_average_ore_per_kwh\)\)/);
assert.match(source, /\["Elnät", selectedRecord\.grid_sek == null \? "Saknas"/);
assert.match(source, /\["Total", selectedRecord\.total_sek\]/);
assert.match(source, /\.cost-kpis \{[\s\S]*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);/);
assert.match(source, /Mot förra månaden/);
assert.match(source, /Mot 3 månaders snitt/);
assert.match(source, /Mot 12 månaders snitt/);
assert.match(source, /comparison\.basis_label \? `\$\{comparison\.label\} · \$\{comparison\.basis_label\}`/);
assert.match(source, /basis_key: "elhandel_gross"/);
assert.match(source, /cost-main-grid/);
assert.match(source, /Ingen daglig serie tillgänglig för vald månad/);
assert.match(source, /buildInvoiceMonthHistory\(estimate/);
assert.match(source, /buildCostReferenceComparisons\(monthHistory, selectedMonth, selectedCost\)/);

console.log("cost chart interaction and compact layout regression passed");
