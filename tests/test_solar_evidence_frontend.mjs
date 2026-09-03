import assert from "node:assert/strict";
import fs from "node:fs";
import { solarEvidenceStatus } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const panel = fs.readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const websocket = fs.readFileSync(new URL("../custom_components/elrakning/websocket.py", import.meta.url), "utf8");

assert.doesNotMatch(panel, /data-solar-evidence-card/);
assert.match(panel, /data-solar-evidence-debug/);
assert.match(panel, /solar_evidence: powerHistory\.solar_evidence/);
assert.match(panel, /solar_evidence: this\._powerHistory\?\.solar_evidence \|\| \{ available: false, days: \[\] \}/);
assert.match(panel, /Open-Meteo/);
assert.match(websocket, /SOLAR_EVIDENCE_STATE_COMMAND/);
assert.match(websocket, /websocket_solar_evidence_state/);
assert.match(panel, /solar_evidence_state/);
assert.match(panel, /export function solarEvidenceStatus\(evidenceDays, date, today = localDateKey\(new Date\(\)\)\)/);
assert.match(panel, /evidenceDay\.audit_complete === true\) return "✅"/);
assert.match(panel, /return date === today \? "–" : "❌"/);
assert.match(panel, /solarEvidenceStatus\(evidenceDays, day\.date, today\)/);
assert.match(panel, /solar_evidence: this\._powerHistory\?\.solar_evidence/);
assert.match(panel, /card\.hidden = !this\._debugEnabled \|\| !evidence\?\.available/);
assert.match(panel, /solar-evidence-list \{[^}]*max-height: 58vh;[^}]*overflow-x: hidden;[^}]*overflow-y: auto;/);
assert.match(panel, /\.card\.solar-evidence-debug \{[^}]*background: var\(--ha-card-background, var\(--card-background-color\)\);[^}]*box-shadow: none;[^}]*backdrop-filter: none;/);
assert.match(panel, /solar-evidence-day \{[^}]*padding: 6px 8px;/);
assert.match(panel, /solar-evidence-list \{[^}]*gap: 5px;/);
assert.match(panel, /Actual.*omError.*forecastError/);
assert.match(panel, /Number\.isFinite\(Number\(value\)\)/);
const evidenceDays = [
  { date: "2026-08-28", audit_complete: true },
  { date: "2026-08-29", audit_complete: false },
  { date: "2026-09-01", audit_complete: false },
];
assert.equal(solarEvidenceStatus(evidenceDays, "2026-08-28", "2026-09-03"), "✅");
assert.equal(solarEvidenceStatus(evidenceDays, "2026-08-29", "2026-09-03"), "❌");
assert.equal(solarEvidenceStatus(evidenceDays, "2026-09-01", "2026-09-01"), "–");
assert.equal(solarEvidenceStatus([], "2026-08-30", "2026-09-03"), "–");
assert.equal(solarEvidenceStatus([{ date: "2026-08-30", audit_complete: true }], "2026-08-29", "2026-09-03"), "–");
console.log("solar evidence frontend endpoint/render regression passed");
