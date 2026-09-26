import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync("custom_components/elrakning/websocket.py", "utf8");

assert.match(source, /POWER_HISTORY_ENRICHMENT_COMMAND = f"\{DOMAIN\}\/power_history_enrichment"/);
assert.match(source, /connection\.send_result\(msg\["id"\], result\)\s*\n\s*\n\s*\n@websocket_api\.websocket_command/);
assert.match(source, /enrichment\["load_forecast"\] = await _async_load_forecast_state\(hass, request_id=request_id\)/);
assert.match(source, /_async_power_forecast_state\(\s*hass, requested_date, load_forecast=enrichment\["load_forecast"\]/);
assert.match(source, /if load_forecast is None:\s*load_forecast = await _async_load_forecast_state\(hass, site_id\)/);

console.log("power history request-scoped forecast reuse regression: ok");
