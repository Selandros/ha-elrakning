import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildBatteryDailyHistory, buildCanonicalMeterPoints, buildContinuousGapPairs, buildEnergyBalance, buildMonotoneCubicSegments, buildPriceAnalysisFacts, buildSolarDailyHistory, buildSolarHistoryTooltipLines, buildThresholdClippedSegments, createPriceDebugText, diagnosticComponent, diagnosticSymbol, displayPowerValue, formatDiagnosticsText, generateUpcomingPriceAnalysis, integratePowerHistoryKwh, isVisiblePowerValue, nearestMeterPoint, normalizeMeterValue, POWER_DISPLAY_THRESHOLD_KW, priceCategory, priceColorBands, priceColorDetails, providerLabel, renderPriceAnalysis, snapTooltipTimestamp } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const output = formatDiagnosticsText([
  {
    timestamp: "2026-08-22T10:00:00.000Z",
    level: "INFO",
    component: "source",
    event: "source_loading",
    message: "Loading source data",
  },
], "0.0.64");
const eonPanelSource = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
assert.match(eonPanelSource, /data-provider-card="elnet"/);
assert.match(eonPanelSource, /elrakning\/grid\/state/);
assert.match(eonPanelSource, /data-eon-grid-app-account/);
assert.match(eonPanelSource, /data-eon-grid-app-password/);
assert.match(eonPanelSource, /data-eon-grid-web-connect/);
assert.match(eonPanelSource, /data-eon-grid-web-status/);
assert.doesNotMatch(eonPanelSource, /data-eon-grid-web-account/);
assert.doesNotMatch(eonPanelSource, /data-eon-grid-web-password/);
assert.match(eonPanelSource, /elrakning\/grid\/login/);
assert.match(eonPanelSource, /data-eon-grid-source/);
assert.match(eonPanelSource, /elrakning\/grid\/source_data/);
assert.match(eonPanelSource, /data-eon-grid-common-api-probe/);
assert.match(eonPanelSource, /elrakning\/grid\/common_api_probe/);
assert.match(eonPanelSource, /Testa Common API/);
assert.match(eonPanelSource, /response\.status === "ok"/);
assert.match(eonPanelSource, /response\.status === "denied_401"/);
assert.match(eonPanelSource, /response\.status === "denied_403"/);
assert.match(eonPanelSource, /JSON\.stringify\(response\.payload, null, 2\)/);
assert.match(eonPanelSource, /_isEonCommonApiProbeVisible\(\)/);
assert.match(eonPanelSource, /this\._eonGridState\?\.provider === "eon"/);
assert.match(eonPanelSource, /this\._eonGridState\?\.auth_method === "app"/);
assert.match(eonPanelSource, /elrakning-eon-handoff-state/);
assert.match(eonPanelSource, /elrakning-eon-handoff-status/);

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
assert.equal(POWER_DISPLAY_THRESHOLD_KW, 0.1);
assert.equal(displayPowerValue(0.1), 0);
assert.equal(displayPowerValue(-0.1), 0);
assert.equal(displayPowerValue(0.11), 0.11);
assert.equal(displayPowerValue("not-a-number"), null);
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
  {},
  new Date(2026, 7, 23, 12, 0),
  1,
  { today_kwh: 2, remaining_today_kwh: 1 },
);
assert.equal(solarTodayOverExpected[0].utilizationPercent, 200);
const solarTodayMissingRemaining = buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 23, 0, 0), 1, 13),
  { "2026-08-23": 14.1 },
  new Date(2026, 7, 23, 12, 0),
  1,
  { today_kwh: 14.1 },
);
assert.equal(solarTodayMissingRemaining[0].utilizationPercent, null);
assert.equal(buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 23, 0, 0), 1, 13),
  { "2026-08-23": 14.1 },
  new Date(2026, 7, 23, 12, 0),
  1,
  { today_kwh: 14.1, remaining_today_kwh: 14.1 },
)[0].utilizationPercent, null);
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
const solarOverReference = buildSolarDailyHistory(
  dailyHistoryPoints(new Date(2026, 7, 22, 0, 0), 2, 13),
  { "2026-08-22": 1 },
  new Date(2026, 7, 23, 12, 0),
  2,
);
assert.equal(solarOverReference[0].forecastKwh, 1);
assert.equal(solarOverReference[0].utilizationPercent, 200);
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
assert.match(panelSource, /data-config-card-key="elmatare"/);
assert.match(panelSource, /data-config-card-key="solar"/);
assert.doesNotMatch(panelSource, /data-config-card-key="consumption"/);
assert.match(panelSource, /data-config-card-key="battery"/);
assert.match(panelSource, /data-main-card-toggle/);
assert.equal((panelSource.match(/class="main-card-toggle"/g) || []).length, 5);
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
assert.match(panelSource, /\["Förbrukat idag", power\.consumption_energy_kwh, "kWh"\]/);
assert.match(panelSource, /data-power-card="battery-history"/);
assert.match(panelSource, /data-power-card="solar-history"/);
assert.match(panelSource, /id="solar-history-title" class="visually-hidden">Solhistorik<\/h2>/);
assert.match(panelSource, /Batterihistorik/);
assert.match(panelSource, /aria-labelledby="battery-history-title"/);
assert.match(panelSource, /id="battery-history-title" class="visually-hidden">Batterihistorik<\/h2>/);
assert.match(panelSource, /const chart = this\.host\.querySelector\("\[data-battery-history-chart\]"\);\n\s+if \(!card \|\| !chart\) return;/);
assert.doesNotMatch(panelSource, /data-battery-history-status/);
assert.match(panelSource, /\.battery-history-axis-label,[\s\S]*\.battery-history-day-label \{[\s\S]*font-size: 10px;[\s\S]*font-weight: 400;/);
assert.match(panelSource, /\.battery-history-utilization \{[\s\S]*font-weight: 600;/);
assert.match(panelSource, /battery-history-y-label-rail/);
assert.match(panelSource, /battery-history-x-label-rail/);
assert.match(panelSource, /\.battery-history-x-label \{[\s\S]*top: 62%;[\s\S]*transform: translate\(-50%, -50%\);/);
assert.match(panelSource, /font-size: 10px;[\s\S]*font-weight: 400;[\s\S]*line-height: 1;/);
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
assert.match(panelSource, /solar-history-reference-bar \{[\s\S]*color-mix\(in srgb, var\(--solar-color\) 30%/);
assert.match(panelSource, /solar-history-day\.hovered \.solar-history-reference-bar/);
assert.match(panelSource, /buildSolarHistoryTooltipLines\(day, this\._powerHistory\?\.solar_forecast/);
assert.match(panelSource, /Prognos hittills:/);
assert.match(panelSource, /Dagsprognos:/);
assert.doesNotMatch(panelSource, /<strong>\$\{day\.date\}<\/strong><span>Producerat:/);
assert.doesNotMatch(panelSource, /tooltip\.innerHTML = `[^`]*utilizationPercent/);
assert.match(panelSource, /\.solar-history-chart \.soc-tooltip > span/);
assert.match(panelSource, /solar_forecast_baselines/);
assert.match(panelSource, /elrakning\/solar_forecast_state/);
assert.match(panelSource, /elrakning_solar_forecast_update/);
assert.doesNotMatch(panelSource, /solar-history-reference-bar[\s\S]*referenceKwh/);
assert.doesNotMatch(panelSource, /Solpotential/);
assert.match(panelSource, /solar_array_metadata/);
assert.match(panelSource, /tooltip\.innerHTML = `[^`]*<span>Laddat:/);
assert.doesNotMatch(panelSource, /tooltip\.innerHTML = `[^`]*<strong>\$\{day\.date\}<\/strong><span>Laddat:/);
assert.match(panelSource, /<span>Urladdat: \$\{formatEnergy\(day\.dischargingKwh\)\}<\/span>`;/);
assert.doesNotMatch(panelSource, /tooltip\.innerHTML = `[^`]*Kapacitetsutnyttjande:/);
assert.match(panelSource, /battery-history-utilization/);
assert.doesNotMatch(panelSource, /battery-history-hover/);
assert.match(panelSource, /battery-history-day\.hovered \.battery-history-bar/);
assert.match(panelSource, /group\.classList\.add\("hovered"\)/);
assert.match(panelSource, /hoveredDay\?\.classList\.remove\("hovered"\)/);
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
assert.match(panelSource, /data-soc-card/);
assert.match(panelSource, /Batteri SOC/);
assert.match(panelSource, /\.daily-energy-row \{\n\s+align-items: stretch;\n\s+display: grid;\n\s+gap: 16px;\n\s+grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/);
assert.match(panelSource, /\.daily-energy-row \{\n\s+align-items: stretch;\n\s+display: grid;/);
assert.match(panelSource, /daily-energy-row[\s\S]*data-daily-energy[\s\S]*data-soc-card/);
assert.match(panelSource, /_syncSocCardHeight\(\)/);
assert.match(panelSource, /energyCard\.getBoundingClientRect\(\)\.height/);
assert.match(panelSource, /socCard\.style\.height = `\$\{height\}px`/);
assert.match(panelSource, /_setupSocCardHeightObserver\(\)/);
assert.match(panelSource, /new ResizeObserver\(\(\) => this\._syncSocCardHeight\(\)\)/);
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
assert.match(panelSource, /\.soc-card \{\n\s+--soc-color: var\(--el-solar-color\);[\s\S]*display: flex;[\s\S]*flex-direction: column;/);
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
assert.match(panelSource, /\.soc-chart \{[\s\S]*flex: 1;[\s\S]*margin: 0;[\s\S]*min-height: 0;[\s\S]*width: 100%;/);
assert.match(panelSource, /\.soc-chart-svg \{[\s\S]*height: 100%;[\s\S]*width: 100%;/);
assert.match(panelSource, /\.soc-chart-svg \{[\s\S]*overflow: visible;/);
assert.doesNotMatch(panelSource, /\.soc-chart-svg \{[\s\S]*aspect-ratio: 960 \/ 340;/);
assert.match(panelSource, /<svg class="soc-chart-svg" preserveAspectRatio="none" viewBox="0 0 \$\{width\} \$\{height\}"/);
assert.match(panelSource, /const height = 340;/);
assert.match(panelSource, /\.soc-label-rail \{[\s\S]*position: absolute;[\s\S]*width: 4\.583333%;/);
assert.match(panelSource, /\.soc-label \{[\s\S]*font-size: 10px;[\s\S]*font-weight: 400;[\s\S]*position: absolute;[\s\S]*left: 0;[\s\S]*right: 0;[\s\S]*text-align: center;[\s\S]*transform: translateY\(-50%\);/);
assert.match(panelSource, /const plot = \{ left: 44, right: 8, top: 8, bottom: 8 \};/);
assert.match(panelSource, /const xStart = dayStart\.getTime\(\);/);
assert.match(panelSource, /const xEnd = points\.at\(-1\)\.timestamp;/);
assert.match(panelSource, /const xDuration = Math\.max\(1, xEnd - xStart\);/);
assert.match(panelSource, /const svgX = rect\.width > 0 \? \(\(event\.clientX - rect\.left\) \/ rect\.width\) \* width : plot\.left;/);
assert.match(panelSource, /const clampedSvgX = Math\.max\(plot\.left, Math\.min\(width - plot\.right, svgX\)\);/);
assert.match(panelSource, /const plotRatio = plotWidth > 0 \? \(clampedSvgX - plot\.left\) \/ plotWidth : 0;/);
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
assert.match(panelSource, /Laddnivå: \$\{this\._formatNumber\(point\.value\)\} %/);
assert.doesNotMatch(panelSource, /integratePowerHistoryKwh\([^)]*soc/);
assert.match(panelSource, /\["Import idag", "energy_import_entity"\]/);
assert.match(panelSource, /\["Export idag", "energy_export_entity"\]/);
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
assert.match(panelSource, /chart_layers/);
assert.doesNotMatch(panelSource, /class="chart-legend-toggle active" data-chart-layer/);
assert.match(panelSource, /this\._averageLineVisible = true/);
assert.match(panelSource, /chart-legend-swatch\.average \{[\s\S]*background: var\(--el-price-normal-color\)/);
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
assert.match(panelSource, /#F0A06A/);
assert.match(panelSource, /#72AAF6/);
assert.equal((panelSource.match(/--el-import-color: #F0A06A/g) || []).length, 1);
assert.equal((panelSource.match(/--el-export-color: #72AAF6/g) || []).length, 1);
const mobileMediaIndex = panelSource.indexOf("@media (max-width: 600px)");
const globalImportIndex = panelSource.indexOf("--el-import-color: #F0A06A");
const globalExportIndex = panelSource.indexOf("--el-export-color: #72AAF6");
assert.ok(globalImportIndex >= 0 && globalImportIndex < mobileMediaIndex);
assert.ok(globalExportIndex >= 0 && globalExportIndex < mobileMediaIndex);
assert.match(panelSource, /\.price-section \{\n\s+--solar-color: var\(--el-solar-color\);\n\s+--consumption-color: var\(--el-consumption-color\);\n\s+--grid-import-color: var\(--el-import-color\);\n\s+--grid-export-color: var\(--el-export-color\);\n\s+--charging-color: var\(--el-charging-color\);\n\s+--discharging-color: var\(--el-discharging-color\);/);
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
assert.match(panelSource, /\.chart-bar\.cheap \{\n\s+fill: color-mix\(in srgb, var\(--el-price-cheap-color\) 41%,/);
assert.match(panelSource, /\.chart-bar\.normal \{\n\s+fill: color-mix\(in srgb, var\(--el-price-normal-color\) 41%,/);
assert.match(panelSource, /\.chart-bar\.expensive \{\n\s+fill: color-mix\(in srgb, var\(--el-price-expensive-color\) 41%,/);
assert.equal((panelSource.match(/\.chart-bar\.(?:cheap|normal|expensive) \{\n\s+fill: color-mix\(in srgb, [^\n]+ 41%,/g) || []).length, 3);
assert.doesNotMatch(panelSource, /\.daily-energy-segment \{\n\s+filter:/);
assert.match(panelSource, /\.daily-energy-segment\.local \{[\s\S]*background: color-mix\(in srgb, var\(--daily-energy-local-color\) 70%,/);
assert.match(panelSource, /\.daily-energy-segment\.export \{[\s\S]*background: color-mix\(in srgb, var\(--daily-energy-export-color\) 70%,/);
assert.match(panelSource, /\.daily-energy-segment\.import \{[\s\S]*background: color-mix\(in srgb, var\(--daily-energy-import-color\) 70%,/);
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
assert.match(panelSource, /\$\{bars\}\n      \$\{meterAreas\}\n      \$\{meterLines\}/);
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
assert.doesNotMatch(panelSource, /price-marker-label/);
assert.doesNotMatch(panelSource, /priceMarkers/);
assert.doesNotMatch(panelSource, /markerGroups/);
assert.doesNotMatch(panelSource, /markerLayouts/);
assert.doesNotMatch(panelSource, /markerMinY|markerHeight|markerGap/);
assert.ok((panelSource.match(/var\(--ha-card-background, var\(--card-background-color\)\)/g) || []).length >= 4);
assert.match(panelSource, /_buildVisibleTooltipRows\(comparisonPrice, details, layers = this\._chartLayerState\(\)\)/);
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
assert.match(panelSource, /chart-legend-preview\.solar/);
assert.match(panelSource, /chart-legend-preview\.consumption/);
assert.match(panelSource, /chart-legend-preview\.charging/);
assert.match(panelSource, /chart-legend-preview\.discharging/);
assert.match(panelSource, /data-preview-layer="solar"/);
assert.match(panelSource, /data-preview-layer="consumption"/);
assert.match(panelSource, /data-preview-layer="charging"/);
assert.match(panelSource, /data-preview-layer="discharging"/);
assert.match(panelSource, /data-power-card="solar"/);
assert.doesNotMatch(panelSource, /data-power-card="consumption"/);
assert.match(panelSource, /data-power-card="battery"/);
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
assert.match(panelSource, /this\.renderPriceChart\(\);\n        this\._persistChartPreferences\(\);/);
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
assert.match(panelSource, /rows\.push\(`<span class="tooltip-value">Spotpris: \$\{this\.formatPrice\(comparisonPrice\)\}<\/span>`\)/);
assert.doesNotMatch(panelSource, /<span class="tooltip-value">Elhandel:/);
assert.doesNotMatch(panelSource, /<span class="tooltip-value">Elnät:/);
assert.match(panelSource, /layers\.import && isVisiblePowerValue\(details\?\.import_kw\)/);
assert.match(panelSource, /layers\.export && isVisiblePowerValue\(details\?\.export_kw\)/);
assert.match(panelSource, /tooltip-meter-import/);
assert.match(panelSource, /tooltip-meter-export/);
assert.match(panelSource, /tooltip\.innerHTML =/);
assert.match(panelSource, /\$\{tooltipRows\}/);
assert.match(panelSource, /periods\.forEach\(\(period, index\) =>/);
assert.match(panelSource, /_hoverIsolatedLayer = null/);
assert.match(panelSource, /_effectiveChartLayerState\(\)/);
assert.match(panelSource, /pointerenter/);
assert.match(panelSource, /pointerleave/);
assert.match(panelSource, /event\.pointerType === "touch" \|\| button\.disabled/);
assert.doesNotMatch(panelSource, /event\.pointerType === "touch" \|\| !this\._chartLayerState\(\)\[layer\]/);
assert.match(panelSource, /const hasVisibleTooltipLayer = this\._spotBarsVisible/);
assert.match(panelSource, /if \(!hasVisibleTooltipLayer\)/);
assert.doesNotMatch(panelSource, /if \(!this\._spotBarsVisible\) \{/);
assert.match(panelSource, /if \(!this\._debugEnabled \|\| !hasVisibleTooltipLayer \|\| !insidePlot/);
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
assert.match(panelSource, /chart_debug_copy_clicked/);
assert.match(panelSource, /chart_debug_copy_text_length/);
assert.match(panelSource, /chart_debug_copy_success/);
assert.match(panelSource, /_recordDiagnostic\("price", "INFO", "chart_debug_copy_clicked"/);
assert.match(panelSource, /_recordMeterDiagnostic\("INFO", "meter_save_clicked"/);
assert.match(panelSource, /lastChartDebugCopyAt/);
assert.match(panelSource, /clipboardError/);
assert.doesNotMatch(panelSource, /tooltip_click_received/);
assert.doesNotMatch(panelSource, /tooltip_copy_text_length/);
assert.match(panelSource, /await this\.loadMeterPowerHistory\(\);\n        await this\.loadPowerHistory\(\);\n        close\(\);/);
assert.match(panelSource, /this\.loadMeterState\(loadHistory\)/);
assert.match(panelSource, /\[mapping\.power_entity, mapping\.energy_import_entity, mapping\.energy_export_entity\]\.includes\(entityId\)\) \{\s*this\.loadMeterState\(\);/);
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
