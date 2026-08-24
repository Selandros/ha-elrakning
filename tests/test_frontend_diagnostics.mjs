import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildCanonicalMeterPoints, buildMonotoneCubicSegments, buildPriceAnalysisFacts, createPriceDebugText, diagnosticComponent, diagnosticSymbol, formatDiagnosticsText, generateUpcomingPriceAnalysis, nearestMeterPoint, priceCategory, priceColorBands, priceColorDetails, providerLabel, renderPriceAnalysis, snapTooltipTimestamp } from "../custom_components/elrakning/frontend/elrakning-panel.js";

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
const renderedAnalysis = renderPriceAnalysis(waitFacts);
assert.doesNotMatch(renderedAnalysis.status + renderedAnalysis.forecast, /Starta nu|Vänta|Billigast att starta|Du bör|Kör tvättmaskin/);
assert.doesNotMatch(renderedAnalysis.forecast, /Priset stiger senare|Det blir billigare|Priset förändras under kvällen/);
assert.match(renderPriceAnalysis(waitFacts).forecast, /öre\/kWh/);
assert.match(renderPriceAnalysis(waitFacts).forecast, /Från 03:00: 54 öre\/kWh/);
assert.equal(renderPriceAnalysis({ ...waitFacts, status: "cheap" }).status, "Billigt pris nu");
assert.equal(renderPriceAnalysis({ ...waitFacts, status: "normal" }).status, "Normalt pris nu");
assert.equal(renderPriceAnalysis({ ...waitFacts, status: "expensive" }).status, "Dyrt pris nu");
assert.equal(renderPriceAnalysis(buildPriceAnalysisFacts(makeAnalysisPeriods([5, 5, 5, 5]), 0)).forecast, "Dagens prisanalys är inte tillgänglig");
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
assert.match(panelSource, /data-chart-layer="average"/);
assert.match(panelSource, /data-chart-layer="import"/);
assert.match(panelSource, /data-chart-layer="export"/);
assert.match(panelSource, /data-price-layer="electricity"/);
assert.match(panelSource, /data-price-layer="grid"/);
assert.match(panelSource, /class="price-filter-toggle"/);
assert.match(panelSource, /data-price-toggle/);
assert.match(panelSource, /price-filter-track/);
assert.doesNotMatch(panelSource, /chart-legend-swatch electricity/);
assert.doesNotMatch(panelSource, /chart-legend-swatch grid/);
assert.match(panelSource, /this\._spotBarsVisible/);
assert.match(panelSource, /this\._averageLineVisible = true/);
assert.match(panelSource, /chart-legend-swatch\.average \{[\s\S]*background: var\(--warning-color\)/);
assert.match(panelSource, /if \(layer === "average"\) \{[\s\S]*this\._averageLineVisible = !this\._averageLineVisible/);
assert.match(panelSource, /this\._priceComparisonVisible/);
assert.match(panelSource, /_comparisonPrice/);
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
assert.match(panelSource, /chart-meter-label" text-anchor="start" x="8"/);
assert.doesNotMatch(panelSource, /chart-meter-axis/);
assert.doesNotMatch(panelSource, /const meterAxis/);
assert.match(panelSource, /#F2A373/);
assert.match(panelSource, /#72AAF6/);
assert.equal((panelSource.match(/--grid-import-color: #F2A373/g) || []).length, 1);
assert.equal((panelSource.match(/--grid-export-color: #72AAF6/g) || []).length, 1);
const mobileMediaIndex = panelSource.indexOf("@media (max-width: 600px)");
const globalImportIndex = panelSource.indexOf("--grid-import-color: #F2A373");
const globalExportIndex = panelSource.indexOf("--grid-export-color: #72AAF6");
assert.ok(globalImportIndex >= 0 && globalImportIndex < mobileMediaIndex);
assert.ok(globalExportIndex >= 0 && globalExportIndex < mobileMediaIndex);
assert.match(panelSource, /\.price-section \{\n\s+--solar-color: #77C2A1;\n\s+--consumption-color: #EA7671;\n\s+--grid-import-color: #F2A373;\n\s+--grid-export-color: #72AAF6;\n\s+--charging-color: #844A54;\n\s+--discharging-color: #E06681;/);
assert.match(panelSource, /\.chart-meter-import \{\n\s+stroke: var\(--grid-import-color\);/);
assert.match(panelSource, /\.chart-meter-export \{\n\s+stroke: var\(--grid-export-color\);/);
assert.match(panelSource, /stroke-width: 1\.6/);
assert.match(panelSource, /opacity: \.82/);
assert.match(panelSource, /\.chart-meter-gridline \{\n\s+stroke: var\(--divider-color\);\n\s+stroke-width: 1;\n\s+opacity: \.28;/);
assert.doesNotMatch(panelSource, /const meterPath =/);
assert.match(panelSource, /prepareMeterDisplayPoints\(points\)/);
assert.match(panelSource, /latestByTimestamp = new Map\(\)/);
assert.doesNotMatch(panelSource, /smoothSignedMeterPoints/);
assert.match(panelSource, /buildCanonicalMeterPoints\(points, dayStart, dayEnd, slotMs = 5 \* 60 \* 1000, maxDistanceMs = 2\.5 \* 60 \* 1000\)/);
assert.match(panelSource, /nearestMeterPoint\(points, slotTimestamp, maxDistanceMs\)/);
assert.match(panelSource, /raw_timestamp: hasSample \? selected\.timestamp : null/);
assert.match(panelSource, /for \(let slotTimestamp = dayStartMs; slotTimestamp < dayEndMs; slotTimestamp \+= slotMs\)/);
assert.match(panelSource, /buildMeterDisplaySegments\(points, key\)/);
assert.match(panelSource, /buildSmoothMeterPath\(segment, key, x, meterY\)/);
assert.match(panelSource, /<path class=\"\$\{className\}\" d=\"\$\{this\.buildSmoothMeterPath/);
assert.match(panelSource, /if \(to - from > 0\) segments\.push\(points\.slice\(from, to \+ 1\)\)/);
assert.match(panelSource, /if \(segment\.length < 2\) return \"\"/);
assert.match(panelSource, /const meterCanonicalPoints = this\.buildCanonicalMeterPoints/);
assert.match(panelSource, /const meterDisplayPoints = this\.prepareMeterDisplayPoints\(meterCanonicalPoints\)/);
assert.doesNotMatch(panelSource, /const meterDisplayPoints = this\.smoothSignedMeterPoints/);
assert.match(panelSource, /const meterMaximum = Math\.max\(/);
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
assert.match(panelSource, /priceCategory\(prices\[currentIndex\], colorBands\)/);
assert.match(panelSource, /\.chart-bar\.cheap \{\n\s+fill: color-mix\(in srgb, var\(--success-color\) 38%,/);
assert.match(panelSource, /\.chart-bar\.normal \{\n\s+fill: color-mix\(in srgb, var\(--warning-color\) 38%,/);
assert.match(panelSource, /\.chart-bar\.expensive \{\n\s+fill: color-mix\(in srgb, var\(--error-color\) 38%,/);
assert.doesNotMatch(panelSource, /\.chart-bar\.cheap \{[^}]*opacity:/);
assert.doesNotMatch(panelSource, /\.chart-bar\.normal \{[^}]*opacity:/);
assert.doesNotMatch(panelSource, /\.chart-bar\.expensive \{[^}]*opacity:/);
const chartBarCheapIndex = panelSource.indexOf(".chart-bar.cheap {");
const chartBarNormalIndex = panelSource.indexOf(".chart-bar.normal {");
const chartBarExpensiveIndex = panelSource.indexOf(".chart-bar.expensive {");
assert.ok(chartBarCheapIndex >= 0 && chartBarCheapIndex < mobileMediaIndex);
assert.ok(chartBarNormalIndex >= 0 && chartBarNormalIndex < mobileMediaIndex);
assert.ok(chartBarExpensiveIndex >= 0 && chartBarExpensiveIndex < mobileMediaIndex);
assert.doesNotMatch(panelSource, /marker-highlight/);
assert.match(panelSource, /return `<rect class="chart-bar \$\{category\}"/);
assert.match(panelSource, /\.price-marker-label \{[\s\S]*fill: var\(--primary-color\)/);
assert.ok((panelSource.match(/var\(--ha-card-background, var\(--card-background-color\)\)/g) || []).length >= 4);
assert.match(panelSource, /_buildVisibleTooltipRows\(comparisonPrice, details\)/);
assert.match(panelSource, /snapTooltipTimestamp\(/);
assert.match(panelSource, /tooltipTimestamp = snapTooltipTimestamp/);
assert.match(panelSource, /return start <= tooltipTimestamp && tooltipTimestamp < end/);
assert.match(panelSource, /const time = this\.formatTime\(new Date\(tooltipTimestamp\)\)/);
assert.match(panelSource, /nearestMeterPoint\(this\._meterTooltipPoints, timestamp\)/);
assert.match(panelSource, /const rawMeterPoint = this\._meterPointAtNearest\(tooltipTimestamp\)/);
assert.match(panelSource, /const value = this\._spotBarsVisible && Number\.isFinite\(comparisonPrice\)/);
assert.doesNotMatch(panelSource, /data-tooltip=/);
assert.match(panelSource, />Sol\s*</);
assert.match(panelSource, /Förbrukning/);
assert.match(panelSource, /Laddning/);
assert.match(panelSource, /Urladdning/);
assert.match(panelSource, /<p class="status">Spotpris · öre\/kWh<\/p>/);
assert.match(panelSource, /<span>Handel<\/span>/);
assert.match(panelSource, /<span>Nät<\/span>/);
assert.doesNotMatch(panelSource, /<p class="status">Nord Pool · Spotpris/);
assert.doesNotMatch(panelSource, /data-price-layer="electricity">[\s\S]*<span>Elhandel<\/span>/);
assert.doesNotMatch(panelSource, /data-price-layer="grid">[\s\S]*<span>Elnät<\/span>/);
assert.match(panelSource, /container-name: price-card/);
assert.match(panelSource, /container-type: inline-size/);
assert.match(panelSource, /\.section-heading h2,[\s\S]*font-size: var\(--card-title-size\)/);
assert.match(panelSource, /@supports \(font-size: 1cqw\)[\s\S]*\.price-section \.price-comparison-controls \{[\s\S]*gap: 6px/);
assert.match(panelSource, /\.price-filter-toggle \{[\s\S]*font-size: 10px/);
assert.match(panelSource, /\.price-filter-track \{[\s\S]*height: 16px[\s\S]*--knob-size: 11px[\s\S]*--track-padding: 2px[\s\S]*width: 27px/);
assert.doesNotMatch(panelSource, /\.price-section \.price-filter-track \{[\s\S]*clamp\(/);
assert.doesNotMatch(panelSource, /\.price-section \.price-filter-toggle \{[\s\S]*font-size: var\(--price-card-text-size\)/);
assert.match(panelSource, /\.price-chart-legend \{[\s\S]*display: flex;[\s\S]*flex-wrap: wrap;[\s\S]*gap: 5px 10px/);
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
assert.match(panelSource, /\.price-section \.section-heading > div:first-child \{[\s\S]*flex: 0 0 auto[\s\S]*min-width: max-content/);
assert.match(panelSource, /\.price-summary \{[\s\S]*flex: 0 0 auto[\s\S]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/);
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
assert.match(panelSource, /chart-hover-marker, \.price-marker-label/);
assert.match(panelSource, /Number\.isFinite\(details\?\.import_kw\)/);
assert.match(panelSource, /Number\.isFinite\(details\?\.export_kw\)/);
assert.match(panelSource, /const hoverSnapshot = \{[\s\S]*hoverTime: tooltipTimestamp/);
assert.match(panelSource, /const canonicalMeterPoint = this\._meterCanonicalPointAt\(tooltipTimestamp\)/);
assert.match(panelSource, /const rawMeterPoint = this\._meterPointAtNearest\(tooltipTimestamp\)/);
assert.match(panelSource, /meterSampleTime: canonicalMeterPoint \? canonicalMeterPoint\.timestamp : null/);
assert.match(panelSource, /priceBarValue: barPrice \?\? null/);
assert.match(panelSource, /importValue: meterValue\("import_kw"\)/);
assert.match(panelSource, /exportValue: meterValue\("export_kw"\)/);
assert.match(panelSource, /hoverSnapshot\.importValue > 0/);
assert.match(panelSource, /hoverSnapshot\.exportValue > 0/);
assert.match(panelSource, /_buildVisibleTooltipRows\(comparisonPrice, \{[\s\S]*hoverSnapshot\.importValue/);
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
assert.match(panelSource, /meterObstacleTop\(points, key, textLeft, textRight, x, meterY\)/);
assert.match(panelSource, /const geometry = this\.buildMeterDisplayGeometry\(points, key, x, meterY\)/);
assert.match(panelSource, /Math\.ceil\(Math\.abs\(end\.x - start\.x\) \/ 3\)/);
assert.match(panelSource, /if \(this\._meterPowerVisible\.import\)/);
assert.match(panelSource, /if \(this\._meterPowerVisible\.export\)/);
assert.match(panelSource, /const highestObstacleY = Math\.min\(\.\.\.obstacleTops\)/);
assert.match(panelSource, /chart-legend-preview\.solar/);
assert.match(panelSource, /chart-legend-preview\.consumption/);
assert.match(panelSource, /chart-legend-preview\.charging/);
assert.match(panelSource, /chart-legend-preview\.discharging/);
assert.match(panelSource, /data-preview-layer="solar"/);
assert.match(panelSource, /data-preview-layer="consumption"/);
assert.match(panelSource, /data-preview-layer="charging"/);
assert.match(panelSource, /data-preview-layer="discharging"/);
assert.match(panelSource, /this\._previewLayersVisible\[layer\] = !this\._previewLayersVisible\[layer\]/);
assert.match(panelSource, /chart-legend-preview:not\(\.active\)/);
assert.match(panelSource, /--solar-color: #77C2A1/);
assert.match(panelSource, /--consumption-color: #EA7671/);
assert.match(panelSource, /--charging-color: #844A54/);
assert.match(panelSource, /--discharging-color: #E06681/);
assert.match(panelSource, /\.chart-legend-preview \{[\s\S]*color: var\(--primary-text-color\)/);
assert.match(panelSource, /data-chart-layer="import"/);
assert.match(panelSource, /data-chart-layer="export"/);
assert.doesNotMatch(panelSource, /#56C7A0|#FF6363|#A55E63|#EF5C83|#984C5A|#D65368/);
assert.doesNotMatch(panelSource, /chart-legend-preview\.charging\.active/);
assert.doesNotMatch(panelSource, /chart-legend-preview\.charging:not\(\.active\)/);
assert.match(panelSource, /height: 7px;\n\s+width: 7px;/);
assert.match(panelSource, /this\._spotBarsVisible && Number\.isFinite\(comparisonPrice\)/);
assert.match(panelSource, /this\._chartBarPrices = prices/);
assert.match(panelSource, /const barPrice = this\._chartBarPrices\?\.\[index\]/);
assert.match(panelSource, /this\._spotBarsVisible && Number\.isFinite\(hoverSnapshot\.priceBarValue\)/);
assert.match(panelSource, /hoverGeometry\.y\(hoverSnapshot\.priceBarValue\)/);
assert.match(panelSource, /this\._priceComparisonVisible\.grid/);
assert.match(panelSource, /this\._priceComparisonVisible\.electricity/);
assert.match(panelSource, /rows\.push\(`<span class="tooltip-value">Spotpris: \$\{this\.formatPrice\(comparisonPrice\)\}<\/span>`\)/);
assert.doesNotMatch(panelSource, /<span class="tooltip-value">Elhandel:/);
assert.doesNotMatch(panelSource, /<span class="tooltip-value">Elnät:/);
assert.match(panelSource, /this\._meterPowerVisible\.import && Number\.isFinite\(details\?\.import_kw\)/);
assert.match(panelSource, /this\._meterPowerVisible\.export && Number\.isFinite\(details\?\.export_kw\)/);
assert.match(panelSource, /tooltip-meter-import/);
assert.match(panelSource, /tooltip-meter-export/);
assert.match(panelSource, /tooltip\.innerHTML =/);
assert.match(panelSource, /\$\{tooltipRows\}/);
assert.match(panelSource, /periods\.forEach\(\(period, index\) =>/);
assert.match(panelSource, /const hasVisibleTooltipLayer = this\._spotBarsVisible/);
assert.match(panelSource, /if \(!hasVisibleTooltipLayer\)/);
assert.doesNotMatch(panelSource, /if \(!this\._spotBarsVisible\) \{/);
assert.match(panelSource, /if \(!this\._debugEnabled \|\| !hasVisibleTooltipLayer \|\| !insidePlot/);
assert.match(panelSource, /generateUpcomingPriceAnalysis/);
assert.match(panelSource, /const markerLayouts = this\._spotBarsVisible/);
assert.match(panelSource, /const coveredBars = barGeometry\.filter/);
assert.match(panelSource, /const averageLineY = y\(average\)/);
assert.match(panelSource, /const obstacleTops = \[highestCoveredTop\];[\s\S]*if \(this\._averageLineVisible\) obstacleTops\.push\(averageLineY\)/);
assert.match(panelSource, /\$\{this\._averageLineVisible \? `<line class="chart-average"/);
assert.match(panelSource, /const markerLayoutsByHeight = \[\.\.\.markerLayouts\]/);
assert.doesNotMatch(panelSource, /const markerLabelY =/);
assert.match(panelSource, /data-price-analysis/);
assert.match(panelSource, /\.price-analysis/);
assert.match(panelSource, /white-space: normal/);
assert.match(panelSource, /text-overflow: clip/);
assert.match(panelSource, /overflow-wrap: anywhere/);
assert.match(panelSource, /price-analysis-status/);
assert.match(panelSource, /price-analysis-separator/);
assert.match(panelSource, /price-analysis-forecast/);
assert.match(panelSource, /@container price-card \(max-width: 480px\)/);
assert.match(panelSource, /\.price-analysis-separator \{[\s\S]*display: none/);
assert.match(panelSource, /\.price-analysis-forecast \{[\s\S]*overflow-wrap: anywhere/);
assert.match(panelSource, /\.price-summary \{[\s\S]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/);
assert.doesNotMatch(panelSource, /-webkit-line-clamp: 2/);
assert.match(panelSource, /separator\.textContent = " · "/);
assert.match(panelSource, /forecast\.textContent = upcoming\.forecast/);
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
assert.match(panelSource, /await this\.loadMeterPowerHistory\(\);\n        close\(\);/);
assert.match(panelSource, /meter_history_request_started/);
assert.match(panelSource, /meter_history_request_success/);
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
assert.doesNotMatch(panelSource, /transform: translate\(-50%, -100%\)/);

const technicalOutput = formatDiagnosticsText([
  { level: "DEBUG", component: "source", event: "debug_event", message: "Technical detail" },
], "0.0.64");
assert.match(technicalOutput, /DEBUG source debug_event/);
