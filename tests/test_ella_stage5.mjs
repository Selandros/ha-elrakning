import assert from "node:assert/strict";
import fs from "node:fs";

const panel = fs.readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");

assert.match(panel, /elrakning_load_forecast_update/);
assert.match(panel, /this\.loadPowerHistory\(\)/);
assert.match(panel, /_loadForecastEventUnsubscribePromise/);
assert.match(panel, /event\.data\.site_id === activeSiteId/);
assert.match(panel, /siteContextGeneration !== this\._siteContextGeneration/);
assert.match(panel, /_loadForecast = response\?\.load_forecast/);

console.log("ELLA Stage 5 forecast refresh/static guards: PASS");
