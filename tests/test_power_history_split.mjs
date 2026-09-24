import assert from "node:assert/strict";
import fs from "node:fs";

const backend = fs.readFileSync("custom_components/elrakning/websocket.py", "utf8");
const frontend = fs.readFileSync("custom_components/elrakning/frontend/elrakning-panel.js", "utf8");

const historyHandler = backend.slice(
  backend.indexOf("async def websocket_power_history("),
  backend.indexOf("async def websocket_power_history_enrichment("),
);
assert.match(historyHandler, /manager\.async_history\(msg\.get\("days", 1\)\)/);
assert.doesNotMatch(historyHandler, /_async_load_forecast_state|_async_power_forecast_state|solar_forecast/);
assert.match(backend, /vol\.Required\("type"\): POWER_HISTORY_ENRICHMENT_COMMAND/);
assert.match(backend, /"handler_total_ms"/);
assert.match(backend, /"power_forecast_ms"/);

const historyLoader = frontend.slice(
  frontend.indexOf("  async loadPowerHistory()"),
  frontend.indexOf("  _ellaSelectionBandMarkup"),
);
assert.match(historyLoader, /type: "elrakning\/power_history"/);
assert.match(historyLoader, /this\._refreshPowerEnergyState\(\)/);
assert.match(historyLoader, /void this\.loadPowerHistoryEnrichment\(/);
assert.ok(
  historyLoader.indexOf("this._refreshPowerEnergyState()")
    < historyLoader.indexOf("void this.loadPowerHistoryEnrichment("),
  "history must render before enrichment is awaited",
);
assert.match(historyLoader, /type: "elrakning\/power_history_enrichment"/);
assert.match(historyLoader, /this\._powerHistory = \{\s*\.\.\.this\._powerHistory/);
assert.match(historyLoader, /requestToken !== this\._powerHistoryRequestToken/);
assert.match(historyLoader, /enrichmentToken !== this\._powerHistoryEnrichmentRequestToken/);
assert.match(historyLoader, /contextKey !== this\._powerHistoryContextKey/);
assert.match(historyLoader, /enrichment_request_start/);
assert.match(historyLoader, /enrichment_guard_rejected/);
assert.match(historyLoader, /enrichment_merge_end/);
assert.match(frontend, /ella_plan_request_start/);
assert.match(frontend, /ella_plan_render/);

console.log("power history split and non-blocking enrichment contract: ok");
