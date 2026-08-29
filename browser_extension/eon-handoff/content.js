const ALLOWED_COOKIES = new Set([
  "MyEonAccessScopes",
  "MyEonAccessToken",
  "MyEonAccessToken-ValidUntil",
  "MyEonIDToken",
  "MyEonSession",
]);

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

async function sendAuthenticatedSession() {
  if (location.origin !== "https://www.eon.se") return;
  const cookies = readAllowedCookies();
  if (!cookies.MyEonIDToken || !cookies.MyEonSession) return;
  try {
    const response = await fetch(
      "/bin/eon-se/codeflow/session?pagePath=/content/eon-se/sv_SE/mitt-e-on",
      {credentials: "include", cache: "no-store", headers: {"X-Requested-With": "XMLHttpRequest"}},
    );
    if (!response.ok) return;
    const session = await response.json();
    if (!session?.currentToken) return;
    await chrome.runtime.sendMessage({type: "eon-session-ready", cookies});
  } catch {
    // The content script remains passive when the E.ON session is unavailable.
  }
}

void sendAuthenticatedSession();
