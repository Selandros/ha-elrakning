import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { selectHourlyPricePeriods } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const panelSource = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const websocketSource = readFileSync(new URL("../custom_components/elrakning/websocket.py", import.meta.url), "utf8");
const periods = [
  { start: "2026-08-31T12:00:00+02:00", end: "2026-08-31T13:00:00+02:00", price: 100 },
  { start: "2026-09-01T12:00:00+02:00", end: "2026-09-01T13:00:00+02:00", price: 300 },
];

const august = selectHourlyPricePeriods(periods, new Date(2026, 7, 31));
assert.deepEqual(august.map((period) => period.price), [100]);
assert.ok(august.every((period) => new Date(period.start).getDate() === 31));

const september = selectHourlyPricePeriods(periods, new Date(2026, 8, 1));
assert.deepEqual(september.map((period) => period.price), [300]);
assert.ok(september.every((period) => new Date(period.start).getDate() === 1));
assert.notDeepEqual(august, september);

assert.match(panelSource, /selectHourlyPricePeriods\(this\.priceData\.periods, this\._periodPickerState\.confirmed\)/);
assert.match(panelSource, /request\.date = `\$\{requestedDate\.getFullYear\(\)\}/);
assert.match(panelSource, /const requestedDate = selectedDate instanceof Date \? selectedDate : null;/);
assert.match(panelSource, /const applySelectedHourDate = async \(date\) =>/);
assert.match(panelSource, /await applySelectedHourDate\(date\)/);
assert.match(panelSource, /applySelectedHourDate\(this\._periodPickerState\.draft\)/);
assert.match(websocketSource, /vol\.Optional\("date"\): str/);
assert.match(websocketSource, /target_date = date\.fromisoformat\(requested_date\)/);
assert.match(websocketSource, /current_data = coordinator\.data/);
assert.match(websocketSource, /current_data\.date == target_date/);
assert.match(websocketSource, /await coordinator\.async_get_price_data\(target_date\)/);
assert.match(websocketSource, /else:\n\s+data = coordinator\.data/);

console.log("selected hourly price date regression passed");
