import assert from "node:assert/strict";
import fs from "node:fs";

const frontend = fs.readFileSync("custom_components/elrakning/frontend/elrakning-panel.js", "utf8");
const backend = fs.readFileSync("custom_components/elrakning/websocket.py", "utf8");

assert.match(frontend, /this\._siteIdentityPromise = null;/);
assert.match(frontend, /if \(this\._siteIdentityPromise\) return this\._siteIdentityPromise;/);
assert.match(frontend, /if \(this\.hass !== requestHass\) return null;/);
assert.match(frontend, /this\._siteIdentityPromise === request/);

const history = frontend.slice(frontend.indexOf("async loadPowerHistory("), frontend.indexOf("async _loadPowerHistoryCycle("));
assert.ok(history.indexOf("await this._loadSiteIdentity()") < history.indexOf('"history_request_start"'));
assert.match(history, /const siteId =/);
assert.match(history, /if \(!siteId\) return;/);
assert.match(history, /const cycleKey = `\$\{siteId\}:\$\{siteContextGeneration\}:\$\{requestedDate \|\| ""\}`/);
assert.match(history, /site_id: siteId/);
assert.match(history, /_loadPowerHistoryCycle\(\{ requestedDate, cycle, siteId, siteContextGeneration \}\)/);

const historyCycle = frontend.slice(frontend.indexOf("async _loadPowerHistoryCycle("), frontend.indexOf("async loadPowerHistoryEnrichment("));
assert.match(historyCycle, /siteId !== activeSiteId/);
assert.match(historyCycle, /siteContextGeneration !== this\._siteContextGeneration/);
assert.match(historyCycle, /this\._powerHistoryContextKey = `\$\{siteId\}:\$\{siteContextGeneration\}:/);

for (const method of ["loadPricePlan(", "loadSolarEvidence(", "loadSolarForecast(", "loadBillingHistory("]) {
  const start = frontend.indexOf(`async ${method}`);
  assert.ok(start >= 0, `${method} exists`);
  const body = frontend.slice(start, frontend.indexOf("\n  async ", start + 6));
  assert.ok(body.indexOf("await this._loadSiteIdentity()") >= 0, `${method} waits for site identity`);
}

assert.match(frontend, /this\.loadPriceData\(\),\n      this\.loadPricePlan\(\)/);
assert.equal((frontend.match(/this\._powerHistoryRequestToken \+= 1/g) || []).length, 1);
assert.match(backend, /async def websocket_solar_evidence_state[\s\S]*?_site_is_configured\(hass\)/);
assert.match(backend, /async def websocket_solar_forecast_state[\s\S]*?_site_is_configured\(hass\)/);
assert.match(backend, /async def websocket_billing_history[\s\S]*?_site_is_configured\(hass\)/);

console.log("frontend site-scoped startup gating contract: ok");
