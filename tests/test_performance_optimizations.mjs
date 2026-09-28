import assert from "node:assert/strict";
import fs from "node:fs";
import { decimateDisplayPoints } from "../custom_components/elrakning/frontend/elrakning-panel.js";

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

assert.match(source, /decimateDisplayPoints\(rawPoints/);
assert.match(source, /renderBudget = Math\.min\(1024/);
assert.match(source, /_priceChartRenderCacheKey/);
assert.match(source, /cache_hit/);
assert.match(backend, /semantic_fingerprint/);
assert.match(backend, /load_forecast_cache/);
assert.match(backend, /power_forecast_cache/);
assert.match(backend, /str\(load_forecast\.get\("semantic_fingerprint"\)/);
assert.match(backend, /clear_forecast_view_caches/);

console.log("performance decimation and semantic forecast cache contracts: ok");
