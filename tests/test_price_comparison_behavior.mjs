import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mergePowerHistoryRefreshState } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const panelSource = readFileSync(
  new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url),
  "utf8",
);

const start = panelSource.indexOf("  _periodCustomerPrice(period) {");
const end = panelSource.indexOf("  _hasTradePriceData() {", start);
assert.ok(start >= 0 && end > start, "price comparison methods must be present");

const methodSource = panelSource.slice(start, end).trim();
const PriceHarness = Function(`"use strict"; return class { ${methodSource} };`)();

function priceHarness(periods, visible = { electricity: true, grid: false }) {
  const harness = new PriceHarness();
  harness.priceData = { periods };
  harness._priceComparisonVisible = { ...visible };
  return harness;
}

const activePeriod = {
  spot_price_ex_vat: 0.50,
  electricity_cost_ex_vat: 0.10,
  grid_cost_ex_vat: 0.20,
  grid_contract_source_status: "ACTIVE",
  customer_price: 99,
};

const off = priceHarness([activePeriod], { electricity: true, grid: false });
assert.equal(off._hasGridPriceData(), true);
assert.equal(off._comparisonPrice(activePeriod), 75);
assert.equal(off._periodCustomerPrice(activePeriod), 75);

const on = priceHarness([activePeriod], { electricity: true, grid: true });
assert.equal(on._hasGridPriceData(), true);
assert.equal(on._comparisonPrice(activePeriod), 100);
assert.equal(on._periodCustomerPrice(activePeriod), on._comparisonPrice(activePeriod));
assert.equal(on._comparisonPrice(activePeriod) - off._comparisonPrice(activePeriod), 25);

const nullGridPeriod = {
  ...activePeriod,
  grid_cost_ex_vat: null,
};
const nullGrid = priceHarness([nullGridPeriod], { electricity: true, grid: true });
assert.equal(nullGrid._hasGridPriceData(), false);
assert.equal(nullGrid._comparisonPrice(nullGridPeriod), 75);
assert.equal(nullGrid._periodCustomerPrice(nullGridPeriod), 75);

const futureGridPeriod = {
  ...activePeriod,
  grid_cost_ex_vat: 1.136,
  grid_contract_source_status: "FUTURE",
};
const futureGrid = priceHarness([futureGridPeriod], { electricity: true, grid: true });
assert.equal(futureGrid._hasGridPriceData(), false);
assert.equal(futureGrid._comparisonPrice(futureGridPeriod), 75);
assert.equal(futureGrid._periodCustomerPrice(futureGridPeriod), 75);

const hourlyRender = panelSource.slice(
  panelSource.indexOf("  _renderHourlyPriceChart(options = {})"),
  panelSource.indexOf("  autoScrollToNow(", panelSource.indexOf("  _renderHourlyPriceChart(options = {})")),
);
assert.match(
  hourlyRender,
  /const prices = periods\.map\(\(period\) => this\._periodCustomerPrice\(period\)\)/,
  "hourly bars, average and colors must use the delegated comparison price",
);
assert.match(
  panelSource,
  /_periodCustomerPrice\(period\) \{\s*return this\._comparisonPrice\(period\);\s*\}/,
  "hourly rendered price must delegate to the same comparison calculation used by tooltips/aggregates",
);
assert.match(
  panelSource,
  /const comparisonPrice = this\._comparisonPrice\(period\);/,
  "tooltip must use the same comparison calculation",
);

assert.match(
  hourlyRender,
  /selectPowerForecastPoints\(source,\s*\{[\s\S]*?\}\)/,
  "forecast power must remain direct value_kw points",
);
assert.match(
  hourlyRender,
  /includeElapsed: false/,
  "presentation must split today's forecast after now while backend keeps full-day payload",
);
assert.match(
  hourlyRender,
  /const actualDayEnd = localDateKey\(dayStart\) === localDateKey\(now\)[\s\S]*?now\.getTime\(\)[\s\S]*?dayEnd\.getTime\(\)/,
  "actual power must be bounded by now on the current local day",
);
assert.match(
  hourlyRender,
  /timestamp <= actualDayEnd/,
  "actual history must not render future points",
);
assert.doesNotMatch(
  hourlyRender,
  /dualAxis:\s*true[\s\S]*rightAxisLabels/,
  "hourly price chart must keep price as background without a price axis",
);

const forecastState = {
  schema: "ella_power_forecast.v1",
  available: true,
  series: { solar: { available: true, forecast_points: [{ timestamp: "2026-09-30T10:00:00Z", value_kw: 2 }] } },
};
const sameContextRefresh = mergePowerHistoryRefreshState({
  response: { date: "2026-09-30" },
  series: { solar: { points: [{ timestamp: "2026-09-30T09:00:00Z", value_kw: 1 }] } },
  existingState: { power_forecast: forecastState, solar_evidence: { available: true } },
  contextKey: "site-a:1:2026-09-30",
  previousContextKey: "site-a:1:2026-09-30",
});
assert.equal(sameContextRefresh.power_forecast, forecastState, "history refresh must preserve forecast in the same context");
const differentContextRefresh = mergePowerHistoryRefreshState({
  response: { date: "2026-10-01" },
  series: { solar: { points: [] } },
  existingState: { power_forecast: forecastState },
  contextKey: "site-a:1:2026-10-01",
  previousContextKey: "site-a:1:2026-09-30",
});
assert.equal(differentContextRefresh.power_forecast.available, false, "site/date context change must not reuse forecast");
assert.match(panelSource, /mergePowerHistoryRefreshState\(/, "history refresh must assemble actual and forecast state without replacement");

console.log("price comparison behavior PASS");
