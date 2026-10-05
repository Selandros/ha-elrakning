import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const moduleSource = source.replace("class ElrakningPanel {", "export class ElrakningPanel {");
const module = await import(`data:text/javascript,${encodeURIComponent(moduleSource)}`);

const connection = {};
const host = { querySelector: () => null };
const panel = Object.create(module.ElrakningPanel.prototype);
panel.host = host;
panel._siteState = { site_id: "site-a" };
panel._siteContextGeneration = 1;
panel._canonicalEnergyHistoryRequestToken = 0;
panel._canonicalEnergyHistoryContextKey = null;
panel._canonicalEnergyHistory = null;
panel._canonicalEnergyHistoryInFlight = new Map();
panel._canonicalEnergyHistoryCache = new Map();
panel._canonicalEnergyHistoryRenderFrame = 0;
panel._canonicalEnergyHistoryRenderContextKey = null;
panel._periodPickerState = { confirmed: new Date(2024, 0, 3) };
panel.priceData = { date: "2024-01-03" };
panel.priceSnapshot = {};
panel._loadSiteIdentity = async () => panel._siteState;
panel._recordPowerFlowDiagnostic = () => {};

let requestCount = 0;
let resolveFirst;
const initialHass = {
  connection,
  callWS: () => {
    requestCount += 1;
    return new Promise((resolve) => { resolveFirst = resolve; });
  },
};
panel.hass = initialHass;

const first = panel.loadCanonicalEnergyHistory(new Date(2024, 0, 3));
const second = panel.loadCanonicalEnergyHistory(new Date(2024, 0, 3));
await new Promise((resolve) => setImmediate(resolve));
assert.equal(requestCount, 1, "same site/date consumers share one in-flight backend request");

panel.hass = { ...initialHass, connection };
resolveFirst({
  success: true,
  site_id: "site-a",
  date: "2024-01-03",
  energy_history: { series: { import: [{ start: "2024-01-03T00:00:00Z", end: "2024-01-03T00:15:00Z", value_kw: 0.5 }] } },
});
assert.ok(await first, "same connection with a new hass state object accepts canonical history");
assert.ok(await second, "the second consumer receives the shared canonical result");

await panel.loadCanonicalEnergyHistory(new Date(2024, 0, 3));
assert.equal(requestCount, 1, "a completed historical result is reused without another backend request");

let resolveLate;
panel._canonicalEnergyHistoryCache.clear();
panel._canonicalEnergyHistoryInFlight.clear();
panel.hass = {
  connection,
  callWS: () => new Promise((resolve) => { resolveLate = resolve; }),
};
panel._periodPickerState.confirmed = new Date(2024, 0, 3);
const late = panel.loadCanonicalEnergyHistory(new Date(2024, 0, 3));
await new Promise((resolve) => setImmediate(resolve));
panel._periodPickerState.confirmed = new Date(2024, 0, 4);
resolveLate({
  success: true,
  site_id: "site-a",
  date: "2024-01-03",
  energy_history: { series: { import: [] } },
});
assert.equal(await late, null, "a response for an old selected date remains rejected");

const visitCounts = new Map();
panel._canonicalEnergyHistoryCache.clear();
panel._canonicalEnergyHistoryInFlight.clear();
panel.hass = {
  connection,
  callWS: ({ date }) => {
    visitCounts.set(date, (visitCounts.get(date) || 0) + 1);
    return Promise.resolve({
      success: true,
      site_id: "site-a",
      date,
      energy_history: { series: { import: [{ start: `${date}T00:00:00Z`, end: `${date}T00:15:00Z`, value_kw: 0.5 }] } },
    });
  },
};
for (const date of ["2024-01-03", "2024-01-04", "2024-01-03", "2024-01-02", "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]) {
  panel._periodPickerState.confirmed = new Date(`${date}T12:00:00`);
  panel.priceData = { date };
  assert.ok(await panel.loadCanonicalEnergyHistory(panel._periodPickerState.confirmed), `canonical data is deterministic for ${date}`);
}
assert.deepEqual(Object.fromEntries(visitCounts), {
  "2024-01-01": 1,
  "2024-01-02": 1,
  "2024-01-03": 1,
  "2024-01-04": 1,
}, "revisiting historical dates uses the bounded site/date cache");

console.log("canonical energy history context and dedupe regression passed");
