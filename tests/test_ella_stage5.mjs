import assert from "node:assert/strict";
import fs from "node:fs";

const panel = fs.readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const init = fs.readFileSync(new URL("../custom_components/elrakning/__init__.py", import.meta.url), "utf8");

assert.match(panel, /elrakning_load_forecast_update/);
assert.match(panel, /this\.loadPowerHistory\(\)/);
assert.match(panel, /_loadForecastEventUnsubscribePromise/);
assert.match(panel, /const eventSiteId = event\?\.data\?\.site_id/);
assert.match(panel, /eventSiteId !== activeSiteId/);
assert.match(panel, /const planSiteId = this\._pricePlan\?\.site_id/);
assert.match(panel, /Promise\.allSettled\(\[this\.loadPowerHistory\(\), this\.loadPricePlan\(\)\]\)/);
assert.match(panel, /siteContextGeneration !== this\._siteContextGeneration/);
assert.match(panel, /_loadForecast = response\?\.load_forecast/);
assert.match(init, /minute=\[0, 15, 30, 45\], second=30/);
assert.equal((init.match(/minute=\[0, 15, 30, 45\], second=30/g) || []).length, 1);

console.log("ELLA Stage 5 forecast refresh/static guards: PASS");
