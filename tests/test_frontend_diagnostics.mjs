import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createPriceDebugText, diagnosticComponent, diagnosticSymbol, formatDiagnosticsText, generateUpcomingPriceAnalysis, priceCategory, priceColorBands, priceColorDetails, providerLabel } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const output = formatDiagnosticsText([
  {
    timestamp: "2026-08-22T10:00:00.000Z",
    level: "INFO",
    component: "source",
    event: "source_loading",
    message: "Loading source data",
  },
], "0.0.64");

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
const upcomingPeriods = [1, 1, 1, 1, 3, 4, 10, 12, 14, 15].map((price, index) => ({
  start: `2026-08-23T${String(12 + Math.floor(index / 4)).padStart(2, "0")}:${String((index % 4) * 15).padStart(2, "0")}:00+02:00`,
  end: `2026-08-23T${String(12 + Math.floor((index + 1) / 4)).padStart(2, "0")}:${String(((index + 1) % 4) * 15).padStart(2, "0")}:00+02:00`,
  price: price / 100,
}));
assert.deepEqual(
  generateUpcomingPriceAnalysis(upcomingPeriods, 0, new Date("2026-08-23T12:00:00+02:00")),
  { category: "cheap", status: "Billigt nu", forecast: "Priset väntas stiga om cirka 1 timme" },
);
const guardedLowDay = priceColorBands([...Array.from({ length: 15 }, (_, index) => 1 + index / 10), 4.1, 100, 101, 102, 103, 104]);
assert.equal(priceCategory(4.1, guardedLowDay), "normal");
assert.equal(priceCategory(2, priceColorBands([2, 2, 2])), "normal");

const panelSource = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
assert.doesNotMatch(panelSource, /E\.ON Energidistribution/);
assert.doesNotMatch(panelSource, /HomeWizard/);
assert.match(panelSource, /<h2>Source data<\/h2>/);
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
assert.match(panelSource, /meter_save_clicked/);
assert.match(panelSource, /meter_save_payload_created/);
assert.match(panelSource, /document\.createElement\("ha-selector"\)/);
assert.match(panelSource, /selector\.selector = \{ entity: \{ filter: \{ domain: "sensor" \}, multiple: false \} \}/);
assert.match(panelSource, /selector\.addEventListener\("value-changed"/);
assert.match(panelSource, /selector\.value = event\.detail\?\.value/);
assert.match(panelSource, /meter_selector_values_read/);
assert.match(panelSource, /power_entity/);
assert.match(panelSource, /energy_import_entity/);
assert.match(panelSource, /energy_export_entity/);
assert.match(panelSource, /elrakning_diagnostics_update/);
assert.match(panelSource, /this\._diagnosticEntries = entries\.slice\(\)/);
assert.match(panelSource, /formatDiagnosticsText\(clipboardEntries, this\.version\)/);
assert.match(panelSource, /_websocketErrorDetails\(error\)/);
assert.match(panelSource, /data-meter-field/);
assert.match(panelSource, /save\.disabled = false/);
assert.doesNotMatch(panelSource, /radio\.type = "radio"/);
assert.doesNotMatch(panelSource, /data-meter-candidates/);
assert.doesNotMatch(panelSource, /data-meter-search/);
assert.doesNotMatch(panelSource, /selectedEntities/);
assert.doesNotMatch(panelSource, /selectedCandidate/);
assert.match(panelSource, /meter_save_payload_types/);
assert.match(panelSource, /meter_mapping_created/);
assert.match(panelSource, /data-meter-clear/);
assert.match(panelSource, /elrakning\/meter_store_clear/);
assert.match(panelSource, /elrakning\/meter_power_history/);
assert.match(panelSource, /elrakning_meter_power_update/);
assert.match(panelSource, /data-chart-layer="spot"/);
assert.match(panelSource, /data-chart-layer="electricity"/);
assert.match(panelSource, /data-chart-layer="grid"/);
assert.match(panelSource, /data-chart-layer="import"/);
assert.match(panelSource, /data-chart-layer="export"/);
assert.match(panelSource, /this\._priceLayerVisible\.spot = true/);
assert.match(panelSource, /_priceLayerValue/);
assert.match(panelSource, /chart-price-layer/);
assert.match(panelSource, /chart-meter-import/);
assert.match(panelSource, /chart-meter-export/);
assert.match(panelSource, /#F2A373/);
assert.match(panelSource, /#72AAF6/);
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
assert.match(panelSource, /priceCategory\(prices\[currentIndex\], colorBands\)/);
assert.match(panelSource, /generateUpcomingPriceAnalysis/);
assert.match(panelSource, /data-price-analysis/);
assert.match(panelSource, /\.price-analysis/);
assert.match(panelSource, /white-space: nowrap/);
assert.match(panelSource, /text-overflow: ellipsis/);
assert.doesNotMatch(panelSource, /-webkit-line-clamp: 2/);
assert.doesNotMatch(panelSource, /price-analysis-separator/);
assert.match(panelSource, /document\.createTextNode\(` · \$\{upcoming\.forecast\}`\)/);
assert.match(panelSource, /\.price-analysis-status\.cheap/);
assert.match(panelSource, /\.price-analysis-status\.normal/);
assert.match(panelSource, /\.price-analysis-status\.expensive/);
assert.match(panelSource, /navigator\.clipboard\.writeText/);
assert.match(panelSource, /chart_debug_copy_clicked/);
assert.match(panelSource, /chart_debug_copy_text_length/);
assert.match(panelSource, /chart_debug_copy_success/);
assert.match(panelSource, /_recordDiagnostic\("price", "INFO", "chart_debug_copy_clicked"/);
assert.match(panelSource, /_recordMeterDiagnostic\("INFO", "meter_save_clicked"/);
assert.match(panelSource, /lastChartDebugCopyAt/);
assert.match(panelSource, /clipboardError/);
assert.doesNotMatch(panelSource, /tooltip_click_received/);
assert.doesNotMatch(panelSource, /tooltip_copy_text_length/);

const technicalOutput = formatDiagnosticsText([
  { level: "DEBUG", component: "source", event: "debug_event", message: "Technical detail" },
], "0.0.64");
assert.match(technicalOutput, /DEBUG source debug_event/);
