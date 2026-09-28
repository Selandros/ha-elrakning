import assert from "node:assert/strict";
import fs from "node:fs";
import { applySolarEvidenceVisibility, formatSolarEvidenceCaptureTasks, solarEvidenceCardHidden, solarEvidenceStatus, summarizeSolarEvidenceHistory } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const panel = fs.readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const websocket = fs.readFileSync(new URL("../custom_components/elrakning/websocket.py", import.meta.url), "utf8");

assert.match(panel, /data-solar-evidence-card/);
assert.match(panel, /data-benchmark-evidence-card/);
assert.ok(panel.indexOf('data-diagnostics-card') < panel.indexOf('data-solar-evidence-card'));
assert.ok(panel.indexOf('data-solar-evidence-card') < panel.indexOf('data-benchmark-evidence-card'));
assert.match(panel, /replay_benchmark_evidence/);
assert.match(panel, /\["Site", evidence\.site_id/);
assert.match(panel, /\["Frame known", evidence\.frame_known_at/);
assert.match(panel, /\["Economics from", evidence\.economics_applicability/);
assert.match(panel, /\["Last attempt", evidence\.last_attempt/);
assert.match(panel, /applySolarEvidenceVisibility\(benchmarkEvidenceCard, this\._debugEnabled, this\._benchmarkEvidence\?\.available\)/);
assert.match(websocket, /REPLAY_BENCHMARK_EVIDENCE_COMMAND/);
assert.match(websocket, /websocket_replay_benchmark_evidence/);
assert.doesNotMatch(panel, /data-solar-evidence-debug/);
assert.match(panel, /solar_evidence: powerHistory\.solar_evidence/);
assert.match(panel, /solar_evidence: this\._powerHistory\?\.solar_evidence \|\| \{ available: false, days: \[\] \}/);
assert.match(panel, /Open-Meteo/);
assert.match(panel, /applySolarEvidenceVisibility\(solarEvidenceCard, this\._debugEnabled, this\._powerHistory\?\.solar_evidence\?\.available\)/);
assert.match(websocket, /SOLAR_EVIDENCE_STATE_COMMAND/);
assert.match(websocket, /websocket_solar_evidence_state/);
assert.match(panel, /solar_evidence_state/);
assert.match(websocket, /enrichment\["solar_pvgis"\]/);
assert.match(panel, /solar_pvgis: response\?\.solar_pvgis/);
assert.match(panel, /solar_open_meteo: response\?\.solar_open_meteo/);
assert.match(panel, /export function solarEvidenceStatus\(evidenceDays, date, today = localDateKey\(new Date\(\)\)\)/);
assert.match(panel, /evidenceDay\.audit_complete === true\) return "✅"/);
assert.match(panel, /return date === today \? "–" : "❌"/);
assert.match(panel, /solarEvidenceStatus\(evidenceDays, day\.date, today\)/);
assert.match(panel, /solar_evidence: this\._powerHistory\?\.solar_evidence/);
assert.match(panel, /solar-evidence-list \{[^}]*max-height: 58vh;[^}]*overflow-x: hidden;[^}]*overflow-y: auto;/);
assert.match(panel, /data-card-source="solar-evidence"[^>]*>Visa data<\/button>/);
assert.match(panel, /data-card-source="benchmark-evidence"[^>]*>Visa data<\/button>/);
assert.match(panel, /cardSource === "solar-evidence"/);
assert.match(panel, /cardSource === "benchmark-evidence"/);
assert.match(panel, /powerHistory\.solar_evidence \|\| \{ available: false, days: \[\] \}/);
assert.match(panel, /this\._benchmarkEvidence \|\| \{ available: false \}/);
assert.match(panel, /data-card-source="solar-evidence"/);
assert.match(panel, /data-card-source="benchmark-evidence"/);
assert.match(panel, /\.card\.solar-evidence-card \{[^}]*background: var\(--ha-card-background, var\(--card-background-color\)\);[^}]*box-shadow: none;[^}]*backdrop-filter: none;/);
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
assert.equal(solarEvidenceCardHidden(false, true), true);
assert.equal(solarEvidenceCardHidden(true, true), false);
const solarEvidenceAfterRender = () => ({ hidden: false, style: { display: "block" } });
const debugOff = solarEvidenceAfterRender();
applySolarEvidenceVisibility(debugOff, false, true);
assert.equal(debugOff.hidden, true);
assert.equal(debugOff.style.display, "none");
const debugOn = solarEvidenceAfterRender();
applySolarEvidenceVisibility(debugOn, true, true);
assert.equal(debugOn.hidden, false);
assert.equal(debugOn.style.display, "");
const rerenderedWhileOff = solarEvidenceAfterRender();
applySolarEvidenceVisibility(rerenderedWhileOff, false, true);
assert.equal(rerenderedWhileOff.hidden, true);
assert.equal(rerenderedWhileOff.style.display, "none");
const unavailable = solarEvidenceAfterRender();
applySolarEvidenceVisibility(unavailable, true, false);
assert.equal(unavailable.hidden, true);
assert.match(panel, /Forecast\.Solar common/);
assert.match(panel, /Open-Meteo · historisk jämförelse/);
assert.match(panel, /Forecast\.Solar common · historisk jämförelse/);
assert.match(panel, /Lagrad historik för vald site/);
assert.match(panel, /summarizeSolarEvidenceHistory\(days\)/);
assert.match(panel, /HISTORIK · LEGACY \/ EJ OMVÄRDERAD/);
assert.match(panel, /data-solar-evidence-capture-tasks/);
assert.match(panel, /formatSolarEvidenceCaptureTasks\(evidence\?\.capture_tasks\)/);
assert.match(panel, /outcome \|\| "outcome saknas"/);
assert.match(panel, /target_site_ids/);
assert.match(panel, /applySolarEvidenceVisibility\(card, this\._debugEnabled, evidence\?\.available, captureTasks\.length > 0\)/);
const taskRows = formatSolarEvidenceCaptureTasks({
  startup: {
    source: "startup",
    scheduled_at: "2026-09-28T17:00:00Z",
    started_at: "2026-09-28T17:00:01Z",
    finished_at: "2026-09-28T17:00:02Z",
    target_date: "2026-09-27",
    target_site_ids: ["site-a"],
    outcome: "success",
  },
});
assert.deepEqual(taskRows[0], {
  source: "startup",
  outcome: "success",
  scheduled_at: "2026-09-28T17:00:00Z",
  started_at: "2026-09-28T17:00:01Z",
  finished_at: "2026-09-28T17:00:02Z",
  target_date: "2026-09-27",
  target_site_ids: ["site-a"],
  error_type: null,
  error: null,
});
assert.deepEqual(formatSolarEvidenceCaptureTasks({}), []);
assert.equal(formatSolarEvidenceCaptureTasks({ startup: { source: "startup" } })[0].outcome, null);
assert.deepEqual(summarizeSolarEvidenceHistory([
  { date: "2026-09-27", audit_complete: true },
  { date: "2026-08-04", audit_complete: false },
  { date: "2026-08-28" },
]), { count: 3, first_date: "2026-08-04", last_date: "2026-09-27" });
assert.deepEqual(summarizeSolarEvidenceHistory(Array.from({ length: 55 }, (_, index) => ({
  date: index < 30 ? `2026-08-${String(index + 1).padStart(2, "0")}` : `2026-09-${String(index - 29).padStart(2, "0")}`,
}))), { count: 55, first_date: "2026-08-01", last_date: "2026-09-25" });
console.log("solar evidence frontend endpoint/render regression passed");
