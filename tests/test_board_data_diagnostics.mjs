import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");

assert.match(source, /data-board-data-toggle/);
assert.match(source, /data-board-data-dialog/);
assert.match(source, /_buildBoardDataSnapshot\(\)/);
assert.match(source, /elrakning\/site_identity/);
assert.match(source, /elrakning\/power_state/);
assert.match(source, /elrakning\/meter_state/);
assert.match(source, /elrakning\/electricity_provider_state/);
assert.match(source, /elrakning\/grid\/state/);
assert.match(source, /site_isolation_check/);
assert.match(source, /current_site_ledger_count/);
assert.match(source, /price_chart_runtime_diagnostics:/);
assert.match(source, /state_source: siteData\.current_site \|\| siteData\.site/);
assert.match(source, /first_x:/);
assert.match(source, /last_x:/);
assert.match(source, /sanitizeDebugData\(/);
assert.match(source, /data-board-data-copy/);
assert.match(source, /data-board-data-close/);
assert.doesNotMatch(source, /access_token|refresh_token|Authorization|client_secret/);
console.log("global board data snapshot regression passed");
