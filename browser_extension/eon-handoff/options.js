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
    await chrome.permissions.request({origins: [`${url.origin}/*`]});
    await chrome.storage.local.set({haOrigin: url.origin});
    status.textContent = "Sparat.";
  } catch {
    status.textContent = "Ange en giltig Home Assistant-origin.";
  }
});

void load();
