import assert from "node:assert/strict";
import fs from "node:fs";

const panel = fs.readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const websocket = fs.readFileSync(new URL("../custom_components/elrakning/websocket.py", import.meta.url), "utf8");

assert.match(panel, /data-solar-evidence-card/);
assert.match(panel, /solar_evidence: response\?\.solar_evidence/);
assert.match(panel, /Open-Meteo complete/);
assert.match(websocket, /SOLAR_EVIDENCE_STATE_COMMAND/);
assert.match(websocket, /websocket_solar_evidence_state/);
assert.match(panel, /solar_evidence_state/);
console.log("solar evidence frontend endpoint/render regression passed");
