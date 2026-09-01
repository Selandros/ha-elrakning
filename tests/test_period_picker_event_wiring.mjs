import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../custom_components/elrakning/frontend/elrakning-panel.js", import.meta.url), "utf8");
const moduleSource = source.replace("class ElrakningPanel {", "export class ElrakningPanel {");
const module = await import(`data:text/javascript,${encodeURIComponent(moduleSource)}`);
globalThis.window = { addEventListener() {} };

class FakeElement {
  constructor() {
    this.listeners = new Map();
    this.attributes = new Map();
    this.dataset = {};
    this.classList = { toggle() {} };
    this.hidden = false;
    this.open = false;
    this.textContent = "";
  }

  addEventListener(type, callback) {
    this.listeners.set(type, callback);
  }

  dispatch(type) {
    return this.listeners.get(type)?.({
      target: this,
      stopPropagation() {},
      preventDefault() {},
    });
  }

  querySelector(selector) {
    return this.children?.get(selector) || null;
  }

  querySelectorAll(selector) {
    return this.groups?.get(selector) || [];
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  close() {
    this.open = false;
  }

  showModal() {
    this.open = true;
  }
}

const root = new FakeElement();
const dialog = new FakeElement();
const label = new FakeElement();
const popover = new FakeElement();
const previous = new FakeElement();
previous.dataset.periodPickerNav = "previous";
root.children = new Map([
  ["[data-period-picker-dialog]", dialog],
  ["[data-period-picker-label]", label],
  ["[data-period-picker-popover]", popover],
]);
root.groups = new Map([
  ["[data-period-picker-mode]", []],
  ["[data-period-picker-nav]", [previous]],
]);

const host = new FakeElement();
host.querySelector = (selector) => selector === "[data-period-picker]" ? root : null;
const panel = Object.create(module.ElrakningPanel.prototype);
panel.host = host;
panel._periodPickerState = {
  mode: "hour",
  open: false,
  confirmed: new Date(2026, 8, 1),
  draft: new Date(2026, 8, 1),
  cursor: new Date(2026, 8, 1),
};
const loads = [];
panel.loadPriceData = async (date) => {
  loads.push(date);
};

panel._bindPeriodPicker();
assert.equal(label.textContent, "2026-09-01");
assert.equal(root.groups.get("[data-period-picker-nav]")[0], previous);

const loadPromise = previous.dispatch("click");
assert.equal(panel._periodPickerState.confirmed.toISOString(), "2026-08-30T22:00:00.000Z");
assert.equal(panel._periodPickerState.draft.toISOString(), "2026-08-30T22:00:00.000Z");
assert.equal(label.textContent, "2026-08-31");
await loadPromise;
assert.equal(loads.length, 1);
assert.equal(loads[0].toISOString(), "2026-08-30T22:00:00.000Z");

const boundButton = previous;
panel._renderPeriodPicker();
assert.equal(root.groups.get("[data-period-picker-nav]")[0], boundButton);
assert.equal(boundButton.listeners.has("click"), true);

assert.match(source, /root\.querySelectorAll\("\[data-period-picker-nav\]"\)\.forEach\(\(button\) => button\.addEventListener\("click"/);
assert.equal((source.match(/this\.host\.innerHTML\s*=/g) || []).length, 1);
assert.equal((source.match(/data-period-picker-nav="previous"/g) || []).length, 1);

console.log("period picker event wiring regression passed");
