import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { aggregatePriceAndEnergyByPeriod, aggregatedPriceGroupIndex, buildBatteryDailyHistory, buildCanonicalMeterPoints, buildCanonicalPhasePoints, buildContinuousGapPairs, buildCostAnalysisSeries, buildDailyMaxPhase, buildDailyObservedMaxima, buildEnergyBalance, buildGridSourceCost, buildInvoiceComparison, buildInvoiceEstimate, buildInvoiceProvenance, buildLivePowerProvenance, buildLivePowerTiles, buildLiveSourceEntity, buildMonotoneCubicSegments, buildPhaseChartGeometry, buildPhaseProvenance, buildPreviousMonthActual, buildPriceAnalysisFacts, buildPriceChartGeometry, buildSolarDailyHistory, buildSolarHistoryTooltipFields, buildSolarHistoryTooltipLines, buildThresholdClippedSegments, chartColor, CHART_COLORS, createMeterPowerHistoryState, createPriceDebugText, diagnosticComponent, diagnosticSymbol, displayPowerValue, formatDiagnosticsText, generateUpcomingPriceAnalysis, invoicePeriodLabel, integratePowerHistoryKwh, isPointerInsidePlot, isVisiblePowerValue, mergeDailyPhaseMaxima, mergeMeterPowerHistoryPoint, mergePhaseHistory, nearestMeterPoint, normalizeMeterValue, PHASE_COLOR_MAP, phaseHistoryAvailable, phaseHistoryAxisEnd, phaseHistoryPointCounts, pointerToPlotCoordinates, POWER_DISPLAY_THRESHOLD_KW, priceCategory, priceColorBands, priceColorDetails, previousCalendarMonth, providerLabel, renderPriceAnalysis, renderSharedTooltip, resolveFuseAmpere, sanitizeDebugData, selectPhaseTimeTicks, snapTooltipTimestamp } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const output = formatDiagnosticsText([
  {
    timestamp: "2026-08-22T10:00:00.000Z",
    level: "INFO",
    component: "source",
    event: "source_loading",
    message: "Loading source data",
  },
], "0.0.64");
assert.equal(invoicePeriodLabel({ invoice_date: "2026-08-11", month: "Jul 2026" }), "Jul 2026");
assert.equal(invoicePeriodLabel({ invoice_date: "2026-08-11", month: "Feb 2026-mar 2026" }), "Feb 2026-mar 2026");
assert.equal(invoicePeriodLabel({ invoice_date: "2026-08-11", month: "2026-07" }), "2026-07");
assert.equal(invoicePeriodLabel({ invoice_date: "2026-08-11" }), null);
const aggregatePeriods = [
  { start: "2026-08-30T00:00:00Z", end: "2026-08-30T01:00:00Z", price: 100 },
  { start: "2026-08-30T01:00:00Z", end: "2026-08-30T02:00:00Z", price: 200 },
];
const aggregateMeter = [
  { timestamp: "2026-08-30T00:00:00Z", import_kw: 1, export_kw: 0 },
  { timestamp: "2026-08-30T00:30:00Z", import_kw: 3, export_kw: 0 },
  { timestamp: "2026-08-30T01:00:00Z", import_kw: 3, export_kw: 0 },
  { timestamp: "2026-08-30T01:30:00Z", import_kw: 1, export_kw: 0 },
  { timestamp: "2026-08-30T02:00:00Z", import_kw: 1, export_kw: 0 },
];
const aggregatePower = { solar: { points: [
  { timestamp: "2026-08-30T00:00:00Z", value_kw: 2 },
  { timestamp: "2026-08-30T00:30:00Z", value_kw: 4 },
  { timestamp: "2026-08-30T01:00:00Z", value_kw: 4 },
  { timestamp: "2026-08-30T01:30:00Z", value_kw: 2 },
  { timestamp: "2026-08-30T02:00:00Z", value_kw: 2 },
] } };
const dailyAggregation = aggregatePriceAndEnergyByPeriod(aggregatePeriods, aggregateMeter, aggregatePower, "day", new Date("2026-08-30T12:00:00Z"));
assert.equal(dailyAggregation.length, 1);
assert.equal(dailyAggregation[0].label, "30");
assert.equal(dailyAggregation[0].price, 150);
assert.equal(dailyAggregation[0].energy.import, 4);
assert.equal(dailyAggregation[0].energy.solar, 6);
assert.equal(aggregatePriceAndEnergyByPeriod(aggregatePeriods, aggregateMeter, aggregatePower, "month", new Date("2026-08-30T12:00:00Z"))[0].label, "Aug");
assert.equal(aggregatePriceAndEnergyByPeriod(aggregatePeriods, aggregateMeter, aggregatePower, "year", new Date("2026-08-30T12:00:00Z"))[0].label, "2026");
assert.equal(dailyAggregation[0].price_duration_ms, 2 * 60 * 60 * 1000);
const historicalPeriods = [
  { start: "2026-08-25T00:00:00Z", end: "2026-08-25T01:00:00Z", price: 100 },
  { start: "2026-08-25T01:00:00Z", end: "2026-08-25T02:00:00Z", price: 200 },
  { start: "2026-08-26T00:00:00Z", end: "2026-08-26T01:00:00Z", price: 300 },
  { start: "2026-08-26T01:00:00Z", end: "2026-08-26T02:00:00Z", price: 500 },
];
const historicalDaily = aggregatePriceAndEnergyByPeriod(historicalPeriods, [], {}, "day", new Date("2026-08-25T12:00:00Z"));
assert.deepEqual(historicalDaily.map((item) => [item.label, item.price]), [["25", 150], ["26", 400]]);
assert.equal(aggregatePriceAndEnergyByPeriod(historicalPeriods, [], {}, "month", new Date("2026-08-25T12:00:00Z"))[0].price, 275);
assert.equal(aggregatePriceAndEnergyByPeriod(historicalPeriods, [], {}, "year", new Date("2026-08-25T12:00:00Z"))[0].price, 275);
assert.equal(aggregatedPriceGroupIndex(100, 48, 864, 31), 1);
assert.equal(aggregatedPriceGroupIndex(48, 48, 864, 31), 0);
assert.equal(aggregatedPriceGroupIndex(912, 48, 864, 31), 30);
assert.equal(aggregatedPriceGroupIndex(20, 48, 864, 31), -1);
assert.deepEqual(buildGridSourceCost({
  imported_kwh_so_far: 55.26,
  grid_transfer_ore_per_kwh_gross: 97,
  grid_energy_tax_ore_per_kwh_gross: 45,
  grid_weighted_average_ore_per_kwh: 142,
  grid: { total_so_far_sek: 298.59, accrued_fixed_fee_sek: 226.25, variable_cost_sek: 72.34, fixed_fee_sek: 226.25 },
}, {
  subscription_sek_per_month: 226.25,
  transfer_ore_per_kwh: 97,
  energy_tax_ore_per_kwh: 45,
  variable_grid_ore_per_kwh: 142,
}), {
  total_sek: 298.59,
  fixed_sek: 226.25,
  variable_sek: 72.34,
  imported_kwh: 55.26,
  subscription_sek_per_month: 226.25,
  transfer_ore_per_kwh: 97,
  energy_tax_ore_per_kwh: 45,
  variable_grid_ore_per_kwh: 142,
  source: "canonical_invoice_estimate.grid",
});
assert.deepEqual(buildGridSourceCost(null, { total_sek: 12 }), { total_sek: 12 });
assert.match(readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8"), /data-period-picker/);
assert.match(readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8"), /data-period-picker-mode="hour"[\s\S]*data-period-picker-mode="day"[\s\S]*data-period-picker-mode="month"[\s\S]*data-period-picker-mode="year"/);
const pickerPanelSource = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const pickerSource = pickerPanelSource.slice(pickerPanelSource.indexOf("  _bindPeriodPicker()"), pickerPanelSource.indexOf("  _chartLayerState()"));
assert.match(pickerSource, /renderPriceChart\(\)/);
assert.doesNotMatch(pickerSource, /callWS|selectedMonth/);
assert.match(pickerPanelSource, /data-period-picker-dialog/);
assert.match(pickerPanelSource, /\.period-picker \{[\s\S]*display: flex[\s\S]*align-items: center/);
assert.match(pickerPanelSource, /\.period-picker \{[\s\S]*flex-direction: row-reverse;[\s\S]*flex-wrap: nowrap;[\s\S]*justify-content: flex-end;[\s\S]*position: static;[\s\S]*width: 100%/);
assert.match(pickerPanelSource, /\.period-picker-control \{ order: 2; \}/);
assert.match(pickerPanelSource, /\.period-picker-modes \{ order: 1; \}/);
assert.match(pickerPanelSource, /\.period-picker-control,[\s\S]*\.period-picker-actions \{[\s\S]*flex: 0 1 auto;[\s\S]*white-space: nowrap;/);
assert.match(pickerPanelSource, /\.period-picker \{[\s\S]*gap: clamp\(3px, 1cqw, 8px\);[\s\S]*min-width: 0;/);
assert.match(pickerPanelSource, /\.period-picker-control button,[\s\S]*\.period-picker-modes button \{[\s\S]*padding: clamp\(2px, \.7cqw, 4px\) clamp\(3px, 1\.1cqw, 8px\);/);
assert.match(pickerPanelSource, /\.period-picker-arrow \{[\s\S]*font-size: clamp\(14px, 2\.5cqw, 18px\)/);
assert.match(pickerPanelSource, /\.period-picker-modes button \{ font-size: clamp\(10px, 1\.7cqw, 12px\); \}/);
assert.match(pickerPanelSource, /\.price-section \{[\s\S]*overflow: visible/);
assert.doesNotMatch(pickerPanelSource, /@container price-card \(max-width: 900px\)/);
assert.doesNotMatch(pickerPanelSource, /\.price-section \.period-picker \{[\s\S]*flex-direction: column/);
assert.doesNotMatch(pickerPanelSource, /\.price-section \.period-picker-modes \{[\s\S]*width: 100%/);
assert.match(pickerPanelSource, /\.period-picker-dialog \{[\s\S]*margin: auto;[\s\S]*max-height: calc\(100dvh - 48px\)[\s\S]*max-width: calc\(100vw - 48px\)[\s\S]*overflow-y: auto[\s\S]*width: min\(520px, calc\(100vw - 48px\)/);
const pickerRenderSource = pickerPanelSource.slice(pickerPanelSource.indexOf("  _renderPeriodPicker()"), pickerPanelSource.indexOf("  _bindPeriodPicker()"));
assert.doesNotMatch(pickerPanelSource, /\.period-picker-popover \{[^}]*position: absolute/);
assert.match(pickerRenderSource, /popover\.hidden = true;[\s\S]*dialog\.showModal\(\)[\s\S]*const pickerContent = dialog;/);
assert.doesNotMatch(pickerRenderSource, /mobile \? dialog : popover/);
assert.doesNotMatch(pickerRenderSource, /!mobile && dialog\.open/);
assert.match(pickerSource, /if \(dialog\.open\) \{[\s\S]*dialog\.getBoundingClientRect\(\)/);
assert.match(pickerPanelSource, /\.period-picker-dialog::backdrop \{[\s\S]*background: rgba\(0, 0, 0, \.52\)/);
assert.match(pickerPanelSource, /@media \(max-width: 600px\) \{[\s\S]*\.period-picker-dialog \{[\s\S]*max-height: calc\(100dvh - 48px\)[\s\S]*overflow-y: auto/);
assert.match(pickerPanelSource, /_isMobilePeriodPicker\(\)[\s\S]*matchMedia\("\(max-width: 600px\)"\)/);
assert.match(pickerPanelSource, /@media \(hover: hover\) and \(pointer: fine\) \{[\s\S]*\.period-picker-modes button:hover:not\(\.selected\):not\(\.active\)/);
assert.match(pickerPanelSource, /\.period-picker-modes button:active:not\(\.selected\):not\(\.active\)/);
assert.match(pickerPanelSource, /\.period-picker-dialog button:hover:not\(\.selected\):not\(\.active\)/);
assert.match(pickerPanelSource, /\.period-picker-control button,[\s\S]*\.period-picker-modes button \{[\s\S]*padding: clamp\(2px, \.7cqw, 4px\)/);
assert.match(pickerPanelSource, /\.period-picker-dialog button \{[\s\S]*padding: 4px 8px/);
assert.doesNotMatch(pickerPanelSource, /\.period-picker-actions\s*\{[^}]*gap:\s*clamp/);
assert.doesNotMatch(pickerPanelSource, /@media \(max-width: 600px\) \{[\s\S]*\.price-section \.period-picker button \{[\s\S]*padding: 7px 10px/);
assert.doesNotMatch(pickerPanelSource, /\.price-section \.period-picker button \{[\s\S]*flex: 0 0 auto/);
assert.doesNotMatch(pickerPanelSource, /\.price-section \.period-picker-arrow \{[\s\S]*min-width: 0/);
assert.doesNotMatch(pickerPanelSource, /\.price-section \.period-picker-period \{[\s\S]*min-width: 0[\s\S]*width: auto/);
assert.match(pickerPanelSource, /dialog\.showModal\(\)/);
assert.match(pickerSource, /dialog\.addEventListener\("cancel"/);
assert.match(pickerSource, /dialog\.getBoundingClientRect\(\)/);
assert.match(pickerSource, /event\.clientX < rect\.left[\s\S]*event\.clientY > rect\.bottom/);
assert.match(pickerSource, /event\.preventDefault\(\)[\s\S]*event\.stopPropagation\(\)[\s\S]*close\(\)/);
assert.match(pickerPanelSource, /_updatePeriodPickerDraftSelection\(\)[\s\S]*classList\.toggle\("selected"/);
assert.match(pickerSource, /draftSelectionChanged[\s\S]*_updatePeriodPickerDraftSelection\(\)[\s\S]*return;/);
assert.match(pickerPanelSource, /\.period-picker-day-grid button,[\s\S]*\.period-picker-choice \{[\s\S]*min-height: 36px/);
assert.doesNotMatch(pickerSource, /scrollIntoView\(|positionPicker|setPickerPosition/);
const costSeries = buildCostAnalysisSeries({
  month: "2026-08",
  total_so_far_sek: 356.61,
  estimated_month_total_sek: 686.55,
  rows: [
    { end: "2026-08-01T01:00:00+02:00", trade_cost_sek: 10, grid_cost_sek: 20 },
    { end: "2026-08-15T01:00:00+02:00", trade_cost_sek: 100, grid_cost_sek: 200 },
  ],
}, { cumulative_points: [{ day: 1, value: 10 }, { day: 31, value: 640 }] }, new Date("2026-08-15T12:00:00+02:00"));
assert.equal(costSeries.actual.at(-1).value, 356.61);
assert.equal(costSeries.forecast[0].value, 356.61);
assert.equal(costSeries.forecast.at(-1).value, 686.55);
assert.deepEqual(costSeries.previous, [{ day: 1, value: 10 }, { day: 31, value: 640 }]);
assert.equal(costSeries.method, "cumulative_observed_rows_with_time_allocated_fixed_fee_and_explicit_segments");
assert.equal(costSeries.fixed_fee_allocation_method, "monthly_fixed_fee_accrued_by_elapsed_month_fraction");
assert.equal(buildCostAnalysisSeries({ month: "2026-08", rows: [] }, null, new Date("2026-08-15")).forecast_available, false);
const costEdgeSeries = buildCostAnalysisSeries({
  month: "2026-08",
  total_so_far_sek: 356.704232,
  estimated_month_total_sek: 685.529732,
  forecast_missing_past_kwh: 176.544949,
  trade_weighted_average_ore_per_kwh: 41.565,
  grid_weighted_average_ore_per_kwh: 142,
  trade: { fixed_fee_sek: 39 },
  grid: { fixed_fee_sek: 226.25 },
  rows: [
    { end: "2026-08-24T12:00:00+02:00", trade_cost_sek: 20, grid_cost_sek: 40 },
    { end: "2026-08-08T12:00:00+02:00", trade_cost_sek: 10, grid_cost_sek: 20 },
  ],
}, null, new Date("2026-08-31T12:00:00+02:00"));
assert.equal(costEdgeSeries.actual.some((point) => point.day === 1 && point.value === 0), false);
assert.equal(costEdgeSeries.estimated_past.length, 2);
assert.equal(costEdgeSeries.actual.at(-1).value, 356.704232);
assert.equal(costEdgeSeries.actual_display.at(-1).value > costEdgeSeries.actual.at(-1).value, true);
assert.equal(costEdgeSeries.forecast_future.length, 0);
assert.equal(costEdgeSeries.previous.length, 0);
const eonPanelSource = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
assert.match(eonPanelSource, /data-card-source="price"/);
assert.match(eonPanelSource, /_buildPriceSourceData\(\)/);
assert.match(eonPanelSource, /visible_series/);
assert.match(eonPanelSource, /priceAggregation/);
assert.match(eonPanelSource, /duration_weighted_average/);
assert.match(eonPanelSource, /axes: mode === "hour"/);
assert.match(eonPanelSource, /this\._billingHistory \? \(this\._billingHistory\.price_periods \|\| \[\]\)/);
assert.match(eonPanelSource, /this\._billingHistory \? \(this\._billingHistory\.energy_points \|\| \[\]\)/);
assert.match(eonPanelSource, /billingEnergySource/);
assert.match(eonPanelSource, /selectedPeriod = mode === "hour"[\s\S]*: mode === "day" \? localPeriod\(selected\) : String\(year\)/);
assert.match(eonPanelSource, /displayed_groups/);
assert.match(eonPanelSource, /coverageFor/);
assert.match(eonPanelSource, /data-group-index/);
assert.match(eonPanelSource, /clearGroupHover/);
assert.match(eonPanelSource, /aggregatedPriceGroupIndex/);
assert.doesNotMatch(eonPanelSource, /aggregated-chart-hover-band/);
assert.doesNotMatch(eonPanelSource, /drop-shadow\(/);
assert.doesNotMatch(eonPanelSource, /aggregated-chart-bar\.hovered/);
assert.match(eonPanelSource, /key === "price" \? chartColor\("priceNormal"\)/);
assert.match(eonPanelSource, /_setSoloChartLayer\(layer\)/);
assert.match(eonPanelSource, /_clearSoloChartLayer\(\{ render = true \} = \{\}\)/);
assert.match(eonPanelSource, /this\._clearSoloChartLayer\(\);\n        return;/);
assert.match(eonPanelSource, /window\.setTimeout\(\(\) =>/);
assert.match(eonPanelSource, /longPressTriggered/);
assert.match(eonPanelSource, /button\.dataset\.longPressHandled/);
assert.match(eonPanelSource, /_soloChartLayerSnapshot/);
assert.match(eonPanelSource, /pointercancel/);
assert.match(eonPanelSource, /_effectiveChartLayerState\(\)/);
assert.match(eonPanelSource, /chart-legend-solo-badge/);
assert.match(eonPanelSource, /solo-active/);
assert.match(eonPanelSource, /solo_series: this\._soloChartLayer/);
assert.match(eonPanelSource, /solo_active: Boolean\(this\._soloChartLayer\)/);
assert.match(eonPanelSource, /this\._soloChartLayer === "average" && this\._periodPickerState\.mode !== "hour"/);
assert.match(eonPanelSource, /data-provider-card="elnet"/);
assert.doesNotMatch(eonPanelSource, /Vad har vi för data\?/);
assert.doesNotMatch(eonPanelSource, /data-provider-card="(?:elmatare|solar|battery)"/);
assert.doesNotMatch(eonPanelSource, /data-eon-grid-phase-summary/);
assert.doesNotMatch(eonPanelSource, /Fasbelastning idag/);
assert.match(eonPanelSource, /Max fas idag/);
assert.match(eonPanelSource, /Högsta säkringsandel/);
assert.match(eonPanelSource, /daily_phase_max/);
assert.match(eonPanelSource, /phase_current_source_entities/);
assert.match(eonPanelSource, /mergeDailyPhaseMaxima/);
assert.match(eonPanelSource, /mergePhaseHistory/);
assert.match(eonPanelSource, /createMeterPowerHistoryState/);
assert.match(eonPanelSource, /mergeMeterPowerHistoryPoint/);
assert.match(eonPanelSource, /overflow-anchor: none/);
assert.doesNotMatch(eonPanelSource.slice(eonPanelSource.indexOf("  _renderPhaseHistoryCard()"), eonPanelSource.indexOf("  async loadBillingHistory()")), /scrollIntoView|focus\(/);
assert.doesNotMatch(eonPanelSource.slice(eonPanelSource.indexOf("  _renderPhaseHistoryCard()"), eonPanelSource.indexOf("  async loadBillingHistory()")), /summary\.replaceChildren/);
assert.match(eonPanelSource, /svg\.addEventListener\("pointermove", update\)/);
assert.doesNotMatch(eonPanelSource, /phaseHistoryBound/);
assert.match(eonPanelSource, /buildCanonicalPhasePoints/);
assert.match(eonPanelSource, /pointerToPlotCoordinates/);
assert.match(eonPanelSource, /bucket_size_minutes: 5/);
assert.match(eonPanelSource, /history_cache/);
assert.match(eonPanelSource, /recorder_history/);
assert.match(eonPanelSource, /last_live_merge_at/);
assert.match(eonPanelSource, /data-phase-history-card/);
assert.match(eonPanelSource, /\.phase-history-row \{\n\s+grid-template-columns: 1fr;\n\s+margin-top: 16px;/);
assert.doesNotMatch(eonPanelSource, /\.phase-history-row \{\n\s+grid-template-columns: repeat\(2/);
assert.match(eonPanelSource, /data-phase-metric="current"/);
assert.match(eonPanelSource, /data-phase-metric="voltage"/);
assert.match(eonPanelSource, /data-phase-metric="active_power"/);
assert.match(eonPanelSource, /data-phase-summary/);
assert.match(eonPanelSource, /class="phase-history-heading" aria-label="Faser"[\s\S]*data-phase-history-summary[\s\S]*data-phase-metric="current"/);
assert.match(eonPanelSource, /\.phase-history-heading \{[\s\S]*display: flex;[\s\S]*justify-content: flex-start;[\s\S]*row-gap: 6px;[\s\S]*flex-wrap: wrap;/);
assert.match(eonPanelSource, /\.phase-history-summary \{[\s\S]*display: flex;[\s\S]*margin: 0;/);
assert.match(eonPanelSource, /\.phase-history-summary \{[\s\S]*flex: 0 1 auto;[\s\S]*min-width: 0;/);
assert.match(eonPanelSource, /\.phase-history-metric-selector \{[\s\S]*flex: 0 0 auto;[\s\S]*flex-wrap: nowrap;/);
assert.match(eonPanelSource, /\.phase-history-summary strong \{[\s\S]*font-size: 14px;[\s\S]*line-height: 18px;/);
assert.match(eonPanelSource, /display: inline-flex;[\s\S]*font-size: 14px;[\s\S]*line-height: 18px;/);
assert.match(eonPanelSource, /item\.append\(indicator, phaseLabel, strong\)/);
assert.match(eonPanelSource, /_getPriceChartLiveSignature\(\)/);
assert.match(eonPanelSource, /_getPriceChartLiveSignature\(\) !== this\._priceChartLiveSignature/);
assert.match(eonPanelSource, /slotMs = 5 \* 60 \* 1000/);
assert.match(eonPanelSource, /renderPriceChart\(\{ liveUpdate: true \}\)/);
assert.match(eonPanelSource, /_renderAggregatedPriceChart\(\)/);
assert.match(eonPanelSource, /_renderHourlyPriceChart\(options\)/);
assert.match(eonPanelSource, /price_duration_ms/);
assert.match(eonPanelSource, /data-price-dynamic="lines"/);
assert.match(eonPanelSource, /data-phase-dynamic="lines"/);
assert.match(eonPanelSource, /this\._phaseInteraction = \{/);
assert.doesNotMatch(eonPanelSource, /data-phase-filter=/);
assert.match(eonPanelSource, /togglePhaseSummary/);
assert.match(eonPanelSource, /Välj minst en fas/);
assert.match(eonPanelSource, /phase_history_visible/);
assert.match(eonPanelSource, /phaseColors = PHASE_COLOR_MAP/);
assert.match(eonPanelSource, /color: activePhaseColors\[phase\]/);
assert.match(eonPanelSource, /active_phases:/);
assert.match(eonPanelSource, /phase_color_map: PHASE_COLOR_MAP/);
assert.match(eonPanelSource, /phase_source_entities/);
assert.match(eonPanelSource, /phase-history-time-label/);
assert.match(eonPanelSource, /phase-history-axis-overlay/);
assert.match(eonPanelSource, /nearestCanonicalTimestamp/);
assert.match(eonPanelSource, /pointsAtCanonicalTimestamp/);
assert.match(eonPanelSource, /new Date\(selectedTimestamp\)\.toLocaleString/);
assert.match(eonPanelSource, /phase-history-threshold/);
assert.match(eonPanelSource, /Säkring/);
assert.match(eonPanelSource, /phase-history-zero-line/);
assert.match(eonPanelSource, /buildPhaseProvenance/);
const appendMeterPowerPointSource = eonPanelSource.slice(
  eonPanelSource.indexOf("  _appendMeterPowerPoint(point)"),
  eonPanelSource.indexOf("  _periodCustomerPrice(period)")
);
assert.doesNotMatch(appendMeterPowerPointSource, /_renderInvoiceEstimateCard\(\)/);
const applyMeterStateSource = eonPanelSource.slice(
  eonPanelSource.indexOf("  _applyMeterState(state)"),
  eonPanelSource.indexOf("  _updateLivePhaseMaxima(")
);
assert.doesNotMatch(applyMeterStateSource, /_renderInvoiceEstimateCard\(\)/);
assert.match(eonPanelSource, /state_class/);
assert.match(eonPanelSource, /chartColor\("phaseL1"\)/);
assert.match(eonPanelSource, /chartColor\("phaseL2"\)/);
assert.match(eonPanelSource, /chartColor\("phaseL3"\)/);
assert.match(eonPanelSource, /elrakning\/grid\/state/);
assert.match(eonPanelSource, /data-eon-grid-app-account/);
assert.match(eonPanelSource, /data-eon-grid-app-password/);
assert.doesNotMatch(eonPanelSource, /data-eon-grid-web-connect/);
assert.doesNotMatch(eonPanelSource, /data-eon-grid-web-status/);
assert.doesNotMatch(eonPanelSource, /data-eon-grid-web-account/);
assert.doesNotMatch(eonPanelSource, /data-eon-grid-web-password/);
assert.match(eonPanelSource, /elrakning\/grid\/login/);
assert.match(eonPanelSource, /data-eon-grid-source/);
assert.match(eonPanelSource, /elrakning\/grid\/source_data/);
assert.match(eonPanelSource, /data-grid-provider/);
assert.match(eonPanelSource, /elrakning\/grid\/providers/);
assert.match(eonPanelSource, /_renderGridProviderOptions/);
assert.match(eonPanelSource, /provider\.name/);
assert.doesNotMatch(eonPanelSource, /<option value="eon">E\.ON<\/option>/);
assert.match(eonPanelSource, /Välj elnätsbolag/);
assert.match(eonPanelSource, /Elnätsbolag<select data-grid-provider/);
assert.doesNotMatch(eonPanelSource, /<h3 id="eon-app-title">E\.ON App<\/h3>/);
assert.doesNotMatch(eonPanelSource, /data-eon-grid-common-api-probe/);
assert.doesNotMatch(eonPanelSource, /elrakning\/grid\/common_api_probe/);
assert.doesNotMatch(eonPanelSource, /data-eon-grid-grouped-contracts-probe/);
assert.doesNotMatch(eonPanelSource, /elrakning\/grid\/grouped_contracts_probe/);
assert.doesNotMatch(eonPanelSource, /Testa Common API/);
assert.doesNotMatch(eonPanelSource, /Testa kontrakts-API/);
assert.doesNotMatch(eonPanelSource, /elrakning-eon-handoff-state/);
assert.doesNotMatch(eonPanelSource, /elrakning-eon-handoff-status/);

const handoffServiceSource = readFileSync(new URL("../browser_extension/eon-handoff/service_worker.js", import.meta.url), "utf8");
const handoffBridgeSource = readFileSync(new URL("../browser_extension/eon-handoff/ha_bridge.js", import.meta.url), "utf8");
const handoffContentSource = readFileSync(new URL("../browser_extension/eon-handoff/content.js", import.meta.url), "utf8");
const handoffViewSource = readFileSync(new URL("../custom_components/elrakning/elnat/eon_handoff.py", import.meta.url), "utf8");
const handoffManifest = JSON.parse(readFileSync(new URL("../browser_extension/eon-handoff/manifest.json", import.meta.url), "utf8"));
assert.ok(handoffManifest.permissions.includes("scripting"));
assert.doesNotMatch(handoffServiceSource, /handoff\/pending/);
assert.match(handoffServiceSource, /handoff\/complete/);
assert.match(handoffServiceSource, /credentials: "omit"/);
assert.match(handoffServiceSource, /chrome\.storage\.session/);
assert.doesNotMatch(handoffServiceSource, /handoff\/pending/);
assert.match(handoffServiceSource, /MyEonIDToken/);
assert.match(handoffServiceSource, /MyEonSession/);
assert.match(handoffServiceSource, /handoff_state_stored/);
assert.match(handoffServiceSource, /completionPromise/);
assert.match(handoffBridgeSource, /event\.origin !== location\.origin/);
assert.match(handoffBridgeSource, /ha-handoff-state/);
assert.match(handoffBridgeSource, /elrakning-eon-handoff-status/);
assert.match(handoffBridgeSource, /response\?\.status/);
assert.match(handoffContentSource, /MAX_ATTEMPTS = 8/);
assert.match(handoffContentSource, /pending_missing/);
assert.match(handoffContentSource, /eon-session-missing/);
assert.match(handoffContentSource, /WEB_SESSION_PAGE_PATH = "\/content\/eon-se\/sv_SE\/mitt-e-on"/);
assert.match(handoffServiceSource, /eon_session_validation_failed/);
assert.match(handoffViewSource, /requires_auth = False/);
assert.match(handoffViewSource, /async_complete_web_handoff\(state, cookies\)/);
assert.doesNotMatch(handoffViewSource, /EonHandoffPendingView|handoff\/pending/);
assert.match(eonPanelSource, /data-provider-source-dialog/);
assert.match(eonPanelSource, /data-provider-source-copy/);
assert.match(eonPanelSource, /aria-labelledby="provider-source-dialog-title"/);
assert.match(eonPanelSource, /_showSourceDataDialog\("Source data", "Elmätare"/);
assert.match(eonPanelSource, /_showSourceDataDialog\("Source data", `Faser/);
assert.match(eonPanelSource, /data-live-power-source="invoice"/);
assert.doesNotMatch(eonPanelSource, /data-meter-source-dialog|data-meter-source-close|data-meter-source-text/);
assert.doesNotMatch(eonPanelSource, /_copyText\(JSON\.stringify\(this\._invoiceEstimateRaw/);
const phaseHistoryBinder = eonPanelSource.slice(eonPanelSource.indexOf("  _bindPhaseHistoryCard()"), eonPanelSource.indexOf("  _renderPhaseHistoryCard()"));
assert.doesNotMatch(phaseHistoryBinder, /_copyText/);
assert.match(eonPanelSource, /provider-source-dialog pre \{[\s\S]*user-select: text;/);
assert.doesNotMatch(eonPanelSource, /data-eon-grid-cookie/);
assert.doesNotMatch(eonPanelSource, /data-eon-api-tests/);
assert.doesNotMatch(eonPanelSource, /eon_app_test_login/);
assert.doesNotMatch(eonPanelSource, /eon_web_test_login/);
assert.doesNotMatch(eonPanelSource, /eon_test_comparison/);

assert.match(output, /^Elräkning diagnostics/m);
assert.match(output, /Version: 0\.0\.64/);
assert.match(output, /INFO source source_loading/);
assert.match(output, /Loading source data/);
assert.equal(diagnosticSymbol("INFO"), "✓");
assert.equal(diagnosticSymbol("ERROR"), "✕");
assert.equal(diagnosticComponent("consumption"), "Consumption");
assert.equal(diagnosticComponent("electricity"), "Elhandel");
assert.equal(diagnosticComponent("price"), "Pris");
assert.equal(providerLabel("Greenely", "Kvartsprisavtal"), "Greenely · Kvartsprisavtal");
assert.equal(providerLabel(undefined, "Kvartsprisavtal"), "Kvartsprisavtal");
assert.equal(providerLabel(undefined, undefined), "");
const svg = { getBoundingClientRect: () => ({ left: 10, top: 20, width: 950, height: 300 }) };
const plot = { left: 44, right: 8, top: 12, bottom: 24 };
const insidePointer = pointerToPlotCoordinates(svg, { clientX: 10 + 44 / 960 * 950, clientY: 20 + 12 / 300 * 300 }, plot, 960, 300);
assert.equal(insidePointer.inside, true);
assert.equal(isPointerInsidePlot(svg, { clientX: 10, clientY: 20 }, plot, 960, 300), false);
assert.equal(isPointerInsidePlot(svg, { clientX: 10 + 500 / 960 * 950, clientY: 20 + 150 / 300 * 300 }, plot, 960, 300), true);
assert.equal(chartColor("solar"), CHART_COLORS.solar);
assert.notEqual(CHART_COLORS.solarForecast, CHART_COLORS.solar);
assert.equal(resolveFuseAmpere({ facility: {} }, { facility: { fuse_ampere: 16 } }), 16);
assert.deepEqual(PHASE_COLOR_MAP, { l1: CHART_COLORS.phaseL1, l2: CHART_COLORS.phaseL2, l3: CHART_COLORS.phaseL3 });
assert.match(chartColor("unknown"), /^#[0-9A-F]{6}$/i);
assert.equal(POWER_DISPLAY_THRESHOLD_KW, 0.1);
assert.equal(displayPowerValue(0.1), 0);
assert.equal(displayPowerValue(-0.1), 0);
assert.equal(displayPowerValue(0.11), 0.11);
assert.equal(displayPowerValue("not-a-number"), null);
const phaseMaxima = mergeDailyPhaseMaxima({}, { l1: -12, l2: 7, l3: 9 }, "2026-08-30T12:00:00Z");
assert.deepEqual(phaseMaxima, {
  l1: { ampere: 12, raw_value: -12, timestamp: "2026-08-30T12:00:00.000Z" },
  l2: { ampere: 7, raw_value: 7, timestamp: "2026-08-30T12:00:00.000Z" },
  l3: { ampere: 9, raw_value: 9, timestamp: "2026-08-30T12:00:00.000Z" },
});
const updatedPhaseMaxima = mergeDailyPhaseMaxima(phaseMaxima, { l1: -10, l2: -8, l3: 11 }, "2026-08-30T13:00:00Z");
assert.equal(updatedPhaseMaxima.l1.ampere, 12);
assert.equal(updatedPhaseMaxima.l3.ampere, 11);
const dailyMaxPhase = buildDailyMaxPhase(updatedPhaseMaxima, 16);
assert.deepEqual(dailyMaxPhase, { phase: "l1", ampere: 12, raw_value: -12, timestamp: "2026-08-30T12:00:00.000Z", fuse_ampere: 16, utilization_percent: 75 });
const tiedDailyMaxPhase = buildDailyMaxPhase({ l1: { ampere: 11, timestamp: "2026-08-30T12:00:00.000Z" }, l2: { ampere: 11, timestamp: "2026-08-30T13:00:00.000Z" } }, 16);
assert.equal(tiedDailyMaxPhase.phase, "l1");
const integrationStart = new Date("2026-08-23T00:00:00");
const integrationEnd = new Date("2026-08-24T00:00:00");
const powerPoints = (values) => values.map((value, index) => ({
  timestamp: new Date(integrationStart.getTime() + index * 5 * 60 * 1000).toISOString(),
  value_kw: value,
}));
assert.equal(integratePowerHistoryKwh(powerPoints([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]), integrationStart, integrationEnd, new Date("2026-08-23T01:00:00")), 1);
assert.ok(Math.abs(integratePowerHistoryKwh(powerPoints([5, 5, 5, 5, 5, 5, 5]), integrationStart, integrationEnd, new Date("2026-08-23T00:30:00")) - 2.5) < 1e-12);
assert.ok(Math.abs(integratePowerHistoryKwh(powerPoints([0, 1 / 3, 2 / 3, 1, 4 / 3, 5 / 3, 2, 7 / 3, 8 / 3, 3, 10 / 3, 11 / 3, 4]), integrationStart, integrationEnd, new Date("2026-08-23T01:00:00")) - 2) < 1e-12);
assert.equal(integratePowerHistoryKwh(powerPoints([0.05, 0.05]), integrationStart, integrationEnd, new Date("2026-08-23T00:05:00")), 0.004166666666666667);
const invoiceEstimate = buildInvoiceEstimate(
  [
    { start: "2026-08-01T00:00:00Z", end: "2026-08-01T00:15:00Z", trade_customer_price_ore_per_kwh: 20, spot_price_ex_vat: 0.1, electricity_cost_ex_vat: 0.1, vat: 0.05 },
    { start: "2026-08-01T00:15:00Z", end: "2026-08-01T00:30:00Z", trade_customer_price_ore_per_kwh: 40, spot_price_ex_vat: 0.2, electricity_cost_ex_vat: 0.1, vat: 0.1 },
  ],
  [
    { timestamp: "2026-08-01T00:00:00Z", import_kw: 2 },
    { timestamp: "2026-08-01T00:15:00Z", import_kw: 2 },
    { timestamp: "2026-08-01T00:30:00Z", import_kw: 4 },
  ],
  { variable_total_ore_per_kwh_gross: 100, fixed_monthly_sek: 226.25 },
  null,
  new Date("2026-08-01T00:30:00Z"),
);
assert.ok(Math.abs(invoiceEstimate.imported_kwh_so_far - 1.25) < 1e-12);
assert.ok(Math.abs(invoiceEstimate.trade.variable_cost_sek - 0.4) < 1e-12);
assert.ok(Math.abs(invoiceEstimate.grid.variable_cost_sek - 1.25) < 1e-12);
assert.equal(invoiceEstimate.grid.fixed_fee_sek, 226.25);
assert.equal(invoiceEstimate.trade_weighted_average_ore_per_kwh, 32);
assert.equal(invoiceEstimate.grid_weighted_average_ore_per_kwh, 100);
assert.equal(invoiceEstimate.completeness.export_credit, false);
const incompleteInvoiceEstimate = buildInvoiceEstimate(
  [{ start: "2026-08-01T00:00:00Z", end: "2026-08-01T00:15:00Z" }],
  [{ timestamp: "2026-08-01T00:00:00Z", import_kw: 2 }, { timestamp: "2026-08-01T00:15:00Z", import_kw: 2 }],
  { variable_total_ore_per_kwh_gross: 100, fixed_monthly_sek: 226.25 },
  null,
  new Date("2026-08-01T00:15:00Z"),
);
assert.equal(incompleteInvoiceEstimate.data_coverage.missing_price_periods, 1);
assert.equal(previousCalendarMonth("2026-08"), "2026-07");
assert.equal(previousCalendarMonth("2027-01"), "2026-12");
const previousActual = buildPreviousMonthActual({
  trade: [
    { invoice_date: "2026-08-03", month: "2026-07", amount_due_sek: 127.31 },
    { invoice_date: "2026-08-03", month: "2026-08", amount_due_sek: 99 },
  ],
  grid: [{ invoice_date: "2026-08-14", month: "2026-07", amount_due_sek: 294.32 }],
}, "2026-08");
assert.equal(previousActual.month, "2026-07");
assert.equal(previousActual.coverage, "complete");
assert.equal(previousActual.total_sek, 421.63);
const lowerComparison = buildInvoiceComparison({ estimated_month_total_sek: 368.18 }, previousActual);
assert.equal(lowerComparison.available, true);
assert.ok(Math.abs(lowerComparison.difference_sek + 53.45) < 1e-12);
assert.ok(Math.abs(lowerComparison.difference_percent + 12.6766) < 0.01);
assert.ok(lowerComparison.fill_percent < 100);
assert.equal(lowerComparison.previous_marker_percent, 100);
const higherComparison = buildInvoiceComparison({ estimated_month_total_sek: 493.73 }, previousActual);
assert.ok(Math.abs(higherComparison.difference_sek - 72.1) < 1e-12);
assert.ok(higherComparison.fill_percent > higherComparison.previous_marker_percent);
const equalComparison = buildInvoiceComparison({ estimated_month_total_sek: 421.63 }, previousActual);
assert.equal(equalComparison.difference_sek, 0);
assert.equal(equalComparison.difference_percent, 0);
const partialActual = buildPreviousMonthActual({ trade: [{ month: "2026-07", amount_due_sek: 127.31 }], grid: [] }, "2026-08");
assert.equal(buildInvoiceComparison({ estimated_month_total_sek: 368.18 }, partialActual).available, false);
const creditedActual = buildPreviousMonthActual({ trade: [{ month: "2026-07", billing_period: "2026-07", period_cost_before_credits_sek: 312.45, credits_applied_sek: 312.45, amount_due_sek: 0, source: "synthetic_trade_invoice" }], grid: [] }, "2026-08");
assert.equal(creditedActual.trade.available, true);
assert.equal(creditedActual.trade.invoice_exists, true);
assert.equal(creditedActual.trade.total_sek, 312.45);
assert.equal(creditedActual.trade.period_cost_before_credits_sek, 312.45);
assert.equal(creditedActual.trade.credits_applied_sek, 312.45);
assert.equal(creditedActual.trade.amount_due_sek, 0);
assert.equal(creditedActual.trade.comparison_value_sek, 312.45);
assert.equal(creditedActual.trade.invoices[0].amount_due_sek, 0);
assert.equal(creditedActual.trade.invoices[0].comparison_value_sek, 312.45);
assert.equal(creditedActual.grid.available, false);
assert.equal(creditedActual.grid.total_sek, null);
assert.equal(creditedActual.grid.reason, "no_previous_invoice");
assert.equal(creditedActual.coverage, "partial");
assert.equal(creditedActual.comparison.reason, "previous_grid_invoice_missing");
const creditedComparison = buildInvoiceComparison({ estimated_month_total_sek: 368.18 }, creditedActual);
assert.equal(creditedComparison.available, false);
assert.equal(creditedComparison.coverage, "partial");
assert.equal(creditedComparison.reason, "previous_grid_invoice_missing");
assert.equal(buildPreviousMonthActual({ trade: [{ invoice_date: "2026-08-03", amount_due_sek: 127.31 }], grid: [] }, "2026-08").coverage, "missing");
const invoiceProvenance = buildInvoiceProvenance(invoiceEstimate, {
  entity_id: "sensor.synthetic_grid_power",
  energy_points: [{ timestamp: "2026-08-01T00:00:00Z", import_kw: 2 }],
  integration_method: "trapezoidal_power_integration",
  grid_price: {
    transfer_ore_per_kwh_gross: 97,
    energy_tax_ore_per_kwh_gross: 45,
    vat_included: true,
    source: "grid_contract",
  },
  trade_vat_included: false,
});
assert.equal(invoiceProvenance.energy_source.method, "integrated_grid_power");
assert.equal(invoiceProvenance.energy_source.sample_count, 1);
assert.equal(invoiceProvenance.energy_source.integration_method, "trapezoidal_power_integration");
assert.equal(invoiceProvenance.energy_source.source_entities[0].entity_id, "sensor.synthetic_grid_power");
assert.equal(invoiceProvenance.grid_variable.transfer_ore_per_kwh_gross, 97);
assert.equal(invoiceProvenance.grid_variable.energy_tax_ore_per_kwh_gross, 45);
assert.equal(invoiceProvenance.grid_variable.vat_included, true);
assert.equal(invoiceProvenance.fixed_fees.applied_once, true);
assert.equal(invoiceProvenance.energy_source.source_entity, "sensor.synthetic_grid_power");
assert.equal(buildInvoiceProvenance(invoiceEstimate, { entity_id: "sensor.synthetic_grid_power" }).energy_source.source_entities[0].entity_id, "sensor.synthetic_grid_power");
assert.equal(invoiceProvenance.vat_audit.spot.source_is_ex_vat, true);
assert.equal(invoiceProvenance.vat_audit.trade_variable.source_is_ex_vat, true);
assert.equal(invoiceProvenance.vat_audit.trade_variable.vat_component_present, true);
assert.equal(invoiceProvenance.actual_so_far.imported_kwh, invoiceEstimate.imported_kwh_so_far);
assert.equal(invoiceProvenance.forecast_remaining.method, invoiceEstimate.forecast_method);
assert.equal(invoiceProvenance.calculation.estimated_total_sek, invoiceEstimate.estimated_month_total_sek);
const calculation = invoiceProvenance.calculation;
const calculatedTotal = [
  calculation.trade_variable_actual_sek,
  calculation.trade_variable_forecast_remaining_sek,
  calculation.grid_transfer_actual_sek,
  calculation.grid_transfer_forecast_remaining_sek,
  calculation.grid_energy_tax_actual_sek,
  calculation.grid_energy_tax_forecast_remaining_sek,
  calculation.trade_fixed_sek,
  calculation.grid_fixed_sek,
].reduce((sum, value) => sum + (value || 0), 0);
assert.ok(Math.abs(calculatedTotal - calculation.estimated_total_sek) < 1e-9);
assert.equal(invoiceProvenance.vat_audit.grid_transfer.vat_added_by_us, false);
assert.equal(invoiceProvenance.fixed_fees.trade.source, null);
const fixedInvoiceEstimate = buildInvoiceEstimate(
  [{ start: "2026-08-01T00:00:00Z", end: "2026-08-01T00:15:00Z", trade_customer_price_ore_per_kwh: 20 }],
  [{ timestamp: "2026-08-01T00:00:00Z", import_kw: 2 }, { timestamp: "2026-08-01T00:15:00Z", import_kw: 2 }],
  { variable_total_ore_per_kwh_gross: 100, fixed_monthly_sek: 226.25 },
  39,
  new Date("2026-08-01T00:15:00Z"),
);
const fixedInvoiceProvenance = buildInvoiceProvenance(fixedInvoiceEstimate, { grid_price: { variable_total_ore_per_kwh_gross: 100, fixed_monthly_sek: 226.25, transfer_ore_per_kwh_gross: 55, energy_tax_ore_per_kwh_gross: 45, vat_included: true } });
assert.equal(fixedInvoiceProvenance.fixed_fees.trade.source, "provider_summary.tariff.fixed_fee_incl_vat_per_month");
assert.ok(Math.abs(fixedInvoiceProvenance.calculation.component_sum_sek - fixedInvoiceEstimate.estimated_month_total_sek) < 1e-9);
const coveredDurationEstimate = buildInvoiceEstimate(
  [{ start: "2026-08-23T00:00:00Z", end: "2026-08-24T00:00:00Z", trade_customer_price_ore_per_kwh: 20 }],
  Array.from({ length: 289 }, (_, index) => ({ timestamp: new Date(Date.parse("2026-08-23T00:00:00Z") + index * 5 * 60 * 1000).toISOString(), import_kw: 2 })),
  { variable_total_ore_per_kwh_gross: 100, fixed_monthly_sek: 226.25 },
  null,
  new Date("2026-08-30T00:00:00Z"),
);
assert.ok(coveredDurationEstimate.data_coverage.coverage_percent > 3);
assert.ok(coveredDurationEstimate.data_coverage.coverage_percent < 4);
assert.ok(coveredDurationEstimate.forecast_missing_past_kwh > 0);
assert.ok(coveredDurationEstimate.forecast_future_kwh > 0);
assert.equal(coveredDurationEstimate.data_coverage.periods.observed_covered.kwh, coveredDurationEstimate.imported_kwh_so_far);
assert.ok(coveredDurationEstimate.data_coverage.periods.missing_past.estimated_kwh > 0);
assert.equal(coveredDurationEstimate.data_coverage.first_period, "2026-08-23T00:00:00.000Z");
const gappedInvoiceEstimate = buildInvoiceEstimate(
  [{ start: "2026-08-01T00:00:00Z", end: "2026-08-01T01:00:00Z", trade_customer_price_ore_per_kwh: 20 }],
  [{ timestamp: "2026-08-01T00:00:00Z", import_kw: 2 }, { timestamp: "2026-08-01T01:00:00Z", import_kw: 2 }],
  { variable_total_ore_per_kwh_gross: 100, fixed_monthly_sek: 226.25 },
  null,
  new Date("2026-08-01T01:00:00Z"),
);
assert.equal(gappedInvoiceEstimate.imported_kwh_so_far, null);
assert.equal(gappedInvoiceEstimate.data_coverage.missing_energy_periods, 1);
const dailyHistoryPoints = (day, value, count) => Array.from({ length: count }, (_, index) => ({
  timestamp: new Date(day.getTime() + index * 5 * 60 * 1000).toISOString(),
  value_kw: value,
}));
const dailyHistory = buildBatteryDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 1, 13),
  dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 2, 7),
  2,
  new Date(2026, 7, 23, 12, 0),
);
const solarHistory = buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 1, 13),
  { "2026-08-22": 10 },
  new Date(2026, 7, 23, 12, 0),
  2,
);
assert.equal(solarHistory.length, 2);
assert.equal(solarHistory[0].forecastKwh, 10);
assert.equal(solarHistory[0].utilizationPercent, 10);
const solarToday = buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 23, 0, 0), 1, 13),
  { "2026-08-23": 14.1 },
  new Date(2026, 7, 23, 12, 0),
  1,
  { today_kwh: 14.1, remaining_today_kwh: 6.5 },
);
assert.equal(solarToday[0].forecastKwh, 14.1);
assert.ok(Math.abs(solarToday[0].utilizationPercent - 1 / 7.6 * 100) < 1e-12);
const solarTodayOverExpected = buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 23, 0, 0), 2, 13),
  { "2026-08-23": 2 },
  new Date(2026, 7, 23, 12, 0),
  1,
  { today_kwh: 2, remaining_today_kwh: 1 },
);
assert.equal(solarTodayOverExpected[0].utilizationPercent, 50);
assert.equal(solarTodayOverExpected[0].performanceDeltaPercent, 100);
const solarTodayMissingRemaining = buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 23, 0, 0), 1, 13),
  { "2026-08-23": 14.1 },
  new Date(2026, 7, 23, 12, 0),
  1,
  { today_kwh: 14.1 },
);
assert.equal(solarTodayMissingRemaining[0].utilizationPercent, null);
const solarTodayPerformance = buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 23, 0, 0), 8.32, 13),
  { "2026-08-23": 16.57 },
  new Date(2026, 7, 23, 12, 0),
  1,
  { today_kwh: 16.57, remaining_today_kwh: 10.39 },
)[0];
assert.ok(Math.abs(solarTodayPerformance.utilizationPercent - 6.18 / 8.32 * 100) < 1e-12);
assert.ok(Math.abs(solarTodayPerformance.performanceDeltaPercent - ((8.32 / 6.18) - 1) * 100) < 1e-12);
assert.equal(buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 23, 0, 0), 1, 13),
  { "2026-08-23": 14.1 },
  new Date(2026, 7, 23, 12, 0),
  1,
  { today_kwh: 14.1, remaining_today_kwh: 14.1 },
)[0].utilizationPercent, null);
const solarAccuracyEqual = buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 10, 13),
  { "2026-08-22": 10 },
  new Date(2026, 7, 23, 12, 0),
  2,
)[0];
assert.equal(solarAccuracyEqual.forecastAccuracyPercent, 100);
assert.equal(solarAccuracyEqual.forecastDeviationPercent, 0);
const solarAccuracyAbove = buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 20, 13),
  { "2026-08-22": 10 },
  new Date(2026, 7, 23, 12, 0),
  2,
)[0];
assert.equal(solarAccuracyAbove.forecastAccuracyPercent, 50);
assert.equal(solarAccuracyAbove.forecastDeviationPercent, 100);
const solarAccuracyBelow = buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 5, 13),
  { "2026-08-22": 10 },
  new Date(2026, 7, 23, 12, 0),
  2,
)[0];
assert.equal(solarAccuracyBelow.forecastAccuracyPercent, 50);
assert.equal(solarAccuracyBelow.forecastDeviationPercent, -50);
assert.equal(solarAccuracyAbove.forecastComparisonBasis, "full_day_forecast");
assert.equal(solarAccuracyAbove.forecastComparisonActualKwh, solarAccuracyAbove.producedKwh);
assert.equal(solarAccuracyAbove.forecastComparisonExpectedKwh, solarAccuracyAbove.forecastKwh);
assert.deepEqual(buildSolarHistoryTooltipLines(
  { date: "2026-08-23", producedKwh: 0.67, forecastKwh: 18.83 },
  { today_kwh: 14.1, remaining_today_kwh: 3.96 },
  new Date(2026, 7, 23, 12, 0),
), ["Producerat: 0.67 kWh", "Prognos hittills: 10.14 kWh", "Dagsprognos: 18.83 kWh"]);
assert.deepEqual(buildSolarHistoryTooltipLines(
  { date: "2026-08-22", producedKwh: 41.19, forecastKwh: 38.7 },
  { today_kwh: 14.1, remaining_today_kwh: 3.96 },
  new Date(2026, 7, 23, 12, 0),
), ["Producerat: 41.19 kWh", "Prognos: 38.7 kWh"]);
assert.deepEqual(buildSolarHistoryTooltipLines(
  { date: "2026-08-23", producedKwh: 0.67, forecastKwh: 18.83 },
  { today_kwh: 14.1 },
  new Date(2026, 7, 23, 12, 0),
), ["Producerat: 0.67 kWh", "Dagsprognos: 18.83 kWh"]);
assert.deepEqual(buildSolarHistoryTooltipLines(
  { date: "2026-08-23", producedKwh: 0.67, forecastKwh: null },
  { today_kwh: 14.1, remaining_today_kwh: 14.1 },
  new Date(2026, 7, 23, 12, 0),
), ["Producerat: 0.67 kWh"]);
const solarTooltipFields = buildSolarHistoryTooltipFields(
  {
    date: "2026-08-23",
    producedKwh: 0.67,
    forecastKwh: 18.83,
    forecastAccuracyPercent: 54.7,
    forecastDeviationPercent: 82.7,
  },
  {
    today_kwh: 14.1, remaining_today_kwh: 3.96, this_hour_kwh: 1.2,
    next_hour_kwh: null, power_now_kw: 1.842, power_next_hour_kw: 2.1,
    peak_time_today: "13:00", tomorrow_kwh: 12.5,
  },
  new Date(2026, 7, 23, 12, 0),
  { source: "smhi", available: true, current: { condition: "partlycloudy", cloud_total: 88, temperature: 20.1 } },
  { elevation: 36.7, azimuth: 181.2, rising: true, daylight: true },
);
assert.ok(solarTooltipFields.some((field) => field.label === "Prognos hittills" && field.rawValue === 10.14));
assert.ok(!solarTooltipFields.some((field) => field.label.startsWith("Forecast") || field.label.startsWith("SMHI") || field.label === "Solhöjd"));
assert.ok(solarTooltipFields.length <= 5);
assert.ok(solarTooltipFields.some((field) => field.label === "Prognosträff hittills" && field.formatted === "54,7 %"));
assert.ok(solarTooltipFields.some((field) => field.label === "Avvikelse" && field.formatted === "+82,7 %"));
const liveTiles = buildLivePowerTiles(
  { consumption_kw: 0.63, solar_kw: 6.94, charging_kw: 0, discharging_kw: 0 },
  { power_kw: 2.43 },
  { house: 2, solar: 10, grid: 5, battery: 4 },
);
assert.equal(liveTiles.house.value, 0.63);
assert.equal(liveTiles.house.status, "Förbrukar");
assert.equal(liveTiles.house.maxToday, 2);
assert.equal(liveTiles.house.fillPercent, 31.5);
assert.equal(liveTiles.solar.value, 6.94);
assert.equal(liveTiles.solar.status, "Producerar");
assert.equal(buildLivePowerTiles({ solar_kw: 0 }, {}).solar.status, "Ingen produktion");
assert.equal(buildLivePowerTiles({ solar_kw: 0 }, {}).solar.colorKey, "neutral");
assert.equal(liveTiles.grid.value, 2.43);
assert.equal(liveTiles.grid.status, "Importerar");
const gridTilesWithPhases = buildLivePowerTiles(
  {},
  { power_kw: 2.85, phase_current_a: { l1: 7.2, l2: 9.8, l3: 8.4 } },
  {},
);
assert.equal(gridTilesWithPhases.grid.maxPhaseCurrentA, 9.8);
assert.equal(gridTilesWithPhases.grid.fuseUtilizationPercent, null);
const gridTilesWithFuse = buildLivePowerTiles(
  {},
  { power_kw: 2.85, phase_current_a: { l1: 7.2, l2: 9.8, l3: 8.4 }, facility: { fuse_ampere: 16 } },
  {},
);
assert.equal(gridTilesWithFuse.grid.fuseAmpere, 16);
assert.ok(Math.abs(gridTilesWithFuse.grid.fuseUtilizationPercent - 61.25) < 1e-12);
const gridTilesWithNegativePhase = buildLivePowerTiles(
  {},
  { power_kw: 0, phase_current_a: { l1: -14, l2: 3, l3: 4 }, facility: { fuse_ampere: 16 } },
  {},
);
assert.equal(gridTilesWithNegativePhase.grid.maxPhaseCurrentA, 14);
assert.equal(gridTilesWithNegativePhase.grid.fuseUtilizationPercent, 87.5);
assert.equal(liveTiles.battery.status, "Ingen aktivitet");
assert.equal(buildLivePowerTiles({ charging_kw: 0, discharging_kw: 0 }, {}).battery.status, "Ingen aktivitet");
assert.equal(liveTiles.battery.fillPercent, 0);
assert.equal(buildLivePowerTiles({}, {}).solar.scaleMax, 1);
assert.equal(buildLivePowerTiles({ solar_kw: 5.24 }, {}).solar.scaleMax, 5.24);
const maxima = buildDailyObservedMaxima({ series: {
  solar: { points: [{ timestamp: "2026-08-30T10:00:00+02:00", value_kw: 4.2 }] },
  consumption: { points: [{ timestamp: "2026-08-30T11:00:00+02:00", value_kw: 2.1 }] },
  charging: { points: [{ timestamp: "2026-08-30T12:00:00+02:00", value_kw: 3.5 }] },
  discharging: { points: [{ timestamp: "2026-08-30T13:00:00+02:00", value_kw: 4.4 }] },
} }, { points: [{ timestamp: "2026-08-30T14:00:00+02:00", import_kw: 5.2, export_kw: 0 }] }, new Date("2026-08-30T15:00:00+02:00"));
assert.deepEqual(maxima, { date: "2026-08-30", house: 2.1, solar: 4.2, grid: 5.2, battery: 4.4 });
assert.equal(buildLivePowerTiles({}, { power_kw: -0.11 }).grid.status, "Exporterar");
assert.equal(buildLivePowerTiles({}, { power_kw: 0.05 }).grid.status, "Ingen överföring");
assert.equal(buildLivePowerTiles({ charging_kw: 6.2, discharging_kw: 0 }).battery.status, "Laddar");
assert.equal(buildLivePowerTiles({ charging_kw: 0, discharging_kw: 3.1 }).battery.status, "Urladdar");
assert.equal(buildLivePowerTiles({ charging_kw: 6.2, discharging_kw: 3.1 }).battery.status, "Inkonsekvent data");
assert.equal(buildLivePowerTiles({ consumption_kw: 1 }, {}).house.colorKey, "consumption");
assert.equal(buildLivePowerTiles({ solar_kw: 1 }, {}).solar.colorKey, "solar");
assert.equal(buildLivePowerTiles({}, { power_kw: 1 }).grid.colorKey, "import");
assert.equal(buildLivePowerTiles({}, { power_kw: -1 }).grid.colorKey, "export");
assert.equal(buildLivePowerTiles({}, { power_kw: 0 }).grid.colorKey, "neutral");
assert.equal(buildLivePowerTiles({ charging_kw: 1 }, {}).battery.colorKey, "charging");
assert.equal(buildLivePowerTiles({ discharging_kw: 1 }, {}).battery.colorKey, "discharging");
assert.equal(buildLivePowerTiles({}, {}).battery.colorKey, "neutral");
const liveEntityStates = {
  "sensor.pv_a": { state: "1200", attributes: { unit_of_measurement: "W", device_class: "power" }, last_updated: "2026-08-30T12:00:00Z" },
  "sensor.pv_b": { state: "0.8", attributes: { unit_of_measurement: "kW", device_class: "power" }, last_updated: "2026-08-30T12:00:00Z" },
  "sensor.house_power": { state: "2400", attributes: { unit_of_measurement: "W", device_class: "power" }, last_updated: "2026-08-30T12:00:00Z" },
  "sensor.grid_power": { state: "-350", attributes: { unit_of_measurement: "W", device_class: "power" }, last_updated: "2026-08-30T12:00:00Z" },
  "sensor.l1": { state: "-8.2", attributes: { unit_of_measurement: "A", device_class: "current" }, last_updated: "2026-08-30T12:00:00Z" },
  "sensor.l2": { state: "6.4", attributes: { unit_of_measurement: "A", device_class: "current" }, last_updated: "2026-08-30T12:00:00Z" },
  "sensor.l3": { state: "7.1", attributes: { unit_of_measurement: "A", device_class: "current" }, last_updated: "2026-08-30T12:00:00Z" },
  "sensor.battery_power": { state: "-900", attributes: { unit_of_measurement: "W", device_class: "power" }, last_updated: "2026-08-30T12:00:00Z" },
};
const provenanceSolar = buildLivePowerProvenance(
  "solar",
  liveTiles.solar,
  { solar_entities: ["sensor.pv_a", "sensor.pv_b"] },
  {},
  {},
  {},
  liveEntityStates,
  { solar: 2 },
);
assert.deepEqual(provenanceSolar.source.entities.map((item) => item.entity_id), ["sensor.pv_a", "sensor.pv_b"]);
assert.deepEqual(provenanceSolar.derivation.inputs_kw, [1.2, 0.8]);
assert.equal(provenanceSolar.derivation.result_kw_from_inputs, 2);
assert.equal(provenanceSolar.derivation.method, "sum_power_entities");
const provenanceHouse = buildLivePowerProvenance("house", liveTiles.house, { consumption_entity: "sensor.house_power" }, {}, {}, {}, liveEntityStates, { house: 2 });
assert.equal(provenanceHouse.source.entities[0].state, "2400");
assert.equal(provenanceHouse.derivation.input_kw, 2.4);
const provenanceHouseWithHistoryPeak = buildLivePowerProvenance(
  "house",
  liveTiles.house,
  { consumption_entity: "sensor.house_power" },
  {},
  {},
  { date: "2026-08-30", series: { consumption: { points: [{ timestamp: "2026-08-30T11:00:00Z", value_kw: 13.633 }] } } },
  {},
  { house: 8.009 },
  new Date("2026-08-30T12:00:00Z"),
);
assert.equal(provenanceHouseWithHistoryPeak.history.history_max_kw, 13.633);
assert.equal(provenanceHouseWithHistoryPeak.history.result_kw, 13.633);
assert.deepEqual(provenanceHouseWithHistoryPeak.history.history_max_point, {
  timestamp: "2026-08-30T11:00:00Z",
  entity_id: "sensor.house_power",
  raw_value: 13.633,
  normalized_kw: 13.633,
});
const provenanceHouseWithLivePeak = buildLivePowerProvenance(
  "house",
  liveTiles.house,
  { consumption_entity: "sensor.house_power" },
  {},
  {},
  { date: "2026-08-30", series: { consumption: { points: [{ timestamp: "2026-08-30T11:00:00Z", value_kw: 7.5 }] } } },
  {},
  { house: 8.009 },
  new Date("2026-08-30T12:00:00Z"),
);
assert.equal(provenanceHouseWithLivePeak.history.result_kw, 8.009);
const provenanceHouseWithoutHistory = buildLivePowerProvenance(
  "house",
  liveTiles.house,
  { consumption_entity: "sensor.house_power" },
  {},
  {},
  { date: "2026-08-29", series: { consumption: { points: [{ timestamp: "2026-08-29T11:00:00Z", value_kw: 13.633 }] } } },
  {},
  { house: 8.009 },
  new Date("2026-08-30T12:00:00Z"),
);
assert.equal(provenanceHouseWithoutHistory.history.history_max_kw, null);
assert.equal(provenanceHouseWithoutHistory.history.result_kw, 8.009);
const localDayMaxima = buildDailyObservedMaxima(
  { series: { consumption: { points: [
    { timestamp: "2026-08-29T21:59:59Z", value_kw: 20 },
    { timestamp: "2026-08-29T22:00:00Z", value_kw: 9 },
  ] } } },
  {},
  new Date("2026-08-30T00:30:00+02:00"),
);
assert.equal(localDayMaxima.house, 9);
const provenanceGrid = buildLivePowerProvenance(
  "grid",
  gridTilesWithFuse.grid,
  {},
  {
    power_entity: "sensor.grid_power",
    invert_power: true,
    phase_current_source_entities: { l1: "sensor.l1", l2: "sensor.l2", l3: "sensor.l3" },
    phase_source_entities: { current: { l1: "sensor.l1", l2: "sensor.l2", l3: "sensor.l3" } },
    facility: { fuse_ampere: 16 },
  },
  { date: "2026-08-30", points: [{ timestamp: "2026-08-30T12:00:00Z", import_kw: 0, export_kw: 0.35 }] },
  {},
  liveEntityStates,
  { grid: 0.35 },
);
assert.equal(provenanceGrid.derivation.input_signed_kw, -0.35);
assert.equal(provenanceGrid.derivation.input_signed_kw_after_invert, 0.35);
assert.equal(provenanceGrid.source.fuse_ampere, 16);
assert.deepEqual(provenanceGrid.source.phase_current_entities, { l1: "sensor.l1", l2: "sensor.l2", l3: "sensor.l3" });
assert.equal(provenanceGrid.source.entities.find((item) => item.entity_id === "sensor.l1").role, "phase_l1_current");
assert.equal(provenanceGrid.history.history_max_kw, 0.35);
const provenanceBattery = buildLivePowerProvenance(
  "battery",
  liveTiles.battery,
  { battery_power_entity: "sensor.battery_power", invert_battery_power: true },
  {},
  {},
  {},
  liveEntityStates,
  { battery: 0.9 },
);
assert.equal(provenanceBattery.derivation.method, "split_signed_battery_power");
assert.equal(provenanceBattery.derivation.input_signed_kw, -0.9);
assert.equal(provenanceBattery.derivation.input_signed_kw_after_invert, 0.9);
const provenanceSeparateBattery = buildLivePowerProvenance(
  "battery",
  buildLivePowerTiles({ charging_kw: 0.4, discharging_kw: 0.2 }, {}).battery,
  { charging_entity: "sensor.charge", discharging_entity: "sensor.discharge" },
  {},
  {},
  { series: { charging: { points: [{ value_kw: 0.4 }] }, discharging: { points: [{ value_kw: 0.2 }] } } },
  { ...liveEntityStates, "sensor.charge": { state: "400", attributes: { unit_of_measurement: "W" } }, "sensor.discharge": { state: "0.2", attributes: { unit_of_measurement: "kW" } } },
  { battery: 0.4 },
);
assert.equal(provenanceSeparateBattery.derivation.method, "separate_charge_discharge_entities");
assert.equal(provenanceSeparateBattery.derivation.charging_input_kw, 0.4);
assert.equal(provenanceSeparateBattery.derivation.discharging_input_kw, 0.2);
assert.equal(buildLiveSourceEntity(liveEntityStates, "sensor.pv_a", "solar_power").unit, "W");
const phaseProvenance = buildPhaseProvenance(
  "active_power",
  {
    phase_source_entities: { active_power: { l1: "sensor.phase_power_l1" } },
    phase_discovery_method: "device_registry_and_phase_metadata",
  },
  { phase_history: { active_power: { l1: { points: [{ timestamp: "2026-08-30T12:00:00Z", value: 0.16, raw_value: 160 }] } } } },
  { "sensor.phase_power_l1": { state: "160", attributes: { unit_of_measurement: "W", device_class: "power", state_class: "measurement" }, last_updated: "2026-08-30T12:00:00Z" } },
);
assert.equal(phaseProvenance.source.entities.l1.raw_state, "160");
assert.equal(phaseProvenance.source.entities.l1.normalized_value, 0.16);
assert.equal(phaseProvenance.source.entities.l1.normalized_unit, "kW");
assert.equal(phaseProvenance.source.entities.l1.conversion, "W / 1000");
assert.equal(phaseProvenance.source.entities.l1.state_class, "measurement");
assert.equal(phaseProvenance.source.discovery_method, "device_registry_and_phase_metadata");
const invertedPhaseProvenance = buildPhaseProvenance(
  "active_power",
  {
    invert_power: true,
    phase_source_entities: { active_power: { l1: "sensor.phase_power_l1" } },
  },
  {},
  { "sensor.phase_power_l1": { state: "160", attributes: { unit_of_measurement: "W", device_class: "power" } } },
);
assert.equal(invertedPhaseProvenance.source.entities.l1.normalized_value, -0.16);
assert.equal(invertedPhaseProvenance.source.entities.l1.invert_power, true);
assert.match(invertedPhaseProvenance.normalization, /invert_power=true/);
const recorderPhaseHistory = {
  current: Object.fromEntries(["l1", "l2", "l3"].map((phase) => [
    phase,
    {
      points: Array.from({ length: 150 }, (_, index) => ({
        timestamp: `2026-08-30T${String(Math.floor(index / 60)).padStart(2, "0")}:${String(index % 60).padStart(2, "0")}:00Z`,
        value: index,
      })),
    },
  ])),
  voltage: { l1: { points: [{ timestamp: "2026-08-30T12:00:00Z", value: 230 }] } },
  active_power: { l1: { points: [{ timestamp: "2026-08-30T12:00:00Z", value: 0.1 }] } },
};
const mergedPhaseHistory = mergePhaseHistory(recorderPhaseHistory, {
  current: { l1: { points: [{ timestamp: "2026-08-30T02:30:00Z", value: 151 }] }, l2: { points: [{ timestamp: "2026-08-30T02:30:00Z", value: 151 }] }, l3: { points: [{ timestamp: "2026-08-30T02:30:00Z", value: 151 }] } },
});

const seededMeterHistory = {
  ...createMeterPowerHistoryState("2026-08-30"),
  phase_history: recorderPhaseHistory,
  points: [{ timestamp: "2026-08-30T11:55:00.000Z", import_kw: 0.1, export_kw: 0 }],
  phase_source_entities: { current: { l1: "sensor.l1", l2: "sensor.l2", l3: "sensor.l3" } },
  phase_discovery_method: "device_registry_and_phase_metadata",
  loaded_at: "2026-08-30T11:00:00.000Z",
};
const liveMeterEvent = {
  timestamp: "2026-08-30T12:00:00.000Z",
  entity_id: "sensor.grid_power",
  phase_current_a: { l1: -1, l2: 2, l3: 3 },
  phase_voltage_v: { l1: 230, l2: 231, l3: 232 },
  phase_active_power_kw: { l1: 0.1, l2: 0.2, l3: 0.3 },
  import_kw: 0.4,
  export_kw: 0,
};
const afterLiveMeterEvent = mergeMeterPowerHistoryPoint(seededMeterHistory, liveMeterEvent, "sensor.grid_power");
assert.equal(afterLiveMeterEvent.phase_history.current.l1.points.length, 151);
assert.equal(afterLiveMeterEvent.phase_history.current.l2.points.length, 151);
assert.equal(afterLiveMeterEvent.phase_history.current.l3.points.length, 151);
assert.equal(afterLiveMeterEvent.phase_history.voltage.l1.points.length, 2);
assert.equal(afterLiveMeterEvent.phase_history.active_power.l1.points.length, 2);
assert.equal(afterLiveMeterEvent.points.length, 2);
assert.equal(afterLiveMeterEvent.phase_source_entities.current.l1, "sensor.l1");
assert.equal(afterLiveMeterEvent.phase_discovery_method, "device_registry_and_phase_metadata");
assert.equal(afterLiveMeterEvent.loaded_at, "2026-08-30T11:00:00.000Z");
assert.equal(afterLiveMeterEvent.last_live_timestamp, "2026-08-30T12:00:00.000Z");
let repeatedMeterHistory = afterLiveMeterEvent;
for (let iteration = 1; iteration <= 50; iteration += 1) {
  repeatedMeterHistory = mergeMeterPowerHistoryPoint(repeatedMeterHistory, {
    ...liveMeterEvent,
    timestamp: `2026-08-30T12:${String(iteration).padStart(2, "0")}:00.000Z`,
  }, "sensor.grid_power");
  assert.equal(repeatedMeterHistory.phase_history.current.l1.points.length, 151 + iteration);
  assert.deepEqual(Object.keys(repeatedMeterHistory), Object.keys(afterLiveMeterEvent));
}
assert.equal(mergedPhaseHistory.current.l1.points.length, 151);
assert.equal(mergedPhaseHistory.current.l2.points.length, 151);
assert.equal(mergedPhaseHistory.current.l3.points.length, 151);
assert.equal(mergePhaseHistory(mergedPhaseHistory, {}).current.l1.points.length, 151);
assert.equal(mergePhaseHistory(mergedPhaseHistory, { current: { l1: { points: [{ timestamp: "2026-08-30T02:30:00Z", value: 999 }] } } }).current.l1.points.length, 151);
assert.equal(mergePhaseHistory(mergedPhaseHistory, { current: { l1: { points: [{ timestamp: "2026-08-30T02:30:00Z", value: 999 }] } } }).current.l1.points.at(-1).value, 999);
assert.deepEqual(phaseHistoryPointCounts(mergedPhaseHistory), {
  current: { l1: 151, l2: 151, l3: 151 },
  voltage: { l1: 1, l2: 0, l3: 0 },
  active_power: { l1: 1, l2: 0, l3: 0 },
});
assert.equal(phaseHistoryAvailable(mergedPhaseHistory, {}), true);
assert.equal(phaseHistoryAvailable({}, { phase_source_entities: { current: { l1: "sensor.phase_l1" } } }), true);
assert.equal(phaseHistoryAvailable({}, {}), false);
assert.equal(phaseHistoryAxisEnd([{ timestamp: "2026-08-30T17:50:00Z" }, { timestamp: "2026-08-30T15:00:00Z" }]), Date.parse("2026-08-30T17:50:00Z"));
assert.equal(phaseHistoryAxisEnd([]), null);
const mobilePhaseTicks = selectPhaseTimeTicks(Array.from({ length: 9 }, (_, index) => index * 3 * 60 * 60 * 1000), 300, 56);
assert.ok(mobilePhaseTicks.length <= 6);
assert.equal(mobilePhaseTicks[0], 0);
assert.equal(mobilePhaseTicks.at(-1), 8 * 3 * 60 * 60 * 1000);
assert.ok(mobilePhaseTicks.slice(1).every((tick, index) => tick - mobilePhaseTicks[index] >= 56));
assert.deepEqual(selectPhaseTimeTicks([3, 1, 2, 1], 200, 56), [1, 2, 3]);
const phaseGeometryWidths = [320, 390, 600, 900, 1200].map((width) => buildPhaseChartGeometry(width));
assert.ok(phaseGeometryWidths.every((geometry) => geometry.plotWidth > 0 && geometry.plotRight < geometry.width));
assert.ok(phaseGeometryWidths[0].plotWidth < phaseGeometryWidths.at(-1).plotWidth);
assert.ok(phaseGeometryWidths.every((geometry) => geometry.plotLeft <= 58));
assert.equal(buildPhaseChartGeometry(390).compact, true);
assert.equal(buildPhaseChartGeometry(900).compact, false);
const hourlyPriceGeometry = buildPriceChartGeometry();
const dualPriceGeometry = buildPriceChartGeometry(960, 350, { dualAxis: true });
assert.equal(hourlyPriceGeometry.plotLeft, 60);
assert.equal(hourlyPriceGeometry.plotBottom, hourlyPriceGeometry.xAxisRailHeight);
assert.equal(dualPriceGeometry.plotLeft, 64);
assert.equal(dualPriceGeometry.plotRight, 72);
assert.ok(hourlyPriceGeometry.plotWidth > 0 && dualPriceGeometry.plotWidth > 0);
assert.match(eonPanelSource, /chart-axis-overlay-x\.edge-start/);
assert.match(eonPanelSource, /chart-axis-overlay-x\.edge-end/);
assert.match(eonPanelSource, /buildPriceChartGeometry\(width, height, \{ dualAxis: true \}\)/);
assert.match(eonPanelSource, /buildPriceChartGeometry\(width, height\)/);
const phaseRawSamples = (offset = 0) => Array.from({ length: 720 }, (_, index) => ({
  timestamp: new Date(Date.parse("2026-08-30T00:00:00Z") + (index * 5 + offset) * 1000).toISOString(),
  value: index === 361 ? 99 : index / 100,
}));
const renderedPhaseSamples = buildCanonicalPhasePoints(phaseRawSamples(), "2026-08-30T00:00:00Z", "2026-08-30T00:59:55Z");
const renderedVoltageSamples = buildCanonicalPhasePoints(phaseRawSamples(1), "2026-08-30T00:00:00Z", "2026-08-30T00:59:55Z");
const renderedPowerSamples = buildCanonicalPhasePoints(phaseRawSamples(2), "2026-08-30T00:00:00Z", "2026-08-30T00:59:55Z");
assert.equal(phaseRawSamples().length, 720);
assert.equal(renderedPhaseSamples.length, 12);
assert.equal(renderedVoltageSamples.length, renderedPhaseSamples.length);
assert.equal(renderedPowerSamples.length, renderedPhaseSamples.length);
assert.deepEqual(renderedPhaseSamples.map((point) => point.timestamp), renderedVoltageSamples.map((point) => point.timestamp));
assert.deepEqual(renderedPhaseSamples.map((point) => point.timestamp), renderedPowerSamples.map((point) => point.timestamp));
assert.equal(phaseHistoryAxisEnd(renderedPhaseSamples), Date.parse("2026-08-30T00:55:00Z"));
assert.equal(Math.max(...phaseRawSamples().map((point) => point.value)), 99);
assert.match(eonPanelSource, /cardAvailable = phaseHistoryAvailable/);
assert.match(eonPanelSource, /Välj minst en fas/);
assert.doesNotMatch(eonPanelSource, /card\.hidden = !hasActivePoints/);
for (const raw of [provenanceSolar, provenanceHouse, provenanceGrid, provenanceBattery]) {
  assert.equal(Object.prototype.hasOwnProperty.call(raw, "token"), false);
  assert.equal(Object.prototype.hasOwnProperty.call(raw, "password"), false);
  assert.equal(Object.prototype.hasOwnProperty.call(raw, "cookies"), false);
}
const sourcePolicyFixture = sanitizeDebugData({
  customerId: "customer-placeholder",
  accountId: "account-placeholder",
  installationId: "installation-placeholder",
  premiseId: "premise-placeholder",
  POD: "pod-placeholder",
  meterId: "meter-placeholder",
  deviceNumber: "device-placeholder",
  contractId: "contract-placeholder",
  invoiceKey: "invoice-placeholder",
  name: "Example",
  address: { city: "Exampletown" },
  tariff: { transfer_price: 97 },
  invoice_status: "issued",
  token: "secret",
  accessToken: "access-secret",
  refreshToken: "refresh-secret",
  authorization: "Bearer secret",
  cookie: "session-cookie",
  clientSecret: "client-secret",
  apiKey: "api-secret",
  nested: [{ session_token: "session-secret" }],
});
assert.equal(sourcePolicyFixture.customerId, "customer-placeholder");
assert.equal(sourcePolicyFixture.accountId, "account-placeholder");
assert.equal(sourcePolicyFixture.installationId, "installation-placeholder");
assert.equal(sourcePolicyFixture.premiseId, "premise-placeholder");
assert.equal(sourcePolicyFixture.POD, "pod-placeholder");
assert.equal(sourcePolicyFixture.meterId, "meter-placeholder");
assert.equal(sourcePolicyFixture.deviceNumber, "device-placeholder");
assert.equal(sourcePolicyFixture.contractId, "contract-placeholder");
assert.equal(sourcePolicyFixture.invoiceKey, "invoice-placeholder");
assert.equal(sourcePolicyFixture.name, "Example");
assert.equal(sourcePolicyFixture.address.city, "Exampletown");
assert.equal(sourcePolicyFixture.tariff.transfer_price, 97);
assert.equal(sourcePolicyFixture.invoice_status, "issued");
for (const key of ["token", "accessToken", "refreshToken", "authorization", "cookie", "clientSecret", "apiKey"]) {
  assert.equal(sourcePolicyFixture[key], "[redacted]");
}
assert.equal(sourcePolicyFixture.nested[0].session_token, "[redacted]");
assert.doesNotMatch(eonPanelSource, /function copyChartRawData/);
assert.match(eonPanelSource, /data-live-power-scale/);
assert.doesNotMatch(eonPanelSource, /data-live-power-max/);
assert.doesNotMatch(eonPanelSource, /live-power-max/);
assert.match(eonPanelSource, /data-live-power-copy-feedback/);
assert.equal((eonPanelSource.match(/data-live-power-source=/g) || []).length, 5);
assert.match(eonPanelSource, /Visa data/);
assert.doesNotMatch(eonPanelSource, /Visa mätardata/);
assert.match(eonPanelSource, /_livePowerRaw/);
assert.match(eonPanelSource, /_updateLivePowerCardInteractivity/);
assert.doesNotMatch(eonPanelSource, /_copyLivePowerTile/);
assert.doesNotMatch(eonPanelSource, /debug-copy-enabled/);
assert.match(eonPanelSource, /\.live-power-debug-footer\.visible \{/);
assert.match(eonPanelSource, /JSON\.stringify\(safeSource, null, 2\)/);
assert.match(eonPanelSource, /liveSource \|\| isEon \|\| cardSource/);
assert.match(eonPanelSource, /closest\?\.\("\[data-live-power-tile\], \[data-invoice-estimate-card\]"\)/);
const invoiceRenderSource = eonPanelSource.slice(
  eonPanelSource.indexOf("  _renderInvoiceEstimateCard()"),
  eonPanelSource.indexOf("  _renderInvoiceCardCosts()"),
);
assert.match(invoiceRenderSource, /card\._livePowerRaw = this\._invoiceEstimateRaw/);
assert.match(invoiceRenderSource, /this\._updateLivePowerCardInteractivity\(\)/);
assert.match(eonPanelSource, /data-live-power-grid-meta/);
assert.match(eonPanelSource, /data-live-power-grid-fuse-status/);
assert.match(eonPanelSource, /fill\.style\.backgroundColor = chartColor\(tile\.colorKey\)/);
assert.match(eonPanelSource, /status\.style\.color = Number\.isFinite\(tile\.value\)/);
assert.match(eonPanelSource, /grid-template-rows: auto auto auto 5px auto minmax\(0, auto\);/);
assert.match(eonPanelSource, /live-power-debug-footer/);
assert.match(eonPanelSource, /data-live-power-scale[\s\S]*data-live-power-grid-fuse-status/);
assert.match(eonPanelSource, /maxPhaseCurrentA/);
assert.match(eonPanelSource, /fuseUtilizationPercent/);
assert.match(eonPanelSource, /maxPhaseCurrentA\) && Number\.isFinite\(tile\.fuseAmpere\)[\s\S]*\/ \$\{this\._formatNumber\(tile\.fuseAmpere\)\} A/);
assert.doesNotMatch(eonPanelSource, /`Maxfas \$\{this\._formatNumber\(tile\.maxPhaseCurrentA\)/);
assert.match(eonPanelSource, /daily_max_phase_current_a/);
assert.match(eonPanelSource, /daily_max_fuse_utilization_percent/);
assert.doesNotMatch(eonPanelSource, /Maxfas \$\{this\._formatNumber\(tile\.maxPhaseCurrentA\)/);
assert.match(eonPanelSource, /facility\?\.fuse_ampere/);
const liveCardInteractivitySource = eonPanelSource.slice(
  eonPanelSource.indexOf("  _updateLivePowerCardInteractivity()"),
  eonPanelSource.indexOf("  _renderDailyEnergyCard()"),
);
assert.match(liveCardInteractivitySource, /\.live-power-debug-footer/);
assert.doesNotMatch(liveCardInteractivitySource, /addEventListener|_copyLivePowerTile|tabIndex|setAttribute\("role"/);
assert.doesNotMatch(eonPanelSource, /live-power-icon/);
assert.doesNotMatch(eonPanelSource, /live-power-tooltip/);
assert.doesNotMatch(eonPanelSource, /_bindLivePowerTooltips/);
assert.match(eonPanelSource, /grid-template-columns: repeat\(4, minmax\(0, 1fr\)/);
assert.match(eonPanelSource, /@media \(max-width: 760px\)[\s\S]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)/);
const solarOverReference = buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 2, 13),
  { "2026-08-22": 1 },
  new Date(2026, 7, 23, 12, 0),
  2,
);
assert.equal(solarOverReference[0].forecastKwh, 1);
assert.equal(solarOverReference[0].utilizationPercent, 50);
assert.equal(buildSolarDailyHistory(dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 1, 13), [], new Date(2026, 7, 23, 12, 0), 2)[0].forecastKwh, null);
assert.equal(buildSolarDailyHistory(dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 1, 13), [], new Date(2026, 7, 23, 12, 0), 2)[0].utilizationPercent, null);
assert.equal(dailyHistory.length, 7);
assert.ok(Math.abs(dailyHistory[5].chargingKwh - 1) < 1e-12);
assert.ok(Math.abs(dailyHistory[5].dischargingKwh - 1) < 1e-12);
assert.ok(Math.abs(dailyHistory[5].utilizationPercent - 50) < 1e-12);
assert.equal(buildBatteryDailyHistory(dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 1, 13), [], null, new Date(2026, 7, 23, 12, 0))[5].utilizationPercent, null);
assert.ok(Math.abs(buildBatteryDailyHistory(dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 1, 13), dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 2, 7), 0.5, new Date(2026, 7, 23, 12, 0))[5].utilizationPercent - 200) < 1e-12);
assert.equal(integratePowerHistoryKwh([
  powerPoints([1, 1, 1])[0],
  powerPoints([1, 1, 1])[2],
], integrationStart, integrationEnd, new Date("2026-08-23T00:10:00")), 0);
const solarBalance = buildEnergyBalance(31.9, 15.8);
assert.equal(solarBalance.total, 31.9);
assert.equal(solarBalance.external, 15.8);
assert.ok(Math.abs(solarBalance.local - 16.1) < 1e-12);
assert.ok(Math.abs(solarBalance.localPercent - 16.1 / 31.9 * 100) < 1e-12);
assert.ok(Math.abs(solarBalance.externalPercent - 15.8 / 31.9 * 100) < 1e-12);
const consumptionBalance = buildEnergyBalance(16.5, 0.4);
assert.equal(consumptionBalance.total, 16.5);
assert.equal(consumptionBalance.external, 0.4);
assert.ok(Math.abs(consumptionBalance.local - 16.1) < 1e-12);
assert.ok(Math.abs(consumptionBalance.localPercent - 16.1 / 16.5 * 100) < 1e-12);
assert.ok(Math.abs(consumptionBalance.externalPercent - 0.4 / 16.5 * 100) < 1e-12);
assert.equal(buildEnergyBalance(0, 2).local, 0);
assert.equal(buildEnergyBalance(null, 2).local, null);
assert.equal(integratePowerHistoryKwh(powerPoints([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]), integrationStart, integrationEnd, new Date("2026-08-23T01:00:00")), 1);
assert.ok(Math.abs(integratePowerHistoryKwh(powerPoints([2, 2, 2, 2, 2, 2, 2]), integrationStart, integrationEnd, new Date("2026-08-23T00:30:00")) - 1) < 1e-12);
assert.equal(buildEnergyBalance(25, 30).local, 0);
assert.equal(buildEnergyBalance(25, 30).externalPercent, 120);
const thresholdPoints = (values) => values.map((value, index) => ({
  timestamp: `2026-08-25T12:${String(index * 5).padStart(2, "0")}:00Z`,
  raw_timestamp: value === null ? null : `2026-08-25T12:${String(index * 5).padStart(2, "0")}:00Z`,
  value_kw: value,
  gap_before: false,
}));
const risingSegments = buildThresholdClippedSegments(thresholdPoints([0.04, 1.19]), "value_kw");
assert.equal(risingSegments.length, 1);
assert.equal(risingSegments[0].length, 2);
assert.equal(risingSegments[0][0].value_kw, 0.1);
assert.equal(risingSegments[0][0].timestamp, new Date("2026-08-25T12:00:00Z").getTime() + (0.06 / 1.15) * 5 * 60 * 1000);
const isolatedSegments = buildThresholdClippedSegments(thresholdPoints([0.03, 0.36, 0.04]), "value_kw");
assert.deepEqual(isolatedSegments.map((segment) => segment.map((point) => point.value_kw)), [[0.1, 0.36, 0.1]]);
const fallingSegments = buildThresholdClippedSegments(thresholdPoints([0.8, 0.3, 0.04]), "value_kw");
assert.equal(fallingSegments[0].at(-1).value_kw, 0.1);
const openEndedSegments = buildThresholdClippedSegments(thresholdPoints([1.5, 2.66]), "value_kw");
assert.equal(openEndedSegments[0].at(-1).value_kw, 2.66);
assert.equal(buildThresholdClippedSegments(thresholdPoints([0.1, 0.05]), "value_kw").length, 0);
assert.equal(buildThresholdClippedSegments(thresholdPoints([0.4, null, 1.2]), "value_kw").length, 0);
const continuousGapPoints = thresholdPoints([1, 2, 4, 5]).filter((_, index) => index !== 2);
const continuousGapSnapshot = JSON.stringify(continuousGapPoints);
const continuousGaps = buildContinuousGapPairs(continuousGapPoints, "value_kw");
assert.equal(continuousGaps.length, 1);
assert.equal(continuousGaps[0][0].value_kw, 2);
assert.equal(continuousGaps[0][1].value_kw, 5);
assert.equal(JSON.stringify(continuousGapPoints), continuousGapSnapshot);
assert.equal(buildContinuousGapPairs(thresholdPoints([1, 2]), "value_kw").length, 0);
const missingStartPoints = thresholdPoints([null, 1.19, 1.2]);
assert.deepEqual(
  buildThresholdClippedSegments(missingStartPoints, "value_kw")[0].map((point) => point.value_kw),
  [1.19, 1.2],
);
assert.equal(isVisiblePowerValue(0), false);
assert.equal(isVisiblePowerValue(0.01), false);
assert.equal(isVisiblePowerValue(0.1), false);
assert.equal(isVisiblePowerValue(0.11), true);
for (const series of ["import", "export", "solar", "consumption", "charging", "discharging"]) {
  assert.equal(isVisiblePowerValue(0.1), false, `${series} threshold`);
  assert.equal(isVisiblePowerValue(0.11), true, `${series} threshold`);
}
const lowPriceDay = priceColorBands([1.7, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 8, 12, 18, 20, 35.8]);
assert.equal(priceCategory(1.7, lowPriceDay), "cheap");
assert.equal(priceCategory(8, lowPriceDay), "normal");
assert.equal(priceCategory(18, lowPriceDay), "expensive");
const normalDay = priceColorBands([20, 30, 40, 50, 60, 70, 80, 90, 100, 110]);
assert.equal(priceCategory(30, normalDay), "cheap");
assert.equal(priceCategory(60, normalDay), "normal");
assert.equal(priceCategory(100, normalDay), "expensive");
const extremePeakDay = priceColorBands([10, 11, 12, 12, 13, 13, 14, 14, 15, 15, 16, 17, 40]);
assert.equal(priceCategory(40, extremePeakDay), "expensive");
const relativePeakDay = priceColorBands([10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 21, 22, 23, 24, 25]);
assert.equal(priceCategory(21, relativePeakDay), "expensive");
assert.deepEqual(priceColorDetails(21, relativePeakDay, 11, 15), {
  price: 21,
  category: "red",
  min: 10,
  max: 25,
  average: 14.3,
  median: 10,
  rank: 11,
  period_count: 15,
  percentile: 73.3,
  reason: ["above_average", "above_median_threshold"],
});
assert.deepEqual(priceColorDetails(25, relativePeakDay, 15, 15).reason, ["top_20_percent", "above_average", "above_median_threshold"]);
assert.equal(createPriceDebugText({
  time: "13:30–13:45",
  value: "35,7 öre/kWh",
  details: { price: 35.7, category: "red", reason: ["top_20_percent"] },
}), "13:30–13:45\n35,7 öre/kWh\n\n{\n  \"price\": 35.7,\n  \"category\": \"red\",\n  \"reason\": [\n    \"top_20_percent\"\n  ]\n}");
assert.match(createPriceDebugText({
  time: "13:30–13:45",
  value: "58,7 öre/kWh",
  details: {
    spot_price_ex_vat: 29.93,
    electricity_cost_ex_vat: 17,
    subtotal_ex_vat: 46.93,
    vat: 11.73,
    customer_price: 58.66,
    category: "red",
  },
}), /\"spot_price_ex_vat\": 29\.93[\s\S]*\"electricity_cost_ex_vat\": 17[\s\S]*\"subtotal_ex_vat\": 46\.93[\s\S]*\"vat\": 11\.73[\s\S]*\"customer_price\": 58\.66/);
const makeAnalysisPeriods = (values) => values.map((price, index) => {
  const start = new Date("2026-08-23T00:00:00+02:00");
  start.setMinutes(index * 15);
  const end = new Date(start);
  end.setMinutes(end.getMinutes() + 15);
  return { start: start.toISOString(), end: end.toISOString(), price: price / 100 };
});
const waitPeriods = makeAnalysisPeriods([
  ...Array(12).fill(86),
  ...Array(8).fill(54),
  ...Array(12).fill(100),
]);
const waitFacts = buildPriceAnalysisFacts(waitPeriods, 0);
assert.equal(waitFacts.usage_window_minutes, 120);
assert.equal(waitFacts.search_horizon_hours, 6);
assert.equal(waitFacts.now_window.average_price, 86);
assert.equal(waitFacts.best_window.startIndex, 12);
assert.equal(waitFacts.best_window.average_price, 54);
assert.equal(waitFacts.difference_ore_per_kwh, 32);
assert.equal(Math.round(waitFacts.difference_percent), 37);
assert.equal(waitFacts.lower_window_significant, true);
assert.equal(waitFacts.higher_window_significant, false);
assert.deepEqual(renderPriceAnalysis(waitFacts), {
  category: waitFacts.status,
  status: "Billigt pris nu",
  forecast: "Nästa 2 h: 86 öre/kWh i snitt. Från 03:00: 54 öre/kWh.",
  sentences: ["Nästa 2 h: 86 öre/kWh i snitt.", "Från 03:00: 54 öre/kWh."],
});
const marginPeriods = makeAnalysisPeriods([...Array(8).fill(86), ...Array(24).fill(82)]);
const marginFacts = buildPriceAnalysisFacts(marginPeriods, 0);
assert.equal(marginFacts.best_window.average_price, 82);
assert.equal(marginFacts.lower_window_significant, false);
assert.equal(marginFacts.higher_window_significant, false);
assert.equal(renderPriceAnalysis(marginFacts).status, "Dyrt pris nu");
assert.match(renderPriceAnalysis(marginFacts).forecast, /6 timmar/);
const cheapNowFacts = buildPriceAnalysisFacts(makeAnalysisPeriods([...Array(8).fill(40), ...Array(24).fill(100)]), 0);
assert.equal(cheapNowFacts.best_window.startIndex, 0);
assert.equal(cheapNowFacts.lower_window_significant, false);
assert.match(renderPriceAnalysis(cheapNowFacts).forecast, /Nästa 2 h/);
const makeClockPeriods = (startText, values, gapAfter = -1) => values.map((value, index) => {
  const start = new Date(startText);
  start.setTime(start.getTime() + index * 15 * 60 * 1000 + (index > gapAfter && gapAfter >= 0 ? 15 * 60 * 1000 : 0));
  const end = new Date(start.getTime() + 15 * 60 * 1000);
  return { start: start.toISOString(), end: end.toISOString(), price: value / 100 };
});
const lateWithoutTomorrow = buildPriceAnalysisFacts(
  makeClockPeriods("2026-08-23T23:00:00+02:00", [80, 81, 82, 83]),
  0,
);
assert.equal(lateWithoutTomorrow.available_future_minutes, 60);
assert.equal(lateWithoutTomorrow.has_full_two_hour_window, false);
assert.equal(lateWithoutTomorrow.has_full_six_hour_horizon, false);
assert.match(renderPriceAnalysis(lateWithoutTomorrow).forecast, /Resten av kvällen/);
assert.doesNotMatch(renderPriceAnalysis(lateWithoutTomorrow).forecast, /Nästa 2 h|6 timmar/);
assert.deepEqual(renderPriceAnalysis(lateWithoutTomorrow).sentences, ["Resten av kvällen: 81,5 öre/kWh i snitt."]);
const lateWithTomorrow = buildPriceAnalysisFacts(
  makeClockPeriods("2026-08-23T23:00:00+02:00", Array.from({ length: 24 }, (_, index) => 80 + index)),
  0,
);
assert.equal(lateWithTomorrow.available_future_minutes, 360);
assert.equal(lateWithTomorrow.has_full_two_hour_window, true);
assert.equal(lateWithTomorrow.has_full_six_hour_horizon, true);
assert.equal(lateWithTomorrow.crosses_midnight, true);
assert.match(renderPriceAnalysis(lateWithTomorrow).forecast, /Nästa 2 h/);
const gapFacts = buildPriceAnalysisFacts(
  makeClockPeriods("2026-08-23T21:00:00+02:00", [80, 81, 82, 83], 1),
  0,
);
assert.equal(gapFacts.available_future_periods, 2);
assert.equal(gapFacts.effective_search_horizon_minutes, 30);
assert.doesNotMatch(renderPriceAnalysis(gapFacts).forecast, /6 timmar|Nästa 2 h/);
const renderedAnalysis = renderPriceAnalysis(waitFacts);
assert.doesNotMatch(renderedAnalysis.status + renderedAnalysis.forecast, /Starta nu|Vänta|Billigast att starta|Du bör|Kör tvättmaskin/);
assert.doesNotMatch(renderedAnalysis.forecast, /Priset stiger senare|Det blir billigare|Priset förändras under kvällen/);
assert.match(renderPriceAnalysis(waitFacts).forecast, /öre\/kWh/);
assert.match(renderPriceAnalysis(waitFacts).forecast, /Från 03:00: 54 öre\/kWh/);
assert.equal(renderPriceAnalysis({ ...waitFacts, status: "cheap" }).status, "Billigt pris nu");
assert.equal(renderPriceAnalysis({ ...waitFacts, status: "normal" }).status, "Normalt pris nu");
assert.equal(renderPriceAnalysis({ ...waitFacts, status: "expensive" }).status, "Dyrt pris nu");
assert.equal(renderPriceAnalysis(buildPriceAnalysisFacts(makeAnalysisPeriods([5, 5, 5, 5]), 0)).forecast, "Dagens prisanalys är inte tillgänglig");
assert.deepEqual(renderPriceAnalysis(buildPriceAnalysisFacts(makeAnalysisPeriods([5, 5, 5, 5]), 0)).sentences, ["Dagens prisanalys är inte tillgänglig"]);
const guardedLowDay = priceColorBands([...Array.from({ length: 15 }, (_, index) => 1 + index / 10), 4.1, 100, 101, 102, 103, 104]);
assert.equal(priceCategory(4.1, guardedLowDay), "normal");
assert.equal(priceCategory(2, priceColorBands([2, 2, 2])), "normal");
const tooltipDayStart = new Date("2026-08-23T00:00:00+02:00").getTime();
const tooltipDayEnd = tooltipDayStart + 24 * 60 * 60 * 1000;
const tooltipSlot = (hour, minute) => new Date(`2026-08-23T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00+02:00`).getTime();
assert.equal(snapTooltipTimestamp(tooltipSlot(4, 45), tooltipDayStart, tooltipDayEnd), tooltipSlot(4, 45));
assert.equal(snapTooltipTimestamp(tooltipSlot(4, 47), tooltipDayStart, tooltipDayEnd), tooltipSlot(4, 45));
assert.equal(snapTooltipTimestamp(tooltipSlot(4, 49), tooltipDayStart, tooltipDayEnd), tooltipSlot(4, 50));
assert.equal(snapTooltipTimestamp(tooltipSlot(4, 53), tooltipDayStart, tooltipDayEnd), tooltipSlot(4, 55));
assert.equal(snapTooltipTimestamp(tooltipSlot(23, 59), tooltipDayStart, tooltipDayEnd), tooltipSlot(23, 55));
const rawMeterPoints = [
  { timestamp: "2026-08-23T04:48:30+02:00", import_kw: 4.82, export_kw: 0 },
  { timestamp: "2026-08-23T04:52:00+02:00", import_kw: 5, export_kw: 0 },
];
assert.equal(nearestMeterPoint(rawMeterPoints, tooltipSlot(4, 50)).import_kw, 4.82);
assert.equal(nearestMeterPoint(rawMeterPoints, tooltipSlot(4, 55)), null);
const canonicalMeterPoints = buildCanonicalMeterPoints(
  [...rawMeterPoints, { timestamp: "2026-08-23T04:53:00+02:00", import_kw: 5, export_kw: 0 }],
  new Date("2026-08-23T00:00:00+02:00"),
  new Date("2026-08-24T00:00:00+02:00"),
);
assert.equal(canonicalMeterPoints.length, 288);
const canonical0450 = canonicalMeterPoints.find((point) => point.timestamp === tooltipSlot(4, 50));
assert.equal(canonical0450.import_kw, 4.82);
assert.equal(canonical0450.raw_timestamp, rawMeterPoints[0].timestamp);
const canonical0455 = canonicalMeterPoints.find((point) => point.timestamp === tooltipSlot(4, 55));
assert.equal(canonical0455.import_kw, 5);
assert.equal(canonical0455.raw_timestamp, "2026-08-23T04:53:00+02:00");
const canonical0500 = canonicalMeterPoints.find((point) => point.timestamp === tooltipSlot(5, 0));
assert.equal(canonical0500.import_kw, null);
assert.equal(canonical0500.raw_timestamp, null);
assert.equal(rawMeterPoints.length, 2);
assert.equal(normalizeMeterValue(null), null);
assert.equal(normalizeMeterValue(undefined), null);
assert.equal(normalizeMeterValue(""), null);
assert.equal(normalizeMeterValue(0), 0);
assert.equal(normalizeMeterValue("0"), 0);
assert.equal(normalizeMeterValue(4.82), 4.82);
const canonicalMissingSample = buildCanonicalMeterPoints(
  [{ timestamp: "2026-08-23T05:00:00+02:00", import_kw: null, export_kw: 0 }],
  new Date("2026-08-23T00:00:00+02:00"),
  new Date("2026-08-24T00:00:00+02:00"),
);
const canonical0500Missing = canonicalMissingSample.find((point) => point.timestamp === tooltipSlot(5, 0));
assert.equal(canonical0500Missing.import_kw, null);
assert.equal(canonical0500Missing.export_kw, null);
assert.equal(canonical0500Missing.raw_timestamp, null);
const canonicalZeroSample = buildCanonicalMeterPoints(
  [{ timestamp: "2026-08-23T05:00:00+02:00", import_kw: 0, export_kw: 0 }],
  new Date("2026-08-23T00:00:00+02:00"),
  new Date("2026-08-24T00:00:00+02:00"),
);
const canonical0500Zero = canonicalZeroSample.find((point) => point.timestamp === tooltipSlot(5, 0));
assert.equal(canonical0500Zero.import_kw, 0);
assert.equal(canonical0500Zero.export_kw, 0);
assert.equal(canonical0500Zero.raw_timestamp, "2026-08-23T05:00:00+02:00");
const monotoneCoordinates = [{ x: 0, y: 0 }, { x: 1, y: 2 }, { x: 2, y: 1 }, { x: 3, y: 3 }];
const monotoneSegments = buildMonotoneCubicSegments(monotoneCoordinates);
assert.equal(monotoneSegments.length, monotoneCoordinates.length - 1);
assert.deepEqual(monotoneSegments[0].start, monotoneCoordinates[0]);
assert.deepEqual(monotoneSegments.at(-1).end, monotoneCoordinates.at(-1));
for (const segment of monotoneSegments) {
  const low = Math.min(segment.start.y, segment.end.y);
  const high = Math.max(segment.start.y, segment.end.y);
  for (let step = 0; step <= 20; step += 1) {
    const t = step / 20;
    const inverse = 1 - t;
    const y = inverse ** 3 * segment.start.y
      + 3 * inverse ** 2 * t * segment.control1.y
      + 3 * inverse * t ** 2 * segment.control2.y
      + t ** 3 * segment.end.y;
    assert.ok(y >= low - 1e-9 && y <= high + 1e-9);
  }
}

const panelSource = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
assert.doesNotMatch(panelSource, /E\.ON Energidistribution/);
assert.doesNotMatch(panelSource, /HomeWizard/);
assert.match(panelSource, /<h2 id="provider-source-dialog-title">Source data<\/h2>/);
assert.match(panelSource, /data-provider-source-copy/);
assert.match(panelSource, /data-electricity-configure/);
assert.match(panelSource, /data-electricity-provider/);
assert.match(panelSource, /elrakning\/electricity_provider_state/);
assert.match(panelSource, /elrakning\/electricity_provider_remove/);
assert.match(panelSource, /await this\.loadPriceData\(\);/);
assert.equal((panelSource.match(/this\._applyProviderState\(saved\);\n\s*await this\.loadPriceData\(\);/g) || []).length, 2);
assert.match(panelSource, /let saving = false/);
assert.match(panelSource, /saving = true/);
assert.match(panelSource, /result\.textContent = "Sparar\.\.\."/);
assert.match(panelSource, /saving = false/);
assert.match(panelSource, /--card-title-size: clamp\(20px, 5\.2cqw, 24px\)/);
assert.match(panelSource, /--price-card-text-size: clamp\(10px, 2\.7cqw, 12px\)/);
assert.match(panelSource, /--card-legend-size: var\(--price-card-text-size\)/);
assert.doesNotMatch(panelSource, /--card-(subtitle|toggle|kpi|analysis|tooltip)-/);
assert.match(panelSource, /border-radius: 8px/);
assert.match(panelSource, /font-size: clamp\(9px, 2\.2cqw, 10px\)/);
assert.match(panelSource, /max-width: min\(170px, calc\(100% - 12px\)\)/);
assert.match(panelSource, /padding: clamp\(4px, 1cqw, 5px\) clamp\(5px, 1\.3cqw, 6px\)/);
assert.match(panelSource, /\.tooltip-value \{[\s\S]*font-size: inherit[\s\S]*line-height: 1\.15[\s\S]*margin-top: 2px/);
assert.match(panelSource, /\.chart-tooltip > strong[\s\S]*font-size: inherit/);
assert.match(panelSource, /\.section-heading h2,[\s\S]*\.card\[data-provider-card\] h2/);
assert.doesNotMatch(panelSource, /\.price-value\.current strong \{/);
assert.match(panelSource, /\.price-analysis-status \{[\s\S]*font-size: var\(--price-card-text-size\)/);
assert.match(panelSource, /\.price-analysis-forecast \{[\s\S]*font-size: var\(--price-card-text-size\)/);
assert.match(panelSource, /Ta bort elhandelsavtal/);
assert.match(panelSource, /data-electricity-history-option/);
assert.match(panelSource, /Radera historik/);
assert.match(panelSource, /purge_history: purgeHistory\?\.checked === true/);
assert.match(panelSource, /purgeHistory = document\.createElement\("input"\)/);
assert.match(panelSource, /if \(configured\)/);
assert.doesNotMatch(panelSource, /<input type="checkbox" data-electricity-purge-history>/);
assert.match(panelSource, /remove\.disabled = true/);
assert.match(panelSource, /data-retained-history/);
assert.match(panelSource, /Sparad historik/);
assert.match(panelSource, /elrakning\/electricity_history_state/);
assert.match(panelSource, /elrakning\/electricity_history_purge/);
assert.match(panelSource, /window\.confirm\("Radera sparad historik/);
assert.match(panelSource, /data-retained-history-purge/);
assert.match(panelSource, /Välj elhandelsbolag/);
assert.doesNotMatch(panelSource, /<h2 id="greenely-title">Greenely<\/h2>/);
assert.match(panelSource, /data-meter-configure/);
assert.match(panelSource, /data-meter-configure="house_load"/);
assert.match(panelSource, /data-meter-configure="meter"/);
assert.match(panelSource, /data-eon-grid-card-configure/);
assert.match(panelSource, /const opens = this\.host\.querySelectorAll\("\[data-meter-configure\]"\)/);
assert.match(panelSource, /mode === "house_load"/);
assert.match(panelSource, /Husets last/);
assert.match(panelSource, /const opens = this\.host\.querySelectorAll\("\[data-eon-grid-configure\], \[data-eon-grid-card-configure\]"\)/);
assert.match(panelSource, /data-config-cards-toggle/);
assert.match(panelSource, /class="header-icon-button config-cards-button\$\{this\._configurationCardsVisible \? " active" : ""\}"/);
assert.match(panelSource, /class="header-icon-button debug-button\$\{this\._debugEnabled \? " active" : ""\}"/);
assert.match(panelSource, /data-config-cards-toggle><ha-icon icon="mdi:cog-outline"><\/ha-icon><\/button>/);
assert.match(panelSource, /data-debug-toggle><ha-icon icon="mdi:bug-outline"><\/ha-icon><\/button>/);
assert.doesNotMatch(panelSource, /⚙️|🐞/);
assert.match(panelSource, /aria-label="Visa konfigurationskort"/);
assert.match(panelSource, /aria-label="Visa diagnostik"/);
assert.match(panelSource, /data-configuration-cards/);
assert.match(panelSource, /_bindConfigurationCardsToggle()/);
assert.match(panelSource, /this\._applyConfigurationCardsVisibility\(response\.configuration_cards_visible, response\.main_cards\)/);
assert.match(panelSource, /main_cards/);
assert.match(panelSource, /data-config-card-key="elhandel"/);
assert.match(panelSource, /data-config-card-key="elnet"/);
assert.doesNotMatch(panelSource, /data-config-card-key="elmatare"/);
assert.doesNotMatch(panelSource, /data-config-card-key="solar"/);
assert.doesNotMatch(panelSource, /data-config-card-key="consumption"/);
assert.doesNotMatch(panelSource, /data-config-card-key="battery"/);
assert.match(panelSource, /data-main-card-toggle/);
assert.equal((panelSource.match(/class="main-card-toggle"/g) || []).length, 2);
assert.doesNotMatch(panelSource, /main-card-toggle[^>]*>Main/);
assert.match(panelSource, /main-card-toggle[^>]*aria-label="Main"/);
assert.match(panelSource, /configuration-control/);
assert.match(panelSource, /\.main-card-toggle\[hidden\] \{[\s\S]*display: none !important/);
assert.match(panelSource, /\.main-card-track \{[\s\S]*background: #555/);
assert.match(panelSource, /\.main-card-track::after \{[\s\S]*background: #d8d8d8/);
assert.match(panelSource, /\.main-card-toggle input:checked \+ \.main-card-track \{[\s\S]*background: var\(--primary-color\)/);
assert.match(panelSource, /this\._applyConfigurationCardsVisibility\(this\._configurationCardsVisible\)/);
assert.match(panelSource, /configuration_cards_visible: this._configurationCardsVisible/);
assert.doesNotMatch(panelSource, /debug-toggle-track/);
assert.doesNotMatch(panelSource, /role="switch" aria-label="Visa diagnostik"/);
assert.doesNotMatch(panelSource, />Översikt<\/p>/);
assert.match(panelSource, /\.header \{[\s\S]*margin-bottom: 16px;[\s\S]*padding-bottom: 0;/);
assert.doesNotMatch(panelSource, /\.header \{[\s\S]*border-bottom:/);
assert.match(panelSource, /\[data-configuration-cards\]\[hidden\] \{[\s\S]*display: none;/);
assert.match(panelSource, /\.header-icon-button \{[\s\S]*opacity: \.55;/);
assert.match(panelSource, /\.header-icon-button\.active \{[\s\S]*opacity: 1;/);
assert.doesNotMatch(panelSource, /header-icon-button[\s\S]*drop-shadow/);
assert.doesNotMatch(panelSource, /header-icon-button[^}]*filter:/);
assert.match(panelSource, /config-cards-button\$\{this\._configurationCardsVisible \? " active" : ""\}/);
assert.match(panelSource, /debug-button\$\{this\._debugEnabled \? " active" : ""\}/);
assert.match(panelSource, /meter_save_clicked/);
assert.match(panelSource, /meter_save_payload_created/);
assert.match(panelSource, /document\.createElement\("ha-selector"\)/);
assert.match(panelSource, /selector\.selector = \{ entity: \{ filter: selectorConfig\(field\), multiple: false \} \}/);
assert.match(panelSource, /\["Wh", "kWh", "MWh"\]/);
assert.match(panelSource, /selector\.addEventListener\("value-changed"/);
assert.match(panelSource, /selector\.value = event\.detail\?\.value/);
assert.match(panelSource, /const buildMeterSelector = \(labelText, field, value\) => \{/);
assert.match(panelSource, /selector\.dataset\.meterField = field/);
assert.match(panelSource, /selector\.selector = \{ entity: \{ filter: selectorConfig\(field\), multiple: false \} \}/);
assert.match(panelSource, /container\.replaceChildren\(buildMeterSelector\(labelText, field, value\)\)/);
assert.match(panelSource, /fields\.map\(\(\[labelText, field\]\) =>\s*buildMeterSelector\(labelText, field, mapping\?\.\[field\] \|\| undefined\)\)/);
assert.match(panelSource, /meter_selector_values_read/);
assert.match(panelSource, /power_entity/);
assert.match(panelSource, /energy_import_entity/);
assert.match(panelSource, /energy_export_entity/);
assert.match(panelSource, /elrakning_diagnostics_update/);
assert.match(panelSource, /this\._diagnosticEntries = entries\.slice\(\)/);
assert.match(panelSource, /formatDiagnosticsText\(clipboardEntries, this\.version\)/);
assert.match(panelSource, /_websocketErrorDetails\(error\)/);
assert.match(panelSource, /data-meter-field/);
assert.match(panelSource, /data-meter-consumption-selector/);
assert.match(panelSource, /data-meter-clear-last/);
assert.match(panelSource, /Husets last/);
assert.match(panelSource, /Nät just nu/);
assert.match(panelSource, /displayPowerValue\(power\.consumption_kw\)/);
assert.doesNotMatch(panelSource, /\["Producerat idag", this\._powerState\.solar_energy_kwh, "kWh"\]/);
assert.match(panelSource, /integratePowerHistoryKwh\(points, dayStart, dayEnd, now\)/);
assert.match(panelSource, /_calculatePowerEnergy\("solar"\)/);
assert.match(panelSource, /_calculatePowerEnergy\("consumption"\)/);
assert.match(panelSource, /_calculatePowerEnergy\("charging"\)/);
assert.match(panelSource, /_calculatePowerEnergy\("discharging"\)/);
assert.match(panelSource, /_powerLivePoints = Object\.fromEntries\(\["solar", "consumption", "charging", "discharging", "soc"\]/);
assert.doesNotMatch(panelSource, /\["Förbrukat idag", power\.consumption_energy_kwh, "kWh"\]/);
assert.match(panelSource, /data-power-card="battery-history"/);
assert.match(panelSource, /data-power-card="solar-history"/);
assert.match(panelSource, /id="solar-history-title" class="visually-hidden">Solhistorik<\/h2>/);
assert.match(panelSource, /Batterihistorik/);
assert.match(panelSource, /aria-labelledby="battery-history-title"/);
assert.match(panelSource, /id="battery-history-title" class="visually-hidden">Batterihistorik<\/h2>/);
assert.match(panelSource, /const chart = this\.host\.querySelector\("\[data-battery-history-chart\]"\);\n\s+if \(!card \|\| !chart\) return;/);
assert.doesNotMatch(panelSource, /data-battery-history-status/);
assert.match(panelSource, /--chart-axis-font-size: 10px;/);
assert.match(panelSource, /--chart-axis-font-weight: 400;/);
assert.match(panelSource, /\.battery-history-axis-label,[\s\S]*\.battery-history-day-label,[\s\S]*font-size: var\(--chart-axis-font-size\);[\s\S]*font-weight: var\(--chart-axis-font-weight\);[\s\S]*line-height: var\(--chart-axis-line-height\);/);
assert.match(panelSource, /\.battery-history-axis-label \{[^}]*color: var\(--chart-axis-color\);[^}]*opacity: var\(--chart-axis-opacity\);/);
assert.match(panelSource, /\.battery-history-utilization \{[\s\S]*font-weight: 600;/);
assert.match(panelSource, /battery-history-y-label-rail/);
assert.match(panelSource, /battery-history-x-label-rail/);
assert.match(panelSource, /\.battery-history-x-label \{[\s\S]*top: 62%;[\s\S]*transform: translate\(-50%, -50%\);/);
assert.match(panelSource, /\.solar-history-axis-label,[\s\S]*\.solar-history-day-label,[\s\S]*font-size: var\(--chart-axis-font-size\);[\s\S]*font-weight: var\(--chart-axis-font-weight\);[\s\S]*line-height: var\(--chart-axis-line-height\);/);
assert.match(panelSource, /\.solar-history-axis-label \{[^}]*color: var\(--chart-axis-color\);[^}]*opacity: var\(--chart-axis-opacity\);/);
assert.doesNotMatch(panelSource, /<text class="battery-history-(axis-label|day-label|utilization)"/);
const batteryHistoryMarkup = panelSource.match(/<article class="card battery-history-card"[\s\S]*?<\/article>/)?.[0] || "";
assert.doesNotMatch(batteryHistoryMarkup, /card-heading/);
assert.doesNotMatch(panelSource, /battery-history-meta|data-battery-history-meta/);
assert.match(panelSource, /const capacity = Number\(power\.capacity_kwh\);[\s\S]*buildBatteryDailyHistory\([\s\S]*capacity,[\s\S]*\);/);
assert.match(panelSource, /const height = 320;/);
assert.match(panelSource, /const plot = \{ left: 42, right: 8, top: 12, bottom: 50 \};/);
assert.match(panelSource, /const range = Number\.isFinite\(capacity\) && capacity > 0 \? capacity : Math\.max\(1, maximum\);/);
assert.match(panelSource, /const yLabels = \[range, range \/ 2, 0\];/);
assert.doesNotMatch(panelSource, /data-power-card="battery-history"[^>]*data-config-card-key/);
assert.doesNotMatch(panelSource, /data-power-card="battery-history"[^>]*data-main-card-toggle/);
assert.match(panelSource, /battery-history-row/);
assert.ok(panelSource.indexOf('class="daily-energy-row"') < panelSource.indexOf('class="daily-energy-row battery-history-row"'));
assert.ok(panelSource.indexOf('class="daily-energy-row battery-history-row"') < panelSource.indexOf('data-configuration-cards'));
assert.match(panelSource, /buildBatteryDailyHistory\(/);
assert.match(panelSource, /buildSolarDailyHistory\(/);
assert.match(panelSource, /const values = days\.flatMap\(\(day\) => \[day\.producedKwh, day\.forecastKwh\]\)/);
assert.match(panelSource, /class="solar-history-reference-bar"/);
assert.match(panelSource, /referenceBarWidth/);
assert.match(panelSource, /solar-history-reference-bar" fill="\$\{chartColor\("solarForecast"\)\}"/);
assert.match(panelSource, /solar-history-day\.hovered \.solar-history-reference-bar/);
assert.match(panelSource, /buildSolarHistoryTooltipFields\(\n\s+day,/);
assert.match(panelSource, /renderSharedTooltip\(tooltip/);
assert.match(panelSource, /Prognos hittills:/);
assert.match(panelSource, /Dagsprognos:/);
assert.doesNotMatch(panelSource, /<strong>\$\{day\.date\}<\/strong><span>Producerat:/);
assert.doesNotMatch(panelSource, /tooltip\.innerHTML = `[^`]*utilizationPercent/);
assert.match(panelSource, /\.solar-history-chart \.soc-tooltip > span/);
assert.match(panelSource, /solar_forecast_baselines/);
assert.match(panelSource, /elrakning\/solar_forecast_state/);
assert.match(panelSource, /elrakning_solar_forecast_update/);
assert.match(panelSource, /elrakning_solar_weather_update/);
assert.match(panelSource, /solar_weather/);
assert.doesNotMatch(panelSource, /solar-history-reference-bar[\s\S]*referenceKwh/);
assert.doesNotMatch(panelSource, /Solpotential/);
assert.match(panelSource, /const referenceBarWidth = barWidth;/);
assert.match(panelSource, /solar_array_metadata/);
assert.match(panelSource, /renderSharedTooltip\(tooltip, \{[\s\S]*label: "Laddat"/);
assert.match(panelSource, /renderSharedTooltip\(tooltip, \{[\s\S]*label: "Urladdat"/);
assert.doesNotMatch(panelSource, /tooltip\.innerHTML = `[^`]*<strong>\$\{day\.date\}<\/strong><span>Laddat:/);
assert.doesNotMatch(panelSource, /tooltip\.innerHTML = `[^`]*Kapacitetsutnyttjande:/);
const weatherTooltip = buildSolarHistoryTooltipLines(
  { date: new Date().toLocaleDateString("sv-SE"), producedKwh: 1 },
  null,
  new Date(),
  { source: "smhi", available: true, current: { condition: "partlycloudy", cloud_coverage: 42 } },
);
assert.ok(!weatherTooltip.some((line) => line.startsWith("SMHI:")));
assert.match(panelSource, /battery-history-utilization/);
assert.doesNotMatch(panelSource, /battery-history-hover/);
assert.match(panelSource, /battery-history-day\.hovered \.battery-history-bar/);
assert.match(panelSource, /group\.classList\.add\("hovered"\)/);
assert.match(panelSource, /hoveredDay\?\.classList\.remove\("hovered"\)/);
assert.match(panelSource, /\.soc-tooltip \{[\s\S]*pointer-events: none;/);
assert.doesNotMatch(panelSource, /function bindSharedTooltipCopy/);
assert.doesNotMatch(panelSource, /bindSharedTooltipCopy\(/);
assert.doesNotMatch(panelSource, /pointerdown[\s\S]*copyChartRawData/);
assert.match(panelSource, /data-card-source="energy"/);
assert.match(panelSource, /data-card-source="battery-history"/);
assert.match(panelSource, /data-card-source="solar-history"/);
assert.match(panelSource, /data-card-source="soc"/);
assert.match(panelSource, /_buildCardSourceData\(cardSource\)/);
assert.match(panelSource, /card: "energy"/);
assert.match(panelSource, /card: "soc"/);
assert.match(panelSource, /card: "battery-history"/);
assert.match(panelSource, /card: "solar-history"/);
assert.match(panelSource, /solar_local_kwh/);
assert.match(panelSource, /canonical_points: points/);
assert.match(panelSource, /daily_buckets: days/);
assert.match(panelSource, /forecast_baselines: powerHistory\.solar_forecast_baselines/);
assert.match(panelSource, /text\.textContent = liveSource \|\| isEon \|\| cardSource/);
assert.doesNotMatch(panelSource, /battery: batteryIsConfigured \? \[\["Laddning"[\s\S]*Laddat idag/);
assert.match(panelSource, /series\?\.\[seriesKey\]\?\.points/);
assert.match(panelSource, /data-daily-energy/);
assert.match(panelSource, /Dagens energi/);
assert.match(panelSource, /id="daily-energy-title" class="visually-hidden">Dagens energi<\/h2>/);
assert.equal((panelSource.match(/firstLabel: "Lokalt"/g) || []).length, 2);
assert.doesNotMatch(panelSource, /Använt lokalt/);
assert.doesNotMatch(panelSource, /Lokalt försörjt/);
assert.match(panelSource, /buildEnergyBalance\(solarAvailable \? power\.solar_energy_kwh : null, exportKwh\)/);
assert.match(panelSource, /buildEnergyBalance\(consumptionAvailable \? power\.consumption_energy_kwh : null, importKwh\)/);
assert.match(panelSource, /Math\.max\(0, Math\.min\(100/);
assert.match(panelSource, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
assert.match(panelSource, /\.daily-energy-grid \{\n\s+align-items: start;/);
assert.match(panelSource, /data-soc-card/);
assert.match(panelSource, /Batteri SOC/);
assert.match(panelSource, /\.daily-energy-row \{\n\s+align-items: stretch;\n\s+display: grid;\n\s+gap: 16px;\n\s+grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/);
assert.match(panelSource, /@container \(max-width: 760px\) \{[\s\S]*\.daily-energy-row \{\n\s+align-items: start;/);
assert.match(panelSource, /daily-energy-row[\s\S]*data-daily-energy[\s\S]*data-soc-card/);
assert.doesNotMatch(panelSource, /_syncSocCardHeight|_setupSocCardHeightObserver/);
assert.match(panelSource, /\.live-power-row \{\n\s+align-items: stretch;/);
assert.match(panelSource, /\.live-power-tile \{[\s\S]*grid-template-rows: auto auto auto 5px auto minmax\(0, auto\);/);
assert.match(panelSource, /\.live-power-grid-fuse-status-spacer \{\n\s+display: none;/);
assert.match(panelSource, /\.grid \{\n\s+align-items: stretch;/);
assert.match(panelSource, /\.soc-card \{[\s\S]*display: block;/);
assert.match(panelSource, /\.soc-card \{[\s\S]*min-block-size: 0;/);
assert.match(panelSource, /@media \(min-width: 761px\) \{[\s\S]*\.soc-card \{[\s\S]*contain: size;[\s\S]*display: grid;[\s\S]*grid-template-rows: minmax\(0, 1fr\) auto;[\s\S]*overflow: hidden;/);
assert.match(panelSource, /\.soc-card \.card-source-action \{[\s\S]*justify-self: start;[\s\S]*width: max-content;/);
assert.match(panelSource, /@media \(min-width: 761px\) \{[\s\S]*\.soc-card \.soc-chart \{[\s\S]*height: auto;/);
assert.match(panelSource, /@media \(min-width: 761px\) \{[\s\S]*\.soc-card \.soc-chart \{[\s\S]*box-sizing: border-box;[\s\S]*padding-block: 4px;/);
assert.match(panelSource, /@media \(max-width: 760px\) \{[\s\S]*\.soc-card \{[\s\S]*contain: none;[\s\S]*display: block;[\s\S]*overflow: hidden;/);
assert.match(panelSource, /@media \(max-width: 760px\) \{[\s\S]*\.soc-card \.soc-chart \{[\s\S]*box-sizing: border-box;[\s\S]*padding-block: 0;/);
assert.doesNotMatch(panelSource, /@media \(max-width: 700px\) \{[\s\S]*\.daily-energy-row \{\n\s+grid-template-columns: 1fr;/);
assert.match(panelSource, /\.daily-energy-card \{[\s\S]*min-width: 0;/);
assert.match(panelSource, /\.card\.daily-energy-card \{\n\s+min-height: 0;\n\s+\}/);
assert.match(panelSource, /\.daily-energy-grid \{[\s\S]*margin-top: 0;/);
assert.match(panelSource, /\.daily-energy-part-heading > \*,[\s\S]*\.daily-energy-part-values > \* \{[\s\S]*min-width: 0;[\s\S]*overflow-wrap: normal;[\s\S]*word-break: normal;/);
assert.match(panelSource, /@media \(max-width: 700px\) \{[\s\S]*\.daily-energy-part-heading \{\n\s+display: block;/);
assert.match(panelSource, /\.daily-energy-part-labels,[\s\S]*\.daily-energy-part-values \{[\s\S]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/);
assert.match(panelSource, /\.page \{[\s\S]*container-type: inline-size;/);
assert.match(panelSource, /@container \(max-width: 760px\) \{[\s\S]*\.daily-energy-row \{[\s\S]*grid-template-columns: 1fr;/);
assert.doesNotMatch(panelSource, /@container \(max-width: 220px\) \{[\s\S]*\.daily-energy-grid \{[\s\S]*grid-template-columns: 1fr;/);
assert.doesNotMatch(panelSource, /@container \(max-width: 220px\) \{[\s\S]*\.soc-card-content \{[\s\S]*grid-template-columns: 1fr;/);
assert.match(panelSource, /\.daily-energy-bar \{[\s\S]*height: clamp\(20px, 6cqw, 30px\);[\s\S]*margin: clamp\(8px, 1\.5cqw, 11px\) 0 clamp\(7px, 1\.3cqw, 10px\);/);
assert.match(panelSource, /\.daily-energy-percent \{[\s\S]*font-size: clamp\(10px, 2\.7cqw, 14px\);[\s\S]*line-height: clamp\(20px, 6cqw, 30px\);/);
assert.match(panelSource, /\.daily-energy-percent\.first \{[\s\S]*left: clamp\(4px, 1\.25cqw, 6px\);/);
assert.match(panelSource, /\.daily-energy-percent\.second \{[\s\S]*right: clamp\(4px, 1\.25cqw, 6px\);/);
assert.match(panelSource, /\.daily-energy-total \{[\s\S]*text-align: right;\n\s+\}/);
assert.doesNotMatch(panelSource, /--el-soc-color/);
assert.match(panelSource, /\.soc-card \{\n\s+--soc-color: var\(--el-solar-color\);[\s\S]*display: block;/);
assert.match(panelSource, /\.soc-area \{[\s\S]*fill: var\(--soc-color\);[\s\S]*fill-opacity: \.3;/);
assert.match(panelSource, /\.soc-line \{[\s\S]*stroke: var\(--soc-color\);/);
assert.match(panelSource, /\.soc-estimated-area \{[\s\S]*fill: #5f9f82;[\s\S]*fill-opacity: \.22;/);
assert.match(panelSource, /\.soc-estimated-line \{[\s\S]*stroke: #5f9f82;[\s\S]*stroke-width: 2;/);
assert.match(panelSource, /\.chart-hover-marker-soc \{ fill: var\(--soc-color\); \}/);
assert.match(panelSource, /class="chart-hover-marker chart-hover-marker-soc"/);
assert.match(panelSource, /class="visually-hidden">Batteri SOC<\/h2>/);
assert.match(panelSource, /\.visually-hidden \{[\s\S]*position: absolute;[\s\S]*width: 1px;/);
assert.match(panelSource, /class="battery-history-utilization">\$\{Number\.isFinite\(day\.utilizationPercent\)/);
assert.match(panelSource, /\.battery-history-chart \.soc-tooltip > span,[\s\S]*\.solar-history-chart \.soc-tooltip > span \{[\s\S]*display: block;/);
assert.match(panelSource, /class="card-heading soc-card-heading"/);
assert.match(panelSource, /\.card\.soc-card \{\n\s+min-height: 0;\n\s+\}/);
assert.doesNotMatch(panelSource, /Utnyttjande/);
assert.doesNotMatch(panelSource, /data-capacity-utilization/);
assert.doesNotMatch(panelSource, /capacity-battery/);
assert.doesNotMatch(panelSource, /capacity-utilization/);
assert.doesNotMatch(panelSource, /_syncCapacityUtilizationWidth|_setupCapacityUtilizationWidthObserver|_capacityUtilizationWidthObserver/);
assert.doesNotMatch(panelSource, /\.soc-card-content/);
assert.match(panelSource, /class="card soc-card"[\s\S]*class="soc-chart" data-soc-chart/);
assert.doesNotMatch(panelSource, /@container \(max-width: 220px\) \{[\s\S]*\.soc-card-content \{[\s\S]*grid-template-columns: 1fr;/);
assert.match(panelSource, /_capacityUtilizationPercent\(\)/);
assert.doesNotMatch(panelSource, /\.soc-chart \{[^}]*flex:\s*1/);
assert.match(panelSource, /\.soc-chart \{[\s\S]*margin: 0;[\s\S]*min-height: 0;[\s\S]*width: 100%;/);
assert.match(panelSource, /\.soc-chart-svg \{[\s\S]*height: 100%;[\s\S]*width: 100%;/);
assert.match(panelSource, /\.soc-chart-svg \{[\s\S]*overflow: visible;/);
assert.doesNotMatch(panelSource, /\.soc-chart-svg \{[\s\S]*aspect-ratio: 960 \/ 340;/);
assert.match(panelSource, /<svg class="soc-chart-svg" preserveAspectRatio="none" viewBox="0 0 \$\{width\} \$\{height\}"/);
assert.match(panelSource, /const height = 340;/);
assert.match(panelSource, /\.soc-label-rail \{[\s\S]*position: absolute;[\s\S]*width: 4\.583333%;/);
assert.match(panelSource, /\.soc-label \{[\s\S]*font-size: var\(--chart-axis-font-size\);[\s\S]*font-weight: var\(--chart-axis-font-weight\);[\s\S]*line-height: var\(--chart-axis-line-height\);[\s\S]*position: absolute;[\s\S]*left: 0;[\s\S]*right: 0;[\s\S]*text-align: center;[\s\S]*transform: translateY\(-50%\);/);
assert.match(panelSource, /const plot = \{ left: 44, right: 8, top: 8, bottom: 8 \};/);
assert.match(panelSource, /const xStart = dayStart\.getTime\(\);/);
assert.match(panelSource, /const xEnd = points\.at\(-1\)\.timestamp;/);
assert.match(panelSource, /const xDuration = Math\.max\(1, xEnd - xStart\);/);
assert.match(panelSource, /pointerToPlotCoordinates\(svg, event, plot, width, height\)/);
assert.match(panelSource, /if \(!pointer\?\.inside\)/);
assert.doesNotMatch(panelSource, /const clampedSvgX =/);
assert.match(panelSource, /const timestamp = xStart \+ plotRatio \* xDuration;/);
assert.match(panelSource, /const singletonMarkup = segments\.filter\(\(segment\) => segment\.length === 1\)/);
assert.match(panelSource, /const estimatedSegments = \[\];/);
assert.match(panelSource, /estimatedSegments\.push\(\[points\[index\], point\]\)/);
assert.match(panelSource, /const estimatedMarkup = estimatedSegments\.map/);
assert.match(panelSource, /\$\{gridMarkup\}\$\{lineMarkup\}\$\{estimatedMarkup\}\$\{singletonMarkup\}/);
assert.match(panelSource, /class="soc-singleton"/);
assert.match(panelSource, /\$\{gridMarkup\}\$\{lineMarkup\}\$\{estimatedMarkup\}\$\{singletonMarkup\}/);
assert.match(panelSource, /\[0, 50, 100\]\.map\(\(level\)/);
assert.match(panelSource, /class="soc-label top">100<\/span><span class="soc-label middle">50<\/span><span class="soc-label bottom">0<\/span>/);
assert.doesNotMatch(panelSource, /<text class="soc-label"/);
assert.doesNotMatch(panelSource, /const timeLabels =/);
assert.doesNotMatch(panelSource, /\$\{timeLabels\}/);
assert.match(panelSource, /series\?\.soc\?\.points/);
assert.match(panelSource, /value_percent/);
assert.match(panelSource, /Math\.max\(0, Math\.min\(100, value\)\)/);
assert.match(panelSource, /Ingen historik idag/);
assert.match(panelSource, /renderSharedTooltip\(tooltip, \{[\s\S]*label: "Laddnivå"/);
assert.doesNotMatch(panelSource, /integratePowerHistoryKwh\([^)]*soc/);
assert.match(panelSource, /\["Import idag", "energy_import_entity"\]/);
assert.match(panelSource, /\["Export idag", "energy_export_entity"\]/);
assert.doesNotMatch(panelSource, /\["Import idag", meter\.energy_import_kwh, "kWh"\]/);
assert.doesNotMatch(panelSource, /\["Export idag", meter\.energy_export_kwh, "kWh"\]/);
assert.match(panelSource, /Byt sensor/);
assert.match(panelSource, /displayPowerValue\(meter\.power_kw\)/);
assert.match(panelSource, /solar_entities: Array\.isArray\(current\.solar_entities\)/);
assert.match(panelSource, /charging_entity: current\.charging_entity/);
assert.match(panelSource, /mapping\.consumption_entity = ""/);
assert.match(panelSource, /powerMapping\.consumption_entity/);
assert.match(panelSource, /elrakning\/power_save/);
assert.match(panelSource, /save\.disabled = false/);
assert.doesNotMatch(panelSource, /radio\.type = "radio"/);
assert.doesNotMatch(panelSource, /data-meter-candidates/);
assert.doesNotMatch(panelSource, /data-meter-search/);
assert.doesNotMatch(panelSource, /selectedEntities/);
assert.doesNotMatch(panelSource, /selectedCandidate/);
assert.match(panelSource, /meter_save_payload_types/);
assert.match(panelSource, /meter_mapping_created/);
assert.match(panelSource, /data-meter-clear/);
assert.match(panelSource, /data-meter-invert-power/);
assert.match(panelSource, /Invertera effekt/);
assert.match(panelSource, /mapping\.invert_power = invertToggle\.checked/);
assert.match(panelSource, /invertToggle\.checked = meterResponse\.invert_power === true/);
assert.match(panelSource, /elrakning\/meter_store_clear/);
assert.match(panelSource, /elrakning\/meter_power_history/);
assert.match(panelSource, /elrakning_meter_power_update/);
assert.match(panelSource, /data-chart-layer="spot"/);
assert.match(panelSource, /data-chart-layer="average"/);
assert.match(panelSource, /data-chart-layer="import"/);
assert.match(panelSource, /data-chart-layer="export"/);
assert.match(panelSource, /data-price-layer="electricity"/);
assert.match(panelSource, /data-price-layer="grid"/);
assert.match(panelSource, /data-invoice-estimate-card/);
assert.match(panelSource, /Estimerad faktura/);
assert.match(panelSource, /grid-template-columns: repeat\(5, minmax\(0, 1fr\)\)/);
assert.match(panelSource, /\.live-power-tile\.invoice-estimate-card \{[\s\S]*min-height: 0;/);
assert.match(panelSource, /@media \(max-width: 760px\) \{[\s\S]*\.invoice-estimate-card \{[\s\S]*grid-column: 1 \/ -1;/);
assert.match(panelSource, /data-live-power-tile="battery"[\s\S]*data-invoice-estimate-card/);
assert.match(panelSource, /class="live-power-title">Estimerad faktura/);
assert.match(panelSource, /class="live-power-title">Estimerad faktura<\/span><\/div>\s*<span class="live-power-grid-meta invoice-estimate-month"/);
assert.match(panelSource, /\.invoice-estimate-month \{[\s\S]*justify-self: start;/);
assert.match(panelSource, /\.invoice-estimate-month \{[\s\S]*margin-left: 0;[\s\S]*text-align: left;/);
assert.match(panelSource, /class="live-power-value" data-invoice-estimate-total/);
assert.match(panelSource, /data-invoice-estimate-total/);
assert.match(panelSource, /_formatInvoiceMonth\(estimate\.month\)\.split\(" "\)\[0\]/);
assert.match(panelSource, /const invoicePeriod = invoicePeriodLabel\(latest\);/);
assert.doesNotMatch(panelSource, /latest\.invoice_date \|\| latest\.month/);
assert.match(panelSource, /provider-invoice-cost/);
assert.match(panelSource, /data-provider-invoice-cost="elhandel"/);
assert.match(panelSource, /data-provider-invoice-cost="elnet"/);
assert.match(panelSource, /estimated_month_total_sek/);
assert.match(panelSource, /total_so_far_sek/);
assert.doesNotMatch(panelSource, /data-invoice-estimate-copy-feedback/);
assert.match(panelSource, /data-live-power-source="invoice"/);
assert.doesNotMatch(panelSource, /_updateInvoiceEstimateInteractivity/);
assert.doesNotMatch(panelSource, /invoice-estimate-card\.debug-copy-enabled/);
assert.match(panelSource, /const CHART_COLORS = Object\.freeze/);
assert.match(panelSource, /fill="\$\{chartColor\("solar"\)\}"/);
assert.match(panelSource, /fill="\$\{chartColor\("solarForecast"\)\}"/);
assert.match(panelSource, /stroke="\$\{color\}"/);
assert.match(panelSource, /fill="\$\{color\}"/);
assert.match(panelSource, /fill="\$\{chartColor\(className\)\}"/);
assert.match(panelSource, /chartColor\("charging"\)/);
assert.match(panelSource, /chartColor\("discharging"\)/);
assert.match(panelSource, /chartColor\("soc"\)/);
assert.doesNotMatch(panelSource, /\.solar-history-reference-bar \{[^}]*color-mix\(/);
assert.doesNotMatch(panelSource, /data-invoice-estimate-copy>Kopiera raw-data/);
assert.doesNotMatch(panelSource, /data-invoice-estimate-grid/);
assert.doesNotMatch(panelSource, /data-invoice-estimate-status/);
assert.doesNotMatch(panelSource, /Prognos för månaden/);
assert.doesNotMatch(panelSource, /data-invoice-estimate-total[\s\S]*Hittills/);
assert.match(panelSource, /forecast_method/);
assert.match(panelSource, /buildInvoiceProvenance\(/);
assert.match(panelSource, /buildInvoiceEstimate\(/);
assert.match(panelSource, /elrakning\/billing_history/);
assert.match(panelSource, /this\._billingHistory/);
assert.match(panelSource, /billingHistory\?\.price_periods/);
assert.match(panelSource, /trade_weighted_average_ore_per_kwh/);
assert.match(panelSource, /export_credit: false/);
assert.match(panelSource, /class="price-filter-toggle"/);
assert.match(panelSource, /data-price-toggle/);
assert.match(panelSource, /price-filter-track/);
assert.doesNotMatch(panelSource, /chart-legend-swatch electricity/);
assert.doesNotMatch(panelSource, /chart-legend-swatch grid/);
assert.match(panelSource, /this\._spotBarsVisible/);
assert.match(panelSource, /elrakning\/ui_preferences\/get/);
assert.match(panelSource, /elrakning\/ui_preferences\/set/);
assert.match(panelSource, /_loadChartPreferences/);
assert.match(panelSource, /_persistChartPreferences/);
assert.match(panelSource, /async _persistChartPreferences\(updates = \{\}\)/);
assert.match(panelSource, /\.\.\.updates/);
assert.match(panelSource, /this\._persistChartPreferences\(\{ price_comparison: \{ \.\.\.this\._priceComparisonVisible \} \}\)/);
assert.match(panelSource, /response\?\.price_comparison/);
assert.match(panelSource, /this\._chartPreferencesSavePromise = Promise\.resolve\(\);/);
assert.match(panelSource, /this\._chartPreferencesSavePromise = this\._chartPreferencesSavePromise[\s\S]*\.catch\(\(\) => \{\}\)[\s\S]*\.then\(async/);
assert.match(panelSource, /price_comparison: \{ \.\.\.this\._priceComparisonVisible \}/);
assert.match(panelSource, /chart_layers/);
assert.match(panelSource, /price_comparison: \{ \.\.\.this\._priceComparisonVisible \}/);
assert.match(panelSource, /_applyPriceComparisonState/);
assert.match(panelSource, /this\._priceComparisonVisible\[layer\] = input\.checked/);
assert.match(panelSource, /input\.checked = this\._priceComparisonVisible\.grid/);
assert.doesNotMatch(panelSource, /this\._priceComparisonVisible\.grid = false/);
assert.doesNotMatch(panelSource, /class="chart-legend-toggle active" data-chart-layer/);
assert.match(panelSource, /this\._averageLineVisible = true/);
assert.match(panelSource, /chart-legend-swatch\.average \{[\s\S]*background: var\(--el-price-normal-color\)/);
assert.match(panelSource, /if \(layer === "average"\) \{[\s\S]*this\._averageLineVisible = !this\._averageLineVisible/);
assert.match(panelSource, /this\._priceComparisonVisible/);
assert.match(panelSource, /_comparisonPrice/);
assert.match(panelSource, /grid_cost_ex_vat/);
assert.match(panelSource, /grid_price/);
assert.match(panelSource, /variable_total_ore_per_kwh_gross/);
assert.match(panelSource, /this\._chartTooltipDetails\.set\(index, \{/);
assert.match(panelSource, /createPriceDebugText\(\{ time, value, details \}\)/);
assert.match(panelSource, /grid_contract_preview_applied|grid_provider/);
assert.doesNotMatch(panelSource, /chart-price-layer/);
assert.match(panelSource, /const prices = periods\.map\(\(period\) => this\._periodCustomerPrice\(period\)\)/);
assert.match(panelSource, /const comparisonPrice = this\._comparisonPrice\(period\)/);
assert.match(panelSource, /data-price-layer="grid"/);
assert.match(panelSource, /input\.disabled = !available/);
assert.match(panelSource, /control\.classList\.toggle\("is-disabled", !available\)/);
assert.match(panelSource, /chart-meter-import/);
assert.match(panelSource, /chart-meter-export/);
assert.match(panelSource, /chart-meter-gridline/);
assert.match(panelSource, /const meterGrid = meterVisible/);
assert.match(panelSource, /const meterGridLevels = Array\.from/);
assert.match(panelSource, /const plot = \{ left: 42, right: 8/);
assert.doesNotMatch(panelSource, /chart-meter-label" text-anchor="start" x="8"/);
assert.match(panelSource, /chart-axis-overlay-label/);
assert.match(panelSource, /chart-axis-overlay-x-cull/);
assert.match(panelSource, /@container price-chart \(max-width: 520px\)/);
assert.match(panelSource, /\.phase-history-time-label \{?[^}]*font-size: var\(--chart-axis-font-size\);/);
assert.match(panelSource, /\.chart-label \{[^}]*font-size: var\(--chart-axis-font-size\);[^}]*font-weight: var\(--chart-axis-font-weight\);/);
assert.match(panelSource, /\.chart-meter-label \{[^}]*font-size: var\(--chart-axis-font-size\);[^}]*font-weight: var\(--chart-axis-font-weight\);/);
assert.doesNotMatch(panelSource, /chart-meter-axis/);
assert.doesNotMatch(panelSource, /const meterAxis/);
assert.match(panelSource, /#F0A06A/);
assert.match(panelSource, /#72AAF6/);
assert.equal((panelSource.match(/--el-import-color: #F0A06A/g) || []).length, 1);
assert.equal((panelSource.match(/--el-export-color: #72AAF6/g) || []).length, 1);
const mobileMediaIndex = panelSource.indexOf("@media (max-width: 600px)");
const globalImportIndex = panelSource.indexOf("--el-import-color: #F0A06A");
const globalExportIndex = panelSource.indexOf("--el-export-color: #72AAF6");
assert.ok(globalImportIndex >= 0 && globalImportIndex < mobileMediaIndex);
assert.ok(globalExportIndex >= 0 && globalExportIndex < mobileMediaIndex);
assert.match(panelSource, /\.price-section \{\n\s+--solar-color: var\(--el-solar-color, #77C2A1\);\n\s+--consumption-color: var\(--el-consumption-color, #E87570\);\n\s+--grid-import-color: var\(--el-import-color, #F0A06A\);\n\s+--grid-export-color: var\(--el-export-color, #72AAF6\);\n\s+--charging-color: var\(--el-charging-color, #B76A8F\);\n\s+--discharging-color: var\(--el-discharging-color, #DF5C8A\);/);
assert.match(panelSource, /\.chart-meter-import \{\n\s+stroke: var\(--grid-import-color\);/);
assert.match(panelSource, /\.chart-meter-export \{\n\s+stroke: var\(--grid-export-color\);/);
assert.match(panelSource, /stroke-width: 1\.6/);
assert.match(panelSource, /opacity: \.82/);
assert.match(panelSource, /\.chart-meter-gridline \{\n\s+stroke: var\(--divider-color\);\n\s+stroke-width: 1;\n\s+opacity: \.28;/);
assert.doesNotMatch(panelSource, /const meterPath =/);
assert.match(panelSource, /prepareMeterDisplayPoints\(points\)/);
assert.match(panelSource, /POWER_DISPLAY_THRESHOLD_KW = 0\.1/);
assert.match(panelSource, /import_kw: Number\.isFinite\(importKw\) \? importKw : null/);
assert.match(panelSource, /export_kw: Number\.isFinite\(exportKw\) \? exportKw : null/);
assert.match(panelSource, /powerDisplayPoints\[key\] = powerCanonicalPoints\[key\]\.map/);
assert.match(panelSource, /meterDisplayPoints\.flatMap/);
assert.match(panelSource, /isVisiblePowerValue\(details\?\.import_kw\)/);
assert.match(panelSource, /isVisiblePowerValue\(details\?\.export_kw\)/);
assert.match(panelSource, /isVisiblePowerValue\(value\)/);
assert.match(panelSource, /latestByTimestamp = new Map\(\)/);
assert.doesNotMatch(panelSource, /smoothSignedMeterPoints/);
assert.match(panelSource, /buildCanonicalMeterPoints\(points, dayStart, dayEnd, slotMs = 5 \* 60 \* 1000, maxDistanceMs = 2\.5 \* 60 \* 1000\)/);
assert.match(panelSource, /nearestMeterPoint\(points, slotTimestamp, maxDistanceMs\)/);
assert.match(panelSource, /raw_timestamp: hasSample \? selected\.timestamp : null/);
assert.match(panelSource, /for \(let slotTimestamp = dayStartMs; slotTimestamp < dayEndMs; slotTimestamp \+= slotMs\)/);
assert.match(panelSource, /buildMeterDisplaySegments\(points, key\)/);
assert.match(panelSource, /buildThresholdClippedSegments\(points, key\)/);
assert.match(panelSource, /POWER_DISPLAY_THRESHOLD_KW - previousValue/);
assert.match(panelSource, /timestamp: previousTime \+ ratio \* \(currentTime - previousTime\)/);
assert.match(panelSource, /synthetic: true/);
assert.match(panelSource, /currentTime - previousTime === 5 \* 60 \* 1000/);
assert.match(panelSource, /buildSmoothMeterPath\(segment, key, x, meterY\)/);
assert.match(panelSource, /buildMeterDisplayMarkup\(points, key, className, x, meterY\)/);
assert.match(panelSource, /if \(segment\.length < 2\) return ""/);
assert.doesNotMatch(panelSource, /chart-power-point/);
assert.doesNotMatch(panelSource, /chart-power-point\.chart-meter-import/);
assert.doesNotMatch(panelSource, /chart-power-point\.chart-meter-export/);
assert.doesNotMatch(panelSource, /value_kw: isVisiblePowerValue\(point\.value_kw\) \? point\.value_kw : null/);
assert.match(panelSource, /segment\.coordinates\.length === 1/);
assert.match(panelSource, /const lateDayFallback = !facts\.has_full_two_hour_window/);
assert.match(panelSource, /normalizeMeterValue\(point\.import_kw\)/);
assert.match(panelSource, /normalizeMeterValue\(point\.export_kw\)/);
assert.doesNotMatch(panelSource, /import_kw: Number\(point\.import_kw\) \|\| 0/);
assert.doesNotMatch(panelSource, /export_kw: Number\(point\.export_kw\) \|\| 0/);
assert.doesNotMatch(panelSource, /points\[start - 1\]\[key\] === 0/);
assert.doesNotMatch(panelSource, /points\[end \+ 1\]\[key\] === 0/);
assert.match(panelSource, /if \(segment\.length < 2\) return \"\"/);
assert.match(panelSource, /const meterCanonicalPoints = this\.buildCanonicalMeterPoints/);
assert.match(panelSource, /const meterDisplayPoints = this\.prepareMeterDisplayPoints\(meterCanonicalPoints\)/);
assert.doesNotMatch(panelSource, /const meterDisplayPoints = this\.smoothSignedMeterPoints/);
assert.match(panelSource, /const meterMaximum = Math\.max\(/);
assert.match(panelSource, /const meterBase = Math\.max\(10, meterMaximum\)/);
const meterRangeForMaximum = (meterMaximum) => {
  const meterBase = Math.max(10, meterMaximum);
  const meterMagnitude = 10 ** Math.floor(Math.log10(meterBase / 4));
  const meterNormalized = (meterBase / 4) / meterMagnitude;
  const meterStepFactor = meterNormalized <= 1 ? 1 : meterNormalized <= 2 ? 2 : meterNormalized <= 5 ? 5 : 10;
  const meterStep = meterStepFactor * meterMagnitude;
  return Math.ceil(meterBase / meterStep) * meterStep;
};
assert.equal(meterRangeForMaximum(0.8), 10);
assert.equal(meterRangeForMaximum(4.2), 10);
assert.equal(meterRangeForMaximum(9.9), 10);
assert.equal(meterRangeForMaximum(10), 10);
assert.ok(meterRangeForMaximum(10.1) > 10);
assert.match(panelSource, /const meterY = \(value\) => plot\.top \+ plotHeight - \(Math\.max\(0, Number\(value\) \|\| 0\) \/ meterRange\) \* plotHeight/);
assert.match(panelSource, /meterPointAt = \(timestamp\) => meterPoints\.reduce/);
assert.match(panelSource, /Är du säker\? Alla valda mätare tas bort\./);
assert.match(panelSource, /renderSelectors\(response\);/);
assert.match(panelSource, /priceColorDetails/);
assert.match(panelSource, /createPriceDebugText/);
assert.match(panelSource, /spot_price_ex_vat: Number\(period\.spot_price_ex_vat\) \* 100/);
assert.match(panelSource, /electricity_cost_ex_vat: Number\.isFinite/);
assert.match(panelSource, /subtotal_ex_vat: Number\(period\.subtotal_ex_vat\) \* 100/);
assert.match(panelSource, /vat: Number\(period\.vat\) \* 100/);
assert.match(panelSource, /customer_price: Number\(period\.customer_price\) \* 100/);
assert.match(panelSource, /price-value\.current strong\.cheap/);
assert.match(panelSource, /price-value\.current strong\.normal/);
assert.match(panelSource, /price-value\.current strong\.expensive/);
assert.match(panelSource, /\.price-value strong\.cheap \{[\s\S]*color: var\(--el-price-cheap-color\)/);
assert.match(panelSource, /\.price-value strong\.expensive \{[\s\S]*color: var\(--el-price-expensive-color\)/);
assert.match(panelSource, /if \(key === "lowest"\) element\.classList\.add\("cheap"\)/);
assert.match(panelSource, /if \(key === "highest"\) element\.classList\.add\("expensive"\)/);
assert.match(panelSource, /priceCategory\(prices\[currentIndex\], colorBands\)/);
assert.match(panelSource, /\.chart-bar\.cheap \{\s*fill: #67C98C;\s*fill-opacity: \.32;/);
assert.match(panelSource, /\.chart-bar\.normal \{\s*fill: #B9A05D;\s*fill-opacity: \.32;/);
assert.match(panelSource, /\.chart-bar\.expensive \{\s*fill: #E4687D;\s*fill-opacity: \.32;/);
assert.equal((panelSource.match(/\.chart-bar\.(?:cheap|normal|expensive) \{[\s\S]*?fill: color-mix\(/g) || []).length, 0);
assert.doesNotMatch(panelSource, /\.daily-energy-segment \{\n\s+filter:/);
assert.match(panelSource, /\.daily-energy-segment\.local \{[\s\S]*background-color: var\(--daily-energy-local-color, #77C2A1\)/);
assert.match(panelSource, /\.daily-energy-segment\.export \{[\s\S]*background-color: var\(--daily-energy-export-color, #72AAF6\)/);
assert.match(panelSource, /\.daily-energy-segment\.import \{[\s\S]*background-color: var\(--daily-energy-import-color, #F0A06A\)/);
assert.match(panelSource, /daily-energy-percent first/);
assert.match(panelSource, /daily-energy-percent second/);
assert.match(panelSource, /\.daily-energy-percent\.first \{[\s\S]*left: clamp\(4px, 1\.25cqw, 6px\);/);
assert.match(panelSource, /\.daily-energy-percent\.second \{[\s\S]*right: clamp\(4px, 1\.25cqw, 6px\);/);
assert.match(panelSource, /\.daily-energy-bar \{[\s\S]*height: clamp\(20px, 6cqw, 30px\);[\s\S]*margin: clamp\(8px, 1\.5cqw, 11px\) 0 clamp\(7px, 1\.3cqw, 10px\);/);
assert.match(panelSource, /\.daily-energy-percent \{[\s\S]*font-size: clamp\(10px, 2\.7cqw, 14px\);[\s\S]*line-height: clamp\(20px, 6cqw, 30px\);/);
assert.match(panelSource, /<div class="daily-energy-part-values"><span>\$\{formatEnergy\(firstValue\)\}<\/span><span>\$\{formatEnergy\(secondValue\)\}<\/span><\/div>/);
assert.match(panelSource, /\.daily-energy-part-values \{[\s\S]*font-size: inherit;/);
assert.doesNotMatch(panelSource, /\.daily-energy-part-values \{[^}]*font-size: var\(--price-card-text-size\);/);
assert.match(panelSource, /\.chart-bar \{[\s\S]*fill-opacity: \.72;[\s\S]*stroke: #111111;[\s\S]*stroke-width: \.7;/);
assert.doesNotMatch(panelSource, /\.chart-bar \{[^}]*stroke-opacity/);
assert.doesNotMatch(panelSource, /\.chart-bar \{[^}]*stroke: color-mix/);
assert.match(panelSource, /\.chart-power-area \{[\s\S]*pointer-events: none;[\s\S]*stroke: none;[\s\S]*fill-opacity: \.18;/);
assert.match(panelSource, /\.chart-power-area-solar \{ fill: var\(--solar-color\); \}/);
assert.match(panelSource, /\.chart-power-area-import \{ fill: var\(--grid-import-color\); \}/);
assert.match(panelSource, /\.chart-power-area-export \{ fill: var\(--grid-export-color\); \}/);
assert.match(panelSource, /\.chart-power-area-consumption \{ fill: var\(--consumption-color\); \}/);
assert.match(panelSource, /\.chart-power-area-charging \{ fill: var\(--charging-color\); \}/);
assert.match(panelSource, /\.chart-power-area-discharging \{ fill: var\(--discharging-color\); \}/);
assert.match(panelSource, /\.chart-interpolated-line \{[\s\S]*opacity: \.45;/);
assert.match(panelSource, /\.chart-interpolated-area \{[\s\S]*opacity: \.35;/);
assert.match(panelSource, /buildMeterDisplayAreaMarkup\(points, key, className, x, meterY\)/);
assert.match(panelSource, /buildContinuousGapPairs\(points, key\)/);
assert.match(panelSource, /class="\$\{className\} chart-interpolated-line"/);
assert.match(panelSource, /class="\$\{className\} chart-interpolated-area"/);
assert.match(panelSource, /buildMeterDisplayAreaMarkup\(powerDisplayPoints\.solar, "value_kw", "chart-power-area chart-power-area-solar"/);
assert.match(panelSource, /buildMeterDisplayAreaMarkup\(meterDisplayPoints, "import_kw", "chart-power-area chart-power-area-import"/);
assert.match(panelSource, /buildMeterDisplayAreaMarkup\(meterDisplayPoints, "export_kw", "chart-power-area chart-power-area-export"/);
assert.match(panelSource, /buildMeterDisplayAreaMarkup\(powerDisplayPoints\.consumption, "value_kw", "chart-power-area chart-power-area-consumption"/);
assert.match(panelSource, /buildMeterDisplayAreaMarkup\(powerDisplayPoints\.charging, "value_kw", "chart-power-area chart-power-area-charging"/);
assert.match(panelSource, /buildMeterDisplayAreaMarkup\(powerDisplayPoints\.discharging, "value_kw", "chart-power-area chart-power-area-discharging"/);
assert.match(panelSource, /if \(segment\.length < 2\) return "";/);
assert.match(panelSource, /data-price-dynamic="grid"/);
assert.match(panelSource, /data-price-dynamic="areas"/);
assert.match(panelSource, /data-price-dynamic="lines"/);
assert.equal((panelSource.match(/buildMeterDisplayAreaMarkup\(/g) || []).length, 7);
assert.match(panelSource, /data-power-battery-mode role="radiogroup"/);
assert.doesNotMatch(panelSource, /data-power-battery-mode><select/);
assert.match(panelSource, /value="combined"><span>Kombinerad sensor/);
assert.match(panelSource, /value="separate"><span>Separata sensorer/);
assert.match(panelSource, /batteryModeOptions\.forEach/);
assert.match(panelSource, /battery-mode-option:has\(input:checked\)/);
assert.match(panelSource, /battery-mode-option:focus-within/);
assert.match(panelSource, /data-power-selectors><\/div>\n\s+<label class="battery-invert-row" data-power-invert-battery-wrap/);
assert.match(panelSource, /data-power-invert-battery/);
assert.match(panelSource, /battery_power_entity/);
assert.match(panelSource, /invert_battery_power/);
assert.match(panelSource, /id="power-title"><\/h2>/);
assert.match(panelSource, /solar: "Konfigurera sol"/);
assert.match(panelSource, /consumption: "Konfigurera last"/);
assert.match(panelSource, /battery: "Konfigurera batteri"/);
assert.match(panelSource, /\.battery-mode-wrap\[hidden\],[\s\S]*\.battery-invert-row\[hidden\],[\s\S]*display: none;/);
assert.match(panelSource, /\.power-solar-analysis-status\[hidden\],[\s\S]*\[data-power-add-solar\]\[hidden\][\s\S]*display: none;/);
assert.match(panelSource, /batteryModeWrap\.hidden = mode !== "battery"/);
assert.match(panelSource, /invertBatteryWrap\.hidden = mode !== "battery" \|\| batteryMode !== "combined"/);
assert.match(panelSource, /solarAnalysisStatus\.hidden = mode !== "solar" \|\| sunAvailable/);
assert.match(panelSource, /addSolar\.hidden = mode !== "solar"/);
assert.match(panelSource, /const fieldsFor = \(selectedMode\) => selectedMode === "solar"/);
assert.match(panelSource, /displayPowerValue\(value\)/);
assert.doesNotMatch(panelSource, /\.chart-bar\.cheap \{[^}]*\sopacity:/);
assert.doesNotMatch(panelSource, /\.chart-bar\.normal \{[^}]*\sopacity:/);
assert.doesNotMatch(panelSource, /\.chart-bar\.expensive \{[^}]*\sopacity:/);
const chartBarCheapIndex = panelSource.indexOf(".chart-bar.cheap {");
const chartBarNormalIndex = panelSource.indexOf(".chart-bar.normal {");
const chartBarExpensiveIndex = panelSource.indexOf(".chart-bar.expensive {");
assert.ok(chartBarCheapIndex >= 0 && chartBarCheapIndex < mobileMediaIndex);
assert.ok(chartBarNormalIndex >= 0 && chartBarNormalIndex < mobileMediaIndex);
assert.ok(chartBarExpensiveIndex >= 0 && chartBarExpensiveIndex < mobileMediaIndex);
assert.match(panelSource, /\.chart-bar\.cheap \{\s*fill: #67C98C;\s*fill-opacity: \.32;/);
assert.match(panelSource, /\.chart-bar\.normal \{\s*fill: #B9A05D;\s*fill-opacity: \.32;/);
assert.match(panelSource, /\.chart-bar\.expensive \{\s*fill: #E4687D;\s*fill-opacity: \.32;/);
assert.match(panelSource, /\.solar-history-reference-bar \{\s*fill-opacity: \.9;/);
assert.doesNotMatch(panelSource, /\.solar-history-reference-bar \{[^}]*color-mix\(/);
assert.match(panelSource, /\.daily-energy-segment\.local \{\s*background-color: var\(--daily-energy-local-color, #77C2A1\)/);
assert.match(panelSource, /\.daily-energy-segment\.export \{\s*background-color: var\(--daily-energy-export-color, #72AAF6\)/);
assert.match(panelSource, /\.daily-energy-segment\.import \{\s*background-color: var\(--daily-energy-import-color, #F0A06A\)/);
assert.doesNotMatch(panelSource, /\.daily-energy-segment\.(?:local|supply|export|import) \{[^}]*color-mix\(/);
assert.match(panelSource, /\.daily-energy-segment \{[\s\S]*display: block;[\s\S]*flex: 0 0 auto;[\s\S]*flex-basis: auto;[\s\S]*height: 100%;/);
assert.match(panelSource, /\.daily-energy-segment \{[\s\S]*opacity: \.6;/);
assert.doesNotMatch(panelSource, /\.daily-energy-segment[^{]*\{[^}]*opacity: (?!\.6)/);
assert.doesNotMatch(panelSource, /marker-highlight/);
assert.match(panelSource, /return `<rect class="chart-bar \$\{category\}" fill="\$\{barColor\}"/);
assert.doesNotMatch(panelSource, /price-marker-label/);
assert.doesNotMatch(panelSource, /priceMarkers/);
assert.doesNotMatch(panelSource, /markerGroups/);
assert.doesNotMatch(panelSource, /markerLayouts/);
assert.doesNotMatch(panelSource, /markerMinY|markerHeight|markerGap/);
assert.ok((panelSource.match(/var\(--ha-card-background, var\(--card-background-color\)\)/g) || []).length >= 4);
assert.match(panelSource, /_buildVisibleTooltipFields\(comparisonPrice, details, layers = this\._chartLayerState\(\)\)/);
assert.match(panelSource, /snapTooltipTimestamp\(/);
assert.match(panelSource, /tooltipTimestamp = snapTooltipTimestamp/);
assert.match(panelSource, /return start <= tooltipTimestamp && tooltipTimestamp < end/);
assert.match(panelSource, /const time = this\.formatTime\(new Date\(tooltipTimestamp\)\)/);
assert.match(panelSource, /nearestMeterPoint\(this\._meterTooltipPoints, timestamp\)/);
assert.match(panelSource, /const rawMeterPoint = this\._meterPointAtNearest\(tooltipTimestamp\)/);
assert.match(panelSource, /const value = visibleLayers\.spot && Number\.isFinite\(comparisonPrice\)/);
assert.doesNotMatch(panelSource, /data-tooltip=/);
assert.match(panelSource, />Sol\s*</);
assert.match(panelSource, /data-preview-layer="consumption"[\s\S]*>Last/);
assert.match(panelSource, /Laddning/);
assert.match(panelSource, /Urladdning/);
assert.doesNotMatch(panelSource, /\["Laddnivå", this\._powerState\.soc_percent, "%"\]/);
assert.doesNotMatch(panelSource, /\["Kapacitet", this\._powerState\.capacity_kwh, "kWh"\]/);
assert.match(panelSource, /<p class="status">Spotpris · öre\/kWh<\/p>/);
assert.match(panelSource, /<span>Handel<\/span>/);
assert.match(panelSource, /<span>Nät<\/span>/);
assert.doesNotMatch(panelSource, /<p class="status">Nord Pool · Spotpris/);
assert.doesNotMatch(panelSource, /data-price-layer="electricity">[\s\S]*<span>Elhandel<\/span>/);
assert.doesNotMatch(panelSource, /data-price-layer="grid">[\s\S]*<span>Elnät<\/span>/);
assert.match(panelSource, /container-name: price-card/);
assert.match(panelSource, /container-type: inline-size/);
assert.match(panelSource, /\.section-heading h2,[\s\S]*font-size: var\(--card-title-size\)/);
assert.match(panelSource, /\.price-section \.section-heading h2 \{[\s\S]*font-size: clamp\(19px, 4\.7cqw, 22px\)/);
assert.match(panelSource, /@supports \(font-size: 1cqw\)[\s\S]*\.price-section \.price-comparison-controls \{[\s\S]*gap: 6px/);
assert.match(panelSource, /\.price-filter-toggle \{[\s\S]*font-size: 10px/);
assert.match(panelSource, /\.price-filter-track \{[\s\S]*height: 16px[\s\S]*--knob-size: 11px[\s\S]*--track-padding: 2px[\s\S]*width: 27px/);
assert.doesNotMatch(panelSource, /\.price-section \.price-filter-track \{[\s\S]*clamp\(/);
assert.doesNotMatch(panelSource, /\.price-section \.price-filter-toggle \{[\s\S]*font-size: var\(--price-card-text-size\)/);
assert.match(panelSource, /\.price-chart-legend \{[\s\S]*display: flex;[\s\S]*flex-wrap: nowrap;[\s\S]*justify-content: space-between/);
assert.match(panelSource, /\.price-chart-legend \{[\s\S]*margin-left: 0;[\s\S]*margin-right: 0;[\s\S]*max-width: none;[\s\S]*width: 100%/);
assert.match(panelSource, /\.price-chart-legend \.chart-legend-toggle \{[\s\S]*flex: 0 1 auto;[\s\S]*min-width: 0;[\s\S]*white-space: nowrap/);
assert.match(panelSource, /\.price-chart-legend \{[\s\S]*font-size: var\(--card-legend-size\)/);
assert.doesNotMatch(panelSource, /\.price-chart-legend \{[^}]*display: grid/);
assert.doesNotMatch(panelSource, /\.price-chart-legend \{[^}]*grid-template-columns/);
assert.doesNotMatch(panelSource, /@container price-card \(max-width: 480px\) \{\s*\.price-section \.price-chart-legend/);
assert.match(panelSource, /\.chart-legend-toggle \{[\s\S]*gap: 3px/);
assert.match(panelSource, /data-price="current"[\s\S]*data-price="average"[\s\S]*data-price="lowest"[\s\S]*data-price="highest"/);
assert.match(panelSource, /\.price-analysis-status[\s\S]*font-size: var\(--price-card-text-size\)/);
assert.match(panelSource, /\.price-analysis-forecast[\s\S]*font-size: var\(--price-card-text-size\)/);
assert.match(panelSource, /\.price-section \.section-heading \.status[\s\S]*font-size: var\(--price-card-text-size\)/);
assert.doesNotMatch(panelSource, /\.chart-svg \{[\s\S]*min-width: [^0]/);
assert.match(panelSource, /\.section-heading \{[\s\S]*display: flex;[\s\S]*flex-wrap: wrap/);
assert.match(panelSource, /\.section-heading h2,[\s\S]*white-space: nowrap/);
assert.match(panelSource, /class="price-heading-main"/);
assert.match(panelSource, /\.price-heading-main \{[\s\S]*display: flex[\s\S]*flex: 0 0 auto[\s\S]*gap: 12px/);
assert.match(panelSource, /\.price-heading-main > div:first-child \{[\s\S]*flex: 0 0 auto[\s\S]*min-width: max-content/);
assert.match(panelSource, /\.price-heading-main[\s\S]*price-comparison-controls/);
assert.doesNotMatch(panelSource, /\.price-comparison-controls \{[\s\S]*margin: 0 0 0 auto/);
assert.match(panelSource, /\.section-heading \{[\s\S]*justify-content: flex-start/);
assert.match(panelSource, /\.price-heading-main \{[\s\S]*justify-content: flex-start/);
assert.match(panelSource, /\.price-summary \{[\s\S]*display: grid[\s\S]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/);
assert.doesNotMatch(panelSource, /\.price-summary \{[^}]*flex-wrap:/);
assert.match(panelSource, /\.price-summary \{[\s\S]*flex: 1 1 230px/);
assert.match(panelSource, /\.price-summary \.price-value \{[\s\S]*min-width: 0[\s\S]*text-align: center[\s\S]*white-space: nowrap/);
assert.match(panelSource, /\.price-summary \{[\s\S]*min-width: min\(100%, 215px\)/);
assert.match(panelSource, /\.price-summary \{[\s\S]*width: min\(100%, 230px\)/);
assert.match(panelSource, /\.price-section \.price-summary \{[\s\S]*gap: clamp\(4px, \.8cqw, 6px\)/);
assert.match(panelSource, /\.price-section \.section-heading \{[\s\S]*gap: clamp\(1px, \.5cqw, 2px\) clamp\(8px, 1\.5cqw, 12px\)/);
assert.match(panelSource, /ResizeObserver\(updateLayoutState\)/);
assert.match(panelSource, /price-summary-wrapped/);
assert.match(panelSource, /price-summary-inline/);
assert.match(panelSource, /summary\.getBoundingClientRect\(\)\.top > cluster\.getBoundingClientRect\(\)\.bottom \+ 1/);
assert.match(panelSource, /\.section-heading\.price-summary-inline[\s\S]*font-size: clamp\(11px, 1\.5cqw, 15px\)/);
assert.match(panelSource, /\.section-heading\.price-summary-inline[\s\S]*font-size: clamp\(11px, 1\.7cqw, 17px\)/);
assert.match(panelSource, /chart-legend-preview/);
assert.match(panelSource, /\.chart-legend-toggle \{[\s\S]*cursor: pointer;/);
assert.match(panelSource, /min-height: 22px/);
assert.match(panelSource, /\.price-chart \{[\s\S]*container-type: inline-size/);
assert.match(panelSource, /\.price-chart \{[\s\S]*min-height: 0/);
assert.match(panelSource, /\.price-chart \{[\s\S]*overflow-x: hidden/);
assert.match(panelSource, /\.chart-svg \{[\s\S]*aspect-ratio: 960 \/ 350/);
assert.match(panelSource, /\.chart-svg \{[\s\S]*height: auto/);
assert.match(panelSource, /\.chart-svg \{[\s\S]*max-height: 350px/);
assert.match(panelSource, /@supports \(height: 1cqw\)[\s\S]*height: min\(350px, 36\.458333cqw\)/);
assert.doesNotMatch(panelSource, /\.chart-svg \{[\s\S]*\n\s*height: 350px;/);
assert.match(panelSource, /\.chart-svg \{[\s\S]*max-width: 100%;[\s\S]*min-width: 0/);
assert.doesNotMatch(panelSource, /\.chart-svg \{[\s\S]*min-width: 720px/);
assert.match(panelSource, /const height = 350/);
assert.match(panelSource, /viewBox="0 0 \$\{width\} \$\{height\}"/);
assert.match(panelSource, /chart-hover-markers/);
assert.match(panelSource, /chart-hover-marker-spot/);
assert.match(panelSource, /chart-hover-marker-import/);
assert.match(panelSource, /chart-hover-marker-export/);
assert.doesNotMatch(panelSource, /bar-hover/);
assert.doesNotMatch(panelSource, /clearBarHover/);
assert.doesNotMatch(panelSource, /classList\.add\("bar-hover"\)/);
assert.match(panelSource, /return `<rect class="chart-bar \$\{category\}"/);
assert.match(panelSource, /show\(period\.period, event, period\.tooltipTimestamp\)/);
assert.match(panelSource, /tooltip\.hidden = false/);
assert.match(panelSource, /const priceMarkerX = hoverGeometry\.x\(hoverSnapshot\.hoverTime\)/);
assert.match(panelSource, /clearHoverMarkers/);
assert.match(panelSource, /function positionChartTooltip\(chart, tooltip, clientX, clientY, obstacles = \[\], orbitState = \{\}\)/);
assert.match(panelSource, /const angleStep = Math\.PI \/ 45/);
assert.match(panelSource, /const obstacleRects = obstacles\.map/);
assert.match(panelSource, /querySelectorAll\("\.chart-hover-marker"\)/);
assert.match(panelSource, /isVisiblePowerValue\(details\?\.import_kw\)/);
assert.match(panelSource, /isVisiblePowerValue\(details\?\.export_kw\)/);
assert.match(panelSource, /const hoverSnapshot = \{[\s\S]*hoverTime: tooltipTimestamp/);
assert.match(panelSource, /const canonicalMeterPoint = this\._meterCanonicalPointAt\(tooltipTimestamp\)/);
assert.match(panelSource, /const rawMeterPoint = this\._meterPointAtNearest\(tooltipTimestamp\)/);
assert.match(panelSource, /meterSampleTime: canonicalMeterPoint \? canonicalMeterPoint\.timestamp : null/);
assert.match(panelSource, /priceBarValue: barPrice \?\? null/);
assert.match(panelSource, /importValue: meterValue\("import_kw"\)/);
assert.match(panelSource, /exportValue: meterValue\("export_kw"\)/);
assert.match(panelSource, /isVisiblePowerValue\(hoverSnapshot\.importValue\)/);
assert.match(panelSource, /isVisiblePowerValue\(hoverSnapshot\.exportValue\)/);
assert.match(panelSource, /_buildVisibleTooltipFields\(comparisonPrice, \{[\s\S]*hoverSnapshot\.importValue/);
assert.match(panelSource, /hoverGeometry\.y\(hoverSnapshot\.priceBarValue\)/);
assert.match(panelSource, /buildMeterDisplayCoordinates\(segment, key, x, meterY\)/);
assert.match(panelSource, /buildMeterDisplayPathSegments\(coordinates\)/);
assert.match(panelSource, /meterDisplayYAt\(geometry, timestamp, x\)/);
assert.match(panelSource, /control1:/);
assert.match(panelSource, /control2:/);
assert.match(panelSource, /path\.push\(`C /);
assert.match(panelSource, /for \(let iteration = 0; iteration < 24; iteration \+= 1\)/);
assert.match(panelSource, /const currentX = inverse \* inverse \* inverse \* start\.x/);
assert.match(panelSource, /meterDisplayY: \(key, timestamp\) => this\.meterDisplayYAt/);
assert.match(panelSource, /const importDisplayY = meterMarkerX === null/);
assert.match(panelSource, /const meterMarkerX = Number\.isFinite\(hoverSnapshot\.meterSampleTime\)/);
assert.match(panelSource, /hoverGeometry\.x\(hoverSnapshot\.meterSampleTime\)/);
assert.match(panelSource, /hoverGeometry\.meterDisplayY\("import_kw", hoverSnapshot\.meterSampleTime\)/);
assert.match(panelSource, /hoverGeometry\.meterDisplayY\("export_kw", hoverSnapshot\.meterSampleTime\)/);
assert.match(panelSource, /Number\.isFinite\(importDisplayY\)/);
assert.match(panelSource, /Number\.isFinite\(exportDisplayY\)/);
assert.match(panelSource, /chart-legend-preview\.solar/);
assert.match(panelSource, /chart-legend-preview\.consumption/);
assert.match(panelSource, /chart-legend-preview\.charging/);
assert.match(panelSource, /chart-legend-preview\.discharging/);
assert.match(panelSource, /data-preview-layer="solar"/);
assert.match(panelSource, /data-preview-layer="consumption"/);
assert.match(panelSource, /data-preview-layer="charging"/);
assert.match(panelSource, /data-preview-layer="discharging"/);
assert.match(panelSource, /data-power-card="solar-history"/);
assert.doesNotMatch(panelSource, /data-power-card="consumption"/);
assert.match(panelSource, /data-power-card="battery-history"/);
assert.match(panelSource, /this\._mainCards\.consumption = false/);
assert.match(panelSource, /if \(this\._mainCards\.consumption && !this\._mainCards\.elmatare\) this\._mainCards\.elmatare = true/);
assert.match(panelSource, /elrakning\/power_state/);
assert.match(panelSource, /elrakning\/power_save/);
assert.match(panelSource, /elrakning\/power_history/);
assert.match(panelSource, /type: "elrakning\/power_history", days: 7/);
assert.match(panelSource, /_refreshBackendState\(true\)/);
assert.match(panelSource, /this\._backendHydrationPromise = Promise\.all\(\[/);
assert.match(panelSource, /"elrakning_integration_ready"/);
assert.match(panelSource, /_readyEventUnsubscribePromise/);
assert.match(panelSource, /addEventListener\?\.\("ready", this\._connectionReadyListener\)/);
assert.match(panelSource, /removeEventListener\("ready", this\._connectionReadyListener\)/);
assert.match(panelSource, /state\.error === "meter_unavailable"/);
assert.match(panelSource, /state\.error === "power_unavailable"/);
assert.match(panelSource, /response\?\.error === "integration_unavailable"/);
assert.match(panelSource, /this\.renderPriceChart\(\);\n        this\._persistChartPreferences\(\{ chart_layers: this\._chartLayerState\(\) \}\);/);
assert.match(panelSource, /Array\.isArray\(current\.solar_entities\) \? \[\.\.\.current\.solar_entities\]/);
assert.match(panelSource, /data-power-clear/);
assert.match(panelSource, /_appendPowerPoint\(entry\.series, entry\.point\)/);
assert.match(panelSource, /_resetPowerLivePoints/);
assert.match(panelSource, /\.meter-invert-toggle \{/);
assert.match(panelSource, /\.meter-invert-toggle \.price-filter-track \{/);
assert.match(panelSource, /buildCanonicalPowerPoints/);
assert.match(panelSource, /chart-power-solar/);
assert.match(panelSource, /chart-power-consumption/);
assert.match(panelSource, /chart-power-charging/);
assert.match(panelSource, /chart-power-discharging/);
assert.match(panelSource, /this\._previewLayersVisible\[layer\] = !this\._previewLayersVisible\[layer\]/);
assert.match(panelSource, /chart-legend-preview:not\(\.active\)/);
assert.match(panelSource, /--solar-color: var\(--el-solar-color\)/);
assert.match(panelSource, /--consumption-color: var\(--el-consumption-color\)/);
assert.match(panelSource, /--grid-import-color: var\(--el-import-color\)/);
assert.match(panelSource, /--charging-color: var\(--el-charging-color\)/);
assert.match(panelSource, /--discharging-color: var\(--el-discharging-color\)/);
assert.match(panelSource, /\.chart-legend-preview \{[\s\S]*color: var\(--primary-text-color\)/);
assert.match(panelSource, /data-chart-layer="import"/);
assert.match(panelSource, /data-chart-layer="export"/);
assert.doesNotMatch(panelSource, /#56C7A0|#FF6363|#A55E63|#EF5C83|#984C5A|#D65368/);
assert.doesNotMatch(panelSource, /chart-legend-preview\.charging\.active/);
assert.doesNotMatch(panelSource, /chart-legend-preview\.charging:not\(\.active\)/);
assert.match(panelSource, /height: 7px;\n\s+width: 7px;/);
assert.match(panelSource, /visibleLayers\.spot && Number\.isFinite\(comparisonPrice\)/);
assert.match(panelSource, /this\._chartBarPrices = prices/);
assert.match(panelSource, /const barPrice = this\._chartBarPrices\?\.\[index\]/);
assert.match(panelSource, /visibleLayers\.spot && Number\.isFinite\(hoverSnapshot\.priceBarValue\)/);
assert.match(panelSource, /hoverGeometry\.y\(hoverSnapshot\.priceBarValue\)/);
assert.match(panelSource, /this\._priceComparisonVisible\.grid/);
assert.match(panelSource, /this\._priceComparisonVisible\.electricity/);
assert.match(panelSource, /const label = "Spotpris";/);
assert.match(panelSource, /add\(label, value, this\.formatPrice\(value\)\)/);
assert.match(panelSource, /\.chart-tooltip \{[\s\S]*pointer-events: none;/);
assert.match(panelSource, /\.chart-tooltip\.debug-tooltip \{[\s\S]*pointer-events: none;/);
assert.doesNotMatch(panelSource, /const label = tradeVisible && gridVisible[\s\S]*\? "Totalpris"[\s\S]*\? "Elnät"[\s\S]*: "Elhandel"/);
assert.doesNotMatch(panelSource, /add\("Överföring"/);
assert.match(panelSource, /layers\.import && isVisiblePowerValue\(details\?\.import_kw\)/);
assert.match(panelSource, /layers\.export && isVisiblePowerValue\(details\?\.export_kw\)/);
assert.match(panelSource, /tooltip-meter-import/);
assert.match(panelSource, /tooltip-meter-export/);
assert.match(panelSource, /renderSharedTooltip\(tooltip/);
assert.match(panelSource, /fields: tooltipFields/);
assert.match(panelSource, /periods\.forEach\(\(period, index\) =>/);
assert.doesNotMatch(panelSource, /_hoverIsolatedLayer/);
assert.match(panelSource, /_effectiveChartLayerState\(\)/);
const legendSource = panelSource.slice(panelSource.indexOf("  _bindChartLegend()"), panelSource.indexOf("  _bindDebugToggle()"));
assert.doesNotMatch(legendSource, /bindHoverIsolation/);
assert.match(legendSource, /const bindHoverPreview = \(button, layer\) =>/);
const hoverPreviewSource = legendSource.slice(legendSource.indexOf("const setHoverPreview"), legendSource.indexOf("const toggleLayer"));
assert.doesNotMatch(hoverPreviewSource, /renderPriceChart\(\)/);
assert.match(hoverPreviewSource, /node\.style\.opacity = "0"/);
assert.match(hoverPreviewSource, /node\.style\.opacity = ""/);
assert.match(legendSource, /bindLongPress\(button, button\.dataset\.chartLayer\)/);
assert.match(legendSource, /bindLongPress\(button, button\.dataset\.previewLayer\)/);
assert.match(legendSource, /bindHoverPreview\(button, button\.dataset\.chartLayer\)/);
assert.match(legendSource, /bindHoverPreview\(button, button\.dataset\.previewLayer\)/);
assert.match(legendSource, /pointerleave/);
assert.match(legendSource, /pointercancel/);
assert.match(legendSource, /this\._setSoloChartLayer\(layer\)/);
assert.doesNotMatch(panelSource, /event\.pointerType === "touch" \|\| !this\._chartLayerState\(\)\[layer\]/);
assert.match(panelSource, /const hasVisibleTooltipLayer = this\._spotBarsVisible/);
assert.match(panelSource, /if \(!hasVisibleTooltipLayer\)/);
assert.doesNotMatch(panelSource, /if \(!this\._spotBarsVisible\) \{/);
assert.match(panelSource, /const pointer = pointerToPlotCoordinates\(svg, event, plot, width, height\);/);
assert.match(panelSource, /if \(!pointer\?\.inside\)/);
assert.match(panelSource, /generateUpcomingPriceAnalysis/);
assert.match(panelSource, /\$\{visibleLayers\.average \? `<line class="chart-average"/);
assert.match(panelSource, /querySelectorAll\("\.chart-hover-marker"\)/);
assert.match(panelSource, /data-price-analysis/);
assert.match(panelSource, /\.price-analysis/);
assert.match(panelSource, /white-space: normal/);
assert.match(panelSource, /text-overflow: clip/);
assert.match(panelSource, /overflow-wrap: anywhere/);
assert.match(panelSource, /price-analysis-status/);
assert.match(panelSource, /price-analysis-forecast/);
assert.match(panelSource, /\.price-analysis-status \{[\s\S]*display: block/);
assert.match(panelSource, /\.price-analysis-forecast \{[\s\S]*column-gap: \.3em[\s\S]*display: flex[\s\S]*flex-wrap: wrap/);
assert.match(panelSource, /\.price-analysis-sentence \{[\s\S]*flex: 0 1 auto[\s\S]*min-width: min-content[\s\S]*overflow-wrap: break-word/);
assert.doesNotMatch(panelSource, /price-analysis-separator/);
assert.doesNotMatch(panelSource, /@container price-card \(max-width: 480px\)[\s\S]*price-analysis/);
assert.match(panelSource, /\.price-summary \{[\s\S]*gap: 6px/);
assert.doesNotMatch(panelSource, /-webkit-line-clamp: 2/);
assert.match(panelSource, /for \(const sentenceText of upcoming\.sentences \|\| \[upcoming\.forecast\]\)/);
assert.match(panelSource, /sentence\.className = "price-analysis-sentence"/);
assert.match(panelSource, /\.price-analysis-status\.cheap/);
assert.match(panelSource, /\.price-analysis-status\.normal/);
assert.match(panelSource, /\.price-analysis-status\.expensive/);
assert.match(panelSource, /navigator\.clipboard\.writeText/);
assert.doesNotMatch(panelSource, /chart_debug_copy_clicked/);
assert.doesNotMatch(panelSource, /chart_debug_copy_text_length/);
assert.doesNotMatch(panelSource, /chart_debug_copy_success/);
assert.match(panelSource, /_recordMeterDiagnostic\("INFO", "meter_save_clicked"/);
assert.match(panelSource, /clipboardError/);
assert.doesNotMatch(panelSource, /tooltip_click_received/);
assert.doesNotMatch(panelSource, /tooltip_copy_text_length/);
assert.match(panelSource, /if \(mode === "house_load"\)[\s\S]*await this\.loadPowerHistory\(\);[\s\S]*close\(\);/);
assert.match(panelSource, /const payload = \{[\s\S]*type: "elrakning\/meter_save"/);
assert.match(panelSource, /this\.loadMeterState\(loadHistory\)/);
assert.match(panelSource, /phaseEntities = Object\.values\(mapping\.phase_current_entities \|\| \{\}\)/);
assert.match(panelSource, /\[mapping\.power_entity, mapping\.energy_import_entity, mapping\.energy_export_entity, \.\.\.phaseEntities\]\.includes\(entityId\)/);
assert.match(panelSource, /async loadMeterState\(loadHistory = false\)/);
assert.match(panelSource, /if \(loadHistory\) await this\.loadMeterPowerHistory\(\);/);
assert.doesNotMatch(panelSource, /meter_history_request_started/);
assert.doesNotMatch(panelSource, /meter_history_request_success/);
assert.match(panelSource, /meter_history_request_failed/);
assert.match(panelSource, /if \(!response\?\.success\)/);
assert.match(panelSource, /_meterHistoryRequestToken/);
assert.match(panelSource, /response\?\.entity_id/);
assert.match(panelSource, /point\.entity_id && point\.entity_id !== this\._meterState\?\.power_entity/);
assert.match(panelSource, /function positionChartTooltip\(chart, tooltip, clientX, clientY, obstacles = \[\], orbitState = \{\}\)/);
assert.match(panelSource, /tooltip\.offsetWidth/);
assert.match(panelSource, /tooltip\.offsetHeight/);
assert.match(panelSource, /const angleStep = Math\.PI \/ 45/);
assert.match(panelSource, /const intersects = \(left, top\) => obstacleRects\.some/);
assert.match(panelSource, /const fitsViewport = \(left, top\) =>/);
assert.match(panelSource, /for \(let distance = 0; distance <= 36; distance \+= 12\)/);
assert.match(panelSource, /const viewportTop = chart\.scrollTop \+ safety/);
assert.match(panelSource, /const viewportBottom = chart\.scrollTop \+ chart\.clientHeight - safety/);
assert.match(panelSource, /positionChartTooltip\(chart, tooltip, event\.clientX, event\.clientY, obstacles, this\._tooltipOrbit\)/);
assert.match(panelSource, /touch-action: pan-y/);
assert.match(panelSource, /chart\.addEventListener\("touchstart"[\s\S]*insidePlot\(touch\.clientX, touch\.clientY\)[\s\S]*show\(hit\.period, touch, hit\.tooltipTimestamp\)/);
assert.match(panelSource, /chart\.addEventListener\("touchmove"[\s\S]*periodAt\(touch\.clientX\)[\s\S]*show\(hit\.period, touch, hit\.tooltipTimestamp\)/);
assert.match(panelSource, /const clearTouchHover = \(\) => \{[\s\S]*tooltip\.hidden = true/);
assert.doesNotMatch(panelSource, /_pinnedPeriod/);
assert.doesNotMatch(panelSource, /touchend[\s\S]*copyChartDebugText/);
assert.match(panelSource, /positionChartTooltip\(chart, tooltip, event\.clientX, event\.clientY, \[\], this\._tooltipOrbit\)/);
assert.doesNotMatch(panelSource, /tooltip\.style\.top = `\$\{pointY \/ height \* rect\.height\}px`/);
assert.doesNotMatch(panelSource, /\.soc-tooltip \{[\s\S]*transform: translate\(-50%, -100%\);/);

const technicalOutput = formatDiagnosticsText([
  { level: "DEBUG", component: "source", event: "debug_event", message: "Technical detail" },
], "0.0.64");
assert.match(technicalOutput, /DEBUG source debug_event/);
