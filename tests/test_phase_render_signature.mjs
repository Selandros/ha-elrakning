import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildPhaseRenderDomain } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const renderStart = source.indexOf("  _renderPhaseHistoryCard()");
const renderEnd = source.indexOf("  _applyMeterState(state)", renderStart);
const renderSource = source.slice(renderStart, renderEnd);

const canonicalPhasePoints = [
  { timestamp: 0, raw_timestamp: "2026-08-30T00:00:00.000Z", value: 1, gap_before: false },
];
const baselineRawPoints = [{ timestamp: "2026-08-30T00:00:00.000Z", value: 1 }];
const changedRawPoints = [...baselineRawPoints, { timestamp: "2026-08-30T00:02:00.000Z", value: 20 }];
const rawDomain = (points, metric = "current", fuse = null) => buildPhaseRenderDomain(points, metric, fuse);

assert.deepEqual(canonicalPhasePoints, canonicalPhasePoints);
assert.notDeepEqual(rawDomain(baselineRawPoints), rawDomain(changedRawPoints));
assert.deepEqual(rawDomain(baselineRawPoints), rawDomain([{ ...baselineRawPoints[0] }]));
assert.notDeepEqual(canonicalPhasePoints, [{ ...canonicalPhasePoints[0], value: 2 }]);
assert.notDeepEqual(rawDomain(baselineRawPoints, "voltage"), rawDomain(baselineRawPoints, "active_power"));
assert.notDeepEqual(rawDomain(baselineRawPoints, "current", 16), rawDomain(baselineRawPoints, "current", 20));
assert.match(renderSource, /const renderDomain = buildPhaseRenderDomain\(/);
assert.match(renderSource, /renderSignature = JSON\.stringify\(\{[\s\S]*domain: renderDomain/);

console.log("passed phase render signature raw-domain invalidation test");
