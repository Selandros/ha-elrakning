const STATE_COMMAND = "elrakning/cadence_audit_state";
const START_COMMAND = "elrakning/cadence_audit_start";
const STOP_COMMAND = "elrakning/cadence_audit_stop";
const CLEANUP_COMMAND = "elrakning/cadence_audit_cleanup";

const ROLE_LABELS = Object.freeze({
  "house.consumption": "Husets last",
  "solar.production": "Solproduktion",
  "grid.power/import": "Nät",
  "battery.power": "Batterieffekt",
  "battery.soc": "Batteri SOC",
});

function formatDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return "–";
  const whole = Math.round(value);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = whole % 60;
  if (hours) return `${hours} h ${minutes} min`;
  if (minutes) return `${minutes} min ${secs} s`;
  return `${secs} s`;
}

function formatTimestamp(value) {
  if (!value) return "–";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "–";
  return date.toLocaleString("sv-SE");
}

function formatSeconds(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toLocaleString("sv-SE", { maximumFractionDigits: 1 })} s` : "–";
}

function statusLabel(status) {
  return {
    idle: "Ej startad",
    running: "Pågår",
    completed: "Klar",
    completed_with_runtime_gap: "Klar med runtime-gap",
    cancelled: "Avbruten",
    error: "Fel",
  }[status] || status || "Okänd";
}

function downloadJson(filename, value) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

class CadenceAuditPanel {
  constructor(host, version) {
    this.host = host;
    this.version = version;
    this.hass = null;
    this.state = null;
    this.section = null;
    this._refreshTimer = null;
    this._countdownTimer = null;
    this._requestGeneration = 0;
    this._destroyed = false;
  }

  setHass(hass) {
    this.hass = hass;
    this._ensureSection();
    if (!this.state) this._load();
    this._syncTimers();
  }

  destroy() {
    this._destroyed = true;
    this._clearTimers();
    this.section?.remove();
    this.section = null;
  }

  _ensureSection() {
    if (this._destroyed || this.section?.isConnected) return;
    const main = this.host.querySelector("main");
    if (!main) return;
    const section = document.createElement("section");
    section.className = "card cadence-audit-card";
    section.dataset.cadenceAuditCard = "";
    section.innerHTML = `
      <style>
        .cadence-audit-card { display: grid; gap: 14px; }
        .cadence-audit-card .cadence-audit-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
        .cadence-audit-card .cadence-audit-heading h2 { margin: 0; }
        .cadence-audit-card .cadence-audit-status { font-size: .9rem; opacity: .8; }
        .cadence-audit-card .cadence-audit-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px 16px; }
        .cadence-audit-card .cadence-audit-meta div { display: grid; gap: 2px; }
        .cadence-audit-card .cadence-audit-meta span { font-size: .78rem; opacity: .68; }
        .cadence-audit-card .cadence-audit-actions { display: flex; flex-wrap: wrap; gap: 8px; }
        .cadence-audit-card .cadence-audit-table-wrap { overflow-x: auto; }
        .cadence-audit-card table { width: 100%; border-collapse: collapse; font-size: .82rem; }
        .cadence-audit-card th, .cadence-audit-card td { text-align: left; padding: 7px 8px; border-bottom: 1px solid rgba(128,128,128,.2); white-space: nowrap; }
        .cadence-audit-card .cadence-source { display: grid; gap: 2px; min-width: 180px; white-space: normal; }
        .cadence-audit-card .cadence-source small { opacity: .62; overflow-wrap: anywhere; }
        .cadence-audit-card .cadence-audit-note { font-size: .8rem; opacity: .72; }
        .cadence-audit-card .cadence-audit-error { color: var(--error-color, #db4437); }
      </style>
      <div class="cadence-audit-heading">
        <h2>Datakällor · 24h cadence-audit</h2>
        <span class="cadence-audit-status" data-cadence-status>Hämtar…</span>
      </div>
      <div class="cadence-audit-meta">
        <div><span>Start</span><strong data-cadence-start>–</strong></div>
        <div><span>Slut</span><strong data-cadence-end>–</strong></div>
        <div><span>Återstående</span><strong data-cadence-remaining>–</strong></div>
        <div><span>HA-restarts</span><strong data-cadence-restarts>0</strong></div>
      </div>
      <div class="cadence-audit-actions">
        <button type="button" data-cadence-start-button>Starta 24h-audit</button>
        <button type="button" data-cadence-stop-button>Avbryt audit</button>
        <button type="button" data-cadence-export-button>Exportera JSON</button>
        <button type="button" data-cadence-cleanup-button>Rensa audit</button>
      </div>
      <div class="cadence-audit-table-wrap">
        <table>
          <thead>
            <tr>
              <th>Roll / källa</th>
              <th>Reports</th>
              <th>Changed</th>
              <th>Samma värde</th>
              <th>Median</th>
              <th>p95</th>
              <th>p99</th>
              <th>Max gap</th>
              <th>Unavailable</th>
            </tr>
          </thead>
          <tbody data-cadence-signals></tbody>
        </table>
      </div>
      <div class="cadence-audit-note" data-cadence-note>
        Auditen mäter endast den source generation som resolveras vid start. Ingen universell cadence eller stale_after antas.
      </div>
      <div class="cadence-audit-note" data-cadence-message aria-live="polite"></div>
    `;
    const diagnostics = main.querySelector("[data-diagnostics-card]");
    if (diagnostics) main.insertBefore(section, diagnostics);
    else main.append(section);
    this.section = section;
    section.querySelector("[data-cadence-start-button]").addEventListener("click", () => this._command(START_COMMAND));
    section.querySelector("[data-cadence-stop-button]").addEventListener("click", () => this._command(STOP_COMMAND));
    section.querySelector("[data-cadence-cleanup-button]").addEventListener("click", () => this._command(CLEANUP_COMMAND));
    section.querySelector("[data-cadence-export-button]").addEventListener("click", () => this._export());
    this._render();
  }

  async _load() {
    if (!this.hass?.callWS || this._destroyed) return;
    const generation = ++this._requestGeneration;
    try {
      const state = await this.hass.callWS({ type: STATE_COMMAND });
      if (this._destroyed || generation !== this._requestGeneration) return;
      this.state = state;
      this._render();
      this._syncTimers();
    } catch (error) {
      if (this._destroyed || generation !== this._requestGeneration) return;
      this._message("Audit-state kunde inte hämtas.", true);
    }
  }

  async _command(type) {
    if (!this.hass?.callWS || this._destroyed) return;
    this._message("Arbetar…", false);
    try {
      const state = await this.hass.callWS({ type });
      this.state = state;
      this._message("", false);
      this._render();
      this._syncTimers();
    } catch (error) {
      this._message(error?.message || "Kommandot misslyckades.", true);
    }
  }

  async _export() {
    await this._load();
    if (!this.state || this.state.status === "idle") {
      this._message("Det finns ingen audit att exportera.", true);
      return;
    }
    const auditId = this.state.audit_id || "audit";
    downloadJson(`elrakning-cadence-audit-${auditId}.json`, {
      exported_at: new Date().toISOString(),
      elrakning_version: this.version,
      ...this.state,
    });
    this._message("JSON exporterad.", false);
  }

  _syncTimers() {
    if (this._destroyed) return;
    const running = this.state?.status === "running";
    if (running && !this._refreshTimer) {
      this._refreshTimer = window.setInterval(() => this._load(), 10000);
    }
    if (!running && this._refreshTimer) {
      window.clearInterval(this._refreshTimer);
      this._refreshTimer = null;
    }
    if (running && !this._countdownTimer) {
      this._countdownTimer = window.setInterval(() => this._renderCountdown(), 1000);
    }
    if (!running && this._countdownTimer) {
      window.clearInterval(this._countdownTimer);
      this._countdownTimer = null;
    }
  }

  _clearTimers() {
    if (this._refreshTimer) window.clearInterval(this._refreshTimer);
    if (this._countdownTimer) window.clearInterval(this._countdownTimer);
    this._refreshTimer = null;
    this._countdownTimer = null;
  }

  _renderCountdown() {
    const output = this.section?.querySelector("[data-cadence-remaining]");
    if (!output) return;
    if (this.state?.status !== "running" || !this.state.planned_end_at) {
      output.textContent = "–";
      return;
    }
    const remaining = Math.max(0, (new Date(this.state.planned_end_at).getTime() - Date.now()) / 1000);
    output.textContent = formatDuration(remaining);
  }

  _render() {
    if (!this.section) return;
    const state = this.state || { status: "idle", signals: [] };
    this.section.querySelector("[data-cadence-status]").textContent = statusLabel(state.status);
    this.section.querySelector("[data-cadence-start]").textContent = formatTimestamp(state.started_at);
    this.section.querySelector("[data-cadence-end]").textContent = formatTimestamp(state.completed_at || state.planned_end_at);
    this.section.querySelector("[data-cadence-restarts]").textContent = String(state.restart_count || 0);
    this._renderCountdown();

    const running = state.status === "running";
    this.section.querySelector("[data-cadence-start-button]").disabled = running;
    this.section.querySelector("[data-cadence-stop-button]").disabled = !running;
    this.section.querySelector("[data-cadence-export-button]").disabled = state.status === "idle";
    this.section.querySelector("[data-cadence-cleanup-button]").disabled = running || state.status === "idle";

    const tbody = this.section.querySelector("[data-cadence-signals]");
    tbody.replaceChildren();
    const signals = Array.isArray(state.signals) ? state.signals : [];
    for (const signal of signals) {
      const row = document.createElement("tr");
      const source = document.createElement("td");
      source.className = "cadence-source";
      const role = document.createElement("strong");
      role.textContent = ROLE_LABELS[signal.logical_role] || signal.logical_role || "Okänd roll";
      const entity = document.createElement("small");
      entity.textContent = signal.entity_id || "Ingen entity";
      source.append(role, entity);
      const gap = signal.cadence?.observed_event_gap_seconds || {};
      const cells = [
        signal.report_count ?? 0,
        signal.state_changed_count ?? 0,
        signal.same_value_report_count ?? 0,
        formatSeconds(gap.median),
        formatSeconds(gap.p95),
        formatSeconds(gap.p99),
        formatSeconds(gap.max),
        formatDuration(signal.unavailable?.duration_seconds || 0),
      ];
      row.append(source, ...cells.map((value) => {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        return cell;
      }));
      tbody.append(row);
    }

    const notes = [];
    if (Array.isArray(state.missing_roles) && state.missing_roles.length) {
      notes.push(`Ej konfigurerade roller: ${state.missing_roles.join(", ")}.`);
    }
    if (state.runtime_gap_seconds > 0) {
      notes.push(`Runtime-gap: ${formatDuration(state.runtime_gap_seconds)}.`);
    }
    notes.push("WebSocket-reconnects är ej tillämpliga: collectorn kör lokalt på HA event bus.");
    notes.push("Stale klassas inte av auditen; stale_after är source-generation-specifikt och fastställs först från observation.");
    this.section.querySelector("[data-cadence-note]").textContent = notes.join(" ");
  }

  _message(text, error) {
    const output = this.section?.querySelector("[data-cadence-message]");
    if (!output) return;
    output.textContent = text || "";
    output.classList.toggle("cadence-audit-error", Boolean(error));
  }
}

export function mountCadenceAudit(host, { version }) {
  return new CadenceAuditPanel(host, version);
}
