import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildCostAnalysisSeries, buildCostChartTooltipFields } from "../custom_components/elrakning/frontend/elrakning-panel.js";

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

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const costRender = source.slice(source.indexOf("  _renderCostChart(chart, series)"), source.indexOf("  _bindCostCard()"));

assert.match(costRender, /buildCostChartTooltipFields\(\{/);
assert.match(costRender, /<g class="cost-chart-hover" aria-hidden="true"><\/g>/);
assert.match(costRender, /svg\.addEventListener\("pointerdown", update\)/);
assert.match(costRender, /svg\.addEventListener\("pointermove", update\)/);
assert.match(costRender, /svg\.addEventListener\("pointerleave", clear\)/);
assert.match(costRender, /svg\.addEventListener\("pointercancel", clear\)/);
assert.match(costRender, /chart\.innerHTML =/);
assert.match(source, /\.cost-chart \{[\s\S]*min-height: 144px;/);
assert.match(source, /\.cost-details \{[\s\S]*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);/);
assert.match(source, /@container \(max-width: 600px\) \{[\s\S]*\.cost-details \{ grid-template-columns: repeat\(2, minmax\(0, 1fr\)\); \}/);

console.log("cost chart interaction and compact layout regression passed");
