import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const phaseChartRule = source.match(/\.phase-history-chart \{([\s\S]*?)\n        \}/)?.[1] || "";

assert.match(phaseChartRule, /margin-top: 2px;/);
assert.match(source, /\.phase-history-metric-selector \{[\s\S]*transform: translateY\(-10px\);/);
assert.match(source, /@media \(max-width: 600px\) \{[\s\S]*\.phase-history-chart \{[\s\S]*margin-top: 10px;/);
assert.match(source, /@media \(max-width: 600px\) \{[\s\S]*\.phase-history-metric-selector \{[\s\S]*transform: none;/);
assert.match(source, /\.price-chart \{[\s\S]*margin-top: 0;/);

console.log("phase spacing regression passed");
