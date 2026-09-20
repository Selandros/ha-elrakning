import assert from "node:assert/strict";
import fs from "node:fs";

const panel = fs.readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");

assert.match(panel, /ELLA · Energiplan/);
assert.match(panel, /ella_binding_verified/);
assert.match(panel, /const ellaBound = this\._siteState\?\.ella_binding_verified === true/);
assert.match(panel, /Lärläge · Shadow · styrning avstängd/);
assert.match(panel, /load_forecast/);
assert.match(panel, /chart-power-forecast-load/);
assert.match(panel, /stroke-dasharray: 8 5/);
assert.match(panel, /Batteriplan väntar på ESS-modell/);
assert.match(panel, /data-ella-card/);
assert.match(panel, /ella-selection-band/);
assert.match(panel, /this\._renderSocChart\(\)/);
assert.doesNotMatch(panel, /if\s*\(.*(?:growatt|huawei|solis)/i);

console.log("ELLA visual preview static checks: PASS");
