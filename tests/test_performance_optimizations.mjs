import assert from "node:assert/strict";
import fs from "node:fs";
import { performance } from "node:perf_hooks";
import {
  buildCanonicalMeterPoints,
  buildDailyObservedMaxima,
  decimateDisplayPoints,
  recomputeDailyEnergyState,
} from "../custom_components/elrakning/frontend/elrakning-panel.js";

const source = fs.readFileSync("custom_components/elrakning/frontend/elrakning-panel.js", "utf8");
const backend = fs.readFileSync("custom_components/elrakning/websocket.py", "utf8");

const points = Array.from({ length: 1000 }, (_, index) => ({
  timestamp: index * 900000,
  value_kw: index === 417 ? 99 : index === 731 ? -22 : index / 100,
}));
const before = JSON.stringify(points);
const rendered = decimateDisplayPoints(points, { targetPoints: 64, valueKeys: ["value_kw"] });

assert.ok(rendered.length <= 64, "display output must respect the render budget");
assert.equal(rendered[0], points[0], "first point must be retained");
assert.equal(rendered.at(-1), points.at(-1), "last point must be retained");
assert.ok(rendered.some((point) => point.value_kw === 99), "bucket maximum must be retained");
assert.ok(rendered.some((point) => point.value_kw === -22), "bucket minimum must be retained");
assert.ok(rendered.every((point, index) => index === 0 || point.timestamp >= rendered[index - 1].timestamp), "time order must be retained");
assert.equal(JSON.stringify(points), before, "raw source points must not be mutated");

const referenceNearestMeterPoint = (rows, timestamp, maxDistanceMs = 2.5 * 60 * 1000) => {
  const nearest = rows.reduce((result, point) => {
    const pointTimestamp = new Date(point.timestamp).getTime();
    const distance = Math.abs(pointTimestamp - timestamp);
    if (!Number.isFinite(pointTimestamp) || distance > maxDistanceMs || (!result || distance < result.distance)) {
      return Number.isFinite(pointTimestamp) && distance <= maxDistanceMs
        ? { point, distance }
        : result;
    }
    return result;
  }, null);
  return nearest?.point || null;
};
const referenceCanonicalMeterPoints = (rows, dayStart, dayEnd, slotMs = 5 * 60 * 1000) => {
  const start = new Date(dayStart).getTime();
  const end = new Date(dayEnd).getTime();
  const result = [];
  let previousSelected = false;
  for (let timestamp = start; timestamp < end; timestamp += slotMs) {
    const selected = referenceNearestMeterPoint(rows, timestamp);
    const normalize = (value) => value === null || value === undefined || value === ""
      ? null
      : Number.isFinite(Number(value)) ? Number(value) : null;
    const importKw = selected ? normalize(selected.import_kw) : null;
    const exportKw = selected ? normalize(selected.export_kw) : null;
    const hasSample = Number.isFinite(importKw) || Number.isFinite(exportKw);
    result.push({
      timestamp,
      raw_timestamp: hasSample ? selected.timestamp : null,
      import_kw: hasSample && Number.isFinite(importKw) ? importKw : null,
      export_kw: hasSample && Number.isFinite(exportKw) ? exportKw : null,
      gap_before: hasSample && !previousSelected,
    });
    previousSelected = hasSample;
  }
  return result;
};
const semanticRows = [
  { timestamp: "2026-08-23T04:48:30+02:00", import_kw: 4.82, export_kw: null },
  { timestamp: "2026-08-23T04:52:00+02:00", import_kw: null, export_kw: 0 },
  { timestamp: "2026-08-23T04:53:00+02:00", import_kw: 5, export_kw: null },
].reverse();
const semanticStart = new Date("2026-08-23T04:45:00+02:00");
const semanticEnd = new Date("2026-08-23T05:05:00+02:00");
assert.deepEqual(
  buildCanonicalMeterPoints(semanticRows, semanticStart, semanticEnd),
  referenceCanonicalMeterPoints(semanticRows, semanticStart, semanticEnd),
  "canonical meter optimization must preserve nearest-point, tie, null and zero semantics",
);

const realisticPoints = Array.from({ length: 10000 }, (_, index) => ({
  timestamp: new Date(Date.parse("2026-10-08T00:00:00Z") + index * 5000).toISOString(),
  value_kw: 1 + (index % 37) / 10,
  import_kw: 1 + (index % 29) / 10,
  export_kw: index % 23 === 0 ? 0 : null,
}));
const realisticPowerHistory = {
  series: Object.fromEntries(["solar", "consumption", "charging", "discharging"]
    .map((key) => [key, { points: realisticPoints }])),
};
const realisticMeterHistory = { points: realisticPoints };
const recomputeStart = performance.now();
const recomputed = recomputeDailyEnergyState(
  {},
  realisticPowerHistory,
  realisticMeterHistory,
  new Date("2026-10-08T12:00:00Z"),
);
const recomputeDurationMs = performance.now() - recomputeStart;
assert.ok(recomputeDurationMs < 500, `10k-point energy recomputation took ${recomputeDurationMs.toFixed(1)} ms`);
assert.equal(Number.isFinite(recomputed.consumption_energy_kwh), true);
assert.equal(Number.isFinite(recomputed.meter_import_energy_kwh), true);
const maxima = buildDailyObservedMaxima(
  realisticPowerHistory,
  realisticMeterHistory,
  new Date("2026-10-08T12:00:00Z"),
);
assert.equal(maxima.date, "2026-10-08");
assert.equal(maxima.house, maxima.solar);
assert.equal(maxima.grid, 3.8);

assert.match(source, /decimateDisplayPoints\(rawPoints/);
assert.match(source, /renderBudget = Math\.min\(1024/);
assert.match(source, /_priceChartRenderCacheKey/);
assert.match(source, /cache_hit/);
assert.match(source, /nearestCandidates/);
assert.match(source, /const dayStart = localDayStart\(now\)/);
assert.match(backend, /semantic_fingerprint/);
assert.match(backend, /load_forecast_cache/);
assert.match(backend, /power_forecast_cache/);
assert.match(backend, /str\(load_forecast\.get\("semantic_fingerprint"\)/);
assert.match(backend, /clear_forecast_view_caches/);

console.log("performance decimation and semantic forecast cache contracts: ok");
