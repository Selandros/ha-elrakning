import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { performanceWarningKind } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const panel = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const websocket = readFileSync(new URL("../custom_components/elrakning/websocket.py", import.meta.url), "utf8");

assert.equal(performanceWarningKind(499, [], 60_000), null);
assert.equal(performanceWarningKind(500, [], 60_000), "ui_stall");
assert.equal(performanceWarningKind(100, [10_000, 20_000, 30_000], 60_000), "repeated_ui_stalls");
assert.equal(performanceWarningKind(100, [0, 10_000], 60_000), null);
assert.match(panel, /new PerformanceObserver/);
assert.match(panel, /_performanceWatchdog\?\.observer\?\.disconnect\(\)/);
assert.match(panel, /type: "elrakning\/meter_diagnostic", component: "performance"/);
assert.match(panel, /now - last < 180_000/);
assert.match(panel, /_recordSlowRender\("price-chart"/);
assert.match(websocket, /vol\.In\(\{"meter", "price", "performance"\}\)/);
assert.doesNotMatch(panel, /setInterval\(/);

console.log("performance watchdog lifecycle/threshold tests passed");
