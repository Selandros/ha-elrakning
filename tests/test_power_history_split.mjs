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
assert.match(backend, /load_forecast_inflight/);
assert.match(backend, /_async_load_forecast_state_uncached/);
assert.match(backend, /_skip_load_forecast/);
assert.match(backend, /not_required_for_empty_load_plan/);
assert.match(backend, /_minimal_action_plan/);

const historyLoader = frontend.slice(
  frontend.indexOf("  async loadPowerHistory(selectedDate = null)"),
  frontend.indexOf("  _ellaSelectionBandMarkup"),
);
assert.match(historyLoader, /type: "elrakning\/power_history"/);
assert.match(historyLoader, /this\._refreshPowerEnergyState\(\)/);
assert.match(historyLoader, /cycle\.enrichment = this\.loadPowerHistoryEnrichment\(/);
assert.ok(
  historyLoader.indexOf("this._refreshPowerEnergyState()")
    < historyLoader.indexOf("cycle.enrichment = this.loadPowerHistoryEnrichment("),
  "history must render before enrichment is awaited",
);
assert.match(historyLoader, /type: "elrakning\/power_history_enrichment"/);
assert.match(historyLoader, /this\._powerHistory = \{\s*\.\.\.this\._powerHistory/);
assert.match(historyLoader, /requestToken !== this\._powerHistoryRequestToken/);
assert.match(historyLoader, /enrichmentToken !== this\._powerHistoryEnrichmentRequestToken/);
assert.match(historyLoader, /contextKey !== this\._powerHistoryContextKey/);
assert.match(historyLoader, /const cycleKey = `\$\{this\._siteContextGeneration\}:\$\{requestedDate \|\| ""\}`/);
assert.match(historyLoader, /const existing = this\._powerHistoryInFlight\.get\(cycleKey\)/);
assert.match(historyLoader, /if \(existing\) return existing\.history/);
assert.match(frontend, /this\.loadPowerHistory\(next\)/);
assert.match(backend, /power_forecast_inflight/);
assert.match(backend, /async def _build_power_forecast_state\(/);
assert.doesNotMatch(backend, /cache\.clear\(\)\s*\n\s*cache\[cache_key\]/);

console.log("power history split and non-blocking enrichment contract: ok");
