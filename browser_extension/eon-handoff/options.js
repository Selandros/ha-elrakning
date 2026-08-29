const input = document.querySelector("#ha-origin");
const status = document.querySelector("#status");

async function load() {
  const stored = await chrome.storage.local.get("haOrigin");
  input.value = stored.haOrigin || "";
}

document.querySelector("#save").addEventListener("click", async () => {
  try {
    const url = new URL(input.value);
    if (!/^https?:$/.test(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error();
    const granted = await chrome.permissions.request({origins: [`${url.origin}/*`]});
    if (!granted) throw new Error("ha_permission_denied");
    await chrome.storage.local.set({haOrigin: url.origin});
    await chrome.scripting.unregisterContentScripts({ids: ["ha-bridge"]}).catch(() => {});
    await chrome.scripting.registerContentScripts([{
      id: "ha-bridge",
      matches: [`${url.origin}/*`],
      js: ["ha_bridge.js"],
      runAt: "document_start",
      persistAcrossSessions: true,
    }]);
    const tabs = await chrome.tabs.query({});
    await Promise.all(tabs
      .filter((tab) => tab.id && tab.url && new URL(tab.url).origin === url.origin)
      .map((tab) => chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["ha_bridge.js"]}).catch(() => {})));
    status.textContent = "Sparat.";
  } catch {
    status.textContent = "Ange en giltig Home Assistant-origin.";
  }
});

void load();
