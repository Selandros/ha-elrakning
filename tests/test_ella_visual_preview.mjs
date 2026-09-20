import assert from "node:assert/strict";
import fs from "node:fs";
import { reconcileEllaSiteState } from "../custom_components/elrakning/frontend/elrakning-panel.js";

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

const bound = { site_id: "site-a", ella_binding_verified: true };
const unbound = { site_id: "site-b", ella_binding_verified: false };
const initial = { loadForecast: { available: true, frames: [{ frame_id: "a" }] }, ellaSelection: { id: "a" } };
const switchedAway = reconcileEllaSiteState(bound, unbound, initial);
assert.equal(switchedAway.changed, true);
assert.equal(switchedAway.bound, false);
assert.deepEqual(switchedAway.loadForecast, { available: false, reason: "ella_unbound", frames: [] });
assert.equal(switchedAway.ellaSelection, null);

const switchedBack = reconcileEllaSiteState(unbound, bound, switchedAway);
assert.equal(switchedBack.changed, true);
assert.equal(switchedBack.bound, true);
assert.deepEqual(switchedBack.loadForecast, { available: false, reason: "site_changed", frames: [] });
assert.equal(switchedBack.ellaSelection, null);

console.log("ELLA visual preview static checks: PASS");
