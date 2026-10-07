import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { applyCanonicalEnergyHistoryResponse, buildCanonicalEnergyHistoryContextKey, buildThresholdClippedSegments, canonicalEnergyHistoryCacheIsUsable, canonicalEnergyHistoryViewIsCurrent, energyHistoryIntervalValueAt, energyHistoryToMeterCurvePoints, energyHistoryToMeterStepPoints, energyIntervalsToCurvePoints, energyIntervalsToStepPoints, integrateEnergyIntervalsKwh, selectHourlyPricePeriods } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const panelSource = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const websocketSource = readFileSync(new URL("../custom_components/elrakning/websocket.py", import.meta.url), "utf8");
const periods = [
  { start: "2026-08-31T12:00:00+02:00", end: "2026-08-31T13:00:00+02:00", price: 100 },
  { start: "2026-09-01T12:00:00+02:00", end: "2026-09-01T13:00:00+02:00", price: 300 },
];


const hourlyIntervals = [{
  start: "2026-08-30T10:00:00+02:00",
  end: "2026-08-30T11:00:00+02:00",
  value_kw: 2,
  resolution_seconds: 3600,
  source: "home_assistant_long_term_statistics",
}];
const hourlyStep = energyIntervalsToStepPoints(hourlyIntervals);
assert.equal(hourlyStep.length, 2);
assert.equal(hourlyStep[0].value_kw, 2);
assert.equal(hourlyStep[0].source_resolution_seconds, 3600);
assert.equal(hourlyStep[0].history_interval_id, hourlyStep[1].history_interval_id);
assert.deepEqual(energyIntervalsToStepPoints([{ ...hourlyIntervals[0], value_kw: null }]), []);
assert.deepEqual(energyIntervalsToCurvePoints([{ ...hourlyIntervals[0], value_kw: null }]), []);
const historicalSegments = buildThresholdClippedSegments(hourlyStep, "value_kw");
assert.equal(historicalSegments.length, 1);
assert.equal(historicalSegments[0].length, 2);
assert.equal(integrateEnergyIntervalsKwh(hourlyIntervals, "2026-08-30T10:00:00+02:00", "2026-08-30T11:00:00+02:00"), 2);
const meterStep = energyHistoryToMeterStepPoints({ series: {
  import: hourlyIntervals,
  export: [{ ...hourlyIntervals[0], value_kw: 0.5 }],
} });
assert.equal(meterStep[0].import_kw, 2);
assert.equal(meterStep[0].export_kw, 0.5);

const adjacentHourly = [
  { ...hourlyIntervals[0], start: "2026-08-30T11:00:00+02:00", end: "2026-08-30T12:00:00+02:00", value_kw: 3.25 },
  { ...hourlyIntervals[0], start: "2026-08-30T12:00:00+02:00", end: "2026-08-30T13:00:00+02:00", value_kw: 3.69 },
];
const longTermHistory = { series: { solar: adjacentHourly } };
assert.equal(energyHistoryIntervalValueAt(longTermHistory, "solar", "2026-08-30T11:15:00+02:00"), 3.25);
assert.equal(energyHistoryIntervalValueAt(longTermHistory, "solar", "2026-08-30T11:45:00+02:00"), 3.25);
assert.equal(energyHistoryIntervalValueAt(longTermHistory, "solar", "2026-08-30T12:15:00+02:00"), 3.69);
const curvePoints = energyIntervalsToCurvePoints(adjacentHourly);
assert.equal(curvePoints.length, 3);
assert.equal(curvePoints[0].history_curve, true);
assert.equal(curvePoints[0].source_resolution_seconds, 3600);
const curveSegments = buildThresholdClippedSegments(curvePoints, "value_kw");
assert.equal(curveSegments.length, 1);
assert.equal(curveSegments[0].length, 3);
const meterCurve = energyHistoryToMeterCurvePoints({ series: { import: adjacentHourly } });
assert.equal(meterCurve.length, 3);
assert.equal(meterCurve[1].import_kw, 3.69);

const hourlyWithGap = [adjacentHourly[0], {
  ...adjacentHourly[1],
  start: "2026-08-30T13:00:00+02:00",
  end: "2026-08-30T14:00:00+02:00",
}];
const gapCurve = energyIntervalsToCurvePoints(hourlyWithGap);
const gapSegments = buildThresholdClippedSegments(gapCurve, "value_kw");
assert.equal(gapSegments.length, 2);
assert.ok(gapSegments.every((segment) => segment.length === 2));

const august = selectHourlyPricePeriods(periods, new Date(2026, 7, 31));
assert.deepEqual(august.map((period) => period.price), [100]);
assert.ok(august.every((period) => new Date(period.start).getDate() === 31));

const september = selectHourlyPricePeriods(periods, new Date(2026, 8, 1));
assert.deepEqual(september.map((period) => period.price), [300]);
assert.ok(september.every((period) => new Date(period.start).getDate() === 1));
assert.notDeepEqual(august, september);
const adjacentDays = [
  { start: "2026-10-03T23:00:00+02:00", end: "2026-10-04T00:00:00+02:00", price: 10 },
  { start: "2026-10-04T00:00:00+02:00", end: "2026-10-04T01:00:00+02:00", price: 20 },
];
assert.deepEqual(selectHourlyPricePeriods(adjacentDays, new Date("2026-10-03T12:00:00+02:00")).map((period) => period.price), [10]);
assert.deepEqual(selectHourlyPricePeriods(adjacentDays, new Date("2026-10-04T12:00:00+02:00")).map((period) => period.price), [20]);

assert.match(panelSource, /selectHourlyPricePeriods\(this\.priceData\.periods, selectedDate\)/);
assert.doesNotMatch(panelSource, /_tomorrowPriceData|tomorrowPeriods|timelineDayCount/);
assert.match(panelSource, /const periods = this\._periodPickerState\?\.mode === "hour"/);
assert.doesNotMatch(panelSource, /await this\.hass\.callWS\(requestDate\(tomorrow\)\)/);
assert.match(panelSource, /const requestDate = \(date\) =>/);
assert.match(panelSource, /request\.date = `\$\{date\.getFullYear\(\)\}/);
assert.match(panelSource, /const requestedDate = selectedDate instanceof Date \? selectedDate : this\._periodPickerState\?\.confirmed \|\| new Date\(\);/);
assert.doesNotMatch(panelSource, /const tomorrow = new Date\(requestedDate\);/);
assert.match(panelSource, /const applySelectedHourDate = async \(date\) =>/);
assert.match(panelSource, /await applySelectedHourDate\(date\)/);
assert.match(panelSource, /applySelectedHourDate\(this\._periodPickerState\.draft\)/);
assert.match(websocketSource, /vol\.Optional\("date"\): str/);
assert.match(websocketSource, /target_date = date\.fromisoformat\(requested_date\)/);
assert.match(websocketSource, /current_data = coordinator\.data/);
assert.match(websocketSource, /current_data\.date == target_date/);
assert.match(websocketSource, /await coordinator\.async_get_price_data\(target_date\)/);
const priceHandler = websocketSource.slice(websocketSource.indexOf("async def websocket_get_price_data"), websocketSource.indexOf("async def _async_canonical_energy_history_for_date"));
assert.doesNotMatch(priceHandler, /_site_is_configured\(hass\)/);
assert.match(websocketSource, /site_manager\.global_binding\("nord_pool"\)/);
assert.match(websocketSource, /else:\n\s+data = coordinator\.data/);

assert.doesNotMatch(priceHandler, /async_build_energy_history/);
assert.match(priceHandler, /global_binding\("nord_pool"\)/);
assert.match(priceHandler, /response\["binding"\] = global_binding/);
const canonicalHistoryHandler = websocketSource.slice(websocketSource.indexOf("async def websocket_canonical_energy_history"), websocketSource.indexOf("async def websocket_greenely_test"));
assert.match(websocketSource, /CANONICAL_ENERGY_HISTORY_COMMAND = f"\{DOMAIN\}\/canonical_energy_history"/);
assert.match(websocketSource, /local_day_slots\(target_date, timezone_name\)/);
assert.match(canonicalHistoryHandler, /_async_canonical_energy_history_for_date/);
assert.match(websocketSource, /asyncio\.shield\(task\)/);
const loadPriceDataSource = panelSource.slice(panelSource.indexOf("  async loadPriceData("), panelSource.indexOf("  async loadPricePlan("));
assert.ok(
  loadPriceDataSource.indexOf("void this.loadCanonicalEnergyHistory(requestedDate);")
    < loadPriceDataSource.indexOf("await this.hass.callWS(requestDate(requestedDate))"),
  "canonical history must start without waiting for price data",
);
assert.match(loadPriceDataSource, /this\._canonicalEnergyHistoryContextKey === contextKey/);
assert.match(panelSource, /async loadCanonicalEnergyHistory\(selectedDate = null\)/);
assert.match(panelSource, /type: "elrakning\/canonical_energy_history"/);
assert.match(panelSource, /canonical_energy_history_stale_rejected/);
assert.match(panelSource, /canonical_energy_history_merge/);
const canonicalHistory = { series: { import: [{ start: "2026-10-03T22:00:00Z", end: "2026-10-03T22:15:00Z", value_kw: 0.392 }] } };
assert.equal(buildCanonicalEnergyHistoryContextKey("site-a", 4, "2026-10-04"), "site-a:4:2026-10-04");
const connection = {};
const stableCanonicalView = (date) => canonicalEnergyHistoryViewIsCurrent({
  requestSiteId: "site-a",
  requestSiteContextGeneration: 4,
  requestDate: date,
  requestLifecycleToken: 1,
  activeSiteId: "site-a",
  activeSiteContextGeneration: 4,
  activeDate: date,
  activeLifecycleToken: 1,
  requestConnection: connection,
  activeConnection: connection,
});
for (const date of ["2026-10-03", "2026-10-04", "2026-10-03", "2026-10-02", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]) {
  assert.equal(stableCanonicalView(date), true, `same view must accept ${date} regardless of sibling completion`);
}
assert.equal(canonicalEnergyHistoryViewIsCurrent({
  requestSiteId: "site-a",
  requestSiteContextGeneration: 4,
  requestDate: "2026-10-03",
  requestLifecycleToken: 1,
  activeSiteId: "site-a",
  activeSiteContextGeneration: 4,
  activeDate: "2026-10-04",
  activeLifecycleToken: 1,
  requestConnection: connection,
  activeConnection: connection,
}), false, "a late response for a previous day must remain rejected");
assert.equal(canonicalEnergyHistoryViewIsCurrent({
  requestSiteId: "site-a",
  requestSiteContextGeneration: 4,
  requestDate: "2026-10-04",
  requestLifecycleToken: 1,
  activeSiteId: "site-a",
  activeSiteContextGeneration: 4,
  activeDate: "2026-10-04",
  activeLifecycleToken: 1,
  requestConnection: connection,
  activeConnection: {},
}), false, "a reconnect must reject the old request");
const cachedHistory = { energyHistory: canonicalHistory, loadedAt: 10_000 };
assert.equal(canonicalEnergyHistoryCacheIsUsable(cachedHistory, { isCurrentDate: false, now: 999_999 }), true);
assert.equal(canonicalEnergyHistoryCacheIsUsable(cachedHistory, { isCurrentDate: true, now: 14_999 }), true);
assert.equal(canonicalEnergyHistoryCacheIsUsable(cachedHistory, { isCurrentDate: true, now: 15_001 }), false);
assert.deepEqual(applyCanonicalEnergyHistoryResponse({
  response: { success: true, site_id: "site-a", date: "2026-10-04", energy_history: canonicalHistory },
  expectedSiteId: "site-a",
  expectedDate: "2026-10-04",
  activeSiteId: "site-a",
}), { accepted: true, reason: null, energyHistory: canonicalHistory });
assert.equal(applyCanonicalEnergyHistoryResponse({
  response: { success: true, site_id: "site-a", date: "2026-10-03", energy_history: canonicalHistory },
  expectedSiteId: "site-a",
  expectedDate: "2026-10-04",
  activeSiteId: "site-a",
}).accepted, false);
assert.equal(applyCanonicalEnergyHistoryResponse({
  response: { success: true, site_id: "site-a", date: "2026-10-04", energy_history: canonicalHistory },
  expectedSiteId: "site-a",
  expectedDate: "2026-10-04",
  activeSiteId: "site-b",
}).accepted, false);
assert.match(panelSource, /const energyHistory = this\.priceSnapshot\?\.energy_history \|\| \{\};/);
assert.match(panelSource, /this\.loadPowerState\(loadHistory\),[\s\S]*this\.loadSolarEvidence\(\),/);
assert.doesNotMatch(panelSource.slice(panelSource.indexOf("  async _refreshBackendState"), panelSource.indexOf("  async loadPriceData")), /this\.loadBillingHistory\(\),/);
assert.match(panelSource, /void this\.loadBillingHistory\(\);/);
assert.match(panelSource, /const meterSelection = mergeMeterRenderPoints\(rawMeterPoints, historicalMeterPoints\)/);
assert.match(panelSource, /canonicalEnergyHistoryViewIsCurrent\(\{/);
assert.match(panelSource, /canonical_energy_history_cache_hit/);
assert.match(panelSource, /_canonicalEnergyHistoryInFlight\.get\(contextKey\)/);
assert.match(panelSource, /requestConnection !== this\.hass\?\.connection/);
assert.doesNotMatch(panelSource.slice(panelSource.indexOf("async loadCanonicalEnergyHistory"), panelSource.indexOf("async loadPricePlan")), /requestHass !== this\.hass/);
assert.match(panelSource, /const useHistoricalPower = rawPoints\.length === 0 && historicalPoints\.length > 0/);
assert.match(panelSource, /const mergedPowerPoints = historicalPoints\.length[\s\S]*?const displaySource = mergedPowerPoints\.length/);
assert.match(panelSource, /const meterValue = \(key\) => canonicalMeterPoint && Number\.isFinite\(Number\(canonicalMeterPoint\[key\]\)\)\n        \? Number\(canonicalMeterPoint\[key\]\)\n        : hoverGeometry\?\.meterDisplayValue\?\.\(key, tooltipTimestamp\) \?\? null;/);

console.log("selected hourly price date regression passed");
