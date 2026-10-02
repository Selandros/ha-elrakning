import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync("custom_components/elrakning/websocket.py", "utf8");
assert.match(source, /EON_GRID_REFRESH_COMMAND = f"\{DOMAIN\}\/eon_grid_refresh"/);
assert.match(source, /async_register_command\(hass, websocket_eon_grid_refresh\)/);
assert.match(source, /async def websocket_eon_grid_refresh\(hass, connection, msg\):/);
assert.match(source, /if not _execution_admin\(connection\):/);
assert.match(source, /result = await manager\.async_refresh\(\)/);
assert.match(source, /"refreshed_at": datetime\.now\(timezone\.utc\)\.isoformat\(\)/);
const handler = source.slice(source.indexOf("async def websocket_eon_grid_refresh"), source.indexOf("@websocket_api.websocket_command({\n    vol.Required(\"type\"): EON_GRID_SAVE_COMMAND"));
assert.doesNotMatch(handler, /async_save|store\.async_save|config_entries/);

console.log("E.ON refresh websocket contract regression passed");
