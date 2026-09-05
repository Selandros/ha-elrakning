import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const audit = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-cadence-audit.js", import.meta.url), "utf8");
const loader = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-loader.js", import.meta.url), "utf8");
const backend = readFileSync(new URL("../custom_components/elrakning/cadence_audit.py", import.meta.url), "utf8");

for (const command of [
  "elrakning/cadence_audit_state",
  "elrakning/cadence_audit_start",
  "elrakning/cadence_audit_stop",
  "elrakning/cadence_audit_cleanup",
]) {
  assert.match(audit, new RegExp(command.replace("/", "\\/")));
}

assert.match(audit, /Datakällor · 24h cadence-audit/);
assert.match(audit, /data-cadence-signals/);
assert.match(audit, /same_value_report_count/);
assert.match(audit, /observed_event_gap_seconds/);
assert.match(audit, /runtime_gap_seconds/);
assert.match(audit, /stale_after/);
assert.match(audit, /source generation/);
assert.match(audit, /insertBefore\(section, diagnostics\)/);

assert.match(loader, /elrakning-cadence-audit\.js/);
assert.match(loader, /mountCadenceAudit/);
assert.match(loader, /this\._cadenceAudit\.setHass\(this\._hass\)/);
assert.match(loader, /this\._cadenceAudit\?\.destroy\?\.\(\)/);

assert.match(backend, /AUDITED_LOGICAL_ROLES/);
assert.match(backend, /source_generation_id/);
assert.match(backend, /async_track_state_report_event/);
assert.match(backend, /async_track_state_change_event/);
assert.match(backend, /stale_after_seconds.*None/);
assert.doesNotMatch(backend, /sensor\.fsp_ne_/i);
assert.doesNotMatch(backend, /huawei/i);
assert.doesNotMatch(backend, /growatt/i);
assert.doesNotMatch(backend, /homewizard/i);
assert.doesNotMatch(audit, /sensor\.fsp_ne_/i);
assert.doesNotMatch(audit, /huawei/i);
assert.doesNotMatch(audit, /growatt/i);
assert.doesNotMatch(audit, /homewizard/i);

console.log("cadence audit UI/source-agnostic regression: ok");
