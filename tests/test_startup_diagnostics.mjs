import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");

for (const marker of [
  "panel_mount",
  "ha_connection_ready",
  "integration_ready_event",
  "price_data_request_start",
  "price_data_response",
  "power_history_request_start",
  "power_history_state_applied",
  "meter_power_history_request_start",
  "meter_power_history_state_applied",
  "solar_history_placeholder_render",
  "solar_history_render",
  "battery_history_placeholder_render",
  "battery_history_render",
  "consumption_history_placeholder_render",
  "consumption_history_render",
  "__elrakningStartupDiagnostics",
]) assert.match(source, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));

assert.match(source, /performance\?\.now\?\./);
assert.match(source, /console\?\.info\?\./);
console.log("startup diagnostics instrumentation markers: ok");
