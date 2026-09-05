import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync("custom_components/elrakning/websocket.py", "utf8");
const login = source.slice(
  source.indexOf("async def websocket_grid_login"),
  source.indexOf("async def websocket_grid_source_data")
);
const remove = source.slice(
  source.indexOf("async def websocket_grid_remove"),
  source.indexOf("async def websocket_grid_web_handoff_start")
);

assert.match(login, /site_identity_manager/);
assert.match(login, /result\.get\("configured"\)/);
assert.match(login, /async_bind_grid_runtime\(manager\)/);
assert.match(login, /manager\.async_start_refresh\(\)/);
assert.match(login, /provider\.state\.get\("facility"\)/);

assert.match(remove, /async_unbind_grid_runtime\(\)/);
assert.match(remove, /async_apply_site_binding\(None\)/);
assert.match(remove, /if not has_other_binding:/);
assert.match(remove, /await manager\.async_remove\(\)/);
assert.match(remove, /else:/);
assert.match(remove, /EON_GRID_UPDATE_EVENT/);

console.log("grid websocket site-binding regression passed");
