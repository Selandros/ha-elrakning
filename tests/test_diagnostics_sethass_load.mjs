import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const bind = source.slice(source.indexOf("  _bindDiagnostics("), source.indexOf("  _updateInvoiceCard("));
const setHass = source.slice(source.indexOf("  setHass(hass)"), source.indexOf("  destroy()"));
const destroy = source.slice(source.indexOf("  destroy()"), source.indexOf("  async _refreshBackendState"));

assert.match(bind, /_bindDiagnostics\(loadInitial = false\)/);
assert.match(bind, /const requestGeneration = \+\+this\._diagnosticsRequestGeneration/);
assert.match(bind, /const lifecycleGeneration = this\._diagnosticsLifecycleGeneration/);
assert.match(bind, /const requestHass = this\.hass/);
assert.match(bind, /requestHass\.callWS\(\{ type: "elrakning\/diagnostics_state" \}\)/);
assert.match(bind, /if \(!isCurrentRequest\(\)\) return;\s*render\(response\.logs\)/);
assert.match(bind, /if \(isCurrentRequest\(\)\) status\.textContent = "Varning"/);
assert.match(bind, /if \(loadInitial\) load\(\)/);
assert.doesNotMatch(bind, /\n\s*load\(\);\s*\n\s*}/);

assert.match(setHass, /const connectionChanged = Boolean\(hass\?\.connection && this\._eventConnection !== hass\.connection\)/);
assert.match(setHass, /this\._diagnosticsLifecycleGeneration \+= 1/);
assert.match(setHass, /this\._diagnosticsRequestGeneration \+= 1/);
assert.match(setHass, /this\._bindDiagnostics\(connectionChanged\)/);
assert.match(setHass, /subscribeEvents\(\s*\(\) => this\._loadDiagnosticsState\?\.\(\),\s*"elrakning_diagnostics_update"/);

assert.match(destroy, /this\._diagnosticsLifecycleGeneration \+= 1/);
assert.match(destroy, /this\._diagnosticsRequestGeneration \+= 1/);
assert.match(destroy, /this\._diagnosticsBound = false/);
assert.match(destroy, /this\._diagnosticsDomNodes = null/);

console.log("diagnostics setHass load regression: ok");
