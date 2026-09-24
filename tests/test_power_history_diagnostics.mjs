import assert from "node:assert/strict";
import fs from "node:fs";

const websocket = fs.readFileSync("custom_components/elrakning/websocket.py", "utf8");
const power = fs.readFileSync("custom_components/elrakning/power.py", "utf8");
const panel = fs.readFileSync("custom_components/elrakning/frontend/elrakning-panel.js", "utf8");

assert.match(websocket, /vol\.Optional\("diagnostics", default=False\): bool/);
assert.match(websocket, /power_history_diagnostics/);
assert.match(websocket, /handler_total_ms/);
assert.match(power, /recorder_start/);
assert.match(power, /raw_entity_counts/);
assert.match(power, /inflight_wait/);
assert.match(panel, /diagnostics: true/);
assert.match(panel, /power_history_backend_timing/);

console.log("power history diagnostics source checks passed");
