import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolveFuseAmpere } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const applyStart = source.indexOf("  _applyEonGridState(state)");
const applyEnd = source.indexOf("  _bindEonGridDialog()", applyStart);
const applySource = source.slice(applyStart, applyEnd);

const resolvedFuseChanged = (meterState, oldGridState, newGridState) => (
  resolveFuseAmpere(meterState, oldGridState) !== resolveFuseAmpere(meterState, newGridState)
);

assert.equal(resolvedFuseChanged(null, { facility: { fuse_ampere: 16 } }, { facility: { fuse_ampere: 20 } }), true);
assert.equal(resolvedFuseChanged(null, { facility: { fuse_ampere: 16 } }, { facility: { fuse_ampere: "16" } }), false);
assert.equal(resolvedFuseChanged({ facility: { fuse_ampere: 16 } }, { facility: { fuse_ampere: 16 } }, { facility: { fuse_ampere: 20 } }), false);
assert.equal(resolvedFuseChanged(null, {}, { facility: { fuse_ampere: 16 } }), true);
assert.equal(resolvedFuseChanged(null, { facility: { fuse_ampere: 16 } }, {}), true);
assert.equal(resolvedFuseChanged(null, { unrelated: "old" }, { unrelated: "new" }), false);

assert.match(applySource, /const previousFuseAmpere = resolveFuseAmpere\(this\._meterState, this\._eonGridState\);/);
assert.match(applySource, /this\._eonGridState = state;/);
assert.match(applySource, /const fuseAmpere = resolveFuseAmpere\(this\._meterState, state\);/);
assert.match(applySource, /if \(fuseChanged\) this\._renderPhaseHistoryCard\(\);/);

console.log("passed E.ON fuse phase-history invalidation test");
