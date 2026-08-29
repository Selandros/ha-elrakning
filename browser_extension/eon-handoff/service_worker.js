const ALLOWED_COOKIES = new Set([
  "MyEonAccessScopes", "MyEonAccessToken", "MyEonAccessToken-ValidUntil",
  "MyEonIDToken", "MyEonSession",
]);
const STATUS_VALUES = new Set([
  "helper_state_received", "handoff_state_stored", "eon_page_loaded",
  "eon_session_ready", "handoff_posting", "completed", "helper_not_configured",
  "helper_unreachable", "pending_missing", "handoff_expired", "eon_session_missing",
  "eon_session_validation_failed", "ha_unreachable", "handoff_rejected",
]);
const BACKEND_STATUS_MAP = new Map([
  ["session_failed", "eon_session_validation_failed"],
  ["reauth_required", "eon_session_validation_failed"],
  ["customer_id_missing", "eon_session_validation_failed"],
]);
const SESSION_KEY = "eonHandoff";
let completionPromise = null;

function normalizeOrigin(value) {
  const url = new URL(value);
  if (!/^https?:$/.test(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error("invalid_ha_origin");
  }
  return url.origin;
}

async function configuredHaOrigin() {
  const stored = await chrome.storage.local.get("haOrigin");
  return normalizeOrigin(stored.haOrigin);
}

async function signalStatus(tabId, status) {
  if (!tabId || !STATUS_VALUES.has(status)) return;
  try {
    await chrome.tabs.sendMessage(tabId, {type: "eon-handoff-status", status});
  } catch {
    // The HA tab may be closed before the bounded status update.
  }
}

async function clearPending() {
  await chrome.storage.session.remove(SESSION_KEY);
}

async function storePending(state, tabId) {
  await chrome.storage.session.set({[SESSION_KEY]: {
    state, tabId, expiresAt: Date.now() + 300000,
  }});
}

async function pendingStatus(status) {
  const pending = await getPending();
  if (pending) await signalStatus(pending.tabId, status);
  return pending;
}

async function getPending() {
  const stored = await chrome.storage.session.get(SESSION_KEY);
  const pending = stored[SESSION_KEY];
  if (!pending || typeof pending.state !== "string" || !pending.tabId) return null;
  if (typeof pending.expiresAt !== "number" || pending.expiresAt <= Date.now()) {
    await clearPending();
    await signalStatus(pending.tabId, "handoff_expired");
    return null;
  }
  return pending;
}

function filteredCookies(cookieMap) {
  return Object.fromEntries(Object.entries(cookieMap || {}).filter(([name, value]) => (
    ALLOWED_COOKIES.has(name) && typeof value === "string" && value
  )));
}

async function completeHandoff(cookieMap) {
  let origin;
  try {
    origin = await configuredHaOrigin();
  } catch {
    return {status: "helper_not_configured"};
  }
  const pending = await getPending();
  if (!pending) return {status: "pending_missing"};
  await signalStatus(pending.tabId, "eon_session_ready");
  await signalStatus(pending.tabId, "handoff_posting");
  const cookies = filteredCookies(cookieMap);
  if (!cookies.MyEonIDToken || !cookies.MyEonSession) {
    await signalStatus(pending.tabId, "eon_session_missing");
    return {status: "eon_session_missing"};
  }
  let response;
  try {
    response = await fetch(`${origin}/api/elrakning/eon/handoff/complete`, {
      method: "POST", credentials: "omit", cache: "no-store",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({state: pending.state, cookies}),
    });
  } catch {
    await clearPending();
    await signalStatus(pending.tabId, "ha_unreachable");
    return {status: "ha_unreachable"};
  }
  let payload = {};
  try { payload = await response.json(); } catch { payload = {}; }
  await clearPending();
  if (response.ok && payload.success === true) {
    await signalStatus(pending.tabId, "completed");
    return {status: "completed"};
  }
  const status = BACKEND_STATUS_MAP.get(payload.error) || (STATUS_VALUES.has(payload.error) ? payload.error : "handoff_rejected");
  await signalStatus(pending.tabId, status);
  return {status};
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "ha-handoff-state") {
    void (async () => {
      const origin = await configuredHaOrigin().catch(() => null);
      const senderUrl = sender.tab?.url;
      if (!origin || !sender.tab?.id || !senderUrl || new URL(senderUrl).origin !== origin) {
        sendResponse({status: "helper_unreachable"});
        return;
      }
      if (typeof message.state !== "string" || message.state.length < 32) {
        sendResponse({status: "handoff_rejected"});
        return;
      }
      await storePending(message.state, sender.tab.id);
      await signalStatus(sender.tab.id, "handoff_state_stored");
      sendResponse({status: "handoff_state_stored"});
    })().catch(() => sendResponse({status: "helper_unreachable"}));
    return true;
  }
  if (message?.type === "eon-session-ready" && message.cookies) {
    const eonOrigin = sender.tab?.url ? new URL(sender.tab.url).origin : null;
    if (eonOrigin !== "https://www.eon.se") return;
    if (!completionPromise) {
      completionPromise = completeHandoff(message.cookies).finally(() => { completionPromise = null; });
    }
    completionPromise.then(sendResponse).catch(() => sendResponse({status: "handoff_rejected"}));
    return true;
  }
  if (["eon-page-loaded", "eon-session-missing"].includes(message?.type)) {
    const eonOrigin = sender.tab?.url ? new URL(sender.tab.url).origin : null;
    if (eonOrigin !== "https://www.eon.se") return;
    void pendingStatus(message.type === "eon-page-loaded" ? "eon_page_loaded" : "eon_session_missing");
  }
});
