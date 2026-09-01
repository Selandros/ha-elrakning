import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");

assert.match(source, /this\._powerStateRequestGeneration = 0/);
assert.match(source, /this\._powerStateMutationGeneration = 0/);
assert.match(source, /this\._powerStateLifecycleGeneration = 0/);

const requestHelper = source.slice(source.indexOf("  _beginPowerStateRequest()"), source.indexOf("  _calculatePowerEnergy("));
assert.match(requestHelper, /requestGeneration: \+\+this\._powerStateRequestGeneration/);
assert.match(requestHelper, /mutationGeneration: this\._powerStateMutationGeneration/);
assert.match(requestHelper, /lifecycleGeneration: this\._powerStateLifecycleGeneration/);
assert.match(requestHelper, /hass: this\.hass/);
assert.match(requestHelper, /connection: this\.hass\?\.connection/);
assert.match(requestHelper, /request\.requestGeneration === this\._powerStateRequestGeneration/);
assert.match(requestHelper, /request\.mutationGeneration === this\._powerStateMutationGeneration/);
assert.match(requestHelper, /request\.lifecycleGeneration === this\._powerStateLifecycleGeneration/);
assert.match(requestHelper, /_isCurrentPowerStateContext\(request\)/);
assert.doesNotMatch(requestHelper, /request\.hass === this\.hass/);
assert.match(requestHelper, /request\.connection === this\._eventConnection/);
assert.match(requestHelper, /_applyPowerStateResponse\(request, state\)/);

const load = source.slice(source.indexOf("  async loadPowerState("), source.indexOf("  async loadPowerHistory("));
assert.match(load, /const request = this\._beginPowerStateRequest\(\)/);
assert.match(load, /this\._applyPowerStateResponse\(request, state\)/);
assert.ok(load.indexOf("this._applyPowerStateResponse(request, state)") < load.indexOf("this.loadPowerHistory"), "state must be guarded before history hydration continues");

const live = source.slice(source.indexOf("  _appendPowerState("), source.indexOf("  _resetPowerLivePoints("));
assert.match(live, /this\._applyAuthoritativePowerState\(eventData\.state\)/);
assert.doesNotMatch(live, /_applyPowerState\(eventData\.state\)/);

const saveCalls = [...source.matchAll(/this\._applyAuthoritativePowerState\(response\)/g)];
assert.equal(saveCalls.length, 4, "all four existing power_save apply paths must invalidate stale reads");

const houseDialog = source.slice(source.indexOf('const powerResponse = await request.hass.callWS({ type: "elrakning/power_state" })') - 120, source.indexOf('const powerResponse = await request.hass.callWS({ type: "elrakning/power_state" })') + 300);
assert.match(houseDialog, /const request = this\._beginPowerStateRequest\(\)/);
assert.match(houseDialog, /_applyPowerStateResponse\(request, powerResponse\)/);

const powerDialog = source.slice(source.indexOf('const state = await request.hass.callWS({ type: "elrakning/power_state" })') - 120, source.indexOf('const state = await request.hass.callWS({ type: "elrakning/power_state" })') + 1000);
assert.match(powerDialog, /const request = this\._beginPowerStateRequest\(\)/);
assert.match(powerDialog, /_applyPowerStateResponse\(request, state\)/);
assert.match(powerDialog, /const currentState =/);
assert.match(powerDialog, /renderSelectors\(currentState\)/);

const stateChanged = source.slice(source.indexOf('subscribeEvents(\n        (event) => {'), source.indexOf('"state_changed",') + '"state_changed",'.length);
assert.doesNotMatch(stateChanged, /loadPowerState\(\)/);

const connection = source.slice(source.indexOf("  setHass(hass)"), source.indexOf("  destroy()"));
assert.match(connection, /this\._powerStateLifecycleGeneration \+= 1/);
assert.match(connection, /this\._powerStateRequestGeneration \+= 1/);

const destroy = source.slice(source.indexOf("  destroy()"), source.indexOf("  async _refreshBackendState"));
assert.match(destroy, /this\._powerStateLifecycleGeneration \+= 1/);
assert.match(destroy, /this\._powerStateRequestGeneration \+= 1/);
assert.match(destroy, /this\._powerStateMutationGeneration \+= 1/);

console.log("power state stale response guards: ok");
