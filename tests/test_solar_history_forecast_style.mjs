import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");

assert.match(source, /\.solar-history-reference-bar \{\s*fill-opacity: \.22;/);
assert.match(source, /solar-history-reference-bar" fill="\$\{chartColor\("socEstimated"\)\}"/);
assert.match(source, /\.solar-history-day\.hovered \.solar-history-bar \{\s*fill-opacity: 1;/);
assert.match(source, /\.solar-history-day\.hovered \.solar-history-reference-bar \{\s*fill-opacity: \.32;/);
assert.doesNotMatch(source, /\.solar-history-day\.hovered \.solar-history-reference-bar \{\s*fill-opacity: 1;/);
assert.match(source, /solar-history-bar" fill="\$\{chartColor\("solar"\)\}"/);

console.log("solar history forecast style regression passed");
