if (!window.__elrakningEonHandoffBridge) {
  window.__elrakningEonHandoffBridge = true;
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== location.origin) return;
    if (event.data?.type !== "elrakning-eon-handoff-state" || typeof event.data.state !== "string") return;
    void chrome.runtime.sendMessage({type: "ha-handoff-state", state: event.data.state});
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type !== "eon-handoff-status" || typeof message.status !== "string") return;
    window.postMessage({type: "elrakning-eon-handoff-status", status: message.status}, location.origin);
  });
}
