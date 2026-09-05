import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync("custom_components/elrakning/frontend/elrakning-loader.js", "utf8");
const definitions = new Map();
const context = vm.createContext({
  HTMLElement: class {},
  customElements: {
    get: (name) => definitions.get(name),
    define: (name, ctor) => {
      if (definitions.has(name)) throw new Error(`duplicate custom element: ${name}`);
      definitions.set(name, ctor);
    },
  },
  console,
});

new vm.Script(source).runInContext(context);
new vm.Script(source).runInContext(context);

assert.equal(typeof definitions.get("elrakning-panel"), "function");
assert.equal(definitions.size, 1);
console.log("frontend loader reentrant evaluation regression: ok");
