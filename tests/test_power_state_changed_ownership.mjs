import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const subscription = source.slice(source.indexOf('subscribeEvents(\n        (event) => {'), source.indexOf('"state_changed",') + '"state_changed",'.length);
const power = readFileSync(new URL("../custom_components/elrakning/power.py", import.meta.url), "utf8");

assert.match(subscription, /powerEntities = \[/);
for (const field of ["solar_entities", "consumption_entity", "charging_entity", "discharging_entity", "battery_power_entity", "soc_entity", "capacity_entity"]) {
  assert.match(subscription, new RegExp(field));
}
assert.match(subscription, /if \(\[mapping\.power_entity, mapping\.energy_import_entity, mapping\.energy_export_entity, \.\.\.phaseEntities\]\.includes\(entityId\)\) \{[\s\S]*loadMeterState\(\)/);
assert.doesNotMatch(subscription, /loadPowerState\(\)/);

assert.match(power, /self\._state_unsub = hass\.bus\.async_listen\(EVENT_STATE_CHANGED, self\._async_state_changed\)/);
assert.match(power, /selected = set\(self\.mapping\.get\("solar_entities", \[\]\)\) \|/);
assert.match(power, /self\.hass\.bus\.async_fire\(\s*POWER_UPDATE_EVENT/);
assert.match(power, /"state": state/);

console.log("power state_changed ownership regression: ok");
