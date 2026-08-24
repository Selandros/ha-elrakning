export function formatDiagnosticsText(entries, version) {
  const lines = ["Elräkning diagnostics", `Version: ${version}`, ""];
  for (const entry of Array.isArray(entries) ? entries : []) {
    const time = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString("sv-SE") : "";
    lines.push(`${time} ${entry.level || "INFO"} ${entry.component || ""} ${entry.event || ""}`);
    lines.push(entry.message || "", "");
  }
  return lines.join("\n").trimEnd();
}

export function diagnosticSymbol(level) {
  return { INFO: "✓", WARNING: "⚠", ERROR: "✕" }[String(level || "INFO").toUpperCase()] || "";
}

export function diagnosticComponent(component) {
  return {
    consumption: "Consumption",
    greenely: "Greenely",
    integration: "Elräkning",
    invoice: "Invoice",
    electricity: "Elhandel",
    provider: "Elhandel",
    source: "Source data",
    meter: "Elmätare",
    price: "Pris",
    websocket: "Websocket",
  }[component] || component || "Elräkning";
}

export function providerLabel(providerName, agreementName) {
  return [providerName, agreementName]
    .filter((value) => typeof value === "string" && value.trim())
    .map((value) => value.trim())
    .join(" · ");
}

export function priceColorBands(prices) {
  const validPrices = prices.filter(Number.isFinite);
  const sorted = validPrices.sort((left, right) => left - right);
  if (!sorted.length || sorted[0] === sorted.at(-1)) return null;
  const cheapCount = Math.max(1, Math.floor(sorted.length * 0.4));
  const expensiveCount = Math.max(1, Math.ceil(sorted.length * 0.2));
  const middle = Math.floor(sorted.length / 2);
  const median = sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
  return {
    cheapThreshold: sorted[cheapCount - 1],
    expensiveThreshold: sorted[sorted.length - expensiveCount],
    minimum: sorted[0],
    maximum: sorted.at(-1),
    median,
    average: validPrices.reduce((sum, price) => sum + price, 0) / validPrices.length,
    sorted,
  };
}

export function priceCategory(price, bands) {
  if (!Number.isFinite(price) || !bands) return "normal";
  if (bands.median > 0 && price > bands.median * 2 && price > bands.average) return "expensive";
  if (price >= bands.expensiveThreshold) return "expensive";
  if (price <= bands.cheapThreshold) return "cheap";
  return "normal";
}

export function priceColorDetails(price, bands, rank, periodCount) {
  const category = priceCategory(price, bands);
  const categoryName = { cheap: "green", normal: "yellow", expensive: "red" }[category];
  if (!bands) {
    return { price, category: categoryName, reason: ["flat_price_profile"] };
  }
  const inTopTwentyPercent = price >= bands.expensiveThreshold;
  const aboveAverage = price > bands.average;
  const aboveMedianThreshold = bands.median > 0 && price > bands.median * 2;
  const reason = category === "cheap"
    ? ["bottom_40_percent"]
    : category === "normal"
      ? ["middle_40_percent"]
      : [
        ...(inTopTwentyPercent ? ["top_20_percent"] : []),
        ...(aboveAverage ? ["above_average"] : []),
        ...(aboveMedianThreshold ? ["above_median_threshold"] : []),
      ];
  const round = (value) => Math.round(value * 10) / 10;
  return {
    price: round(price),
    category: categoryName,
    min: round(bands.minimum),
    max: round(bands.maximum),
    average: round(bands.average),
    median: round(bands.median),
    rank,
    period_count: periodCount,
    percentile: round((rank / periodCount) * 100),
    reason,
  };
}

export function createPriceDebugText(priceData) {
  const lines = [priceData.time, priceData.value];
  if (priceData.details) lines.push("", JSON.stringify(priceData.details, null, 2));
  return lines.join("\n");
}

function formatAnalysisClock(timestamp) {
  return new Date(timestamp).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" });
}

function formatAnalysisPrice(value) {
  return `${Number(value).toLocaleString("sv-SE", { maximumFractionDigits: 1 })} öre/kWh`;
}

function buildUsageWindow(periods, prices, startIndex, windowPeriods) {
  if (startIndex < 0 || startIndex + windowPeriods > periods.length) return null;
  const values = prices.slice(startIndex, startIndex + windowPeriods);
  if (values.some((value) => !Number.isFinite(value))) return null;
  return {
    start: periods[startIndex].start,
    end: periods[startIndex + windowPeriods - 1].end,
    startIndex,
    endIndex: startIndex + windowPeriods - 1,
    average_price: values.reduce((sum, value) => sum + value, 0) / values.length,
  };
}

export function buildPriceAnalysisFacts(periods, currentIndex) {
  if (!Array.isArray(periods) || currentIndex < 0 || currentIndex >= periods.length) {
    return null;
  }
  const prices = periods.map((period) => Number(period.price) * 100);
  const bands = priceColorBands(prices);
  const usageWindowPeriods = 8;
  const searchHorizonPeriods = 24;
  const nowWindow = buildUsageWindow(periods, prices, currentIndex, usageWindowPeriods);
  if (!bands || !nowWindow) return null;
  const categories = prices.map((price) => priceCategory(price, bands));
  const lastStartIndex = Math.min(
    periods.length - usageWindowPeriods,
    currentIndex + searchHorizonPeriods - usageWindowPeriods,
  );
  let bestWindow = nowWindow;
  let highestWindow = nowWindow;
  for (let startIndex = currentIndex + 1; startIndex <= lastStartIndex; startIndex += 1) {
    const window = buildUsageWindow(periods, prices, startIndex, usageWindowPeriods);
    if (!window) continue;
    if (window.average_price < bestWindow.average_price) bestWindow = window;
    if (window.average_price > highestWindow.average_price) highestWindow = window;
  }
  const differenceOre = nowWindow.average_price - bestWindow.average_price;
  const differencePercent = nowWindow.average_price !== 0
    ? (differenceOre / Math.abs(nowWindow.average_price)) * 100
    : 0;
  const higherDifferenceOre = highestWindow.average_price - nowWindow.average_price;
  const higherDifferencePercent = nowWindow.average_price !== 0
    ? (higherDifferenceOre / Math.abs(nowWindow.average_price)) * 100
    : 0;
  return {
    currentIndex,
    status: categories[currentIndex],
    currentPrice: prices[currentIndex],
    dailyAverage: bands.average,
    median: bands.median,
    percentile: (prices.filter((price) => price <= prices[currentIndex]).length / prices.length) * 100,
    minimum: bands.minimum,
    maximum: bands.maximum,
    usage_window_minutes: 120,
    search_horizon_hours: 6,
    now_window: nowWindow,
    best_window: bestWindow,
    highest_window: highestWindow,
    difference_ore_per_kwh: differenceOre,
    difference_percent: differencePercent,
    lower_window_significant: bestWindow.startIndex > nowWindow.startIndex
      && (differenceOre >= 10 || differencePercent >= 15),
    higher_window_significant: highestWindow.startIndex > nowWindow.startIndex
      && (higherDifferenceOre >= 10 || higherDifferencePercent >= 15),
    categories,
  };
}

export function renderPriceAnalysis(facts) {
  if (!facts) return { category: null, status: "", forecast: "Dagens prisanalys är inte tillgänglig" };
  const status = {
    cheap: "Billigt pris nu",
    normal: "Normalt pris nu",
    expensive: "Dyrt pris nu",
  }[facts.status];
  const observations = [
    `Nästa 2 h: ${formatAnalysisPrice(facts.now_window.average_price)} i snitt.`,
  ];
  if (facts.lower_window_significant) {
    observations.push(`Från ${formatAnalysisClock(facts.best_window.start)}: ${formatAnalysisPrice(facts.best_window.average_price)}.`);
  } else if (facts.higher_window_significant) {
    observations.push(`Från ${formatAnalysisClock(facts.highest_window.start)}: ${formatAnalysisPrice(facts.highest_window.average_price)}.`);
  } else {
    observations.push("Ingen tydligt billigare eller dyrare period finns de närmaste 6 timmarna.");
  }
  return { category: facts.status, status, forecast: observations.slice(0, 2).join(" ") };
}

export function generateUpcomingPriceAnalysis(periods, currentIndex) {
  return renderPriceAnalysis(buildPriceAnalysisFacts(periods, currentIndex));
}

export function snapTooltipTimestamp(timestamp, dayStartMs, dayEndMs, slotMs = 5 * 60 * 1000) {
  const latestSlot = dayEndMs - slotMs;
  const snapped = dayStartMs + Math.round((timestamp - dayStartMs) / slotMs) * slotMs;
  return Math.max(dayStartMs, Math.min(latestSlot, snapped));
}

export function nearestMeterPoint(points, timestamp, maxDistanceMs = 2.5 * 60 * 1000) {
  const nearest = (Array.isArray(points) ? points : []).reduce((result, point) => {
    const pointTimestamp = new Date(point.timestamp).getTime();
    const distance = Math.abs(pointTimestamp - timestamp);
    if (!Number.isFinite(pointTimestamp) || distance > maxDistanceMs || (!result || distance < result.distance)) {
      return Number.isFinite(pointTimestamp) && distance <= maxDistanceMs
        ? { point, distance }
        : result;
    }
    return result;
  }, null);
  return nearest?.point || null;
}

export function buildCanonicalMeterPoints(points, dayStart, dayEnd, slotMs = 5 * 60 * 1000, maxDistanceMs = 2.5 * 60 * 1000) {
  const dayStartMs = new Date(dayStart).getTime();
  const dayEndMs = new Date(dayEnd).getTime();
  const canonical = [];
  let previousSelected = false;
  for (let slotTimestamp = dayStartMs; slotTimestamp < dayEndMs; slotTimestamp += slotMs) {
    const selected = nearestMeterPoint(points, slotTimestamp, maxDistanceMs);
    const importKw = selected ? Number(selected.import_kw) : null;
    const exportKw = selected ? Number(selected.export_kw) : null;
    const hasSample = Boolean(selected)
      && Number.isFinite(importKw)
      && Number.isFinite(exportKw);
    canonical.push({
      timestamp: slotTimestamp,
      raw_timestamp: hasSample ? selected.timestamp : null,
      import_kw: hasSample ? importKw : null,
      export_kw: hasSample ? exportKw : null,
      gap_before: hasSample && !previousSelected,
    });
    previousSelected = hasSample;
  }
  return canonical;
}

function monotoneEndpointTangent(point, nextPoint, followingPoint, slope, nextSlope) {
  const width = Math.abs(nextPoint.x - point.x);
  const nextWidth = Math.abs(followingPoint.x - nextPoint.x);
  let tangent = ((2 * width + nextWidth) * slope - width * nextSlope) / (width + nextWidth);
  if (Math.sign(tangent) !== Math.sign(slope)) tangent = 0;
  if (Math.sign(slope) !== Math.sign(nextSlope) && Math.abs(tangent) > Math.abs(3 * slope)) {
    tangent = 3 * slope;
  }
  return tangent;
}

export function buildMonotoneCubicSegments(coordinates) {
  if (!Array.isArray(coordinates) || coordinates.length < 2) return [];
  const slopes = coordinates.slice(0, -1).map((left, index) => (
    (coordinates[index + 1].y - left.y) / (coordinates[index + 1].x - left.x)
  ));
  const tangents = new Array(coordinates.length).fill(0);
  if (slopes.length === 1) {
    tangents[0] = slopes[0];
    tangents[1] = slopes[0];
  } else {
    tangents[0] = monotoneEndpointTangent(
      coordinates[0], coordinates[1], coordinates[2], slopes[0], slopes[1],
    );
    for (let index = 1; index < coordinates.length - 1; index += 1) {
      const previousSlope = slopes[index - 1];
      const nextSlope = slopes[index];
      tangents[index] = previousSlope * nextSlope <= 0
        ? 0
        : (2 * previousSlope * nextSlope) / (previousSlope + nextSlope);
    }
    tangents[tangents.length - 1] = monotoneEndpointTangent(
      coordinates.at(-1), coordinates.at(-2), coordinates.at(-3), slopes.at(-1), slopes.at(-2),
    );
  }
  return coordinates.slice(0, -1).map((start, index) => {
    const end = coordinates[index + 1];
    const width = end.x - start.x;
    return {
      start,
      control1: { x: start.x + width / 3, y: start.y + tangents[index] * width / 3 },
      control2: { x: end.x - width / 3, y: end.y - tangents[index + 1] * width / 3 },
      end,
    };
  });
}

function positionChartTooltip(chart, tooltip, clientX, clientY, obstacles = [], orbitState = {}) {
  const gap = 12;
  const safety = 7;
  const bounds = chart.getBoundingClientRect();
  const pointerX = clientX - bounds.left + chart.scrollLeft;
  const pointerY = clientY - bounds.top + chart.scrollTop;
  const tooltipWidth = tooltip.offsetWidth;
  const tooltipHeight = tooltip.offsetHeight;
  const viewportLeft = chart.scrollLeft + safety;
  const viewportRight = chart.scrollLeft + chart.clientWidth - safety;
  const viewportTop = chart.scrollTop + safety;
  const viewportBottom = chart.scrollTop + chart.clientHeight - safety;
  const obstacleRects = obstacles.map((obstacle) => {
    const rect = obstacle.getBoundingClientRect ? obstacle.getBoundingClientRect() : obstacle;
    return {
      left: rect.left - bounds.left + chart.scrollLeft - 8,
      right: rect.right - bounds.left + chart.scrollLeft + 8,
      top: rect.top - bounds.top + chart.scrollTop - 8,
      bottom: rect.bottom - bounds.top + chart.scrollTop + 8,
    };
  });
  const intersects = (left, top) => obstacleRects.some((rect) => (
    left < rect.right
    && left + tooltipWidth > rect.left
    && top < rect.bottom
    && top + tooltipHeight > rect.top
  ));
  const fitsViewport = (left, top) => (
    left >= viewportLeft
    && top >= viewportTop
    && left + tooltipWidth <= viewportRight
    && top + tooltipHeight <= viewportBottom
  );
  const angleStep = Math.PI / 45;
  const preferredAngle = Number.isFinite(orbitState.angle) ? orbitState.angle : -Math.PI / 2;
  const candidates = [];
  for (let distance = 0; distance <= 36; distance += 12) {
    for (let offset = 0; offset <= Math.PI; offset += angleStep) {
      if (offset === 0) {
        candidates.push(preferredAngle);
        continue;
      }
      candidates.push(preferredAngle - offset, preferredAngle + offset);
    }
    for (const angle of candidates) {
      const unitX = Math.cos(angle);
      const unitY = Math.sin(angle);
      const extent = Math.abs(unitX) * tooltipWidth / 2 + Math.abs(unitY) * tooltipHeight / 2;
      const centerX = pointerX + unitX * (extent + gap + distance);
      const centerY = pointerY + unitY * (extent + gap + distance);
      const left = centerX - tooltipWidth / 2;
      const top = centerY - tooltipHeight / 2;
      if (!fitsViewport(left, top) || intersects(left, top)) continue;
      orbitState.angle = angle;
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
      return;
    }
    candidates.length = 0;
  }
  const fallbackLeft = Math.max(viewportLeft, Math.min(viewportRight - tooltipWidth, pointerX - tooltipWidth / 2));
  const fallbackTop = Math.max(viewportTop, Math.min(viewportBottom - tooltipHeight, pointerY - tooltipHeight / 2));
  tooltip.style.left = `${fallbackLeft}px`;
  tooltip.style.top = `${fallbackTop}px`;
}

class ElrakningPanel {
  constructor(host, version) {
    this.host = host;
    this.version = version;
    this._debugEnabled = false;
    this._debugPreferenceChanged = false;
    this._diagnosticEntries = [];
    this._pinnedPeriod = null;
    this._chartTouch = null;
    this._chartDebugCopyText = "";
    this._tooltipOrbit = { angle: null };
    this._meterPowerHistory = { date: null, points: [] };
    this._meterTooltipPoints = [];
    this._meterCanonicalPoints = [];
    this._meterCanonicalPointMap = new Map();
    this._meterHistorySummary = null;
    this._meterHistoryRequestToken = 0;
    this._meterPowerVisible = { import: true, export: true };
    this._spotBarsVisible = true;
    this._averageLineVisible = true;
    this._previewLayersVisible = {
      solar: true,
      consumption: true,
      charging: true,
      discharging: true,
    };
    this._priceComparisonVisible = { electricity: true, grid: false };
    this._providerConfigured = false;
    this.priceData = {
      source: "nord_pool",
      mode: "spot_price",
      adjustments: {},
      periods: [],
      error: "missing_integration",
    };
  }

  render() {
    this.host.innerHTML = `
      <div class="theme-background" aria-hidden="true"></div>
      <main class="page">
        <header class="header">
          <div class="header-top">
            <div class="page-title-row">
              <h1>Elräkning</h1>
              <span class="frontend-version">${this.version}</span>
            </div>
            <label class="debug-toggle">
              <span aria-hidden="true">🐞</span>
              <input type="checkbox" role="switch" aria-label="Visa diagnostik" data-debug-toggle>
              <span class="debug-toggle-track" aria-hidden="true"><span></span></span>
            </label>
          </div>
          <p>Översikt</p>
        </header>

        <section class="price-section" aria-labelledby="price-title">
          <div class="section-heading">
            <div>
              <h2 id="price-title">Dagens elpris</h2>
              <p class="status">Spotpris · öre/kWh</p>
            </div>
            <div class="price-comparison-controls" aria-label="Prisjämförelse">
              <label class="price-filter-toggle" data-price-layer="electricity">
                <span>Handel</span>
                <input type="checkbox" role="switch" data-price-toggle checked>
                <span class="price-filter-track" aria-hidden="true"><span></span></span>
              </label>
              <label class="price-filter-toggle" data-price-layer="grid">
                <span>Nät</span>
                <input type="checkbox" role="switch" data-price-toggle>
                <span class="price-filter-track" aria-hidden="true"><span></span></span>
              </label>
            </div>
            <div class="price-summary">
              <div class="price-value current">
                <span>Just nu</span>
                <strong data-price="current">–</strong>
              </div>
              <div class="price-value average">
                <span>Snitt</span>
                <strong data-price="average">–</strong>
              </div>
              <div class="price-value">
                <span>Lägst</span>
                <strong data-price="lowest">–</strong>
              </div>
              <div class="price-value">
                <span>Högst</span>
                <strong data-price="highest">–</strong>
              </div>
            </div>
          </div>
          <div class="price-chart" aria-live="polite"></div>
          <div class="price-chart-legend" data-meter-legend hidden>
            <button type="button" class="chart-legend-toggle active" data-chart-layer="spot" aria-pressed="true">
              <span class="chart-legend-swatch spot" aria-hidden="true"></span>Pris
            </button>
            <button type="button" class="chart-legend-toggle active" data-chart-layer="average" aria-pressed="true">
              <span class="chart-legend-swatch average" aria-hidden="true"></span>Snitt
            </button>
            <button type="button" class="chart-legend-toggle active" data-chart-layer="import" aria-pressed="true">
              <span class="chart-legend-swatch import" aria-hidden="true"></span>Köp
            </button>
            <button type="button" class="chart-legend-toggle active" data-chart-layer="export" aria-pressed="true">
              <span class="chart-legend-swatch export" aria-hidden="true"></span>Sälj
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview active solar" data-preview-layer="solar" aria-pressed="true">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Sol
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview active consumption" data-preview-layer="consumption" aria-pressed="true">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Förbrukning
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview active charging" data-preview-layer="charging" aria-pressed="true">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Laddning
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview active discharging" data-preview-layer="discharging" aria-pressed="true">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Urladdning
            </button>
          </div>
          <p class="price-analysis" data-price-analysis aria-live="polite">Dagens prisanalys laddas …</p>
        </section>

        <section class="grid" aria-label="Elräkningens översikt">
          <article class="card" data-provider-card="elhandel">
            <div class="card-heading">
              <h2>Elhandel</h2>
              <span class="status" data-provider-status></span>
            </div>
            <p class="provider" data-provider-name="elhandel" hidden></p>
            <div class="provider-summary" data-provider-summary hidden></div>
            <div class="retained-history" data-retained-history hidden>
              <h3>Sparad historik</h3>
              <div data-retained-history-list></div>
            </div>
            <p class="provider-processing-error" data-provider-processing-error hidden>Fel vid senaste hämtning</p>
            <button type="button" data-electricity-configure>Konfigurera</button>
            <button type="button" data-provider-source hidden>Vad har vi för data?</button>
            <button type="button" data-greenely-parse-latest hidden>Tolka senaste</button>
          </article>

            <article class="card" data-provider-card="elnet">
            <div class="card-heading">
              <h2>Elnät</h2>
              <span class="status">Ej konfigurerad</span>
            </div>
            <p class="provider" data-provider-name="elnet" hidden></p>
            <button type="button">Konfigurera</button>
          </article>

          <article class="card" data-provider-card="elmatare">
            <div class="card-heading">
              <h2>Elmätare</h2>
              <span class="status" data-meter-status>Ej konfigurerad</span>
            </div>
            <p class="provider" data-provider-name="elmatare" hidden></p>
            <div class="meter-summary" data-meter-summary hidden></div>
            <button type="button" data-meter-configure>Konfigurera</button>
            <button type="button" data-meter-source hidden>Visa mätardata</button>
          </article>

        </section>
        <section class="card invoice-diagnostics" data-invoice-diagnostics hidden>
          <h2>Fakturatolkning</h2>
          <div class="invoice-diagnostic-grid" data-invoice-diagnostic-fields></div>
          <h3>PDF-textutdrag</h3>
          <pre data-invoice-debug-text></pre>
        </section>
        <section class="card diagnostics-card" data-diagnostics-card hidden>
          <div class="card-heading"><h2>Diagnostik</h2><span class="status" data-diagnostics-status>OK</span></div>
          <button type="button" data-diagnostics-copy>Kopiera alla loggar</button>
          <button type="button" data-diagnostics-clear>Rensa loggar</button>
          <span class="diagnostics-copy-status" data-diagnostics-copy-status aria-live="polite"></span>
          <div class="diagnostics-list" data-diagnostics-list></div>
        </section>
      </main>
      <div class="provider-source-dialog" data-provider-source-dialog hidden role="dialog" aria-modal="true">
        <div class="provider-dialog-card">
          <h2>Source data</h2>
          <p class="source-provider" data-provider-source-provider hidden></p>
          <pre data-provider-source-text></pre>
          <button type="button" data-provider-source-copy disabled>Kopiera</button>
          <button type="button" data-provider-source-close>Stäng</button>
        </div>
      </div>
      <div class="meter-dialog" data-meter-dialog hidden role="dialog" aria-modal="true" aria-labelledby="meter-title">
        <div class="meter-dialog-card">
          <h2 id="meter-title">Elmätare</h2>
          <p data-meter-result></p>
          <div class="meter-selectors" data-meter-selectors></div>
          <button type="button" data-meter-clear>Rensa elmätare</button>
          <div class="provider-actions">
            <button type="button" data-meter-cancel>Avbryt</button>
            <button type="button" data-meter-save disabled>Spara</button>
          </div>
        </div>
      </div>
      <div class="meter-source-dialog" data-meter-source-dialog hidden role="dialog" aria-modal="true">
        <div class="provider-dialog-card">
          <h2>Mätardata</h2>
          <pre data-meter-source-text></pre>
          <button type="button" data-meter-source-close>Stäng</button>
        </div>
      </div>
      <div class="provider-dialog" data-electricity-dialog hidden role="dialog" aria-modal="true" aria-labelledby="electricity-provider-title">
        <div class="provider-dialog-card">
          <h2 id="electricity-provider-title">Välj elhandelsbolag</h2>
          <label>Elhandelsbolag<select data-electricity-provider aria-label="Elhandelsbolag"></select></label>
          <label>E-post<input type="email" data-greenely-email autocomplete="off"></label>
          <label>Lösenord<input type="password" data-greenely-password autocomplete="off"></label>
          <p class="provider-result" data-provider-result></p>
          <select data-greenely-facility hidden aria-label="Greenely-anläggning"></select>
          <div data-electricity-history-option></div>
          <div class="provider-actions">
            <button type="button" data-electricity-cancel>Avbryt</button>
            <button type="button" data-electricity-remove hidden>Ta bort elhandelsavtal</button>
            <button type="button" data-electricity-save>Spara</button>
            <button type="button" data-greenely-consumption hidden>Testa förbrukning</button>
            <button type="button" data-greenely-invoices hidden>Hämta fakturor</button>
            <button type="button" data-greenely-parse hidden>Tolka senaste fakturan</button>
          </div>
        </div>
      </div>
      <style>
        :host {
          --card-title-size: clamp(20px, 5.2cqw, 24px);
          --price-card-text-size: clamp(10px, 2.7cqw, 12px);
          --card-legend-size: var(--price-card-text-size);
          display: block;
          height: 100%;
          min-height: 0;
          overflow: auto;
          box-sizing: border-box;
          color: var(--primary-text-color);
        }

        .theme-background {
          inset: 0;
          pointer-events: none;
          position: fixed;
          z-index: 0;
        }

        .page {
          box-sizing: border-box;
          max-width: 960px;
          min-height: 100%;
          margin: 0 auto;
          padding: 28px 20px 40px;
          position: relative;
          z-index: 1;
        }

        .page-title-row {
          align-items: baseline;
          display: flex;
          gap: 8px;
        }

        .header-top {
          align-items: center;
          display: flex;
          justify-content: space-between;
          gap: 16px;
        }

        .debug-toggle {
          align-items: center;
          color: var(--secondary-text-color);
          cursor: pointer;
          display: inline-flex;
          gap: 10px;
          user-select: none;
        }

        .debug-toggle input {
          height: 1px;
          opacity: 0;
          position: absolute;
          width: 1px;
        }

        .debug-toggle-track {
          background: var(--divider-color);
          border-radius: 999px;
          box-sizing: border-box;
          display: block;
          height: 30px;
          position: relative;
          transition: background-color 120ms ease;
          width: 52px;
        }

        .debug-toggle-track span {
          background: var(--ha-card-background, var(--card-background-color));
          border-radius: 50%;
          box-shadow: var(--ha-card-box-shadow, none);
          display: block;
          height: 22px;
          left: 4px;
          position: absolute;
          top: 50%;
          transform: translateY(-50%);
          transition: left 120ms ease;
          width: 22px;
        }

        .debug-toggle input:checked + .debug-toggle-track {
          background: var(--primary-color);
        }

        .debug-toggle input:checked + .debug-toggle-track span {
          left: calc(100% - 4px - 22px);
        }

        .debug-toggle input:focus-visible + .debug-toggle-track {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }

        .frontend-version {
          color: var(--secondary-text-color);
          font-size: 12px;
          opacity: .7;
        }

        .provider-dialog, .provider-source-dialog {
          align-items: center;
          background: color-mix(in srgb, var(--primary-background-color) 70%, transparent);
          display: flex;
          inset: 0;
          justify-content: center;
          padding: 20px;
          position: fixed;
          z-index: 2;
        }

        .meter-dialog, .meter-source-dialog {
          align-items: center;
          background: color-mix(in srgb, var(--primary-background-color) 70%, transparent);
          display: flex;
          inset: 0;
          justify-content: center;
          padding: 20px;
          position: fixed;
          z-index: 2;
        }

        .meter-dialog[hidden], .meter-source-dialog[hidden] {
          display: none;
        }

        .meter-dialog-card {
          background: var(--ha-card-background, var(--card-background-color));
          border: 1px solid var(--divider-color);
          border-radius: var(--ha-card-border-radius, 12px);
          box-sizing: border-box;
          max-width: 620px;
          padding: 20px;
          width: 100%;
        }

        .meter-selectors {
          display: grid;
          gap: 16px;
          margin-top: 16px;
        }

        .meter-selector-label {
          color: var(--primary-text-color);
          display: grid;
          font-weight: 500;
          gap: 6px;
        }

        .meter-summary {
          color: var(--secondary-text-color);
          display: grid;
          gap: 6px 18px;
          grid-template-columns: minmax(120px, auto) 1fr;
          margin-top: 14px;
        }

        .provider-dialog[hidden], .provider-source-dialog[hidden] {
          display: none;
        }

        .provider-dialog-card {
          background: var(--ha-card-background, var(--card-background-color));
          border: 1px solid var(--divider-color);
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-box-shadow, none);
          box-sizing: border-box;
          max-width: 420px;
          padding: 24px;
          width: 100%;
        }

        .provider-dialog-card label {
          color: var(--secondary-text-color);
          display: block;
          margin-top: 16px;
        }

        .provider-dialog-card input {
          background: var(--primary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          box-sizing: border-box;
          color: var(--primary-text-color);
          display: block;
          font: inherit;
          margin-top: 6px;
          padding: 9px;
          width: 100%;
        }

        .electricity-history-option {
          align-items: center;
          display: flex !important;
          gap: 8px;
        }

        .provider-dialog-card .electricity-history-option input {
          display: inline-block;
          height: auto;
          margin: 0;
          padding: 0;
          width: auto;
        }

        .electricity-history-help {
          color: var(--secondary-text-color);
          font-size: 12px;
          margin: 6px 0 0;
        }

        .provider-actions {
          display: flex;
          gap: 10px;
          justify-content: flex-end;
          margin-top: 20px;
        }

        .provider-result {
          margin-top: 16px;
          white-space: pre-line;
        }

        .provider-dialog-card select {
          background: var(--primary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          box-sizing: border-box;
          color: var(--primary-text-color);
          font: inherit;
          margin-top: 12px;
          padding: 9px;
          width: 100%;
        }

        .provider-source-dialog pre {
          color: var(--secondary-text-color);
          max-height: 60vh;
          overflow: auto;
          white-space: pre-wrap;
        }

        .provider-summary {
          display: grid;
          gap: 6px 18px;
          grid-template-columns: minmax(130px, auto) 1fr;
          margin-top: 14px;
        }

        .source-provider {
          color: var(--secondary-text-color);
          font-size: 14px;
          margin: 8px 0 0;
        }

        .provider-summary strong {
          color: var(--secondary-text-color);
          font-weight: 400;
        }

        .provider-processing-error {
          color: var(--secondary-text-color);
          font-size: 14px;
          margin-top: 12px;
        }

        .invoice-summary {
          color: var(--secondary-text-color);
          margin-top: 12px;
          white-space: pre-line;
        }

        .retained-history {
          border-top: 1px solid var(--divider-color);
          margin-top: 16px;
          padding-top: 12px;
        }

        .retained-history h3 {
          font-size: 14px;
          margin: 0 0 8px;
        }

        .retained-history-item {
          align-items: center;
          display: flex;
          gap: 12px;
          justify-content: space-between;
        }

        .retained-history-item + .retained-history-item {
          border-top: 1px solid var(--divider-color);
          margin-top: 10px;
          padding-top: 10px;
        }

        .retained-history-details {
          color: var(--secondary-text-color);
          font-size: 13px;
        }

        .invoice-diagnostics {
          margin-top: 16px;
        }

        .invoice-diagnostic-grid {
          display: grid;
          gap: 6px 18px;
          grid-template-columns: minmax(150px, auto) 1fr;
          margin-top: 16px;
        }

        .invoice-diagnostics h3 {
          font-size: 15px;
          font-weight: 500;
          margin: 20px 0 8px;
        }

        .invoice-diagnostics pre {
          background: var(--primary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          box-sizing: border-box;
          color: var(--secondary-text-color);
          max-height: 360px;
          overflow: auto;
          padding: 12px;
          white-space: pre-wrap;
        }

        .diagnostics-list {
          display: grid;
          gap: 6px;
          margin-top: 14px;
          max-height: 320px;
          overflow: auto;
        }

        .diagnostics-copy-status {
          color: var(--secondary-text-color);
          font-size: 13px;
          margin-left: 8px;
        }

        .diagnostics-card {
          margin-top: 16px;
        }

        .diagnostic-entry {
          color: var(--secondary-text-color);
          display: grid;
          gap: 2px;
          font-size: 13px;
        }

        .diagnostic-meta {
          color: var(--primary-text-color);
          font-weight: 500;
        }

        .diagnostic-entry.error { color: var(--error-color); }
        .diagnostic-entry.warning { color: var(--warning-color); }


        .header {
          border-bottom: 1px solid var(--divider-color);
          margin-bottom: 24px;
          padding-bottom: 16px;
        }

        h1, h2, p {
          margin: 0;
        }

        h1 {
          font-size: 28px;
          font-weight: 500;
        }

        .header p {
          color: var(--secondary-text-color);
          font-size: 16px;
          margin-top: 8px;
        }

        .grid {
          display: grid;
          gap: 16px;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        }

        .price-section {
          --solar-color: #77C2A1;
          --consumption-color: #EA7671;
          --grid-import-color: #F2A373;
          --grid-export-color: #72AAF6;
          --charging-color: #844A54;
          --discharging-color: #E06681;
          container-name: price-card;
          container-type: inline-size;
          background: var(--ha-card-glass-tint, var(--ha-card-background, var(--card-background-color)));
          border: var(--ha-card-border-width, 1px) var(--ha-card-border-style, solid) var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-glass-inset-shadow, var(--ha-card-box-shadow, none));
          box-sizing: border-box;
          isolation: isolate;
          margin-bottom: 16px;
          overflow: hidden;
          padding: 20px 20px 12px;
          position: relative;
          backdrop-filter: var(--ha-card-backdrop-filter, none);
          -webkit-backdrop-filter: var(--ha-card-backdrop-filter, none);
        }

        .section-heading {
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 16px;
          margin-bottom: 2px;
        }

        .price-summary {
          display: grid;
          gap: 20px;
          flex: 0 0 auto;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          min-width: min(100%, 408px);
          text-align: right;
          width: min(100%, 408px);
        }

        .price-value > span {
          display: block;
          white-space: nowrap;
        }

        .price-value strong {
          display: block;
          font-size: var(--price-card-text-size);
          font-weight: 600;
          margin-top: 3px;
          white-space: nowrap;
        }

        .price-value.current strong.cheap {
          color: var(--success-color);
        }

        .price-value.current strong.normal {
          color: var(--warning-color);
        }

        .price-value.current strong.expensive {
          color: var(--error-color);
        }

        .price-value small, .price-value em {
          color: var(--secondary-text-color);
          display: block;
          font-size: var(--price-card-text-size);
          font-style: normal;
          white-space: nowrap;
        }

        .price-value > span {
          color: var(--secondary-text-color);
          font-size: var(--price-card-text-size);
        }

        .section-heading h2,
        .card[data-provider-card] h2 {
          font-size: var(--card-title-size);
          font-weight: 700;
          line-height: 1.1;
          margin-bottom: 6px;
          white-space: nowrap;
        }

        .price-section .section-heading > div:first-child {
          flex: 0 0 auto;
          min-width: max-content;
        }

        .unit {
          color: var(--secondary-text-color);
          font-size: var(--price-card-text-size);
          font-weight: 500;
          line-height: 1.2;
          opacity: .9;
          white-space: nowrap;
        }

        .price-section .section-heading .status {
          font-size: var(--price-card-text-size);
          font-weight: 500;
          line-height: 1.2;
          opacity: .9;
        }

        .chart-bar.cheap {
          fill: color-mix(in srgb, var(--success-color) 38%, var(--ha-card-background, var(--card-background-color)));
        }

        .chart-bar.normal {
          fill: color-mix(in srgb, var(--warning-color) 38%, var(--ha-card-background, var(--card-background-color)));
        }

        .chart-bar.expensive {
          fill: color-mix(in srgb, var(--error-color) 38%, var(--ha-card-background, var(--card-background-color)));
        }

        @media (max-width: 600px) {
          .price-section {
          padding: 16px 12px 10px;
          }
        }

        .price-chart {
          container-type: inline-size;
          min-height: 0;
          overflow-x: hidden;
          position: relative;
          -webkit-overflow-scrolling: touch;
          overscroll-behavior-x: contain;
        }

        .price-analysis {
          color: var(--secondary-text-color);
          font-size: var(--price-card-text-size);
          height: auto;
          line-height: 18px;
          margin: 2px 0 0;
          min-height: 20px;
          overflow: visible;
          overflow-wrap: anywhere;
          text-overflow: clip;
          white-space: normal;
        }

        .price-analysis-status {
          font-size: var(--price-card-text-size);
          font-weight: 600;
          line-height: 1.2;
        }

        .price-analysis-status.cheap {
          color: var(--success-color);
        }

        .price-analysis-status.normal {
          color: var(--warning-color);
        }

        .price-analysis-status.expensive {
          color: var(--error-color);
        }

        .price-analysis-separator,
        .price-analysis-forecast {
          color: var(--secondary-text-color);
        }

        .price-analysis-forecast {
          font-size: var(--price-card-text-size);
          line-height: 1.35;
          overflow-wrap: anywhere;
        }

        @container price-card (max-width: 480px) {
          .price-analysis-status,
          .price-analysis-forecast {
            display: block;
          }

          .price-analysis-separator {
            display: none;
          }

          .price-analysis-forecast {
            margin-top: 2px;
          }
        }

        .price-chart-legend {
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 5px 10px;
          font-size: var(--card-legend-size);
          min-height: 22px;
          justify-content: center;
          margin-top: 1px;
        }

        .price-comparison-controls {
          align-items: center;
          display: flex;
          flex: 0 0 auto;
          gap: 6px;
          justify-content: flex-end;
          align-self: center;
          margin: 0 0 0 auto;
          white-space: nowrap;
        }

        .chart-legend-toggle {
          gap: 3px;
          padding: 1px 0;
        }

        .price-filter-toggle {
          align-items: center;
          color: var(--secondary-text-color);
          cursor: pointer;
          display: inline-flex;
          font-size: 10px;
          gap: 6px;
          user-select: none;
        }

        .price-filter-toggle input {
          height: 1px;
          opacity: 0;
          position: absolute;
          width: 1px;
        }

        .price-filter-track {
          background: var(--divider-color);
          border-radius: 999px;
          box-sizing: border-box;
          display: block;
          height: 16px;
          --knob-size: 11px;
          --track-padding: 2px;
          position: relative;
          transition: background-color 120ms ease;
          width: 27px;
        }

        .price-filter-track span {
          background: var(--ha-card-background, var(--card-background-color));
          border-radius: 50%;
          box-shadow: var(--ha-card-box-shadow, none);
          display: block;
          height: var(--knob-size);
          left: var(--track-padding);
          position: absolute;
          top: 50%;
          transform: translateY(-50%);
          transition: left 120ms ease;
          width: var(--knob-size);
        }

        .price-filter-toggle input:checked + .price-filter-track {
          background: var(--primary-color);
        }

        .price-filter-toggle input:checked + .price-filter-track span {
          left: calc(100% - var(--track-padding) - var(--knob-size));
        }

        .price-filter-toggle input:focus-visible + .price-filter-track {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }

        .price-filter-toggle.is-disabled {
          cursor: default;
          opacity: .35;
        }

        @supports (font-size: 1cqw) {
          .price-section .section-heading {
            gap: clamp(1px, .5cqw, 2px) clamp(6px, 2.1cqw, 16px);
          }

          .price-section .price-comparison-controls {
            gap: clamp(4px, 1.7cqw, 8px);
          }

          .price-section .price-filter-toggle {
            font-size: var(--price-card-text-size);
            gap: clamp(2px, .8cqw, 4px);
          }

          .price-section .price-filter-track {
            --knob-size: clamp(11px, 3cqw, 14px);
            --track-padding: clamp(2px, .7cqw, 3px);
            height: clamp(16px, 4.1cqw, 20px);
            width: clamp(27px, 7.2cqw, 34px);
          }

          .price-section .price-summary {
            gap: clamp(4px, 2.1cqw, 20px);
          }

          .price-section .chart-legend-swatch {
            height: clamp(4.5px, 1.5cqw, 6px);
            width: clamp(4.5px, 1.5cqw, 6px);
          }

          .price-section .price-analysis {
            margin-top: clamp(1px, .5cqw, 2px);
          }

          .price-section .price-analysis-forecast {
            margin-top: clamp(1px, .4cqw, 2px);
          }
        }

        .chart-legend-toggle {
          align-items: center;
          background: transparent;
          border: 0;
          color: var(--secondary-text-color);
          cursor: pointer;
          display: inline-flex;
          font-size: var(--card-legend-size);
          gap: 3px;
          margin: 0;
          opacity: .55;
          padding: 2px 0;
        }

        .chart-legend-toggle.active {
          color: var(--primary-text-color);
          opacity: 1;
        }

        .chart-legend-toggle:disabled {
          cursor: default;
          opacity: .35;
        }

        .chart-legend-toggle[data-chart-layer="import"] {
          color: var(--primary-text-color);
        }

        .chart-legend-toggle[data-chart-layer="export"] {
          color: var(--primary-text-color);
        }

        .chart-legend-toggle[data-chart-layer="spot"] {
          color: var(--secondary-text-color);
        }

        .chart-legend-preview {
          cursor: pointer;
          opacity: 1;
        }

        .chart-legend-preview:not(.active) {
          opacity: .55;
        }

        .chart-legend-preview.solar .chart-legend-swatch {
          background: var(--solar-color);
        }

        .chart-legend-preview.consumption .chart-legend-swatch {
          background: var(--consumption-color);
        }

        .chart-legend-preview.charging .chart-legend-swatch {
          background: var(--charging-color);
        }

        .chart-legend-preview.discharging .chart-legend-swatch {
          background: var(--discharging-color);
        }

        .chart-legend-preview {
          color: var(--primary-text-color);
        }

        .chart-legend-swatch {
          border-radius: 999px;
          display: inline-block;
          height: 7px;
          width: 7px;
        }

        .chart-legend-swatch.import {
          background: var(--grid-import-color);
        }

        .chart-legend-swatch.export {
          background: var(--grid-export-color);
        }

        .chart-legend-swatch.spot {
          background: var(--secondary-text-color);
        }

        .chart-legend-swatch.average {
          background: var(--warning-color);
        }

        .empty-chart {
          align-items: center;
          border: 1px dashed var(--divider-color);
          border-radius: 8px;
          box-sizing: border-box;
          color: var(--secondary-text-color);
          display: flex;
          justify-content: center;
          min-height: 220px;
          padding: 24px;
          text-align: center;
        }

        .chart-svg {
          aspect-ratio: 960 / 350;
          display: block;
          height: auto;
          max-width: 100%;
          max-height: 350px;
          min-width: 0;
          width: 100%;
        }

        @supports (height: 1cqw) {
          .chart-svg {
            height: min(350px, 36.458333cqw);
          }
        }

        .chart-axis, .chart-gridline {
          stroke: var(--divider-color);
          stroke-width: 1;
        }

        .chart-label {
          fill: var(--secondary-text-color);
          font-size: var(--card-chart-label-size);
        }

        .chart-average {
          stroke: var(--warning-color);
          stroke-dasharray: 5 4;
          stroke-width: 1.5;
        }

        .chart-meter-gridline {
          stroke: var(--divider-color);
          stroke-width: 1;
          opacity: .28;
        }

        .chart-meter-label {
          fill: var(--secondary-text-color);
          font-size: var(--card-chart-label-size);
        }

        .chart-meter-import,
        .chart-meter-export {
          fill: none;
          stroke-linecap: round;
          stroke-linejoin: round;
          stroke-width: 1.6;
          opacity: .82;
          vector-effect: non-scaling-stroke;
        }

        .chart-meter-import {
          stroke: var(--grid-import-color);
        }

        .chart-meter-export {
          stroke: var(--grid-export-color);
        }

        .chart-hover-markers {
          pointer-events: none;
        }

        .chart-hover-marker {
          stroke: var(--ha-card-background, var(--card-background-color));
          stroke-width: 2;
          vector-effect: non-scaling-stroke;
        }

        .chart-hover-marker-spot {
          fill: var(--primary-text-color);
        }

        .chart-hover-marker-import {
          fill: var(--grid-import-color);
        }

        .chart-hover-marker-export {
          fill: var(--grid-export-color);
        }

        .price-marker-label {
          fill: var(--primary-color);
          font-size: var(--card-marker-size);
          font-weight: 700;
        }

        .chart-bar {
          cursor: default;
        }

        .chart-tooltip {
          background: var(--ha-card-background, var(--card-background-color));
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          box-shadow: var(--ha-card-box-shadow);
          color: var(--primary-text-color);
          font-size: clamp(9px, 2.2cqw, 10px);
          left: 0;
          max-width: min(170px, calc(100% - 12px));
          overflow-wrap: anywhere;
          padding: clamp(4px, 1cqw, 5px) clamp(5px, 1.3cqw, 6px);
          pointer-events: none;
          position: absolute;
          top: 0;
          white-space: normal;
          z-index: 1;
        }

        .chart-tooltip.debug-tooltip {
          font-size: 13px;
          max-width: min(420px, calc(100% - 16px));
          padding: 8px 10px;
          pointer-events: none;
          white-space: pre-wrap;
        }

        .tooltip-value {
          display: block;
          font-size: inherit;
          line-height: 1.15;
          margin-top: 2px;
        }

        .chart-tooltip > strong {
          display: block;
          font-size: inherit;
          font-weight: 600;
          line-height: 1.15;
        }

        .tooltip-meter-import {
          color: var(--grid-import-color);
        }

        .tooltip-meter-export {
          color: var(--grid-export-color);
        }

        .card {
          background: var(--ha-card-glass-tint, var(--ha-card-background, var(--card-background-color)));
          border: var(--ha-card-border-width, 1px) var(--ha-card-border-style, solid) var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-glass-inset-shadow, var(--ha-card-box-shadow, none));
          box-sizing: border-box;
          isolation: isolate;
          min-height: 170px;
          overflow: hidden;
          padding: 20px;
          position: relative;
          container-type: inline-size;
          backdrop-filter: var(--ha-card-backdrop-filter, none);
          -webkit-backdrop-filter: var(--ha-card-backdrop-filter, none);
        }

        .card-heading {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        h2 {
          font-size: 19px;
          font-weight: 500;
        }

        .provider, .status {
          color: var(--secondary-text-color);
          font-size: 14px;
        }

        .provider {
          margin-top: 16px;
        }

        button {
          background: var(--primary-color);
          border: 0;
          border-radius: 6px;
          color: var(--text-primary-color);
          cursor: default;
          font: inherit;
          margin-top: 20px;
          padding: 10px 16px;
        }

      </style>
    `;

    this._setupThemeBackgroundSync();
    this._syncThemeBackground();
    this._bindElectricityProviderDialog();
    this._bindRetainedHistory();
    this._bindMeterDialog();
    this._bindDebugToggle();
    this._bindProviderSourceDialog();
    this._bindMeterSourceDialog();
    this._bindDiagnostics();
    this._bindMainInvoiceParser();
    this._bindChartLegend();
    this.renderPriceChart();
  }

  _bindChartLegend() {
    for (const button of this.host.querySelectorAll("[data-chart-layer]")) {
      button.addEventListener("click", () => {
        const layer = button.dataset.chartLayer;
        if (layer === "import" || layer === "export") {
          this._meterPowerVisible[layer] = !this._meterPowerVisible[layer];
          button.classList.toggle("active", this._meterPowerVisible[layer]);
          button.setAttribute("aria-pressed", String(this._meterPowerVisible[layer]));
          this.renderPriceChart();
          return;
        }
        if (layer === "average") {
          this._averageLineVisible = !this._averageLineVisible;
          button.classList.toggle("active", this._averageLineVisible);
          button.setAttribute("aria-pressed", String(this._averageLineVisible));
          this.renderPriceChart();
          return;
        }
        if (layer !== "spot") return;
        this._spotBarsVisible = !this._spotBarsVisible;
        button.classList.toggle("active", this._spotBarsVisible);
        button.setAttribute("aria-pressed", String(this._spotBarsVisible));
        this.renderPriceChart();
      });
    }
    for (const button of this.host.querySelectorAll("[data-preview-layer]")) {
      button.addEventListener("click", () => {
        const layer = button.dataset.previewLayer;
        if (!(layer in this._previewLayersVisible)) return;
        this._previewLayersVisible[layer] = !this._previewLayersVisible[layer];
        button.classList.toggle("active", this._previewLayersVisible[layer]);
        button.setAttribute("aria-pressed", String(this._previewLayersVisible[layer]));
      });
    }
    for (const control of this.host.querySelectorAll("[data-price-layer]")) {
      const input = control.querySelector("[data-price-toggle]");
      if (!input) continue;
      input.addEventListener("change", () => {
        const layer = control.dataset.priceLayer;
        if (!(layer in this._priceComparisonVisible) || input.disabled) return;
        this._priceComparisonVisible[layer] = !this._priceComparisonVisible[layer];
        input.checked = this._priceComparisonVisible[layer];
        this.updatePriceSummary();
        this.renderPriceChart();
      });
    }
  }

  _bindDebugToggle() {
    const toggle = this.host.querySelector("[data-debug-toggle]");
    if (!toggle) return;
    toggle.addEventListener("change", () => {
      this._debugEnabled = toggle.checked;
      this._debugPreferenceChanged = true;
      this._applyDebugVisibility();
      this._saveDebugPreference();
    });
    this._applyDebugVisibility();
  }

  async _loadDebugPreference() {
    if (!this.hass?.callWS) return;
    try {
      const response = await this.hass.callWS({ type: "elrakning/frontend_preferences" });
      if (!this._debugPreferenceChanged && typeof response.debug_enabled === "boolean") {
        this._debugEnabled = response.debug_enabled;
        const toggle = this.host.querySelector("[data-debug-toggle]");
        if (toggle) toggle.checked = this._debugEnabled;
        this._applyDebugVisibility();
      }
    } catch {
      // Keep the default off state when Home Assistant preference loading fails.
    }
  }

  async _saveDebugPreference() {
    if (!this.hass?.callWS) return;
    try {
      await this.hass.callWS({ type: "elrakning/frontend_preferences_set", debug_enabled: this._debugEnabled });
    } catch {
      // Keep the UI responsive; the next toggle can retry persistence.
    }
  }

  _applyDebugVisibility() {
    const source = this.host.querySelector("[data-provider-source]");
    const meterSource = this.host.querySelector("[data-meter-source]");
    const diagnostics = this.host.querySelector("[data-diagnostics-card]");
    if (source) source.hidden = !this._debugEnabled;
    if (meterSource) meterSource.hidden = !this._debugEnabled || this._meterState?.configured !== true;
    if (diagnostics) diagnostics.hidden = !this._debugEnabled;
  }

  _bindMeterDialog() {
    const open = this.host.querySelector("[data-meter-configure]");
    const dialog = this.host.querySelector("[data-meter-dialog]");
    const cancel = this.host.querySelector("[data-meter-cancel]");
    const save = this.host.querySelector("[data-meter-save]");
    const clear = this.host.querySelector("[data-meter-clear]");
    const result = this.host.querySelector("[data-meter-result]");
    const selectorsElement = this.host.querySelector("[data-meter-selectors]");
    if (!open || !dialog || !cancel || !save || !result || !selectorsElement) return;
    const fields = [
      ["Effekt", "power_entity"],
      ["Import", "energy_import_entity"],
      ["Export", "energy_export_entity"],
    ];
    const close = () => { dialog.hidden = true; };
    const renderSelectors = (mapping) => {
      selectorsElement.replaceChildren(...fields.map(([labelText, field]) => {
        const label = document.createElement("label");
        label.className = "meter-selector-label";
        label.textContent = labelText;
        const selector = document.createElement("ha-selector");
        selector.dataset.meterField = field;
        selector.hass = this.hass;
        selector.selector = { entity: { filter: { domain: "sensor" }, multiple: false } };
        selector.value = mapping?.[field] || undefined;
        selector.addEventListener("value-changed", (event) => {
          selector.value = event.detail?.value;
        });
        label.append(selector);
        return label;
      }));
    };
    open.addEventListener("click", async () => {
      dialog.hidden = false;
      save.disabled = true;
      result.textContent = "Hämtar sparad mätarkonfiguration …";
      try {
        const response = await this.hass.callWS({ type: "elrakning/meter_state" });
        this._applyMeterState(response);
        renderSelectors(response);
        result.textContent = "Välj de entiteter som ska användas.";
        save.disabled = false;
      } catch {
        selectorsElement.replaceChildren();
        result.textContent = "Mätarkonfigurationen kunde inte hämtas.";
      }
    });
    save.addEventListener("click", async () => {
      await this._recordMeterDiagnostic("INFO", "meter_save_clicked", "Meter save button clicked");
      const mapping = Object.fromEntries(fields.map(([, field]) => {
        const value = selectorsElement.querySelector(`[data-meter-field="${field}"]`)?.value;
        return [field, typeof value === "string" && value ? value : ""];
      }));
      const payload = {
        type: "elrakning/meter_save",
        ...mapping,
      };
      await this._recordMeterDiagnostic("INFO", "meter_selector_values_read", JSON.stringify(mapping));
      await this._recordMeterDiagnostic("INFO", "meter_mapping_created", `Created mapping: ${JSON.stringify(mapping)}`);
      await this._recordMeterDiagnostic("INFO", "meter_save_payload_created", `Payload fields: ${Object.keys(payload).filter((key) => key !== "type").join(", ")}`);
      await this._recordMeterDiagnostic("INFO", "meter_save_payload_types", `Payload types: ${Object.entries(payload).filter(([key]) => key !== "type").map(([key, value]) => `${key}:${typeof value}`).join(", ")}`);
      save.disabled = true;
      result.textContent = "Sparar …";
      try {
        await this._recordMeterDiagnostic("INFO", "meter_save_websocket_sent", "Meter save websocket request sent");
        const response = await this.hass.callWS(payload);
        await this._recordMeterDiagnostic("INFO", "meter_save_response_received", "Meter save websocket response received");
        if (!response.success) {
          await this._recordMeterDiagnostic("ERROR", "meter_save_response_failed", `Meter save response failed: ${response.error || "save_failed"}`);
          throw new Error(response.error || "save_failed");
        }
        this._applyMeterState(response);
        await this.loadMeterPowerHistory();
        close();
      } catch (error) {
        const details = this._websocketErrorDetails(error);
        await this._recordMeterDiagnostic("ERROR", "meter_save_exception", `Meter save exception: ${details.code}: ${details.message}`);
        save.disabled = false;
        result.textContent = `Elmätaren kunde inte sparas: ${details.code}: ${details.message}`;
      }
    });
    cancel.addEventListener("click", close);
    clear?.addEventListener("click", async () => {
      if (!window.confirm("Är du säker? Alla valda mätare tas bort.")) return;
      try {
        const response = await this.hass.callWS({ type: "elrakning/meter_store_clear" });
        if (!response.success) throw new Error(response.error || "meter_store_clear_failed");
        this._applyMeterState(response);
        renderSelectors(response);
        result.textContent = "Elmätare rensad.";
      } catch (error) {
        const details = this._websocketErrorDetails(error);
        result.textContent = `Elmätaren kunde inte rensas: ${details.code}: ${details.message}`;
      }
    });
  }

  async _recordMeterDiagnostic(level, event, message) {
    return this._recordDiagnostic("meter", level, event, message);
  }

  async _recordDiagnostic(component, level, event, message) {
    if (!this.hass?.callWS) return;
    try {
      await this.hass.callWS({
        type: "elrakning/meter_diagnostic",
        component,
        level,
        event,
        message,
      });
    } catch {
      // The save flow must remain usable if diagnostics transport is unavailable.
    }
  }

  async _copyText(text) {
    if (!text) throw new Error("empty_tooltip_text");
    let clipboardError;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return;
      } catch (error) {
        clipboardError = error;
      }
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) throw clipboardError || new Error("clipboard_unavailable");
  }

  _websocketErrorDetails(error) {
    const details = error?.error && typeof error.error === "object" ? error.error : error;
    return {
      code: details?.code || error?.code || "unknown_error",
      message: details?.message || error?.message || "Websocket request failed",
    };
  }

  _bindMeterSourceDialog() {
    const open = this.host.querySelector("[data-meter-source]");
    const dialog = this.host.querySelector("[data-meter-source-dialog]");
    const close = this.host.querySelector("[data-meter-source-close]");
    const text = this.host.querySelector("[data-meter-source-text]");
    if (!open || !dialog || !close || !text) return;
    const dismiss = () => { dialog.hidden = true; text.textContent = ""; };
    open.addEventListener("click", async () => {
      dialog.hidden = false;
      text.textContent = "Hämtar mätardata …";
      try {
        const response = await this.hass.callWS({ type: "elrakning/meter_source" });
        text.textContent = JSON.stringify(response, null, 2);
      } catch {
        text.textContent = "Mätardata kunde inte hämtas.";
      }
    });
    close.addEventListener("click", dismiss);
  }

  _bindRetainedHistory() {
    const list = this.host.querySelector("[data-retained-history-list]");
    if (!list) return;
    list.addEventListener("click", async (event) => {
      const button = event.target.closest?.("[data-retained-history-purge]");
      if (!button) return;
      const facilityId = button.dataset.facilityId;
      const provider = button.dataset.provider;
      if (!facilityId || !provider) return;
      if (!window.confirm("Radera sparad historik?\n\nDen lokalt sparade historiken för den här anläggningen och elhandelsbolaget raderas. Historik hos leverantören påverkas inte och kan hämtas igen om avtalet läggs till senare.")) return;
      button.disabled = true;
      try {
        const response = await this.hass.callWS({
          type: "elrakning/electricity_history_purge",
          facility_id: facilityId,
          provider,
        });
        if (!response.success) throw new Error(response.error || "history_purge_failed");
        await this.loadRetainedHistory();
      } catch {
        button.disabled = false;
      }
    });
  }

  async loadRetainedHistory() {
    const card = this.host.querySelector("[data-retained-history]");
    const list = this.host.querySelector("[data-retained-history-list]");
    if (!card || !list) return;
    try {
      const response = await this.hass.callWS({ type: "elrakning/electricity_history_state" });
      const history = Array.isArray(response.history) ? response.history : [];
      list.replaceChildren(...history.map((item) => {
        const row = document.createElement("div");
        row.className = "retained-history-item";
        const details = document.createElement("div");
        const provider = document.createElement("strong");
        provider.textContent = item.provider || "Elhandelsbolag";
        const counts = document.createElement("div");
        counts.className = "retained-history-details";
        counts.textContent = `${item.invoice_count || 0} fakturor · ${item.consumption_sample_count || 0} förbrukningsposter`;
        details.append(provider, counts);
        const purge = document.createElement("button");
        purge.type = "button";
        purge.textContent = "Radera historik";
        purge.dataset.retainedHistoryPurge = "";
        purge.dataset.facilityId = item.facility_id || "";
        purge.dataset.provider = item.provider || "";
        row.append(details, purge);
        return row;
      }));
      card.hidden = this._providerConfigured || history.length === 0;
    } catch {
      card.hidden = true;
    }
  }

  _bindElectricityProviderDialog() {
    const dialog = this.host.querySelector("[data-electricity-dialog]");
    const open = this.host.querySelector("[data-electricity-configure]");
    const cancel = this.host.querySelector("[data-electricity-cancel]");
    const save = this.host.querySelector("[data-electricity-save]");
    const remove = this.host.querySelector("[data-electricity-remove]");
    const providerSelect = this.host.querySelector("[data-electricity-provider]");
    const consumption = this.host.querySelector("[data-greenely-consumption]");
    const invoicesButton = this.host.querySelector("[data-greenely-invoices]");
    const parseButton = this.host.querySelector("[data-greenely-parse]");
    const facilitySelect = this.host.querySelector("[data-greenely-facility]");
    const historyOption = this.host.querySelector("[data-electricity-history-option]");
    const email = this.host.querySelector("[data-greenely-email]");
    const password = this.host.querySelector("[data-greenely-password]");
    const result = this.host.querySelector("[data-provider-result]");
    if (!dialog || !open || !cancel || !save || !remove || !providerSelect || !consumption || !invoicesButton || !parseButton || !facilitySelect || !email || !password || !result || !historyOption) return;
    let facilities = [];
    let saving = false;
    let purgeHistory = null;
    const close = () => {
      dialog.hidden = true;
      email.value = "";
      password.value = "";
      result.textContent = "";
      consumption.hidden = true;
      invoicesButton.hidden = true;
      parseButton.hidden = true;
      facilitySelect.hidden = true;
      facilitySelect.replaceChildren();
      purgeHistory = null;
      historyOption.replaceChildren();
      facilities = [];
    };
    const loadProviders = async () => {
      const state = await this.hass.callWS({ type: "elrakning/electricity_provider_state" });
      const providers = Array.isArray(state.providers) ? state.providers : [];
      providerSelect.replaceChildren(...providers.map((provider) => {
        const option = document.createElement("option");
        option.value = provider.provider;
        option.textContent = provider.name;
        return option;
      }));
      providerSelect.value = state.provider || providers[0]?.provider || "";
      const configured = state.configured === true;
      remove.hidden = !configured;
      historyOption.replaceChildren();
      purgeHistory = null;
      if (configured) {
        const option = document.createElement("label");
        option.className = "electricity-history-option";
        purgeHistory = document.createElement("input");
        purgeHistory.type = "checkbox";
        purgeHistory.dataset.electricityPurgeHistory = "";
        const label = document.createElement("span");
        label.textContent = "Radera historik";
        option.append(purgeHistory, label);
        const help = document.createElement("p");
        help.className = "electricity-history-help";
        help.textContent = "Sparad historik i Elräkning för den här anläggningen och elhandelsbolaget raderas. Om avtalet läggs till igen kan historik hämtas på nytt från leverantören.";
        historyOption.append(option, help);
      }
    };
    const selectedProviderName = () => providerSelect.selectedOptions[0]?.textContent || "Elhandelsbolaget";
    open.addEventListener("click", async () => {
      dialog.hidden = false;
      result.textContent = "Hämtar elhandelsbolag …";
      try {
        await loadProviders();
        result.textContent = "";
        email.focus();
      } catch {
        result.textContent = "Elhandelsbolag kunde inte hämtas.";
      }
    });
    cancel.addEventListener("click", close);
    remove.addEventListener("click", async () => {
      if (saving) return;
      saving = true;
      remove.disabled = true;
      result.textContent = "Tar bort...";
      try {
        const response = await this.hass.callWS({
          type: "elrakning/electricity_provider_remove",
          provider: providerSelect.value,
          purge_history: purgeHistory?.checked === true,
        });
        if (!response.success) throw new Error(response.error || "remove_failed");
        this._applyProviderState({ configured: false });
        await this.loadPriceData();
        await loadProviders();
        await this.loadRetainedHistory();
        if (purgeHistory) purgeHistory.checked = false;
        result.textContent = "Elhandelsavtalet har tagits bort.";
      } catch {
        result.textContent = "Elhandelsavtalet kunde inte tas bort.";
      } finally {
        saving = false;
        remove.disabled = false;
      }
    });
    save.addEventListener("click", async () => {
      if (saving) return;
      if (!providerSelect.value) {
        result.textContent = "Välj ett elhandelsbolag.";
        return;
      }
      const emailValue = email.value.trim();
      const passwordValue = password.value;
      if (!emailValue || !passwordValue) {
        result.textContent = "Fyll i e-post och lösenord.";
        return;
      }
      saving = true;
      save.disabled = true;
      result.textContent = "Sparar...";
      if (facilities.length > 1) {
        try {
          const saved = await this.hass.callWS({ type: "elrakning/electricity_provider_save", email: emailValue, password: passwordValue, facility_id: facilitySelect.value });
          if (!saved.success) {
            result.textContent = this._greenelyErrorText(saved.error);
            return;
          }
          this._applyProviderState(saved);
          await this.loadPriceData();
          result.textContent = `${selectedProviderName()} konfigurerad`;
          setTimeout(close, 2500);
        } catch {
          result.textContent = "Elhandelsavtalet kunde inte sparas.";
        } finally {
          saving = false;
          save.disabled = false;
        }
        return;
      }
      try {
        const response = await this.hass.callWS({
          type: "elrakning/greenely_test",
          email: emailValue,
          password: passwordValue,
        });
        if (!response.success) {
          result.textContent = response.error === "invalid_auth"
            ? "Inloggningen misslyckades."
            : response.error === "unexpected_response"
              ? "Greenely svarade med ett oväntat format."
            : response.error === "connection_error" || response.error === "timeout"
              ? "Kunde inte ansluta till Greenely."
              : response.error === "no_facilities"
                ? "Inga anläggningar hittades."
                : "Greenely-testet misslyckades.";
          return;
        }
        facilities = response.facilities.filter((facility) => facility.id);
        const primaryFacilities = facilities.filter((facility) => facility.is_primary);
        facilitySelect.replaceChildren(...facilities.map((facility) => {
          const option = document.createElement("option");
          option.value = facility.id;
          option.textContent = facility.name || facility.address || facility.id;
          return option;
        }));
        if (facilities.length > 1) {
          facilitySelect.hidden = false;
        } else if (primaryFacilities.length === 1) {
          facilitySelect.value = primaryFacilities[0].id;
        }
        consumption.hidden = true;
        invoicesButton.hidden = true;
        if (facilities.length === 1) {
          const saved = await this.hass.callWS({ type: "elrakning/electricity_provider_save", email: emailValue, password: passwordValue, facility_id: facilities[0].id });
          if (!saved.success) {
            result.textContent = this._greenelyErrorText(saved.error);
            return;
          }
          this._applyProviderState(saved);
          await this.loadPriceData();
          result.textContent = `${selectedProviderName()} konfigurerad`;
          setTimeout(close, 2500);
        } else {
          result.textContent = "Välj anläggning och tryck Spara igen.";
          save.textContent = "Spara";
        }
      } catch {
        result.textContent = "Kunde inte ansluta till Greenely.";
      } finally {
        saving = false;
        save.disabled = false;
      }
    });
    consumption.addEventListener("click", async () => {
      const facilityId = facilitySelect.value;
      if (!facilityId) return;
      consumption.disabled = true;
      result.textContent = "Testar förbrukning …";
      try {
        const response = await this.hass.callWS({
          type: "elrakning/greenely_consumption_test",
          email: email.value.trim(),
          password: password.value,
          facility_id: facilityId,
        });
        if (!response.success) {
          result.textContent = response.error === "invalid_auth"
            ? "Inloggningen misslyckades."
            : response.error === "connection_error" || response.error === "timeout"
              ? "Kunde inte ansluta till Greenely."
              : response.error === "unexpected_response"
                ? "Greenely svarade med ett oväntat format."
                : "Förbrukningstestet misslyckades.";
          return;
        }
        result.textContent = `Förbrukningsdata hittades\nAntal datapunkter: ${response.data_count}\n\nFält: ${response.top_level_keys.join(", ") || "inga"}\nExempel:\n${response.sample_items.map((item) => JSON.stringify(item)).join("\n") || "inga"}`;
      } catch {
        result.textContent = "Kunde inte ansluta till Greenely.";
      } finally {
        consumption.disabled = false;
      }
    });
    invoicesButton.addEventListener("click", async () => {
      const facilityId = facilitySelect.value;
      if (!facilityId) return;
      invoicesButton.disabled = true;
      result.textContent = "Hämtar fakturor …";
      try {
        const response = await this.hass.callWS({
          type: "elrakning/electricity_provider_save",
          email: email.value.trim(),
          password: password.value,
          facility_id: facilityId,
        });
        if (!response.success) {
          result.textContent = response.error === "invalid_auth"
            ? "Inloggningen misslyckades."
            : response.error === "connection_error" || response.error === "timeout"
              ? "Kunde inte ansluta till Greenely."
              : response.error === "unexpected_response"
                ? "Greenely svarade med ett oväntat format."
                : "Fakturorna kunde inte hämtas.";
          return;
        }
        this._applyProviderState(response);
        this._updateInvoiceCard(response);
        result.textContent = `${response.invoice_count} fakturor hämtades.`;
      } catch {
        result.textContent = "Fakturorna kunde inte hämtas.";
      } finally {
        invoicesButton.disabled = false;
      }
    });
    parseButton.addEventListener("click", async () => {
      parseButton.disabled = true;
      result.textContent = "Tolkar senaste fakturan …";
      try {
        const response = await this.hass.callWS({ type: "elrakning/greenely_parse_latest_test" });
        if (!response.success) {
          result.textContent = response.error === "pdf_parser_unavailable"
            ? "PDF-parsern är inte tillgänglig i Home Assistant."
            : response.error === "invalid_pdf"
              ? "PDF-filen kunde inte tolkas."
              : "Fakturatolkningen misslyckades.";
          return;
        }
        const parsed = response.parsed || {};
        const spot = parsed.spot || {};
        const variable = parsed.variable_cost || {};
        const fixed = parsed.fixed_fee || {};
        result.textContent = [
          `Avtal: ${parsed.agreement_name || "–"}`,
          `Period: ${parsed.period_start || "–"} – ${parsed.period_end || "–"}`,
          `Förbrukning: ${this._formatNumber(parsed.consumption_kwh)} kWh`,
          `Spotpris: ${this._formatNumber(spot.rate_ore_per_kwh_ex_vat)} öre/kWh`,
          `Rörliga kostnader: ${this._formatNumber(variable.rate_ore_per_kwh_ex_vat)} öre/kWh`,
          `Fast avgift: ${this._formatSek(fixed.amount_ex_vat_sek)} ex moms`,
          `Moms: ${this._formatNumber(parsed.vat?.rate_percent)} %`,
          `Warnings: ${parsed.warnings?.join(", ") || "inga"}`,
        ].join("\n");
      } catch {
        result.textContent = "Fakturatolkningen misslyckades.";
      } finally {
        parseButton.disabled = false;
      }
    });
  }

  _bindProviderSourceDialog() {
    const open = this.host.querySelector("[data-provider-source]");
    const dialog = this.host.querySelector("[data-provider-source-dialog]");
    const close = this.host.querySelector("[data-provider-source-close]");
    const copy = this.host.querySelector("[data-provider-source-copy]");
    const provider = this.host.querySelector("[data-provider-source-provider]");
    const text = this.host.querySelector("[data-provider-source-text]");
    if (!open || !dialog || !close || !copy || !provider || !text) return;
    const dismiss = () => {
      dialog.hidden = true;
      provider.hidden = true;
      provider.textContent = "";
      text.textContent = "";
      copy.disabled = true;
    };
    open.addEventListener("click", async () => {
      dialog.hidden = false;
      text.textContent = "Hämtar Source data …";
      provider.hidden = true;
      provider.textContent = "";
      copy.disabled = true;
      try {
        const source = await this.hass.callWS({ type: "elrakning/electricity_provider_source_data", limit: 500 });
        const providerName = source.provider_name || source.facility?.provider_name;
        if (typeof providerName === "string" && providerName.trim()) {
          provider.textContent = `Källa: ${providerName.trim()}`;
          provider.hidden = false;
        }
        text.textContent = JSON.stringify({ facility: source.facility, contracts: source.contracts, invoices: source.invoices.items, consumption: { total: source.consumption.total, items: source.consumption.items } }, null, 2);
        copy.disabled = false;
      } catch {
        text.textContent = "Source data kunde inte hämtas.";
      }
    });
    copy.addEventListener("click", async () => {
      try {
        await this._copyText(text.textContent);
        copy.textContent = "Kopierat";
        window.setTimeout(() => { copy.textContent = "Kopiera"; }, 1500);
      } catch {
        copy.textContent = "Kunde inte kopiera";
        window.setTimeout(() => { copy.textContent = "Kopiera"; }, 1500);
      }
    });
    close.addEventListener("click", dismiss);
  }

  _bindDiagnostics() {
    const list = this.host.querySelector("[data-diagnostics-list]");
    const status = this.host.querySelector("[data-diagnostics-status]");
    const copy = this.host.querySelector("[data-diagnostics-copy]");
    const copyStatus = this.host.querySelector("[data-diagnostics-copy-status]");
    const clear = this.host.querySelector("[data-diagnostics-clear]");
    if (!list || !status || !copy || !copyStatus || !clear || !this.hass?.callWS) return;
    const render = (logs) => {
      const entries = Array.isArray(logs) ? logs : [];
      this._diagnosticEntries = entries.slice();
      const latest = entries.at(-1);
      status.textContent = latest?.level === "ERROR" ? "Fel" : latest?.level === "WARNING" ? "Varning" : "OK";
      list.replaceChildren(...this._diagnosticEntries.map((entry) => {
        const line = document.createElement("div");
        line.className = `diagnostic-entry ${String(entry.level || "").toLowerCase()}`;
        const time = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString("sv-SE") : "";
        const meta = document.createElement("div");
        meta.className = "diagnostic-meta";
        meta.textContent = `${time} ${diagnosticSymbol(entry.level)} ${diagnosticComponent(entry.component)}`;
        const message = document.createElement("div");
        message.textContent = entry.message || "";
        line.append(meta, message);
        return line;
      }));
    };
    const load = async () => {
      try {
        const response = await this.hass.callWS({ type: "elrakning/diagnostics_state" });
        render(response.logs);
      } catch {
        status.textContent = "Varning";
      }
    };
    this._loadDiagnosticsState = load;
    if (!this._diagnosticsBound) {
      copy.addEventListener("click", async () => {
        try {
          const clipboardEntries = this._diagnosticEntries.slice();
          await this._copyText(formatDiagnosticsText(clipboardEntries, this.version));
          copyStatus.textContent = "Kopierat";
          window.setTimeout(() => { copyStatus.textContent = ""; }, 1500);
        } catch {
          copyStatus.textContent = "Kunde inte kopiera";
        }
      });
      clear.addEventListener("click", async () => {
        await this.hass.callWS({ type: "elrakning/diagnostics_clear" });
        await load();
      });
      this._diagnosticsBound = true;
    }
    load();
  }

  _updateInvoiceCard(response) {
    const provider = this.host.querySelector('[data-provider-name="elhandel"]');
    const summary = this.host.querySelector("[data-provider-summary]");
    if (!provider || !summary) return;
    const agreement = response.summary?.agreement_name;
    provider.textContent = providerLabel(response.provider_name, agreement);
    provider.hidden = !provider.textContent;
    const tariff = response.summary?.tariff || {};
    const period = response.summary?.latest_period || {};
    const consumption = response.consumption;
    const latest = response.latest_invoice;
    const rows = [];
    if (tariff.variable_cost_ore_per_kwh_incl_vat != null) rows.push(["Rörlig kostnad", `${this._formatNumber(tariff.variable_cost_ore_per_kwh_incl_vat)} öre/kWh`]);
    if (tariff.fixed_fee_incl_vat_per_month != null) rows.push(["Fast avgift", `${this._formatSek(tariff.fixed_fee_incl_vat_per_month)}/mån`]);
    if (consumption?.month_to_date_kwh != null) rows.push([`Förbrukning ${this._formatInvoiceMonth(consumption.month)}`, `${this._formatNumber(consumption.month_to_date_kwh)} kWh`]);
    if (period.weighted_spot_average_ore_per_kwh != null) rows.push([`Snittspot ${this._formatInvoiceMonth(period.period_start)}`, `${this._formatNumber(period.weighted_spot_average_ore_per_kwh)} öre/kWh`]);
    if (period.credit_closing_sek > 0) rows.push(["Tillgodo", this._formatSek(period.credit_closing_sek)]);
    if (latest) {
      rows.push(["Senaste faktura", this._formatInvoiceMonth(latest.invoice_date || latest.month)]);
      if (period.amount_due_sek != null) rows.push(["Att betala", this._formatSek(period.amount_due_sek)]);
    }
    summary.replaceChildren(...rows.flatMap(([label, value]) => {
      const left = document.createElement("strong");
      left.textContent = label;
      const right = document.createElement("span");
      right.textContent = value;
      return [left, right];
    }));
    summary.hidden = rows.length === 0;
  }

  _formatInvoiceMonth(value) {
    if (typeof value !== "string") return "–";
    const match = value.match(/^(\d{4})-(\d{2})/);
    if (!match) return value;
    const month = ["Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"][Number(match[2]) - 1];
    return month ? `${month} ${match[1]}` : value;
  }

  _greenelyErrorText(error) {
    return error === "invalid_auth" ? "Felaktig e-post eller lösenord"
      : error === "connection_error" || error === "timeout" ? "Kunde inte ansluta till Greenely"
        : error === "no_facilities" ? "Ingen anläggning hittades"
          : error === "internal_error" ? "Greenely kunde inte konfigureras"
            : "Greenely svarade med ett oväntat format";
  }

  _formatSek(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "–";
    return `${value.toLocaleString("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} kr`;
  }

  _formatNumber(value) {
    return typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString("sv-SE", { maximumFractionDigits: 2 })
      : "–";
  }

  _formatInvoiceState(state) {
    if (state === "Paid") return "Betald";
    if (state === "Cancelled" || state === "Canceled") return "Makulerad";
    return state || "";
  }

  _bindMainInvoiceParser() {
    const button = this.host.querySelector("[data-greenely-parse-latest]");
    const diagnosticsCard = this.host.querySelector("[data-invoice-diagnostics]");
    const fields = this.host.querySelector("[data-invoice-diagnostic-fields]");
    const debugText = this.host.querySelector("[data-invoice-debug-text]");
    if (!button || !diagnosticsCard || !fields || !debugText) return;
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Felsöker …";
      try {
        const response = await this.hass.callWS({ type: "elrakning/greenely_parse_latest_test" });
        if (!response.success) {
          button.textContent = "Felsök misslyckades";
          return;
        }
        if (response.electricity_provider_state) this._applyProviderState(response.electricity_provider_state);
        const parsed = response.parsed || {};
        const variable = parsed.variable_cost || {};
        const fixed = parsed.fixed_fee || {};
        const spot = parsed.spot || {};
        const vat = parsed.vat || {};
        const diagnostics = response.diagnostics || {};
        const rows = [
          ["Avtal", parsed.agreement_name],
          ["Period", parsed.period_start && parsed.period_end ? `${parsed.period_start} – ${parsed.period_end}` : null],
          ["Förbrukning", this._formatNumber(parsed.consumption_kwh) === "–" ? null : `${this._formatNumber(parsed.consumption_kwh)} kWh`],
          ["Spotpris", spot.rate_ore_per_kwh_ex_vat == null ? null : `${this._formatNumber(spot.rate_ore_per_kwh_ex_vat)} öre/kWh · ${this._formatSek(spot.amount_ex_vat_sek)} ex moms`],
          ["Rörliga kostnader", variable.rate_ore_per_kwh_ex_vat == null ? null : `${this._formatNumber(variable.rate_ore_per_kwh_ex_vat)} öre/kWh · ${this._formatSek(variable.amount_ex_vat_sek)} ex moms`],
          ["Fast avgift", fixed.amount_ex_vat_sek == null ? null : `${this._formatSek(fixed.amount_ex_vat_sek)} ex moms · ${this._formatSek(fixed.amount_incl_vat_sek)} inkl moms`],
          ["Moms", vat.amount_sek != null ? `${this._formatSek(vat.amount_sek)}` : (vat.rate_percent == null ? null : `${this._formatNumber(vat.rate_percent)} %`)],
          ["Öresutjämning", parsed.rounding_sek == null ? null : this._formatSek(parsed.rounding_sek)],
          ["Ingående tillgodo", parsed.credit?.opening_balance_sek == null ? null : this._formatSek(parsed.credit.opening_balance_sek)],
          ["Använd kredit", parsed.credit?.used_sek == null ? null : this._formatSek(parsed.credit.used_sek)],
          ["Tillgodo efter faktura", parsed.credit?.closing_balance_sek == null ? null : this._formatSek(parsed.credit.closing_balance_sek)],
          ["Ordinarie kostnad", parsed.gross_charge_sek == null ? null : this._formatSek(parsed.gross_charge_sek)],
          ["Att betala", response.amount_due_sek == null ? null : this._formatSek(response.amount_due_sek)],
          ["Betalningskontroll", diagnostics.payment_reconciliation],
          ["Warnings", parsed.warnings?.length ? parsed.warnings.join(", ") : "inga"],
          ["Matchade fält", diagnostics.matched_fields?.join(", ") || "inga"],
          ["Saknade fält", diagnostics.missing_fields?.join(", ") || "inga"],
        ];
        fields.replaceChildren(...rows.flatMap(([label, value]) => {
          const left = document.createElement("strong");
          left.textContent = label;
          const right = document.createElement("span");
          right.textContent = value == null ? "Ej hittad" : value;
          return [left, right];
        }));
        debugText.textContent = response.debug_text_excerpt || "Inget relevant textutdrag hittades.";
        diagnosticsCard.hidden = false;
        button.textContent = "Felsök";
      } catch {
        button.textContent = "Felsök misslyckades";
      } finally {
        button.disabled = false;
      }
    });
  }

  _findDeep(root, selector) {
    const match = root.querySelector?.(selector);
    if (match) return match;
    for (const element of root.querySelectorAll?.("*") || []) {
      if (element.shadowRoot) {
        const shadowMatch = this._findDeep(element.shadowRoot, selector);
        if (shadowMatch) return shadowMatch;
      }
    }
    return null;
  }

  _syncThemeBackground() {
    const background = this.host.querySelector(".theme-background");
    const haMain = this._findDeep(document, "home-assistant-main");
    if (!background || !haMain) return;
    const rect = haMain.getBoundingClientRect();
    const lovelaceBackground = getComputedStyle(this.host)
      .getPropertyValue("--lovelace-background")
      .trim();
    background.style.position = "fixed";
    background.style.top = `${rect.top}px`;
    background.style.left = `${rect.left}px`;
    background.style.width = `${rect.width}px`;
    background.style.height = `${rect.height}px`;
    if (lovelaceBackground) {
      background.style.setProperty("background", lovelaceBackground, "important");
    }
  }

  _setupThemeBackgroundSync() {
    if (this._themeBackgroundReady) return;
    this._themeBackgroundReady = true;
    this._onThemeResize = () => this._syncThemeBackground();
    this._onThemeFocus = () => this._syncThemeBackground();
    this._onThemeVisibility = () => {
      if (document.visibilityState === "visible") this._syncThemeBackground();
    };
    window.addEventListener("resize", this._onThemeResize);
    window.addEventListener("focus", this._onThemeFocus);
    document.addEventListener("visibilitychange", this._onThemeVisibility);
    const haMain = this._findDeep(document, "home-assistant-main");
    if (haMain && "ResizeObserver" in window) {
      this._themeResizeObserver = new ResizeObserver(this._onThemeResize);
      this._themeResizeObserver.observe(haMain);
    }
  }

  _syncCardTheme() {
    const themes = this.hass?.themes;
    if (!themes) return;
    const themeName = themes.theme;
    const mode = themes.darkMode ? "dark" : "light";
    const theme = themes.themes?.[themeName];
    if (!theme) return;
    const key = `${themeName}:${mode}`;
    if (key === this._cardThemeKey) return;
    this._cardThemeKey = key;
    const effectiveTheme = { ...theme, ...(theme.modes?.[mode] || {}) };
    const root = effectiveTheme["card-mod-root"];
    const properties = ["--ha-card-glass-tint", "--ha-card-backdrop-filter", "--ha-card-glass-inset-shadow"];
    properties.forEach((property) => this.host.style.removeProperty(property));
    if (typeof root !== "string") return;
    const declarationPattern = /(--ha-card-(?:glass-tint|backdrop-filter|glass-inset-shadow))\s*:\s*([^;}]*)(?:;|$)/g;
    let match;
    while ((match = declarationPattern.exec(root))) {
      const value = match[2].replace(/\/\*[\s\S]*?\*\//g, "").trim();
      if (value && !value.startsWith("#") && !value.startsWith("//")) {
        this.host.style.setProperty(match[1], value);
      }
    }
  }

  setHass(hass) {
    this.hass = hass;
    this._bindDiagnostics();
    this._syncCardTheme();
    if (hass?.connection && this._eventConnection !== hass.connection) {
      if (this._eventUnsubscribePromise) {
        Promise.resolve(this._eventUnsubscribePromise)
          .then((unsubscribe) => unsubscribe?.())
          .catch(() => {});
      }
      if (this._greenelyEventUnsubscribePromise) {
        Promise.resolve(this._greenelyEventUnsubscribePromise)
          .then((unsubscribe) => unsubscribe?.())
          .catch(() => {});
      }
      if (this._meterEventUnsubscribePromise) {
        Promise.resolve(this._meterEventUnsubscribePromise)
          .then((unsubscribe) => unsubscribe?.())
          .catch(() => {});
      }
      if (this._meterPowerEventUnsubscribePromise) {
        Promise.resolve(this._meterPowerEventUnsubscribePromise)
          .then((unsubscribe) => unsubscribe?.())
          .catch(() => {});
      }
      if (this._diagnosticsEventUnsubscribePromise) {
        Promise.resolve(this._diagnosticsEventUnsubscribePromise)
          .then((unsubscribe) => unsubscribe?.())
          .catch(() => {});
      }
      this._eventUnsubscribePromise = hass.connection.subscribeEvents(
        () => this.loadPriceData(),
        "elrakning_price_update",
      );
      this._greenelyEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => {
          this.loadProviderState();
          this.loadRetainedHistory();
        },
        "elrakning_electricity_provider_update",
      );
      this._meterEventUnsubscribePromise = hass.connection.subscribeEvents(
        (event) => {
          const entityId = event.data?.entity_id;
          const mapping = this._meterState || {};
          if ([mapping.power_entity, mapping.energy_import_entity, mapping.energy_export_entity].includes(entityId)) {
            this.loadMeterState();
          }
        },
        "state_changed",
      );
      this._meterPowerEventUnsubscribePromise = hass.connection.subscribeEvents(
        (event) => this._appendMeterPowerPoint(event.data),
        "elrakning_meter_power_update",
      );
      this._diagnosticsEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => this._loadDiagnosticsState?.(),
        "elrakning_diagnostics_update",
      );
      this._eventConnection = hass.connection;
      this.loadPriceData();
      this.loadProviderState();
      this.loadRetainedHistory();
      this.loadMeterState();
      this._loadDebugPreference();
    }
  }

  destroy() {
    if (this._dismissTooltip) {
      document.removeEventListener("touchstart", this._dismissTooltip);
    }
    if (this._eventUnsubscribePromise) {
      Promise.resolve(this._eventUnsubscribePromise)
        .then((unsubscribe) => unsubscribe?.())
        .catch(() => {});
    }
    if (this._greenelyEventUnsubscribePromise) {
      Promise.resolve(this._greenelyEventUnsubscribePromise)
        .then((unsubscribe) => unsubscribe?.())
        .catch(() => {});
    }
    if (this._meterEventUnsubscribePromise) {
      Promise.resolve(this._meterEventUnsubscribePromise)
        .then((unsubscribe) => unsubscribe?.())
        .catch(() => {});
    }
    if (this._meterPowerEventUnsubscribePromise) {
      Promise.resolve(this._meterPowerEventUnsubscribePromise)
        .then((unsubscribe) => unsubscribe?.())
        .catch(() => {});
    }
    if (this._diagnosticsEventUnsubscribePromise) {
      Promise.resolve(this._diagnosticsEventUnsubscribePromise)
        .then((unsubscribe) => unsubscribe?.())
        .catch(() => {});
    }
    this._dismissTooltip = null;
    this._eventUnsubscribePromise = null;
    this._greenelyEventUnsubscribePromise = null;
    this._meterEventUnsubscribePromise = null;
    this._meterPowerEventUnsubscribePromise = null;
    this._diagnosticsEventUnsubscribePromise = null;
    this._loadDiagnosticsState = null;
    this._eventConnection = null;
    this._tooltipChart = null;
    window.removeEventListener("resize", this._onThemeResize);
    window.removeEventListener("focus", this._onThemeFocus);
    document.removeEventListener("visibilitychange", this._onThemeVisibility);
    this._themeResizeObserver?.disconnect();
    this._themeResizeObserver = null;
    this._themeBackgroundReady = false;
  }

  async loadPriceData() {
    if (!this.hass?.callWS) return;
    try {
      this.priceSnapshot = await this.hass.callWS({ type: "elrakning/price_data" });
    } catch {
      this.priceSnapshot = { error: "data_unavailable", periods: [] };
    }
    this.priceData = {
      source: "nord_pool",
      mode: this.priceSnapshot.mode || "spot_price",
      adjustments: this.priceSnapshot.adjustments || {},
      periods: Array.isArray(this.priceSnapshot.periods) ? this.priceSnapshot.periods : [],
      error: this.priceSnapshot.error || null,
    };
    this._updatePriceComparisonControls();
    this.updatePriceSummary();
    if (this.host.querySelector(".price-chart")) this.renderPriceChart();
  }

  async loadProviderState() {
    if (!this.hass?.callWS) return;
    try {
      const state = await this.hass.callWS({ type: "elrakning/electricity_provider_state" });
      this._applyProviderState(state);
    } catch {
      // Keep the optional Greenely UI unconfigured when state is unavailable.
    }
  }

  _applyProviderState(state) {
    const configured = state?.configured === true;
    this._providerConfigured = configured;
    const retainedHistory = this.host.querySelector("[data-retained-history]");
    if (retainedHistory && configured) retainedHistory.hidden = true;
    const status = this.host.querySelector("[data-provider-status]");
    const processingError = state?.processing_status?.error === true;
    const processingErrorText = this.host.querySelector("[data-provider-processing-error]");
    const mainParseButton = this.host.querySelector("[data-greenely-parse-latest]");
    if (status) status.textContent = "";
    if (processingErrorText) processingErrorText.hidden = !processingError;
    if (mainParseButton) {
      mainParseButton.hidden = !processingError;
      mainParseButton.textContent = "Felsök";
    }
    this._applyProviderCard("elhandel", {
      provider_name: configured ? state?.provider_name : null,
      agreement_name: configured ? state?.summary?.agreement_name : null,
      source_type: state?.source_type,
    });
    if (configured) {
      this._updateInvoiceCard(state);
      const parseButton = this.host.querySelector("[data-greenely-parse]");
      if (parseButton) parseButton.hidden = !processingError;
    } else {
      const summary = this.host.querySelector("[data-provider-summary]");
      if (summary) {
        summary.replaceChildren();
        summary.hidden = true;
      }
      const parseButton = this.host.querySelector("[data-greenely-parse]");
      if (parseButton) parseButton.hidden = true;
    }
  }

  _applyProviderCard(type, data) {
    const card = this.host.querySelector(`[data-provider-card="${type}"]`);
    const provider = this.host.querySelector(`[data-provider-name="${type}"]`);
    if (!provider) return;
    const label = providerLabel(data?.provider_name, data?.agreement_name);
    provider.textContent = label;
    provider.hidden = !label;
    if (card) {
      const status = card.querySelector(".status");
      if (status) {
        status.textContent = label ? "" : "Ej konfigurerad";
        status.hidden = Boolean(label);
      }
    }
  }

  _applyMeterState(state) {
    this._meterState = state;
    const provider = this.host.querySelector('[data-provider-name="elmatare"]');
    const summary = this.host.querySelector("[data-meter-summary]");
    const status = this.host.querySelector("[data-meter-status]");
    const source = this.host.querySelector("[data-meter-source]");
    const configured = state?.configured === true;
    const label = providerLabel(state?.provider_name, state?.device_name);
    if (provider) {
      provider.textContent = label;
      provider.hidden = !label;
    }
    if (status) {
      status.textContent = configured ? "" : "Ej konfigurerad";
      status.hidden = configured;
    }
    if (source) source.hidden = !this._debugEnabled || !configured;
    if (!summary) return;
    const rows = [
      ["Effekt just nu", state?.power_kw, "kW"],
      ["Import idag", state?.energy_import_kwh, "kWh"],
      ["Export idag", state?.energy_export_kwh, "kWh"],
    ].filter(([, value]) => typeof value === "number" && Number.isFinite(value));
    summary.replaceChildren(...rows.flatMap(([name, value, unit]) => {
      const labelElement = document.createElement("strong");
      labelElement.textContent = name;
      const valueElement = document.createElement("span");
      valueElement.textContent = `${this._formatNumber(value)} ${unit}`;
      return [labelElement, valueElement];
    }));
    summary.hidden = rows.length === 0;
  }

  async loadMeterState() {
    if (!this.hass?.callWS) return;
    try {
      const state = await this.hass.callWS({ type: "elrakning/meter_state" });
      this._applyMeterState(state);
      await this.loadMeterPowerHistory();
    } catch {
      // Keep the meter card unconfigured when state is unavailable.
    }
  }

  async loadMeterPowerHistory() {
    if (!this.hass?.callWS) return;
    const entityId = this._meterState?.power_entity || null;
    const requestToken = ++this._meterHistoryRequestToken;
    this._meterPowerHistory = { date: null, points: [] };
    this._meterHistorySummary = null;
    await this._recordMeterDiagnostic(
      "INFO",
      "meter_history_request_started",
      `Meter history request started · Entity: ${entityId || "none"}`,
    );
    try {
      const request = { type: "elrakning/meter_power_history" };
      if (entityId) request.entity_id = entityId;
      const response = await this.hass.callWS(request);
      if (requestToken !== this._meterHistoryRequestToken || entityId !== (this._meterState?.power_entity || null)) return;
      if (!response?.success) {
        this._meterHistorySummary = {
          entity_id: response?.entity_id || entityId,
          success: false,
          date: response?.date || null,
          point_count: 0,
          error: response?.error || "history_unavailable",
        };
        await this._recordMeterDiagnostic(
          "ERROR",
          "meter_history_request_failed",
          `Meter history failed · Entity: ${entityId || "none"} · Error: ${response?.error || "history_unavailable"}`,
        );
        if (this.host.querySelector(".price-chart")) this.renderPriceChart();
        return;
      }
      this._meterPowerHistory = {
        date: response?.date || null,
        points: Array.isArray(response?.points) ? response.points : [],
      };
      this._meterHistorySummary = response.history || {
        entity_id: response?.entity_id || entityId,
        success: true,
        date: response?.date || null,
        point_count: this._meterPowerHistory.points.length,
      };
      const summary = this._meterHistorySummary;
      await this._recordMeterDiagnostic(
        "INFO",
        "meter_history_request_success",
        `Meter history loaded · Entity: ${summary.entity_id || "none"} · Points: ${summary.point_count}`,
      );
    } catch (error) {
      if (requestToken !== this._meterHistoryRequestToken) return;
      this._meterPowerHistory = { date: null, points: [] };
      this._meterHistorySummary = {
        entity_id: entityId,
        success: false,
        date: null,
        point_count: 0,
        error: "history_unavailable",
      };
      const details = this._websocketErrorDetails(error);
      await this._recordMeterDiagnostic(
        "ERROR",
        "meter_history_request_failed",
        `Meter history failed · Entity: ${entityId || "none"} · Error: ${details.code}: ${details.message}`,
      );
    }
    if (this.host.querySelector(".price-chart")) this.renderPriceChart();
  }

  _appendMeterPowerPoint(point) {
    if (!point?.timestamp) return;
    if (point.entity_id && point.entity_id !== this._meterState?.power_entity) return;
    const timestamp = new Date(point.timestamp);
    if (Number.isNaN(timestamp.getTime())) return;
    const date = timestamp.toLocaleDateString("sv-SE");
    const currentDate = this._meterPowerHistory.date || date;
    if (date !== currentDate) return;
    const points = Array.isArray(this._meterPowerHistory.points)
      ? [...this._meterPowerHistory.points]
      : [];
    const next = {
      timestamp: timestamp.toISOString(),
      import_kw: Number(point.import_kw) || 0,
      export_kw: Number(point.export_kw) || 0,
    };
    const index = points.findIndex((item) => item.timestamp === next.timestamp);
    if (index >= 0) points[index] = next;
    else points.push(next);
    points.sort((left, right) => new Date(left.timestamp) - new Date(right.timestamp));
    this._meterPowerHistory = { date: currentDate, points };
    if (this.host.querySelector(".price-chart")) this.renderPriceChart();
  }

  _periodCustomerPrice(period) {
    const value = Number(period.customer_price ?? period.price);
    return Number.isFinite(value) ? value * 100 : null;
  }

  _comparisonPrice(period) {
    const spotExVat = Number(period.spot_price_ex_vat);
    const fallbackSpot = Number(period.price);
    const spot = Number.isFinite(spotExVat) ? spotExVat : fallbackSpot;
    if (!Number.isFinite(spot)) return null;
    let subtotal = spot;
    if (this._priceComparisonVisible.electricity) {
      const electricity = Number(period.electricity_cost_ex_vat);
      if (Number.isFinite(electricity)) subtotal += electricity;
    }
    if (this._priceComparisonVisible.grid) {
      const grid = Number(period.grid_cost_ex_vat);
      if (Number.isFinite(grid)) subtotal += grid;
    }
    return subtotal * 125;
  }

  _hasGridPriceData() {
    return this.priceData.periods.length > 0
      && this.priceData.periods.every((period) => Number.isFinite(Number(period.grid_cost_ex_vat)));
  }

  _updatePriceComparisonControls() {
    const control = this.host.querySelector('[data-price-layer="grid"]');
    const input = control?.querySelector("[data-price-toggle]");
    if (!control || !input) return;
    const available = this._hasGridPriceData();
    input.disabled = !available;
    control.title = available ? "Visa elnätskostnad i prisjämförelsen" : "Elnätspris saknas";
    control.classList.toggle("is-disabled", !available);
    if (!available) {
      this._priceComparisonVisible.grid = false;
      input.checked = false;
    }
  }

  updatePriceSummary() {
    const periods = Array.isArray(this.priceSnapshot?.periods)
      ? this.priceSnapshot.periods
      : [];
    const now = new Date();
    const currentPeriod = periods.find((period) => {
      const start = new Date(period.start);
      const end = new Date(period.end);
      return start <= now && now < end;
    });
    const comparison = periods.map((period) => ({ period, value: this._comparisonPrice(period) }))
      .filter((item) => Number.isFinite(item.value));
    const lowestItem = comparison.reduce((result, item) => (
      !result || item.value < result.value ? item : result
    ), null);
    const highestItem = comparison.reduce((result, item) => (
      !result || item.value > result.value ? item : result
    ), null);
    const current = currentPeriod && Number.isFinite(this._comparisonPrice(currentPeriod))
      ? { ...currentPeriod, price: this._comparisonPrice(currentPeriod) / 100 }
      : null;
    const lowest = lowestItem ? { ...lowestItem.period, price: lowestItem.value / 100 } : null;
    const highest = highestItem ? { ...highestItem.period, price: highestItem.value / 100 } : null;
    const average = comparison.length
      ? { price: comparison.reduce((sum, item) => sum + item.value, 0) / comparison.length / 100 }
      : null;
    const prices = periods.map((period) => this._periodCustomerPrice(period)).filter(Number.isFinite);
    const colorBands = priceColorBands(prices);
    const currentIndex = periods.indexOf(currentPeriod);
    const currentCategory = currentIndex >= 0
      ? priceCategory(prices[currentIndex], colorBands)
      : null;
    const analysis = this.host.querySelector("[data-price-analysis]");
    if (analysis) {
      const analysisPeriods = periods.map((period) => ({
        ...period,
        price: this._periodCustomerPrice(period) / 100,
      }));
      const upcoming = renderPriceAnalysis(buildPriceAnalysisFacts(analysisPeriods, currentIndex));
      analysis.replaceChildren();
      if (upcoming.status) {
        const status = document.createElement("span");
        status.className = `price-analysis-status ${upcoming.category}`;
        status.textContent = upcoming.status;
        const separator = document.createElement("span");
        separator.className = "price-analysis-separator";
        separator.textContent = " · ";
        const forecast = document.createElement("span");
        forecast.className = "price-analysis-forecast";
        forecast.textContent = upcoming.forecast;
        analysis.append(status, separator, forecast);
      } else {
        const forecast = document.createElement("span");
        forecast.className = "price-analysis-forecast";
        forecast.textContent = upcoming.forecast;
        analysis.append(forecast);
      }
    }
    const summary = { current, lowest, highest, average };
    for (const key of ["current", "lowest", "highest", "average"]) {
      const value = Number(summary[key]?.price) * 100;
      const element = this.host.querySelector(`[data-price="${key}"]`);
      if (element) {
        element.textContent = Number.isFinite(value) ? this.formatPrice(value) : "–";
        if (key === "current") {
          element.classList.remove("cheap", "normal", "expensive");
          if (currentCategory) element.classList.add(currentCategory);
        }
      }
      const time = this.host.querySelector(`[data-time="${key}"]`);
      const period = summary[key];
      if (time) {
        time.textContent = period?.start && period?.end
          ? `${this.formatTime(new Date(period.start))}–${this.formatTime(new Date(period.end))}`
          : "";
      }
    }
  }

  prepareMeterDisplayPoints(points) {
    const latestByTimestamp = new Map();
    points.forEach((point) => {
      const timestamp = new Date(point.timestamp).getTime();
      const importKw = Number(point.import_kw);
      const exportKw = Number(point.export_kw);
      if (!Number.isFinite(timestamp)) return;
      latestByTimestamp.set(timestamp, {
        timestamp,
        raw_timestamp: point.raw_timestamp ?? null,
        import_kw: Number.isFinite(importKw) ? importKw : null,
        export_kw: Number.isFinite(exportKw) ? exportKw : null,
        gap_before: Boolean(point.gap_before),
      });
    });
    return [...latestByTimestamp.values()].sort((a, b) => (
      a.timestamp - b.timestamp
    ));
  }

  buildCanonicalMeterPoints(points, dayStart, dayEnd, slotMs = 5 * 60 * 1000, maxDistanceMs = 2.5 * 60 * 1000) {
    return buildCanonicalMeterPoints(points, dayStart, dayEnd, slotMs, maxDistanceMs);
  }

  buildMeterDisplaySegments(points, key) {
    const segments = [];
    let start = null;
    points.forEach((point, index) => {
      const active = Number(point[key]) > 0;
      if (active && start === null) start = index;
      if ((!active || index === points.length - 1) && start !== null) {
        const end = active && index === points.length - 1 ? index : index - 1;
        const from = start > 0 && points[start - 1][key] === 0 && !points[start].gap_before
          ? start - 1
          : start;
        const to = end < points.length - 1 && points[end + 1][key] === 0 && !points[end + 1].gap_before
          ? end + 1
          : end;
        if (to - from > 0) segments.push(points.slice(from, to + 1));
        start = null;
      }
    });
    return segments;
  }

  buildMeterDisplayCoordinates(segment, key, x, meterY) {
    return segment.map((point) => ({
      x: x(point.timestamp),
      y: meterY(point[key]),
    }));
  }

  buildMeterDisplayPathSegments(coordinates) {
    return buildMonotoneCubicSegments(coordinates);
  }

  buildMeterDisplayGeometry(points, key, x, meterY) {
    return this.buildMeterDisplaySegments(points, key).map((segment) => {
      const coordinates = this.buildMeterDisplayCoordinates(segment, key, x, meterY);
      return {
        coordinates,
        pathSegments: this.buildMeterDisplayPathSegments(coordinates),
      };
    });
  }

  meterDisplayYAt(geometry, timestamp, x) {
    const targetX = x(timestamp);
    for (const segment of Array.isArray(geometry) ? geometry : []) {
      for (const pathSegment of segment.pathSegments) {
        const { start, control1, control2, end } = pathSegment;
        const minX = Math.min(start.x, end.x);
        const maxX = Math.max(start.x, end.x);
        if (targetX < minX || targetX > maxX) continue;
        if (end.x === start.x) return start.y;
        let low = 0;
        let high = 1;
        for (let iteration = 0; iteration < 24; iteration += 1) {
          const progress = (low + high) / 2;
          const inverse = 1 - progress;
          const currentX = inverse * inverse * inverse * start.x
            + 3 * inverse * inverse * progress * control1.x
            + 3 * inverse * progress * progress * control2.x
            + progress * progress * progress * end.x;
          if (currentX < targetX) low = progress;
          else high = progress;
        }
        const progress = (low + high) / 2;
        const inverse = 1 - progress;
        return inverse * inverse * inverse * start.y
          + 3 * inverse * inverse * progress * control1.y
          + 3 * inverse * progress * progress * control2.y
          + progress * progress * progress * end.y;
      }
    }
    return null;
  }

  buildSmoothMeterPath(segment, key, x, meterY) {
    if (segment.length < 2) return "";
    const coordinates = this.buildMeterDisplayCoordinates(segment, key, x, meterY);
    const pathSegments = this.buildMeterDisplayPathSegments(coordinates);
    const first = coordinates[0];
    const path = [`M ${first.x} ${first.y}`];
    pathSegments.forEach(({ control1, control2, end }) => {
      path.push(`C ${control1.x} ${control1.y} ${control2.x} ${control2.y} ${end.x} ${end.y}`);
    });
    return path.join(" ");
  }

  meterObstacleTop(points, key, textLeft, textRight, x, meterY) {
    let obstacleTop = Infinity;
    const geometry = this.buildMeterDisplayGeometry(points, key, x, meterY);
    const cubicPoint = (start, control1, control2, end, progress) => {
      const inverse = 1 - progress;
      return {
        x: inverse * inverse * inverse * start.x
          + 3 * inverse * inverse * progress * control1.x
          + 3 * inverse * progress * progress * control2.x
          + progress * progress * progress * end.x,
        y: inverse * inverse * inverse * start.y
          + 3 * inverse * inverse * progress * control1.y
          + 3 * inverse * progress * progress * control2.y
          + progress * progress * progress * end.y,
      };
    };
    geometry.forEach(({ pathSegments }) => {
      pathSegments.forEach(({ start, control1, control2, end }) => {
        const steps = Math.max(1, Math.ceil(Math.abs(end.x - start.x) / 3));
        for (let step = 0; step <= steps; step += 1) {
          const point = cubicPoint(start, control1, control2, end, step / steps);
          if (point.x >= textLeft && point.x <= textRight) obstacleTop = Math.min(obstacleTop, point.y);
        }
      });
    });
    return Number.isFinite(obstacleTop) ? obstacleTop : null;
  }

  renderPriceChart() {
    const chart = this.host.querySelector(".price-chart");
    if (!chart) return;

    if (!this.priceData.periods.length) {
      const legend = this.host.querySelector("[data-meter-legend]");
      if (legend) legend.hidden = true;
      const message = this.priceData.error === "missing_integration"
        ? "<strong>Ingen Nord Pool-sensor hittades.</strong><span>Lägg till Nord Pool i Home Assistant för att visa dagens elpris.</span>"
        : "<strong>Dagens Nord Pool-priser kunde inte hämtas.</strong>";
      chart.innerHTML = `<div class="empty-chart">${message}</div>`;
      return;
    }

    const periods = this.priceData.periods;
    this._updatePriceComparisonControls();
    const prices = periods.map((period) => this._periodCustomerPrice(period));
    this._chartBarPrices = prices;
    const average = prices.length
      ? prices.reduce((sum, price) => sum + price, 0) / prices.length
      : 0;
    const finitePrices = prices.filter(Number.isFinite);
    const minimum = finitePrices.length ? Math.min(...finitePrices) : 0;
    const maximum = finitePrices.length ? Math.max(...finitePrices) : 0;
    const range = maximum - minimum;
    const colorBands = priceColorBands(prices);
    const priceRanks = new Map();
    colorBands?.sorted.forEach((price, index) => priceRanks.set(price, index + 1));
    this._chartTooltipDetails = new Map();
    const width = 960;
    const height = 350;
    const plot = { left: 42, right: 8, top: 42, bottom: 30 };
    const plotWidth = width - plot.left - plot.right;
    const plotHeight = height - plot.top - plot.bottom;
    const valueRange = range || 1;
    const y = (price) => plot.top + ((maximum - price) / valueRange) * plotHeight;
    const zeroY = Math.max(plot.top, Math.min(plot.top + plotHeight, y(0)));
    const firstStart = new Date(periods[0].start);
    const dayStart = new Date(firstStart.getFullYear(), firstStart.getMonth(), firstStart.getDate());
    const dayEnd = new Date(dayStart);
    dayEnd.setDate(dayEnd.getDate() + 1);
    const dayDuration = dayEnd.getTime() - dayStart.getTime();
    this._chartGeometry = {
      width,
      height,
      plotLeft: plot.left,
      plotTop: plot.top,
      plotWidth,
      plotHeight,
      dayStartMs: dayStart.getTime(),
      dayDuration,
    };
    const now = new Date();
    const currentPeriod = periods.find((period) => {
      const start = new Date(period.start);
      const end = new Date(period.end);
      return start <= now && now < end;
    });
    const lowestPeriod = periods.reduce((lowest, period) => (
      this._periodCustomerPrice(period) < this._periodCustomerPrice(lowest) ? period : lowest
    ), periods[0]);
    const highestPeriod = periods.reduce((highest, period) => (
      this._periodCustomerPrice(period) > this._periodCustomerPrice(highest) ? period : highest
    ), periods[0]);
    const markerGroups = new Map();
    [[currentPeriod, "Nu"], [lowestPeriod, "Lägst"], [highestPeriod, "Högst"]]
      .forEach(([period, label]) => {
        if (!period) return;
        const key = period.start;
        const group = markerGroups.get(key) || { period, labels: [] };
        group.labels.push(label);
        markerGroups.set(key, group);
      });
    const x = (timestamp) => plot.left + ((new Date(timestamp).getTime() - dayStart.getTime()) / dayDuration) * plotWidth;
    const barGeometry = periods.map((period, index) => {
      const price = prices[index];
      return {
        period,
        startX: x(period.start),
        endX: x(period.end),
        top: price >= 0 ? y(price) : zeroY,
      };
    });
    const meterPoints = Array.isArray(this._meterPowerHistory?.points)
      ? this._meterPowerHistory.points.filter((point) => {
        const timestamp = new Date(point.timestamp).getTime();
        return Number.isFinite(timestamp) && timestamp >= dayStart.getTime() && timestamp < dayEnd.getTime();
      })
      : [];
    this._meterTooltipPoints = meterPoints;
    const meterCanonicalPoints = this.buildCanonicalMeterPoints(meterPoints, dayStart, dayEnd);
    this._meterCanonicalPoints = meterCanonicalPoints;
    this._meterCanonicalPointMap = new Map(
      meterCanonicalPoints
        .filter((point) => point.raw_timestamp !== null)
        .map((point) => [point.timestamp, point]),
    );
    const meterDisplayPoints = this.prepareMeterDisplayPoints(meterCanonicalPoints);
    const meterMaximum = Math.max(
      0,
      ...meterPoints.flatMap((point) => [Number(point.import_kw), Number(point.export_kw)])
        .filter(Number.isFinite),
    );
    const meterBase = meterMaximum || 1;
    const meterMagnitude = 10 ** Math.floor(Math.log10(meterBase / 4));
    const meterNormalized = (meterBase / 4) / meterMagnitude;
    const meterStepFactor = meterNormalized <= 1 ? 1 : meterNormalized <= 2 ? 2 : meterNormalized <= 5 ? 5 : 10;
    const meterStep = meterStepFactor * meterMagnitude;
    const meterRange = Math.ceil(meterBase / meterStep) * meterStep;
    const meterY = (value) => plot.top + plotHeight - (Math.max(0, Number(value) || 0) / meterRange) * plotHeight;
    const meterLinesFor = (key, className, visible) => visible
      ? this.buildMeterDisplaySegments(meterDisplayPoints, key)
        .map((segment) => `<path class="${className}" d="${this.buildSmoothMeterPath(segment, key, x, meterY)}" />`)
        .join("")
      : "";
    const meterDisplayGeometry = {
      import_kw: this.buildMeterDisplayGeometry(meterDisplayPoints, "import_kw", x, meterY),
      export_kw: this.buildMeterDisplayGeometry(meterDisplayPoints, "export_kw", x, meterY),
    };
    const meterLines = [
      meterLinesFor("import_kw", "chart-meter-import", this._meterPowerVisible.import),
      meterLinesFor("export_kw", "chart-meter-export", this._meterPowerVisible.export),
    ].join("");
    const meterVisible = meterPoints.length > 0 && (this._meterPowerVisible.import || this._meterPowerVisible.export);
    const meterGridLevels = Array.from({ length: Math.round(meterRange / meterStep) + 1 }, (_, index) => index * meterStep);
    const meterGrid = meterVisible
      ? meterGridLevels.map((level) => `<line class="chart-meter-gridline" x1="${plot.left}" y1="${meterY(level)}" x2="${width - plot.right}" y2="${meterY(level)}" />
         <text class="chart-meter-label" text-anchor="start" x="8" y="${meterY(level) + 4}">${this._formatNumber(level)} kW</text>`).join("")
      : "";
    const meterPointAt = (timestamp) => meterPoints.reduce((latest, point) => (
      new Date(point.timestamp).getTime() <= timestamp ? point : latest
    ), null);
    periods.forEach((period, index) => {
      const price = prices[index];
      const category = priceCategory(price, colorBands);
      const colorDetails = priceColorDetails(
        price,
        colorBands,
        colorBands ? priceRanks.get(price) : 1,
        periods.length,
      );
      this._chartTooltipDetails.set(index, {
        ...colorDetails,
        spot_price_ex_vat: Number(period.spot_price_ex_vat) * 100,
        electricity_cost_ex_vat: Number.isFinite(Number(period.electricity_cost_ex_vat))
          ? Number(period.electricity_cost_ex_vat) * 100
          : null,
        subtotal_ex_vat: Number(period.subtotal_ex_vat) * 100,
        vat: Number(period.vat) * 100,
        customer_price: Number(period.customer_price) * 100,
        ...(meterPointAt(new Date(period.start).getTime()) ? {
          import_kw: meterPointAt(new Date(period.start).getTime()).import_kw,
          export_kw: meterPointAt(new Date(period.start).getTime()).export_kw,
        } : {}),
      });
    });
    const bars = this._spotBarsVisible ? periods.map((period, index) => {
      const price = prices[index];
      const top = price >= 0 ? y(price) : zeroY;
      const bottom = price >= 0 ? zeroY : y(price);
      const category = priceCategory(price, colorBands);
      const start = new Date(period.start);
      const end = new Date(period.end);
      const startX = x(period.start);
      const barWidth = ((end.getTime() - start.getTime()) / dayDuration) * plotWidth;
      return `<rect class="chart-bar ${category}" data-index="${index}" x="${startX}" y="${top}" width="${Math.max(1, barWidth - 1)}" height="${Math.max(1, bottom - top)}" rx="1" />`;
    }).join("") : "";
    const markerMinY = 18;
    const markerLayouts = this._spotBarsVisible ? [...markerGroups.entries()].map(([, group]) => {
      const markerX = (x(group.period.start) + x(group.period.end)) / 2;
      const label = group.labels.join(" • ");
      const labelWidth = Math.max(16, label.length * 8.5);
      const placeRight = markerX + labelWidth / 2 > width - 4;
      const placeLeft = markerX - labelWidth / 2 < 4;
      const textX = placeRight ? markerX - 4 : placeLeft ? markerX + 4 : markerX;
      const textAnchor = placeRight ? "end" : placeLeft ? "start" : "middle";
      const textLeft = textAnchor === "start" ? textX : textAnchor === "end" ? textX - labelWidth : textX - labelWidth / 2;
      const textRight = textAnchor === "start" ? textX + labelWidth : textAnchor === "end" ? textX : textX + labelWidth / 2;
      const coveredBars = barGeometry.filter((bar) => bar.endX > textLeft && bar.startX < textRight);
      const highestCoveredTop = coveredBars.length
        ? Math.min(...coveredBars.map((bar) => bar.top))
        : plot.top + plotHeight;
      const averageLineY = y(average);
      const obstacleTops = [highestCoveredTop];
      if (this._averageLineVisible) obstacleTops.push(averageLineY);
      if (this._meterPowerVisible.import) {
        const importTop = this.meterObstacleTop(
          meterDisplayPoints,
          "import_kw",
          textLeft,
          textRight,
          x,
          meterY,
        );
        if (importTop !== null) obstacleTops.push(importTop);
      }
      if (this._meterPowerVisible.export) {
        const exportTop = this.meterObstacleTop(
          meterDisplayPoints,
          "export_kw",
          textLeft,
          textRight,
          x,
          meterY,
        );
        if (exportTop !== null) obstacleTops.push(exportTop);
      }
      const highestObstacleY = Math.min(...obstacleTops);
      return {
        label,
        markerX,
        textX,
        textAnchor,
        textLeft,
        textRight,
        maxY: highestObstacleY - 8,
        y: Math.max(markerMinY, highestObstacleY - 8),
      };
    }) : [];
    const markerHeight = 16;
    const markerGap = 4;
    const markerLayoutsByHeight = [...markerLayouts].sort((left, right) => left.y - right.y);
    for (let index = 0; index < markerLayoutsByHeight.length; index += 1) {
      const current = markerLayoutsByHeight[index];
      for (let previousIndex = 0; previousIndex < index; previousIndex += 1) {
        const previous = markerLayoutsByHeight[previousIndex];
        const horizontalOverlap = current.textLeft < previous.textRight && current.textRight > previous.textLeft;
        const verticalOverlap = current.y - markerHeight < previous.y + markerGap;
        if (!horizontalOverlap || !verticalOverlap) continue;
        const upperY = previous.y - markerHeight - markerGap;
        const lowerY = previous.y + markerHeight + markerGap;
        current.y = upperY >= markerMinY ? upperY : Math.min(lowerY, current.maxY);
      }
    }
    const priceMarkers = markerLayouts.map((marker) => `
      <text class="price-marker-label" text-anchor="${marker.textAnchor}" x="${marker.textX}" y="${marker.y}">${marker.label}</text>`).join("");
    const hourLabels = Array.from({ length: 24 }, (_, hour) => {
      const hourDate = new Date(dayStart);
      hourDate.setHours(hourDate.getHours() + hour);
      return `<text class="chart-label" text-anchor="middle" x="${x(hourDate)}" y="${height - 8}">${String(hour).padStart(2, "0")}</text>`;
    }).join("");
    const legend = this.host.querySelector("[data-meter-legend]");
    if (legend) legend.hidden = periods.length === 0 && meterPoints.length === 0;
    this._chartHoverGeometry = {
      x,
      y,
      meterY,
      meterDisplayY: (key, timestamp) => this.meterDisplayYAt(meterDisplayGeometry[key], timestamp, x),
    };
    chart.innerHTML = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Dagens elpris i 15-minutersperioder">
      <line class="chart-axis" x1="${plot.left}" y1="${zeroY}" x2="${width - plot.right}" y2="${zeroY}" />
      ${meterGrid}
      ${bars}
      ${meterLines}
      ${this._averageLineVisible ? `<line class="chart-average" x1="${plot.left}" y1="${y(average)}" x2="${width - plot.right}" y2="${y(average)}" />` : ""}
      ${priceMarkers}
      <g class="chart-hover-markers" aria-hidden="true"></g>
      ${hourLabels}
    </svg><div class="chart-tooltip" hidden></div>`;
    this.bindChartTooltips();
    this.autoScrollToNow(chart, x(now), this.priceSnapshot?.date, currentPeriod);
  }

  autoScrollToNow(chart, nowX, date, currentPeriod) {
    if (!date || !currentPeriod || this._autoScrolledDate === date) return;
    if (!window.matchMedia("(max-width: 600px)").matches) return;
    requestAnimationFrame(() => {
      if (chart.scrollWidth <= chart.clientWidth) return;
      const scale = chart.scrollWidth / 960;
      const targetX = nowX * scale;
      const desiredPosition = chart.clientWidth * 0.33;
      chart.scrollLeft = Math.max(
        0,
        Math.min(
          chart.scrollWidth - chart.clientWidth,
          targetX - desiredPosition,
        ),
      );
      this._autoScrolledDate = date;
    });
  }

  _buildVisibleTooltipRows(comparisonPrice, details) {
    const rows = [];
    if (this._spotBarsVisible && Number.isFinite(comparisonPrice)) {
      rows.push(`<span class="tooltip-value">Spotpris: ${this.formatPrice(comparisonPrice)}</span>`);
    }
    if (this._meterPowerVisible.import && Number.isFinite(details?.import_kw)) {
      rows.push(`<span class="tooltip-value tooltip-meter-import">Import: ${this._formatNumber(details.import_kw)} kW</span>`);
    }
    if (this._meterPowerVisible.export && Number.isFinite(details?.export_kw)) {
      rows.push(`<span class="tooltip-value tooltip-meter-export">Export: ${this._formatNumber(details.export_kw)} kW</span>`);
    }
    return rows.join("");
  }

  _meterPointAtNearest(timestamp) {
    return nearestMeterPoint(this._meterTooltipPoints, timestamp);
  }

  _meterCanonicalPointAt(timestamp) {
    const timestampMs = new Date(timestamp).getTime();
    return this._meterCanonicalPointMap.get(timestampMs) || null;
  }

  bindChartTooltips() {
    const chart = this.host.querySelector(".price-chart");
    const svg = this.host.querySelector(".chart-svg");
    const tooltip = this.host.querySelector(".chart-tooltip");
    if (!chart || !svg || !tooltip || !this._chartGeometry) return;
    const periodAt = (clientX) => {
      const geometry = this._chartGeometry;
      const bounds = svg.getBoundingClientRect();
      const viewX = ((clientX - bounds.left) / bounds.width) * geometry.width;
      if (viewX < geometry.plotLeft || viewX > geometry.plotLeft + geometry.plotWidth) return null;
      const timestamp = geometry.dayStartMs
        + ((viewX - geometry.plotLeft) / geometry.plotWidth) * geometry.dayDuration;
      const tooltipTimestamp = snapTooltipTimestamp(
        timestamp,
        geometry.dayStartMs,
        geometry.dayStartMs + geometry.dayDuration,
      );
      const index = this.priceData.periods.findIndex((period) => {
        const start = new Date(period.start).getTime();
        const end = new Date(period.end).getTime();
        return start <= tooltipTimestamp && tooltipTimestamp < end;
      });
      return index < 0 ? null : { period: this.priceData.periods[index], index, tooltipTimestamp };
    };
    const insidePlot = (clientX, clientY) => {
      const geometry = this._chartGeometry;
      const bounds = svg.getBoundingClientRect();
      const viewX = ((clientX - bounds.left) / bounds.width) * geometry.width;
      const viewY = ((clientY - bounds.top) / bounds.height) * geometry.height;
      return viewX >= geometry.plotLeft
        && viewX <= geometry.plotLeft + geometry.plotWidth
        && viewY >= geometry.plotTop
        && viewY <= geometry.plotTop + geometry.plotHeight;
    };
    const show = (period, event, tooltipTimestamp) => {
      const time = this.formatTime(new Date(tooltipTimestamp));
      const comparisonPrice = this._comparisonPrice(period);
      const value = this._spotBarsVisible && Number.isFinite(comparisonPrice)
        ? `${this.formatPrice(comparisonPrice)} öre/kWh`
        : "";
      const index = this.priceData.periods.indexOf(period);
      const canonicalMeterPoint = this._meterCanonicalPointAt(tooltipTimestamp);
      const rawMeterPoint = this._meterPointAtNearest(tooltipTimestamp);
      const meterValue = (key) => canonicalMeterPoint && Number.isFinite(Number(canonicalMeterPoint[key]))
        ? Number(canonicalMeterPoint[key])
        : null;
      const barPrice = this._chartBarPrices?.[index];
      const hoverSnapshot = {
        hoverTime: tooltipTimestamp,
        meterSampleTime: canonicalMeterPoint ? canonicalMeterPoint.timestamp : null,
        priceBarValue: barPrice ?? null,
        importValue: meterValue("import_kw"),
        exportValue: meterValue("export_kw"),
        pvValue: null,
        loadValue: null,
        chargeValue: null,
        dischargeValue: null,
      };
      const baseDetails = this._chartTooltipDetails?.get(index) || {};
      const details = this._debugEnabled ? { ...baseDetails } : null;
      if (details) {
        if (!rawMeterPoint || !Number.isFinite(Number(rawMeterPoint.import_kw))) delete details.import_kw;
        else details.import_kw = Number(rawMeterPoint.import_kw);
        if (!rawMeterPoint || !Number.isFinite(Number(rawMeterPoint.export_kw))) delete details.export_kw;
        else details.export_kw = Number(rawMeterPoint.export_kw);
      }
      const tooltipRows = this._buildVisibleTooltipRows(comparisonPrice, {
        import_kw: hoverSnapshot.importValue,
        export_kw: hoverSnapshot.exportValue,
      });
      const tooltipText = details ? createPriceDebugText({ time, value, details }) : "";
      if (details) {
        tooltip.textContent = tooltipText;
      } else {
        tooltip.innerHTML = `<strong>${time}</strong>${tooltipRows}`;
      }
      this._chartDebugCopyText = tooltipText;
      const hoverMarkers = svg.querySelector(".chart-hover-markers");
      const hoverGeometry = this._chartHoverGeometry;
      if (hoverMarkers && hoverGeometry) {
        const priceMarkerX = hoverGeometry.x(hoverSnapshot.hoverTime);
        const meterMarkerX = Number.isFinite(hoverSnapshot.meterSampleTime)
          ? hoverGeometry.x(hoverSnapshot.meterSampleTime)
          : null;
        const markers = [];
        if (this._spotBarsVisible && Number.isFinite(hoverSnapshot.priceBarValue)) {
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-spot" cx="${priceMarkerX}" cy="${hoverGeometry.y(hoverSnapshot.priceBarValue)}" r="4" />`);
        }
        const importDisplayY = meterMarkerX === null
          ? null
          : hoverGeometry.meterDisplayY("import_kw", hoverSnapshot.meterSampleTime);
        if (this._meterPowerVisible.import && meterMarkerX !== null && Number.isFinite(hoverSnapshot.importValue) && hoverSnapshot.importValue > 0 && Number.isFinite(importDisplayY)) {
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-import" cx="${meterMarkerX}" cy="${importDisplayY}" r="4" />`);
        }
        const exportDisplayY = meterMarkerX === null
          ? null
          : hoverGeometry.meterDisplayY("export_kw", hoverSnapshot.meterSampleTime);
        if (this._meterPowerVisible.export && meterMarkerX !== null && Number.isFinite(hoverSnapshot.exportValue) && hoverSnapshot.exportValue > 0 && Number.isFinite(exportDisplayY)) {
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-export" cx="${meterMarkerX}" cy="${exportDisplayY}" r="4" />`);
        }
        hoverMarkers.innerHTML = markers.join("");
      }
      tooltip.classList.toggle("debug-tooltip", Boolean(details));
      tooltip.title = "";
      tooltip.hidden = false;
      const obstacles = [
        ...svg.querySelectorAll(".chart-hover-marker, .price-marker-label"),
      ];
      positionChartTooltip(chart, tooltip, event.clientX, event.clientY, obstacles, this._tooltipOrbit);
    };
    const clearHoverMarkers = () => {
      const hoverMarkers = svg.querySelector(".chart-hover-markers");
      if (hoverMarkers) hoverMarkers.replaceChildren();
    };
    const hasVisibleTooltipLayer = this._spotBarsVisible
      || this._meterPowerVisible.import
      || this._meterPowerVisible.export;
    svg.addEventListener("mousemove", (event) => {
      if (event.sourceCapabilities?.firesTouchEvents) return;
      if (!hasVisibleTooltipLayer) {
        clearHoverMarkers();
        tooltip.hidden = true;
        return;
      }
      const period = periodAt(event.clientX);
      if (period && insidePlot(event.clientX, event.clientY)) {
        show(period.period, event, period.tooltipTimestamp);
      } else {
        clearHoverMarkers();
        if (!this._pinnedPeriod) tooltip.hidden = true;
      }
    });
    svg.addEventListener("mouseleave", () => {
      clearHoverMarkers();
      if (!this._pinnedPeriod) tooltip.hidden = true;
    });
    const clearPinnedTooltip = () => {
      this._pinnedPeriod = null;
      tooltip.hidden = true;
    };
    let lastChartDebugCopyAt = 0;
    const copyChartDebugText = async () => {
      if (!this._debugEnabled) return;
      const now = performance.now();
      if (now - lastChartDebugCopyAt < 500) return;
      lastChartDebugCopyAt = now;
      const copyText = this._chartDebugCopyText;
      void this._recordDiagnostic("price", "INFO", "chart_debug_copy_clicked", "Price chart debug bar clicked");
      void this._recordDiagnostic("price", "INFO", "chart_debug_copy_text_length", `Chart debug copy text length: ${copyText.length}`);
      if (!copyText) return;
      try {
        await this._copyText(copyText);
        void this._recordDiagnostic("price", "INFO", "chart_debug_copy_success", "Price chart debug text copied");
      } catch {
        // Copy failures are intentionally not logged beyond the requested diagnostics.
      }
    };
    svg.addEventListener("click", (event) => {
      if (!this._debugEnabled || !hasVisibleTooltipLayer || !insidePlot(event.clientX, event.clientY)) return;
      const hit = periodAt(event.clientX);
      if (!hit) return;
      show(hit.period, event, hit.tooltipTimestamp);
      void copyChartDebugText();
    });
    chart.addEventListener("touchstart", (event) => {
      const touch = event.touches[0];
      if (!touch) return;
      this._chartTouch = {
        x: touch.clientX,
        y: touch.clientY,
        scrollLeft: chart.scrollLeft,
        moved: false,
      };
    }, { passive: true });
    chart.addEventListener("touchmove", (event) => {
      const state = this._chartTouch;
      const touch = event.touches[0];
      if (!state || !touch) return;
      const moved = Math.abs(touch.clientX - state.x) > 8
        || Math.abs(touch.clientY - state.y) > 8
        || Math.abs(chart.scrollLeft - state.scrollLeft) > 3;
      if (moved && !state.moved) {
        state.moved = true;
        if (this._pinnedPeriod) clearPinnedTooltip();
      }
    }, { passive: true });
    chart.addEventListener("touchend", (event) => {
      const state = this._chartTouch;
      const touch = event.changedTouches[0];
      this._chartTouch = null;
      if (!state || !touch) return;
      if (state.moved || Math.abs(chart.scrollLeft - state.scrollLeft) > 3) return;
      if (!hasVisibleTooltipLayer || !insidePlot(touch.clientX, touch.clientY)) {
        clearPinnedTooltip();
        return;
      }
      const hit = periodAt(touch.clientX);
      if (!hit) {
        clearPinnedTooltip();
        return;
      }
      this._pinnedPeriod = hit.period;
      show(hit.period, touch, hit.tooltipTimestamp);
      void copyChartDebugText();
    }, { passive: true });
    chart.addEventListener("touchcancel", () => {
      this._chartTouch = null;
    }, { passive: true });
    if (this._dismissTooltip) {
      document.removeEventListener("touchstart", this._dismissTooltip);
    }
    this._dismissTooltip = ((event) => {
      if (!this._pinnedPeriod) return;
      const path = event.composedPath?.() || [];
      if (path.includes(this._tooltipChart)) return;
      clearPinnedTooltip();
    });
    this._tooltipChart = chart;
    document.addEventListener("touchstart", this._dismissTooltip, { passive: true });
  }

  formatPrice(value) {
    return value.toLocaleString("sv-SE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  }

  formatTime(value) {
    return value.toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" });
  }
}

export function mountElrakningPanel(host, { version }) {
  console.info(`[Elräkning] frontend ${version} loaded`);
  const panel = new ElrakningPanel(host, version);
  panel.render();
  return panel;
}
