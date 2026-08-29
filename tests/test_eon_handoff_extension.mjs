import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../browser_extension/eon-handoff/service_worker.js", import.meta.url), "utf8");
const listeners = [];
const sessionStore = {};
const statusMessages = [];
const writes = [];
const requests = [];
const chrome = {
  storage: {
    local: {get: async () => ({haOrigin: "http://ha.test:8123"})},
    session: {
      set: async (value) => { writes.push("set"); Object.assign(sessionStore, value); },
      get: async () => sessionStore,
      remove: async () => { writes.push("remove"); delete sessionStore.eonHandoff; },
    },
  },
  tabs: {sendMessage: async (tabId, message) => { statusMessages.push([tabId, message.status]); }},
  runtime: {onMessage: {addListener: (listener) => listeners.push(listener)}},
};
const context = {chrome, URL, Set, Object, Date, Promise, JSON, Number, String, Array};
vm.runInNewContext(source, context);
assert.equal(listeners.length, 1);
const listener = listeners[0];

function dispatch(message, sender) {
  return new Promise((resolve) => {
    const returned = listener(message, sender, resolve);
    assert.equal(returned, true);
  });
}

const haSender = {tab: {id: 7, url: "http://ha.test:8123/lovelace"}};
const eonSender = {tab: {id: 8, url: "https://www.eon.se/mitt-e-on"}};
const stateAck = await dispatch({type: "ha-handoff-state", state: "synthetic-state-abcdefghijklmnopqrstuvwxyz"}, haSender);
assert.equal(stateAck.status, "handoff_state_stored");
assert.deepEqual(writes, ["set"]);

const originalFetch = context.fetch;
context.fetch = async (url, options) => {
  requests.push({url, options});
  return {ok: true, json: async () => ({success: true})};
};
const cookies = {
  MyEonIDToken: "synthetic-id-token",
  MyEonSession: "synthetic-session",
  MyEonAccessToken: "synthetic-access-token",
  AnalyticsCookie: "must-not-cross",
};
const [first, second] = await Promise.all([
  dispatch({type: "eon-session-ready", cookies}, eonSender),
  dispatch({type: "eon-session-ready", cookies}, eonSender),
]);
assert.equal(first.status, "completed");
assert.equal(second.status, "completed");
assert.equal(requests.length, 1);
assert.equal(requests[0].url, "http://ha.test:8123/api/elrakning/eon/handoff/complete");
assert.equal(requests[0].options.credentials, "omit");
const body = JSON.parse(requests[0].options.body);
assert.equal(body.state, "synthetic-state-abcdefghijklmnopqrstuvwxyz");
assert.deepEqual(body.cookies, {
  MyEonIDToken: "synthetic-id-token",
  MyEonSession: "synthetic-session",
  MyEonAccessToken: "synthetic-access-token",
});
assert.equal(sessionStore.eonHandoff, undefined);
assert.deepEqual(statusMessages, [[7, "handoff_state_stored"], [7, "eon_session_ready"], [7, "handoff_posting"], [7, "completed"]]);
assert.equal(originalFetch, undefined);
console.log("passed extension handoff ack/race/filter test");
