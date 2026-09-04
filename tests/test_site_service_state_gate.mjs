import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync("custom_components/elrakning/websocket.py", "utf8");
assert.match(source, /def _site_binding_is_configured\(hass: HomeAssistant, service: str\)/);

const provider = source.slice(source.indexOf("async def websocket_electricity_provider_state"), source.indexOf("async def websocket_electricity_provider_remove"));
assert.match(provider, /if not _site_binding_is_configured\(hass, "elhandel"\)/);
assert.doesNotMatch(provider, /if not _site_is_configured\(hass\)/);

const grid = source.slice(source.indexOf("async def websocket_grid_state"), source.indexOf("async def websocket_grid_login"));
assert.match(grid, /if not _site_binding_is_configured\(hass, "grid"\)/);
assert.doesNotMatch(grid, /if not _site_is_configured\(hass\)/);

const eon = source.slice(source.indexOf("async def websocket_eon_grid_state"), source.indexOf("async def websocket_eon_grid_save"));
assert.match(eon, /if not _site_binding_is_configured\(hass, "grid"\)/);
assert.doesNotMatch(eon, /if not _site_is_configured\(hass\)/);

console.log("site service state gate regression passed");
