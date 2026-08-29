const ALLOWED_COOKIES = new Set([
  "MyEonAccessScopes",
  "MyEonAccessToken",
  "MyEonAccessToken-ValidUntil",
  "MyEonIDToken",
  "MyEonSession",
]);

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

async function completeHandoff(cookieMap) {
  const origin = await configuredHaOrigin();
  const permission = await chrome.permissions.contains({origins: [`${origin}/*`]});
  if (!permission) return;
  const cookies = Object.fromEntries(
    Object.entries(cookieMap).filter(([name, value]) => ALLOWED_COOKIES.has(name) && typeof value === "string" && value),
  );
  if (!cookies.MyEonIDToken || !cookies.MyEonSession) return;
  const pendingResponse = await fetch(`${origin}/api/elrakning/eon/handoff/pending`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!pendingResponse.ok) return;
  const pending = await pendingResponse.json();
  if (!pending.active || typeof pending.state !== "string") return;
  await fetch(`${origin}/api/elrakning/eon/handoff/complete`, {
    method: "POST",
    credentials: "include",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({state: pending.state, cookies}),
  });
}

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type !== "eon-session-ready" || !message.cookies) return;
  void completeHandoff(message.cookies).catch(() => {});
});
