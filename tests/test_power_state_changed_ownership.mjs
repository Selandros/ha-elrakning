import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const subscription = source.slice(source.indexOf('subscribeEvents(\n        (event) => {'), source.indexOf('"state_changed",') + '"state_changed",'.length);
const power = readFileSync(new URL("../custom_components/elrakning/power.py", import.meta.url), "utf8");

assert.match(subscription, /if \(\[mapping\.energy_import_entity, mapping\.energy_export_entity\]\.includes\(entityId\)\) \{[\s\S]*loadMeterState\(\)/);
assert.doesNotMatch(subscription, /phaseEntities/);
for (const forbidden of ["loadPowerState", "loadPowerHistory", "loadPowerStateEnrichment", "loadPowerHistoryEnrichment"]) {
  assert.doesNotMatch(subscription, new RegExp(forbidden));
}
assert.doesNotMatch(subscription, /powerEntities/);
assert.match(subscription, /PowerManager owns live power state through elrakning_power_update/);

assert.match(power, /self\._state_unsub = hass\.bus\.async_listen\(EVENT_STATE_CHANGED, self\._async_state_changed\)/);
assert.match(power, /selected = set\(self\.mapping\.get\("solar_entities", \[\]\)\) \|/);
assert.match(power, /self\.hass\.bus\.async_fire\(\s*POWER_UPDATE_EVENT/);
assert.match(power, /"state": state/);

console.log("power state_changed ownership regression: ok");
