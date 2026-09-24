import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync("custom_components/elrakning/websocket.py", "utf8");

assert.match(source, /result\["load_forecast"\] = await _async_load_forecast_state\(hass\)/);
assert.match(source, /_async_power_forecast_state\(\s*hass, requested_date, load_forecast=result\["load_forecast"\]/);
assert.match(source, /if load_forecast is None:\s*load_forecast = await _async_load_forecast_state\(hass, site_id\)/);

console.log("power history request-scoped forecast reuse regression: ok");
