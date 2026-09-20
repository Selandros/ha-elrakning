import assert from "node:assert/strict";
import fs from "node:fs";
import { centerCurrentPricePlanCard, currentPricePlanBlock, reconcileEllaSiteState, togglePricePlanSelection } from "../custom_components/elrakning/frontend/elrakning-panel.js";

const panel = fs.readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const priceTemplate = panel.slice(panel.indexOf('<div class="price-chart"'), panel.indexOf('<div class="daily-energy-row">'));

assert.match(panel, /type: "elrakning\/ella_plan"/);
assert.match(panel, /data-price-plan-rail/);
const priceSectionStart = panel.indexOf('<section class="price-section"');
const priceSectionEnd = panel.indexOf('</section>', priceSectionStart);
const pricePlanRail = panel.indexOf('<div class="price-plan-rail" data-price-plan-rail');
assert.ok(priceSectionStart >= 0 && priceSectionEnd > priceSectionStart && pricePlanRail > priceSectionEnd);
const priceSectionMarkup = panel.slice(priceSectionStart, priceSectionEnd);
assert.match(priceSectionMarkup, /price-chart-frame[\s\S]*price-controls/);
assert.match(panel, /<\/section>\s*\n\s*<div class="price-plan-rail" data-price-plan-rail/);
assert.doesNotMatch(panel.slice(pricePlanRail), /<div class="price-controls">/);
assert.match(panel, /--dashboard-card-gap: 16px;/);
assert.match(panel, /dashboard-card-stack/);
assert.match(panel, /\.dashboard-card-stack\s*\{[\s\S]*?display: grid;[\s\S]*?gap: 0;[\s\S]*?margin-bottom: 16px;/);
assert.match(panel, /\.header-top\s*\{[\s\S]*?gap: 16px;[\s\S]*?margin-top: 16px;/);
assert.match(panel, /\.dashboard-card-stack:has\(> :not\(\[hidden\]\) ~ :not\(\[hidden\]\)\)\s*\{[\s\S]*?gap: var\(--dashboard-card-gap\);/);
assert.match(panel, /\.dashboard-card-stack\s*> \*\s*\{[\s\S]*?margin-block: 0;/);
const priceSectionRule = panel.match(/\.price-section\s*\{([^}]*)\}/)?.[1] || "";
const pricePlanRailRule = panel.match(/\.price-plan-rail\s*\{([^}]*)\}/)?.[1] || "";
const genericButtonRule = panel.match(/\n\s*button\s*\{([^}]*)\}/)?.[1] || "";
assert.match(pricePlanRailRule, /gap: 0;/);
assert.match(panel, /\.price-plan-rail:has\(> :not\(\[hidden\]\) ~ :not\(\[hidden\]\)\)\s*\{[\s\S]*?gap: var\(--dashboard-card-gap\);/);
assert.match(pricePlanRailRule, /padding: 3px;/);
assert.match(pricePlanRailRule, /padding-inline-start: 2px;/);
assert.doesNotMatch(priceSectionRule, /margin-bottom:/);
assert.doesNotMatch(pricePlanRailRule, /margin(?:-top|-right|-bottom|-left)?:/);
assert.doesNotMatch(genericButtonRule, /margin-top:/);
assert.doesNotMatch(panel, /\.price-plan-rail\s*\{[\s\S]*?border-bottom:/);
assert.match(panel, /\.daily-energy-row\s*\{[\s\S]*?gap: 0;/);
assert.match(panel, /\.daily-energy-row:has\(> :not\(\[hidden\]\) ~ :not\(\[hidden\]\)\)\s*\{[\s\S]*?gap: var\(--dashboard-card-gap\);/);
assert.match(panel, /\.daily-energy-row:not\(:has\(> :not\(\[hidden\]\)\)\)\s*\{[\s\S]*?display: none;/);
assert.match(panel, /\.daily-energy-row\s*\{[\s\S]*?align-items: stretch;/);
assert.match(panel, /\.page\s*\{[\s\S]*?max-width: 960px;[\s\S]*?margin: 0 auto;/);
assert.doesNotMatch(panel, /\.page\s*\{[^}]*padding:/);
assert.doesNotMatch(panel, /\.daily-energy-part-heading,\s*\.daily-energy-part-labels,\s*\.daily-energy-part-values\s*\{[^}]*gap:/);
const batteryHistoryRule = panel.match(/\.battery-history-row\s*\{([^}]*)\}/)?.[1] || "";
const phaseHistoryRule = panel.match(/\.phase-history-row\s*\{([^}]*)\}/)?.[1] || "";
assert.doesNotMatch(batteryHistoryRule, /margin-top:/);
assert.doesNotMatch(phaseHistoryRule, /margin-top:/);
assert.match(panel, /\.grid\s*\{[\s\S]*?align-items: stretch;/);
const dashboardGridRule = panel.match(/\.grid\s*\{([^}]*)\}/)?.[1] || "";
assert.match(dashboardGridRule, /gap: 0;/);
assert.match(panel, /\.grid:has\(> :not\(\[hidden\]\) ~ :not\(\[hidden\]\)\)\s*\{[\s\S]*?gap: var\(--dashboard-card-gap\);/);
assert.match(panel, /centerCurrentPricePlanCard\(rail, blocks\)/);
assert.match(panel, /price-plan-load-missing/);
assert.match(panel, /Faktisk förbrukning/);
assert.match(panel, /Beräknad total/);
assert.match(panel, /Estimerad förbrukning/);
assert.match(panel, /price-plan-card/);
const pricePlanCardRule = panel.match(/\.price-plan-card\s*\{([^}]*)\}/)?.[1] || "";
assert.match(pricePlanCardRule, /background: var\(--ha-card-glass-tint, var\(--ha-card-background, var\(--card-background-color\)\)\);/);
assert.match(pricePlanCardRule, /border: var\(--ha-card-border-width, 1px\) var\(--ha-card-border-style, solid\) var\(--ha-card-border-color, var\(--divider-color\)\);/);
assert.match(panel, /this\.renderPriceChart\(\)/);
assert.match(panel, /this\._renderSocChart\(\)/);
assert.match(panel, /togglePricePlanSelection\(this\._ellaSelection, block/);
assert.match(panel, /_pricePlanRequestToken/);
assert.match(panel, /siteContextGeneration !== this\._siteContextGeneration/);
assert.match(panel, /_clearPricePlanSelection\(\)/);
assert.match(panel, /addEventListener\("pointerdown", clearUnlessCard\)/);
assert.match(panel, /addEventListener\("wheel", clearUnlessCard, \{ passive: true \}\)/);
assert.match(panel, /addEventListener\("touchmove", clearUnlessCard, \{ passive: true \}\)/);
assert.match(panel, /addEventListener\("scroll", clearUnlessCard, true\)/);
assert.match(panel, /button\.addEventListener\("pointerdown", \(event\) => event\.stopPropagation\(\)\)/);
assert.doesNotMatch(panel, /ELLA · Energiplan/);
assert.doesNotMatch(panel, /Lärläge · Shadow · styrning avstängd/);
assert.doesNotMatch(panel, /data-ella-expand/);
assert.doesNotMatch(panel, /data-site-ella-planner-toggle/);
assert.doesNotMatch(panel, /Batteriplan väntar på ESS-modell/);
assert.doesNotMatch(panel, /Solprognos tillgänglig/);
assert.doesNotMatch(priceTemplate, /price-analysis|Dagens prisanalys laddas|Normalt pris nu|Nästa 2 h|Från /);
assert.doesNotMatch(panel, /if\s*\(.*(?:growatt|huawei|solis)/i);

const bound = { site_id: "site-a", ella_binding_verified: true };
const unbound = { site_id: "site-b", ella_binding_verified: false };
const initial = {
  loadForecast: { available: true, frames: [{ frame_id: "a" }] },
  pricePlan: { available: true, site_id: "site-a", plan_blocks: [{ plan_block_id: "a" }] },
  ellaSelection: { id: "a" },
};
const switchedAway = reconcileEllaSiteState(bound, unbound, initial);
assert.equal(switchedAway.changed, true);
assert.equal(switchedAway.bound, false);
assert.deepEqual(switchedAway.loadForecast, { available: false, reason: "ella_unbound", frames: [] });
assert.deepEqual(switchedAway.pricePlan, { available: false, reason: "site_changed", plan_blocks: [] });
assert.equal(switchedAway.ellaSelection, null);

const switchedBack = reconcileEllaSiteState(unbound, bound, switchedAway);
assert.equal(switchedBack.changed, true);
assert.equal(switchedBack.bound, true);
assert.deepEqual(switchedBack.pricePlan, { available: false, reason: "site_changed", plan_blocks: [] });
assert.equal(switchedBack.ellaSelection, null);

const blockA = { plan_block_id: "a", start: "2026-09-20T13:00:00Z", end: "2026-09-20T17:00:00Z" };
const blockB = { plan_block_id: "b", start: "2026-09-20T17:00:00Z", end: "2026-09-20T20:00:00Z" };
const selectedA = togglePricePlanSelection(null, blockA, "price-only-v1");
assert.deepEqual(selectedA, { id: "a", start: blockA.start, end: blockA.end, revision: "price-only-v1" });
assert.deepEqual(togglePricePlanSelection(selectedA, blockB, "price-only-v1"), {
  id: "b", start: blockB.start, end: blockB.end, revision: "price-only-v1",
});
assert.equal(togglePricePlanSelection(selectedA, blockA, "price-only-v1"), null);

const blockNow = { plan_block_id: "now", start: "2026-09-20T11:30:00Z", end: "2026-09-20T13:45:00Z" };
const blockLater = { plan_block_id: "later", start: "2026-09-20T13:45:00Z", end: "2026-09-20T15:00:00Z" };
assert.equal(currentPricePlanBlock([blockNow, blockLater], Date.parse("2026-09-20T12:00:00Z")), blockNow);
const rail = {
  clientWidth: 300,
  scrollWidth: 900,
  scrollLeft: 0,
  querySelectorAll: () => [{ dataset: { planBlockId: "now" }, offsetLeft: 350, offsetWidth: 220 }],
};
assert.equal(centerCurrentPricePlanCard(rail, [blockNow], Date.parse("2026-09-20T12:00:00Z")), true);
assert.equal(rail.scrollLeft, 310);

console.log("ELLA price-plan shell static/site-switch checks: PASS");
