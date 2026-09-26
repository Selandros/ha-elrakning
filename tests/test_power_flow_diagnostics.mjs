import assert from "node:assert/strict";
import fs from "node:fs";

const frontend = fs.readFileSync("custom_components/elrakning/frontend/elrakning-panel.js", "utf8");
const backend = fs.readFileSync("custom_components/elrakning/websocket.py", "utf8");

for (const event of [
  "date_change", "history_request_start", "history_reused", "history_response_received",
  "history_stale_rejected", "enrichment_request_start", "enrichment_response_received",
  "enrichment_stale_rejected", "enrichment_merge", "history_cycle_failed", "history_cycle_cleanup",
]) assert.match(frontend, new RegExp(`\\"${event}\\"`));
assert.match(frontend, /_recordPowerFlowDiagnostic\(event, details = \{\}\)/);
assert.match(frontend, /relative_ms: roundDiagnosticMs\(performance\.now\(\)\)/);
assert.match(frontend, /site_context_generation: this\._siteContextGeneration/);

for (const event of [
  "history_handler_start", "history_handler_end", "enrichment_handler_start",
  "enrichment_handler_end", "power_forecast_new", "power_forecast_join_existing",
  "power_forecast_task_complete", "load_input_frames_read_complete",
  "power_history_read_complete", "power_input_frames_read_complete",
  "power_forecast_build_complete",
]) assert.match(backend, new RegExp(`\"${event}\"`));
assert.match(backend, /power_flow_diagnostics/);
assert.match(backend, /time\.monotonic\(\)/);
assert.match(backend, /async def _power_flow_diagnostic\(/);
assert.match(backend, /relative_ms/);
assert.doesNotMatch(backend, /payload = \{"mono_ms"/);
assert.match(backend, /frontend_power_flow/);
assert.match(frontend, /this\._recordDiagnostic\("frontend_power_flow"/);
assert.match(frontend, /type: "elrakning\/diagnostics_clear"/);
assert.match(backend, /async def websocket_diagnostics_clear\(/);
assert.match(backend, /async_clear_diagnostics\(\)/);

console.log("power flow day-switch diagnostics contract: ok");
