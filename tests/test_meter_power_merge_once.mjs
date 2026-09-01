import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const method = source.match(/  _appendMeterPowerPoint\(point\) \{([\s\S]*?)\n  \}\n\n  _periodCustomerPrice/);

assert.ok(method, "meter power point handler should exist");
assert.equal((method[1].match(/mergeMeterPowerHistoryPoint\(/g) || []).length, 1);
assert.match(method[1], /_updateLivePhaseMaxima\(point\.phase_current_a/);
assert.match(method[1], /if \(hasPhaseData\) this\._renderLivePowerRow\(\);/);
assert.match(method[1], /if \(meterMerge\.phaseRenderChanged\) this\._renderPhaseHistoryCard\(\);/);

console.log("passed single meter power history merge regression test");
