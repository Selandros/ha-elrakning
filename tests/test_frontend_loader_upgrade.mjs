import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const initSource = readFileSync(new URL("../custom_components/elrakning/__init__.py", import.meta.url), "utf8");
const loaderSource = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-loader.js", import.meta.url), "utf8");
const manifest = JSON.parse(readFileSync(new URL("../custom_components/elrakning/manifest.json", import.meta.url), "utf8"));

assert.match(initSource, /PANEL_LOADER_URL\s*=\s*f["']\{PANEL_LOADER_PATH\}\?v=\{PANEL_LOADER_VERSION\}["']/);
assert.match(initSource, /["']js_url["']:\s*PANEL_LOADER_URL/);
assert.doesNotMatch(initSource, /["']js_url["']:\s*PANEL_LOADER_PATH\b/);
assert.match(loaderSource, /manifest\.json\?t=\$\{Date\.now\(\)\}/);
assert.match(loaderSource, /elrakning-panel\.js\?v=\$\{encodeURIComponent\(version\)\}/);
assert.match(loaderSource, /elrakning-cadence-audit\.js\?v=\$\{encodeURIComponent\(version\)\}/);
assert.equal(manifest.version, "0.0.596");

console.log("frontend loader versioned-upgrade regression: ok");
