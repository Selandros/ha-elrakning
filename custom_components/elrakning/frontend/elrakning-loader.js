class ElrakningPanel extends HTMLElement {
  set hass(value) {
    this._hass = value;
    if (this._panel) this._panel.setHass(value);
    if (this._cadenceAudit) this._cadenceAudit.setHass(value);
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    this._ensureLatestPanel();
    this._startVersionWatch();
  }

  disconnectedCallback() {
    this._stopVersionWatch();
    this._cadenceAudit?.destroy?.();
    this._cadenceAudit = null;
    this._panel?.destroy?.();
    this._panel = null;
    this._loadedVersion = null;
  }

  async _getInstalledVersion() {
    const response = await fetch(`/elrakning/manifest.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Manifest request failed: ${response.status}`);
    const manifest = await response.json();
    if (!manifest?.version) throw new Error("Missing Elräkning version");
    return manifest.version;
  }

  async _ensureLatestPanel() {
    if (this._updatePromise) return this._updatePromise;
    this._updatePromise = this._checkAndLoad();
    try {
      await this._updatePromise;
    } finally {
      this._updatePromise = null;
    }
  }

  async _checkAndLoad() {
    const version = await this._getInstalledVersion();
    if (version === this._loadedVersion) return;
    this._cadenceAudit?.destroy?.();
    this._cadenceAudit = null;
    this._panel?.destroy?.();
    this._panel = null;
    const [{ mountElrakningPanel }, { mountCadenceAudit }] = await Promise.all([
      import(`/elrakning/elrakning-panel.js?v=${encodeURIComponent(version)}`),
      import(`/elrakning/elrakning-cadence-audit.js?v=${encodeURIComponent(version)}`),
    ]);
    this._panel = mountElrakningPanel(this, { version });
    this._cadenceAudit = mountCadenceAudit(this, { version });
    this._loadedVersion = version;
    if (this._hass) {
      this._panel.setHass(this._hass);
      this._cadenceAudit.setHass(this._hass);
    }
  }

  _startVersionWatch() {
    if (this._versionTimer) return;
    this._onFocus = () => this._ensureLatestPanel();
    this._onVisibilityChange = () => {
      if (document.visibilityState === "visible") this._ensureLatestPanel();
    };
    window.addEventListener("focus", this._onFocus);
    document.addEventListener("visibilitychange", this._onVisibilityChange);
    this._versionTimer = window.setInterval(() => this._ensureLatestPanel(), 60000);
  }

  _stopVersionWatch() {
    if (this._versionTimer) window.clearInterval(this._versionTimer);
    this._versionTimer = null;
    if (this._onFocus) window.removeEventListener("focus", this._onFocus);
    if (this._onVisibilityChange) document.removeEventListener("visibilitychange", this._onVisibilityChange);
    this._onFocus = null;
    this._onVisibilityChange = null;
  }
}

if (!customElements.get("elrakning-panel")) {
  customElements.define("elrakning-panel", ElrakningPanel);
}
