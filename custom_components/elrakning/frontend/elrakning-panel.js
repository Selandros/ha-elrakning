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

function periodsAreContiguous(previous, next) {
  const previousEnd = new Date(previous?.end).getTime();
  const nextStart = new Date(next?.start).getTime();
  return Number.isFinite(previousEnd) && Number.isFinite(nextStart) && previousEnd === nextStart;
}

function contiguousFuturePeriodCount(periods, currentIndex) {
  if (currentIndex < 0 || currentIndex >= periods.length) return 0;
  let count = 1;
  while (currentIndex + count < periods.length
    && periodsAreContiguous(periods[currentIndex + count - 1], periods[currentIndex + count])) {
    count += 1;
  }
  return count;
}

export function buildPriceAnalysisFacts(periods, currentIndex) {
  if (!Array.isArray(periods) || currentIndex < 0 || currentIndex >= periods.length) {
    return null;
  }
  const prices = periods.map((period) => Number(period.price) * 100);
  const bands = priceColorBands(prices);
  const availableFuturePeriods = contiguousFuturePeriodCount(periods, currentIndex);
  const effectiveSearchPeriods = Math.min(24, availableFuturePeriods);
  const usageWindowPeriods = Math.min(8, effectiveSearchPeriods);
  const nowWindow = buildUsageWindow(periods, prices, currentIndex, usageWindowPeriods);
  if (!bands || !nowWindow) return null;
  const categories = prices.map((price) => priceCategory(price, bands));
  const lastStartIndex = Math.min(
    currentIndex + availableFuturePeriods - usageWindowPeriods,
    currentIndex + effectiveSearchPeriods - usageWindowPeriods,
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
  const currentStart = new Date(periods[currentIndex].start);
  const lastStart = new Date(periods[currentIndex + availableFuturePeriods - 1].start);
  const lastEnd = new Date(periods[currentIndex + availableFuturePeriods - 1].end);
  const hasNextDayData = lastStart.toDateString() !== currentStart.toDateString();
  const endsAtDayBoundary = lastEnd.getHours() === 0
    && lastEnd.getMinutes() === 0
    && lastEnd.getSeconds() === 0;
  return {
    currentIndex,
    status: categories[currentIndex],
    currentPrice: prices[currentIndex],
    dailyAverage: bands.average,
    median: bands.median,
    percentile: (prices.filter((price) => price <= prices[currentIndex]).length / prices.length) * 100,
    minimum: bands.minimum,
    maximum: bands.maximum,
    usage_window_minutes: usageWindowPeriods * 15,
    search_horizon_hours: effectiveSearchPeriods * 15 / 60,
    available_future_periods: availableFuturePeriods,
    available_future_minutes: availableFuturePeriods * 15,
    effective_search_horizon_minutes: effectiveSearchPeriods * 15,
    has_full_two_hour_window: availableFuturePeriods >= 8,
    has_full_six_hour_horizon: availableFuturePeriods >= 24,
    crosses_midnight: hasNextDayData,
    has_next_day_data: hasNextDayData,
    ends_at_day_boundary: endsAtDayBoundary,
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

function futureWindowLabel(facts) {
  if (facts.has_full_two_hour_window) return "Nästa 2 h";
  if (facts.ends_at_day_boundary && !facts.has_next_day_data) return "Resten av kvällen";
  if (facts.available_future_minutes % 60 === 0) {
    return `Nästa ${facts.available_future_minutes / 60} h`;
  }
  return "Återstående prisdata";
}

function futureHorizonLabel(facts) {
  if (facts.has_full_six_hour_horizon) return "de närmaste 6 timmarna";
  if (facts.ends_at_day_boundary && !facts.has_next_day_data) return "resten av kvällen";
  if (facts.effective_search_horizon_minutes % 60 === 0) {
    return `de kommande ${facts.effective_search_horizon_minutes / 60} timmarna`;
  }
  return "den återstående prisdatan";
}

export function renderPriceAnalysis(facts) {
  if (!facts) {
    const forecast = "Dagens prisanalys är inte tillgänglig";
    return { category: null, status: "", forecast, sentences: [forecast] };
  }
  const status = {
    cheap: "Billigt pris nu",
    normal: "Normalt pris nu",
    expensive: "Dyrt pris nu",
  }[facts.status];
  const observations = [
    `${futureWindowLabel(facts)}: ${formatAnalysisPrice(facts.now_window.average_price)} i snitt.`,
  ];
  const lateDayFallback = !facts.has_full_two_hour_window
    && facts.ends_at_day_boundary
    && !facts.has_next_day_data;
  if (lateDayFallback) {
    // The remaining evening is already fully described by the first observation.
  } else if (facts.lower_window_significant) {
    observations.push(`Från ${formatAnalysisClock(facts.best_window.start)}: ${formatAnalysisPrice(facts.best_window.average_price)}.`);
  } else if (facts.higher_window_significant) {
    observations.push(`Från ${formatAnalysisClock(facts.highest_window.start)}: ${formatAnalysisPrice(facts.highest_window.average_price)}.`);
  } else {
    observations.push(`Ingen tydligt billigare eller dyrare period finns ${futureHorizonLabel(facts)}.`);
  }
  const sentences = observations.slice(0, 2);
  return { category: facts.status, status, forecast: sentences.join(" "), sentences };
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

export function normalizeMeterValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export const POWER_DISPLAY_THRESHOLD_KW = 0.1;

export function isVisiblePowerValue(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > POWER_DISPLAY_THRESHOLD_KW;
}

export function displayPowerValue(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return Math.abs(numeric) <= POWER_DISPLAY_THRESHOLD_KW ? 0 : numeric;
}

export function buildCanonicalMeterPoints(points, dayStart, dayEnd, slotMs = 5 * 60 * 1000, maxDistanceMs = 2.5 * 60 * 1000) {
  const dayStartMs = new Date(dayStart).getTime();
  const dayEndMs = new Date(dayEnd).getTime();
  const canonical = [];
  let previousSelected = false;
  for (let slotTimestamp = dayStartMs; slotTimestamp < dayEndMs; slotTimestamp += slotMs) {
    const selected = nearestMeterPoint(points, slotTimestamp, maxDistanceMs);
    const importKw = selected ? normalizeMeterValue(selected.import_kw) : null;
    const exportKw = selected ? normalizeMeterValue(selected.export_kw) : null;
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

export function integratePowerHistoryKwh(points, dayStart, dayEnd, now = new Date(), slotMs = 5 * 60 * 1000) {
  const canonical = buildCanonicalMeterPoints(
    (Array.isArray(points) ? points : []).map((point) => ({
      timestamp: point.timestamp,
      import_kw: point.value_kw,
      export_kw: 0,
    })),
    dayStart,
    dayEnd,
    slotMs,
  );
  const nowMs = new Date(now).getTime();
  const samples = canonical.filter((point) => point.raw_timestamp !== null && point.timestamp <= nowMs);
  let energyKwh = 0;
  for (let index = 1; index < samples.length; index += 1) {
    const previous = samples[index - 1];
    const current = samples[index];
    if (current.timestamp - previous.timestamp !== slotMs || current.gap_before) continue;
    if (!Number.isFinite(previous.import_kw) || !Number.isFinite(current.import_kw)) continue;
    energyKwh += ((previous.import_kw + current.import_kw) / 2) * (slotMs / (60 * 60 * 1000));
  }
  return energyKwh;
}

export function buildEnergyBalance(totalKwh, externalKwh) {
  const total = Number.isFinite(totalKwh) ? totalKwh : null;
  const external = Number.isFinite(externalKwh) ? externalKwh : null;
  const local = total !== null && external !== null ? Math.max(total - external, 0) : null;
  return {
    total,
    external,
    local,
    localPercent: total > 0 && local !== null ? local / total * 100 : null,
    externalPercent: total > 0 && external !== null ? external / total * 100 : null,
  };
}

export function buildThresholdClippedSegments(points, key) {
  const segments = [];
  let segment = [];
  const appendSegment = () => {
    if (segment.length >= 2) segments.push(segment);
    segment = [];
  };
  const crossingPoint = (previous, current) => {
    const previousTime = new Date(previous.timestamp).getTime();
    const currentTime = new Date(current.timestamp).getTime();
    const previousValue = normalizeMeterValue(previous[key]);
    const currentValue = normalizeMeterValue(current[key]);
    const denominator = currentValue - previousValue;
    if (!Number.isFinite(previousTime) || !Number.isFinite(currentTime) || !Number.isFinite(denominator) || denominator === 0) return null;
    const ratio = (POWER_DISPLAY_THRESHOLD_KW - previousValue) / denominator;
    if (!Number.isFinite(ratio) || ratio < 0 || ratio > 1) return null;
    return {
      ...current,
      timestamp: previousTime + ratio * (currentTime - previousTime),
      raw_timestamp: null,
      [key]: POWER_DISPLAY_THRESHOLD_KW,
      synthetic: true,
    };
  };
  (Array.isArray(points) ? points : []).forEach((point, index, source) => {
    const value = normalizeMeterValue(point?.[key]);
    if (!Number.isFinite(value)) {
      appendSegment();
      return;
    }
    const previous = source[index - 1];
    const previousValue = normalizeMeterValue(previous?.[key]);
    const previousTime = new Date(previous?.timestamp).getTime();
    const currentTime = new Date(point.timestamp).getTime();
    const contiguous = previous
      && Number.isFinite(previousValue)
      && Number.isFinite(previousTime)
      && Number.isFinite(currentTime)
      && previous.raw_timestamp != null
      && point.raw_timestamp != null
      && currentTime - previousTime === 5 * 60 * 1000
      && !point.gap_before;
    if (!contiguous) {
      appendSegment();
      if (isVisiblePowerValue(value)) segment.push(point);
      return;
    }
    const previousVisible = isVisiblePowerValue(previousValue);
    const currentVisible = isVisiblePowerValue(value);
    if (currentVisible) {
      if (!previousVisible) {
        const crossing = crossingPoint(previous, point);
        if (crossing) segment.push(crossing);
      }
      segment.push(point);
    } else if (previousVisible) {
      const crossing = crossingPoint(previous, point);
      if (crossing) segment.push(crossing);
      appendSegment();
    }
  });
  appendSegment();
  return segments;
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
    this._configurationCardsVisible = true;
    this._mainCards = {
      elhandel: false,
      elnet: false,
      elmatare: false,
      solar: false,
      consumption: false,
      battery: false,
    };
    this._diagnosticEntries = [];
    this._chartTouch = null;
    this._chartDebugCopyText = "";
    this._tooltipOrbit = { angle: null };
    this._priceHeaderLayoutObserver = null;
    this._chartPreferencesReady = false;
    this._meterPowerHistory = { date: null, points: [] };
    this._meterTooltipPoints = [];
    this._meterCanonicalPoints = [];
    this._meterCanonicalPointMap = new Map();
    this._meterHistorySummary = null;
    this._meterHistoryRequestToken = 0;
    this._powerState = null;
    this._powerHistory = { date: null, series: {} };
    this._powerHistoryRequestToken = 0;
    this._powerLivePoints = Object.fromEntries(["solar", "consumption", "charging", "discharging", "soc"].map((key) => [key, new Map()]));
    this._backendHydrationPromise = null;
    this._readyEventUnsubscribePromise = null;
    this._connectionReadyListener = null;
    this._meterPowerVisible = { import: true, export: true };
    this._spotBarsVisible = true;
    this._averageLineVisible = true;
    this._hoverIsolatedLayer = null;
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
            <div class="header-icon-controls" aria-label="Elräkningens kontroller">
              <button type="button" class="header-icon-button config-cards-button${this._configurationCardsVisible ? " active" : ""}" aria-label="Visa konfigurationskort" aria-pressed="${this._configurationCardsVisible}" data-config-cards-toggle><ha-icon icon="mdi:cog-outline"></ha-icon></button>
              <button type="button" class="header-icon-button debug-button${this._debugEnabled ? " active" : ""}" aria-label="Visa diagnostik" aria-pressed="${this._debugEnabled}" data-debug-toggle><ha-icon icon="mdi:bug-outline"></ha-icon></button>
            </div>
          </div>
        </header>

        <section class="price-section" aria-labelledby="price-title">
          <div class="section-heading">
            <div class="price-heading-main">
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
            <button type="button" class="chart-legend-toggle${this._spotBarsVisible ? " active" : ""}" data-chart-layer="spot" aria-pressed="${this._spotBarsVisible}">
              <span class="chart-legend-swatch spot" aria-hidden="true"></span>Pris
            </button>
            <button type="button" class="chart-legend-toggle${this._averageLineVisible ? " active" : ""}" data-chart-layer="average" aria-pressed="${this._averageLineVisible}">
              <span class="chart-legend-swatch average" aria-hidden="true"></span>Snitt
            </button>
            <button type="button" class="chart-legend-toggle${this._meterPowerVisible.import ? " active" : ""}" data-chart-layer="import" aria-pressed="${this._meterPowerVisible.import}">
              <span class="chart-legend-swatch import" aria-hidden="true"></span>Köp
            </button>
            <button type="button" class="chart-legend-toggle${this._meterPowerVisible.export ? " active" : ""}" data-chart-layer="export" aria-pressed="${this._meterPowerVisible.export}">
              <span class="chart-legend-swatch export" aria-hidden="true"></span>Sälj
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview${this._previewLayersVisible.solar ? " active" : ""} solar" data-preview-layer="solar" aria-pressed="${this._previewLayersVisible.solar}">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Sol
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview${this._previewLayersVisible.consumption ? " active" : ""} consumption" data-preview-layer="consumption" aria-pressed="${this._previewLayersVisible.consumption}">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Last
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview${this._previewLayersVisible.charging ? " active" : ""} charging" data-preview-layer="charging" aria-pressed="${this._previewLayersVisible.charging}">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Laddning
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview${this._previewLayersVisible.discharging ? " active" : ""} discharging" data-preview-layer="discharging" aria-pressed="${this._previewLayersVisible.discharging}">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Urladdning
            </button>
          </div>
          <p class="price-analysis" data-price-analysis aria-live="polite">Dagens prisanalys laddas …</p>
        </section>

        <div class="daily-energy-row">
          <section class="card daily-energy-card" data-daily-energy hidden aria-labelledby="daily-energy-title">
            <div class="card-heading">
              <h2 id="daily-energy-title" class="visually-hidden">Dagens energi</h2>
            </div>
            <div class="daily-energy-grid" data-daily-energy-grid></div>
          </section>

          <section class="card soc-card" data-soc-card hidden aria-labelledby="soc-title">
            <div class="card-heading soc-card-heading">
              <h2 id="soc-title" class="visually-hidden">Batteri SOC</h2>
            </div>
            <div class="soc-card-content">
              <div class="soc-chart" data-soc-chart></div>
              <div class="capacity-utilization">
                <h2 class="capacity-utilization-title">Utnyttjande</h2>
                <div data-capacity-utilization></div>
              </div>
            </div>
          </section>
        </div>

        <section class="grid" data-configuration-cards aria-label="Elräkningens konfigurationskort">
          <article class="card" data-provider-card="elhandel" data-config-card-key="elhandel">
            <div class="card-heading">
              <h2>Elhandel</h2>
              <span class="status" data-provider-status></span>
              <label class="main-card-toggle" data-main-card-toggle="elhandel" aria-label="Main"><input type="checkbox"><span class="main-card-track" aria-hidden="true"></span></label>
            </div>
            <p class="provider" data-provider-name="elhandel" hidden></p>
            <div class="provider-summary" data-provider-summary hidden></div>
            <div class="retained-history" data-retained-history hidden>
              <h3>Sparad historik</h3>
              <div data-retained-history-list></div>
            </div>
            <p class="provider-processing-error" data-provider-processing-error hidden>Fel vid senaste hämtning</p>
            <button type="button" class="configuration-control" data-electricity-configure>Konfigurera</button>
            <button type="button" data-provider-source hidden>Vad har vi för data?</button>
            <button type="button" data-greenely-parse-latest hidden>Tolka senaste</button>
          </article>

            <article class="card" data-provider-card="elnet" data-config-card-key="elnet">
            <div class="card-heading">
              <h2>Elnät</h2>
              <span class="status">Ej konfigurerad</span>
              <label class="main-card-toggle" data-main-card-toggle="elnet" aria-label="Main"><input type="checkbox"><span class="main-card-track" aria-hidden="true"></span></label>
            </div>
            <p class="provider" data-provider-name="elnet" hidden></p>
            <button type="button" class="configuration-control">Konfigurera</button>
          </article>

          <article class="card" data-provider-card="elmatare" data-config-card-key="elmatare">
            <div class="card-heading">
              <h2>Elmätare</h2>
              <span class="status" data-meter-status>Ej konfigurerad</span>
              <label class="main-card-toggle" data-main-card-toggle="elmatare" aria-label="Main"><input type="checkbox"><span class="main-card-track" aria-hidden="true"></span></label>
            </div>
            <p class="provider" data-provider-name="elmatare" hidden></p>
            <div class="meter-summary" data-meter-summary hidden></div>
            <button type="button" class="configuration-control" data-meter-configure>Konfigurera</button>
            <button type="button" data-meter-source hidden>Visa mätardata</button>
          </article>

          <article class="card power-card" data-power-card="solar" data-config-card-key="solar">
            <div class="card-heading"><h2>Sol</h2><span class="status" data-power-status="solar">Ej konfigurerad</span><label class="main-card-toggle" data-main-card-toggle="solar" aria-label="Main"><input type="checkbox"><span class="main-card-track" aria-hidden="true"></span></label></div>
            <div class="power-summary" data-power-summary="solar" hidden></div>
            <button type="button" class="configuration-control" data-power-configure="solar">Konfigurera</button>
          </article>

          <article class="card power-card" data-power-card="battery" data-config-card-key="battery">
            <div class="card-heading"><h2>Batteri</h2><span class="status" data-power-status="battery">Ej konfigurerad</span><label class="main-card-toggle" data-main-card-toggle="battery" aria-label="Main"><input type="checkbox"><span class="main-card-track" aria-hidden="true"></span></label></div>
            <div class="power-summary" data-power-summary="battery" hidden></div>
            <button type="button" class="configuration-control" data-power-configure="battery">Konfigurera</button>
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
          <label class="price-filter-toggle meter-invert-toggle">
            <span>Invertera effekt</span>
            <input type="checkbox" data-meter-invert-power>
            <span class="price-filter-track" aria-hidden="true"><span></span></span>
          </label>
          <div class="meter-selectors" data-meter-selectors></div>
          <div class="meter-load-section">
            <h3>Husets last</h3>
            <div class="meter-selectors" data-meter-consumption-selector></div>
          </div>
          <button type="button" data-meter-clear>Rensa elmätare</button>
          <button type="button" data-meter-clear-last>Rensa last</button>
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
      <div class="meter-dialog power-dialog" data-power-dialog hidden role="dialog" aria-modal="true" aria-labelledby="power-title">
        <div class="meter-dialog-card">
          <h2 id="power-title">Konfigurera energi</h2>
          <p data-power-result></p>
          <div class="battery-mode-wrap" data-power-battery-mode-wrap hidden>
            <span class="battery-mode-title">Batterieffekt</span>
            <div class="battery-mode-control" data-power-battery-mode role="radiogroup" aria-label="Batterieffekt">
              <label class="battery-mode-option"><input type="radio" name="battery-mode" value="combined"><span>Kombinerad sensor</span></label>
              <label class="battery-mode-option"><input type="radio" name="battery-mode" value="separate"><span>Separata sensorer</span></label>
            </div>
          </div>
          <div class="meter-selectors" data-power-selectors></div>
          <label class="battery-invert-row" data-power-invert-battery-wrap hidden>Invertera batterieffekt<input type="checkbox" data-power-invert-battery></label>
          <button type="button" data-power-add-solar hidden>Lägg till solentitet</button>
          <button type="button" data-power-clear>Rensa</button>
          <div class="provider-actions">
            <button type="button" data-power-cancel>Avbryt</button>
            <button type="button" data-power-save disabled>Spara</button>
          </div>
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
          container-type: inline-size;
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

        .header-icon-controls {
          align-items: center;
          display: inline-flex;
          flex: 0 0 auto;
          gap: 4px;
        }

        .header-icon-button {
          align-items: center;
          background: transparent;
          border: 0;
          border-radius: 8px;
          color: var(--secondary-text-color);
          cursor: pointer;
          display: inline-flex;
          font-size: 20px;
          height: 32px;
          justify-content: center;
          line-height: 1;
          margin: 0;
          padding: 0;
          opacity: .55;
          transition: opacity 120ms ease, background-color 120ms ease;
          width: 32px;
        }

        .header-icon-button ha-icon {
          --mdc-icon-size: 20px;
          height: 20px;
          width: 20px;
        }

        .header-icon-button:hover {
          background: color-mix(in srgb, var(--secondary-text-color) 12%, transparent);
        }

        .header-icon-button:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }

        .header-icon-button.active {
          opacity: 1;
        }

        [data-configuration-cards][hidden] {
          display: none;
        }

        @media (max-width: 480px) {
          .header-icon-controls {
            gap: 2px;
          }

          .header-icon-button {
            font-size: 18px;
            height: 30px;
            width: 30px;
          }

          .header-icon-button ha-icon {
            --mdc-icon-size: 18px;
            height: 18px;
            width: 18px;
          }
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

        .battery-mode-wrap {
          display: grid;
          gap: 8px;
          margin-top: 16px;
        }

        .battery-mode-title {
          color: var(--primary-text-color);
          font-weight: 500;
        }

        .battery-mode-control {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          max-width: 460px;
        }

        .battery-mode-option {
          align-items: center;
          background: var(--ha-card-background, var(--card-background-color));
          border: 1px solid var(--divider-color);
          color: var(--primary-text-color);
          cursor: pointer;
          display: flex;
          justify-content: center;
          min-height: 42px;
          padding: 8px 12px;
          text-align: center;
        }

        .battery-mode-option:first-child {
          border-radius: 8px 0 0 8px;
        }

        .battery-mode-option:last-child {
          border-left: 0;
          border-radius: 0 8px 8px 0;
        }

        .battery-mode-option input {
          height: 1px;
          margin: -1px;
          opacity: 0;
          position: absolute;
          width: 1px;
        }

        .battery-mode-option:has(input:checked) {
          background: var(--primary-color);
          border-color: var(--primary-color);
          color: var(--text-primary-color, white);
          font-weight: 600;
        }

        .battery-mode-option:focus-within {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }

        .battery-invert-row {
          align-items: center;
          display: flex;
          gap: 10px;
          margin-top: 16px;
        }

        @media (max-width: 420px) {
          .battery-mode-option {
            font-size: 13px;
            padding-left: 6px;
            padding-right: 6px;
          }
        }

        .meter-summary {
          color: var(--secondary-text-color);
          display: grid;
          gap: 6px 18px;
          grid-template-columns: minmax(120px, auto) 1fr;
          margin-top: 14px;
        }

        .meter-load-section {
          margin-top: 14px;
        }

        .meter-load-section h3 {
          font-size: inherit;
          font-weight: 500;
          margin: 0 0 8px;
        }

        .power-summary {
          color: var(--secondary-text-color);
          display: grid;
          gap: 6px 18px;
          grid-template-columns: minmax(120px, auto) 1fr;
          margin-top: 14px;
        }

        .power-summary-divider {
          border-top: 1px solid var(--divider-color);
          grid-column: 1 / -1;
          margin: 6px 0;
        }

        .daily-energy-row {
          align-items: start;
          display: grid;
          gap: 16px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        @container (max-width: 760px) {
          .daily-energy-row {
            grid-template-columns: 1fr;
          }
        }

        .daily-energy-card {
          --daily-energy-local-color: var(--solar-color, #77C2A1);
          --daily-energy-export-color: var(--grid-export-color, #72AAF6);
          --daily-energy-import-color: var(--grid-import-color, #F0A06A);
          min-height: 0;
          min-width: 0;
        }

        .daily-energy-grid {
          display: grid;
          gap: 24px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          margin-top: 14px;
        }

        .daily-energy-part {
          min-width: 0;
        }

        .daily-energy-part-heading,
        .daily-energy-part-labels,
        .daily-energy-part-values {
          align-items: baseline;
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 12px;
        }

        .daily-energy-part-heading > *,
        .daily-energy-part-labels > *,
        .daily-energy-part-values > * {
          min-width: 0;
          overflow-wrap: normal;
          word-break: normal;
        }

        .daily-energy-part-heading strong {
          color: var(--primary-text-color);
          font-weight: 600;
        }

        .daily-energy-total {
          color: var(--primary-text-color);
          font-weight: 600;
          text-align: right;
        }

        .daily-energy-bar {
          background: var(--divider-color);
          border-radius: 999px;
          display: flex;
          height: clamp(20px, 6cqw, 30px);
          margin: clamp(8px, 1.5cqw, 11px) 0 clamp(7px, 1.3cqw, 10px);
          overflow: hidden;
          position: relative;
        }

        .daily-energy-segment {
          filter: brightness(.78) saturate(.9);
          min-width: 0;
          transition: width 120ms ease;
        }

        .daily-energy-segment.local {
          background: var(--daily-energy-local-color);
        }

        .daily-energy-segment.supply {
          background: var(--daily-energy-local-color);
        }

        .daily-energy-segment.export {
          background: var(--daily-energy-export-color);
        }

        .daily-energy-segment.import {
          background: var(--daily-energy-import-color);
        }

        .daily-energy-percent {
          color: #fff;
          font-size: clamp(10px, 2.7cqw, 14px);
          font-weight: 600;
          line-height: clamp(20px, 6cqw, 30px);
          position: absolute;
          text-shadow: 0 1px 2px rgb(0 0 0 / 55%);
          top: 0;
          white-space: nowrap;
          z-index: 1;
        }

        .daily-energy-percent.first {
          left: clamp(4px, 1.25cqw, 6px);
        }

        .daily-energy-percent.second {
          right: clamp(4px, 1.25cqw, 6px);
        }

        .daily-energy-part-labels {
          color: var(--secondary-text-color);
          font-weight: 500;
        }

        .daily-energy-part-labels span:last-child,
        .daily-energy-part-values span:last-child {
          text-align: right;
        }

        .daily-energy-part-values {
          color: var(--secondary-text-color);
          font-size: inherit;
          margin-top: 2px;
        }

        @media (max-width: 700px) {
          .daily-energy-card {
            padding: 12px;
          }

          .daily-energy-grid {
            gap: clamp(6px, 2cqw, 8px);
          }

          .daily-energy-part-heading {
            display: block;
          }

          .daily-energy-part-heading strong,
          .daily-energy-total {
            display: block;
            text-align: left;
          }

          .daily-energy-part-labels,
          .daily-energy-part-values {
            gap: 4px;
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }

        .soc-card {
          --soc-color: var(--solar-color, #77C2A1);
          min-height: 0;
          min-width: 0;
        }

        .soc-card-content {
          align-items: stretch;
          display: grid;
          gap: 8px;
          grid-template-columns: minmax(0, 7fr) minmax(0, 3fr);
          margin-top: 2px;
        }

        .visually-hidden {
          border: 0;
          clip: rect(0 0 0 0);
          clip-path: inset(50%);
          height: 1px;
          margin: -1px;
          overflow: hidden;
          padding: 0;
          position: absolute;
          white-space: nowrap;
          width: 1px;
        }

        .capacity-utilization-title {
          color: var(--primary-text-color);
          font-family: inherit;
          font-size: clamp(12px, 2cqw, 19px);
          font-weight: 500;
          line-height: normal;
          margin: 0;
          padding: 0;
          min-width: 0;
          white-space: nowrap;
          text-align: right;
        }

        .soc-chart {
          margin: 0 -8px 0 0;
          position: relative;
        }

        .capacity-utilization {
          align-items: stretch;
          display: flex;
          flex-direction: column;
          justify-content: flex-start;
          min-width: 0;
          padding: 0;
        }

        .capacity-utilization > [data-capacity-utilization] {
          align-items: center;
          display: flex;
          flex: 1;
          justify-content: center;
          min-height: 0;
        }

        .capacity-battery {
          align-items: center;
          border: 2px solid var(--divider-color);
          border-radius: 12px;
          box-sizing: border-box;
          align-self: stretch;
          display: grid;
          height: calc(100% - 7px);
          max-height: 100%;
          margin-top: 7px;
          max-width: 72px;
          min-width: 44px;
          overflow: visible;
          padding: 0 8px;
          position: relative;
          width: fit-content;
        }

        .capacity-battery::before {
          background: var(--divider-color);
          border-radius: 4px 4px 0 0;
          content: "";
          height: 7px;
          left: 50%;
          position: absolute;
          top: -9px;
          transform: translateX(-50%);
          width: 28px;
        }

        .capacity-battery-fill {
          background: var(--soc-color);
          border-radius: 8px;
          bottom: 0;
          left: 0;
          opacity: .82;
          position: absolute;
          right: 0;
          transition: height 120ms ease;
        }

        .capacity-battery-value {
          align-items: center;
          color: var(--primary-text-color);
          display: flex;
          font-size: clamp(10px, 1.6cqw, 16px);
          font-weight: 700;
          inset: auto;
          justify-content: center;
          position: relative;
          text-shadow: 0 1px 2px rgb(0 0 0 / 55%);
          white-space: nowrap;
          z-index: 1;
        }

        .soc-chart-svg {
          display: block;
          height: 103px;
          max-width: 100%;
          width: 100%;
        }

        .soc-gridline {
          stroke: var(--divider-color);
          stroke-width: 1;
          opacity: .5;
        }

        .soc-label {
          fill: var(--secondary-text-color);
          font-size: var(--card-chart-label-size);
        }

        .soc-area {
          fill: var(--soc-color);
          fill-opacity: .3;
          stroke: none;
        }

        .soc-line {
          fill: none;
          stroke: var(--soc-color);
          stroke-linecap: round;
          stroke-linejoin: round;
          stroke-width: 2;
          vector-effect: non-scaling-stroke;
        }

        .soc-tooltip {
          background: var(--ha-card-background, var(--card-background-color));
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          box-shadow: var(--ha-card-box-shadow, none);
          color: var(--primary-text-color);
          font-size: var(--price-card-text-size);
          line-height: 1.25;
          padding: 6px 8px;
          pointer-events: none;
          position: absolute;
          white-space: nowrap;
          z-index: 2;
        }

        .soc-tooltip strong {
          display: block;
          font-weight: 600;
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
          margin-bottom: 16px;
          padding-bottom: 0;
        }

        h1, h2, p {
          margin: 0;
        }

        h1 {
          font-size: 28px;
          font-weight: 500;
        }

        .grid {
          display: grid;
          gap: 16px;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        }

        .price-section {
          --solar-color: #77C2A1;
          --consumption-color: #E87570;
          --grid-import-color: #F0A06A;
          --grid-export-color: #72AAF6;
          --charging-color: #B76A8F;
          --discharging-color: #DF5C8A;
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
          justify-content: flex-start;
          margin-bottom: 2px;
        }

        .price-heading-main {
          align-items: center;
          display: flex;
          flex: 0 0 auto;
          gap: 12px;
          justify-content: flex-start;
        }

        .price-summary {
          align-items: center;
          display: grid;
          flex: 1 1 230px;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 6px;
          justify-content: center;
          min-width: min(100%, 215px);
          text-align: right;
          width: min(100%, 230px);
        }

        .price-summary .price-value {
          min-width: 0;
          text-align: center;
          white-space: nowrap;
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

        .price-value strong.cheap {
          color: var(--success-color);
        }

        .price-value.current strong.normal {
          color: var(--warning-color);
        }

        .price-value.current strong.expensive {
          color: var(--error-color);
        }

        .price-value strong.expensive {
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

        .section-heading.price-summary-inline .price-summary .price-value > span,
        .section-heading.price-summary-inline .price-summary .price-value small,
        .section-heading.price-summary-inline .price-summary .price-value em {
          font-size: clamp(11px, 1.5cqw, 15px);
        }

        .section-heading.price-summary-inline .price-summary .price-value strong {
          font-size: clamp(11px, 1.7cqw, 17px);
        }

        .section-heading h2,
        .card[data-provider-card] h2 {
          font-size: var(--card-title-size);
          font-weight: 700;
          line-height: 1.1;
          margin-bottom: 6px;
          white-space: nowrap;
        }

        .price-section .section-heading h2 {
          font-size: clamp(19px, 4.7cqw, 22px);
        }

        .price-heading-main > div:first-child {
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
          fill: color-mix(in srgb, var(--success-color) 41%, var(--ha-card-background, var(--card-background-color)));
        }

        .chart-bar.normal {
          fill: color-mix(in srgb, var(--warning-color) 41%, var(--ha-card-background, var(--card-background-color)));
        }

        .chart-bar.expensive {
          fill: color-mix(in srgb, var(--error-color) 41%, var(--ha-card-background, var(--card-background-color)));
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
          touch-action: pan-y;
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
          display: block;
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

        .price-analysis-forecast {
          color: var(--secondary-text-color);
        }

        .price-analysis-forecast {
          align-items: baseline;
          column-gap: .3em;
          display: flex;
          font-size: var(--price-card-text-size);
          flex-wrap: wrap;
          line-height: 1.35;
          row-gap: 0;
        }

        .price-analysis-sentence {
          flex: 0 1 auto;
          min-width: min-content;
          overflow-wrap: break-word;
        }

        .price-chart-legend {
          align-items: center;
          display: flex;
          flex-wrap: nowrap;
          font-size: var(--card-legend-size);
          min-height: 22px;
          justify-content: space-between;
          margin-top: 1px;
          margin-left: 0;
          margin-right: 0;
          max-width: none;
          width: 100%;
        }

        .price-chart-legend .chart-legend-toggle {
          flex: 0 1 auto;
          min-width: 0;
          white-space: nowrap;
        }

        .price-comparison-controls {
          align-items: center;
          display: flex;
          flex: 0 0 auto;
          gap: 6px;
          justify-content: flex-end;
          align-self: center;
          margin: 0;
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

        .meter-invert-toggle {
          font-size: 12px;
          gap: 8px;
          margin: 12px 0 16px;
        }

        .meter-invert-toggle .price-filter-track {
          height: 20px;
          --knob-size: 14px;
          --track-padding: 2px;
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
            gap: clamp(1px, .5cqw, 2px) clamp(8px, 1.5cqw, 12px);
          }

          .price-section .price-comparison-controls {
            gap: 6px;
          }

          .price-section .price-summary {
            gap: clamp(4px, .8cqw, 6px);
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

        .chart-power-solar { stroke: var(--solar-color); }
        .chart-power-consumption { stroke: var(--consumption-color); }
        .chart-power-charging { stroke: var(--charging-color); }
        .chart-power-discharging { stroke: var(--discharging-color); }
        .chart-power-solar,
        .chart-power-consumption,
        .chart-power-charging,
        .chart-power-discharging {
          fill: none;
          stroke-linecap: round;
          stroke-linejoin: round;
          stroke-width: 1.6;
          opacity: .82;
          vector-effect: non-scaling-stroke;
        }

        .chart-power-area {
          pointer-events: none;
          stroke: none;
          fill-opacity: .18;
        }

        .chart-power-area-solar { fill: var(--solar-color); }
        .chart-power-area-import { fill: var(--grid-import-color); }
        .chart-power-area-export { fill: var(--grid-export-color); }
        .chart-power-area-consumption { fill: var(--consumption-color); }
        .chart-power-area-charging { fill: var(--charging-color); }
        .chart-power-area-discharging { fill: var(--discharging-color); }

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

        .chart-hover-marker-solar { fill: var(--solar-color); }
        .chart-hover-marker-consumption { fill: var(--consumption-color); }
        .chart-hover-marker-charging { fill: var(--charging-color); }
        .chart-hover-marker-discharging { fill: var(--discharging-color); }
        .chart-hover-marker-soc { fill: var(--soc-color); }

        .tooltip-power-solar { color: var(--solar-color); }
        .tooltip-power-consumption { color: var(--consumption-color); }
        .tooltip-power-charging { color: var(--charging-color); }
        .tooltip-power-discharging { color: var(--discharging-color); }

        .chart-bar {
          cursor: default;
          fill-opacity: .72;
          stroke: #111111;
          stroke-width: .7;
          vector-effect: non-scaling-stroke;
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
          position: relative;
        }

        .card-heading:has(.main-card-toggle) h2 {
          padding-right: 44px;
        }

        .main-card-toggle {
          align-items: center;
          color: var(--secondary-text-color);
          cursor: pointer;
          display: inline-flex;
          font-size: 12px;
          gap: 4px;
          position: absolute;
          right: 0;
          top: 0;
          white-space: nowrap;
        }

        .main-card-toggle[hidden] {
          display: none !important;
        }

        .main-card-toggle input {
          height: 0;
          opacity: 0;
          position: absolute;
          width: 0;
        }

        .main-card-track {
          background: #555;
          border-radius: 10px;
          display: inline-block;
          height: 16px;
          position: relative;
          transition: background-color 120ms ease;
          width: 27px;
        }

        .main-card-track::after {
          background: #d8d8d8;
          border-radius: 50%;
          content: "";
          height: 11px;
          left: 2px;
          position: absolute;
          top: 2px;
          transition: transform 120ms ease;
          width: 11px;
        }

        .main-card-toggle input:checked + .main-card-track {
          background: var(--primary-color);
        }

        .main-card-toggle input:checked + .main-card-track::after {
          transform: translateX(12px);
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
    this._bindPowerDialog();
    this._bindDebugToggle();
    this._bindConfigurationCardsToggle();
    this._bindMainCardToggles();
    this._bindProviderSourceDialog();
    this._bindMeterSourceDialog();
    this._bindDiagnostics();
    this._bindMainInvoiceParser();
    this._bindChartLegend();
    this._setupPriceHeaderLayoutObserver();
    this.renderPriceChart();
  }

  _setupPriceHeaderLayoutObserver() {
    const heading = this.host.querySelector(".section-heading");
    if (!heading || !("ResizeObserver" in window)) return;
    const updateLayoutState = () => {
      const cluster = heading.querySelector(".price-heading-main");
      const summary = heading.querySelector(".price-summary");
      if (!cluster || !summary) return;
      const wrapped = summary.getBoundingClientRect().top > cluster.getBoundingClientRect().bottom + 1;
      heading.classList.toggle("price-summary-wrapped", wrapped);
      heading.classList.toggle("price-summary-inline", !wrapped);
    };
    this._priceHeaderLayoutObserver = new ResizeObserver(updateLayoutState);
    this._priceHeaderLayoutObserver.observe(heading);
    updateLayoutState();
  }

  _chartLayerState() {
    return {
      spot: this._spotBarsVisible,
      average: this._averageLineVisible,
      import: this._meterPowerVisible.import,
      export: this._meterPowerVisible.export,
      ...this._previewLayersVisible,
    };
  }

  _effectiveChartLayerState() {
    const layers = this._chartLayerState();
    if (!this._hoverIsolatedLayer) return layers;
    return Object.fromEntries(Object.keys(layers).map((key) => [key, key === this._hoverIsolatedLayer]));
  }

  _applyMainCardState(mainCards) {
    if (!mainCards || typeof mainCards !== "object") return;
    for (const key of Object.keys(this._mainCards)) {
      if (typeof mainCards[key] === "boolean") this._mainCards[key] = mainCards[key];
    }
    if (this._mainCards.consumption && !this._mainCards.elmatare) this._mainCards.elmatare = true;
    this._mainCards.consumption = false;
  }

  _applyConfigurationCardsVisibility(visible, mainCards = this._mainCards) {
    if (typeof visible !== "boolean") return;
    this._configurationCardsVisible = visible;
    const cards = this.host.querySelector("[data-configuration-cards]");
    const button = this.host.querySelector("[data-config-cards-toggle]");
    this._applyMainCardState(mainCards);
    const anyMainCard = Object.values(this._mainCards).some(Boolean);
    if (cards) cards.hidden = !visible && !anyMainCard;
    for (const card of this.host.querySelectorAll("[data-config-card-key]")) {
      const key = card.dataset.configCardKey;
      card.hidden = !visible && !this._mainCards[key];
    }
    for (const toggle of this.host.querySelectorAll("[data-main-card-toggle]")) {
      const key = toggle.dataset.mainCardToggle;
      const input = toggle.querySelector("input");
      toggle.hidden = !visible;
      if (input && typeof this._mainCards[key] === "boolean") input.checked = this._mainCards[key];
    }
    for (const control of this.host.querySelectorAll(".configuration-control")) control.hidden = !visible;
    if (button) {
      button.classList.toggle("active", visible);
      button.setAttribute("aria-pressed", String(visible));
    }
  }

  _applyChartLayerState(layers) {
    if (!layers || typeof layers !== "object") return;
    if (typeof layers.spot === "boolean") this._spotBarsVisible = layers.spot;
    if (typeof layers.average === "boolean") this._averageLineVisible = layers.average;
    if (typeof layers.import === "boolean") this._meterPowerVisible.import = layers.import;
    if (typeof layers.export === "boolean") this._meterPowerVisible.export = layers.export;
    for (const key of Object.keys(this._previewLayersVisible)) {
      if (typeof layers[key] === "boolean") this._previewLayersVisible[key] = layers[key];
    }
  }

  _syncChartLayerButtons() {
    const layers = this._chartLayerState();
    for (const button of this.host.querySelectorAll("[data-chart-layer]")) {
      const value = layers[button.dataset.chartLayer];
      if (typeof value !== "boolean") continue;
      button.classList.toggle("active", value);
      button.setAttribute("aria-pressed", String(value));
    }
    for (const button of this.host.querySelectorAll("[data-preview-layer]")) {
      const value = layers[button.dataset.previewLayer];
      if (typeof value !== "boolean") continue;
      button.classList.toggle("active", value);
      button.setAttribute("aria-pressed", String(value));
    }
  }

  async _loadChartPreferences() {
    if (!this.hass?.callWS) return;
    try {
      const response = await this.hass.callWS({ type: "elrakning/ui_preferences/get" });
      this._applyChartLayerState(response.chart_layers);
      this._applyConfigurationCardsVisibility(response.configuration_cards_visible, response.main_cards);
      this._chartPreferencesReady = true;
      this._syncChartLayerButtons();
      this.renderPriceChart();
    } catch {
      // Keep the first-use defaults for this session when preference loading fails.
    }
  }

  async _persistChartPreferences() {
    if (!this.hass?.callWS || !this._chartPreferencesReady) return;
    try {
      await this.hass.callWS({
        type: "elrakning/ui_preferences/set",
        chart_layers: this._chartLayerState(),
        configuration_cards_visible: this._configurationCardsVisible,
        main_cards: this._mainCards,
      });
    } catch (error) {
      console.warn("Elrakning chart preference persistence failed", error);
    }
  }

  _bindChartLegend() {
    const bindHoverIsolation = (button, layer) => {
      button.addEventListener("pointerenter", (event) => {
        if (event.pointerType === "touch" || button.disabled) return;
        this._hoverIsolatedLayer = layer;
        this.renderPriceChart();
      });
      button.addEventListener("pointerleave", (event) => {
        if (event.pointerType === "touch") return;
        this._hoverIsolatedLayer = null;
        this.renderPriceChart();
      });
    };
    for (const button of this.host.querySelectorAll("[data-chart-layer]")) {
      bindHoverIsolation(button, button.dataset.chartLayer);
      button.addEventListener("click", () => {
        const layer = button.dataset.chartLayer;
        if (layer === "import" || layer === "export") {
          this._meterPowerVisible[layer] = !this._meterPowerVisible[layer];
          button.classList.toggle("active", this._meterPowerVisible[layer]);
          button.setAttribute("aria-pressed", String(this._meterPowerVisible[layer]));
          this.renderPriceChart();
          this._persistChartPreferences();
          return;
        }
        if (layer === "average") {
          this._averageLineVisible = !this._averageLineVisible;
          button.classList.toggle("active", this._averageLineVisible);
          button.setAttribute("aria-pressed", String(this._averageLineVisible));
          this.renderPriceChart();
          this._persistChartPreferences();
          return;
        }
        if (layer !== "spot") return;
        this._spotBarsVisible = !this._spotBarsVisible;
        button.classList.toggle("active", this._spotBarsVisible);
        button.setAttribute("aria-pressed", String(this._spotBarsVisible));
        this.renderPriceChart();
        this._persistChartPreferences();
      });
    }
    for (const button of this.host.querySelectorAll("[data-preview-layer]")) {
      bindHoverIsolation(button, button.dataset.previewLayer);
      button.addEventListener("click", () => {
        const layer = button.dataset.previewLayer;
        if (!(layer in this._previewLayersVisible)) return;
        this._previewLayersVisible[layer] = !this._previewLayersVisible[layer];
        button.classList.toggle("active", this._previewLayersVisible[layer]);
        button.setAttribute("aria-pressed", String(this._previewLayersVisible[layer]));
        this.renderPriceChart();
        this._persistChartPreferences();
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
    toggle.addEventListener("click", () => {
      this._debugEnabled = !this._debugEnabled;
      toggle.classList.toggle("active", this._debugEnabled);
      toggle.setAttribute("aria-pressed", String(this._debugEnabled));
      this._debugPreferenceChanged = true;
      this._applyDebugVisibility();
      this._saveDebugPreference();
    });
    this._applyDebugVisibility();
  }

  _bindConfigurationCardsToggle() {
    const toggle = this.host.querySelector("[data-config-cards-toggle]");
    if (!toggle) return;
    toggle.addEventListener("click", () => {
      this._applyConfigurationCardsVisibility(!this._configurationCardsVisible);
      this._persistChartPreferences();
    });
    this._applyConfigurationCardsVisibility(this._configurationCardsVisible);
  }

  _bindMainCardToggles() {
    for (const toggle of this.host.querySelectorAll("[data-main-card-toggle]")) {
      const input = toggle.querySelector("input");
      if (!input) continue;
      toggle.addEventListener("click", (event) => {
        if (event.target === input) return;
        event.preventDefault();
        input.checked = !input.checked;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
      input.addEventListener("change", () => {
        const key = toggle.dataset.mainCardToggle;
        if (!(key in this._mainCards)) return;
        this._mainCards[key] = input.checked;
        if (key === "elmatare") this._mainCards.consumption = false;
        this._applyConfigurationCardsVisibility(this._configurationCardsVisible);
        this._persistChartPreferences();
      });
    }
  }

  async _loadDebugPreference() {
    if (!this.hass?.callWS) return;
    try {
      const response = await this.hass.callWS({ type: "elrakning/frontend_preferences" });
      if (!this._debugPreferenceChanged && typeof response.debug_enabled === "boolean") {
        this._debugEnabled = response.debug_enabled;
        const toggle = this.host.querySelector("[data-debug-toggle]");
        if (toggle) {
          toggle.classList.toggle("active", this._debugEnabled);
          toggle.setAttribute("aria-pressed", String(this._debugEnabled));
        }
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
    const clearLast = this.host.querySelector("[data-meter-clear-last]");
    const result = this.host.querySelector("[data-meter-result]");
    const selectorsElement = this.host.querySelector("[data-meter-selectors]");
    const consumptionSelectorElement = this.host.querySelector("[data-meter-consumption-selector]");
    const invertToggle = this.host.querySelector("[data-meter-invert-power]");
    if (!open || !dialog || !cancel || !save || !result || !selectorsElement || !consumptionSelectorElement || !invertToggle) return;
    const fields = [
      ["Effekt", "power_entity"],
      ["Import idag", "energy_import_entity"],
      ["Export idag", "energy_export_entity"],
    ];
    const close = () => {
      dialog.hidden = true;
      invertToggle.checked = false;
      selectorsElement.replaceChildren();
      consumptionSelectorElement.replaceChildren();
    };
    const selectorConfig = (field) => {
      if (field !== "energy_import_entity" && field !== "energy_export_entity") return { domain: "sensor" };
      const energyEntities = Object.entries(this.hass?.states || {})
        .filter(([, state]) => state?.attributes?.device_class === "energy"
          && ["Wh", "kWh", "MWh"].includes(state?.attributes?.unit_of_measurement))
        .map(([entityId]) => entityId);
      return { domain: "sensor", device_class: "energy", entity_id: energyEntities };
    };
    const renderEntitySelector = (container, labelText, field, value) => {
      const label = document.createElement("label");
      label.className = "meter-selector-label";
      label.textContent = labelText;
      const selector = document.createElement("ha-selector");
      selector.dataset.meterField = field;
      selector.hass = this.hass;
      selector.selector = { entity: { filter: selectorConfig(field), multiple: false } };
      selector.value = value || undefined;
      selector.addEventListener("value-changed", (event) => {
        selector.value = event.detail?.value;
      });
      label.append(selector);
      container.replaceChildren(label);
    };
    const renderSelectors = (mapping) => {
      selectorsElement.replaceChildren(...fields.map(([labelText, field]) => {
        const label = document.createElement("label");
        label.className = "meter-selector-label";
        label.textContent = labelText;
        const selector = document.createElement("ha-selector");
        selector.dataset.meterField = field;
        selector.hass = this.hass;
        selector.selector = { entity: { filter: selectorConfig(field), multiple: false } };
        selector.value = mapping?.[field] || undefined;
        selector.addEventListener("value-changed", (event) => {
          selector.value = event.detail?.value;
        });
        label.append(selector);
        return label;
      }));
    };
    const renderConsumptionSelector = (state) => {
      renderEntitySelector(consumptionSelectorElement, "Husets last", "consumption_entity", state?.consumption_entity);
    };
    const currentPowerMapping = () => {
      const current = this._powerState || {};
      return {
        solar_entities: Array.isArray(current.solar_entities) ? [...current.solar_entities] : [],
        consumption_entity: current.consumption_entity || "",
        charging_entity: current.charging_entity || "",
        discharging_entity: current.discharging_entity || "",
        battery_power_entity: current.battery_power_entity || "",
        invert_battery_power: current.invert_battery_power === true,
        soc_entity: current.soc_entity || "",
        capacity_entity: current.capacity_entity || "",
      };
    };
    open.addEventListener("click", async () => {
      dialog.hidden = false;
      save.disabled = true;
      result.textContent = "Hämtar sparad konfiguration …";
      try {
        const [meterResponse, powerResponse] = await Promise.all([
          this.hass.callWS({ type: "elrakning/meter_state" }),
          this.hass.callWS({ type: "elrakning/power_state" }),
        ]);
        this._applyMeterState(meterResponse);
        this._applyPowerState(powerResponse);
        renderSelectors(meterResponse);
        renderConsumptionSelector(powerResponse);
        invertToggle.checked = meterResponse.invert_power === true;
        result.textContent = "Välj de entiteter som ska användas.";
        save.disabled = false;
      } catch {
        selectorsElement.replaceChildren();
        consumptionSelectorElement.replaceChildren();
        result.textContent = "Mätar- eller lastkonfigurationen kunde inte hämtas.";
      }
    });
    save.addEventListener("click", async () => {
      await this._recordMeterDiagnostic("INFO", "meter_save_clicked", "Meter save button clicked");
      const mapping = Object.fromEntries(fields.map(([, field]) => {
        const value = selectorsElement.querySelector(`[data-meter-field="${field}"]`)?.value;
        return [field, typeof value === "string" && value ? value : ""];
      }));
      mapping.invert_power = invertToggle.checked;
      const powerMapping = currentPowerMapping();
      powerMapping.consumption_entity = consumptionSelectorElement.querySelector('[data-meter-field="consumption_entity"]')?.value || "";
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
        const powerResponse = await this.hass.callWS({ type: "elrakning/power_save", ...powerMapping });
        if (!powerResponse?.success) throw new Error(powerResponse?.error || "power_save_failed");
        this._applyPowerState(powerResponse);
        await this.loadMeterPowerHistory();
        await this.loadPowerHistory();
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
        invertToggle.checked = false;
        result.textContent = "Elmätare rensad.";
      } catch (error) {
        const details = this._websocketErrorDetails(error);
        result.textContent = `Elmätaren kunde inte rensas: ${details.code}: ${details.message}`;
      }
    });
    clearLast?.addEventListener("click", async () => {
      if (!window.confirm("Är du säker? Husets last rensas.")) return;
      const mapping = currentPowerMapping();
      mapping.consumption_entity = "";
      save.disabled = true;
      result.textContent = "Rensar last …";
      try {
        this._resetPowerLivePoints();
        const response = await this.hass.callWS({ type: "elrakning/power_save", ...mapping });
        if (!response?.success) throw new Error(response?.error || "power_clear_failed");
        this._applyPowerState(response);
        renderConsumptionSelector(response);
        await this.loadPowerHistory();
        save.disabled = false;
        result.textContent = "Last rensad.";
      } catch (error) {
        const details = this._websocketErrorDetails(error);
        save.disabled = false;
        result.textContent = `Lasten kunde inte rensas: ${details.code}: ${details.message}`;
      }
    });
  }

  _bindPowerDialog() {
    const dialog = this.host.querySelector("[data-power-dialog]");
    const selectorsElement = this.host.querySelector("[data-power-selectors]");
    const result = this.host.querySelector("[data-power-result]");
    const save = this.host.querySelector("[data-power-save]");
    const cancel = this.host.querySelector("[data-power-cancel]");
    const addSolar = this.host.querySelector("[data-power-add-solar]");
    const clear = this.host.querySelector("[data-power-clear]");
    const batteryModeWrap = this.host.querySelector("[data-power-battery-mode-wrap]");
    const batteryModeOptions = Array.from(this.host.querySelectorAll("[data-power-battery-mode] input[type=radio]"));
    const invertBatteryWrap = this.host.querySelector("[data-power-invert-battery-wrap]");
    const invertBatteryToggle = this.host.querySelector("[data-power-invert-battery]");
    if (!dialog || !selectorsElement || !result || !save || !cancel) return;
    let mode = "solar";
    let batteryMode = "separate";
    let solarCount = 2;
    const fieldsFor = (selectedMode) => selectedMode === "solar"
      ? Array.from({ length: solarCount }, (_, index) => [`Solproduktion ${index + 1}`, "solar_entities", true])
      : selectedMode === "consumption"
        ? [["Förbrukning", "consumption_entity", false]]
        : [
          ...(batteryMode === "combined" ? [["Batterieffekt", "battery_power_entity", false]] : [["Laddning", "charging_entity", false], ["Urladdning", "discharging_entity", false]]),
          ["Batteriets laddnivå", "soc_entity", false],
          ["Batterikapacitet", "capacity_entity", false],
        ];
    const close = () => { dialog.hidden = true; selectorsElement.replaceChildren(); };
    const renderSelectors = (state) => {
      const fields = fieldsFor(mode);
      if (batteryModeWrap) batteryModeWrap.hidden = mode !== "battery";
      batteryModeOptions.forEach((option) => { option.checked = option.value === batteryMode; });
      if (invertBatteryWrap) invertBatteryWrap.hidden = mode !== "battery" || batteryMode !== "combined";
      selectorsElement.replaceChildren(...fields.map(([labelText, field, multiple], index) => {
        const label = document.createElement("label");
        label.className = "meter-selector-label";
        label.textContent = labelText;
        const selector = document.createElement("ha-selector");
        selector.dataset.powerField = field;
        if (multiple) selector.dataset.powerIndex = String(index);
        selector.hass = this.hass;
        selector.selector = { entity: { filter: { domain: "sensor" }, multiple: false } };
        const current = multiple ? state?.solar_entities?.[index] : state?.[field];
        selector.value = current || undefined;
        selector.addEventListener("value-changed", (event) => { selector.value = event.detail?.value; });
        label.append(selector);
        return label;
      }));
      if (invertBatteryWrap) {
        if (mode === "battery" && batteryMode === "combined" && selectorsElement.children.length > 1) {
          selectorsElement.insertBefore(invertBatteryWrap, selectorsElement.children[1]);
        } else {
          selectorsElement.parentElement.insertBefore(invertBatteryWrap, selectorsElement.nextElementSibling);
        }
      }
    };
    const open = async (selectedMode) => {
      mode = selectedMode;
      dialog.hidden = false;
      if (clear) clear.textContent = ({ solar: "Rensa sol", consumption: "Rensa last", battery: "Rensa batteri" })[mode];
      save.disabled = true;
      result.textContent = "Hämtar sparad konfiguration …";
      try {
        const state = await this.hass.callWS({ type: "elrakning/power_state" });
        solarCount = Math.max(2, state?.solar_entities?.length || 0);
        batteryMode = state?.battery_power_entity ? "combined" : "separate";
        batteryModeOptions.forEach((option) => { option.checked = option.value === batteryMode; });
        if (invertBatteryToggle) invertBatteryToggle.checked = state?.invert_battery_power === true;
        this._applyPowerState(state);
        renderSelectors(state);
        if (addSolar) addSolar.hidden = mode !== "solar";
        result.textContent = "Välj de entiteter som ska användas.";
        save.disabled = false;
      } catch {
        selectorsElement.replaceChildren();
        result.textContent = "Energikonfigurationen kunde inte hämtas.";
      }
    };
    this.host.querySelectorAll("[data-power-configure]").forEach((button) => {
      button.addEventListener("click", () => open(button.dataset.powerConfigure));
    });
    batteryModeOptions.forEach((option) => option.addEventListener("change", () => {
      if (!option.checked) return;
      batteryMode = option.value === "combined" ? "combined" : "separate";
      renderSelectors(this._powerState || {});
    }));
    save.addEventListener("click", async () => {
      const current = this._powerState || {};
      const mapping = {
        solar_entities: Array.isArray(current.solar_entities) ? [...current.solar_entities] : [],
        consumption_entity: current.consumption_entity || "",
        charging_entity: current.charging_entity || "",
        discharging_entity: current.discharging_entity || "",
        battery_power_entity: current.battery_power_entity || "",
        invert_battery_power: batteryMode === "combined" && invertBatteryToggle?.checked === true,
        soc_entity: current.soc_entity || "",
        capacity_entity: current.capacity_entity || "",
      };
      selectorsElement.querySelectorAll("[data-power-field]").forEach((selector) => {
        if (selector.dataset.powerField === "solar_entities") mapping.solar_entities.push(selector.value || "");
        else mapping[selector.dataset.powerField] = selector.value || "";
      });
      if (mode === "solar") {
        mapping.solar_entities = Array.from(selectorsElement.querySelectorAll('[data-power-field="solar_entities"]'))
          .map((selector) => selector.value || "");
      }
      if (mode === "battery" && batteryMode === "combined") {
        mapping.charging_entity = "";
        mapping.discharging_entity = "";
      } else if (mode === "battery") {
        mapping.battery_power_entity = "";
        mapping.invert_battery_power = false;
      }
      save.disabled = true;
      result.textContent = "Sparar …";
      try {
        this._resetPowerLivePoints();
        const response = await this.hass.callWS({ type: "elrakning/power_save", ...mapping });
        if (!response?.success) throw new Error(response?.error || "power_save_failed");
        this._applyPowerState(response);
        await this.loadPowerHistory();
        close();
      } catch (error) {
        const details = this._websocketErrorDetails(error);
        save.disabled = false;
        result.textContent = `Energikonfigurationen kunde inte sparas: ${details.code}: ${details.message}`;
      }
    });
    cancel.addEventListener("click", close);
    clear?.addEventListener("click", async () => {
      const labels = { solar: "Sol", consumption: "Last", battery: "Batteri" };
      if (!window.confirm(`Är du säker? ${labels[mode]} rensas.`)) return;
      const current = this._powerState || {};
      const mapping = {
        solar_entities: Array.isArray(current.solar_entities) ? [...current.solar_entities] : [],
        consumption_entity: current.consumption_entity || "",
        charging_entity: current.charging_entity || "",
        discharging_entity: current.discharging_entity || "",
        battery_power_entity: current.battery_power_entity || "",
        invert_battery_power: false,
        soc_entity: current.soc_entity || "",
        capacity_entity: current.capacity_entity || "",
      };
      if (mode === "solar") mapping.solar_entities = [];
      if (mode === "consumption") mapping.consumption_entity = "";
      if (mode === "battery") {
        mapping.battery_power_entity = "";
        mapping.charging_entity = "";
        mapping.discharging_entity = "";
        mapping.invert_battery_power = false;
        mapping.soc_entity = "";
        mapping.capacity_entity = "";
      }
      save.disabled = true;
      result.textContent = "Rensar …";
      try {
        this._resetPowerLivePoints();
        const response = await this.hass.callWS({ type: "elrakning/power_save", ...mapping });
        if (!response?.success) throw new Error(response?.error || "power_clear_failed");
        this._applyPowerState(response);
        await this.loadPowerHistory();
        close();
      } catch (error) {
        const details = this._websocketErrorDetails(error);
        save.disabled = false;
        result.textContent = `Energikonfigurationen kunde inte rensas: ${details.code}: ${details.message}`;
      }
    });
    addSolar?.addEventListener("click", () => {
      if (mode !== "solar" || solarCount >= 12) return;
      solarCount += 1;
      renderSelectors(this._powerState || {});
    });
  }

  _applyPowerState(state) {
    this._powerState = state ? {
      ...state,
      solar_energy_kwh: this._calculatePowerEnergy("solar"),
      consumption_energy_kwh: this._calculatePowerEnergy("consumption"),
      charging_energy_kwh: this._calculatePowerEnergy("charging"),
      discharging_energy_kwh: this._calculatePowerEnergy("discharging"),
    } : null;
    const solarConfigured = Array.isArray(this._powerState?.solar_entities) && this._powerState.solar_entities.length > 0;
    const batteryConfigured = Boolean(this._powerState?.charging_entity || this._powerState?.discharging_entity || this._powerState?.soc_entity || this._powerState?.capacity_entity);
    const batteryPowerConfigured = Boolean(this._powerState?.battery_power_entity);
    const batteryIsConfigured = batteryConfigured || batteryPowerConfigured;
    const capacityUtilizationPercent = this._capacityUtilizationPercent();
    const values = {
      solar: solarConfigured ? [["Effekt just nu", this._powerState.solar_kw, "kW"], ["Producerat idag", this._powerState.solar_energy_kwh, "kWh"]] : [],
      battery: batteryIsConfigured ? [["Laddning", this._powerState.charging_kw, "kW"], ["Urladdning", this._powerState.discharging_kw, "kW"], ["Laddnivå", this._powerState.soc_percent, "%"], ["Kapacitet", this._powerState.capacity_kwh, "kWh"], ["Laddat idag", this._powerState.charging_energy_kwh, "kWh"], ["Urladdat idag", this._powerState.discharging_energy_kwh, "kWh"], ["Kapacitetsutnyttjande", capacityUtilizationPercent, "%"]] : [],
    };
    for (const [cardType, rows] of Object.entries(values)) {
      const status = this.host.querySelector(`[data-power-status="${cardType === "battery" ? "battery" : "solar"}"]`);
      const summary = this.host.querySelector(`[data-power-summary="${cardType}"]`);
      const configured = cardType === "solar" ? solarConfigured : batteryIsConfigured;
      if (status) {
        status.textContent = configured ? "" : "Ej konfigurerad";
        status.hidden = configured;
      }
      if (!summary) continue;
      const validRows = rows
        .map(([labelText, value, unit]) => [labelText, unit === "kW" ? displayPowerValue(value) : value, unit])
        .filter(([, value]) => typeof value === "number" && Number.isFinite(value));
      const summaryNodes = [];
      validRows.forEach(([labelText, value, unit], index) => {
        if (cardType === "battery" && index === 4) {
          const divider = document.createElement("div");
          divider.className = "power-summary-divider";
          summaryNodes.push(divider);
        }
        const label = document.createElement("strong");
        label.textContent = labelText;
        const output = document.createElement("span");
        output.textContent = `${this._formatNumber(value)} ${unit}`;
        summaryNodes.push(label, output);
      });
      summary.replaceChildren(...summaryNodes);
      summary.hidden = validRows.length === 0;
    }
    this._renderMergedMeterSummary();
    this._renderSocChart();
  }

  _calculatePowerEnergy(seriesKey) {
    const points = this._powerHistory?.series?.[seriesKey]?.points;
    const now = new Date();
    const dayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const dayEnd = new Date(dayStart);
    dayEnd.setDate(dayEnd.getDate() + 1);
    return integratePowerHistoryKwh(points, dayStart, dayEnd, now);
  }

  _refreshPowerEnergyState() {
    if (!this._powerState) return;
    this._applyPowerState(this._powerState);
  }

  _renderMergedMeterSummary() {
    const meter = this._meterState || {};
    const power = this._powerState || {};
    const meterConfigured = meter.configured === true;
    const loadConfigured = Boolean(power.consumption_entity);
    const configured = meterConfigured || loadConfigured;
    const status = this.host.querySelector("[data-meter-status]");
    const summary = this.host.querySelector("[data-meter-summary]");
    if (status) {
      status.textContent = configured ? "" : "Ej konfigurerad";
      status.hidden = configured;
    }
    if (!summary) return;
    const rows = [];
    if (loadConfigured) {
      rows.push(["Husets last", displayPowerValue(power.consumption_kw), "kW"]);
      rows.push(["Förbrukat idag", power.consumption_energy_kwh, "kWh"]);
    }
    if (meterConfigured) {
      rows.push(["Nät just nu", displayPowerValue(meter.power_kw), "kW"]);
      if (meter.energy_import_entity && meter.energy_import_valid === false) {
        rows.push(["Import idag", "Byt sensor", ""]);
      } else if (typeof meter.energy_import_kwh === "number") {
        rows.push(["Import idag", meter.energy_import_kwh, "kWh"]);
      }
      if (meter.energy_export_entity && meter.energy_export_valid === false) {
        rows.push(["Export idag", "Byt sensor", ""]);
      } else if (typeof meter.energy_export_kwh === "number") {
        rows.push(["Export idag", meter.energy_export_kwh, "kWh"]);
      }
    }
    const validRows = rows.filter(([, value, unit]) =>
      unit === "" ? value === "Byt sensor" : typeof value === "number" && Number.isFinite(value));
    summary.replaceChildren(...validRows.flatMap(([labelText, value, unit]) => {
      const label = document.createElement("strong");
      label.textContent = labelText;
      const output = document.createElement("span");
      output.textContent = unit ? `${this._formatNumber(value)} ${unit}` : value;
      return [label, output];
    }));
    summary.hidden = validRows.length === 0;
    this._renderDailyEnergyCard();
  }

  _renderDailyEnergyCard() {
    const card = this.host.querySelector("[data-daily-energy]");
    const grid = this.host.querySelector("[data-daily-energy-grid]");
    if (!card || !grid) return;
    const power = this._powerState || {};
    const meter = this._meterState || {};
    const solarConfigured = Array.isArray(power.solar_entities) && power.solar_entities.length > 0;
    const consumptionConfigured = Boolean(power.consumption_entity);
    const powerEnergyAvailable = (key) => Array.isArray(this._powerHistory?.series?.[key]?.points)
      && this._powerHistory.series[key].points.some((point) => Number.isFinite(new Date(point.timestamp).getTime()) && Number.isFinite(Number(point.value_kw)));
    const solarAvailable = solarConfigured && powerEnergyAvailable("solar") && Number.isFinite(power.solar_energy_kwh);
    const consumptionAvailable = consumptionConfigured && powerEnergyAvailable("consumption") && Number.isFinite(power.consumption_energy_kwh);
    const energyValue = (entityKey, validKey, valueKey) => (
      meter[entityKey] && meter[validKey] !== false && Number.isFinite(meter[valueKey]) ? meter[valueKey] : null
    );
    const exportKwh = energyValue("energy_export_entity", "energy_export_valid", "energy_export_kwh");
    const importKwh = energyValue("energy_import_entity", "energy_import_valid", "energy_import_kwh");
    const hasAnyPart = solarConfigured || consumptionConfigured;
    card.hidden = !hasAnyPart;
    if (!hasAnyPart) {
      grid.replaceChildren();
      return;
    }
    const clampPercent = (value) => Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
    const formatEnergy = (value) => Number.isFinite(value) ? `${this._formatNumber(value)} kWh` : "—";
    const formatPercent = (value) => Number.isFinite(value) ? `${this._formatNumber(value)} %` : "—";
    const balancePart = ({ title, total, totalAvailable, firstLabel, firstValue, firstPercent, secondLabel, secondValue, secondPercent, firstClass, secondClass }) => {
      const firstWidth = clampPercent(firstPercent);
      const secondWidth = clampPercent(secondPercent);
      return `<section class="daily-energy-part">
        <div class="daily-energy-part-heading"><strong>${title}</strong><span class="daily-energy-total">${totalAvailable ? formatEnergy(total) : "—"}</span></div>
        <div class="daily-energy-bar" aria-hidden="true"><span class="daily-energy-segment ${firstClass}" style="width: ${firstWidth}%"></span><span class="daily-energy-segment ${secondClass}" style="width: ${secondWidth}%"></span><span class="daily-energy-percent first">${formatPercent(firstPercent)}</span><span class="daily-energy-percent second">${formatPercent(secondPercent)}</span></div>
        <div class="daily-energy-part-labels"><span>${firstLabel}</span><span>${secondLabel}</span></div>
        <div class="daily-energy-part-values"><span>${formatEnergy(firstValue)}</span><span>${formatEnergy(secondValue)}</span></div>
      </section>`;
    };
    const solarBalance = buildEnergyBalance(solarAvailable ? power.solar_energy_kwh : null, exportKwh);
    const consumptionBalance = buildEnergyBalance(consumptionAvailable ? power.consumption_energy_kwh : null, importKwh);
    const markup = [];
    if (solarConfigured) {
      const total = solarBalance.total;
      markup.push(balancePart({
        title: "Solproduktion",
        total,
        totalAvailable: total !== null,
        firstLabel: "Lokalt",
        firstValue: solarBalance.local,
        firstPercent: solarBalance.localPercent,
        secondLabel: "Export",
        secondValue: solarBalance.external,
        secondPercent: solarBalance.externalPercent,
        firstClass: "local",
        secondClass: "export",
      }));
    }
    if (consumptionConfigured) {
      const total = consumptionBalance.total;
      markup.push(balancePart({
        title: "Förbrukning",
        total,
        totalAvailable: total !== null,
        firstLabel: "Lokalt",
        firstValue: consumptionBalance.local,
        firstPercent: consumptionBalance.localPercent,
        secondLabel: "Import",
        secondValue: consumptionBalance.external,
        secondPercent: consumptionBalance.externalPercent,
        firstClass: "supply",
        secondClass: "import",
      }));
    }
    grid.innerHTML = markup.join("");
  }

  _renderSocChart() {
    const card = this.host.querySelector("[data-soc-card]");
    const chart = this.host.querySelector("[data-soc-chart]");
    const capacityIndicator = this.host.querySelector("[data-capacity-utilization]");
    if (!card || !chart || !capacityIndicator) return;
    const configured = Boolean(this._powerState?.soc_entity);
    card.hidden = !configured;
    if (!configured) {
      chart.replaceChildren();
      capacityIndicator.replaceChildren();
      return;
    }
    const capacityUtilizationPercent = this._capacityUtilizationPercent();
    const capacityLabel = Number.isFinite(capacityUtilizationPercent)
      ? `${this._formatNumber(capacityUtilizationPercent)} %`
      : "—";
    const capacityFill = Number.isFinite(capacityUtilizationPercent)
      ? Math.max(0, Math.min(100, capacityUtilizationPercent))
      : 0;
    capacityIndicator.innerHTML = `<div class="capacity-battery" role="img" aria-label="Kapacitetsutnyttjande ${capacityLabel}"><span class="capacity-battery-fill" style="height: ${capacityFill}%"></span><span class="capacity-battery-value">${capacityLabel}</span></div>`;
    const now = new Date();
    const dayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const dayEnd = new Date(dayStart);
    dayEnd.setDate(dayEnd.getDate() + 1);
    const points = (Array.isArray(this._powerHistory?.series?.soc?.points) ? this._powerHistory.series.soc.points : [])
      .map((point) => ({
        timestamp: new Date(point.timestamp).getTime(),
        value: Number(point.value_percent),
      }))
      .filter((point) => Number.isFinite(point.timestamp) && point.timestamp >= dayStart.getTime() && point.timestamp < dayEnd.getTime() && Number.isFinite(point.value))
      .sort((left, right) => left.timestamp - right.timestamp);
    if (!points.length) {
      chart.textContent = "Ingen historik idag";
      return;
    }
    const width = 960;
    const height = 340;
    const plot = { left: 32, right: 8, top: 8, bottom: 32 };
    const plotWidth = width - plot.left - plot.right;
    const plotHeight = height - plot.top - plot.bottom;
    const x = (timestamp) => plot.left + ((timestamp - dayStart.getTime()) / (dayEnd.getTime() - dayStart.getTime())) * plotWidth;
    const y = (value) => plot.top + (1 - Math.max(0, Math.min(100, value)) / 100) * plotHeight;
    const intervals = points.slice(1).map((point, index) => point.timestamp - points[index].timestamp).filter((interval) => interval > 0);
    const typicalInterval = intervals.length ? intervals.slice().sort((left, right) => left - right)[Math.floor(intervals.length / 2)] : 0;
    const maxGap = Math.max(30 * 60 * 1000, typicalInterval * 4, 2 * 60 * 60 * 1000);
    const segments = [];
    let segment = [points[0]];
    points.slice(1).forEach((point, index) => {
      if (point.timestamp - points[index].timestamp > maxGap) {
        segments.push(segment);
        segment = [];
      }
      segment.push(point);
    });
    segments.push(segment);
    const lineMarkup = segments.filter((segment) => segment.length >= 2).map((segment) => {
      const coordinates = segment.map((point) => `${x(point.timestamp)} ${y(point.value)}`).join(" L ");
      const area = `M ${x(segment[0].timestamp)} ${plot.top + plotHeight} L ${coordinates} L ${x(segment.at(-1).timestamp)} ${plot.top + plotHeight} Z`;
      return `<path class="soc-area" d="${area}" /><path class="soc-line" d="M ${coordinates}" />`;
    }).join("");
    const gridMarkup = [0, 25, 50, 75, 100].map((level) => `<line class="soc-gridline" x1="${plot.left}" y1="${y(level)}" x2="${width - plot.right}" y2="${y(level)}" /><text class="soc-label" x="2" y="${y(level) + 4}">${level}</text>`).join("");
    const timeLabels = [0, 6, 12, 18, 24].map((hour) => `<text class="soc-label" text-anchor="middle" x="${plot.left + (hour / 24) * plotWidth}" y="${height - 6}">${String(hour).padStart(2, "0")}</text>`).join("");
    chart.innerHTML = `<svg class="soc-chart-svg" preserveAspectRatio="none" viewBox="0 0 ${width} ${height}" role="img" aria-label="Batteriets laddnivå idag">
      ${gridMarkup}${lineMarkup}<g class="soc-hover" aria-hidden="true"></g>${timeLabels}
    </svg><div class="soc-tooltip" hidden></div>`;
    const svg = chart.querySelector(".soc-chart-svg");
    const tooltip = chart.querySelector(".soc-tooltip");
    const hover = chart.querySelector(".soc-hover");
    const clear = () => {
      tooltip.hidden = true;
      hover.replaceChildren();
    };
    const update = (event) => {
      const rect = svg.getBoundingClientRect();
      const timestamp = dayStart.getTime() + Math.max(0, Math.min(rect.width, event.clientX - rect.left)) / rect.width * (dayEnd.getTime() - dayStart.getTime());
      const point = points.reduce((nearest, candidate) => Math.abs(candidate.timestamp - timestamp) < Math.abs(nearest.timestamp - timestamp) ? candidate : nearest, points[0]);
      const pointX = x(point.timestamp);
      const pointY = y(point.value);
      tooltip.innerHTML = `<strong>${new Date(point.timestamp).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" })}</strong><span>Laddnivå: ${this._formatNumber(point.value)} %</span>`;
      tooltip.hidden = false;
      hover.innerHTML = `<circle class="chart-hover-marker chart-hover-marker-soc" cx="${pointX}" cy="${pointY}" r="4" />`;
      positionChartTooltip(chart, tooltip, event.clientX, event.clientY, [], this._tooltipOrbit);
    };
    svg.addEventListener("pointermove", update);
    svg.addEventListener("pointerdown", update);
    svg.addEventListener("pointerleave", clear);
    svg.addEventListener("pointercancel", clear);
  }

  _capacityUtilizationPercent() {
    const discharged = Number(this._powerState?.discharging_energy_kwh);
    const capacity = Number(this._powerState?.capacity_kwh);
    return Number.isFinite(discharged) && Number.isFinite(capacity) && capacity > 0
      ? discharged / capacity * 100
      : null;
  }

  async loadPowerState(loadHistory = false) {
    if (!this.hass?.callWS) return;
    try {
      const state = await this.hass.callWS({ type: "elrakning/power_state" });
      if (state?.success === false && state.error === "power_unavailable") return;
      this._applyPowerState(state);
      if (loadHistory) await this.loadPowerHistory();
    } catch {
      // Keep optional power cards unconfigured when state is unavailable.
    }
  }

  async loadPowerHistory() {
    if (!this.hass?.callWS) return;
    const requestToken = ++this._powerHistoryRequestToken;
    try {
      const response = await this.hass.callWS({ type: "elrakning/power_history" });
      if (response?.error === "power_unavailable") return;
      if (requestToken !== this._powerHistoryRequestToken) return;
      const series = response?.success && response?.series && typeof response.series === "object" ? response.series : {};
      for (const [key, points] of Object.entries(this._powerLivePoints)) {
        if (!points.size) continue;
        const merged = new Map((Array.isArray(series[key]?.points) ? series[key].points : []).map((point) => [point.timestamp, point]));
        for (const [timestamp, point] of points) merged.set(timestamp, point);
        series[key] = { ...(series[key] || {}), points: [...merged.values()].sort((left, right) => new Date(left.timestamp) - new Date(right.timestamp)) };
      }
      this._powerHistory = {
        date: response?.date || null,
        series,
      };
      this._refreshPowerEnergyState();
      if (this.host.querySelector(".price-chart")) this.renderPriceChart();
    } catch {
      if (requestToken !== this._powerHistoryRequestToken) return;
      this._powerHistory = { date: null, series: {} };
      this._refreshPowerEnergyState();
    }
  }

  _appendPowerState(eventData) {
    if (eventData?.state) {
      this._applyPowerState(eventData.state);
      for (const entry of eventData.points || []) this._appendPowerPoint(entry.series, entry.point);
      this._refreshPowerEnergyState();
      if (this.host.querySelector(".price-chart")) this.renderPriceChart();
    }
  }

  _resetPowerLivePoints() {
    for (const points of Object.values(this._powerLivePoints)) points.clear();
  }

  _appendPowerPoint(series, point) {
    const valueKey = series === "soc" ? "value_percent" : "value_kw";
    if (!(series in this._powerLivePoints) || !point?.timestamp || !Number.isFinite(Number(point[valueKey]))) return;
    const timestamp = new Date(point.timestamp);
    if (Number.isNaN(timestamp.getTime())) return;
    const date = timestamp.toLocaleDateString("sv-SE");
    if (this._powerHistory.date && date !== this._powerHistory.date) return;
    this._powerLivePoints[series].set(timestamp.toISOString(), {
      timestamp: timestamp.toISOString(),
      [valueKey]: Number(point[valueKey]),
    });
    const existing = Array.isArray(this._powerHistory.series?.[series]?.points)
      ? [...this._powerHistory.series[series].points]
      : [];
    const byTimestamp = new Map(existing.map((item) => [item.timestamp, item]));
    byTimestamp.set(timestamp.toISOString(), this._powerLivePoints[series].get(timestamp.toISOString()));
    this._powerHistory.series = {
      ...this._powerHistory.series,
      [series]: { ...(this._powerHistory.series?.[series] || {}), points: [...byTimestamp.values()].sort((left, right) => new Date(left.timestamp) - new Date(right.timestamp)) },
    };
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
      if (response?.success === false && response.error === "electricity_manager_unavailable") return;
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
      if (this._powerEventUnsubscribePromise) {
        Promise.resolve(this._powerEventUnsubscribePromise)
          .then((unsubscribe) => unsubscribe?.())
          .catch(() => {});
      }
      if (this._diagnosticsEventUnsubscribePromise) {
        Promise.resolve(this._diagnosticsEventUnsubscribePromise)
          .then((unsubscribe) => unsubscribe?.())
          .catch(() => {});
      }
      if (this._readyEventUnsubscribePromise) {
        Promise.resolve(this._readyEventUnsubscribePromise)
          .then((unsubscribe) => unsubscribe?.())
          .catch(() => {});
      }
      if (this._connectionReadyListener && this._eventConnection?.removeEventListener) {
        this._eventConnection.removeEventListener("ready", this._connectionReadyListener);
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
          const powerMapping = this._powerState || {};
          const powerEntities = [
            ...(Array.isArray(powerMapping.solar_entities) ? powerMapping.solar_entities : []),
            powerMapping.consumption_entity,
            powerMapping.charging_entity,
            powerMapping.discharging_entity,
            powerMapping.battery_power_entity,
            powerMapping.soc_entity,
            powerMapping.capacity_entity,
          ];
          if (powerEntities.includes(entityId)) this.loadPowerState();
        },
        "state_changed",
      );
      this._meterPowerEventUnsubscribePromise = hass.connection.subscribeEvents(
        (event) => this._appendMeterPowerPoint(event.data),
        "elrakning_meter_power_update",
      );
      this._powerEventUnsubscribePromise = hass.connection.subscribeEvents(
        (event) => this._appendPowerState(event.data),
        "elrakning_power_update",
      );
      this._diagnosticsEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => this._loadDiagnosticsState?.(),
        "elrakning_diagnostics_update",
      );
      this._readyEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => this._refreshBackendState(true),
        "elrakning_integration_ready",
      );
      this._connectionReadyListener = () => this._refreshBackendState(true);
      hass.connection.addEventListener?.("ready", this._connectionReadyListener);
      this._eventConnection = hass.connection;
      this._refreshBackendState(true);
    }
  }

  destroy() {
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
    if (this._powerEventUnsubscribePromise) {
      Promise.resolve(this._powerEventUnsubscribePromise)
        .then((unsubscribe) => unsubscribe?.())
        .catch(() => {});
    }
    if (this._diagnosticsEventUnsubscribePromise) {
      Promise.resolve(this._diagnosticsEventUnsubscribePromise)
        .then((unsubscribe) => unsubscribe?.())
        .catch(() => {});
    }
    if (this._readyEventUnsubscribePromise) {
      Promise.resolve(this._readyEventUnsubscribePromise)
        .then((unsubscribe) => unsubscribe?.())
        .catch(() => {});
    }
    if (this._connectionReadyListener && this._eventConnection?.removeEventListener) {
      this._eventConnection.removeEventListener("ready", this._connectionReadyListener);
    }
    this._eventUnsubscribePromise = null;
    this._greenelyEventUnsubscribePromise = null;
    this._meterEventUnsubscribePromise = null;
    this._meterPowerEventUnsubscribePromise = null;
    this._powerEventUnsubscribePromise = null;
    this._diagnosticsEventUnsubscribePromise = null;
    this._readyEventUnsubscribePromise = null;
    this._connectionReadyListener = null;
    this._backendHydrationPromise = null;
    this._loadDiagnosticsState = null;
    this._eventConnection = null;
    window.removeEventListener("resize", this._onThemeResize);
    window.removeEventListener("focus", this._onThemeFocus);
    document.removeEventListener("visibilitychange", this._onThemeVisibility);
    this._themeResizeObserver?.disconnect();
    this._themeResizeObserver = null;
    this._priceHeaderLayoutObserver?.disconnect();
    this._priceHeaderLayoutObserver = null;
    this._themeBackgroundReady = false;
  }

  async _refreshBackendState(loadHistory = true) {
    if (this._backendHydrationPromise) return this._backendHydrationPromise;
    this._backendHydrationPromise = Promise.all([
      this.loadPriceData(),
      this.loadProviderState(),
      this.loadRetainedHistory(),
      this.loadMeterState(loadHistory),
      this.loadPowerState(loadHistory),
      this._loadDebugPreference(),
      this._loadChartPreferences(),
    ]).finally(() => {
      this._backendHydrationPromise = null;
    });
    return this._backendHydrationPromise;
  }

  async loadPriceData() {
    if (!this.hass?.callWS) return;
    try {
      const response = await this.hass.callWS({ type: "elrakning/price_data" });
      if (response?.error === "integration_unavailable") return;
      this.priceSnapshot = response;
    } catch {
      return;
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
      if (state?.success === false && state.error === "electricity_manager_unavailable") return;
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
    const source = this.host.querySelector("[data-meter-source]");
    const label = providerLabel(state?.provider_name, state?.device_name);
    if (provider) {
      provider.textContent = label;
      provider.hidden = !label;
    }
    if (source) source.hidden = !this._debugEnabled || state?.configured !== true;
    this._renderMergedMeterSummary();
  }

  async loadMeterState(loadHistory = false) {
    if (!this.hass?.callWS) return;
    try {
      const state = await this.hass.callWS({ type: "elrakning/meter_state" });
      if (state?.success === false && state.error === "meter_unavailable") return;
      this._applyMeterState(state);
      if (loadHistory) await this.loadMeterPowerHistory();
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
    try {
      const request = { type: "elrakning/meter_power_history" };
      if (entityId) request.entity_id = entityId;
      const response = await this.hass.callWS(request);
      if (response?.error === "meter_unavailable") return;
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
      import_kw: normalizeMeterValue(point.import_kw),
      export_kw: normalizeMeterValue(point.export_kw),
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
        const forecast = document.createElement("span");
        forecast.className = "price-analysis-forecast";
        for (const sentenceText of upcoming.sentences || [upcoming.forecast]) {
          const sentence = document.createElement("span");
          sentence.className = "price-analysis-sentence";
          sentence.textContent = sentenceText;
          forecast.append(sentence);
        }
        analysis.append(status, forecast);
      } else {
        const forecast = document.createElement("span");
        forecast.className = "price-analysis-forecast";
        const sentence = document.createElement("span");
        sentence.className = "price-analysis-sentence";
        sentence.textContent = upcoming.forecast;
        forecast.append(sentence);
        analysis.append(forecast);
      }
    }
    const summary = { current, lowest, highest, average };
    for (const key of ["current", "lowest", "highest", "average"]) {
      const value = Number(summary[key]?.price) * 100;
      const element = this.host.querySelector(`[data-price="${key}"]`);
      if (element) {
        element.textContent = Number.isFinite(value) ? this.formatPrice(value) : "–";
        element.classList.remove("cheap", "normal", "expensive");
        if (key === "current" && currentCategory) element.classList.add(currentCategory);
        if (key === "lowest") element.classList.add("cheap");
        if (key === "highest") element.classList.add("expensive");
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
      const importKw = normalizeMeterValue(point.import_kw);
      const exportKw = normalizeMeterValue(point.export_kw);
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

  buildCanonicalPowerPoints(points, dayStart, dayEnd) {
    const canonical = this.buildCanonicalMeterPoints(
      (Array.isArray(points) ? points : []).map((point) => ({
        timestamp: point.timestamp,
        import_kw: point.value_kw,
        export_kw: 0,
      })),
      dayStart,
      dayEnd,
    );
    return canonical.map((point) => ({
      timestamp: point.timestamp,
      raw_timestamp: point.raw_timestamp,
      value_kw: point.import_kw,
      gap_before: point.gap_before,
    }));
  }

  buildMeterDisplaySegments(points, key) {
    return this.buildThresholdClippedSegments(points, key);
  }

  buildThresholdClippedSegments(points, key) {
    return buildThresholdClippedSegments(points, key);
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
      if (segment.coordinates.length === 1 && Math.abs(targetX - segment.coordinates[0].x) < 1) {
        return segment.coordinates[0].y;
      }
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

  buildMeterDisplayMarkup(points, key, className, x, meterY) {
    return this.buildMeterDisplaySegments(points, key).map((segment) => {
      if (segment.length < 2) return "";
      return `<path class="${className}" d="${this.buildSmoothMeterPath(segment, key, x, meterY)}" />`;
    }).join("");
  }

  buildMeterDisplayAreaMarkup(points, key, className, x, meterY) {
    return this.buildMeterDisplaySegments(points, key).map((segment) => {
      if (segment.length < 2) return "";
      const first = segment[0];
      const last = segment.at(-1);
      const firstX = x(first.timestamp);
      const lastX = x(last.timestamp);
      const baselineY = meterY(0);
      return `<path class="${className}" d="M ${firstX} ${baselineY} L ${firstX} ${meterY(first[key])} ${this.buildSmoothMeterPath(segment, key, x, meterY).slice(1)} L ${lastX} ${baselineY} Z" />`;
    }).join("");
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
    const visibleLayers = this._effectiveChartLayerState();
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
    const x = (timestamp) => plot.left + ((new Date(timestamp).getTime() - dayStart.getTime()) / dayDuration) * plotWidth;
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
    const powerCanonicalPoints = {};
    const powerDisplayPoints = {};
    const powerDisplayGeometry = {};
    for (const key of ["solar", "consumption", "charging", "discharging"]) {
      const rawPoints = Array.isArray(this._powerHistory?.series?.[key]?.points)
        ? this._powerHistory.series[key].points.filter((point) => {
          const timestamp = new Date(point.timestamp).getTime();
          return Number.isFinite(timestamp) && timestamp >= dayStart.getTime() && timestamp < dayEnd.getTime();
        })
        : [];
      powerCanonicalPoints[key] = this.buildCanonicalPowerPoints(rawPoints, dayStart, dayEnd);
      powerDisplayPoints[key] = powerCanonicalPoints[key].map((point) => ({
        ...point,
        value_kw: Number.isFinite(Number(point.value_kw)) ? Number(point.value_kw) : null,
      }));
    }
    this._powerCanonicalPointMaps = Object.fromEntries(
      Object.entries(powerCanonicalPoints).map(([key, points]) => [key, new Map(
        points.filter((point) => point.raw_timestamp !== null).map((point) => [point.timestamp, point]),
      )]),
    );
    const meterMaximum = Math.max(
      0,
      ...meterDisplayPoints.flatMap((point) => [Number(point.import_kw), Number(point.export_kw)])
        .filter(Number.isFinite),
      ...Object.values(powerDisplayPoints).flatMap((points) => points.map((point) => Number(point.value_kw)))
        .filter(Number.isFinite),
    );
    const meterBase = Math.max(10, meterMaximum);
    const meterMagnitude = 10 ** Math.floor(Math.log10(meterBase / 4));
    const meterNormalized = (meterBase / 4) / meterMagnitude;
    const meterStepFactor = meterNormalized <= 1 ? 1 : meterNormalized <= 2 ? 2 : meterNormalized <= 5 ? 5 : 10;
    const meterStep = meterStepFactor * meterMagnitude;
    const meterRange = Math.ceil(meterBase / meterStep) * meterStep;
    const meterY = (value) => plot.top + plotHeight - (Math.max(0, Number(value) || 0) / meterRange) * plotHeight;
    const meterLinesFor = (key, className, visible) => visible
      ? this.buildMeterDisplayMarkup(meterDisplayPoints, key, className, x, meterY)
      : "";
    const powerLinesFor = (key, className, visible) => {
      return visible
        ? this.buildMeterDisplayMarkup(powerDisplayPoints[key], "value_kw", className, x, meterY)
        : "";
    };
    const meterDisplayGeometry = {
      import_kw: this.buildMeterDisplayGeometry(meterDisplayPoints, "import_kw", x, meterY),
      export_kw: this.buildMeterDisplayGeometry(meterDisplayPoints, "export_kw", x, meterY),
    };
    for (const key of ["solar", "consumption", "charging", "discharging"]) {
      powerDisplayGeometry[key] = this.buildMeterDisplayGeometry(powerDisplayPoints[key] || [], "value_kw", x, meterY);
    }
    const meterLines = [
      meterLinesFor("import_kw", "chart-meter-import", visibleLayers.import),
      meterLinesFor("export_kw", "chart-meter-export", visibleLayers.export),
      powerLinesFor("solar", "chart-power-solar", visibleLayers.solar),
      powerLinesFor("consumption", "chart-power-consumption", visibleLayers.consumption),
      powerLinesFor("charging", "chart-power-charging", visibleLayers.charging),
      powerLinesFor("discharging", "chart-power-discharging", visibleLayers.discharging),
    ].join("");
    const meterAreas = [
      visibleLayers.solar
        ? this.buildMeterDisplayAreaMarkup(powerDisplayPoints.solar, "value_kw", "chart-power-area chart-power-area-solar", x, meterY)
        : "",
      visibleLayers.import
        ? this.buildMeterDisplayAreaMarkup(meterDisplayPoints, "import_kw", "chart-power-area chart-power-area-import", x, meterY)
        : "",
      visibleLayers.export
        ? this.buildMeterDisplayAreaMarkup(meterDisplayPoints, "export_kw", "chart-power-area chart-power-area-export", x, meterY)
        : "",
      visibleLayers.consumption
        ? this.buildMeterDisplayAreaMarkup(powerDisplayPoints.consumption, "value_kw", "chart-power-area chart-power-area-consumption", x, meterY)
        : "",
      visibleLayers.charging
        ? this.buildMeterDisplayAreaMarkup(powerDisplayPoints.charging, "value_kw", "chart-power-area chart-power-area-charging", x, meterY)
        : "",
      visibleLayers.discharging
        ? this.buildMeterDisplayAreaMarkup(powerDisplayPoints.discharging, "value_kw", "chart-power-area chart-power-area-discharging", x, meterY)
        : "",
    ].join("");
    const meterVisible = (meterDisplayPoints.some((point) => isVisiblePowerValue(point.import_kw) || isVisiblePowerValue(point.export_kw))
      && (visibleLayers.import || visibleLayers.export))
      || Object.entries(powerDisplayPoints).some(([key, points]) => visibleLayers[key]
        && points.some((point) => isVisiblePowerValue(point.value_kw)));
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
    const bars = visibleLayers.spot ? periods.map((period, index) => {
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
      ${meterAreas}
      ${meterLines}
      ${visibleLayers.average ? `<line class="chart-average" x1="${plot.left}" y1="${y(average)}" x2="${width - plot.right}" y2="${y(average)}" />` : ""}
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

  _buildVisibleTooltipRows(comparisonPrice, details, layers = this._chartLayerState()) {
    const rows = [];
    if (layers.spot && Number.isFinite(comparisonPrice)) {
      rows.push(`<span class="tooltip-value">Spotpris: ${this.formatPrice(comparisonPrice)}</span>`);
    }
    if (layers.import && isVisiblePowerValue(details?.import_kw)) {
      rows.push(`<span class="tooltip-value tooltip-meter-import">Import: ${this._formatNumber(details.import_kw)} kW</span>`);
    }
    if (layers.export && isVisiblePowerValue(details?.export_kw)) {
      rows.push(`<span class="tooltip-value tooltip-meter-export">Export: ${this._formatNumber(details.export_kw)} kW</span>`);
    }
    const powerRows = [
      ["solar", "Sol", "tooltip-power-solar"],
      ["consumption", "Last", "tooltip-power-consumption"],
      ["charging", "Laddning", "tooltip-power-charging"],
      ["discharging", "Urladdning", "tooltip-power-discharging"],
    ];
    for (const [key, label, className] of powerRows) {
      if (layers[key] && isVisiblePowerValue(details?.[`${key}_kw`])) {
        rows.push(`<span class="tooltip-value ${className}">${label}: ${this._formatNumber(details[`${key}_kw`])} kW</span>`);
      }
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
      const visibleLayers = this._effectiveChartLayerState();
      const time = this.formatTime(new Date(tooltipTimestamp));
      const comparisonPrice = this._comparisonPrice(period);
      const value = visibleLayers.spot && Number.isFinite(comparisonPrice)
        ? `${this.formatPrice(comparisonPrice)} öre/kWh`
        : "";
      const index = this.priceData.periods.indexOf(period);
      const canonicalMeterPoint = this._meterCanonicalPointAt(tooltipTimestamp);
      const rawMeterPoint = this._meterPointAtNearest(tooltipTimestamp);
      const meterValue = (key) => canonicalMeterPoint && Number.isFinite(Number(canonicalMeterPoint[key]))
        ? Number(canonicalMeterPoint[key])
        : null;
      const powerValue = (key) => {
        const point = this._powerCanonicalPointMaps?.[key]?.get(tooltipTimestamp);
        return point && Number.isFinite(Number(point.value_kw)) ? Number(point.value_kw) : null;
      };
      const barPrice = this._chartBarPrices?.[index];
      const hoverSnapshot = {
        hoverTime: tooltipTimestamp,
        meterSampleTime: canonicalMeterPoint ? canonicalMeterPoint.timestamp : null,
        priceBarValue: barPrice ?? null,
        importValue: meterValue("import_kw"),
        exportValue: meterValue("export_kw"),
        pvValue: powerValue("solar"),
        loadValue: powerValue("consumption"),
        chargeValue: powerValue("charging"),
        dischargeValue: powerValue("discharging"),
      };
      const baseDetails = this._chartTooltipDetails?.get(index) || {};
      const details = this._debugEnabled ? { ...baseDetails } : null;
      if (details) {
        if (!rawMeterPoint || !Number.isFinite(Number(rawMeterPoint.import_kw))) delete details.import_kw;
        else details.import_kw = Number(rawMeterPoint.import_kw);
        if (!rawMeterPoint || !Number.isFinite(Number(rawMeterPoint.export_kw))) delete details.export_kw;
        else details.export_kw = Number(rawMeterPoint.export_kw);
        for (const [key, snapshotKey] of [["solar", "pvValue"], ["consumption", "loadValue"], ["charging", "chargeValue"], ["discharging", "dischargeValue"]]) {
          const value = hoverSnapshot[snapshotKey];
          if (Number.isFinite(value)) details[`${key}_kw`] = value;
          else delete details[`${key}_kw`];
        }
      }
      const tooltipRows = this._buildVisibleTooltipRows(comparisonPrice, {
        import_kw: hoverSnapshot.importValue,
        export_kw: hoverSnapshot.exportValue,
        solar_kw: hoverSnapshot.pvValue,
        consumption_kw: hoverSnapshot.loadValue,
        charging_kw: hoverSnapshot.chargeValue,
        discharging_kw: hoverSnapshot.dischargeValue,
      }, visibleLayers);
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
        if (visibleLayers.spot && Number.isFinite(hoverSnapshot.priceBarValue)) {
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-spot" cx="${priceMarkerX}" cy="${hoverGeometry.y(hoverSnapshot.priceBarValue)}" r="4" />`);
        }
        const importDisplayY = meterMarkerX === null
          ? null
          : hoverGeometry.meterDisplayY("import_kw", hoverSnapshot.meterSampleTime);
        if (visibleLayers.import && meterMarkerX !== null && isVisiblePowerValue(hoverSnapshot.importValue) && Number.isFinite(importDisplayY)) {
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-import" cx="${meterMarkerX}" cy="${importDisplayY}" r="4" />`);
        }
        const exportDisplayY = meterMarkerX === null
          ? null
          : hoverGeometry.meterDisplayY("export_kw", hoverSnapshot.meterSampleTime);
        if (visibleLayers.export && meterMarkerX !== null && isVisiblePowerValue(hoverSnapshot.exportValue) && Number.isFinite(exportDisplayY)) {
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-export" cx="${meterMarkerX}" cy="${exportDisplayY}" r="4" />`);
        }
        const powerMarkers = [
          ["solar", "pvValue", "solar"],
          ["consumption", "loadValue", "consumption"],
          ["charging", "chargeValue", "charging"],
          ["discharging", "dischargeValue", "discharging"],
        ];
        for (const [key, snapshotKey, className] of powerMarkers) {
          const value = hoverSnapshot[snapshotKey];
          if (!visibleLayers[key] || !isVisiblePowerValue(value)) continue;
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-${className}" cx="${priceMarkerX}" cy="${hoverGeometry.meterY(value)}" r="4" />`);
        }
        hoverMarkers.innerHTML = markers.join("");
      }
      tooltip.classList.toggle("debug-tooltip", Boolean(details));
      tooltip.title = "";
      tooltip.hidden = false;
      const obstacles = [
        ...svg.querySelectorAll(".chart-hover-marker"),
      ];
      positionChartTooltip(chart, tooltip, event.clientX, event.clientY, obstacles, this._tooltipOrbit);
    };
    const clearHoverMarkers = () => {
      const hoverMarkers = svg.querySelector(".chart-hover-markers");
      if (hoverMarkers) hoverMarkers.replaceChildren();
    };
    const hasVisibleTooltipLayer = this._spotBarsVisible
      || this._meterPowerVisible.import
      || this._meterPowerVisible.export
      || Object.keys(this._previewLayersVisible).some((key) => this._previewLayersVisible[key]);
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
        tooltip.hidden = true;
      }
    });
    svg.addEventListener("mouseleave", () => {
      clearHoverMarkers();
      tooltip.hidden = true;
    });
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
      if (!hasVisibleTooltipLayer || !insidePlot(touch.clientX, touch.clientY)) {
        clearHoverMarkers();
        tooltip.hidden = true;
        this._chartTouch = null;
        return;
      }
      const hit = periodAt(touch.clientX);
      if (!hit) return;
      this._chartTouch = {
        active: true,
      };
      show(hit.period, touch, hit.tooltipTimestamp);
    }, { passive: true });
    chart.addEventListener("touchmove", (event) => {
      const state = this._chartTouch;
      const touch = event.touches[0];
      if (!state || !touch) return;
      if (!hasVisibleTooltipLayer || !insidePlot(touch.clientX, touch.clientY)) {
        clearHoverMarkers();
        tooltip.hidden = true;
        return;
      }
      const hit = periodAt(touch.clientX);
      if (hit) show(hit.period, touch, hit.tooltipTimestamp);
    }, { passive: true });
    const clearTouchHover = () => {
      this._chartTouch = null;
      clearHoverMarkers();
      tooltip.hidden = true;
    };
    chart.addEventListener("touchend", clearTouchHover, { passive: true });
    chart.addEventListener("touchcancel", clearTouchHover, { passive: true });
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
