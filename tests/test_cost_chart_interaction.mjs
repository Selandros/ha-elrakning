import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildCombinedMonthlyCostForecast, buildCostAnalysisSeries, buildCostChartGeometry, buildCostChartTooltipFields, buildCostKpiComparisons, buildCostKpiTotals, buildCostMonthComparison, buildCostPresentationModel, buildCostReferenceComparisons, buildDailyCostSeries, buildDailyCostTooltipFields, buildInvoiceMonthHistory, buildPreviousMonthActual, costHistoryDisplayOrder, invoiceMonthDisplayValue, mergeKnownProviderGridCost, nextCalendarMonth, normalizeInvoiceMonth } from "../custom_components/elrakning/frontend/elrakning-panel.js";

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
const partialProvider = mergeKnownProviderGridCost({
  month: "2026-10",
  total_so_far_sek: null,
  estimated_total_sek: 0,
  forecast_confidence: "partial_data",
  trade: { total_so_far_sek: null },
  grid: { total_so_far_sek: null, variable_cost_sek: null, fixed_fee_sek: null },
}, {
  imported_kwh_so_far: 28.611,
  grid: { total_so_far_sek: 281.88, variable_cost_sek: 40.63, fixed_fee_sek: 241.25 },
});
const partialProviderHistory = buildInvoiceMonthHistory(partialProvider);
assert.equal(partialProviderHistory[0].coverage, "partial");
assert.equal(partialProviderHistory[0].known_amount_gross_sek, 281.88);
assert.equal(partialProviderHistory[0].variable_actual_sek, 40.63);
assert.equal(partialProviderHistory[0].fixed_monthly_sek, 241.25);
assert.equal(invoiceMonthDisplayValue({ current: true, coverage: "partial", known_amount_gross_sek: 281.88, estimated_total_sek: 0 }), 0);
assert.equal(invoiceMonthDisplayValue({ current: true, coverage: "partial", known_amount_gross_sek: 281.88, estimated_total_sek: null }), 281.88);
assert.equal(invoiceMonthDisplayValue({ current: true, coverage: "partial", known_amount_gross_sek: null, estimated_total_sek: null }), null);
const forecastProviderState = {
  provider: "greenely",
  consumption: { month: "2026-10", month_to_date_kwh: 20 },
  analysis: { consumption_cost: { schema: "greenely.consumption_cost.v1", available: true, month_to_date_cost_sek: 15.67741935483871 } },
};
const forecastPresentation = buildCostPresentationModel({ estimated_grid_month_total_sek: 1178.45, trade: { total_so_far_sek: null }, grid: { total_so_far_sek: 332 } }, forecastProviderState, new Date(2026, 9, 3, 12));
assert.equal(forecastPresentation.trade_forecast_sek, 243);
assert.equal(forecastPresentation.forecast_total_sek, 1421.45);
assert.equal(forecastPresentation.trade_mtd_label, "Estimat hittills");
assert.equal(forecastPresentation.trade_invoice_actual_sek, null);
assert.equal(forecastPresentation.cost_so_far_sek, 347.6774193548387);
assert.equal(forecastPresentation.forecast_remaining_display_sek, 1073.7725806451613);
assert.deepEqual(buildCostKpiTotals(1421.45, 332, 23.55), { cost_so_far_sek: 355.55, forecast_remaining_sek: 1065.9 });
assert.equal(buildCostKpiComparisons({ estimated_month_total_sek: null }, { coverage: "missing" }, [], forecastPresentation)[0].difference_sek, null);
assert.equal(buildCombinedMonthlyCostForecast(null, { estimated_cost_display_sek: 243 }), null);
assert.equal(buildCombinedMonthlyCostForecast(1178.45, null), null);
const forecastHistory = buildInvoiceMonthHistory({ month: "2026-10", total_so_far_sek: null, estimated_month_total_sek: null, trade: { total_so_far_sek: null }, grid: { total_so_far_sek: 326.22138 } }, {}, forecastPresentation);
assert.equal(forecastHistory[0].estimated_total_sek, 1421.45);
assert.equal(invoiceMonthDisplayValue(forecastHistory[0]), 1421.45);
const partialHistoryWithoutForecast = buildInvoiceMonthHistory({ month: "2026-10", total_so_far_sek: null, estimated_month_total_sek: null, trade: { total_so_far_sek: null }, grid: { total_so_far_sek: 326.22138 } });
assert.equal(partialHistoryWithoutForecast[0].estimated_total_sek, null);
assert.equal(invoiceMonthDisplayValue(partialHistoryWithoutForecast[0]), 326.22138);
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
const gridOnlyPartial = buildPreviousMonthActual({
  trade: [],
  grid: [{ month: "Aug 2026", amount_due_sek: 40, vat_included: true, _invoice_key: "grid-only" }],
}, "2026-09");
assert.equal(gridOnlyPartial.coverage, "partial");
assert.equal(gridOnlyPartial.known_amount_gross_sek, 40);
assert.deepEqual(gridOnlyPartial.sources_present, ["elnät"]);
const partialTotalComparison = buildCostReferenceComparisons([
  { month: "2026-09", current: true, coverage: "partial", estimated_total_sek: 240 },
  { month: "2026-08", coverage: "partial", known_amount_gross_sek: 25, source_signature: "SEK:gross_invoice_total", tax_compatible: true },
], "2026-09", null);
assert.equal(partialTotalComparison[0].available, true);
assert.equal(partialTotalComparison[0].difference_sek, 215);
assert.equal(partialTotalComparison[0].partial_baseline, true);
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
const kpiComparisons = buildCostKpiComparisons(
  { estimated_month_total_sek: 240, total_so_far_sek: 120, forecast_remaining_total_sek: 120 },
  { month: "2026-08", coverage: "partial", known_amount_gross_sek: 0 },
);
assert.equal(kpiComparisons[0].available, true);
assert.equal(kpiComparisons[0].difference_sek, 240);
assert.equal(kpiComparisons[0].difference_percent, null);
assert.equal(kpiComparisons[0].partial_baseline, true);
assert.equal(kpiComparisons[1].available, false);
assert.equal(kpiComparisons[2].available, false);
const percentageKpiComparison = buildCostKpiComparisons(
  { estimated_month_total_sek: 240, total_so_far_sek: 120, forecast_remaining_total_sek: 120 },
  { month: "2026-08", coverage: "complete", total_sek: 200 },
);
assert.equal(percentageKpiComparison[0].difference_sek, 40);
assert.equal(percentageKpiComparison[0].difference_percent, 20);
const checkpointComparisons = buildCostKpiComparisons(
  { estimated_month_total_sek: 240, total_so_far_sek: 120, forecast_remaining_total_sek: 120 },
  { month: "2026-08", coverage: "complete", total_sek: 200 },
  [{ kind: "previous_month_same_local_time", cost_to_date_sek: 80, causal: true }],
);
assert.equal(checkpointComparisons[1].available, true);
assert.equal(checkpointComparisons[2].available, true);
assert.equal(checkpointComparisons[2].difference_sek, 0);
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
const componentOnlyComparisons = buildCostReferenceComparisons([
  { month: "2026-09", current: true, coverage: "partial", estimated_total_sek: 240, comparison_components: { elhandel: { value_sek: 110, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
  { month: "2026-08", coverage: "partial", comparison_components: { elhandel: { value_sek: 80, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
  { month: "2026-07", coverage: "partial", comparison_components: { elhandel: { value_sek: 100, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
  { month: "2026-06", coverage: "partial", comparison_components: { elhandel: { value_sek: 60, basis_key: "elhandel_gross", currency: "SEK", tax_basis_class: "gross" } } },
], "2026-09", null);
assert.equal(componentOnlyComparisons[0].available, false);
assert.equal(componentOnlyComparisons[0].comparison_scope, "current_estimated_month_vs_invoice_total_history");
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
assert.equal("comparison_components" in componentHistory[0], false);
assert.equal("comparison_components" in componentHistory[1], false);
const incompatibleTotal = buildCostReferenceComparisons([
  { month: "2026-09", coverage: "complete", total_sek: 240, source_signature: "SEK:gross_invoice_total", tax_compatible: true },
  { month: "2026-08", coverage: "complete", total_sek: 80, source_signature: "EUR:gross_invoice_total", tax_compatible: true },
], "2026-09", 240);
assert.equal(incompatibleTotal[0].available, false);
const twelveMonths = Array.from({ length: 13 }, (_, index) => ({ month: `202${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`, period_cost_before_credits_sek: 100 + index, vat_included: true }));
assert.equal(buildInvoiceMonthHistory({ month: "2026-09", total_so_far_sek: 10 }, { trade: twelveMonths, grid: [] }).length, 12);
const references = buildCostReferenceComparisons([
  { month: "2026-09", coverage: "partial", total_sek: 100 },
  { month: "2026-08", coverage: "complete", total_sek: 80 },
  { month: "2026-07", coverage: "complete", total_sek: 120 },
  { month: "2026-06", coverage: "partial", total_sek: 200 },
], "2026-09", 100);
assert.equal(references[0].available, true);
assert.equal(references[0].difference_sek, 20);
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

const dailyBars = buildDailyCostSeries([
  { date: "2026-09-01", actual: { import_kwh: 2, elhandel_sek: 1, elnat_variable_sek: 2, total_variable_cost_sek: 3, status: "actual", source: "recorder" } },
  { date: "2026-09-02", actual: { import_kwh: 1, elhandel_sek: 0.5, elnat_variable_sek: 1, total_variable_cost_sek: 1.5, status: "actual", source: "recorder" } },
  { date: "2026-09-03", actual: { import_kwh: 1, elhandel_sek: 0.5, elnat_variable_sek: 1, total_variable_cost_sek: 1.5, status: "actual_to_date", source: "recorder" }, forecast: { import_kwh: 2, total_variable_cost_sek: 3, status: "forecast", source: "monthly_forecast.per_day" } },
  { date: "2026-09-04", forecast: { import_kwh: 4, total_variable_cost_sek: 6, status: "forecast", source: "monthly_forecast.per_day" } },
], "2026-09");
assert.equal(dailyBars.days.length, 30);
assert.deepEqual(dailyBars.days.slice(0, 4).map((day) => day.status), ["actual", "actual", "actual_plus_forecast", "forecast"]);
assert.equal(dailyBars.days[2].import_kwh, 3);
assert.equal(dailyBars.days[2].total_variable_cost_sek, 4.5);
assert.equal(dailyBars.days[3].total_variable_cost_sek, 6);
assert.equal(dailyBars.days[4].status, "unavailable");
assert.equal(dailyBars.days[0].average_price_ore_per_kwh, 150);
assert.deepEqual(buildDailyCostTooltipFields(dailyBars.days[2]).map((field) => field.label), ["Import", "Handel", "Nät", "Snittpris"]);
assert.deepEqual(buildDailyCostTooltipFields(dailyBars.days[2]).map((field) => field.value), ["3,00 kWh", "0,50", "1,00", "150,00 öre/kWh"]);
assert.deepEqual(buildDailyCostTooltipFields({ import_kwh: null, elhandel_sek: undefined, elnat_variable_sek: NaN, total_variable_cost_sek: null, average_price_ore_per_kwh: Infinity, status: "unavailable" }).map((field) => field.value), ["–", "–", "–", "–"]);
const unavailableMonth = buildDailyCostSeries([], "2026-08");
assert.equal(unavailableMonth.days.length, 31);
assert.equal(unavailableMonth.days.every((day) => day.status === "unavailable" && !day.available), true);

const greenelyProviderState = {
  provider: "greenely",
  analysis: {
    consumption_cost: {
      schema: "greenely.consumption_cost.v1",
      available: true,
      samples: [
        { localtime: "2026-10-01 19:00", cost_sek: 0.84047 },
        { localtime: "2026-10-01 20:00", cost_sek: 6.58818 },
      ],
    },
  },
};
const providerDailyBars = buildDailyCostSeries([
  { date: "2026-10-01", actual: { import_kwh: 13.508, elnat_variable_sek: 19.18136, total_variable_cost_sek: 19.18136, status: "actual", source: "reconciled_grid_import" } },
], "2026-10", greenelyProviderState);
assert.equal(providerDailyBars.days[0].status, "actual_plus_provider_estimate");
assert.equal(providerDailyBars.days[0].actual.elhandel_sek, undefined);
assert.equal(providerDailyBars.days[0].provenance.provider_trade, "greenely_provider_analysis_estimate");
assert.ok(Math.abs(providerDailyBars.days[0].elhandel_sek - 7.42865) < 1e-9);
assert.ok(Math.abs(providerDailyBars.days[0].total_variable_cost_sek - 26.61001) < 1e-9);
assert.ok(Math.abs(providerDailyBars.days[0].average_price_ore_per_kwh - 196.994447735) < 1e-6);
assert.equal(buildDailyCostTooltipFields(providerDailyBars.days[0])[1].value, "7,43");
assert.equal(buildDailyCostTooltipFields(providerDailyBars.days[0])[2].value, "19,18");
const missingGreenelyCost = buildDailyCostSeries([
  { date: "2026-10-01", actual: { import_kwh: 13.508, elnat_variable_sek: 19.18136, total_variable_cost_sek: 19.18136, status: "actual" } },
], "2026-10", { provider: "greenely", analysis: { consumption_cost: { schema: "greenely.consumption_cost.v1", available: false, samples: [] } } });
assert.equal(missingGreenelyCost.days[0].elhandel_sek, null);
assert.equal(missingGreenelyCost.days[0].total_variable_cost_sek, 19.18136);

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const costRender = source.slice(source.indexOf("  _renderCostChart(chart, series)"), source.indexOf("  _bindCostCard()"));

assert.match(costRender, /buildDailyCostTooltipFields\(point\)/);
assert.match(costRender, /if \(!point \|\| !point\.available\) \{/);
assert.doesNotMatch(costRender, /!series\.days\.some\(\(day\) => day\.available\)/);
assert.doesNotMatch(costRender, /cost-chart-legend|Faktiskt|Prognos|Faktiskt \+ handelsestimat/);
assert.match(costRender, /series\.days\.filter\(\(day\) => day\.available\)\.map/);
assert.match(costRender, /class="cost-chart-bar cost-chart-bar-actual"/);
assert.doesNotMatch(costRender, /cost-chart-bar-(forecast|mixed)/);
assert.doesNotMatch(costRender, /cost-chart-bar-unavailable/);
assert.doesNotMatch(costRender, /point\.status === "forecast"/);
assert.match(costRender, /const total = Number\.isFinite\(point\.total_variable_cost_sek\)/);
assert.match(costRender, /title: `\$\{point\.day\} \$\{this\._formatInvoiceMonth\(series\.month \|\| ""\)\.split\(" "\)\[0\]\} - \$\{total\}kr`/);
assert.match(costRender, /fill="var\(--el-solar-color, #77C2A1\)"/);
assert.match(source, /\.cost-chart-bar-actual \{ fill: var\(--el-solar-color, #77C2A1\);/);
assert.doesNotMatch(source, /\.cost-chart-(estimated|forecast|previous|legend-estimated|legend-forecast|legend-previous|bar-forecast|bar-mixed|bar-unavailable)\s*\{/);
assert.doesNotMatch(source, /\.cost-chart-legend/);
const costHistorySectionMarkup = source.slice(source.indexOf('<section class="cost-history-section"'), source.indexOf('</section>', source.indexOf('<section class="cost-history-section"')));
assert.match(costHistorySectionMarkup, /aria-label="Månads kostnadshistorik"/);
assert.match(costHistorySectionMarkup, /data-cost-status hidden aria-hidden="true"/);
assert.doesNotMatch(costHistorySectionMarkup, /Månadskostnad senaste 12 månaderna|känd kostnad av/);
assert.match(source, /\.cost-main-grid \{ align-items: stretch;/);
assert.match(source, /\.cost-chart \{[\s\S]*display: flex;[\s\S]*min-height: 144px;/);
assert.match(source, /\.cost-chart-svg \{[\s\S]*height: 100%;[\s\S]*min-height: 144px;/);
assert.match(source, /\.cost-chart-plot \{[\s\S]*flex: 1;[\s\S]*min-height: 144px;/);
assert.match(costRender, /var\(--el-solar-color, #77C2A1\)/);
assert.match(costRender, /Daglig rörlig kostnad över vald månad/);
assert.match(costRender, /buildCostChartGeometry\(width, plotWithAxisGutter, series\.days_in_month\)/);
assert.match(costRender, /measuredPriceAxisGutter\(chart, axisLabels, 24\)/);
assert.match(costRender, /axisGutter \+ initialBarWidth \/ 2/);
assert.match(costRender, /plotWithAxisGutter/);
assert.match(costRender, /--cost-axis-left-gutter/);
assert.match(source, /\.cost-chart-plot \{[\s\S]*--cost-axis-left-gutter: 48px;/);
assert.match(source, /\.chart-axis-overlay-y-left \{[\s\S]*width: var\(--cost-axis-left-gutter, 48px\)/);
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
assert.match(source, /\.cost-details \{[\s\S]*display: grid;[\s\S]*margin-top: 12px;/);
assert.match(source, /\.cost-detail-row \{[\s\S]*grid-template-columns: minmax\(68px, auto\) repeat\(3, minmax\(0, 1fr\)\);/);
assert.match(source, /\.cost-detail-row-short \{[\s\S]*grid-template-columns: minmax\(68px, auto\) repeat\(2, minmax\(0, 1fr\)\);/);
assert.match(source, /\.cost-detail strong \{ font-weight: 500; white-space: nowrap; \}/);
assert.match(source, /row\.className = `cost-detail-row\$\{cells\.length === 2 \? " cost-detail-row-short" : ""\}`/);
assert.match(source, /cells\.length === 2 \? " cost-detail-row-short"/);
assert.match(source, /@container \(max-width: 600px\) \{[\s\S]*\.cost-detail-row \{ grid-template-columns: minmax\(60px, auto\) repeat\(2, minmax\(0, 1fr\)\); \}/);
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
assert.match(source, /cost-history-bar-item\.selected \.cost-history-bar \{ box-shadow: 0 0 0 1px color-mix\(/);
assert.match(source, /cost-history-bar-value/);
assert.match(source, /amount\.textContent = hasValue \? this\._formatSek\(value\) : "–"/);
assert.match(source, /itemElement\.append\(label, bar, amount\)/);
assert.match(source, /const hasValue = item\.coverage !== "missing" && Number\.isFinite\(value\)/);
assert.match(source, /const valueForItem = invoiceMonthDisplayValue/);
assert.match(source, /export function invoiceMonthDisplayValue/);
assert.match(source, /item\.estimated_total_sek, item\.known_amount_gross_sek/);
assert.match(source, /cost-history-bar-item\.estimated/);
assert.match(source, /\.cost-history-bar \{ align-self: center;[\s\S]*background: var\(--el-solar-color, #77C2A1\);/);
assert.match(source, /\.cost-history-bar \{ align-self: center;[\s\S]*max-width: 50px;[\s\S]*width: 100%; \}/);
assert.match(source, /\.cost-history-bar-item\.estimated \.cost-history-bar \{ border: 1px dashed var\(--el-solar-color, #77C2A1\);/);
assert.match(source, /\.cost-history-bar-item\.partial \.cost-history-bar \{ border: 1px dashed var\(--el-solar-color, #77C2A1\);/);
assert.match(source, /Beräknad månadskostnad/);
assert.match(source, /<div class="card-heading cost-card-heading"><h2 id="cost-title">Kostnad<\/h2><\/div>/);
assert.doesNotMatch(source, /data-cost-period|cost-subtitle|Översikt över kostnad, prognos och fakturahistorik/);
const costKpiRender = source.slice(source.indexOf("const currentRows ="), source.indexOf("const series =", source.indexOf("const currentRows =")));
assert.equal((costKpiRender.match(/\["(?:Beräknad månadskostnad|Kostnad hittills|Beräknat återstående)"/g) || []).length, 3);
assert.match(source, /const currentRows = \[/);
assert.match(source, /\["Beräknad månadskostnad", showingCurrent \? presentationModel\?\.forecast_total_sek/);
assert.match(source, /\["Kostnad hittills", showingCurrent \? presentationModel\?\.cost_so_far_sek/);
assert.match(source, /\["Beräknat återstående", showingCurrent \? presentationModel\?\.forecast_remaining_display_sek/);
assert.match(source, /const kpiTotals = buildCostKpiTotals\(base\?\.forecast_total_sek, estimate\.grid\?\.total_so_far_sek, base\?\.trade_mtd_sek\)/);
assert.doesNotMatch(costKpiRender, /cost-kpi-secondary/);
assert.doesNotMatch(source, /Prognos för hela innevarande månaden|Från månadens början till nu|Prognos från nu till månadens slut/);
assert.match(source, /cost-history-bar-item\.estimated/);
assert.doesNotMatch(costKpiRender, /Mot förra månaden/);
assert.doesNotMatch(source, /cost-detail-secondary/);
assert.match(source, /\["Nät", \[[\s\S]*\["Hittills", estimate\.grid\?\.total_so_far_sek\][\s\S]*\["Fast", networkFixed\][\s\S]*\["Rörlig", networkVariable\]/);
assert.match(source, /\["Handel", \[[\s\S]*\[presentationModel\?\.trade_mtd_label \|\| "Hittills", providerMonthToDateCost\][\s\S]*\["Fast", null\][\s\S]*\["Rörlig", null\]/);
assert.match(source, /\["Import", \[[\s\S]*\["Hittills", importSoFar\][\s\S]*\["Nät prognos", networkImportForecast\][\s\S]*\["Handel prognos", tradeImportForecast\]/);
assert.match(source, /\["Prognos", \[[\s\S]*\["Nät", networkForecast\][\s\S]*\["Handel", tradeCostForecast\]/);
assert.match(source, /providerMonthToDateCost = presentationModel\?\.trade_mtd_sek/);
assert.match(source, /hasProviderTradeEstimate/);
assert.match(source, /buildCostPresentationModel\(estimate, this\._electricityProviderState, new Date\(\)\)/);
assert.match(source, /value == null[\s\S]*?"–"/);
assert.match(source, /\["Elnät", selectedRecord\.grid_sek == null \? "Saknas"/);
assert.match(source, /\["Total", selectedRecord\.total_sek\]/);
assert.match(source, /\.cost-kpis \{[\s\S]*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);/);
assert.match(source, /\.cost-kpi \{[\s\S]*background: var\(--ha-card-background,[\s\S]*border: 1px solid var\(--divider-color\);[\s\S]*border-radius: var\(--ha-card-border-radius/);
assert.match(source, /\.cost-kpis \{ gap: 8px; grid-template-columns: 1fr; \}/);
assert.match(source, /cost-kpi-comparison/);
assert.match(source, /\.cost-kpi-value-row \{[\s\S]*display: flex;[\s\S]*gap: 8px;/);
const costKpiComparisonCss = source.match(/\.cost-kpi-comparison \{[^}]*\}/)?.[0] || "";
assert.match(costKpiComparisonCss, /font-size: 1\.2rem;[\s\S]*font-weight: 600;[\s\S]*padding: 0;/);
assert.doesNotMatch(costKpiComparisonCss, /border: 1px solid/);
assert.match(source, /\.cost-kpi-comparison\.up \{[^}]*font-size: 16px;/);
assert.match(source, /\.cost-kpi-comparison\.unavailable \{[^}]*font-size: 16px;/);
assert.match(source, /buildCostKpiComparisons\(estimate, previous/);
assert.match(costKpiRender, /item\.className = "cost-kpi"[\s\S]*valueRow\.className = "cost-kpi-value-row"[\s\S]*valueRow\.append\(output\)[\s\S]*if \(bubble\) valueRow\.append\(bubble\)[\s\S]*item\.append\(name, valueRow\)/);
assert.doesNotMatch(costKpiRender, /item\.append\(name, output, bubble\)/);
assert.match(costKpiRender, /const percent = Number\(comparison\.difference_percent\)/);
assert.doesNotMatch(costKpiRender, /this\._formatSek\(Math\.abs\(comparison\.difference_sek\)\)/);
assert.match(source, /Mot förra månaden/);
assert.match(source, /Mot 3 månaders snitt/);
assert.match(source, /Mot 12 månaders snitt/);
assert.doesNotMatch(source, /comparison\.basis_label/);
assert.doesNotMatch(source, /basis_key: "elhandel_gross"/);
assert.match(source, /cost-main-grid/);
assert.match(source, /\.cost-comparison \{[\s\S]*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);[\s\S]*margin-top: 14px;/);
assert.match(source, /\.cost-comparison \{ grid-template-columns: 1fr; \}/);
assert.match(source, /Ingen daglig serie tillgänglig för vald månad/);
assert.match(source, /buildInvoiceMonthHistory\(estimate/);
assert.match(source, /buildCostReferenceComparisons\(monthHistory, selectedMonth, selectedCost\)/);
const costHistoryMarkup = source.slice(source.indexOf('<section class="cost-history-section"'), source.indexOf('</article>', source.indexOf('<section class="cost-history-section"')));
assert.ok(costHistoryMarkup.indexOf('data-cost-history-chart') < costHistoryMarkup.indexOf('data-cost-comparison'), "history bars must precede comparison cards");

console.log("cost chart interaction and compact layout regression passed");
