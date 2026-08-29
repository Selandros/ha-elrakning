const ALLOWED_COOKIES = new Set([
  "MyEonAccessScopes", "MyEonAccessToken", "MyEonAccessToken-ValidUntil",
  "MyEonIDToken", "MyEonSession",
]);
const MAX_ATTEMPTS = 8;
const RETRY_DELAY_MS = 750;
const WEB_SESSION_PAGE_PATH = "/content/eon-se/sv_SE/mitt-e-on";

function readAllowedCookies() {
  const cookies = {};
  for (const part of document.cookie.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 1) continue;
    const name = part.slice(0, separator).trim();
    if (ALLOWED_COOKIES.has(name)) cookies[name] = part.slice(separator + 1).trim();
  }
  return cookies;
}

function waitForRetry() {
  return new Promise((resolve) => window.setTimeout(resolve, RETRY_DELAY_MS));
}

async function sendStatus(type) {
  try { await chrome.runtime.sendMessage({type}); } catch { /* Keep the page passive if the helper is unavailable. */ }
}

async function sendAuthenticatedSession() {
  if (location.origin !== "https://www.eon.se") return;
  await sendStatus("eon-page-loaded");
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
    const cookies = readAllowedCookies();
    if (cookies.MyEonIDToken && cookies.MyEonSession) {
      try {
        const response = await fetch(
          `/bin/eon-se/codeflow/session?pagePath=${encodeURIComponent(WEB_SESSION_PAGE_PATH)}`,
          {credentials: "include", cache: "no-store", headers: {"X-Requested-With": "XMLHttpRequest"}},
        );
        if (response.ok && (await response.json())?.currentToken) {
          const result = await chrome.runtime.sendMessage({type: "eon-session-ready", cookies});
          if (result?.status === "completed") return;
          if (result?.status && result.status !== "pending_missing") return;
        }
      } catch { /* Retry only within the bounded handoff window. */ }
    }
    if (attempt + 1 < MAX_ATTEMPTS) await waitForRetry();
  }
  await sendStatus("eon-session-missing");
}

void sendAuthenticatedSession();
