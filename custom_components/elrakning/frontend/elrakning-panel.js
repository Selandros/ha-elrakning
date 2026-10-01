export const CHART_COLORS = Object.freeze({
  priceCheap: "#67C98C",
  priceNormal: "#B9A05D",
  priceExpensive: "#E4687D",
  solar: "#77C2A1",
  solarForecast: "#4F8F72",
  consumption: "#E87570",
  import: "#F0A06A",
  export: "#72AAF6",
  charging: "#B76A8F",
  discharging: "#DF5C8A",
  soc: "#77C2A1",
  socEstimated: "#5F9F82",
  neutral: "#8590A6",
  phaseL1: "#77C2A1",
  phaseL2: "#72AAF6",
  phaseL3: "#F0A06A",
});

export function chartColor(key) {
  return CHART_COLORS[key] || CHART_COLORS.neutral;
}

export const PHASE_COLOR_MAP = Object.freeze({
  l1: chartColor("phaseL1"),
  l2: chartColor("phaseL2"),
  l3: chartColor("phaseL3"),
});

function chartSeriesColor(className) {
  const colors = [
    ["chart-meter-import", "import"],
    ["chart-meter-export", "export"],
    ["chart-power-solar", "solar"],
    ["chart-power-consumption", "consumption"],
    ["chart-power-charging", "charging"],
    ["chart-power-discharging", "discharging"],
  ];
  const match = colors.find(([classToken]) => String(className).split(" ").includes(classToken));
  return chartColor(match?.[1] || "neutral");
}

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
    performance: "Performance",
    websocket: "Websocket",
    frontend_power_flow: "Frontend power flow",
  }[component] || component || "Elräkning";
}

export function providerLabel(providerName, agreementName) {
  return [providerName, agreementName]
    .filter((value) => typeof value === "string" && value.trim())
    .map((value) => value.trim())
    .join(" · ");
}

export function invoicePeriodLabel(invoice) {
  if (!invoice || typeof invoice !== "object") return null;
  for (const key of ["month", "billing_period"]) {
    const value = invoice[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

export function buildGridSourceCost(estimate, fallback = null) {
  const grid = estimate?.grid;
  if (!grid || typeof grid !== "object") return fallback;
  const existing = fallback && typeof fallback === "object" ? fallback : {};
  return {
    total_sek: grid.total_so_far_sek ?? null,
    fixed_sek: grid.accrued_fixed_fee_sek ?? null,
    variable_sek: grid.variable_cost_sek ?? null,
    imported_kwh: estimate.imported_kwh_so_far ?? null,
    subscription_sek_per_month: grid.fixed_fee_sek ?? existing.subscription_sek_per_month ?? null,
    transfer_ore_per_kwh: estimate.grid_transfer_ore_per_kwh_gross ?? existing.transfer_ore_per_kwh ?? null,
    energy_tax_ore_per_kwh: estimate.grid_energy_tax_ore_per_kwh_gross ?? existing.energy_tax_ore_per_kwh ?? null,
    variable_grid_ore_per_kwh: estimate.grid_weighted_average_ore_per_kwh ?? existing.variable_grid_ore_per_kwh ?? null,
    source: "canonical_invoice_estimate.grid",
  };
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

/**
 * Build a bounded display-only series while retaining extrema in each bucket.
 * The source array and its point objects are never mutated.
 */
export function decimateDisplayPoints(points, {
  targetPoints = 1024,
  valueKeys = ["value_kw", "import_kw", "export_kw"],
} = {}) {
  const source = Array.isArray(points) ? points : [];
  const budget = Math.max(2, Math.floor(Number(targetPoints) || 0));
  if (source.length <= budget) return source.slice();
  const bucketCount = Math.max(1, Math.floor(budget / 4));
  const bucketSize = Math.ceil(source.length / bucketCount);
  const output = [];
  for (let start = 0; start < source.length; start += bucketSize) {
    const end = Math.min(source.length, start + bucketSize);
    const candidates = new Set([start, end - 1]);
    for (const key of valueKeys) {
      let minimumIndex = null;
      let maximumIndex = null;
      let minimum = Infinity;
      let maximum = -Infinity;
      for (let index = start; index < end; index += 1) {
        const value = Number(source[index]?.[key]);
        if (!Number.isFinite(value)) continue;
        if (value < minimum) {
          minimum = value;
          minimumIndex = index;
        }
        if (value > maximum) {
          maximum = value;
          maximumIndex = index;
        }
      }
      if (minimumIndex !== null) candidates.add(minimumIndex);
      if (maximumIndex !== null) candidates.add(maximumIndex);
    }
    [...candidates].sort((left, right) => left - right).forEach((index) => output.push(source[index]));
  }
  return output;
}

export function normalizeMeterValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function localDateKey(value) {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString("sv-SE") : null;
}

function roundDiagnosticMs(value) {
  return Math.round(Number(value) * 1000) / 1000;
}

const DIAGNOSTIC_ERROR_MESSAGE_LIMIT = 512;
const DIAGNOSTIC_ERROR_STACK_LIMIT = 2048;

export function sanitizeDiagnosticError(error) {
  const redact = (value, limit) => String(value || "")
    .replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, "[redacted-id]")
    .replace(/\b(?:[0-9a-f]{16,}|\d{10,})\b/gi, "[redacted-token]")
    .slice(0, limit);
  return {
    error_name: String(error?.name || "Error").slice(0, 96),
    error_message: redact(error?.message, DIAGNOSTIC_ERROR_MESSAGE_LIMIT),
    error_stack: redact(error?.stack, DIAGNOSTIC_ERROR_STACK_LIMIT),
  };
}

function localDayStart(value) {
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? new Date(date.getFullYear(), date.getMonth(), date.getDate())
    : null;
}

function nextForecastBoundary(now) {
  const boundary = new Date(now);
  const minutes = boundary.getMinutes();
  const remainder = minutes % 15;
  boundary.setMinutes(minutes - remainder + 15, 0, 0);
  return boundary;
}

function forecastModelRank(frame) {
  const modelVersion = frame?.quality?.model_version
    || frame?.provenance?.model_version
    || frame?.points?.[0]?.point?.model_version
    || "";
  return modelVersion === "load-profile-v2" ? 2 : 1;
}

export function selectLoadForecastPoints(frames, { siteId = null, selectedDate = new Date(), now = new Date() } = {}) {
  const dayStart = localDayStart(selectedDate);
  if (!dayStart) return [];
  const dayEnd = new Date(dayStart);
  dayEnd.setDate(dayEnd.getDate() + 1);
  const todayStart = localDayStart(now);
  if (!todayStart) return [];
  const dayKey = localDateKey(dayStart);
  const todayKey = localDateKey(todayStart);
  if (dayKey < todayKey) return [];
  const firstVisible = dayKey === todayKey ? nextForecastBoundary(now) : dayStart;
  const candidates = (Array.isArray(frames) ? frames : [])
    .filter((frame) => (frame?.logical_role === "load.forecast" || frame?.payload_schema === "load_forecast.v1")
      && (!siteId || frame.site_id === siteId)
      && Array.isArray(frame.points)
      && frame.points.some((point) => {
        const timestamp = new Date(point?.valid_at).getTime();
        return Number.isFinite(timestamp) && timestamp >= dayStart.getTime() && timestamp < dayEnd.getTime();
      }))
    .sort((left, right) => {
      const modelOrder = forecastModelRank(left) - forecastModelRank(right);
      if (modelOrder) return modelOrder;
      const knownOrder = new Date(left.known_at || 0).getTime() - new Date(right.known_at || 0).getTime();
      if (knownOrder) return knownOrder;
      const revisionOrder = Number(left.revision || 0) - Number(right.revision || 0);
      return revisionOrder || String(left.frame_id || "").localeCompare(String(right.frame_id || ""));
    });
  const frame = candidates.at(-1);
  if (!frame) return [];
  const points = new Map();
  for (const point of frame.points) {
    const timestamp = new Date(point?.valid_at).getTime();
    const value = Number(point?.value);
    if (!Number.isFinite(timestamp) || !Number.isFinite(value)
      || timestamp < firstVisible.getTime() || timestamp >= dayEnd.getTime()) continue;
    points.set(timestamp, { timestamp, value_kw: value / 1000 });
  }
  return [...points.values()].sort((left, right) => left.timestamp - right.timestamp);
}

function forecastPointValueKw(point) {
  for (const key of ["value_kw", "forecast_value_kw", "estimated_value_kw"]) {
    const value = Number(point?.[key]);
    if (Number.isFinite(value)) return value;
  }
  const watts = Number(point?.value_w ?? point?.forecast_value_w ?? point?.estimated_value_w);
  return Number.isFinite(watts) ? watts / 1000 : null;
}

function forecastPointIsMarked(point) {
  const classification = String(
    point?.classification
      || point?.data_kind
      || point?.provenance?.classification
      || "",
  ).toLowerCase();
  return point?.forecast === true
    || point?.estimated === true
    || point?.predicted === true
    || ["forecast", "estimated", "predicted"].includes(classification);
}

function selectForecastPointsFromFrames(frames, {
  siteId = null,
  selectedDate = new Date(),
  now = new Date(),
  logicalRole = null,
  includeElapsed = false,
} = {}) {
  const dayStart = localDayStart(selectedDate);
  const todayStart = localDayStart(now);
  if (!dayStart || !todayStart) return [];
  const dayEnd = new Date(dayStart);
  dayEnd.setDate(dayEnd.getDate() + 1);
  const dayKey = localDateKey(dayStart);
  const todayKey = localDateKey(todayStart);
  if (dayKey < todayKey) return [];
  const firstVisible = !includeElapsed && dayKey === todayKey ? nextForecastBoundary(now) : dayStart;
  const candidates = (Array.isArray(frames) ? frames : [])
    .filter((frame) => (!logicalRole || frame?.logical_role === logicalRole)
      && (!siteId || !frame?.site_id || frame.site_id === siteId)
      && Array.isArray(frame?.points)
      && frame.points.some((point) => {
        const timestamp = new Date(point?.valid_at || point?.timestamp).getTime();
        return Number.isFinite(timestamp) && timestamp >= dayStart.getTime() && timestamp < dayEnd.getTime();
      }))
    .sort((left, right) => {
      const knownOrder = new Date(left.known_at || 0).getTime() - new Date(right.known_at || 0).getTime();
      if (knownOrder) return knownOrder;
      const revisionOrder = Number(left.revision || 0) - Number(right.revision || 0);
      return revisionOrder || String(left.frame_id || "").localeCompare(String(right.frame_id || ""));
    });
  const frame = candidates.at(-1);
  if (!frame) return [];
  const points = new Map();
  for (const point of frame.points) {
    const timestamp = new Date(point?.valid_at || point?.timestamp).getTime();
    const valueKw = forecastPointValueKw(point);
    if (!Number.isFinite(timestamp) || !Number.isFinite(valueKw)
      || timestamp < firstVisible.getTime() || timestamp >= dayEnd.getTime()
      || (siteId && point?.site_id && point.site_id !== siteId)) continue;
    points.set(timestamp, { timestamp, value_kw: valueKw, forecast: true });
  }
  return [...points.values()].sort((left, right) => left.timestamp - right.timestamp);
}

export function selectPowerForecastPoints(source, {
  siteId = null,
  selectedDate = new Date(),
  now = new Date(),
  includeElapsed = false,
} = {}) {
  if (!source || typeof source !== "object") return [];
  const frames = [];
  for (const key of ["forecast_frames", "estimated_frames", "forecast", "estimate"]) {
    const value = source[key];
    if (Array.isArray(value)) frames.push(...value.map((item) => Array.isArray(item?.points) ? item : { points: [item] }));
    else if (Array.isArray(value?.points)) frames.push(value);
  }
  for (const key of ["forecast_points", "estimated_points", "predicted_points"]) {
    if (Array.isArray(source[key])) frames.push({ points: source[key] });
  }
  if (Array.isArray(source.points)) {
    const marked = source.points.filter(forecastPointIsMarked);
    if (marked.length) frames.push({ points: marked });
  }
  return selectForecastPointsFromFrames(frames, { siteId, selectedDate, now, includeElapsed });
}

export function mergePowerHistoryRefreshState({ response, series, existingState = {}, contextKey, previousContextKey } = {}) {
  const unavailableForecast = { schema: "ella_power_forecast.v1", available: false, series: {} };
  const sameContext = contextKey && contextKey === previousContextKey;
  return {
    date: response?.date || null,
    series: series || {},
    power_forecast: sameContext ? (existingState.power_forecast || unavailableForecast) : unavailableForecast,
    solar_analysis: { available: false, days: [] },
    solar_forecast: { available: false },
    solar_forecast_baselines: {},
    solar_shadow: { available: false, days: [] },
    solar_evidence: existingState.solar_evidence || { available: false, days: [] },
    solar_weather: { available: false, source: "smhi", status: "unavailable", current: {}, hourly_forecast: [] },
    solar_sun: { available: false },
    solar_pvgis: { available: false, source: "jrc_pvgis" },
    solar_open_meteo: { available: false, source: "open_meteo" },
  };
}

export function mergePowerHistoryEnrichmentState({ response, existingState = {} } = {}) {
  const unavailableForecast = { schema: "ella_power_forecast.v1", available: false, series: {} };
  const responseForecast = response && typeof response === "object" ? response.power_forecast : undefined;
  const powerForecast = responseForecast && typeof responseForecast === "object"
    ? responseForecast
    : existingState.power_forecast || unavailableForecast;
  return {
    ...existingState,
    power_forecast: powerForecast,
    solar_analysis: response?.solar_analysis || { available: false, days: [] },
    solar_forecast: response?.solar_forecast || { available: false },
    solar_forecast_baselines: response?.solar_forecast_baselines || response?.solar_forecast?.baselines || {},
    solar_shadow: response?.solar_shadow || { available: false, days: [] },
    solar_weather: response?.solar_weather || { available: false, source: "smhi", status: "unavailable", current: {}, hourly_forecast: [] },
    solar_sun: response?.solar_sun || { available: false },
    solar_pvgis: response?.solar_pvgis || existingState.solar_pvgis || { available: false, source: "jrc_pvgis" },
    solar_open_meteo: response?.solar_open_meteo || existingState.solar_open_meteo || { available: false, source: "open_meteo" },
  };
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

export function buildDailyObservedMaxima(powerHistory = {}, meterHistory = {}, now = new Date()) {
  const date = localDateKey(now);
  const maxFor = (points, value) => (Array.isArray(points) ? points : [])
    .filter((point) => localDateKey(point?.timestamp) === date)
    .map((point) => Math.abs(Number(value(point))))
    .filter(Number.isFinite)
    .reduce((maximum, current) => Math.max(maximum, current), 0);
  const series = powerHistory?.series || {};
  const meterPoints = Array.isArray(meterHistory?.points) ? meterHistory.points : [];
  const gridMaximum = meterPoints
    .filter((point) => localDateKey(point?.timestamp) === date)
    .map((point) => Math.max(Math.abs(Number(point.import_kw)), Math.abs(Number(point.export_kw))))
    .filter(Number.isFinite)
    .reduce((maximum, current) => Math.max(maximum, current), 0);
  return {
    date,
    house: maxFor(series.consumption?.points, (point) => point.value_kw),
    solar: maxFor(series.solar?.points, (point) => point.value_kw),
    grid: gridMaximum,
    battery: Math.max(
      maxFor(series.charging?.points, (point) => point.value_kw),
      maxFor(series.discharging?.points, (point) => point.value_kw),
    ),
  };
}

export function buildLivePowerTiles(powerState = {}, meterState = {}, maxima = {}) {
  const finiteMagnitude = (value) => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : null;
  const houseConfigured = Boolean(powerState.consumption_entity);
  const solarConfigured = Array.isArray(powerState.solar_entities) && powerState.solar_entities.some(Boolean);
  const batteryConfigured = Boolean(
    powerState.battery_power_entity
    || powerState.charging_entity
    || powerState.discharging_entity
    || powerState.soc_entity
    || powerState.capacity_entity,
  );
  const gridConfigured = meterState.configured === true && Boolean(meterState.power_entity);
  const house = finiteMagnitude(powerState.consumption_kw);
  const solar = finiteMagnitude(powerState.solar_kw);
  const gridPower = meterState.power_kw == null ? null : Number(meterState.power_kw);
  let grid = { value: null, status: gridConfigured ? "Ej tillgängligt" : "Ej konfigurerad", direction: null };
  if (gridConfigured && Number.isFinite(gridPower)) {
    const normalized = displayPowerValue(gridPower);
    grid = normalized === 0
      ? { value: 0, status: "Ingen överföring", direction: null }
      : normalized > 0
        ? { value: normalized, status: "Importerar", direction: "import" }
        : { value: Math.abs(normalized), status: "Exporterar", direction: "export" };
  }
  const fuseAmpere = gridConfigured ? Number(meterState.facility?.fuse_ampere ?? meterState.fuse_ampere) : NaN;
  const phaseValues = gridConfigured && meterState.phase_current_a && typeof meterState.phase_current_a === "object"
    ? Object.fromEntries(["l1", "l2", "l3"].map((phase) => [phase, meterState.phase_current_a[phase] == null ? null : Number(meterState.phase_current_a[phase])]))
    : {};
  const validPhaseValues = Object.values(phaseValues).filter(Number.isFinite);
  const maxPhaseCurrentA = validPhaseValues.length ? Math.max(...validPhaseValues.map((value) => Math.abs(value))) : null;
  const fuseUtilizationPercent = Number.isFinite(maxPhaseCurrentA) && Number.isFinite(fuseAmpere) && fuseAmpere > 0
    ? maxPhaseCurrentA / fuseAmpere * 100
    : null;
  grid = { ...grid, colorKey: grid.direction || "neutral", fuseAmpere: Number.isFinite(fuseAmpere) ? fuseAmpere : null, phaseCurrentA: phaseValues, maxPhaseCurrentA, fuseUtilizationPercent };
  const charging = finiteMagnitude(powerState.charging_kw);
  const discharging = finiteMagnitude(powerState.discharging_kw);
  const chargingActive = charging !== null && charging > POWER_DISPLAY_THRESHOLD_KW;
  const dischargingActive = discharging !== null && discharging > POWER_DISPLAY_THRESHOLD_KW;
  const battery = !batteryConfigured
    ? { value: null, status: "Ej konfigurerad", direction: null, colorKey: "neutral", charging, discharging }
    : chargingActive && dischargingActive
    ? { value: null, status: "Inkonsekvent data", direction: "invalid", colorKey: "neutral", charging, discharging }
    : chargingActive
      ? { value: charging, status: "Laddar", direction: "charging", colorKey: "charging", charging, discharging }
      : dischargingActive
        ? { value: discharging, status: "Urladdar", direction: "discharging", colorKey: "discharging", charging, discharging }
      : { value: 0, status: "Ingen aktivitet", direction: null, colorKey: "neutral", charging, discharging };
  const withScale = (tile, key) => {
    const current = Number.isFinite(tile.value) ? Math.abs(tile.value) : 0;
    const maxToday = Math.max(0, Number.isFinite(Number(maxima[key])) ? Number(maxima[key]) : current);
    const scaleMax = Math.max(1, maxToday);
    return { ...tile, maxToday, scaleMax, fillPercent: Math.max(0, Math.min(100, current / scaleMax * 100)) };
  };
  return {
    house: withScale({ value: houseConfigured ? house : null, status: houseConfigured ? (house === null ? "Ej tillgängligt" : "Förbrukar") : "Ej konfigurerad", colorKey: "consumption" }, "house"),
    solar: withScale({ value: solarConfigured ? solar : null, status: solarConfigured ? (solar === null ? "Ej tillgängligt" : solar === 0 ? "Ingen produktion" : "Producerar") : "Ej konfigurerad", colorKey: solarConfigured && solar === 0 ? "neutral" : "solar" }, "solar"),
    grid: withScale(grid, "grid"),
    battery: withScale(battery, "battery"),
  };
}

export function mergeDailyPhaseMaxima(dailyPhaseMax = {}, phaseCurrentA = {}, timestamp = new Date()) {
  const next = { ...(dailyPhaseMax || {}) };
  const timestampValue = timestamp instanceof Date ? timestamp : new Date(timestamp);
  const timestampText = Number.isNaN(timestampValue.getTime()) ? null : timestampValue.toISOString();
  for (const phase of ["l1", "l2", "l3"]) {
    const raw = phaseCurrentA?.[phase];
    const value = raw == null ? NaN : Number(raw);
    if (!Number.isFinite(value)) continue;
    const magnitude = Math.abs(value);
    const previous = Number(next[phase]?.ampere);
    if (!Number.isFinite(previous) || magnitude > previous) next[phase] = { ampere: magnitude, raw_value: value, timestamp: timestampText };
  }
  return next;
}

export function buildDailyMaxPhase(dailyPhaseMax = {}, fuseAmpere = null) {
  const winner = ["l1", "l2", "l3"].reduce((best, phase) => {
    const item = dailyPhaseMax?.[phase];
    const ampere = Number(item?.ampere);
    return Number.isFinite(ampere) && (!best || ampere > best.ampere) ? { phase, item, ampere } : best;
  }, null);
  if (!winner) return null;
  const fuse = Number(fuseAmpere);
  const utilization = Number.isFinite(fuse) && fuse > 0 ? winner.ampere / fuse * 100 : null;
  return {
    phase: winner.phase,
    ampere: winner.ampere,
    raw_value: winner.item.raw_value ?? null,
    timestamp: winner.item.timestamp ?? null,
    fuse_ampere: Number.isFinite(fuse) && fuse > 0 ? fuse : null,
    utilization_percent: utilization,
  };
}

export function mergePhaseHistory(existing = {}, incoming = {}) {
  const merged = { ...(existing || {}) };
  for (const metric of ["current", "voltage", "active_power"]) {
    const incomingMetric = incoming?.[metric];
    if (!incomingMetric || typeof incomingMetric !== "object") continue;
    const currentMetric = { ...(merged[metric] || {}) };
    for (const phase of ["l1", "l2", "l3"]) {
      const incomingSeries = incomingMetric[phase];
      if (!incomingSeries || typeof incomingSeries !== "object" || !Array.isArray(incomingSeries.points)) continue;
      const existingSeries = currentMetric[phase] || {};
      const pointsByTimestamp = new Map(
        (Array.isArray(existingSeries.points) ? existingSeries.points : [])
          .filter((point) => point?.timestamp)
          .map((point) => [point.timestamp, point]),
      );
      for (const point of incomingSeries.points) {
        if (point?.timestamp) pointsByTimestamp.set(point.timestamp, point);
      }
      const points = [...pointsByTimestamp.values()].sort((left, right) => new Date(left.timestamp) - new Date(right.timestamp));
      currentMetric[phase] = { ...existingSeries, ...incomingSeries, points: points.slice(-2000) };
    }
    merged[metric] = currentMetric;
  }
  return merged;
}

export function createMeterPowerHistoryState(date = null) {
  return {
    date,
    points: [],
    phase_current_history: {},
    phase_history: {},
    phase_source_entities: {},
    phase_discovery_method: null,
    daily_phase_max: {},
    daily_max_phase: null,
    daily_max_phase_current_a: null,
    daily_max_fuse_utilization_percent: null,
    phase_current_source_entities: {},
    phase_current_discovery_method: null,
    loaded_at: null,
    last_live_merge_at: null,
    last_live_timestamp: null,
  };
}

export function mergeMeterPowerHistoryPoint(history = {}, point = {}, powerEntityId = null) {
  let next = { ...history };
  let phaseRenderChanged = false;
  if (point?.phase_current_a || point?.phase_voltage_v || point?.phase_active_power_kw) {
    const timestamp = point.timestamp || new Date().toISOString();
    let phaseHistory = history.phase_history || {};
    for (const [metric, values] of [["current", point.phase_current_a], ["voltage", point.phase_voltage_v], ["active_power", point.phase_active_power_kw]]) {
      if (!values || typeof values !== "object") continue;
      const timestampMs = Date.parse(timestamp);
      const sameTimestamp = (candidate) => {
        const candidateMs = Date.parse(candidate);
        return Number.isFinite(timestampMs) && Number.isFinite(candidateMs)
          ? candidateMs === timestampMs
          : candidate === timestamp;
      };
      for (const phase of ["l1", "l2", "l3"]) {
        const raw = values[phase];
        const value = raw == null ? NaN : Number(raw);
        if (!Number.isFinite(value)) continue;
        const storedValue = metric === "current" ? Math.abs(value) : value;
        const existingSeries = phaseHistory[metric]?.[phase] || {};
        const existingPoints = Array.isArray(existingSeries.points) ? existingSeries.points : [];
        const lastIndex = existingPoints.length - 1;
        const index = lastIndex >= 0 && sameTimestamp(existingPoints[lastIndex]?.timestamp)
          ? lastIndex
          : existingPoints.findIndex((item) => sameTimestamp(item.timestamp));
        if (index >= 0 && existingPoints[index]?.value === storedValue) continue;
        const points = [...existingPoints];
        const nextPoint = { timestamp: index >= 0 ? existingPoints[index].timestamp : timestamp, value: storedValue };
        if (index >= 0) points[index] = { ...points[index], ...nextPoint }; else points.push(nextPoint);
        points.sort((left, right) => new Date(left.timestamp) - new Date(right.timestamp));
        const nextMetric = { ...(phaseHistory[metric] || {}) };
        nextMetric[phase] = { ...existingSeries, points: points.slice(-2000) };
        phaseHistory = { ...phaseHistory, [metric]: nextMetric };
        phaseRenderChanged = true;
      }
    }
    next = { ...next, phase_history: phaseHistory, last_live_merge_at: new Date().toISOString(), last_live_timestamp: timestamp };
  }
  if (!point?.timestamp || (point.entity_id && point.entity_id !== powerEntityId)) return { history: next, phaseRenderChanged };
  const timestamp = new Date(point.timestamp);
  if (Number.isNaN(timestamp.getTime())) return { history: next, phaseRenderChanged };
  const date = timestamp.toLocaleDateString("sv-SE");
  const currentDate = next.date || date;
  if (date !== currentDate) return { history: next, phaseRenderChanged };
  const points = Array.isArray(next.points) ? [...next.points] : [];
  const nextPoint = { timestamp: timestamp.toISOString(), import_kw: normalizeMeterValue(point.import_kw), export_kw: normalizeMeterValue(point.export_kw) };
  const index = points.findIndex((item) => item.timestamp === nextPoint.timestamp);
  if (index >= 0) points[index] = nextPoint; else points.push(nextPoint);
  points.sort((left, right) => new Date(left.timestamp) - new Date(right.timestamp));
  return { history: { ...next, date: currentDate, points }, phaseRenderChanged };
}

export function phaseHistoryPointCounts(history = {}) {
  return Object.fromEntries(["current", "voltage", "active_power"].map((metric) => [
    metric,
    Object.fromEntries(["l1", "l2", "l3"].map((phase) => [
      phase,
      Array.isArray(history?.[metric]?.[phase]?.points) ? history[metric][phase].points.length : 0,
    ])),
  ]));
}

export function phaseHistoryAvailable(history = {}, meterState = {}) {
  const hasHistory = ["current", "voltage", "active_power"].some((metric) =>
    ["l1", "l2", "l3"].some((phase) => Array.isArray(history?.[metric]?.[phase]?.points)),
  );
  const sourceGroups = Object.values(meterState?.phase_source_entities || {});
  const hasSources = sourceGroups.some((group) => group && typeof group === "object" && Object.values(group).some(Boolean));
  const liveGroups = [meterState?.phase_current_a, meterState?.phase_voltage_v, meterState?.phase_active_power_kw];
  const hasLive = liveGroups.some((group) => group && typeof group === "object" && Object.values(group).some((value) => Number.isFinite(Number(value))));
  return hasHistory || hasSources || hasLive;
}

export function phaseHistoryAxisEnd(points = []) {
  return (Array.isArray(points) ? points : [])
    .map((point) => new Date(point?.timestamp).getTime())
    .filter(Number.isFinite)
    .reduce((latest, timestamp) => Math.max(latest, timestamp), null);
}

export function selectPhaseTimeTicks(ticks = [], plotWidth = 0, minimumSpacing = 56) {
  const values = [...new Set((Array.isArray(ticks) ? ticks : []).map(Number).filter(Number.isFinite))].sort((left, right) => left - right);
  if (values.length <= 2) return values;
  const maxVisible = Math.max(2, Math.floor(Math.max(1, Number(plotWidth) || 1) / Math.max(1, Number(minimumSpacing) || 1)) + 1);
  if (values.length <= maxVisible) return values;
  return Array.from({ length: maxVisible }, (_, index) => values[Math.round(index * (values.length - 1) / (maxVisible - 1))]);
}

export function phaseAxisGutter(metric = "current") {
  return {
    current: 34,
    voltage: 48,
    active_power: 50,
  }[metric] || 34;
}

export function buildPhaseChartGeometry(containerWidth = 960, { metric = "current" } = {}) {
  const width = Math.max(320, Math.round(Number(containerWidth) || 960));
  const compact = width <= 600;
  const plotLeft = phaseAxisGutter(metric);
  const plotRight = compact ? 10 : 12;
  const plotTop = 12;
  const plotWidth = Math.max(1, width - plotLeft - plotRight);
  const height = Math.round(Math.min(300, Math.max(160, plotWidth * (compact ? 0.38 : 0.28))));
  const plotBottom = compact ? 34 : 24;
  return { width, height, plotLeft, plotRight, plotTop, plotBottom, plotWidth, plotHeight: Math.max(1, height - plotTop - plotBottom), compact, axisLabelGutter: plotLeft };
}

export function axisCollisionInset(actualTextExtent, desiredGap = 8, availableOutsideSpace = 0) {
  const textExtent = Number(actualTextExtent);
  const gap = Number(desiredGap);
  const outsideSpace = Number(availableOutsideSpace);
  return Math.max(0, (Number.isFinite(textExtent) ? textExtent : 0)
    + (Number.isFinite(gap) ? Math.max(0, gap) : 0)
    - (Number.isFinite(outsideSpace) ? Math.max(0, outsideSpace) : 0));
}

export function priceAxisGutter(labels = [], gap = 8) {
  if (!Array.isArray(labels) || labels.length === 0) return 0;
  const widestLabel = (Array.isArray(labels) ? labels : [])
    .map((label) => String(label ?? "").length * 7)
    .reduce((max, width) => Math.max(max, width), 0);
  return Math.ceil(axisCollisionInset(widestLabel, gap));
}

function measuredPriceAxisGutter(chart, labels, gap = 8) {
  if (!Array.isArray(labels) || labels.length === 0) return 0;
  if (!chart || typeof document === "undefined") return priceAxisGutter(labels, gap);
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) return priceAxisGutter(labels, gap);
  const style = getComputedStyle(chart);
  context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
  const widestLabel = (Array.isArray(labels) ? labels : [])
    .map((label) => context.measureText(String(label ?? "")).width)
    .reduce((max, width) => Math.max(max, width), 0);
  return Math.ceil(axisCollisionInset(widestLabel, gap));
}

function measuredPriceAxisLabelGutter(chart, labels, gap = 8) {
  if (!Array.isArray(labels) || labels.length === 0) return 0;
  if (!chart || typeof document === "undefined") return priceAxisGutter(labels, gap);
  const sample = document.createElement("span");
  sample.className = "chart-axis-overlay-label chart-axis-overlay-y-left";
  sample.textContent = labels.reduce((longest, label) => String(label ?? "").length > String(longest ?? "").length ? label : longest, "");
  sample.style.cssText = "position:absolute;visibility:hidden;width:auto;padding:0;white-space:nowrap;";
  chart.append(sample);
  const range = document.createRange();
  range.selectNodeContents(sample);
  const measuredWidth = range.getBoundingClientRect().width;
  sample.remove();
  return Math.ceil(axisCollisionInset(measuredWidth, gap));
}

export function buildHourlyBoundaryHours(containerWidth = 960) {
  const width = Number(containerWidth) || 960;
  const step = width >= 760 ? 1 : width >= 480 ? 3 : 6;
  return Array.from({ length: 25 }, (_, hour) => hour)
    .filter((hour) => hour === 0 || hour === 24 || hour % step === 0);
}

export function buildHourlyBarEdges(periodStart, periodEnd, dayStart, dayEnd, plotLeft, plotRight) {
  const start = new Date(periodStart).getTime();
  const end = new Date(periodEnd).getTime();
  const axisStart = new Date(dayStart).getTime();
  const axisEnd = new Date(dayEnd).getTime();
  if (![start, end, axisStart, axisEnd, plotLeft, plotRight].every(Number.isFinite)
    || axisEnd <= axisStart || end < start || plotRight < plotLeft) return null;
  const x = (timestamp) => plotLeft + ((timestamp - axisStart) / (axisEnd - axisStart)) * (plotRight - plotLeft);
  return { left: x(start), right: x(end) };
}

export function buildPriceChartGeometry(width = 960, height = 350, {
  dualAxis = false,
  containerWidth = width,
  leftAxisLabels = ["0 kW", "5 kW", "10 kW"],
  rightAxisLabels = dualAxis ? ["0 öre/kWh", "100 öre/kWh"] : [],
  leftAxisGutter = null,
  rightAxisGutter = null,
  contentLeft = 0,
  contentRight = null,
} = {}) {
  const chartWidth = Math.max(320, Math.round(Number(width) || 960));
  const chartHeight = Math.max(160, Math.round(Number(height) || 350));
  const renderedWidth = Math.max(320, Number(containerWidth) || chartWidth);
  const contentStartValue = Number(contentLeft);
  const contentEndValue = Number(contentRight);
  const contentStart = Number.isFinite(contentStartValue) ? contentStartValue : 0;
  const contentEnd = contentRight != null && Number.isFinite(contentEndValue) ? contentEndValue : chartWidth;
  const xAxisRailHeight = Math.round(16 * chartWidth / renderedWidth);
  const leftGutter = Number.isFinite(leftAxisGutter) ? leftAxisGutter : priceAxisGutter(leftAxisLabels);
  const rightGutter = Number.isFinite(rightAxisGutter)
    ? rightAxisGutter
    : priceAxisGutter(rightAxisLabels);
  const leftInset = leftGutter * chartWidth / renderedWidth;
  const rightInset = rightGutter * chartWidth / renderedWidth;
  const plotLeft = contentStart + leftInset;
  const plotRight = contentEnd - rightInset;
  const plot = dualAxis
    ? { left: leftInset, right: rightInset, top: 30, bottom: xAxisRailHeight }
    : { left: leftInset, right: rightInset, top: 42, bottom: xAxisRailHeight };
  const plotWidth = Math.max(1, plotRight - plotLeft);
  const plotHeight = Math.max(1, chartHeight - plot.top - plot.bottom);
  return {
    width: chartWidth,
    height: chartHeight,
    contentLeft: contentStart,
    contentRight: contentEnd,
    leftInset,
    rightInset,
    plotLeft,
    plotRight,
    plotTop: plot.top,
    plotBottom: plot.bottom,
    plotWidth,
    plotHeight,
    xAxisRailHeight: plot.bottom,
    plot,
  };
}

/** Convert a browser pointer to the SVG viewBox and plot coordinate systems. */
export function pointerToPlotCoordinates(svg, event, plot, width, height) {
  const bounds = svg?.getBoundingClientRect?.();
  if (!bounds || !bounds.width || !bounds.height) return null;
  const viewX = ((event.clientX - bounds.left) / bounds.width) * width;
  const viewY = ((event.clientY - bounds.top) / bounds.height) * height;
  return {
    viewX,
    viewY,
    plotX: viewX - plot.left,
    plotY: viewY - plot.top,
    inside: viewX >= plot.left && viewX <= width - plot.right
      && viewY >= plot.top && viewY <= height - plot.bottom,
  };
}

export function isPointerInsidePlot(svg, event, plot, width, height) {
  return pointerToPlotCoordinates(svg, event, plot, width, height)?.inside === true;
}

const DEBUG_SENSITIVE_KEY = /(?:^|[_-])(?:password|passcode|passphrase|authorization|cookie|cookies|client[_-]?secret|api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|current[_-]?token|session[_-]?(?:token|secret)|csrf[_-]?token|security[_-]?token|authorization[_-]?code|code[_-]?(?:verifier|challenge)|jwt|dpop|cat|credential|secret|token)(?:$|[_-])|^MyEon(?:Session|AccessToken|IDToken|ResumeAt|AccessScopes)$/i;

export function sanitizeDebugData(value, key = "") {
  if (DEBUG_SENSITIVE_KEY.test(key)) return "[redacted]";
  if (Array.isArray(value)) return value.map((item) => sanitizeDebugData(item));
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => [
    childKey,
    sanitizeDebugData(childValue, childKey),
  ]));
}

export function resolveFuseAmpere(meterState, gridState) {
  const candidates = [
    meterState?.facility?.fuse_ampere,
    meterState?.fuse_ampere,
    gridState?.facility?.fuse_ampere,
    gridState?.fuse_ampere,
  ];
  const value = candidates.map(Number).find((candidate) => Number.isFinite(candidate) && candidate > 0);
  return value ?? null;
}

function phaseStateValueEqual(left, right) {
  if (left == null || right == null) return left == null && right == null;
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  return Number.isFinite(leftNumber) && Number.isFinite(rightNumber)
    ? leftNumber === rightNumber
    : left === right;
}

export function phaseMeterStateDependenciesChanged(previous, next, gridState) {
  if (!previous) return true;
  if (resolveFuseAmpere(previous, gridState) !== resolveFuseAmpere(next, gridState)) return true;
  for (const [metric, field] of [["current", "phase_current_a"], ["voltage", "phase_voltage_v"], ["active_power", "phase_active_power_kw"]]) {
    for (const phase of ["l1", "l2", "l3"]) {
      if (!phaseStateValueEqual(previous?.[field]?.[phase], next?.[field]?.[phase])) return true;
    }
    for (const phase of ["l1", "l2", "l3"]) {
      if ((previous?.phase_source_entities?.[metric]?.[phase] || null) !== (next?.phase_source_entities?.[metric]?.[phase] || null)) return true;
    }
  }
  return false;
}

export function phaseChartDomNeedsRender(chart) {
  return Boolean(chart && !chart.querySelector(".phase-history-svg, .phase-history-empty"));
}

export function buildCanonicalPhasePoints(points, dayStart, axisEnd, slotMs = 5 * 60 * 1000, maxDistanceMs = 2.5 * 60 * 1000) {
  const dayStartMs = new Date(dayStart).getTime();
  const axisEndMs = new Date(axisEnd).getTime();
  if (!Number.isFinite(dayStartMs) || !Number.isFinite(axisEndMs) || axisEndMs < dayStartMs) return [];
  const lastSlot = dayStartMs + Math.floor((axisEndMs - dayStartMs) / slotMs) * slotMs;
  const canonical = [];
  let previousSelected = false;
  for (let slotTimestamp = dayStartMs; slotTimestamp <= lastSlot; slotTimestamp += slotMs) {
    const selected = nearestMeterPoint(points, slotTimestamp, maxDistanceMs);
    const value = selected == null ? null : normalizeMeterValue(selected.value);
    const hasSample = selected != null && Number.isFinite(value);
    if (hasSample) {
      canonical.push({
        timestamp: slotTimestamp,
        raw_timestamp: selected.timestamp,
        value,
        gap_before: !previousSelected,
      });
    }
    previousSelected = hasSample;
  }
  return canonical;
}

export function buildPhaseRenderDomain(allPoints, metric, fuse) {
  const values = allPoints.map((point) => Number(point.value)).filter(Number.isFinite);
  let minValue = metric === "current" ? 0 : Math.min(...values);
  const observedMax = values.length ? Math.max(...values.map((value) => metric === "current" ? Math.abs(value) : value)) : 0;
  let maxValue = metric === "current"
    ? Math.max(Number.isFinite(fuse) ? fuse : 0, observedMax * 1.08)
    : Math.max(...values);
  if (metric === "active_power") {
    minValue = Math.min(0, minValue);
    maxValue = Math.max(0, maxValue);
  }
  const margin = Math.max(1, (maxValue - minValue) * 0.08);
  if (metric !== "current") {
    minValue -= margin;
    maxValue += margin;
  }
  if (!Number.isFinite(minValue) || !Number.isFinite(maxValue) || maxValue <= minValue) {
    minValue = 0;
    maxValue = 1;
  }
  return { minValue, maxValue };
}

export function buildLiveSourceEntity(states, entityId, role) {
  const state = entityId && states?.[entityId];
  return {
    entity_id: entityId || null,
    state: state?.state ?? null,
    raw_state: state?.state ?? null,
    unit: state?.attributes?.unit_of_measurement ?? null,
    raw_unit: state?.attributes?.unit_of_measurement ?? null,
    device_class: state?.attributes?.device_class ?? null,
    state_class: state?.attributes?.state_class ?? null,
    last_updated: state?.last_updated ?? null,
    role,
  };
}

export function buildPhaseProvenance(metric, meterState = {}, meterHistory = {}, states = {}) {
  const metricKey = metric === "voltage" ? "voltage" : metric === "active_power" ? "active_power" : "current";
  const sourceEntities = meterState.phase_source_entities?.[metricKey]
    || (metricKey === "current" ? meterState.phase_current_source_entities || meterState.phase_current_entities : {})
    || {};
  const normalize = (entityId, phase) => {
    const source = buildLiveSourceEntity(states, entityId, `${metricKey}_${phase}`);
    const raw = Number(source.raw_state);
    const unit = String(source.raw_unit || "").toLowerCase();
    let normalized = Number.isFinite(raw) ? raw : null;
    let conversion = "identity";
    if (metricKey === "active_power" && unit === "w") {
      normalized = raw / 1000;
      conversion = "W / 1000";
    } else if (metricKey === "active_power" && unit === "mw") {
      normalized = raw * 1000;
      conversion = "MW * 1000";
    } else if (metricKey === "current") {
      normalized = Number.isFinite(raw) ? Math.abs(raw) : null;
      conversion = "abs(A) for fuse loading";
    }
    const inverted = metricKey === "active_power" && meterState.invert_power === true;
    if (inverted && normalized != null) normalized = -normalized;
    if (inverted) conversion = `${conversion}; invert_power=true`;
    return { ...source, phase, normalized_value: normalized, normalized_unit: metricKey === "active_power" ? "kW" : metricKey === "voltage" ? "V" : "A", conversion, invert_power: inverted };
  };
  const phases = Object.fromEntries(["l1", "l2", "l3"].map((phase) => [phase, sourceEntities[phase] ? normalize(sourceEntities[phase], phase) : null]));
  return {
    metric: metricKey,
    source: { entities: phases, discovery_method: meterState.phase_discovery_method || meterState.phase_current_discovery_method || null },
    history: meterHistory.phase_history?.[metricKey] || {},
    normalization: metricKey === "active_power" ? `signed grid power is normalized to kW and invert_power=${meterState.invert_power === true}` : metricKey === "current" ? "absolute current magnitude is used for fuse loading" : "source voltage values are retained in V",
  };
}

export function buildLivePowerProvenance(key, tile, powerState = {}, meterState = {}, meterHistory = {}, powerHistory = {}, states = {}, liveMaxima = {}, now = new Date()) {
  const source = [];
  const add = (entityId, role) => { if (entityId) source.push(buildLiveSourceEntity(states, entityId, role)); };
  const sourceValueKw = (entityId) => {
    const snapshot = source.find((item) => item.entity_id === entityId);
    const raw = Number(snapshot?.state);
    if (!Number.isFinite(raw)) return null;
    const unit = String(snapshot?.unit || "").toLowerCase();
    if (unit === "w") return raw / 1000;
    if (unit === "mw") return raw * 1000;
    if (unit === "kw") return raw;
    return null;
  };
  const derivation = { method: "unavailable", input_count: 0, result_kw: tile?.value ?? null };
  if (key === "solar") {
    const entities = Array.isArray(powerState.solar_entities) ? powerState.solar_entities : [];
    entities.forEach((entityId) => add(entityId, "solar_power"));
    derivation.method = "sum_power_entities";
    derivation.input_count = entities.length;
    derivation.unit_conversion = "source_units_to_kW";
    derivation.invert = false;
    derivation.inputs_kw = entities.map((entityId) => sourceValueKw(entityId));
    derivation.result_kw_from_inputs = derivation.inputs_kw.every((value) => Number.isFinite(value))
      ? derivation.inputs_kw.reduce((sum, value) => sum + value, 0)
      : null;
    derivation.formula = entities.length ? entities.map((_, index) => `pv${index + 1}_kw`).join(" + ") : "no solar entities";
  } else if (key === "house") {
    add(powerState.consumption_entity, "consumption_power");
    derivation.method = powerState.consumption_entity ? "explicit_consumption_entity" : "unavailable";
    derivation.input_count = powerState.consumption_entity ? 1 : 0;
    derivation.unit_conversion = "source_units_to_kW";
    derivation.invert = false;
    derivation.input_kw = sourceValueKw(powerState.consumption_entity);
    derivation.formula = powerState.consumption_entity ? "consumption_entity_kw" : "no consumption entity";
  } else if (key === "grid") {
    add(meterState.power_entity, "grid_active_power");
    for (const [phase, entityId] of Object.entries(meterState.phase_current_source_entities || meterState.phase_current_entities || {})) add(entityId, `phase_${phase}_current`);
    derivation.method = meterState.power_entity ? "normalize_signed_meter_power" : "unavailable";
    derivation.input_count = source.length;
    derivation.unit_conversion = "source_units_to_kW";
    derivation.invert = meterState.invert_power === true;
    derivation.input_signed_kw = sourceValueKw(meterState.power_entity);
    derivation.input_signed_kw_after_invert = Number.isFinite(derivation.input_signed_kw)
      ? (derivation.invert ? -derivation.input_signed_kw : derivation.input_signed_kw)
      : null;
    derivation.formula = meterState.power_entity ? "signed_power -> import_kw/export_kw -> magnitude" : "no grid power entity";
  } else if (key === "battery") {
    const combined = Boolean(powerState.battery_power_entity);
    add(powerState.battery_power_entity, "battery_power");
    add(powerState.charging_entity, "battery_charging");
    add(powerState.discharging_entity, "battery_discharging");
    derivation.method = combined ? "split_signed_battery_power" : "separate_charge_discharge_entities";
    derivation.input_count = source.length;
    derivation.unit_conversion = "source_units_to_kW";
    derivation.invert = powerState.invert_battery_power === true;
    derivation.input_signed_kw = combined ? sourceValueKw(powerState.battery_power_entity) : null;
    derivation.input_signed_kw_after_invert = Number.isFinite(derivation.input_signed_kw)
      ? (derivation.invert ? -derivation.input_signed_kw : derivation.input_signed_kw)
      : null;
    derivation.charging_input_kw = combined ? null : sourceValueKw(powerState.charging_entity);
    derivation.discharging_input_kw = combined ? null : sourceValueKw(powerState.discharging_entity);
    derivation.formula = combined ? "signed_battery_kw -> charging_kw/discharging_kw" : "charging_entity_kw + discharging_entity_kw";
  }
  const date = localDateKey(now);
  const maximumPoint = (points, value) => (Array.isArray(points) ? points : [])
    .filter((point) => localDateKey(point?.timestamp) === date)
    .map((point) => ({
      point,
      normalized_kw: Math.abs(Number(value(point))),
    }))
    .filter((candidate) => Number.isFinite(candidate.normalized_kw))
    .reduce((maximum, candidate) => !maximum || candidate.normalized_kw > maximum.normalized_kw ? candidate : maximum, null);
  const historyCandidates = key === "grid"
    ? [
      maximumPoint(meterHistory.points, (point) => point.import_kw),
      maximumPoint(meterHistory.points, (point) => point.export_kw),
    ]
    : key === "battery"
      ? [
        maximumPoint(powerHistory.series?.charging?.points, (point) => point.value_kw),
        maximumPoint(powerHistory.series?.discharging?.points, (point) => point.value_kw),
      ]
      : [maximumPoint(powerHistory.series?.[key === "house" ? "consumption" : key]?.points, (point) => point.value_kw)];
  const historyPointCandidate = historyCandidates
    .filter(Boolean)
    .reduce((maximum, candidate) => !maximum || candidate.normalized_kw > maximum.normalized_kw ? candidate : maximum, null);
  const historyMax = historyPointCandidate?.normalized_kw ?? null;
  const historyMaxPoint = historyPointCandidate ? {
    timestamp: historyPointCandidate.point.timestamp ?? null,
    entity_id: source[0]?.entity_id || null,
    raw_value: historyPointCandidate.point.raw_value ?? historyPointCandidate.point.value_kw ?? historyPointCandidate.normalized_kw,
    normalized_kw: historyPointCandidate.normalized_kw,
  } : null;
  const liveMax = Number(liveMaxima[key]);
  const resultMax = Math.max(
    ...(Number.isFinite(historyMax) ? [historyMax] : []),
    ...(Number.isFinite(liveMax) ? [liveMax] : []),
  );
  const resultKw = Number.isFinite(resultMax) ? resultMax : tile?.maxToday ?? null;
  const history = {
    source: key === "grid" ? "home_assistant_recorder" : "home_assistant_recorder_or_live_state",
    entities: source.map((item) => item.entity_id).filter(Boolean),
    from: meterHistory.date ? `${meterHistory.date}T00:00:00` : powerHistory.date ? `${powerHistory.date}T00:00:00` : null,
    to: null,
    method: "maximum_observed_magnitude",
    history_point_count: key === "grid"
      ? (Array.isArray(meterHistory.points) ? meterHistory.points.length : 0)
      : key === "battery"
        ? (Array.isArray(powerHistory.series?.charging?.points) ? powerHistory.series.charging.points.length : 0)
          + (Array.isArray(powerHistory.series?.discharging?.points) ? powerHistory.series.discharging.points.length : 0)
        : (Array.isArray(powerHistory.series?.[key === "house" ? "consumption" : key]?.points) ? powerHistory.series[key === "house" ? "consumption" : key].points.length : 0),
    history_max_kw: Number.isFinite(historyMax) ? historyMax : null,
    live_max_after_bootstrap_kw: Number.isFinite(Number(liveMaxima[key])) ? Number(liveMaxima[key]) : null,
    result_kw: resultKw,
    max_source: "raw_history_plus_live_daily_max",
    presentation_max_matches_history: !Number.isFinite(historyMax) || !Number.isFinite(resultKw)
      ? null
      : Math.abs(historyMax - Number(resultKw)) < 1e-9,
    history_max_point: historyMaxPoint,
  };
  return {
    display: { current_kw: tile?.value ?? null, status: tile?.status ?? null },
    source: {
      entities: source,
      ...(key === "grid" ? {
        phase_current_entities: meterState.phase_current_source_entities || meterState.phase_current_entities || {},
        phase_source_entities: meterState.phase_source_entities || {},
        fuse_ampere: meterState.facility?.fuse_ampere ?? null,
        fuse_source: "grid_provider_canonical_facility",
      } : {}),
    },
    derivation: { ...derivation, result_kw: tile?.value ?? null },
    history,
    presentation: {
      current_kw: tile?.value ?? null,
      max_today_kw: resultKw,
      scale_floor_kw: 1,
      scale_max_kw: tile?.scaleMax ?? null,
      fill_percent: tile?.fillPercent ?? null,
      status: tile?.status ?? null,
    },
  };
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

export function energyIntervalsToStepPoints(intervals, valueField = "value_kw") {
  const rows = (Array.isArray(intervals) ? intervals : []).map((interval) => ({
    start: new Date(interval?.start).getTime(),
    end: new Date(interval?.end).getTime(),
    value: Number(interval?.[valueField]),
    resolution_seconds: Number(interval?.resolution_seconds),
    source: interval?.source || null,
  })).filter((interval) => Number.isFinite(interval.start)
    && Number.isFinite(interval.end)
    && interval.end > interval.start
    && Number.isFinite(interval.value))
    .sort((left, right) => left.start - right.start);
  const points = [];
  let previousEnd = null;
  for (const interval of rows) {
    const gapBefore = previousEnd !== null && interval.start > previousEnd + 1;
    const base = {
      raw_timestamp: new Date(interval.start).toISOString(),
      value_kw: interval.value,
      source_resolution_seconds: Number.isFinite(interval.resolution_seconds) ? interval.resolution_seconds : null,
      history_source: interval.source,
      history_interval_id: `${interval.start}:${interval.end}:${interval.source || "history"}`,
    };
    points.push({ ...base, timestamp: interval.start, gap_before: gapBefore });
    points.push({ ...base, timestamp: interval.end - 1, gap_before: false });
    previousEnd = interval.end;
  }
  return points;
}

export function energyIntervalsToCurvePoints(intervals, valueField = "value_kw") {
  const rows = (Array.isArray(intervals) ? intervals : []).map((interval) => ({
    start: new Date(interval?.start).getTime(),
    end: new Date(interval?.end).getTime(),
    value: Number(interval?.[valueField]),
    resolution_seconds: Number(interval?.resolution_seconds),
    source: interval?.source || null,
  })).filter((interval) => Number.isFinite(interval.start)
    && Number.isFinite(interval.end)
    && interval.end > interval.start
    && Number.isFinite(interval.value))
    .sort((left, right) => left.start - right.start);
  const points = [];
  rows.forEach((interval, index) => {
    const previous = rows[index - 1];
    const next = rows[index + 1];
    const base = {
      raw_timestamp: new Date(interval.start).toISOString(),
      value_kw: interval.value,
      gap_before: Boolean(previous && interval.start > previous.end + 1),
      history_source: interval.source,
      history_curve: true,
      source_resolution_seconds: Number.isFinite(interval.resolution_seconds) ? interval.resolution_seconds : null,
    };
    points.push({ ...base, timestamp: interval.start });
    if (!next || next.start > interval.end + 1) {
      points.push({
        ...base,
        timestamp: interval.end - 1,
        raw_timestamp: new Date(interval.end - 1).toISOString(),
        gap_before: false,
      });
    }
  });
  return points;
}

export function energyHistoryIntervalValueAt(history, series, timestamp) {
  const target = new Date(timestamp).getTime();
  if (!Number.isFinite(target)) return null;
  const interval = (Array.isArray(history?.series?.[series]) ? history.series[series] : []).find((item) => {
    const start = new Date(item?.start).getTime();
    const end = new Date(item?.end).getTime();
    return Number.isFinite(start) && Number.isFinite(end) && start <= target && target < end;
  });
  const value = Number(interval?.value_kw);
  return Number.isFinite(value) ? value : null;
}

export function energyHistoryToMeterCurvePoints(history) {
  const byTimestamp = new Map();
  const add = (series, key) => {
    for (const point of energyIntervalsToCurvePoints(history?.series?.[series])) {
      const current = byTimestamp.get(point.timestamp) || {
        timestamp: point.timestamp, raw_timestamp: point.raw_timestamp,
        import_kw: null, export_kw: null, gap_before: point.gap_before,
        history_source: point.history_source, history_curve: true,
        source_resolution_seconds: point.source_resolution_seconds,
      };
      current[key] = point.value_kw;
      current.gap_before = current.gap_before || point.gap_before;
      current.source_resolution_seconds ||= point.source_resolution_seconds;
      byTimestamp.set(point.timestamp, current);
    }
  };
  add("import", "import_kw");
  add("export", "export_kw");
  return [...byTimestamp.values()].sort((left, right) => left.timestamp - right.timestamp);
}

export function energyHistoryToMeterStepPoints(history) {
  const byTimestamp = new Map();
  const add = (series, key) => {
    for (const point of energyIntervalsToStepPoints(history?.series?.[series])) {
      const current = byTimestamp.get(point.timestamp) || {
        timestamp: point.timestamp, raw_timestamp: point.raw_timestamp,
        import_kw: null, export_kw: null, gap_before: point.gap_before,
        history_source: point.history_source,
        history_interval_id: point.history_interval_id,
        source_resolution_seconds: point.source_resolution_seconds,
      };
      current[key] = point.value_kw;
      current.history_interval_id ||= point.history_interval_id;
      current.source_resolution_seconds ||= point.source_resolution_seconds;
      current.gap_before = current.gap_before || point.gap_before;
      byTimestamp.set(point.timestamp, current);
    }
  };
  add("import", "import_kw");
  add("export", "export_kw");
  return [...byTimestamp.values()].sort((left, right) => left.timestamp - right.timestamp);
}

export function integrateEnergyIntervalsKwh(intervals, start, end) {
  const startMs = new Date(start).getTime();
  const endMs = new Date(end).getTime();
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return null;
  let total = 0;
  let covered = false;
  for (const interval of Array.isArray(intervals) ? intervals : []) {
    const left = Math.max(startMs, new Date(interval?.start).getTime());
    const right = Math.min(endMs, new Date(interval?.end).getTime());
    const value = Number(interval?.value_kw);
    if (!Number.isFinite(left) || !Number.isFinite(right) || !Number.isFinite(value) || right <= left) continue;
    total += value * ((right - left) / 3600000);
    covered = true;
  }
  return covered ? total : null;
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

export function stockholmDayWindow(now = new Date()) {
  const date = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Stockholm" }).format(new Date(now));
  const [year, month, day] = date.split("-").map(Number);
  const toBoundary = (yearValue, monthValue, dayValue) => {
    const candidate = Date.UTC(yearValue, monthValue - 1, dayValue);
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "Europe/Stockholm",
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    }).formatToParts(new Date(candidate));
    const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, Number(part.value)]));
    const displayedAsUtc = Date.UTC(values.year, values.month - 1, values.day, values.hour % 24, values.minute, values.second);
    return new Date(candidate - (displayedAsUtc - candidate));
  };
  return { date, start: toBoundary(year, month, day), end: toBoundary(year, month, day + 1) };
}

export function integrateMeterHistoryKwh(points, field, dayStart, dayEnd, now = new Date(), slotMs = 5 * 60 * 1000) {
  const canonical = buildCanonicalMeterPoints(points, dayStart, dayEnd, slotMs);
  const nowMs = new Date(now).getTime();
  const samples = canonical.filter((point) => point.raw_timestamp !== null && point.timestamp <= nowMs);
  let energyKwh = 0;
  let covered = false;
  for (let index = 1; index < samples.length; index += 1) {
    const previous = samples[index - 1];
    const current = samples[index];
    if (current.timestamp - previous.timestamp !== slotMs || current.gap_before) continue;
    const previousValue = Number(previous[field]);
    const currentValue = Number(current[field]);
    if (!Number.isFinite(previousValue) || !Number.isFinite(currentValue)) continue;
    energyKwh += ((previousValue + currentValue) / 2) * (slotMs / (60 * 60 * 1000));
    covered = true;
  }
  return covered ? energyKwh : null;
}

export function integrateMeterEnergyByRange(points, startMs, endMs) {
  const sorted = (Array.isArray(points) ? points : []).map((point) => ({
    timestamp: new Date(point.timestamp).getTime(),
    value: Number(point.import_kw),
  })).filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.value))
    .sort((left, right) => left.timestamp - right.timestamp);
  let total = 0;
  let covered = false;
  for (let index = 1; index < sorted.length; index += 1) {
    const left = sorted[index - 1];
    const right = sorted[index];
    if (right.timestamp <= left.timestamp || right.timestamp - left.timestamp > 30 * 60 * 1000) continue;
    const from = Math.max(startMs, left.timestamp);
    const to = Math.min(endMs, right.timestamp);
    if (to <= from) continue;
    const ratio = (timestamp) => (timestamp - left.timestamp) / (right.timestamp - left.timestamp);
    const fromValue = left.value + (right.value - left.value) * ratio(from);
    const toValue = left.value + (right.value - left.value) * ratio(to);
    total += ((fromValue + toValue) / 2) * ((to - from) / 3600000);
    covered = true;
  }
  return covered ? total : null;
}

export function recomputeDailyEnergyState(powerState, powerHistory, meterPowerHistory, now = new Date()) {
  if (!powerState) return null;
  const window = stockholmDayWindow(now);
  const seriesPoints = (key) => powerHistory?.series?.[key]?.points;
  return {
    ...powerState,
    solar_energy_kwh: integratePowerHistoryKwh(seriesPoints("solar"), window.start, window.end, now),
    consumption_energy_kwh: integratePowerHistoryKwh(seriesPoints("consumption"), window.start, window.end, now),
    charging_energy_kwh: integratePowerHistoryKwh(seriesPoints("charging"), window.start, window.end, now),
    discharging_energy_kwh: integratePowerHistoryKwh(seriesPoints("discharging"), window.start, window.end, now),
    meter_import_energy_kwh: integrateMeterHistoryKwh(meterPowerHistory?.points, "import_kw", window.start, window.end, now),
    meter_export_energy_kwh: integrateMeterHistoryKwh(meterPowerHistory?.points, "export_kw", window.start, window.end, now),
  };
}

export function buildInvoiceEstimate(periods, meterPoints, gridPrice, tradeFixedFee = null, now = new Date(), historicalMeterPoints = []) {
  const current = new Date(now);
  const nowMs = current.getTime();
  if (!Array.isArray(periods) || !periods.length || !Array.isArray(meterPoints)) return null;
  const monthStart = new Date(current.getFullYear(), current.getMonth(), 1);
  const nextMonth = new Date(current.getFullYear(), current.getMonth() + 1, 1);
  const gridPriceApplicable = gridPrice?.contract_source_status === "ACTIVE"
    || gridPrice?._effective_dated_applicable === true;
  const gridGross = gridPriceApplicable ? Number(gridPrice?.variable_total_ore_per_kwh_gross) : NaN;
  const points = meterPoints
    .map((point) => ({ timestamp: new Date(point.timestamp).getTime(), importKw: Number(point.import_kw) }))
    .filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.importKw))
    .sort((left, right) => left.timestamp - right.timestamp);
  const historicalPoints = (Array.isArray(historicalMeterPoints) ? historicalMeterPoints : [])
    .map((point) => ({ timestamp: new Date(point.timestamp).getTime(), importKw: Number(point.import_kw) }))
    .filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.importKw))
    .sort((left, right) => left.timestamp - right.timestamp);
  const integrate = (startMs, endMs) => {
    const limit = Math.min(endMs, nowMs);
    if (limit <= startMs || points.length < 2) return { kwh: null, covered: false };
    let total = 0;
    let coveredUntil = startMs;
    for (let index = 1; index < points.length; index += 1) {
      const left = points[index - 1];
      const right = points[index];
      if (right.timestamp - left.timestamp > 30 * 60 * 1000) continue;
      const overlapStart = Math.max(startMs, left.timestamp);
      const overlapEnd = Math.min(limit, right.timestamp);
      if (overlapEnd <= overlapStart || right.timestamp <= left.timestamp) continue;
      const valueAt = (timestamp) => left.importKw + (right.importKw - left.importKw) * ((timestamp - left.timestamp) / (right.timestamp - left.timestamp));
      total += (valueAt(overlapStart) + valueAt(overlapEnd)) / 2 * ((overlapEnd - overlapStart) / 3600000);
      if (overlapStart <= coveredUntil + 1 && overlapEnd > coveredUntil) coveredUntil = overlapEnd;
    }
    return { kwh: coveredUntil >= limit - 1 ? total : null, covered: coveredUntil >= limit - 1 };
  };
  const coveredSegments = [];
  for (let index = 1; index < points.length; index += 1) {
    const left = points[index - 1];
    const right = points[index];
    const segmentStart = Math.max(monthStart.getTime(), left.timestamp);
    const segmentEnd = Math.min(nowMs, right.timestamp);
    if (right.timestamp - left.timestamp <= 30 * 60 * 1000 && segmentEnd > segmentStart) {
      coveredSegments.push({ start: segmentStart, end: segmentEnd });
    }
  }
  const rows = [];
  let missingPricePeriods = 0;
  let missingEnergyPeriods = 0;
  let coveredEnergyPeriods = 0;
  let coveredEnergyKwh = 0;
  let observedPricePeriods = 0;
  for (const period of periods) {
    const startMs = new Date(period.start).getTime();
    const endMs = new Date(period.end).getTime();
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= monthStart.getTime() || startMs >= nowMs) continue;
    observedPricePeriods += 1;
    const integration = integrate(Math.max(startMs, monthStart.getTime()), Math.min(endMs, nowMs));
    if (!integration.covered) {
      missingEnergyPeriods += 1;
      continue;
    }
    coveredEnergyPeriods += 1;
    coveredEnergyKwh += integration.kwh;
    const tradeOre = Number(period.trade_customer_price_ore_per_kwh ?? Number(period.customer_price) * 100);
    if (!Number.isFinite(tradeOre) || !Number.isFinite(gridGross)) {
      missingPricePeriods += 1;
      continue;
    }
    const importKwh = integration.kwh;
    rows.push({
      start: period.start,
      end: period.end,
      import_kwh: importKwh,
      spot_price_ex_vat_ore_per_kwh: Number.isFinite(Number(period.spot_price_ex_vat)) ? Number(period.spot_price_ex_vat) * 100 : null,
      electricity_cost_ex_vat_ore_per_kwh: Number.isFinite(Number(period.electricity_cost_ex_vat)) ? Number(period.electricity_cost_ex_vat) * 100 : null,
      vat_ore_per_kwh: Number.isFinite(Number(period.vat)) ? Number(period.vat) * 100 : null,
      trade_price_ore_per_kwh_gross: tradeOre,
      grid_price_ore_per_kwh_gross: gridGross,
      trade_cost_sek: importKwh * tradeOre / 100,
      grid_cost_sek: importKwh * gridGross / 100,
    });
  }
  const integrateCompleteDay = (sourcePoints, dayStartMs, dayEndMs) => {
    if (sourcePoints.length < 2) return null;
    let total = 0;
    let coveredUntil = dayStartMs;
    for (let index = 1; index < sourcePoints.length; index += 1) {
      const left = sourcePoints[index - 1];
      const right = sourcePoints[index];
      if (right.timestamp - left.timestamp > 30 * 60 * 1000) continue;
      const overlapStart = Math.max(dayStartMs, left.timestamp);
      const overlapEnd = Math.min(dayEndMs, right.timestamp);
      if (overlapEnd <= overlapStart || right.timestamp <= left.timestamp) continue;
      const valueAt = (timestamp) => left.importKw + (right.importKw - left.importKw) * ((timestamp - left.timestamp) / (right.timestamp - left.timestamp));
      total += (valueAt(overlapStart) + valueAt(overlapEnd)) / 2 * ((overlapEnd - overlapStart) / 3600000);
      if (overlapStart <= coveredUntil + 1 && overlapEnd > coveredUntil) coveredUntil = overlapEnd;
    }
    return coveredUntil >= dayEndMs - 1 ? total : null;
  };
  const historicalDailyValues = [];
  for (let dayOffset = 28; dayOffset > 0; dayOffset -= 1) {
    const dayStart = new Date(monthStart.getFullYear(), monthStart.getMonth(), 1 - dayOffset);
    const dayEnd = new Date(dayStart.getFullYear(), dayStart.getMonth(), dayStart.getDate() + 1);
    const value = integrateCompleteDay(historicalPoints, dayStart.getTime(), dayEnd.getTime());
    if (value !== null && Number.isFinite(value)) historicalDailyValues.push(value);
  }
  const historicalBaselineDailyKwh = historicalDailyValues.length
    ? historicalDailyValues.reduce((sum, value) => sum + value, 0) / historicalDailyValues.length
    : null;
  const actualImportedKwh = integrateMeterEnergyByRange(meterPoints, monthStart.getTime(), nowMs);
  const tradeVariableSek = rows.length ? rows.reduce((sum, row) => sum + row.trade_cost_sek, 0) : null;
  const gridVariableSek = rows.length && Number.isFinite(gridGross) ? rows.reduce((sum, row) => sum + row.grid_cost_sek, 0) : null;
  const coveredStart = rows.length ? Math.min(...rows.map((row) => new Date(row.start).getTime())) : null;
  const coveredEnd = rows.length ? Math.max(...rows.map((row) => Math.min(new Date(row.end).getTime(), nowMs))) : null;
  const elapsedMs = Math.max(0, nowMs - monthStart.getTime());
  const monthMs = nextMonth.getTime() - monthStart.getTime();
  const mergedCoveredSegments = coveredSegments.sort((left, right) => left.start - right.start).reduce((merged, segment) => {
    const previous = merged.at(-1);
    if (previous && segment.start <= previous.end) previous.end = Math.max(previous.end, segment.end);
    else merged.push({ ...segment });
    return merged;
  }, []);
  const coveredDurationMs = mergedCoveredSegments.reduce((sum, segment) => sum + segment.end - segment.start, 0);
  const coveredStartMs = mergedCoveredSegments.length ? mergedCoveredSegments[0].start : null;
  const coveredEndMs = mergedCoveredSegments.length ? mergedCoveredSegments.at(-1).end : null;
  const missingPastMs = Math.max(0, elapsedMs - coveredDurationMs);
  const elapsedDays = Math.max(1, elapsedMs / 86400000);
  const coveredDays = coveredDurationMs / 86400000;
  const remainingDays = Math.max(0, (nextMonth.getTime() - nowMs) / 86400000);
  const pricedCostImportKwh = rows.reduce((sum, row) => sum + row.import_kwh, 0);
  const observedDailyImportKwh = actualImportedKwh !== null && actualImportedKwh >= 0 && coveredDays > 0 ? actualImportedKwh / coveredDays : null;
  const tradeWeighted = pricedCostImportKwh > 0
    ? rows.reduce((sum, row) => sum + row.import_kwh * row.trade_price_ore_per_kwh_gross, 0) / pricedCostImportKwh
    : null;
  const gridWeighted = pricedCostImportKwh > 0 ? gridGross : null;
  const fixedTrade = tradeFixedFee != null && Number.isFinite(Number(tradeFixedFee)) ? Number(tradeFixedFee) : null;
  const gridFixed = gridPriceApplicable && Number.isFinite(Number(gridPrice?.fixed_monthly_sek))
    ? Number(gridPrice.fixed_monthly_sek)
    : null;
  const accruedGridFixed = gridFixed === null ? null : gridFixed * Math.min(1, elapsedMs / monthMs);
  const accruedTradeFixed = fixedTrade === null ? null : fixedTrade * Math.min(1, elapsedMs / monthMs);
  const variableSoFarSek = tradeVariableSek === null || gridVariableSek === null ? null : tradeVariableSek + gridVariableSek;
  const fixedSoFarSek = (accruedTradeFixed || 0) + (accruedGridFixed || 0);
  const missingPastDays = missingPastMs / 86400000;
  const forecastMissingPastKwh = observedDailyImportKwh === null ? null : observedDailyImportKwh * missingPastDays;
  const blendWeight = historicalBaselineDailyKwh !== null && observedDailyImportKwh !== null
    ? Math.min(1, coveredDays / 14)
    : historicalBaselineDailyKwh !== null ? 0 : observedDailyImportKwh !== null ? 1 : null;
  const forecastDailyKwh = historicalBaselineDailyKwh !== null && observedDailyImportKwh !== null
    ? historicalBaselineDailyKwh * (1 - blendWeight) + observedDailyImportKwh * blendWeight
    : historicalBaselineDailyKwh ?? observedDailyImportKwh;
  const baselineMissingPastKwh = forecastDailyKwh === null ? null : forecastDailyKwh * missingPastDays;
  const forecastFutureKwh = forecastDailyKwh === null ? null : forecastDailyKwh * remainingDays;
  const fallbackTradeOre = tradeWeighted ?? null;
  const fallbackGridOre = gridWeighted ?? gridGross;
  let knownFutureTradeSek = 0;
  let knownFutureGridSek = 0;
  let knownFutureDurationMs = 0;
  if (forecastDailyKwh !== null) {
    for (const period of periods) {
      const startMs = Math.max(nowMs, new Date(period.start).getTime(), monthStart.getTime());
      const endMs = Math.min(nextMonth.getTime(), new Date(period.end).getTime());
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) continue;
      const tradeOre = Number(period.trade_customer_price_ore_per_kwh ?? Number(period.customer_price) * 100);
      if (!Number.isFinite(tradeOre) || !Number.isFinite(fallbackGridOre)) continue;
      const importKwh = forecastDailyKwh * ((endMs - startMs) / 86400000);
      knownFutureTradeSek += importKwh * tradeOre / 100;
      knownFutureGridSek += importKwh * fallbackGridOre / 100;
      knownFutureDurationMs += endMs - startMs;
    }
  }
  const remainingDurationMs = Math.max(0, nextMonth.getTime() - nowMs);
  const unknownFutureKwh = forecastDailyKwh === null ? null : forecastDailyKwh * Math.max(0, remainingDurationMs - knownFutureDurationMs) / 86400000;
  const missingPastTradeSek = baselineMissingPastKwh === null || fallbackTradeOre === null ? null : baselineMissingPastKwh * fallbackTradeOre / 100;
  const missingPastGridSek = baselineMissingPastKwh === null || fallbackGridOre === null ? null : baselineMissingPastKwh * fallbackGridOre / 100;
  const unknownFutureTradeSek = unknownFutureKwh === null || fallbackTradeOre === null ? null : unknownFutureKwh * fallbackTradeOre / 100;
  const unknownFutureGridSek = unknownFutureKwh === null || fallbackGridOre === null ? null : unknownFutureKwh * fallbackGridOre / 100;
  const forecastImportKwh = actualImportedKwh !== null && forecastFutureKwh !== null
    ? actualImportedKwh + forecastFutureKwh
    : null;
  const forecastTradeRemainingSek = unknownFutureTradeSek === null
    ? null : knownFutureTradeSek + unknownFutureTradeSek;
  const forecastGridRemainingSek = unknownFutureGridSek === null
    ? null : knownFutureGridSek + unknownFutureGridSek;
  const forecastVariableSek = variableSoFarSek === null || forecastTradeRemainingSek === null || forecastGridRemainingSek === null
    ? null : tradeVariableSek + gridVariableSek + forecastTradeRemainingSek + forecastGridRemainingSek;
  const totalSoFarSek = variableSoFarSek === null ? null : variableSoFarSek + fixedSoFarSek;
  const forecastRemainingFixedSek = (fixedTrade === null && gridFixed === null)
    ? 0
    : (fixedTrade === null ? 0 : Math.max(0, fixedTrade - (accruedTradeFixed || 0)))
      + (gridFixed === null ? 0 : Math.max(0, gridFixed - (accruedGridFixed || 0)));
  const forecastRemainingTotalSek = forecastVariableSek === null || !Number.isFinite(forecastRemainingFixedSek)
    ? null : forecastVariableSek - (tradeVariableSek || 0) - (gridVariableSek || 0) + forecastRemainingFixedSek;
  const estimatedMonthTotalSek = totalSoFarSek === null || forecastRemainingTotalSek === null
    ? null : totalSoFarSek + forecastRemainingTotalSek;
  return {
    month: `${current.getFullYear()}-${String(current.getMonth() + 1).padStart(2, "0")}`,
    imported_kwh_so_far: actualImportedKwh,
    actual_imported_kwh_display: actualImportedKwh,
    priced_imported_kwh: rows.length ? pricedCostImportKwh : null,
    trade: { variable_cost_sek: tradeVariableSek, fixed_fee_sek: fixedTrade, accrued_fixed_fee_sek: accruedTradeFixed, total_so_far_sek: tradeVariableSek === null ? null : tradeVariableSek + (accruedTradeFixed || 0) },
    grid: { variable_cost_sek: gridVariableSek, fixed_fee_sek: gridFixed, accrued_fixed_fee_sek: accruedGridFixed, total_so_far_sek: gridVariableSek === null ? null : gridVariableSek + (accruedGridFixed || 0) },
    total_so_far_sek: totalSoFarSek,
    estimated_month_total_sek: estimatedMonthTotalSek,
    forecast_import_kwh: forecastImportKwh,
    forecast_remaining_kwh: forecastFutureKwh,
    forecast_missing_past_kwh: baselineMissingPastKwh,
    forecast_future_kwh: forecastFutureKwh,
    forecast_remaining_days: remainingDays,
    forecast_remaining_trade_variable_sek: forecastTradeRemainingSek,
    forecast_remaining_grid_variable_sek: forecastGridRemainingSek,
    forecast_missing_past_trade_sek: missingPastTradeSek,
    forecast_missing_past_grid_sek: missingPastGridSek,
    forecast_remaining_total_sek: forecastRemainingTotalSek,
    missing_past_estimated_kwh: baselineMissingPastKwh,
    historical_baseline_daily_kwh: historicalBaselineDailyKwh,
    historical_baseline_day_count: historicalDailyValues.length,
    observed_current_daily_kwh: observedDailyImportKwh,
    blend_weight: blendWeight,
    forecast_daily_kwh: forecastDailyKwh,
    forecast_source: historicalBaselineDailyKwh !== null && observedDailyImportKwh !== null
      ? "historical_baseline_blended"
      : historicalBaselineDailyKwh !== null ? "historical_baseline_only" : observedDailyImportKwh !== null ? "current_observed_fallback_low_confidence" : "unavailable",
    forecast_fallback: historicalBaselineDailyKwh === null ? "historical_baseline_unavailable" : null,
    actual_so_far_sek: totalSoFarSek,
    remaining_estimated_sek: estimatedMonthTotalSek === null ? null : estimatedMonthTotalSek - totalSoFarSek,
    forecast_method: "actual imported energy display uses all valid integrated segments; future remaining excludes missing past coverage; trailing complete-day historical baseline blended with current observations; known future prices used where available and recent observed prices used only beyond the known horizon",
    forecast_confidence: rows.length && missingPricePeriods === 0 && missingEnergyPeriods === 0 && coveredDurationMs >= elapsedMs - 1 ? "complete_available_data" : "partial_data",
    data_coverage: { period_count: rows.length, observed_periods: observedPricePeriods, covered_energy_periods: coveredEnergyPeriods, missing_price_periods: missingPricePeriods, missing_energy_periods: missingEnergyPeriods, coverage_percent: elapsedMs ? coveredDurationMs / elapsedMs * 100 : 0, first_period: coveredStartMs ? new Date(coveredStartMs).toISOString() : null, last_period: coveredEndMs ? new Date(coveredEndMs).toISOString() : null, observed_duration_ms: coveredDurationMs, covered_duration_ms: coveredDurationMs, missing_past_duration_ms: missingPastMs, remaining_future_duration_ms: remainingDays * 86400000, elapsed_month_duration_ms: elapsedMs, periods: { observed_covered: { duration_ms: coveredDurationMs, kwh: actualImportedKwh }, priced_observed: { duration_ms: coveredDurationMs, kwh: rows.length ? pricedCostImportKwh : null }, missing_past: { duration_ms: missingPastMs, estimated_kwh: baselineMissingPastKwh }, future_remaining: { duration_ms: remainingDays * 86400000, estimated_kwh: forecastFutureKwh } } },
    trade_weighted_average_ore_per_kwh: tradeWeighted,
    grid_weighted_average_ore_per_kwh: gridWeighted,
    total_weighted_average_ore_per_kwh: tradeWeighted === null || gridWeighted === null ? null : tradeWeighted + gridWeighted,
    completeness: { trade_variable: rows.length > 0, trade_fixed: fixedTrade !== null, grid_variable: rows.length > 0 && Number.isFinite(gridGross), grid_fixed: gridFixed !== null, export_credit: false },
    export_energy_kwh: null,
    rows,
    trade_fixed_fee_source: fixedTrade !== null ? "provider_summary.tariff.fixed_fee_incl_vat_per_month" : null,
  };
}

export function finiteCostNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function applyCanonicalMonthlyForecast(estimate, monthlyForecast) {
  if (!monthlyForecast || typeof monthlyForecast !== "object") return estimate;
  const canonicalField = (name) => Object.prototype.hasOwnProperty.call(monthlyForecast, name)
    ? finiteCostNumber(monthlyForecast[name])
    : undefined;
  const actualCostToDate = canonicalField("actual_cost_to_date_sek");
  const estimatedMonthTotal = canonicalField("estimated_month_total_sek");
  const expectedFutureCost = canonicalField("expected_future_cost_sek");
  const actualImportToDate = canonicalField("actual_import_to_date_kwh");
  const estimatedMonthImport = canonicalField("estimated_month_import_kwh");
  const expectedFutureImport = canonicalField("expected_future_import_kwh");
  return {
    ...estimate,
    ...(estimatedMonthTotal !== undefined ? { estimated_month_total_sek: estimatedMonthTotal } : {}),
    ...(actualCostToDate !== undefined ? { total_so_far_sek: actualCostToDate } : {}),
    ...(expectedFutureCost !== undefined ? { forecast_remaining_total_sek: expectedFutureCost } : {}),
    ...(actualImportToDate !== undefined ? { imported_kwh_so_far: actualImportToDate } : {}),
    ...(estimatedMonthImport !== undefined ? { forecast_import_kwh: estimatedMonthImport } : {}),
    ...(expectedFutureImport !== undefined ? { forecast_remaining_kwh: expectedFutureImport } : {}),
    forecast_method: monthlyForecast.forecast_method || estimate?.forecast_method,
    forecast_provenance: monthlyForecast,
  };
}

export function buildCostAnalysisSeries(estimate, previousActual = null, now = new Date()) {
  const current = new Date(now);
  const year = current.getFullYear();
  const monthIndex = current.getMonth();
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  const actualPoints = [];
  let cumulative = 0;
  const tradeFixed = Number(estimate?.trade?.fixed_fee_sek);
  const gridFixed = Number(estimate?.grid?.fixed_fee_sek);
  const monthlyFixed = (Number.isFinite(tradeFixed) ? tradeFixed : 0) + (Number.isFinite(gridFixed) ? gridFixed : 0);
  const monthStartMs = new Date(year, monthIndex, 1).getTime();
  const monthEndMs = new Date(year, monthIndex + 1, 1).getTime();
  const fixedAt = (timestamp) => monthlyFixed * Math.max(0, Math.min(1, (timestamp - monthStartMs) / (monthEndMs - monthStartMs)));
  for (const row of Array.isArray(estimate?.rows) ? [...estimate.rows].sort((left, right) => new Date(left.end).getTime() - new Date(right.end).getTime()) : []) {
    const timestamp = new Date(row.end || row.start).getTime();
    const value = Number(row.trade_cost_sek) + Number(row.grid_cost_sek);
    if (!Number.isFinite(timestamp) || !Number.isFinite(value)) continue;
    cumulative += value;
    actualPoints.push({ day: Math.max(1, Math.min(daysInMonth, new Date(timestamp).getDate())), value: cumulative + fixedAt(timestamp) });
  }
  if (Number.isFinite(Number(estimate?.total_so_far_sek))) {
    actualPoints.push({ day: Math.max(1, Math.min(daysInMonth, current.getDate())), value: Number(estimate.total_so_far_sek) });
  }
  const dedupe = (points) => [...new Map(points.map((point) => [point.day, point])).values()].sort((left, right) => left.day - right.day);
  const actual = dedupe(actualPoints);
  const actualLast = actual.at(-1) || null;
  const forecastTotal = Number(estimate?.estimated_month_total_sek);
  const weightedRate = Number(estimate?.trade_weighted_average_ore_per_kwh) + Number(estimate?.grid_weighted_average_ore_per_kwh);
  const missingPastCost = Number.isFinite(Number(estimate?.forecast_missing_past_kwh)) && Number.isFinite(weightedRate)
    ? Number(estimate.forecast_missing_past_kwh) * weightedRate / 100
    : 0;
  const firstActual = actual[0] || null;
  const estimatedPast = missingPastCost > 0 && firstActual
    ? [{ day: 1, value: 0 }, { day: firstActual.day, value: missingPastCost + firstActual.value }]
    : [];
  const actualDisplay = missingPastCost > 0
    ? actual.map((point) => ({ ...point, value: point.value + missingPastCost }))
    : actual;
  const displayedLast = actualDisplay.at(-1) || null;
  const forecast = Number.isFinite(forecastTotal) && displayedLast && forecastTotal >= displayedLast.value && daysInMonth > displayedLast.day
    ? Array.from({ length: daysInMonth - displayedLast.day + 1 }, (_, index) => {
      const day = displayedLast.day + index;
      const progress = index / (daysInMonth - displayedLast.day);
      return { day, value: displayedLast.value + (forecastTotal - displayedLast.value) * progress };
    })
    : [];
  const estimated = dedupe([...estimatedPast, ...actualDisplay, ...forecast]);
  const previousCandidates = previousActual?.cumulative_points || previousActual?.chart_points;
  const previous = Array.isArray(previousCandidates)
    ? dedupe(previousCandidates.map((point) => ({ day: Number(point.day), value: Number(point.value) })).filter((point) => Number.isFinite(point.day) && Number.isFinite(point.value) && point.day >= 1))
    : [];
  return {
    month: estimate?.month || null,
    days_in_month: daysInMonth,
    actual,
    actual_display: actualDisplay,
    estimated_past: estimatedPast,
    estimated,
    forecast_future: forecast,
    forecast,
    previous,
    actual_latest_day: actualLast?.day || null,
    actual_latest_observed_value: actualLast?.value ?? null,
    estimated_past_cost_sek: missingPastCost,
    forecast_available: forecast.length > 0,
    previous_available: previous.length > 0,
    method: "cumulative_observed_rows_with_time_allocated_fixed_fee_and_explicit_segments",
    fixed_fee_allocation_method: "monthly_fixed_fee_accrued_by_elapsed_month_fraction",
  };
}

export function buildCostChartTooltipFields({ estimated = null, actual = null, forecast = null, previous = null } = {}) {
  const fields = [];
  if (estimated != null && Number.isFinite(Number(estimated))) {
    fields.push({ label: "Estimerat hittills", value: Number(estimated) });
  }
  if (actual != null && Number.isFinite(Number(actual))) {
    fields.push({ label: "Kostnad hittills", value: Number(actual) });
  }
  if (forecast != null && Number.isFinite(Number(forecast))) {
    fields.push({ label: "Prognos", value: Number(forecast) });
  }
  if (previous != null && Number.isFinite(Number(previous))) {
    fields.push({ label: "Förra månaden", value: Number(previous) });
  }
  return fields;
}

export function buildDailyCostSeries(dailyBreakdown, month) {
  const normalizedMonth = typeof month === "string" && /^\d{4}-\d{2}$/.test(month) ? month : null;
  if (!normalizedMonth) return { month: null, days_in_month: 0, days: [], available: false };
  const [year, monthNumber] = normalizedMonth.split("-").map(Number);
  const daysInMonth = new Date(year, monthNumber, 0).getDate();
  const byDate = new Map((Array.isArray(dailyBreakdown) ? dailyBreakdown : []).map((item) => [item?.date, item]));
  const finite = (value) => value != null && value !== "" && Number.isFinite(Number(value)) ? Number(value) : null;
  const sum = (left, right) => finite(left) === null || finite(right) === null ? null : finite(left) + finite(right);
  const days = Array.from({ length: daysInMonth }, (_, index) => {
    const date = `${normalizedMonth}-${String(index + 1).padStart(2, "0")}`;
    const source = byDate.get(date) || {};
    const actual = source.actual && typeof source.actual === "object" ? source.actual : null;
    const forecast = source.forecast && typeof source.forecast === "object" ? source.forecast : null;
    const actualImport = finite(actual?.import_kwh);
    const forecastImport = finite(forecast?.import_kwh);
    const importKwh = sum(actualImport, forecastImport) ?? actualImport ?? forecastImport;
    const trade = sum(actual?.elhandel_sek, forecast?.elhandel_sek) ?? actual?.elhandel_sek ?? forecast?.elhandel_sek ?? null;
    const grid = sum(actual?.elnat_variable_sek, forecast?.elnat_variable_sek) ?? actual?.elnat_variable_sek ?? forecast?.elnat_variable_sek ?? null;
    const total = sum(actual?.total_variable_cost_sek, forecast?.total_variable_cost_sek) ?? actual?.total_variable_cost_sek ?? forecast?.total_variable_cost_sek ?? null;
    const status = actual && forecast ? "actual_plus_forecast" : actual ? actual.status || "actual" : forecast ? "forecast" : "unavailable";
    return {
      date,
      day: index + 1,
      status,
      available: total !== null || importKwh !== null,
      import_kwh: importKwh,
      elhandel_sek: trade,
      elnat_variable_sek: grid,
      total_variable_cost_sek: total,
      average_price_ore_per_kwh: importKwh > 0 && total !== null ? total / importKwh * 100 : null,
      actual,
      forecast,
      reason: source.reason || (status === "unavailable" ? "daily_actual_or_forecast_missing" : null),
      provenance: { actual: actual?.source || null, forecast: forecast?.source || null, method: actual && forecast ? "actual_to_date_plus_causal_forecast_remainder" : actual?.method || forecast?.method || null },
    };
  });
  return { month: normalizedMonth, days_in_month: daysInMonth, days, available: days.some((day) => day.available), method: "canonical_daily_billing_breakdown" };
}

export function buildDailyCostTooltipFields(day) {
  const number = (value, suffix = " kr") => value == null || !Number.isFinite(Number(value))
    ? "–"
    : `${Number(value).toLocaleString("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${suffix}`;
  return [
    { label: "Import", value: number(day?.import_kwh, " kWh") },
    { label: "Elhandel", value: number(day?.elhandel_sek) },
    { label: "Elnät rörlig", value: number(day?.elnat_variable_sek) },
    { label: "Total rörlig kostnad", value: number(day?.total_variable_cost_sek) },
    { label: "Snittpris", value: number(day?.average_price_ore_per_kwh, " öre/kWh") },
    { label: "Status", value: day?.status === "actual_plus_forecast" ? "Faktiskt + prognos" : day?.status === "actual" ? "Faktiskt" : day?.status === "actual_to_date" ? "Faktiskt hittills" : day?.status === "forecast" ? "Prognos" : "Ej tillgängligt" },
  ];
}

export function buildCostChartGeometry(width, plot, daysInMonth) {
  const plotWidth = width - plot.left - plot.right;
  const daySpan = Math.max(1, daysInMonth - 1);
  const x = (day) => plot.left + ((day - 1) / daySpan) * plotWidth;
  return { plotWidth, x };
}

export function aggregatePriceAndEnergyByPeriod(periods, meterPoints, powerSeries, mode, selectedDate = new Date(), priceForPeriod = (period) => Number(period.price)) {
  const selected = new Date(selectedDate);
  const year = selected.getFullYear();
  const month = selected.getMonth();
  const validPeriods = (Array.isArray(periods) ? periods : []).map((period) => ({
    ...period,
    startMs: new Date(period.start).getTime(),
    endMs: new Date(period.end).getTime(),
    price: Number(priceForPeriod(period)),
  })).filter((period) => Number.isFinite(period.startMs) && Number.isFinite(period.endMs) && period.endMs > period.startMs && Number.isFinite(period.price));
  const pointsFor = (key) => Array.isArray(powerSeries?.[key]?.points) ? powerSeries[key].points : [];
  const meter = Array.isArray(meterPoints) ? meterPoints : [];
  const range = mode === "day"
    ? { start: new Date(year, month, 1), count: new Date(year, month + 1, 0).getDate(), label: (date) => String(date.getDate()).padStart(2, "0") }
    : mode === "month"
      ? { start: new Date(year, 0, 1), count: 12, label: (date) => ["Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"][date.getMonth()] }
      : null;
  let buckets;
  if (range) {
    buckets = Array.from({ length: range.count }, (_, index) => {
      const start = mode === "day" ? new Date(year, month, index + 1) : new Date(year, index, 1);
      const end = mode === "day" ? new Date(year, month, index + 2) : new Date(year, index + 1, 1);
      return { key: index, label: range.label(start), startMs: start.getTime(), endMs: end.getTime() };
    });
  } else {
    const timestamps = [
      ...validPeriods.flatMap((period) => [period.startMs, period.endMs]),
      ...meter.map((point) => new Date(point.timestamp).getTime()),
      ...Object.values(powerSeries || {}).flatMap((series) => (Array.isArray(series?.points) ? series.points : []).map((point) => new Date(point.timestamp).getTime())),
    ].filter(Number.isFinite);
    const years = [...new Set(timestamps.map((timestamp) => new Date(timestamp).getFullYear()))].sort((left, right) => left - right);
    buckets = years.map((bucketYear) => ({ key: bucketYear, label: String(bucketYear), startMs: new Date(bucketYear, 0, 1).getTime(), endMs: new Date(bucketYear + 1, 0, 1).getTime() }));
  }
  const integrate = (points, key, startMs, endMs) => {
    const sorted = (Array.isArray(points) ? points : []).map((point) => ({
      timestamp: new Date(point.timestamp).getTime(),
      value: Number(point[key]),
    })).filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.value)).sort((left, right) => left.timestamp - right.timestamp);
    let total = 0;
    let covered = false;
    for (let index = 1; index < sorted.length; index += 1) {
      const left = sorted[index - 1];
      const right = sorted[index];
      if (right.timestamp <= left.timestamp || right.timestamp - left.timestamp > 30 * 60 * 1000) continue;
      const from = Math.max(startMs, left.timestamp);
      const to = Math.min(endMs, right.timestamp);
      if (to <= from) continue;
      const ratio = (timestamp) => (timestamp - left.timestamp) / (right.timestamp - left.timestamp);
      const fromValue = left.value + (right.value - left.value) * ratio(from);
      const toValue = left.value + (right.value - left.value) * ratio(to);
      total += ((fromValue + toValue) / 2) * ((to - from) / 3600000);
      covered = true;
    }
    return covered ? total : null;
  };
  return buckets.map((bucket) => {
    let priceWeighted = 0;
    let priceDuration = 0;
    let pricePeriodCount = 0;
    for (const period of validPeriods) {
      const duration = Math.max(0, Math.min(bucket.endMs, period.endMs) - Math.max(bucket.startMs, period.startMs));
      if (!duration) continue;
      priceWeighted += period.price * duration;
      priceDuration += duration;
      pricePeriodCount += 1;
    }
    const energy = {};
    const meterImport = integrateMeterEnergyByRange(meter, bucket.startMs, bucket.endMs);
    const meterExport = integrate(meter, "export_kw", bucket.startMs, bucket.endMs);
    if (meterImport !== null) energy.import = meterImport;
    if (meterExport !== null) energy.export = meterExport;
    for (const key of ["solar", "consumption", "charging", "discharging"]) {
      const value = integrate(pointsFor(key), "value_kw", bucket.startMs, bucket.endMs);
      if (value !== null) energy[key] = value;
    }
    return {
      ...bucket,
      price: priceDuration > 0 ? priceWeighted / priceDuration : null,
      price_duration_ms: priceDuration,
      price_period_count: pricePeriodCount,
      energy,
    };
  }).filter((bucket) => bucket.price !== null || Object.keys(bucket.energy).length > 0);
}

export function selectHourlyPricePeriods(periods, selectedDate = new Date()) {
  const selected = new Date(selectedDate);
  if (!Number.isFinite(selected.getTime())) return [];
  const start = new Date(selected.getFullYear(), selected.getMonth(), selected.getDate()).getTime();
  const endDate = new Date(start);
  endDate.setDate(endDate.getDate() + 1);
  const end = endDate.getTime();
  return (Array.isArray(periods) ? periods : []).filter((period) => {
    const timestamp = new Date(period?.start).getTime();
    return Number.isFinite(timestamp) && timestamp >= start && timestamp < end;
  });
}

export function aggregatedPriceGroupIndex(viewX, plotLeft, plotWidth, groupCount) {
  if (!Number.isFinite(viewX) || !Number.isFinite(plotLeft) || !Number.isFinite(plotWidth) || !Number.isInteger(groupCount) || groupCount < 1) return -1;
  if (viewX < plotLeft || viewX > plotLeft + plotWidth) return -1;
  return Math.max(0, Math.min(groupCount - 1, Math.floor((viewX - plotLeft) / (plotWidth / groupCount))));
}

export function buildPriceCategoryBands(plotLeft, plotRight, groupCount) {
  if (!Number.isFinite(plotLeft) || !Number.isFinite(plotRight) || !Number.isInteger(groupCount) || groupCount < 1 || plotRight <= plotLeft) return [];
  const bandWidth = (plotRight - plotLeft) / groupCount;
  return Array.from({ length: groupCount }, (_, index) => ({
    start: plotLeft + index * bandWidth,
    center: plotLeft + (index + .5) * bandWidth,
    end: plotLeft + (index + 1) * bandWidth,
  }));
}

export function previousCalendarMonth(month) {
  if (typeof month !== "string" || !/^\d{4}-\d{2}$/.test(month)) return null;
  const [year, monthNumber] = month.split("-").map(Number);
  if (monthNumber < 1 || monthNumber > 12) return null;
  const date = new Date(Date.UTC(year, monthNumber - 1, 1));
  date.setUTCMonth(date.getUTCMonth() - 1);
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function nextCalendarMonth(month) {
  if (typeof month !== "string" || !/^\d{4}-\d{2}$/.test(month)) return null;
  const [year, monthNumber] = month.split("-").map(Number);
  if (monthNumber < 1 || monthNumber > 12) return null;
  const date = new Date(Date.UTC(year, monthNumber - 1, 1));
  date.setUTCMonth(date.getUTCMonth() + 1);
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function normalizeInvoiceMonth(value) {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (/^\d{4}-\d{2}$/.test(trimmed)) return trimmed;
  if (/[–—-]/.test(trimmed.replace(/^\w{3,9} \d{4}/i, ""))) return null;
  const match = trimmed.match(/^(jan|feb|mar|apr|maj|may|jun|jul|aug|sep|okt|oct|nov|dec)[a-z]*\s+(\d{4})$/i);
  if (!match) return null;
  const month = { jan: 1, feb: 2, mar: 3, apr: 4, maj: 5, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, okt: 10, oct: 10, nov: 11, dec: 12 }[match[1].slice(0, 3).toLowerCase()];
  return month ? `${match[2]}-${String(month).padStart(2, "0")}` : null;
}

export function buildPreviousMonthActual(invoiceSources = {}, selectedMonth) {
  const month = previousCalendarMonth(selectedMonth);
  const finiteInvoiceNumber = (value) => value == null || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  const normalizeInvoiceAmount = (invoice) => {
    const currency = invoice.currency || invoice.currency_code || "SEK";
    const periodCost = finiteInvoiceNumber(invoice.period_cost_before_credits_sek);
    const creditsApplied = finiteInvoiceNumber(invoice.credits_applied_sek);
    if (periodCost !== null && creditsApplied !== null) return { amount_sek: periodCost, tax_basis: invoice.vat_included === true ? "gross_invoice_total" : "gross_period_total_unverified_vat", currency };
    const explicitGross = finiteInvoiceNumber(invoice.gross_amount_sek);
    if (explicitGross !== null) return { amount_sek: explicitGross, tax_basis: "gross_invoice_total", currency };
    const gross = finiteInvoiceNumber(invoice.amount_due_sek);
    if (gross !== null) return { amount_sek: gross, tax_basis: invoice.vat_included === true ? "gross_invoice_total" : "gross_settlement_unverified_vat", currency };
    const ore = finiteInvoiceNumber(invoice.amount_due_ore);
    if (ore !== null) return { amount_sek: ore / 100, tax_basis: invoice.vat_included === true ? "gross_invoice_total" : "gross_settlement_unverified_vat", currency };
    const net = finiteInvoiceNumber(invoice.net_amount_sek ?? invoice.amount_ex_vat_sek);
    const vatAmount = finiteInvoiceNumber(invoice.vat_amount_sek ?? invoice.vat_sek);
    const vatRate = finiteInvoiceNumber(invoice.vat_rate_percent ?? invoice.vat_percent);
    if (net !== null && vatAmount !== null) return { amount_sek: net + vatAmount, tax_basis: "gross_normalized_from_net_plus_vat", currency };
    if (net !== null && vatRate !== null) return { amount_sek: net * (1 + vatRate / 100), tax_basis: "gross_normalized_from_net_plus_vat_rate", currency };
    if (periodCost !== null && invoice.vat_included === true) return { amount_sek: periodCost, tax_basis: "gross_invoice_total", currency };
    return null;
  };
  const statusRank = (invoice) => ({ CURRENT: 3, FUTURE: 2, ENDED: 1 }[String(invoice?._contract_status || invoice?.contract_status || "").toUpperCase()] || 0);
  const selectCanonicalInvoice = (items) => [...items].sort((left, right) => {
    const revisionDelta = finiteInvoiceNumber(right.revision) - finiteInvoiceNumber(left.revision);
    if (Number.isFinite(revisionDelta) && revisionDelta !== 0) return revisionDelta;
    const statusDelta = statusRank(right) - statusRank(left);
    if (statusDelta !== 0) return statusDelta;
    const rightDate = String(right.known_at || right.captured_at || right.invoice_date || "");
    const leftDate = String(left.known_at || left.captured_at || left.invoice_date || "");
    if (rightDate !== leftDate) return rightDate.localeCompare(leftDate);
    return String(right._invoice_key || right.invoice_key || "").localeCompare(String(left._invoice_key || left.invoice_key || ""));
  })[0] || null;
  const normalizeProvider = (items) => {
    const matches = (Array.isArray(items) ? items : []).filter((invoice) => invoice && normalizeInvoiceMonth(invoice.month) === month);
    const selected = selectCanonicalInvoice(matches);
    const normalized = selected ? [selected].map((invoice) => {
      const periodCost = finiteInvoiceNumber(invoice.period_cost_before_credits_sek);
      const amountDue = finiteInvoiceNumber(invoice.amount_due_sek);
      const normalizedAmount = normalizeInvoiceAmount(invoice);
      const comparisonValue = normalizedAmount?.amount_sek ?? null;
      return {
        invoice_exists: true,
        billing_period: invoice.billing_period || invoice.month,
        period_cost_sek: periodCost,
        period_cost_before_credits_sek: periodCost,
        credits_applied_sek: finiteInvoiceNumber(invoice.credits_applied_sek),
        amount_due_sek: amountDue,
        comparison_value_sek: comparisonValue,
        amount_gross_sek: normalizedAmount?.amount_sek ?? null,
        tax_basis: normalizedAmount?.tax_basis ?? null,
        currency: normalizedAmount?.currency ?? null,
        invoice_key: invoice._invoice_key || invoice.invoice_key || null,
        source: invoice.source || null,
      };
    }) : [];
    const comparable = normalized.filter((invoice) => Number.isFinite(invoice.comparison_value_sek));
    const total = comparable.reduce((sum, invoice) => sum + invoice.comparison_value_sek, 0);
    const sumField = (field) => {
      const values = normalized.map((invoice) => invoice[field]).filter((value) => Number.isFinite(value));
      return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
    };
    return {
      available: comparable.length > 0,
      invoice_exists: matches.length > 0,
      total_sek: comparable.length ? total : null,
      billing_period: normalized.length === 1 ? normalized[0].billing_period : month,
      period_cost_sek: sumField("period_cost_sek"),
      period_cost_before_credits_sek: sumField("period_cost_before_credits_sek"),
      credits_applied_sek: sumField("credits_applied_sek"),
      amount_due_sek: sumField("amount_due_sek"),
      comparison_value_sek: comparable.length ? total : null,
      source: normalized.length === 1 ? normalized[0].source : null,
      invoices: normalized,
    };
  };
  const trade = normalizeProvider(invoiceSources.trade);
  const gridMatches = Array.isArray(invoiceSources.grid) ? invoiceSources.grid.filter((invoice) => invoice && normalizeInvoiceMonth(invoice.month) === month) : [];
  const grid = gridMatches.length ? normalizeProvider(gridMatches) : {
    available: false,
    invoice_exists: false,
    billing_period: month,
    period_cost_sek: null,
    period_cost_before_credits_sek: null,
    credits_applied_sek: null,
    amount_due_sek: null,
    comparison_value_sek: null,
    total_sek: null,
    source: null,
    invoices: [],
    reason: "no_previous_invoice",
  };
  const coverage = trade.available && grid.available ? "complete" : trade.available || grid.available ? "partial" : "missing";
  const sourcesPresent = [trade.available ? "elhandel" : null, grid.available ? "elnät" : null].filter(Boolean);
  const sourcesMissing = [trade.available ? null : "elhandel", grid.available ? null : "elnät"].filter(Boolean);
  const sourceSignatures = [trade, grid].filter((item) => item.available).map((item) => `${item.invoices[0]?.currency || "SEK"}:${item.invoices[0]?.tax_basis || "unknown"}`);
  const comparableBasis = new Set(sourceSignatures).size <= 1;
  const combinableBasis = comparableBasis && sourceSignatures.every((signature) => !signature.includes("unverified_vat"));
  const knownAmounts = [trade, grid].filter((item) => item.available && item.invoices[0]?.currency === "SEK" && item.invoices[0]?.tax_basis);
  const knownAmountGrossSek = knownAmounts.length
    ? knownAmounts.reduce((sum, item) => sum + Number(item.total_sek), 0)
    : null;
  const complete = coverage === "complete" && combinableBasis;
  return {
    month,
    trade,
    grid,
    coverage: complete ? "complete" : coverage === "missing" ? "missing" : "partial",
    total_sek: complete && Number.isFinite(trade.total_sek) && Number.isFinite(grid.total_sek) ? trade.total_sek + grid.total_sek : null,
    known_amount_gross_sek: Number.isFinite(knownAmountGrossSek) ? knownAmountGrossSek : null,
    sources_present: sourcesPresent,
    sources_missing: sourcesMissing,
    source_signature: sourceSignatures.join("+") || null,
    tax_compatible: comparableBasis,
    tax_combinable: combinableBasis,
    comparison: {
      available: complete && Number.isFinite(trade.total_sek) && Number.isFinite(grid.total_sek),
      coverage: complete ? "complete" : coverage,
      reason: !combinableBasis && coverage === "complete" ? "incompatible_tax_basis" : coverage === "partial" && !grid.available ? "previous_grid_invoice_missing" : null,
    },
  };
}

export function buildInvoiceComparison(estimate, previousActual) {
  const current = estimate?.estimated_month_total_sek == null ? null : Number(estimate.estimated_month_total_sek);
  const previous = previousActual?.total_sek == null ? null : Number(previousActual.total_sek);
  const complete = previousActual?.coverage === "complete"
    && Number.isFinite(current)
    && Number.isFinite(previous)
    && previous >= 0;
  if (!complete) {
    return {
      available: false,
      month: previousActual?.month || null,
      coverage: previousActual?.coverage || "missing",
      reason: previousActual?.comparison?.reason || null,
      difference_sek: null,
      difference_percent: null,
      scale_max_sek: Number.isFinite(current) && current >= 0 ? current : null,
      fill_percent: Number.isFinite(current) && current > 0 ? 100 : 0,
      previous_marker_percent: null,
    };
  }
  const scaleMax = Math.max(current, previous);
  const difference = current - previous;
  return {
    available: true,
    month: previousActual.month,
    coverage: "complete",
    reason: null,
    difference_sek: difference,
    difference_percent: previous > 0 ? difference / previous * 100 : null,
    scale_max_sek: scaleMax,
    fill_percent: scaleMax > 0 ? current / scaleMax * 100 : 0,
    previous_marker_percent: scaleMax > 0 ? previous / scaleMax * 100 : 0,
  };
}

export function buildCostKpiComparisons(estimate, previousActual, checkpoints = []) {
  const finite = (value) => value != null && value !== "" && Number.isFinite(Number(value)) ? Number(value) : null;
  const currentEstimated = finite(estimate?.estimated_month_total_sek);
  const previousInvoiceTotal = previousActual?.coverage !== "missing"
    ? finite(previousActual?.total_sek ?? previousActual?.known_amount_gross_sek)
    : null;
  const previousPartial = previousActual?.coverage === "partial";
  const sameTimeCheckpoint = Array.isArray(checkpoints)
    ? checkpoints.find((checkpoint) => checkpoint?.kind === "previous_month_same_local_time" && finite(checkpoint.cost_to_date_sek) != null && checkpoint.causal === true)
    : null;
  const remainingBaseline = previousInvoiceTotal != null && sameTimeCheckpoint
    ? previousInvoiceTotal - Number(sameTimeCheckpoint.cost_to_date_sek)
    : null;
  const comparison = (key, label, current, baseline, available, reason, partialBaseline = false) => {
    const currentValue = finite(current);
    const baselineValue = finite(baseline);
    if (!available || currentValue == null || baselineValue == null || baselineValue < 0) {
      return { key, label, available: false, reason, difference_sek: null, difference_percent: null, partial_baseline: partialBaseline };
    }
    const difference = currentValue - baselineValue;
    return {
      key,
      label,
      available: true,
      direction: difference > 0 ? "up" : difference < 0 ? "down" : "same",
      difference_sek: difference,
      difference_percent: baselineValue > 0 ? difference / baselineValue * 100 : null,
      partial_baseline: partialBaseline,
    };
  };
  return [
    comparison("estimated_month_total", "Mot förra månaden", currentEstimated, previousInvoiceTotal, previousInvoiceTotal != null, "previous_invoice_total_missing", previousPartial),
    comparison("cost_to_date", "Mot samma tid förra månaden", estimate?.total_so_far_sek, sameTimeCheckpoint?.cost_to_date_sek, Boolean(sameTimeCheckpoint), "historical_same_time_checkpoint_missing"),
    comparison("forecast_remaining", "Återstående mot förra månaden", estimate?.forecast_remaining_total_sek, remainingBaseline, remainingBaseline != null, "historical_same_time_checkpoint_missing", previousPartial),
  ];
}

export function buildInvoiceMonthHistory(estimate, invoiceSources = {}) {
  const finite = (value) => value != null && value !== "" && Number.isFinite(Number(value)) ? Number(value) : null;
  const months = new Set();
  if (estimate?.month) months.add(estimate.month);
  for (const invoices of [invoiceSources.trade, invoiceSources.grid]) {
    for (const invoice of Array.isArray(invoices) ? invoices : []) {
      const normalizedMonth = normalizeInvoiceMonth(invoice?.month);
      const amountDue = invoice?.amount_due_sek == null || invoice.amount_due_sek === "" ? null : Number(invoice.amount_due_sek);
      const gross = invoice?.gross_amount_sek == null || invoice.gross_amount_sek === "" ? null : Number(invoice.gross_amount_sek);
      const ore = invoice?.amount_due_ore == null || invoice.amount_due_ore === "" ? null : Number(invoice.amount_due_ore);
      const periodCost = invoice?.period_cost_before_credits_sek == null || invoice.period_cost_before_credits_sek === "" ? null : Number(invoice.period_cost_before_credits_sek);
      const hasGross = [amountDue, gross, ore].some(Number.isFinite);
      const hasExplicitGrossPeriod = Number.isFinite(periodCost) && invoice?.vat_included === true;
      const hasCreditedPeriod = Number.isFinite(periodCost) && Number.isFinite(Number(invoice?.credits_applied_sek));
      const hasNetWithVat = Number.isFinite(Number(invoice?.net_amount_sek ?? invoice?.amount_ex_vat_sek))
        && (Number.isFinite(Number(invoice?.vat_amount_sek ?? invoice?.vat_sek)) || Number.isFinite(Number(invoice?.vat_rate_percent ?? invoice?.vat_percent)));
      if (normalizedMonth && (hasGross || hasExplicitGrossPeriod || hasCreditedPeriod || hasNetWithVat)) months.add(normalizedMonth);
    }
  }
  return [...months].sort().reverse().slice(0, 12).map((month) => {
    if (month === estimate?.month) {
      return {
        month,
        current: true,
        coverage: estimate?.forecast_confidence === "complete_available_data" ? "complete" : "partial",
        total_sek: Number.isFinite(Number(estimate?.total_so_far_sek)) ? Number(estimate.total_so_far_sek) : null,
        estimated_total_sek: Number.isFinite(Number(estimate?.estimated_month_total_sek)) ? Number(estimate.estimated_month_total_sek) : null,
        trade_sek: Number.isFinite(Number(estimate?.trade?.total_so_far_sek)) ? Number(estimate.trade.total_so_far_sek) : null,
        grid_sek: Number.isFinite(Number(estimate?.grid?.total_so_far_sek)) ? Number(estimate.grid.total_so_far_sek) : null,
      };
    }
    const actual = buildPreviousMonthActual(invoiceSources, nextCalendarMonth(month));
    return {
      month,
      current: false,
      coverage: actual.coverage,
      total_sek: actual.total_sek,
      known_amount_gross_sek: actual.known_amount_gross_sek,
      estimated_total_sek: null,
      trade_sek: Number.isFinite(Number(actual.trade?.total_sek)) ? Number(actual.trade.total_sek) : null,
      grid_sek: Number.isFinite(Number(actual.grid?.total_sek)) ? Number(actual.grid.total_sek) : null,
      sources_present: actual.sources_present,
      sources_missing: actual.sources_missing,
      source_signature: actual.source_signature,
      tax_compatible: actual.tax_compatible,
      tax_combinable: actual.tax_combinable,
    };
  });
}

export function buildCostMonthComparison(selected, previous) {
  const current = selected?.total_sek == null ? null : Number(selected.total_sek);
  const prior = previous?.total_sek == null ? null : Number(previous.total_sek);
  if (!Number.isFinite(current) || !Number.isFinite(prior) || selected?.coverage !== "complete" || previous?.coverage !== "complete") {
    return { available: false, reason: "incomplete_month_data", difference_sek: null, difference_percent: null };
  }
  const difference = current - prior;
  return { available: true, direction: difference > 0 ? "up" : difference < 0 ? "down" : "same", difference_sek: difference, difference_percent: prior > 0 ? difference / prior * 100 : null };
}

export function buildCostReferenceComparisons(monthHistory, selectedMonth, selectedValue) {
  const selectedIndex = (Array.isArray(monthHistory) ? monthHistory : []).findIndex((item) => item.month === selectedMonth);
  const history = selectedIndex >= 0 ? monthHistory.slice(selectedIndex + 1) : [];
  const selectedRecord = selectedIndex >= 0 ? monthHistory[selectedIndex] : null;
  const selectedSignature = selectedRecord?.source_signature || null;
  const selectedIsCurrentEstimate = selectedRecord?.current === true
    && Number.isFinite(Number(selectedRecord.estimated_total_sek));
  const resolvedSelectedValue = selectedIsCurrentEstimate
    ? Number(selectedRecord.estimated_total_sek)
    : selectedRecord?.coverage !== "missing"
      && selectedValue != null
      && selectedValue !== ""
      && Number.isFinite(Number(selectedValue))
      ? Number(selectedValue)
      : null;
  const comparable = (item) => item
    && item.coverage !== "missing"
    && item.tax_compatible !== false
    && Number.isFinite(Number(item.coverage === "complete" ? item.total_sek : item.known_amount_gross_sek))
    && (!selectedSignature || item.source_signature === selectedSignature);
  const valueOf = (item) => Number(item.coverage === "complete" ? item.total_sek : item.known_amount_gross_sek);
  const baselineItems = history.filter(comparable);
  const activeCurrentValue = resolvedSelectedValue;
  const reference = (count) => {
    const items = baselineItems.slice(0, count);
    const values = items.map(valueOf);
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  };
  const baselineItemsFor = (count) => baselineItems.slice(0, count);
  return [
    { key: "previous", label: "Mot förra månaden", value: baselineItems[0] ? valueOf(baselineItems[0]) : null, sample_count: baselineItems[0] ? 1 : 0 },
    { key: "three_month_average", label: "Mot 3 månaders snitt", value: reference(3), sample_count: Math.min(3, baselineItems.length) },
    { key: "twelve_month_average", label: "Mot 12 månaders snitt", value: reference(12), sample_count: Math.min(12, baselineItems.length) },
  ].map((item) => {
    const current = activeCurrentValue;
    const baseline = item.value == null ? null : Number(item.value);
    const comparisonScope = selectedIsCurrentEstimate ? "current_estimated_month_vs_invoice_total_history" : "invoice_total_history";
    const baselineItemsForComparison = baselineItemsFor(item.key === "previous" ? 1 : item.key === "three_month_average" ? 3 : 12);
    const partialBaseline = baselineItemsForComparison.some((baselineItem) => baselineItem.coverage === "partial");
    if (!Number.isFinite(current) || !Number.isFinite(baseline) || item.sample_count === 0) return { ...item, available: false, difference_sek: null, difference_percent: null, comparison_scope: comparisonScope, partial_baseline: partialBaseline, current_value_source: selectedIsCurrentEstimate ? "estimated_month_total_sek" : "selected_month_value" };
    const difference = current - baseline;
    return { ...item, available: true, direction: difference > 0 ? "up" : difference < 0 ? "down" : "same", difference_sek: difference, difference_percent: baseline > 0 ? difference / baseline * 100 : null, comparison_scope: comparisonScope, partial_baseline: partialBaseline, current_value_source: selectedIsCurrentEstimate ? "estimated_month_total_sek" : "selected_month_value" };
  });
}

export function costHistoryDisplayOrder(monthHistory) {
  return Array.isArray(monthHistory) ? [...monthHistory].reverse() : [];
}

export function buildInvoiceProvenance(estimate, billingHistory = {}) {
  if (!estimate) return null;
  const gridPrice = billingHistory.grid_price || {};
  const energyPoints = Array.isArray(billingHistory.energy_points) ? billingHistory.energy_points : [];
  const rows = Array.isArray(estimate.rows) ? estimate.rows.map((row) => ({
    timestamp: row.start,
    imported_kwh: row.import_kwh,
      trade: {
        ore_per_kwh_gross: row.trade_price_ore_per_kwh_gross,
        vat_included: billingHistory.trade_vat_included ?? (Number.isFinite(row.vat_ore_per_kwh) ? true : null),
      spot_price_ex_vat_ore_per_kwh: row.spot_price_ex_vat_ore_per_kwh,
      electricity_cost_ex_vat_ore_per_kwh: row.electricity_cost_ex_vat_ore_per_kwh,
      vat_ore_per_kwh: row.vat_ore_per_kwh,
    },
    grid: {
      transfer_ore_per_kwh_gross: Number.isFinite(Number(gridPrice.transfer_ore_per_kwh_gross)) ? Number(gridPrice.transfer_ore_per_kwh_gross) : null,
      energy_tax_ore_per_kwh_gross: Number.isFinite(Number(gridPrice.energy_tax_ore_per_kwh_gross)) ? Number(gridPrice.energy_tax_ore_per_kwh_gross) : null,
      variable_total_ore_per_kwh_gross: row.grid_price_ore_per_kwh_gross,
      vat_included: gridPrice.vat_included ?? null,
    },
    trade_cost_sek: row.trade_cost_sek,
    grid_cost_sek: row.grid_cost_sek,
  })) : [];
  const tradeFixedValue = estimate.trade?.fixed_fee_sek;
  const gridFixedValue = estimate.grid?.fixed_fee_sek;
  const tradeFixed = tradeFixedValue != null && Number.isFinite(Number(tradeFixedValue)) ? Number(tradeFixedValue) : null;
  const gridFixed = gridFixedValue != null && Number.isFinite(Number(gridFixedValue)) ? Number(gridFixedValue) : null;
  const gridTransfer = Number(gridPrice.transfer_ore_per_kwh_gross);
  const gridEnergyTax = Number(gridPrice.energy_tax_ore_per_kwh_gross);
  const gridComponentTotal = gridTransfer + gridEnergyTax;
  const splitGridCost = (total, component) => Number.isFinite(Number(total)) && Number.isFinite(component) && gridComponentTotal > 0
    ? Number(total) * component / gridComponentTotal
    : null;
  return {
    energy_source: {
      method: billingHistory.energy_source?.method || "integrated_grid_power",
      source_entities: ((Array.isArray(billingHistory.energy_source?.source_entities) && billingHistory.energy_source.source_entities.length)
        ? billingHistory.energy_source.source_entities
        : [{
        entity_id: billingHistory.energy_source?.entity_id || billingHistory.entity_id || null,
        raw_unit: billingHistory.energy_source?.raw_unit || "kW",
        role: "grid_active_power",
        invert: billingHistory.energy_source?.invert ?? null,
        canonical_sign_convention: billingHistory.energy_source?.canonical_sign_convention || null,
      }]).filter((source) => source?.entity_id),
      raw_unit: billingHistory.energy_source?.raw_unit || "kW",
      source_entity: billingHistory.energy_source?.source_entity || billingHistory.energy_source?.entity_id || billingHistory.entity_id || null,
      sample_count: energyPoints.length || null,
      period_start_value: billingHistory.energy_source?.period_start_value ?? null,
      current_value: billingHistory.energy_source?.current_value ?? null,
      imported_kwh_so_far: estimate.imported_kwh_so_far,
      actual_imported_kwh_display: estimate.actual_imported_kwh_display ?? estimate.imported_kwh_so_far,
      priced_imported_kwh: estimate.priced_imported_kwh ?? null,
      integration_method: billingHistory.integration_method || "trapezoidal_power_integration",
      result_kwh: estimate.actual_imported_kwh_display ?? estimate.imported_kwh_so_far,
    },
    trade_variable: {
      rows,
      formula: "sum(imported_kwh * trade_customer_price_ore_per_kwh_gross / 100)",
      total_sek: estimate.trade?.variable_cost_sek ?? null,
    },
    grid_variable: {
      transfer_ore_per_kwh_gross: gridPrice.transfer_ore_per_kwh_gross ?? null,
      energy_tax_ore_per_kwh_gross: gridPrice.energy_tax_ore_per_kwh_gross ?? null,
      variable_total_ore_per_kwh_gross: estimate.grid_weighted_average_ore_per_kwh ?? null,
      vat_included: gridPrice.vat_included ?? null,
      formula: "(transfer + energy_tax) * imported_kwh / 100",
      total_sek: estimate.grid?.variable_cost_sek ?? null,
    },
    fixed_fees: {
      trade: { monthly_fee_sek: tradeFixed, vat_included: billingHistory.trade_fixed_vat_included ?? (tradeFixed !== null ? true : null), source: billingHistory.trade_fixed_source || estimate.trade_fixed_fee_source || (tradeFixed !== null ? "provider_summary.tariff.fixed_fee_incl_vat_per_month" : null) },
      grid: { monthly_fee_sek: gridFixed, vat_included: gridPrice.vat_included ?? null, source: gridPrice.source || null },
      total_monthly_fixed_sek: (tradeFixed !== null && gridFixed !== null) ? tradeFixed + gridFixed : null,
      applied_once: true,
    },
    actual_so_far: {
      imported_kwh: estimate.imported_kwh_so_far,
      trade_variable_sek: estimate.trade?.variable_cost_sek ?? null,
      grid_variable_sek: estimate.grid?.variable_cost_sek ?? null,
      fixed_fee_accrual_sek: (estimate.trade?.accrued_fixed_fee_sek || 0) + (estimate.grid?.accrued_fixed_fee_sek || 0),
      total_sek: estimate.total_so_far_sek ?? null,
    },
    forecast_remaining: {
      method: estimate.forecast_method,
      days_remaining: billingHistory.days_remaining ?? null,
      forecast_import_kwh: estimate.forecast_import_kwh ?? null,
      forecast_remaining_kwh: estimate.forecast_remaining_kwh ?? null,
      forecast_missing_past_kwh: estimate.forecast_missing_past_kwh ?? null,
      forecast_trade_variable_sek: estimate.forecast_remaining_trade_variable_sek ?? null,
      forecast_grid_variable_sek: estimate.forecast_remaining_grid_variable_sek ?? null,
      forecast_missing_past_trade_sek: estimate.forecast_missing_past_trade_sek ?? null,
      forecast_missing_past_grid_sek: estimate.forecast_missing_past_grid_sek ?? null,
      total_sek: estimate.forecast_remaining_total_sek ?? null,
      historical_baseline_daily_kwh: estimate.historical_baseline_daily_kwh ?? null,
      observed_current_daily_kwh: estimate.observed_current_daily_kwh ?? null,
      blend_weight: estimate.blend_weight ?? null,
      forecast_daily_kwh: estimate.forecast_daily_kwh ?? null,
      source: estimate.forecast_source || null,
      fallback: estimate.forecast_fallback || null,
      actual_so_far_sek: estimate.actual_so_far_sek ?? null,
      remaining_estimated_sek: estimate.remaining_estimated_sek ?? null,
      spot_price_source: billingHistory.spot_price_source || null,
      fallback_price: billingHistory.fallback_price ?? null,
      confidence: estimate.forecast_confidence,
      coverage: estimate.data_coverage || null,
    },
    estimated_month: {
      variable_actual_sek: (estimate.trade?.variable_cost_sek || 0) + (estimate.grid?.variable_cost_sek || 0),
      variable_forecast_sek: estimate.estimated_month_total_sek == null ? null : estimate.estimated_month_total_sek - (tradeFixed || 0) - (gridFixed || 0),
      trade_monthly_fee_sek: tradeFixed,
      grid_monthly_fee_sek: gridFixed,
      estimated_total_sek: estimate.estimated_month_total_sek,
    },
    calculation: {
      trade_variable_actual_sek: estimate.trade?.variable_cost_sek ?? null,
      trade_variable_forecast_remaining_sek: estimate.forecast_remaining_trade_variable_sek ?? null,
      trade_variable_estimated_month_sek: estimate.trade?.variable_cost_sek == null || estimate.forecast_remaining_trade_variable_sek == null ? null : estimate.trade.variable_cost_sek + estimate.forecast_remaining_trade_variable_sek,
      grid_transfer_actual_sek: splitGridCost(estimate.grid?.variable_cost_sek, gridTransfer),
      grid_transfer_forecast_remaining_sek: splitGridCost(estimate.forecast_remaining_grid_variable_sek, gridTransfer),
      grid_transfer_estimated_month_sek: gridPrice.transfer_ore_per_kwh_gross == null || estimate.forecast_import_kwh == null ? null : estimate.forecast_import_kwh * Number(gridPrice.transfer_ore_per_kwh_gross) / 100,
      grid_energy_tax_actual_sek: splitGridCost(estimate.grid?.variable_cost_sek, gridEnergyTax),
      grid_energy_tax_forecast_remaining_sek: splitGridCost(estimate.forecast_remaining_grid_variable_sek, gridEnergyTax),
      grid_energy_tax_estimated_month_sek: gridPrice.energy_tax_ore_per_kwh_gross == null || estimate.forecast_import_kwh == null ? null : estimate.forecast_import_kwh * Number(gridPrice.energy_tax_ore_per_kwh_gross) / 100,
      grid_fixed_sek: gridFixed,
      trade_fixed_sek: tradeFixed,
      other_sek: 0,
      estimated_total_sek: estimate.estimated_month_total_sek,
      component_sum_sek: [
        estimate.trade?.variable_cost_sek,
        estimate.forecast_remaining_trade_variable_sek,
        splitGridCost(estimate.grid?.variable_cost_sek, gridTransfer),
        splitGridCost(estimate.forecast_remaining_grid_variable_sek, gridTransfer),
        splitGridCost(estimate.grid?.variable_cost_sek, gridEnergyTax),
        splitGridCost(estimate.forecast_remaining_grid_variable_sek, gridEnergyTax),
        tradeFixed,
        gridFixed,
      ].reduce((sum, value) => sum + (Number.isFinite(Number(value)) ? Number(value) : 0), 0),
      formula: "trade_variable_actual + trade_variable_forecast_remaining + grid_transfer_actual + grid_transfer_forecast_remaining + grid_energy_tax_actual + grid_energy_tax_forecast_remaining + trade_fixed + grid_fixed",
    },
    vat_audit: {
      spot: { source_is_ex_vat: rows.some((row) => Number.isFinite(row.trade.spot_price_ex_vat_ore_per_kwh)), vat_added_by_calculation: false, vat_component_present: rows.some((row) => Number.isFinite(row.trade.vat_ore_per_kwh)) },
      trade_variable: { source_is_ex_vat: rows.some((row) => Number.isFinite(row.trade.electricity_cost_ex_vat_ore_per_kwh)), vat_added_by_calculation: false, gross_price_source: "period.customer_price", vat_component_present: rows.some((row) => Number.isFinite(row.trade.vat_ore_per_kwh)) },
      grid_transfer: { included_at_source: gridPrice.vat_included ?? null, vat_added_by_us: gridPrice.vat_included === true ? false : null },
      energy_tax: { included_at_source: gridPrice.vat_included ?? null, vat_added_by_us: gridPrice.vat_included === true ? false : null },
      grid_fixed_fee: { included_at_source: gridPrice.vat_included ?? null, vat_added_by_us: gridPrice.vat_included === true ? false : null },
    },
  };
}

export function buildBatteryDailyHistory(chargingPoints, dischargingPoints, capacityKwh, now = new Date(), dayCount = 7) {
  const current = new Date(now);
  const todayStart = new Date(current.getFullYear(), current.getMonth(), current.getDate());
  const requestedDays = Number(dayCount);
  const days = Math.max(1, Math.min(7, Number.isFinite(requestedDays) ? Math.trunc(requestedDays) : 7));
  const pointsForDay = (points, dayStart, dayEnd) => (Array.isArray(points) ? points : []).filter((point) => {
    const timestamp = new Date(point.timestamp).getTime();
    return Number.isFinite(timestamp) && timestamp >= dayStart.getTime() && timestamp < dayEnd.getTime() && Number.isFinite(Number(point.value_kw));
  });
  return Array.from({ length: days }, (_, index) => {
    const dayStart = new Date(todayStart);
    dayStart.setDate(todayStart.getDate() - (days - index - 1));
    const dayEnd = new Date(dayStart);
    dayEnd.setDate(dayStart.getDate() + 1);
    const charging = pointsForDay(chargingPoints, dayStart, dayEnd);
    const discharging = pointsForDay(dischargingPoints, dayStart, dayEnd);
    const integrationNow = dayEnd <= current ? dayEnd : current;
    const chargedKwh = charging.length ? integratePowerHistoryKwh(charging, dayStart, dayEnd, integrationNow) : null;
    const dischargedKwh = discharging.length ? integratePowerHistoryKwh(discharging, dayStart, dayEnd, integrationNow) : null;
    return {
      date: dayStart.toLocaleDateString("sv-SE"),
      label: dayStart.toLocaleDateString("sv-SE", { day: "2-digit", month: "2-digit" }),
      chargingKwh: chargedKwh,
      dischargingKwh: dischargedKwh,
      utilizationPercent: Number.isFinite(Number(dischargedKwh)) && Number.isFinite(Number(capacityKwh)) && Number(capacityKwh) > 0
        ? Number(dischargedKwh) / Number(capacityKwh) * 100
        : null,
    };
  });
}

export function buildSolarDailyHistory(points, forecastBaselines, now = new Date(), dayCount = 7, liveForecast = null, shadowDays = null) {
  const forecastCompletionEpsilonKwh = 0.001;
  const current = new Date(now);
  const todayStart = new Date(current.getFullYear(), current.getMonth(), current.getDate());
  const days = Math.max(1, Math.min(7, Math.trunc(Number(dayCount) || 7)));
  const forecastByDate = forecastBaselines && typeof forecastBaselines === "object" ? forecastBaselines : {};
  const shadowByDate = Array.isArray(shadowDays)
    ? Object.fromEntries(shadowDays.filter((item) => item && typeof item.target_date === "string").map((item) => [item.target_date, item]))
    : null;
  return Array.from({ length: days }, (_, index) => {
    const dayStart = new Date(todayStart);
    dayStart.setDate(todayStart.getDate() - (days - index - 1));
    const dayEnd = new Date(dayStart);
    dayEnd.setDate(dayStart.getDate() + 1);
    const dayPoints = (Array.isArray(points) ? points : []).filter((point) => {
      const timestamp = new Date(point.timestamp).getTime();
      return Number.isFinite(timestamp) && timestamp >= dayStart.getTime() && timestamp < dayEnd.getTime() && Number.isFinite(Number(point.value_kw));
    });
    const actualKwh = dayPoints.length ? integratePowerHistoryKwh(dayPoints, dayStart, dayEnd, dayEnd <= current ? dayEnd : current) : null;
    const localDate = dayStart.toLocaleDateString("sv-SE");
    const forecastKwh = Number.isFinite(Number(forecastByDate[localDate])) ? Number(forecastByDate[localDate]) : null;
    const isToday = dayStart.getTime() === todayStart.getTime();
    const liveTodayKwh = Number.isFinite(Number(liveForecast?.today_kwh)) ? Number(liveForecast.today_kwh) : null;
    const liveRemainingKwh = Number.isFinite(Number(liveForecast?.remaining_today_kwh)) ? Number(liveForecast.remaining_today_kwh) : null;
    const expectedSoFarKwh = isToday && liveTodayKwh !== null && liveRemainingKwh !== null
      ? liveTodayKwh - liveRemainingKwh
      : null;
    const completedToday = isToday && liveRemainingKwh !== null && liveRemainingKwh <= forecastCompletionEpsilonKwh;
    const comparisonExpectedKwh = isToday
      ? (completedToday ? forecastKwh : expectedSoFarKwh)
      : forecastKwh;
    const shadowComparisonAvailable = shadowByDate === null
      ? true
      : shadowByDate[localDate]?.candidate_comparison_available === true;
    const shadowCandidateKwh = shadowByDate !== null && Number.isFinite(Number(shadowByDate[localDate]?.candidate_forecast_kwh))
      ? Number(shadowByDate[localDate].candidate_forecast_kwh)
      : forecastKwh;
    const comparisonBasis = isToday
      ? (completedToday ? (forecastKwh !== null ? "full_day_forecast" : "full_day_forecast_unavailable") : "forecast_so_far")
      : "full_day_forecast";
    const comparisonExpectedWithShadowKwh = shadowByDate !== null && shadowComparisonAvailable
      ? shadowCandidateKwh
      : (isToday ? (completedToday ? shadowCandidateKwh : expectedSoFarKwh) : shadowCandidateKwh);
    const comparisonIsValid = shadowComparisonAvailable && Number.isFinite(actualKwh) && Number.isFinite(comparisonExpectedWithShadowKwh)
      && actualKwh >= 0 && comparisonExpectedWithShadowKwh > 0;
    const forecastAccuracyPercent = comparisonIsValid
      ? Math.max(0, Math.min(100, Math.min(actualKwh, comparisonExpectedWithShadowKwh) / Math.max(actualKwh, comparisonExpectedWithShadowKwh) * 100))
      : null;
    const forecastDeviationPercent = comparisonIsValid
      ? (actualKwh - comparisonExpectedWithShadowKwh) / comparisonExpectedWithShadowKwh * 100
      : null;
    return {
      date: localDate,
      label: dayStart.toLocaleDateString("sv-SE", { day: "2-digit", month: "2-digit" }),
      producedKwh: actualKwh,
      forecastKwh,
      utilizationPercent: forecastAccuracyPercent,
      forecastAccuracyPercent,
      forecastDeviationPercent,
      forecastComparisonActualKwh: actualKwh,
      forecastComparisonExpectedKwh: comparisonExpectedWithShadowKwh,
      forecastComparisonBasis: comparisonBasis,
      rawDayForecastKwh: forecastKwh,
      rawExpectedSoFarKwh: expectedSoFarKwh,
      actualSoFarKwh: isToday ? actualKwh : null,
      forecastCompletionEpsilonKwh,
      performanceRatio: comparisonIsValid ? actualKwh / comparisonExpectedKwh : null,
      performanceDeltaPercent: forecastDeviationPercent,
    };
  });
}

export function solarEvidenceStatus(evidenceDays, date, today = localDateKey(new Date())) {
  const evidenceDay = (Array.isArray(evidenceDays) ? evidenceDays : []).find((day) => day?.date === date);
  if (!evidenceDay || evidenceDay.audit_complete == null) return "–";
  if (evidenceDay.audit_complete === true) return "✅";
  return date === today ? "–" : "❌";
}

export function summarizeSolarEvidenceHistory(evidenceDays) {
  const dates = (Array.isArray(evidenceDays) ? evidenceDays : [])
    .map((day) => day?.date)
    .filter((date) => typeof date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(date))
    .sort();
  return {
    count: dates.length,
    first_date: dates[0] || null,
    last_date: dates[dates.length - 1] || null,
  };
}

export function solarEvidenceCardHidden(debugEnabled, evidenceAvailable) {
  return !Boolean(debugEnabled) || !Boolean(evidenceAvailable);
}

export function formatSolarEvidenceCaptureTasks(captureTasks) {
  if (!captureTasks || typeof captureTasks !== "object" || Array.isArray(captureTasks)) return [];
  return Object.entries(captureTasks)
    .filter(([, task]) => task && typeof task === "object" && !Array.isArray(task))
    .slice(0, 3)
    .map(([key, task]) => ({
      source: task.source || key,
      outcome: Object.prototype.hasOwnProperty.call(task, "outcome") ? task.outcome : null,
      scheduled_at: task.scheduled_at || null,
      started_at: task.started_at || null,
      finished_at: task.finished_at || null,
      target_date: task.target_date || null,
      target_site_ids: Array.isArray(task.target_site_ids) ? task.target_site_ids.slice(0, 8) : [],
      error_type: task.error_type || null,
      error: task.error || null,
    }));
}

export function applySolarEvidenceVisibility(element, debugEnabled, evidenceAvailable, hasCaptureTasks = false) {
  if (!element) return;
  const hidden = !Boolean(debugEnabled) || (!Boolean(evidenceAvailable) && !Boolean(hasCaptureTasks));
  element.hidden = hidden;
  if (element.style) element.style.display = hidden ? "none" : "";
}

export function buildSolarHistoryTooltipLines(day, liveForecast, now = new Date(), weather = null, sun = null) {
  const lines = [];
  if (Number.isFinite(day?.producedKwh)) {
    lines.push(`Producerat: ${day.producedKwh} kWh`);
  }
  const today = new Date(now).toLocaleDateString("sv-SE");
  if (day?.date === today && (!day?.forecastComparisonBasis || day.forecastComparisonBasis === "forecast_so_far")) {
    const liveTodayKwh = Number.isFinite(Number(liveForecast?.today_kwh)) ? Number(liveForecast.today_kwh) : null;
    const liveRemainingKwh = Number.isFinite(Number(liveForecast?.remaining_today_kwh)) ? Number(liveForecast.remaining_today_kwh) : null;
    const expectedSoFarKwh = liveTodayKwh !== null && liveRemainingKwh !== null
      ? liveTodayKwh - liveRemainingKwh
      : null;
    if (expectedSoFarKwh > 0) {
      lines.push(`Prognos hittills: ${expectedSoFarKwh} kWh`);
    }
    if (Number.isFinite(day?.forecastKwh)) {
      lines.push(`Dagsprognos: ${day.forecastKwh} kWh`);
    }
    if (Number.isFinite(day?.forecastAccuracyPercent)) lines.push(`Prognosträff hittills: ${day.forecastAccuracyPercent} %`);
    if (Number.isFinite(day?.forecastDeviationPercent)) {
      const sign = day.forecastDeviationPercent >= 0 ? "+" : "";
      lines.push(`Avvikelse: ${sign}${day.forecastDeviationPercent} %`);
    }
  } else if (Number.isFinite(day?.forecastKwh)) {
    lines.push(`Prognos: ${day.forecastKwh} kWh`);
    if (Number.isFinite(day?.forecastAccuracyPercent)) lines.push(`Prognosträff: ${day.forecastAccuracyPercent} %`);
    if (Number.isFinite(day?.forecastDeviationPercent)) {
      const sign = day.forecastDeviationPercent >= 0 ? "+" : "";
      lines.push(`Avvikelse: ${sign}${day.forecastDeviationPercent} %`);
    }
  }
  return lines;
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
    const sameHistoryInterval = Boolean(previous?.history_interval_id)
      && previous.history_interval_id === point.history_interval_id;
    const historyResolutionMs = Math.max(
      Number(previous?.source_resolution_seconds) || 0,
      Number(point?.source_resolution_seconds) || 0,
    ) * 1000;
    const continuousHistoryCurve = Boolean(previous?.history_curve)
      && Boolean(point?.history_curve)
      && !point.gap_before
      && historyResolutionMs > 0
      && currentTime > previousTime
      && currentTime - previousTime <= historyResolutionMs + 1;
    const contiguous = previous
      && Number.isFinite(previousValue)
      && Number.isFinite(previousTime)
      && Number.isFinite(currentTime)
      && previous.raw_timestamp != null
      && point.raw_timestamp != null
      && ((currentTime - previousTime === 5 * 60 * 1000 && !point.gap_before)
        || sameHistoryInterval
        || continuousHistoryCurve);
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

export function buildContinuousGapPairs(points, key) {
  const gaps = [];
  let previous = null;
  for (const point of Array.isArray(points) ? points : []) {
    const timestamp = new Date(point?.timestamp).getTime();
    const value = normalizeMeterValue(point?.[key]);
    if (!Number.isFinite(timestamp) || !Number.isFinite(value)) continue;
    if (previous && timestamp - previous.timestamp > 5 * 60 * 1000) {
      gaps.push([previous.point, point]);
    }
    previous = { point, timestamp };
  }
  return gaps;
}

export function buildForecastSegments(points, key, resolutionMs = 15 * 60 * 1000) {
  const segments = [];
  let segment = [];
  const appendSegment = () => {
    if (segment.length >= 2) segments.push(segment);
    segment = [];
  };
  const sorted = (Array.isArray(points) ? points : [])
    .map((point) => ({ point, timestamp: new Date(point?.timestamp).getTime(), value: normalizeMeterValue(point?.[key]) }))
    .filter((item) => Number.isFinite(item.timestamp) && Number.isFinite(item.value))
    .sort((left, right) => left.timestamp - right.timestamp);
  sorted.forEach((item, index) => {
    const previous = sorted[index - 1];
    if (!previous || item.timestamp - previous.timestamp !== resolutionMs) {
      appendSegment();
    }
    segment.push(item.point);
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

function tooltipValueIsPresent(value) {
  return value !== null && value !== undefined && value !== ""
    && !(typeof value === "number" && !Number.isFinite(value));
}

export function renderSharedTooltip(tooltip, { title = "", fields = [] }) {
  if (!tooltip) return;
  const validFields = fields.filter((field) => tooltipValueIsPresent(field?.value));
  tooltip.replaceChildren();
  if (title) {
    const heading = document.createElement("strong");
    heading.textContent = title;
    tooltip.append(heading);
  }
  for (const field of validFields) {
    const row = document.createElement("span");
    row.className = `tooltip-value ${field.className || ""}`.trim();
    if (field.color) row.style.color = field.color;
    row.textContent = `${field.label}: ${field.formatted ?? field.value}`;
    tooltip.append(row);
  }
}

const tooltipNumber = (value, maximumFractionDigits = 2) => Number(value).toLocaleString("sv-SE", {
  maximumFractionDigits,
});

export function buildSolarHistoryTooltipFields(day, liveForecast, now = new Date(), weather = null, sun = null) {
  const fields = [];
  const add = (label, value, formatted = value) => {
    if (tooltipValueIsPresent(value)) fields.push({ label, value, rawValue: value, formatted });
  };
  if (Number.isFinite(day?.producedKwh)) add("Producerat", day.producedKwh, `${tooltipNumber(day.producedKwh)} kWh`);
  const today = new Date(now).toLocaleDateString("sv-SE");
  if (day?.date === today && (!day?.forecastComparisonBasis || day.forecastComparisonBasis === "forecast_so_far")) {
    const liveTodayKwh = Number.isFinite(Number(liveForecast?.today_kwh)) ? Number(liveForecast.today_kwh) : null;
    const liveRemainingKwh = Number.isFinite(Number(liveForecast?.remaining_today_kwh)) ? Number(liveForecast.remaining_today_kwh) : null;
    const expectedSoFarKwh = liveTodayKwh !== null && liveRemainingKwh !== null ? liveTodayKwh - liveRemainingKwh : null;
    if (expectedSoFarKwh > 0) add("Prognos hittills", expectedSoFarKwh, `${tooltipNumber(expectedSoFarKwh)} kWh`);
    if (Number.isFinite(day?.forecastKwh)) add("Dagsprognos", day.forecastKwh, `${tooltipNumber(day.forecastKwh)} kWh`);
    if (Number.isFinite(day?.forecastAccuracyPercent)) {
      add("Prognosträff hittills", day.forecastAccuracyPercent, `${tooltipNumber(day.forecastAccuracyPercent, 1)} %`);
    }
    if (Number.isFinite(day?.forecastDeviationPercent)) {
      const sign = day.forecastDeviationPercent >= 0 ? "+" : "";
      add("Avvikelse", day.forecastDeviationPercent, `${sign}${tooltipNumber(day.forecastDeviationPercent, 1)} %`);
    }
  } else if (Number.isFinite(day?.forecastKwh)) {
    add("Prognos", day.forecastKwh, `${tooltipNumber(day.forecastKwh)} kWh`);
    if (Number.isFinite(day?.forecastAccuracyPercent)) {
      add("Prognosträff", day.forecastAccuracyPercent, `${tooltipNumber(day.forecastAccuracyPercent, 1)} %`);
    }
    if (Number.isFinite(day?.forecastDeviationPercent)) {
      const sign = day.forecastDeviationPercent >= 0 ? "+" : "";
      add("Avvikelse", day.forecastDeviationPercent, `${sign}${tooltipNumber(day.forecastDeviationPercent, 1)} %`);
    }
  }
  return fields;
}

export function mergePowerHistoryPoint(existingPoints, incomingPoint, incomingTimestampMs = Date.parse(incomingPoint?.timestamp)) {
  const existing = Array.isArray(existingPoints) ? existingPoints : [];
  const last = existing.at(-1);
  if (!last) return [incomingPoint];
  const lastTimestampMs = Date.parse(last.timestamp);
  if (Number.isFinite(lastTimestampMs) && Number.isFinite(incomingTimestampMs)) {
    if (incomingTimestampMs > lastTimestampMs) return [...existing, incomingPoint];
    if (incomingTimestampMs === lastTimestampMs) {
      const updated = [...existing];
      updated[updated.length - 1] = incomingPoint;
      return updated;
    }
  }
  const byTimestamp = new Map(existing.map((item) => [item.timestamp, item]));
  byTimestamp.set(incomingPoint.timestamp, incomingPoint);
  return [...byTimestamp.values()].sort((left, right) => new Date(left.timestamp) - new Date(right.timestamp));
}

export function performanceWarningKind(durationMs, stallTimes = [], nowMs = Date.now()) {
  if (durationMs >= 500) return "ui_stall";
  const recent = stallTimes.filter((timestamp) => nowMs - timestamp <= 60_000);
  return recent.length >= 3 ? "repeated_ui_stalls" : null;
}

export function createPerformanceSessionId(randomValue = null) {
  const value = randomValue || globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `perf-${String(value).replace(/[^a-z0-9]/gi, "").slice(0, 8)}`;
}

export function reconcileEllaSiteState(previousState, nextState, currentState = {}) {
  const siteId = (state) => state?.current_site?.site_id || state?.site_id || null;
  const previousSiteId = siteId(previousState);
  const nextSiteId = siteId(nextState);
  const trustedPlanSiteId = currentState?.pricePlan?.site_id || null;
  const effectivePreviousSiteId = previousSiteId || trustedPlanSiteId;
  const changed = effectivePreviousSiteId !== nextSiteId;
  const bound = nextState?.ella_binding_verified === true;
  if (!changed) return { changed: false, bound, ...currentState };
  return {
    changed: true,
    bound,
    loadForecast: { available: false, reason: bound ? "site_changed" : "ella_unbound", frames: [] },
    pricePlan: { available: false, reason: "site_changed", plan_blocks: [] },
    ellaSelection: null,
  };
}

export function ellaPlanContextKey(siteId, date) {
  return `${siteId || ""}|${date || ""}`;
}

export function shouldPreserveEllaPlanOnTransportError(plan, previousContextKey, requestContextKey) {
  return plan?.available === true
    && Array.isArray(plan.plan_blocks)
    && plan.plan_blocks.length > 0
    && previousContextKey === requestContextKey;
}

export function togglePricePlanSelection(currentSelection, block, revision = null) {
  const id = block?.plan_block_id;
  if (!id) return null;
  if (currentSelection?.id === id) return null;
  return {
    id,
    start: typeof block.start === "string" ? block.start : null,
    end: typeof block.end === "string" ? block.end : null,
    revision,
  };
}

export function isUserOriginPricePlanScroll(event, rail, userGestureActive = false) {
  if (!event || !rail || event.isTrusted !== true) return false;
  const path = typeof event.composedPath === "function" ? event.composedPath() : [];
  const targetRail = path.includes(rail)
    || event.target?.closest?.("[data-price-plan-rail]") === rail;
  if (!targetRail) return false;
  if (event.type === "wheel" || event.type === "touchmove") return true;
  return event.type === "scroll" && userGestureActive;
}

export function currentPricePlanBlock(blocks, nowMs = Date.now()) {
  if (!Array.isArray(blocks) || !Number.isFinite(nowMs)) return null;
  return blocks.find((block) => {
    const start = new Date(block?.start).getTime();
    const end = new Date(block?.end).getTime();
    return Number.isFinite(start) && Number.isFinite(end) && start <= nowMs && nowMs < end;
  }) || null;
}

export function centerCurrentPricePlanCard(rail, blocks, nowMs = Date.now()) {
  if (!rail || !Array.isArray(blocks)) return false;
  const activeBlock = currentPricePlanBlock(blocks, nowMs);
  if (!activeBlock?.plan_block_id) return false;
  const card = [...(rail.querySelectorAll?.(".price-plan-card") || [])]
    .find((item) => item.dataset?.planBlockId === activeBlock.plan_block_id);
  if (!card || !Number.isFinite(rail.clientWidth)) return false;
  const maxScroll = Math.max(0, rail.scrollWidth - rail.clientWidth);
  const target = card.offsetLeft - (rail.clientWidth - card.offsetWidth) / 2;
  rail.scrollLeft = Math.max(0, Math.min(maxScroll, target));
  return true;
}

function scheduleCurrentPricePlanCenter(rail, blocks) {
  let attempts = 0;
  const center = () => {
    attempts += 1;
    if (centerCurrentPricePlanCard(rail, blocks)) return;
    if (attempts >= 4) return;
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(center);
    else setTimeout(center, 0);
  };
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(() => requestAnimationFrame(center));
  } else {
    setTimeout(center, 0);
  }
}

class ElrakningPanel {
  constructor(host, version) {
    this.host = host;
    this.version = version;
    this._debugEnabled = false;
    this._debugPreferenceChanged = false;
    this._configurationCardsVisible = false;
    this._siteState = null;
    this._siteContextGeneration = 0;
    this._siteIdentityPromise = null;
    this._mainCards = {
      elhandel: false,
      elnet: false,
      elmatare: false,
      solar: false,
      consumption: false,
      battery: false,
    };
    this._diagnosticEntries = [];
    this._diagnosticsBound = false;
    this._diagnosticsDomNodes = null;
    this._diagnosticsRequestGeneration = 0;
    this._diagnosticsLifecycleGeneration = 0;
    this._performanceWatchdog = null;
    this._chartTouch = null;
    this._chartDebugCopyText = "";
    this._tooltipOrbit = { angle: null };
    this._priceHeaderLayoutObserver = null;
    this._chartPreferencesReady = false;
    this._chartPreferencesSavePromise = Promise.resolve();
    this._meterPowerHistory = createMeterPowerHistoryState();
    this._dailyEnergyDiagnosticSignature = null;
    this._livePowerMaxima = { date: null, house: 0, solar: 0, grid: 0, battery: 0 };
    this._meterTooltipPoints = [];
    this._meterCanonicalPoints = [];
    this._meterCanonicalPointMap = new Map();
    this._meterHistorySummary = null;
    this._meterHistoryRequestToken = 0;
    this._powerState = null;
    this._eventConnection = null;
    this._powerStateRequestGeneration = 0;
    this._powerStateMutationGeneration = 0;
    this._powerStateLifecycleGeneration = 0;
    this._powerHistory = { date: null, series: {}, power_forecast: { schema: "ella_power_forecast.v1", available: false, series: {} }, solar_forecast_baselines: {}, solar_shadow: { available: false, days: [] }, solar_evidence: { available: false, days: [] }, solar_weather: { available: false, source: "smhi", status: "unavailable", current: {}, hourly_forecast: [] }, solar_sun: { available: false }, solar_pvgis: { available: false, source: "jrc_pvgis" }, solar_open_meteo: { available: false, source: "open_meteo" } };
    this._benchmarkEvidence = { schema: "ella_replay_benchmark_evidence.v1", available: false, status: "unavailable", blocker: "not_loaded" };
    this._benchmarkEvidenceRequestToken = 0;
    this._loadForecast = { available: false, reason: "not_loaded", frames: [] };
    this._pricePlan = { available: false, reason: "not_loaded", plan_blocks: [] };
    this._pricePlanContextKey = null;
    this._ellaSelection = null;
    this._pricePlanUserScrollGesture = false;
    this._ellaDebugRequestToken = 0;
    this._powerHistoryRequestToken = 0;
    this._powerHistoryEnrichmentRequestToken = 0;
    this._powerHistoryContextKey = null;
    this._powerHistoryInFlight = new Map();
    this._priceChartRenderCacheKey = null;
    this._lastPowerChartRenderStats = null;
    this._pricePlanRequestToken = 0;
    this._solarForecastEventUnsubscribePromise = null;
    this._loadForecastEventUnsubscribePromise = null;
    this._solarEvidenceEventUnsubscribePromise = null;
    this._benchmarkEvidenceEventUnsubscribePromise = null;
    this._powerLivePoints = Object.fromEntries(["solar", "consumption", "charging", "discharging", "soc"].map((key) => [key, new Map()]));
    this._backendHydrationPromise = null;
    this._readyEventUnsubscribePromise = null;
    this._eonGridEventUnsubscribePromise = null;
    this._connectionReadyListener = null;
    this._meterPowerVisible = { import: true, export: true };
    this._spotBarsVisible = true;
    this._averageLineVisible = true;
    this._soloChartLayer = null;
    this._soloChartLayerSnapshot = null;
    this._previewLayersVisible = {
      solar: true,
      consumption: true,
      charging: true,
      discharging: true,
    };
    this._priceComparisonVisible = { electricity: true, grid: false };
    this._phaseHistoryMetric = "current";
    this._phaseHistoryVisible = { l1: true, l2: true, l3: true };
    this._providerConfigured = false;
    this._electricityProviderState = null;
    this._billingHistory = null;
    this._billingHistoryStatus = null;
    this._costUnavailableReason = "billing_history_missing";
    this._billingDailyByMonth = new Map();
    this._costSelectedMonth = null;
    this._dashboardCardVisibility = { house: "always", solar: "config_only", grid: "config_only", battery: "config_only", invoice: "always" };
    const pickerNow = new Date();
    this._periodPickerState = {
      mode: "hour",
      open: false,
      confirmed: new Date(pickerNow.getFullYear(), pickerNow.getMonth(), pickerNow.getDate()),
      draft: new Date(pickerNow.getFullYear(), pickerNow.getMonth(), pickerNow.getDate()),
      cursor: new Date(pickerNow.getFullYear(), pickerNow.getMonth(), 1),
    };
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
              <button type="button" class="header-icon-button config-cards-button" aria-label="Öppna inställningar" aria-haspopup="dialog" data-config-cards-toggle><ha-icon icon="mdi:cog-outline"></ha-icon></button>
              <button type="button" class="header-icon-button debug-button${this._debugEnabled ? " active" : ""}" aria-label="Visa diagnostik" aria-pressed="${this._debugEnabled}" data-debug-toggle><ha-icon icon="mdi:bug-outline"></ha-icon></button>
              <button type="button" class="header-icon-button" aria-label="Visa data" data-board-data-toggle>Visa data</button>
            </div>
          </div>
          <button type="button" class="site-attention" data-site-attention hidden></button>
        </header>

        <div class="dashboard-card-stack">
        <section class="live-power-row" data-live-power-row aria-label="Aktuell effekt">
          <article class="live-power-tile" data-live-power-tile="house">
            <div class="live-power-heading"><span class="live-power-title">Hus</span><label class="dashboard-card-toggle" data-dashboard-card-toggle="house" aria-label="Visa Hus"><input type="checkbox" checked><span class="main-card-track" aria-hidden="true"></span></label><button type="button" class="configuration-control live-power-configure" data-meter-configure="house_load" hidden>Konfigurera</button></div>
            <strong class="live-power-value" data-live-power-value>–</strong>
            <span class="live-power-status" data-live-power-status>Ej tillgängligt</span>
            <div class="live-power-bar" aria-hidden="true"><span data-live-power-fill></span></div>
            <div class="live-power-scale"><span>0</span><span data-live-power-scale>1,00 kW</span></div>
            <span class="live-power-grid-fuse-status live-power-grid-fuse-status-spacer" aria-hidden="true"></span>
            <div class="live-power-debug-footer"><span class="live-power-copy-feedback" data-live-power-copy-feedback aria-live="polite"></span><button type="button" class="live-power-action" data-live-power-source="house" hidden>Visa data</button></div>
          </article>
          <article class="live-power-tile" data-live-power-tile="solar">
            <div class="live-power-heading"><span class="live-power-title">Sol</span><label class="dashboard-card-toggle" data-dashboard-card-toggle="solar" aria-label="Visa Sol"><input type="checkbox" checked><span class="main-card-track" aria-hidden="true"></span></label><button type="button" class="configuration-control live-power-configure" data-power-configure="solar" hidden>Konfigurera</button></div>
            <strong class="live-power-value" data-live-power-value>–</strong>
            <span class="live-power-status" data-live-power-status>Ej tillgängligt</span>
            <div class="live-power-bar" aria-hidden="true"><span data-live-power-fill></span></div>
            <div class="live-power-scale"><span>0</span><span data-live-power-scale>1,00 kW</span></div>
            <span class="live-power-grid-fuse-status live-power-grid-fuse-status-spacer" aria-hidden="true"></span>
            <div class="live-power-debug-footer"><span class="live-power-copy-feedback" data-live-power-copy-feedback aria-live="polite"></span><button type="button" class="live-power-action" data-live-power-source="solar" hidden>Visa data</button></div>
          </article>
          <article class="live-power-tile" data-live-power-tile="grid">
            <div class="live-power-heading"><span class="live-power-title">Nät</span><label class="dashboard-card-toggle" data-dashboard-card-toggle="grid" aria-label="Visa Nät"><input type="checkbox" checked><span class="main-card-track" aria-hidden="true"></span></label><span class="live-power-grid-meta" data-live-power-grid-meta hidden></span><button type="button" class="configuration-control live-power-configure" data-meter-configure="meter" hidden>Konfigurera</button></div>
            <strong class="live-power-value" data-live-power-value>–</strong>
            <span class="live-power-status" data-live-power-status>Ej tillgängligt</span>
            <div class="live-power-bar" aria-hidden="true"><span data-live-power-fill></span></div>
            <div class="live-power-scale"><span>0</span><span data-live-power-scale>1,00 kW</span></div>
            <span class="live-power-grid-fuse-status live-power-grid-fuse-status-spacer" aria-hidden="true"></span>
            <div class="live-power-debug-footer"><span class="live-power-copy-feedback" data-live-power-copy-feedback aria-live="polite"></span><button type="button" class="live-power-action" data-live-power-source="grid" hidden>Visa data</button></div>
          </article>
          <article class="live-power-tile" data-live-power-tile="battery">
            <div class="live-power-heading"><span class="live-power-title">Batteri</span><label class="dashboard-card-toggle" data-dashboard-card-toggle="battery" aria-label="Visa Batteri"><input type="checkbox" checked><span class="main-card-track" aria-hidden="true"></span></label><button type="button" class="configuration-control live-power-configure" data-power-configure="battery" hidden>Konfigurera</button></div>
            <strong class="live-power-value" data-live-power-value>–</strong>
            <span class="live-power-status" data-live-power-status>Ej tillgängligt</span>
            <div class="live-power-bar" aria-hidden="true"><span data-live-power-fill></span></div>
            <div class="live-power-scale"><span>0</span><span data-live-power-scale>1,00 kW</span></div>
            <span class="live-power-grid-fuse-status live-power-grid-fuse-status-spacer" aria-hidden="true"></span>
            <div class="live-power-debug-footer"><span class="live-power-copy-feedback" data-live-power-copy-feedback aria-live="polite"></span><button type="button" class="live-power-action" data-live-power-source="battery" hidden>Visa data</button></div>
          </article>
          <article class="live-power-tile invoice-estimate-card" data-invoice-estimate-card hidden aria-labelledby="invoice-estimate-title">
            <h2 id="invoice-estimate-title" class="visually-hidden">Estimerad faktura</h2>
            <div class="live-power-heading"><span class="live-power-title">Estimerad faktura</span><span class="live-power-grid-meta invoice-estimate-month" data-invoice-estimate-month></span></div>
            <strong class="live-power-value" data-invoice-estimate-total>–</strong>
            <span class="invoice-estimate-status" data-invoice-estimate-status hidden></span>
            <span class="invoice-estimate-today" data-invoice-estimate-today hidden></span>
            <div class="live-power-debug-footer"><span class="live-power-copy-feedback" aria-live="polite"></span><button type="button" class="live-power-action" data-live-power-source="invoice" hidden>Visa data</button></div>
          </article>
        </section>

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
          <div class="price-chart-frame">
            <div class="price-chart" aria-live="polite"></div>
          </div>

        <div class="price-controls">
          <div class="price-chart-legend" data-meter-legend hidden>
            <button type="button" class="chart-legend-toggle${this._spotBarsVisible ? " active" : ""}" data-chart-layer="spot" aria-pressed="${this._spotBarsVisible}">
              <span class="chart-legend-swatch spot" aria-hidden="true"></span>Pris<span class="chart-legend-solo-badge">SOLO</span>
            </button>
            <button type="button" class="chart-legend-toggle${this._averageLineVisible ? " active" : ""}" data-chart-layer="average" aria-pressed="${this._averageLineVisible}">
              <span class="chart-legend-swatch average" aria-hidden="true"></span>Snitt<span class="chart-legend-solo-badge">SOLO</span>
            </button>
            <button type="button" class="chart-legend-toggle${this._meterPowerVisible.import ? " active" : ""}" data-chart-layer="import" aria-pressed="${this._meterPowerVisible.import}">
              <span class="chart-legend-swatch import" aria-hidden="true"></span>Köp<span class="chart-legend-solo-badge">SOLO</span>
            </button>
            <button type="button" class="chart-legend-toggle${this._meterPowerVisible.export ? " active" : ""}" data-chart-layer="export" aria-pressed="${this._meterPowerVisible.export}">
              <span class="chart-legend-swatch export" aria-hidden="true"></span>Sälj<span class="chart-legend-solo-badge">SOLO</span>
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview${this._previewLayersVisible.solar ? " active" : ""} solar" data-preview-layer="solar" aria-pressed="${this._previewLayersVisible.solar}">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Sol<span class="chart-legend-solo-badge">SOLO</span>
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview${this._previewLayersVisible.consumption ? " active" : ""} consumption" data-preview-layer="consumption" aria-pressed="${this._previewLayersVisible.consumption}">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Last<span class="chart-legend-solo-badge">SOLO</span>
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview${this._previewLayersVisible.charging ? " active" : ""} charging" data-preview-layer="charging" aria-pressed="${this._previewLayersVisible.charging}">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Laddning<span class="chart-legend-solo-badge">SOLO</span>
            </button>
            <button type="button" class="chart-legend-toggle chart-legend-preview${this._previewLayersVisible.discharging ? " active" : ""} discharging" data-preview-layer="discharging" aria-pressed="${this._previewLayersVisible.discharging}">
              <span class="chart-legend-swatch" aria-hidden="true"></span>Urladdning<span class="chart-legend-solo-badge">SOLO</span>
            </button>
          </div>
          <button type="button" class="card-source-action price-source-action" data-card-source="price" hidden>Visa data</button>
          <div class="period-picker" data-period-picker>
            <div class="period-picker-control">
              <button type="button" class="period-picker-arrow" data-period-picker-nav="previous" aria-label="Föregående period">‹</button>
              <button type="button" class="period-picker-period" data-period-picker-open aria-haspopup="dialog" aria-expanded="false"><span data-period-picker-label></span></button>
              <button type="button" class="period-picker-arrow" data-period-picker-nav="next" aria-label="Nästa period">›</button>
            </div>
            <div class="period-picker-modes" role="tablist" aria-label="Tidsupplösning">
              <button type="button" role="tab" data-period-picker-mode="hour">Timme</button>
              <button type="button" role="tab" data-period-picker-mode="day">Dag</button>
              <button type="button" role="tab" data-period-picker-mode="month">Månad</button>
              <button type="button" role="tab" data-period-picker-mode="year">År</button>
            </div>
            <div class="period-picker-popover" data-period-picker-popover hidden></div>
            <dialog class="period-picker-dialog" data-period-picker-dialog aria-label="Välj period"></dialog>
          </div>
        </div>
        </section>

        <div class="price-plan-rail" data-price-plan-rail hidden role="list" aria-label="Prisplan"></div>

        <div class="daily-energy-row">
          <section class="card daily-energy-card" data-daily-energy hidden aria-labelledby="daily-energy-title">
            <div class="card-heading">
              <h2 id="daily-energy-title" class="visually-hidden">Dagens energi</h2>
            </div>
            <div class="daily-energy-grid" data-daily-energy-grid></div>
            <button type="button" class="card-source-action" data-card-source="energy" hidden>Visa data</button>
          </section>

          <section class="card soc-card" data-soc-card hidden aria-labelledby="soc-title">
            <div class="card-heading soc-card-heading">
              <h2 id="soc-title" class="visually-hidden">Batteri SOC</h2>
            </div>
            <div class="soc-chart" data-soc-chart></div>
            <button type="button" class="card-source-action" data-card-source="soc" hidden>Visa data</button>
          </section>
        </div>

        <div class="daily-energy-row battery-history-row">
          <article class="card battery-history-card" data-power-card="battery-history" hidden aria-labelledby="battery-history-title">
            <h2 id="battery-history-title" class="visually-hidden">Batterihistorik</h2>
            <div class="battery-history-chart" data-battery-history-chart hidden></div>
            <button type="button" class="card-source-action" data-card-source="battery-history" hidden>Visa data</button>
          </article>
          <article class="card solar-history-card" data-power-card="solar-history" hidden aria-labelledby="solar-history-title">
            <h2 id="solar-history-title" class="visually-hidden">Solhistorik</h2>
            <div class="solar-history-chart" data-solar-history-chart hidden></div>
            <button type="button" class="card-source-action" data-card-source="solar-history" hidden>Visa data</button>
          </article>
        </div>

        <div class="daily-energy-row phase-history-row">
          <article class="card phase-history-card" data-phase-history-card hidden aria-labelledby="phase-history-title">
            <div class="phase-history-heading" aria-label="Faser">
              <h2 id="phase-history-title" class="visually-hidden">Faser</h2>
              <div class="phase-history-summary" data-phase-history-summary></div>
              <div class="phase-history-metric-selector" role="group" aria-label="Fasmätning">
                <button type="button" data-phase-metric="current" aria-pressed="true">Ström</button>
                <button type="button" data-phase-metric="voltage" aria-pressed="false">Spänning</button>
                <button type="button" data-phase-metric="active_power" aria-pressed="false">Effekt</button>
              </div>
            </div>
            <div class="phase-history-chart" data-phase-history-chart></div>
            <button type="button" data-phase-history-copy hidden>Visa data</button>
          </article>
          <article class="card cost-card" data-cost-card hidden aria-labelledby="cost-title">
            <div class="card-heading cost-card-heading"><h2 id="cost-title">Kostnad</h2></div>
            <div class="cost-kpis" data-cost-kpis></div>
            <div class="cost-main-grid"><div class="cost-chart" data-cost-chart aria-live="polite"></div><div class="cost-side"><div class="cost-details" data-cost-summary></div></div></div>
            <section class="cost-history-section" aria-labelledby="cost-history-title"><div class="cost-history-heading"><h3 id="cost-history-title">Månadskostnad senaste 12 månaderna</h3><span class="status" data-cost-status></span><span data-cost-history-status></span></div><div class="cost-history-chart" data-cost-history-chart role="tablist" aria-label="Månader"></div></section>
            <div class="cost-comparison" data-cost-comparison></div>
            <button type="button" class="card-source-action" data-card-source="cost" hidden>Visa data</button>
          </article>
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
            <p class="provider-invoice-cost" data-provider-invoice-cost="elhandel" hidden><span>Kostnad denna månad</span><strong></strong></p>
            <div class="retained-history" data-retained-history hidden>
              <h3>Sparad historik</h3>
              <div data-retained-history-list></div>
            </div>
            <p class="provider-processing-error" data-provider-processing-error hidden>Fel vid senaste hämtning</p>
            <button type="button" class="configuration-control" data-electricity-configure>Konfigurera</button>
            <button type="button" data-provider-source hidden>Visa data</button>
            <button type="button" data-greenely-parse-latest hidden>Tolka senaste</button>
          </article>

          <article class="card" data-provider-card="elnet" data-config-card-key="elnet">
              <div class="card-heading">
                <h2>Elnät</h2>
                <span class="status" data-eon-grid-status>Ej konfigurerad</span>
                <label class="main-card-toggle" data-main-card-toggle="elnet" aria-label="Main"><input type="checkbox"><span class="main-card-track" aria-hidden="true"></span></label>
              </div>
              <p class="provider" data-provider-name="elnet" hidden></p>
              <div class="provider-summary" data-eon-grid-summary hidden></div>
              <p class="provider-invoice-cost" data-provider-invoice-cost="elnet" hidden><span>Kostnad denna månad</span><strong></strong></p>
              <button type="button" class="configuration-control" data-eon-grid-card-configure>Konfigurera</button>
              <button type="button" data-eon-grid-source hidden>Visa data</button>
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
        </div>
        <section class="card solar-evidence-card" data-solar-evidence-card hidden aria-labelledby="solar-evidence-title">
          <div class="card-heading solar-evidence-heading"><h2 id="solar-evidence-title">Solar Evidence</h2><button type="button" class="card-source-action" data-card-source="solar-evidence" hidden>Visa data</button></div>
          <div class="solar-evidence-capture-tasks" data-solar-evidence-capture-tasks hidden></div>
          <div data-solar-evidence-summary></div>
          <div data-solar-evidence-status></div>
          <div class="solar-evidence-list" data-solar-evidence-list></div>
        </section>

        <section class="card solar-evidence-card" data-benchmark-evidence-card hidden aria-labelledby="benchmark-evidence-title">
          <div class="card-heading solar-evidence-heading"><h2 id="benchmark-evidence-title">Benchmark Evidence</h2><button type="button" class="card-source-action" data-card-source="benchmark-evidence" hidden>Visa data</button></div>
          <div data-benchmark-evidence-summary></div>
          <div data-benchmark-evidence-status></div>
          <div class="solar-evidence-list" data-benchmark-evidence-list></div>
        </section>
      </main>
      <div class="provider-source-dialog" data-provider-source-dialog hidden role="dialog" aria-modal="true" aria-labelledby="provider-source-dialog-title">
        <div class="provider-dialog-card">
          <h2 id="provider-source-dialog-title">Source data</h2>
          <p class="source-provider" data-provider-source-provider hidden></p>
          <pre data-provider-source-text></pre>
          <button type="button" data-provider-source-copy disabled>Kopiera</button>
          <button type="button" data-provider-source-close>Stäng</button>
        </div>
      </div>
      <div class="provider-source-dialog" data-board-data-dialog hidden role="dialog" aria-modal="true" aria-labelledby="board-data-dialog-title">
        <div class="provider-dialog-card">
          <h2 id="board-data-dialog-title">Visa data</h2>
          <pre data-board-data-text></pre>
          <button type="button" data-board-data-copy>Kopiera</button>
          <button type="button" data-board-data-close>Stäng</button>
        </div>
      </div>
      <div class="provider-source-dialog site-settings-dialog" data-site-settings-dialog hidden role="dialog" aria-modal="true" aria-labelledby="site-settings-title">
        <div class="provider-dialog-card">
          <h2 id="site-settings-title">Installation / bostad</h2>
          <p class="site-settings-label">Aktiv installation</p>
          <p class="site-settings-current" data-site-current-name>–</p>
          <p class="site-settings-label">Site ID</p>
          <code class="site-settings-id" data-site-current-id>–</code>
          <p class="site-settings-created" data-site-current-created></p>
          <div class="site-settings-actions">
            <button type="button" data-site-rename>Byt namn</button>
            <button type="button" data-site-create>+ Ny installation / bostad</button>
          </div>
          <label class="site-settings-label" for="site-settings-select">Byt installation</label>
          <select id="site-settings-select" data-site-select></select>
          <p class="site-settings-help">Att markera en installation ändrar inte aktiv site.</p>
          <button type="button" data-site-activate disabled>Gör till aktiv installation</button>
          <p class="site-settings-result" data-site-settings-result aria-live="polite"></p>
          <label class="site-settings-config-toggle"><input type="checkbox" data-site-config-cards-toggle> Visa konfigurationskort på tavlan</label>
          <fieldset class="site-settings-card-visibility">
            <legend>Kort på tavlan</legend>
            ${[["house", "Hus"], ["solar", "Sol"], ["grid", "Nät"], ["battery", "Batteri"], ["invoice", "Estimerad faktura"]].map(([key, label]) => `<label>${label}<select data-dashboard-card-visibility="${key}"><option value="always">Alltid</option><option value="config_only">När konfigurerat</option><option value="hidden">Dölj</option></select></label>`).join("")}
          </fieldset>
          <button type="button" data-site-settings-close>Stäng</button>
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
      <div class="meter-dialog power-dialog" data-power-dialog hidden role="dialog" aria-modal="true" aria-labelledby="power-title">
        <div class="meter-dialog-card">
          <h2 id="power-title"></h2>
          <p data-power-result></p>
          <p class="power-solar-analysis-status" data-power-solar-analysis-status hidden></p>
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
      <div class="provider-dialog" data-eon-grid-dialog hidden role="dialog" aria-modal="true" aria-labelledby="eon-grid-title">
        <div class="provider-dialog-card">
          <h2 id="eon-grid-title">Välj elnätsbolag</h2>
          <label>Elnätsbolag<select data-grid-provider aria-label="Elnätsbolag"></select></label>
          <label>Konto-ID<input type="text" data-eon-grid-app-account autocomplete="username"></label>
          <label>Lösenord<input type="password" data-eon-grid-app-password autocomplete="current-password"></label>
          <button type="button" data-eon-grid-app-save>Logga in</button>
          <p class="provider-result" data-eon-grid-result aria-live="polite"></p>
          <div class="provider-actions">
            <button type="button" data-eon-grid-cancel>Avbryt</button>
            <button type="button" data-eon-grid-remove hidden>Ta bort elnätsavtal</button>
          </div>
        </div>
      </div>
      <style>
        :host {
          --card-title-size: clamp(20px, 5.2cqw, 24px);
          --price-card-text-size: clamp(10px, 2.7cqw, 12px);
          --card-legend-size: var(--price-card-text-size);
          --el-price-cheap-color: #67C98C;
          --el-price-normal-color: #B9A05D;
          --el-price-expensive-color: #E4687D;
          --el-solar-color: #77C2A1;
          --el-consumption-color: #E87570;
          --el-import-color: #F0A06A;
          --el-export-color: #72AAF6;
          --el-charging-color: #B76A8F;
          --el-discharging-color: #DF5C8A;
          --dashboard-card-gap: 16px;
          --el-text-primary: var(--primary-text-color, #F1F1F5);
          --el-text-secondary: var(--secondary-text-color, #B7B8C0);
          --el-divider: var(--divider-color, rgba(255, 255, 255, .12));
          --el-background: var(--primary-background-color, #202126);
          --el-card-bg: var(--ha-card-glass-tint, var(--ha-card-background, var(--card-background-color, rgba(25, 25, 30, .72))));
          --el-accent: var(--primary-color, #8F7CFF);
          --chart-axis-font-size: 10px;
          --chart-axis-font-weight: 400;
          --chart-axis-line-height: 1;
          --chart-axis-color: var(--secondary-text-color, #B7B8C0);
          --chart-axis-opacity: 1;
          --solar-color: var(--el-solar-color, #77C2A1);
          --consumption-color: var(--el-consumption-color, #E87570);
          --grid-import-color: var(--el-import-color, #F0A06A);
          --grid-export-color: var(--el-export-color, #72AAF6);
          --charging-color: var(--el-charging-color, #B76A8F);
          --discharging-color: var(--el-discharging-color, #DF5C8A);
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
          margin-top: 16px;
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
          background: rgba(255, 255, 255, 0.12);
          background: color-mix(in srgb, var(--el-text-secondary) 12%, transparent);
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
          background: rgba(0, 0, 0, 0.30);
          background: color-mix(in srgb, var(--el-background) 70%, transparent);
          display: flex;
          inset: 0;
          justify-content: center;
          padding: 20px;
          position: fixed;
          z-index: 2;
        }

        .meter-dialog {
          align-items: center;
          background: rgba(0, 0, 0, 0.30);
          background: color-mix(in srgb, var(--el-background) 70%, transparent);
          display: flex;
          inset: 0;
          justify-content: center;
          padding: 20px;
          position: fixed;
          z-index: 2;
        }

        .meter-dialog[hidden] {
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

        .solar-array-metadata {
          display: grid;
          gap: 8px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .solar-array-metadata label {
          display: grid;
          font-size: 12px;
          gap: 4px;
        }

        .solar-array-metadata input {
          background: var(--ha-card-background, var(--card-background-color));
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          box-sizing: border-box;
          color: var(--primary-text-color);
          min-width: 0;
          padding: 7px 8px;
          width: 100%;
        }

        .battery-mode-wrap {
          display: grid;
          gap: 8px;
          margin-top: 16px;
        }

        .battery-mode-wrap[hidden],
        .battery-invert-row[hidden],
        .power-solar-analysis-status[hidden],
        [data-power-add-solar][hidden] {
          display: none;
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

        .meter-summary,
        .power-summary {
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

        .power-summary-divider {
          border-top: 1px solid var(--divider-color);
          grid-column: 1 / -1;
          margin: 6px 0;
        }

        .battery-history-card {
          min-width: 0;
        }

        .battery-history-chart {
          container-type: inline-size;
          min-width: 0;
          position: relative;
          width: 100%;
        }

        .battery-history-svg {
          display: block;
          height: auto;
          max-width: 100%;
          width: 100%;
        }

        .battery-history-gridline {
          stroke: var(--divider-color);
          stroke-width: 1;
          opacity: .5;
        }

        .battery-history-y-label-rail,
        .battery-history-x-label-rail {
          pointer-events: none;
          position: absolute;
        }

        .battery-history-y-label-rail {
          bottom: 15.625%;
          left: 0;
          top: 3.75%;
          width: 4.375%;
        }

        .battery-history-axis-label,
        .battery-history-day-label,
        .battery-history-utilization {
          box-sizing: border-box;
          display: block;
          font-size: var(--chart-axis-font-size);
          font-weight: var(--chart-axis-font-weight);
          line-height: var(--chart-axis-line-height);
        }

        .battery-history-axis-label {
          color: var(--chart-axis-color);
          opacity: var(--chart-axis-opacity);
          position: absolute;
          right: 0;
          text-align: center;
          transform: translateY(-50%);
          width: 100%;
        }

        .battery-history-axis-label.top { top: 0; }
        .battery-history-axis-label.middle { top: 50%; }
        .battery-history-axis-label.bottom { top: 100%; }

        .battery-history-x-label-rail {
          bottom: 0;
          height: 15.625%;
          left: 4.375%;
          right: .833333%;
        }

        .battery-history-x-label {
          position: absolute;
          text-align: center;
          top: 62%;
          transform: translate(-50%, -50%);
          width: max-content;
        }

        .battery-history-day-label {
          color: var(--secondary-text-color);
        }

        .battery-history-utilization {
          color: var(--primary-text-color);
          font-weight: 600;
        }

        .battery-history-bar {
          rx: 4;
          ry: 4;
        }

        .battery-history-bar.charging {
          fill: var(--charging-color);
          fill-opacity: .72;
        }

        .battery-history-bar.discharging {
          fill: var(--discharging-color);
          fill-opacity: .72;
        }

        .battery-history-day.hovered .battery-history-bar {
          fill-opacity: 1;
        }

        .solar-history-card {
          min-width: 0;
        }

        .solar-history-chart {
          container-type: inline-size;
          min-width: 0;
          position: relative;
          width: 100%;
        }

        .solar-history-svg {
          display: block;
          height: auto;
          max-width: 100%;
          width: 100%;
        }

        .solar-history-gridline {
          stroke: var(--divider-color);
          stroke-width: 1;
          opacity: .5;
        }

        .solar-history-y-label-rail,
        .solar-history-x-label-rail {
          pointer-events: none;
          position: absolute;
        }

        .solar-history-y-label-rail {
          bottom: 15.625%;
          left: 0;
          top: 3.75%;
          width: 4.375%;
        }

        .solar-history-axis-label,
        .solar-history-day-label,
        .solar-history-utilization {
          box-sizing: border-box;
          display: block;
          font-size: var(--chart-axis-font-size);
          font-weight: var(--chart-axis-font-weight);
          line-height: var(--chart-axis-line-height);
        }

        .solar-history-axis-label {
          color: var(--chart-axis-color);
          opacity: var(--chart-axis-opacity);
          position: absolute;
          right: 0;
          text-align: center;
          transform: translateY(-50%);
          width: 100%;
        }

        .solar-history-axis-label.top { top: 0; }
        .solar-history-axis-label.middle { top: 50%; }
        .solar-history-axis-label.bottom { top: 100%; }

        .solar-history-x-label-rail {
          bottom: 0;
          height: 15.625%;
          left: 4.375%;
          right: .833333%;
        }

        .solar-history-x-label {
          position: absolute;
          text-align: center;
          top: 62%;
          transform: translate(-50%, -50%);
          width: max-content;
        }

        .solar-history-day-label {
          color: var(--secondary-text-color);
        }

        .solar-history-utilization {
          color: var(--primary-text-color);
          font-weight: 600;
        }

        .solar-history-evidence-status {
          color: var(--secondary-text-color);
          display: block;
          font-size: var(--chart-axis-font-size);
          line-height: var(--chart-axis-line-height);
          min-height: var(--chart-axis-line-height);
        }

        .solar-history-bar {
          fill: var(--solar-color);
          fill-opacity: .78;
          rx: 4;
          ry: 4;
        }

        .solar-history-reference-bar {
          fill-opacity: .22;
          rx: 4;
          ry: 4;
        }

        .solar-history-day.hovered .solar-history-bar {
          fill-opacity: 1;
        }

        .solar-history-day.hovered .solar-history-reference-bar {
          fill-opacity: .32;
        }

        .card.solar-evidence-card {
          background: var(--ha-card-background, var(--card-background-color));
          box-shadow: none;
          backdrop-filter: none;
          -webkit-backdrop-filter: none;
        }
        .solar-evidence-summary, .solar-evidence-status { line-height: 1.45; }
        .solar-evidence-status { font-weight: 600; margin-top: 4px; }
        .solar-evidence-capture-tasks { background: var(--secondary-background-color); border-radius: 8px; margin: 6px 0; padding: 6px 8px; }
        .solar-evidence-capture-task { display: grid; gap: 2px; grid-template-columns: minmax(0, 1fr) auto; }
        .solar-evidence-capture-task + .solar-evidence-capture-task { border-top: 1px solid var(--divider-color); margin-top: 5px; padding-top: 5px; }
        .solar-evidence-capture-task small { color: var(--secondary-text-color); grid-column: 1 / -1; line-height: 1.3; }
        .solar-evidence-capture-task strong { color: var(--primary-text-color); }
        .solar-evidence-progress { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 4px; }
        .solar-evidence-progress > div { display: grid; gap: 2px; }
        .solar-evidence-progress strong { font-size: 0.9rem; }
        .solar-evidence-progress span { color: var(--secondary-text-color); font-size: 0.9rem; }
        .solar-evidence-progress meter { height: 6px; width: 100%; }
        .solar-evidence-protocol { color: var(--secondary-text-color); display: block; margin-top: 8px; }
        .solar-evidence-heading { align-items: center; flex-direction: row; justify-content: space-between; }
        .solar-evidence-heading .card-source-action { margin-top: 0; width: max-content; }
        .solar-evidence-list { display: grid; gap: 5px; margin-top: 8px; max-height: 58vh; min-height: 0; overflow-x: hidden; overflow-y: auto; }
        .solar-evidence-day { background: var(--secondary-background-color); border-radius: 8px; padding: 6px 8px; }
        .solar-evidence-day-heading { align-items: baseline; display: flex; gap: 8px; justify-content: space-between; }
        .solar-evidence-day-heading strong { color: var(--primary-text-color); }
        .solar-evidence-day-heading span { color: var(--secondary-text-color); font-size: 0.84rem; font-weight: 600; }
        .solar-evidence-metrics { display: grid; gap: 3px 12px; grid-template-columns: repeat(5, minmax(0, 1fr)); margin-top: 4px; }
        .solar-evidence-metrics span { color: var(--secondary-text-color); font-size: 0.84rem; min-width: 0; }
        .solar-evidence-metrics b { color: var(--primary-text-color); display: block; font-size: 0.78rem; font-weight: 600; }
        .solar-evidence-day small { color: var(--secondary-text-color); display: block; line-height: 1.35; margin-top: 4px; }

        @media (max-width: 700px) {
          .solar-evidence-progress { grid-template-columns: 1fr; }
          .solar-evidence-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }

        .daily-energy-row {
          align-items: stretch;
          display: grid;
          gap: 0;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .daily-energy-row:has(> :not([hidden]) ~ :not([hidden])) {
          gap: var(--dashboard-card-gap);
        }

        .daily-energy-row:not(:has(> :not([hidden]))) {
          display: none;
        }

        .dashboard-card-stack {
          display: grid;
          gap: 0;
          margin-bottom: 16px;
        }

        .dashboard-card-stack:has(> :not([hidden]) ~ :not([hidden])) {
          gap: var(--dashboard-card-gap);
        }

        .dashboard-card-stack > * {
          margin-block: 0;
        }

        @container (max-width: 760px) {
        .daily-energy-row {
          align-items: start;
            grid-template-columns: 1fr;
          }
        }

        .daily-energy-card {
          --daily-energy-local-color: var(--el-solar-color, #77C2A1);
          --daily-energy-export-color: var(--el-export-color, #72AAF6);
          --daily-energy-import-color: var(--el-import-color, #F0A06A);
          min-height: 0;
          min-width: 0;
        }

        .daily-energy-grid {
          align-items: start;
          display: grid;
          gap: 24px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          margin-top: 0;
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
          display: block;
          flex: 0 0 auto;
          flex-basis: auto;
          height: 100%;
          min-width: 0;
          opacity: .6;
          transition: width 120ms ease;
        }

        .daily-energy-segment.local {
          background-color: var(--daily-energy-local-color, #77C2A1);
        }

        .daily-energy-segment.supply {
          background-color: var(--daily-energy-local-color, #77C2A1);
        }

        .daily-energy-segment.export {
          background-color: var(--daily-energy-export-color, #72AAF6);
        }

        .daily-energy-segment.import {
          background-color: var(--daily-energy-import-color, #F0A06A);
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
          --soc-color: var(--el-solar-color, #77C2A1);
          display: block;
          min-block-size: 0;
          min-height: 0;
          min-width: 0;
        }

        .price-plan-rail {
          border-top: 0;
          display: grid;
          gap: 0;
          overflow-x: auto;
          padding: 3px;
          padding-inline-start: 2px;
          scrollbar-width: none;
        }

        .price-plan-rail:has(> :not([hidden]) ~ :not([hidden])) {
          gap: var(--dashboard-card-gap);
        }

        .price-plan-rail:not([hidden]) {
          display: flex;
        }

        .price-plan-card {
          background: var(--ha-card-glass-tint, var(--ha-card-background, var(--card-background-color)));
          border: var(--ha-card-border-width, 1px) var(--ha-card-border-style, solid) var(--ha-card-border-color, var(--divider-color));
          border-color: transparent;
          border-radius: var(--ha-card-border-radius, 12px);
          flex: 0 0 min(260px, 78vw);
          padding: 10px;
          text-align: left;
        }

        .price-plan-card.current {
          border-color: color-mix(in srgb, var(--primary-color) 48%, var(--ha-card-border-color, var(--divider-color)));
        }

        .price-plan-card.selected {
          border-color: var(--primary-color);
          box-shadow: 0 0 0 1px var(--primary-color);
        }

        .price-plan-card strong,
        .price-plan-card b,
        .price-plan-card small {
          display: block;
        }

        .price-plan-card b {
          font-size: 1.05em;
          margin-top: 8px;
        }

        .price-plan-card small {
          color: var(--secondary-text-color);
          margin-top: 4px;
        }

        .price-plan-card:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }

        .chart-power-forecast-load {
          stroke-dasharray: 8 5;
          opacity: .68;
        }

        .chart-power-forecast {
          stroke-dasharray: 8 5;
          opacity: .68;
        }

        .ella-selection-band {
          fill: var(--primary-color);
          opacity: .10;
          pointer-events: none;
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

        .soc-chart {
          margin: 0;
          min-block-size: 0;
          min-height: 0;
          position: relative;
          width: 100%;
        }

        .soc-label-rail {
          bottom: 8px;
          left: 0;
          pointer-events: none;
          position: absolute;
          right: auto;
          top: 8px;
          width: 4.583333%;
        }

        .soc-chart-svg {
          display: block;
          height: 100%;
          max-width: 100%;
          overflow: visible;
          width: 100%;
        }

        .soc-gridline {
          stroke: var(--divider-color);
          stroke-width: 1;
          opacity: .5;
        }

        .soc-label {
          color: var(--chart-axis-color);
          font-size: var(--chart-axis-font-size);
          font-weight: var(--chart-axis-font-weight);
          line-height: var(--chart-axis-line-height);
          opacity: var(--chart-axis-opacity);
          position: absolute;
          left: 0;
          right: 0;
          text-align: center;
          transform: translateY(-50%);
        }

        .soc-label.top { top: 0; }
        .soc-label.middle { top: 50%; }
        .soc-label.bottom { top: 100%; }

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

        .soc-estimated-area {
          fill: #5f9f82;
          fill-opacity: .22;
          stroke: none;
        }

        .soc-estimated-line {
          fill: none;
          stroke: #5f9f82;
          stroke-linecap: round;
          stroke-linejoin: round;
          stroke-width: 2;
          vector-effect: non-scaling-stroke;
        }

        .soc-singleton {
          fill: var(--soc-color);
          stroke: var(--ha-card-background, var(--card-background-color));
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

        .battery-history-chart .soc-tooltip > span,
        .solar-history-chart .soc-tooltip > span {
          display: block;
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

        .provider-source-dialog .provider-dialog-card {
          max-height: calc(100vh - 40px);
          overflow: auto;
        }

        .site-settings-dialog .provider-dialog-card {
          max-width: 520px;
        }

        .site-settings-label {
          color: var(--secondary-text-color);
          font-size: 13px;
          margin-top: 16px;
        }

        .site-settings-current {
          font-size: 18px;
          margin-top: 4px;
        }

        .site-settings-id {
          color: var(--secondary-text-color);
          display: block;
          margin-top: 4px;
          overflow-wrap: anywhere;
        }

        .site-settings-created,
        .site-settings-help,
        .site-settings-result {
          color: var(--secondary-text-color);
          font-size: 13px;
          margin-top: 8px;
        }

        .site-settings-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .site-settings-actions button,
        .site-settings-dialog [data-site-activate],
        .site-settings-dialog [data-site-settings-close] {
          margin-top: 16px;
        }

        .site-settings-dialog select {
          background: var(--primary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          box-sizing: border-box;
          color: var(--primary-text-color);
          font: inherit;
          margin-top: 6px;
          padding: 9px;
          width: 100%;
        }

        .site-settings-config-toggle {
          align-items: center;
          display: flex !important;
          gap: 8px;
        }

        .site-settings-config-toggle input {
          display: inline-block;
          margin: 0;
          width: auto;
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

        .eon-auth-methods {
          display: grid;
          gap: 16px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .eon-auth-method {
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          padding: 14px;
        }

        .eon-auth-method h3 {
          margin: 0;
        }

        .eon-auth-method p {
          color: var(--secondary-text-color);
          margin: 8px 0 14px;
        }

        @media (max-width: 700px) {
          .eon-auth-methods {
            grid-template-columns: 1fr;
          }
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
          margin-top: 6px;
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
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          min-width: 0;
          color: var(--secondary-text-color);
          max-height: 60vh;
          overflow: auto;
          user-select: text;
          white-space: pre-wrap;
        }

        .provider-summary {
          display: grid;
          gap: 6px 18px;
          grid-template-columns: minmax(130px, auto) 1fr;
          margin-top: 14px;
        }

        .phase-history-row {
          grid-template-columns: 1fr;
        }

        .cost-card {
          min-width: 0;
        }

        .cost-card .card-heading {
          align-items: flex-start;
          flex-direction: row;
          gap: 12px;
          justify-content: space-between;
        }

        .cost-card .card-heading > div {
          min-width: 0;
        }

        .cost-card .card-heading .status {
          margin-top: 2px;
          text-align: right;
        }

        .cost-card-heading { align-items: center; }

        .cost-kpis {
          display: grid;
          gap: 8px;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          margin-top: 12px;
        }

        .cost-history-list {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-top: 10px;
        }

        .cost-history-list:empty { display: none; }

        .cost-history-section { border-top: 1px solid var(--divider-color); margin-top: 16px; padding-top: 14px; }
        .cost-history-heading { align-items: baseline; display: flex; gap: 8px; justify-content: space-between; }
        .cost-history-heading h3, .cost-side h3 { font-size: 0.95rem; font-weight: 600; margin: 0; }
        .cost-history-heading span { color: var(--secondary-text-color); font-size: var(--card-legend-size); }
        .cost-history-chart { align-items: end; display: flex; gap: 6px; height: 92px; overflow-x: auto; }
        .cost-history-bar-item { align-items: center; background: transparent; border: 1px solid transparent; border-radius: 6px; color: inherit; cursor: pointer; display: flex; flex: 1 0 34px; flex-direction: column; font: inherit; gap: 3px; height: 100%; justify-content: end; min-width: 34px; padding: 3px 3px 2px; }
        .cost-history-bar-item:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
        .cost-history-bar-item.selected { border-color: color-mix(in srgb, var(--primary-color) 70%, transparent); }
        .cost-history-bar-item.estimated .cost-history-bar { border: 1px dashed var(--el-solar-color, #77C2A1); box-sizing: border-box; opacity: .82; }
        .cost-history-bar { background: var(--el-solar-color, #77C2A1); border-radius: 4px 4px 0 0; min-height: 3px; opacity: .75; width: 100%; }
        .cost-history-bar-item.selected .cost-history-bar { opacity: 1; }
        .cost-history-bar-item.partial .cost-history-bar { border: 1px dashed var(--el-solar-color, #77C2A1); box-sizing: border-box; opacity: .82; }
        .cost-history-bar-item.unavailable .cost-history-bar { background: var(--divider-color); height: 3px !important; opacity: 1; }
        .cost-history-bar-label { color: var(--secondary-text-color); font-size: 10px; white-space: nowrap; }
        .cost-history-bar-value { color: var(--primary-text-color); font-size: 10px; font-weight: 500; white-space: nowrap; }

        .cost-kpi,
        .cost-detail {
          min-width: 0;
        }

        .cost-kpi {
          background: var(--ha-card-background, var(--card-background-color));
          border: 1px solid var(--divider-color);
          border-radius: var(--ha-card-border-radius, 8px);
          display: flex;
          flex-direction: column;
          padding: 7px 9px;
        }

        .cost-kpi span,
        .cost-comparison-label,
        .cost-detail span {
          color: var(--secondary-text-color);
          display: block;
          font-size: var(--card-legend-size);
        }

        .cost-kpi strong {
          display: block;
          font-size: 1.2rem;
          font-weight: 600;
          margin-top: 2px;
        }

        .cost-kpi-value-row {
          align-items: baseline;
          display: flex;
          gap: 8px;
          min-width: 0;
        }

        .cost-kpi-comparison {
          align-items: center;
          color: var(--secondary-text-color);
          display: inline-flex;
          font-size: 1.2rem;
          font-weight: 600;
          margin-top: 0;
          max-width: max-content;
          padding: 0;
          white-space: nowrap;
        }

        .cost-kpi-comparison.up { color: var(--error-color, var(--secondary-text-color)); font-size: 16px; }
        .cost-kpi-comparison.down { color: var(--success-color, var(--secondary-text-color)); }
        .cost-kpi-comparison.unavailable { color: var(--secondary-text-color); font-size: 16px; }

        .cost-chart {
          min-height: 144px;
          margin-top: 12px;
          position: relative;
        }

        .cost-main-grid { align-items: start; display: grid; gap: 18px; grid-template-columns: minmax(0, 2fr) minmax(180px, 1fr); }
        .cost-side { border-left: 1px solid var(--divider-color); min-width: 0; padding-left: 16px; }
        .cost-chart-unavailable { align-items: center; border: 1px dashed var(--divider-color); color: var(--secondary-text-color); display: flex; min-height: 144px; justify-content: center; padding: 16px; text-align: center; }

        .cost-chart-svg {
          display: block;
          height: 144px;
          overflow: visible;
          width: 100%;
        }

        .cost-chart-plot {
          position: relative;
        }

        .chart-axis-overlay {
          inset: 0;
          pointer-events: none;
          position: absolute;
          z-index: 1;
        }

        .chart-axis-overlay-label {
          color: var(--chart-axis-color);
          font-size: var(--chart-axis-font-size);
          font-weight: var(--chart-axis-font-weight);
          line-height: var(--chart-axis-line-height);
          opacity: var(--chart-axis-opacity);
          position: absolute;
          white-space: nowrap;
        }

        .chart-axis-overlay-y-left {
          box-sizing: border-box;
          left: 0;
          padding-right: 8px;
          text-align: right;
          transform: translateY(-50%);
          width: 48px;
        }

        .chart-axis-overlay-y-right {
          box-sizing: border-box;
          padding-left: 8px;
          right: 0;
          text-align: right;
          transform: translateY(-50%);
          width: 72px;
        }

        .chart-axis-overlay-x {
          bottom: 0;
          transform: translateX(-50%);
        }

        .chart-axis-overlay-x.edge-start {
          text-align: left;
          transform: none;
        }

        .chart-axis-overlay-x.edge-end {
          text-align: right;
          transform: translateX(-100%);
        }

        .cost-chart-gridline { stroke: var(--divider-color); stroke-width: 1; opacity: .45; }
        .cost-chart-actual { fill: none; stroke: var(--primary-color); stroke-width: 2.5; }
        .cost-chart-estimated { fill: none; stroke: var(--primary-color); stroke-dasharray: 3 4; opacity: .58; stroke-width: 2; }
        .cost-chart-forecast { fill: none; stroke: var(--secondary-text-color); stroke-dasharray: 5 4; stroke-width: 2; }
        .cost-chart-previous { fill: none; stroke: var(--neutral-color, #8590A6); opacity: .55; stroke-width: 1.5; }
        .cost-chart-marker { fill: var(--primary-color); }
        .cost-chart-legend { color: var(--secondary-text-color); display: flex; flex-wrap: wrap; font-size: var(--card-legend-size); gap: 4px 12px; margin-bottom: 2px; }
        .cost-chart-legend span { align-items: center; display: inline-flex; gap: 4px; }
        .cost-chart-legend i { background: var(--el-solar-color, #77C2A1); display: inline-block; height: 2px; width: 14px; }
        .cost-chart-legend-estimated { opacity: .58; }
        .cost-chart-legend-forecast { background: var(--secondary-text-color) !important; }
        .cost-chart-legend-previous { background: var(--neutral-color, #8590A6) !important; opacity: .55; }
        .cost-chart-bar-actual { fill: var(--el-solar-color, #77C2A1); opacity: .82; }
        .cost-chart-bar-forecast { fill: var(--secondary-text-color); opacity: .72; }
        .cost-chart-bar-mixed { fill: var(--el-solar-color, #77C2A1); opacity: .58; stroke: var(--secondary-text-color); stroke-dasharray: 3 2; stroke-width: 1.5; }
        .cost-chart-bar-unavailable { fill: var(--divider-color); opacity: .8; }

        .cost-comparison {
          display: grid;
          gap: 8px;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          margin-top: 14px;
        }

        .cost-comparison-item {
          background: var(--ha-card-background, var(--card-background-color));
          border: 1px solid var(--divider-color);
          border-radius: var(--ha-card-border-radius, 8px);
          min-width: 0;
          padding: 9px 10px;
        }

        .cost-comparison-value { color: var(--primary-text-color); font-weight: 600; margin-top: 4px; }
        .cost-comparison-value.up { color: var(--error-color, var(--primary-text-color)); }
        .cost-comparison-value.down { color: var(--success-color, var(--primary-text-color)); }
        .cost-comparison-value.unavailable { color: var(--secondary-text-color); font-weight: 500; }

        .cost-details {
          display: grid;
          gap: 6px 14px;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          margin-top: 12px;
        }

        .cost-detail strong { font-weight: 500; }

        .cost-summary {
          display: grid;
          gap: 8px 14px;
          grid-template-columns: minmax(0, 1fr) auto;
          margin-top: 16px;
        }

        .cost-summary span {
          color: var(--secondary-text-color);
        }

        .cost-summary strong {
          font-weight: 500;
          text-align: right;
        }

        @container (max-width: 600px) {
          .cost-kpis { gap: 8px; grid-template-columns: 1fr; }
          .cost-kpi strong { font-size: 1rem; }
          .cost-details { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .cost-comparison { grid-template-columns: 1fr; }
          .cost-main-grid { grid-template-columns: 1fr; }
          .cost-side { border-left: 0; border-top: 1px solid var(--divider-color); padding-left: 0; padding-top: 14px; }
        }

        .card-source-action {
          margin-top: 16px;
        }

        .soc-card .card-source-action {
          justify-self: start;
          width: max-content;
        }

        .phase-history-card {
          min-width: 0;
        }

        .phase-history-heading {
          align-items: center;
          display: flex;
          column-gap: 10px;
          justify-content: flex-start;
          row-gap: 6px;
          flex-wrap: wrap;
        }

        @media (min-width: 601px) {
          .card.phase-history-card {
            padding-top: 14px;
          }
        }

        .phase-history-heading h2 {
          font-size: inherit;
          margin: 0;
        }

        .phase-history-metric-selector {
          display: flex;
          flex: 0 0 auto;
          flex-wrap: nowrap;
          gap: 6px;
          margin-left: auto;
          min-width: 0;
          transform: translateY(-10px);
        }

        .phase-history-metric-selector button {
          background: transparent;
          border: 1px solid var(--divider-color);
          border-radius: 999px;
          color: var(--secondary-text-color);
          cursor: pointer;
          font: inherit;
          padding: 4px 9px;
        }

        .phase-history-metric-selector button.active,
        .phase-history-filter-selector button.active {
          background: var(--primary-background-color);
          color: var(--primary-text-color);
        }

        .phase-history-summary {
          align-items: center;
          display: flex;
          flex: 0 1 auto;
          gap: 8px;
          flex-wrap: wrap;
          min-width: 0;
          margin: 0;
        }

        .phase-history-summary div {
          align-items: center;
          color: var(--secondary-text-color);
          cursor: pointer;
          display: inline-flex;
          font-size: 14px;
          gap: 4px;
          line-height: 18px;
          opacity: 0.48;
          padding: 2px 4px;
          transition: opacity 120ms ease;
          white-space: nowrap;
        }

        .phase-history-summary div.active {
          opacity: 1;
        }

        .phase-history-summary div:focus-visible,
        .phase-history-summary div:hover {
          opacity: 0.78;
        }

        .phase-history-phase-label {
          align-items: center;
          display: inline-flex;
          gap: 4px;
        }

        .phase-history-phase-indicator {
          border-radius: 50%;
          display: inline-block;
          height: 6px;
          margin-right: 0;
          width: 6px;
        }

        .phase-history-summary strong {
          color: var(--primary-text-color);
          font-size: 14px;
          font-weight: 500;
          line-height: 18px;
        }

        .phase-history-chart {
          margin-top: 2px;
          min-height: 0;
          overflow-anchor: none;
          position: relative;
        }

        .phase-history-svg {
          display: block;
          height: auto;
          width: 100%;
        }

        .phase-history-axis-overlay {
          inset: 0;
          pointer-events: none;
          position: absolute;
        }

        .phase-history-axis-overlay .phase-history-axis-label,
        .phase-history-axis-overlay .phase-history-time-label {
          color: var(--chart-axis-color);
          font-size: var(--chart-axis-font-size);
          font-weight: var(--chart-axis-font-weight);
          line-height: var(--chart-axis-line-height);
          opacity: var(--chart-axis-opacity);
          position: absolute;
          white-space: nowrap;
        }

        .phase-history-axis-overlay .phase-history-axis-label {
          left: 4px;
          transform: translateY(-50%);
        }

        .phase-history-axis-overlay .phase-history-time-label {
          bottom: 5px;
          transform: translateX(-50%);
        }

        .phase-history-axis-overlay .phase-history-time-label:first-child {
          transform: none;
        }

        .phase-history-axis-overlay .phase-history-time-label:last-child {
          transform: translateX(-100%);
        }

        .phase-history-gridline {
          stroke: var(--divider-color);
          stroke-width: 1;
        }

        .phase-history-threshold,
        .phase-history-zero-line {
          stroke: var(--secondary-text-color);
          stroke-dasharray: 4 4;
          stroke-width: 1;
        }

        .phase-history-reference-label,
        .phase-history-time-label {
          fill: var(--chart-axis-color);
          font-size: var(--chart-axis-font-size);
          font-weight: var(--chart-axis-font-weight);
          opacity: var(--chart-axis-opacity);
        }

        .phase-history-reference-label {
          font-weight: var(--chart-axis-font-weight);
        }

        .phase-history-axis-label {
          fill: var(--chart-axis-color);
          font-size: var(--chart-axis-font-size);
          font-weight: var(--chart-axis-font-weight);
          opacity: var(--chart-axis-opacity);
        }

        .phase-history-line {
          fill: none;
          stroke-width: 2;
        }

        .phase-history-empty {
          color: var(--secondary-text-color);
          padding: 32px 0;
          text-align: center;
        }

        .phase-history-copy-feedback {
          color: var(--secondary-text-color);
          font-size: 11px;
          margin-left: 8px;
        }

        @media (max-width: 600px) {
          .phase-history-metric-selector {
            gap: 4px;
            transform: none;
          }

          .phase-history-metric-selector button {
            padding: 3px 7px;
          }

          .phase-history-chart {
            margin-top: 10px;
            min-height: 0;
            padding-bottom: 24px;
          }

          .phase-history-axis-overlay {
            bottom: 24px;
          }

          .phase-history-axis-overlay .phase-history-time-label {
            bottom: -20px;
          }
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

        .live-power-tile.invoice-estimate-card {
          grid-template-rows: auto auto auto minmax(0, auto);
          min-height: 0;
        }

        .invoice-estimate-card .live-power-heading {
          grid-row: 1;
        }

        .invoice-estimate-month {
          grid-row: auto;
          text-align: right;
        }

        .invoice-estimate-card .live-power-value {
          grid-row: 2;
        }

        .invoice-estimate-today {
          color: var(--secondary-text-color);
          font-size: 12px;
          grid-row: 3;
          line-height: 1.2;
        }

        .provider-invoice-cost span {
          color: var(--secondary-text-color);
          font-size: 12px;
        }

        .provider-invoice-cost {
          display: grid;
          gap: 2px;
          margin: 12px 0 0;
        }

        .provider-invoice-cost strong {
          font-size: 17px;
          font-weight: 500;
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
          margin: 0;
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
          margin: 0;
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


        .live-power-row {
          align-items: stretch;
          display: grid;
          gap: 0;
          grid-template-columns: repeat(5, minmax(0, 1fr));
        }

        .live-power-row:has(> :not([hidden]) ~ :not([hidden])) {
          gap: var(--dashboard-card-gap);
        }

        .live-power-tile {
          background: var(--ha-card-glass-tint, var(--ha-card-background, var(--card-background-color)));
          border: var(--ha-card-border-width, 1px) var(--ha-card-border-style, solid) var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-glass-inset-shadow, var(--ha-card-box-shadow, none));
          box-sizing: border-box;
          container-type: inline-size;
          display: grid;
          grid-template-rows: auto auto auto 5px auto minmax(0, auto);
          row-gap: 1px;
          min-width: 0;
          padding: 12px 14px;
          position: relative;
        }

        .live-power-heading {
          align-items: baseline;
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          justify-content: space-between;
          min-width: 0;
        }

        .live-power-configure {
          font-size: 11px;
          margin: 0 0 0 auto;
          padding: 3px 6px;
        }

        .live-power-title,
        .live-power-status,
        .live-power-value {
          min-width: 0;
          overflow-wrap: normal;
          word-break: normal;
        }

        .live-power-title {
          color: var(--secondary-text-color);
          font-size: 13px;
          white-space: nowrap;
        }

        .live-power-grid-meta {
          color: var(--secondary-text-color);
          font-size: 11px;
          margin-left: auto;
          white-space: nowrap;
        }

        .live-power-value {
          font-size: clamp(18px, 3.2cqw, 26px);
          font-weight: 500;
          line-height: 1.15;
          margin-top: 0;
        }

        .live-power-status {
          color: var(--secondary-text-color);
          font-size: 12px;
          margin-top: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .live-power-grid-fuse-status {
          color: var(--secondary-text-color);
          font-size: 10px;
          margin-top: 0;
        }

        .live-power-grid-fuse-status-spacer {
          display: none;
        }

        .live-power-bar {
          background: rgba(255, 255, 255, 0.14);
          background: color-mix(in srgb, var(--el-text-secondary) 14%, transparent);
          border-radius: 999px;
          height: 5px;
          margin-top: 0;
          overflow: hidden;
        }

        .live-power-bar span {
          background: var(--primary-color);
          border-radius: inherit;
          display: block;
          height: 100%;
          transform-origin: left center;
          transition: width 120ms ease;
        }

        .live-power-scale {
          color: var(--secondary-text-color);
          display: flex;
          font-size: 10px;
          justify-content: space-between;
          margin-top: 0;
        }

        .live-power-copy-feedback {
          color: var(--secondary-text-color);
          font-size: 10px;
          min-height: 1.2em;
          text-align: right;
        }

        .live-power-debug-footer {
          align-items: center;
          display: none;
          gap: 8px;
          justify-content: space-between;
          min-width: 0;
        }

        .live-power-debug-footer.visible {
          display: flex;
        }

        .live-power-action {
          font-size: 11px;
          margin: 0;
          padding: 4px 7px;
          width: max-content;
        }

        @media (max-width: 760px) {
          .live-power-row {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }

          .invoice-estimate-card {
            grid-column: 1 / -1;
          }
        }

        @media (min-width: 761px) {
          .soc-card {
            contain: size;
            display: grid;
            grid-template-rows: minmax(0, 1fr) auto;
            overflow: hidden;
          }

          .soc-card .soc-chart {
            box-sizing: border-box;
            height: auto;
            padding-block: 4px;
          }
        }

        @media (max-width: 760px) {
          .soc-card {
            contain: none;
            display: block;
            overflow: hidden;
          }

          .soc-card .soc-chart {
            box-sizing: border-box;
            height: auto;
            padding-block: 0;
          }
        }

        @media (max-width: 420px) {
          .live-power-row {
            gap: 8px;
          }

          .live-power-tile {
            padding: 10px;
          }

          .live-power-heading {
            gap: 5px;
          }
        }

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
          align-items: stretch;
          display: grid;
          gap: 0;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        }

        .grid:has(> :not([hidden]) ~ :not([hidden])) {
          gap: var(--dashboard-card-gap);
        }

        .price-section {
          --solar-color: var(--el-solar-color, #77C2A1);
          --consumption-color: var(--el-consumption-color, #E87570);
          --grid-import-color: var(--el-import-color, #F0A06A);
          --grid-export-color: var(--el-export-color, #72AAF6);
          --charging-color: var(--el-charging-color, #B76A8F);
          --discharging-color: var(--el-discharging-color, #DF5C8A);
          container-name: price-card;
          container-type: inline-size;
          background: var(--ha-card-glass-tint, var(--ha-card-background, var(--card-background-color)));
          border: var(--ha-card-border-width, 1px) var(--ha-card-border-style, solid) var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-glass-inset-shadow, var(--ha-card-box-shadow, none));
          box-sizing: border-box;
          isolation: isolate;
          overflow: visible;
          padding: 20px 20px 0;
          position: relative;
          backdrop-filter: var(--ha-card-backdrop-filter, none);
          -webkit-backdrop-filter: var(--ha-card-backdrop-filter, none);
        }

        .price-controls {
          display: flex;
          flex-wrap: wrap;
          font-size: var(--price-card-text-size);
          line-height: 1.35;
          row-gap: 0;
          width: 100%;
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
          color: var(--el-price-cheap-color);
        }

        .price-value strong.cheap {
          color: var(--el-price-cheap-color);
        }

        .price-value.current strong.normal {
          color: var(--el-price-normal-color);
        }

        .price-value.current strong.expensive {
          color: var(--el-price-expensive-color);
        }

        .price-value strong.expensive {
          color: var(--el-price-expensive-color);
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
          fill: #67C98C;
          fill-opacity: .32;
        }

        .chart-bar.normal {
          fill: #B9A05D;
          fill-opacity: .32;
        }

        .chart-bar.expensive {
          fill: #E4687D;
          fill-opacity: .32;
        }

        @media (max-width: 600px) {
          .price-section {
          padding: 16px 12px 0;
          }
        }

        .price-chart {
          container-type: inline-size;
          container-name: price-chart;
          min-height: 0;
          overflow-x: hidden;
          position: relative;
          touch-action: pan-y;
          -webkit-overflow-scrolling: touch;
          overscroll-behavior-x: contain;
        }

        /* Keep the desktop price card compact while preserving its full-width plot. */
        @media (min-width: 601px) {
          .price-section .price-chart,
          .price-section .price-chart .chart-svg,
          .price-section .price-chart .chart-axis-overlay {
            height: 295px;
          }

          .price-section .price-chart .chart-svg {
            max-height: 295px;
          }

        }

        /* Price axes reserve only a compact label-sized gutter before the plot. */
        .price-chart .chart-axis-overlay-y-left {
          left: 0;
          padding-right: 8px;
          text-align: left;
          width: var(--price-axis-left-gutter, 1px);
        }

        .price-chart .chart-axis-overlay-y-right {
          padding-left: 8px;
          right: 0;
          width: var(--price-axis-right-gutter, 1px);
        }

        @container price-chart (max-width: 520px) {
          .chart-axis-overlay-x-cull { display: none; }
          .price-chart .chart-axis-overlay-y-left {
            width: var(--price-axis-left-gutter, 1px);
          }
          .price-chart .chart-axis-overlay-y-right {
            width: var(--price-axis-right-gutter, 1px);
          }
        }

        .aggregated-chart-bar.dimmed,
        .aggregated-chart-svg .chart-label.dimmed {
          opacity: .4;
        }

        .aggregated-chart-svg .chart-label.hovered {
          fill: var(--primary-text-color);
          font-weight: 600;
        }

        .price-analysis {
          color: var(--secondary-text-color);
          font-size: var(--price-card-text-size);
          height: auto;
          line-height: 18px;
          margin: 0;
          min-height: 0;
          overflow: visible;
          overflow-wrap: anywhere;
          text-overflow: clip;
          white-space: normal;
        }

        .period-picker {
          align-items: center;
          display: flex;
          flex-direction: row-reverse;
          flex-wrap: nowrap;
          gap: clamp(3px, 1cqw, 8px);
          justify-content: flex-end;
          margin-bottom: 6px;
          max-width: 100%;
          min-width: 0;
          position: static;
          width: 100%;
          z-index: 3;
        }

        .period-picker-control,
        .period-picker-modes {
          align-items: center;
          display: flex;
          flex: 0 1 auto;
          gap: clamp(1px, .6cqw, 4px);
          min-width: 0;
          white-space: nowrap;
        }

        .period-picker-control { order: 2; }
        .period-picker-modes { order: 1; }

        .period-picker-control,
        .period-picker-modes {
          background: var(--ha-card-background, var(--card-background-color));
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          padding: 2px;
        }

        .period-picker-modes { margin-top: 0; }

        .period-picker-control button,
        .period-picker-modes button,
        .period-picker-control .period-picker-period {
          background: transparent;
          border: 0;
          border-radius: 6px;
          box-sizing: border-box;
          color: var(--secondary-text-color);
          cursor: pointer;
          margin: 0;
          min-height: 0;
          min-width: 0;
          padding: clamp(2px, .7cqw, 4px) clamp(3px, 1.1cqw, 8px);
        }

        .period-picker-control button,
        .period-picker-modes button { cursor: pointer; }

        .period-picker-dialog button {
          background: transparent;
          border: 0;
          border-radius: 6px;
          color: var(--secondary-text-color);
          cursor: pointer;
          font: inherit;
          margin: 0;
          min-width: 0;
          padding: 4px 8px;
        }

        .period-picker-control button:focus-visible,
        .period-picker-modes button:focus-visible,
        .period-picker-dialog button:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: -2px;
        }
        @media (hover: hover) and (pointer: fine) {
          .period-picker-control button:hover:not(.selected):not(.active),
          .period-picker-modes button:hover:not(.selected):not(.active),
          .period-picker-dialog button:hover:not(.selected):not(.active) {
            background: var(--primary-background-color);
            color: var(--primary-text-color);
          }
        }
        .period-picker-control button:active:not(.selected):not(.active),
        .period-picker-modes button:active:not(.selected):not(.active),
        .period-picker-dialog button:active:not(.selected):not(.active) {
          background: var(--primary-background-color);
          color: var(--primary-text-color);
        }
        .period-picker-arrow {
          font-size: clamp(14px, 2.5cqw, 18px) !important;
          line-height: 1;
          padding-inline: clamp(1px, .7cqw, 4px) !important;
        }
        .period-picker-period { color: var(--primary-text-color) !important; }
        .period-picker-modes button { font-size: clamp(10px, 1.7cqw, 12px); }
        .period-picker-modes button.active,
        .period-picker-choice.selected,
        .period-picker-day.selected { background: var(--primary-color); color: var(--text-primary-color); }

        .period-picker-dialog {
          background: var(--ha-card-background, var(--card-background-color));
          border: 1px solid var(--divider-color);
          border-radius: 10px;
          box-shadow: var(--ha-card-box-shadow, 0 8px 24px rgba(0, 0, 0, .25));
          box-sizing: border-box;
          color: var(--primary-text-color);
          margin: auto;
          max-height: calc(100dvh - 48px);
          max-width: calc(100vw - 48px);
          overflow-y: auto;
          padding: 12px;
          width: min(520px, calc(100vw - 48px));
        }

        .period-picker-dialog::backdrop {
          background: rgba(0, 0, 0, .52);
        }

        .period-picker-popover-header,
        .period-picker-dialog .period-picker-actions { justify-content: space-between; }
        .period-picker-popover-header strong { color: var(--primary-text-color); font-size: 13px; }
        .period-picker-weekdays,
        .period-picker-day-grid,
        .period-picker-month-grid,
        .period-picker-year-grid { display: grid; gap: 4px; grid-template-columns: repeat(7, minmax(0, 1fr)); margin-top: 8px; }
        .period-picker-weekday { color: var(--secondary-text-color); font-size: 11px; text-align: center; }
        .period-picker-day-grid button { min-height: 30px; padding: 2px; }
        .period-picker-day.outside { opacity: .35; }
        .period-picker-month-grid,
        .period-picker-year-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
        .period-picker-choice { min-height: 32px !important; }
        .period-picker-dialog .period-picker-actions {
          align-items: center;
          display: flex;
          gap: 4px;
          white-space: nowrap;
        }
        .period-picker-dialog .period-picker-actions { border-top: 1px solid var(--divider-color); margin-top: 10px; padding-top: 10px; }
        .period-picker-dialog .period-picker-actions button:last-child { color: var(--primary-text-color); font-weight: 600; }

        @media (max-width: 600px) {
          .period-picker-dialog {
            max-height: calc(100dvh - 48px);
            overflow-y: auto;
            padding: 10px;
            width: min(320px, calc(100vw - 32px));
          }

          .period-picker-popover-header {
            min-height: 36px;
          }

          .period-picker-weekdays,
          .period-picker-day-grid,
          .period-picker-month-grid,
          .period-picker-year-grid {
            gap: 2px;
            margin-top: 4px;
          }

          .period-picker-day-grid button,
          .period-picker-choice {
            min-height: 36px !important;
            touch-action: manipulation;
          }

          .period-picker-actions {
            min-height: 40px;
            margin-top: 6px;
            padding-top: 6px;
          }
        }

        .price-analysis-status {
          display: block;
          font-size: var(--price-card-text-size);
          font-weight: 600;
          line-height: 1.2;
        }

        .price-analysis-status.cheap {
          color: var(--el-price-cheap-color);
        }

        .price-analysis-status.normal {
          color: var(--el-price-normal-color);
        }

        .price-analysis-status.expensive {
          color: var(--el-price-expensive-color);
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
          min-height: 14px;
          justify-content: space-between;
          margin-top: 0;
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

        .chart-legend-toggle.long-pressing {
          opacity: .72;
        }

        .chart-legend-solo-badge {
          border: 1px solid currentColor;
          border-radius: 3px;
          display: none;
          font-size: 9px;
          font-weight: 600;
          letter-spacing: .04em;
          line-height: 12px;
          margin-left: 2px;
          padding: 0 3px;
        }

        .chart-legend-toggle.solo-active .chart-legend-solo-badge {
          display: inline-block;
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
          background: var(--el-price-normal-color);
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
          fill: var(--chart-axis-color);
          font-size: var(--chart-axis-font-size);
          font-weight: var(--chart-axis-font-weight);
          opacity: var(--chart-axis-opacity);
        }

        .chart-average {
          stroke: var(--el-price-normal-color);
          stroke-dasharray: 5 4;
          stroke-width: 1.5;
        }

        .chart-meter-gridline {
          stroke: var(--divider-color);
          stroke-width: 1;
          opacity: .28;
        }

        .chart-meter-label {
          fill: var(--chart-axis-color);
          font-size: var(--chart-axis-font-size);
          font-weight: var(--chart-axis-font-weight);
          opacity: var(--chart-axis-opacity);
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

        .chart-interpolated-line {
          opacity: .45;
        }

        .chart-interpolated-area {
          opacity: .35;
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

        .tooltip-copy-feedback {
          color: var(--secondary-text-color);
          display: block;
          font-size: .9em;
          margin-top: 4px;
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
          overflow: hidden;
          padding: 20px;
          position: relative;
          container-type: inline-size;
          backdrop-filter: var(--ha-card-backdrop-filter, none);
          -webkit-backdrop-filter: var(--ha-card-backdrop-filter, none);
        }

        .card.daily-energy-card {
          min-height: 0;
        }

        .card.soc-card {
          min-height: 0;
        }

        .card.soc-card[hidden] {
          display: none;
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

        .dashboard-card-toggle {
          align-items: center;
          cursor: pointer;
          display: inline-flex;
          margin-left: auto;
        }

        .dashboard-card-toggle input {
          height: 0;
          opacity: 0;
          position: absolute;
          width: 0;
        }

        .dashboard-card-toggle input:checked + .main-card-track {
          background: var(--primary-color);
        }

        .dashboard-card-toggle input:checked + .main-card-track::after {
          transform: translateX(11px);
        }

        h2 {
          font-size: 19px;
          font-weight: 500;
        }

        .provider, .status {
          color: var(--secondary-text-color);
          font-size: 14px;
        }

        .site-attention {
          background: color-mix(in srgb, var(--error-color) 16%, transparent);
          border: 1px solid color-mix(in srgb, var(--error-color) 55%, transparent);
          color: var(--primary-text-color);
          display: block;
          font-size: 13px;
          margin-top: 10px;
          padding: 7px 10px;
          text-align: left;
          width: 100%;
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
          padding: 10px 16px;
        }

      </style>
    `;

    this._setupThemeBackgroundSync();
    this._syncThemeBackground();
    this._bindElectricityProviderDialog();
    this._bindEonGridDialog();
    this._bindRetainedHistory();
    this._bindMeterDialog();
    this._bindPowerDialog();
    this._bindDebugToggle();
    this._bindConfigurationCardsToggle();
    this._bindSiteSettingsDialog();
    this._bindMainCardToggles();
    this._bindDashboardCardToggles();
    this._bindProviderSourceDialog();
    this._bindBoardDataDialog();
    this._bindMeterSourceDialog();
    this._bindLivePowerCards();
    this._bindPhaseHistoryCard();
        this._bindDiagnostics();
    this._bindMainInvoiceParser();
    this._bindCostCard();
    this._bindPeriodPicker();
    this._bindPricePlanSelectionEvents();
    this._bindChartLegend();
    this._setupPriceHeaderLayoutObserver();
    this._setupPriceChartResizeObserver();
    this.renderPriceChart();
    this._startPerformanceWatchdog();
  }

  _performanceMemoryText() {
    const memory = performance.memory;
    if (!memory || !Number.isFinite(memory.usedJSHeapSize)) return "";
    const usedMb = Math.round(memory.usedJSHeapSize / 1048576);
    const totalMb = Number.isFinite(memory.totalJSHeapSize) ? Math.round(memory.totalJSHeapSize / 1048576) : null;
    const limitMb = Number.isFinite(memory.jsHeapSizeLimit) ? Math.round(memory.jsHeapSizeLimit / 1048576) : null;
    return ` · Heap: ${usedMb} MB used · ${totalMb ? `${totalMb} MB allocated` : "allocated size unavailable"}${limitMb ? ` · Limit: ${limitMb} MB` : ""}`;
  }

  _sendPerformanceDiagnostic(level, event, message) {
    const state = this._performanceWatchdog;
    if (!this.hass?.callWS || !state || (state.stopped && event !== "performance_monitor_stopped")) return;
    this.hass.callWS({ type: "elrakning/meter_diagnostic", component: "performance", level, event, message: `Session: ${state.sessionId} · ${message}` }).catch(() => {});
  }

  _startPerformanceWatchdog() {
    if (this._performanceWatchdog) return;
    const state = { observer: null, sessionId: createPerformanceSessionId(), recentStalls: [], totalLongTasks: 0, totalWarnings: 0, maxLongTaskMs: 0, slowRendersByComponent: {}, maxRenderByComponent: {}, lastWarningAt: new Map(), startupSent: false, stopped: false };
    this._performanceWatchdog = state;
    if (typeof PerformanceObserver === "function") {
      try {
        state.observer = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) this._recordPerformanceStall(entry.duration);
        });
        state.observer.observe({ type: "longtask", buffered: true });
      } catch {
        state.observer = null;
      }
    }
    this._flushPerformanceWatchdogStartup();
  }

  _recordPerformanceStall(durationMs) {
    const state = this._performanceWatchdog;
    if (!state || !Number.isFinite(durationMs)) return;
    const now = Date.now();
    state.totalLongTasks += 1;
    state.maxLongTaskMs = Math.max(state.maxLongTaskMs, durationMs);
    state.recentStalls = state.recentStalls.filter((timestamp) => now - timestamp <= 60_000);
    if (durationMs >= 100) state.recentStalls.push(now);
    const kind = performanceWarningKind(durationMs, state.recentStalls, now);
    if (!kind) return;
    const last = state.lastWarningAt.get(kind) || 0;
    if (now - last < 180_000) return;
    state.lastWarningAt.set(kind, now);
    state.totalWarnings += 1;
    const detail = kind === "ui_stall"
      ? `UI performance degraded · Main-thread stall: ${Math.round(durationMs)} ms · Events this session: ${state.totalLongTasks}`
      : `Repeated UI stalls · ${state.recentStalls.length} events / 60 s · Max: ${Math.round(state.maxLongTaskMs)} ms · Session total: ${state.totalLongTasks}`;
    this._sendPerformanceDiagnostic("WARNING", kind, `${detail} · Visibility: ${document.visibilityState}${this._performanceMemoryText()}`);
  }

  _recordSlowRender(component, durationMs) {
    const state = this._performanceWatchdog;
    if (!state || !Number.isFinite(durationMs) || durationMs < 250) return;
    state.slowRendersByComponent[component] = (state.slowRendersByComponent[component] || 0) + 1;
    state.maxRenderByComponent[component] = Math.max(state.maxRenderByComponent[component] || 0, durationMs);
    const key = `slow_render:${component}`;
    const now = Date.now();
    if (now - (state.lastWarningAt.get(key) || 0) < 180_000) return;
    state.lastWarningAt.set(key, now);
    state.totalWarnings += 1;
    this._sendPerformanceDiagnostic("WARNING", "slow_render", `Slow render · Component: ${component} · Duration: ${Math.round(durationMs)} ms · Session count: ${state.slowRendersByComponent[component]}${this._performanceMemoryText()}`);
  }

  _flushPerformanceWatchdogStartup() {
    const state = this._performanceWatchdog;
    if (!state || state.startupSent || !this.hass?.callWS) return;
    this._sendPerformanceDiagnostic("INFO", "performance_monitor_started", `Performance monitor started · Long Tasks: ${state.observer ? "supported" : "unsupported"} · Memory: ${performance.memory ? "supported" : "unsupported"}`);
    state.startupSent = true;
  }

  _stopPerformanceWatchdog() {
    const state = this._performanceWatchdog;
    if (!state || state.stopped) return;
    state.stopped = true;
    state.observer?.disconnect();
    this._sendPerformanceDiagnostic("INFO", "performance_monitor_stopped", "Performance monitor stopped");
    this._performanceWatchdog = null;
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

  _setupPriceChartResizeObserver() {
    const chart = this.host.querySelector(".price-chart");
    if (!chart || !("ResizeObserver" in window)) return;
    let frame = 0;
    const updateChartGeometry = (entries) => {
      const width = Number(entries[0]?.contentRect?.width || 0);
      if (!(width > 0) || Math.abs(width - (this._priceChartRenderedWidth || 0)) < 1) return;
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        frame = 0;
        const renderedWidth = chart.getBoundingClientRect().width || chart.clientWidth || 0;
        if (!(renderedWidth > 0) || Math.abs(renderedWidth - (this._priceChartRenderedWidth || 0)) < 1) return;
        this.renderPriceChart({ layoutUpdate: true });
      });
    };
    this._priceChartResizeObserver = new ResizeObserver(updateChartGeometry);
    this._priceChartResizeObserver.observe(chart);
  }

  _periodPickerLabel(date = this._periodPickerState.confirmed) {
    const value = this._periodPickerState.mode;
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return value === "hour" ? `${year}-${month}-${day}` : value === "day" ? `${year}-${month}` : `${year}`;
  }

  _periodPickerMonthName(date) {
    return date.toLocaleDateString("sv-SE", { month: "long", year: "numeric" });
  }

  _isMobilePeriodPicker() {
    return typeof window.matchMedia === "function" && window.matchMedia("(max-width: 600px)").matches;
  }

  _updatePeriodPickerDraftSelection() {
    const root = this.host.querySelector("[data-period-picker]");
    const dialog = root?.querySelector("[data-period-picker-dialog]");
    const popover = root?.querySelector("[data-period-picker-popover]");
    const surface = dialog?.open ? dialog : popover;
    if (!surface) return;
    const state = this._periodPickerState;
    surface.querySelectorAll(".period-picker-day").forEach((button) => {
      button.classList.toggle("selected", Number(button.dataset.periodPickerDate) === state.draft.getTime());
    });
    surface.querySelectorAll(".period-picker-choice").forEach((button) => {
      const month = button.dataset.periodPickerMonth;
      const year = button.dataset.periodPickerYear;
      const selected = month !== undefined
        ? state.draft.getFullYear() === state.cursor.getFullYear() && state.draft.getMonth() === Number(month)
        : year !== undefined && state.draft.getFullYear() === Number(year);
      button.classList.toggle("selected", selected);
    });
  }

  _renderPeriodPicker() {
    const state = this._periodPickerState;
    const root = this.host.querySelector("[data-period-picker]");
    const label = root?.querySelector("[data-period-picker-label]");
    const popover = root?.querySelector("[data-period-picker-popover]");
    const dialog = root?.querySelector("[data-period-picker-dialog]");
    if (!root || !label || !popover || !dialog) return;
    const showPeriodNavigation = state.mode !== "year";
    root.querySelectorAll("[data-period-picker-nav]").forEach((button) => {
      button.hidden = !showPeriodNavigation;
    });
    label.textContent = this._periodPickerLabel();
    root.querySelectorAll("[data-period-picker-mode]").forEach((button) => {
      const active = button.dataset.periodPickerMode === state.mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
    const periodButton = root.querySelector("[data-period-picker-open]");
    const staticPeriod = root.querySelector("[data-period-picker-static]");
    if (state.mode === "year" && periodButton) {
      const replacement = periodButton.ownerDocument.createElement("span");
      replacement.className = periodButton.className;
      replacement.setAttribute("data-period-picker-static", "");
      replacement.appendChild(label);
      periodButton.replaceWith(replacement);
    } else if (state.mode !== "year" && staticPeriod) {
      const replacement = staticPeriod.ownerDocument.createElement("button");
      replacement.type = "button";
      replacement.className = staticPeriod.className;
      replacement.setAttribute("data-period-picker-open", "");
      replacement.setAttribute("aria-haspopup", "dialog");
      replacement.appendChild(label);
      staticPeriod.replaceWith(replacement);
    }
    const activePeriodButton = root.querySelector("[data-period-picker-open]");
    activePeriodButton?.setAttribute("aria-expanded", String(state.open));
    popover.hidden = true;
    if (!state.open) {
      if (dialog.open) dialog.close();
      return;
    }
    if (!dialog.open) dialog.showModal();
    const pickerContent = dialog;
    const cursor = state.cursor;
    if (state.mode === "hour") {
      const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
      const offset = (first.getDay() + 6) % 7;
      const weekdays = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"].map((name) => `<span class="period-picker-weekday">${name}</span>`).join("");
      const cells = Array.from({ length: 42 }, (_, index) => {
        const date = new Date(cursor.getFullYear(), cursor.getMonth(), index - offset + 1);
        const currentMonth = date.getMonth() === cursor.getMonth();
        const selected = date.toDateString() === state.draft.toDateString();
        return `<button type="button" class="period-picker-day${currentMonth ? "" : " outside"}${selected ? " selected" : ""}" data-period-picker-date="${date.getTime()}">${date.getDate()}</button>`;
      }).join("");
      pickerContent.innerHTML = `<div class="period-picker-popover-header"><button type="button" data-period-picker-calendar-nav="previous" aria-label="Föregående månad">‹</button><strong>${this._periodPickerMonthName(cursor)}</strong><button type="button" data-period-picker-calendar-nav="next" aria-label="Nästa månad">›</button></div><div class="period-picker-weekdays">${weekdays}</div><div class="period-picker-day-grid">${cells}</div><div class="period-picker-actions"><button type="button" data-period-picker-now>Nu</button><button type="button" data-period-picker-confirm>Bekräfta</button></div>`;
      return;
    }
    if (state.mode === "day") {
      const months = ["Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"].map((name, index) => {
        const selected = state.draft.getFullYear() === cursor.getFullYear() && state.draft.getMonth() === index;
        return `<button type="button" class="period-picker-choice${selected ? " selected" : ""}" data-period-picker-month="${index}">${name}</button>`;
      }).join("");
      pickerContent.innerHTML = `<div class="period-picker-popover-header"><button type="button" data-period-picker-calendar-nav="previous" aria-label="Föregående år">‹</button><strong>${cursor.getFullYear()}</strong><button type="button" data-period-picker-calendar-nav="next" aria-label="Nästa år">›</button></div><div class="period-picker-month-grid">${months}</div><div class="period-picker-actions"><button type="button" data-period-picker-now>Nu</button><button type="button" data-period-picker-confirm>Bekräfta</button></div>`;
      return;
    }
    const startYear = Math.floor(cursor.getFullYear() / 15) * 15;
    const years = Array.from({ length: 15 }, (_, index) => startYear + index).map((year) => `<button type="button" class="period-picker-choice${state.draft.getFullYear() === year ? " selected" : ""}" data-period-picker-year="${year}">${year}</button>`).join("");
    pickerContent.innerHTML = `<div class="period-picker-popover-header"><button type="button" data-period-picker-calendar-nav="previous" aria-label="Föregående årtionde">‹</button><strong>${startYear}–${startYear + 14}</strong><button type="button" data-period-picker-calendar-nav="next" aria-label="Nästa årtionde">›</button></div><div class="period-picker-year-grid">${years}</div><div class="period-picker-actions"><button type="button" data-period-picker-now>Nu</button><button type="button" data-period-picker-confirm>Bekräfta</button></div>`;
  }

  _bindPeriodPicker() {
    const root = this.host.querySelector("[data-period-picker]");
    const dialog = root?.querySelector("[data-period-picker-dialog]");
    if (!root || !dialog) return;
    const applySelectedHourDate = async (date) => {
      const next = new Date(date);
      if (!Number.isFinite(next.getTime())) return;
      this._clearPricePlanSelection();
      const previous = this._periodPickerState.confirmed;
      const changed = !previous || previous.getTime() !== next.getTime();
      this._periodPickerState.confirmed = next;
      this._periodPickerState.draft = new Date(next);
      this._periodPickerState.open = false;
      this._renderPeriodPicker();
      if (changed) {
        this._recordPowerFlowDiagnostic("date_change", { requested_date: localDateKey(next) });
        const dateChangeStarted = performance.now();
        await Promise.all([this.loadPriceData(next), this.loadPricePlan(next), this.loadPowerHistory(next)]);
        this._recordPowerFlowDiagnostic("date_change_complete", {
          requested_date: localDateKey(next), duration_ms: roundDiagnosticMs(performance.now() - dateChangeStarted),
        });
      }
      else {
        this.updatePriceSummary();
        this.renderPriceChart();
      }
    };
    const close = () => {
      this._periodPickerState.open = false;
      this._periodPickerState.draft = new Date(this._periodPickerState.confirmed);
      this._renderPeriodPicker();
    };
    root.querySelectorAll("[data-period-picker-mode]").forEach((button) => button.addEventListener("click", () => {
      this._clearPricePlanSelection();
      this._periodPickerState.mode = button.dataset.periodPickerMode;
      if (this._soloChartLayer === "average" && this._periodPickerState.mode !== "hour") {
        this._clearSoloChartLayer({ render: false });
      }
      this._renderPeriodPicker();
      this.updatePriceSummary();
      this.renderPriceChart();
    }));
    root.querySelectorAll("[data-period-picker-nav]").forEach((button) => button.addEventListener("click", async () => {
      this._clearPricePlanSelection();
      if (this._periodPickerState.mode === "year") return;
      const date = new Date(this._periodPickerState.confirmed);
      const direction = button.dataset.periodPickerNav === "next" ? 1 : -1;
      if (this._periodPickerState.mode === "hour") date.setDate(date.getDate() + direction);
      else if (this._periodPickerState.mode === "day") date.setMonth(date.getMonth() + direction, 1);
      else date.setFullYear(date.getFullYear() + direction, date.getMonth(), 1);
      if (this._periodPickerState.mode === "hour") {
        await applySelectedHourDate(date);
      } else {
        this._periodPickerState.confirmed = date;
        this._periodPickerState.draft = new Date(date);
        this._renderPeriodPicker();
        this.updatePriceSummary();
        this.renderPriceChart();
      }
    }));
    const handlePickerClick = (event) => {
      if (event.__periodPickerHandled) return;
      event.__periodPickerHandled = true;
      const periodPickerOpen = event.target.closest?.("[data-period-picker-open]");
      if (periodPickerOpen) {
        this._periodPickerState.open = !this._periodPickerState.open;
        this._periodPickerState.draft = new Date(this._periodPickerState.confirmed);
        this._periodPickerState.cursor = new Date(this._periodPickerState.draft.getFullYear(), this._periodPickerState.draft.getMonth(), 1);
        event.stopPropagation();
        this._renderPeriodPicker();
        return;
      }
      if (dialog.open) {
        const rect = dialog.getBoundingClientRect();
        const outside = event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom;
        if (outside) {
          event.preventDefault();
          event.stopPropagation();
          close();
          return;
        }
      }
      event.stopPropagation();
      let draftSelectionChanged = false;
      const dateButton = event.target.closest?.("[data-period-picker-date]");
      if (dateButton) {
        this._periodPickerState.draft = new Date(Number(dateButton.dataset.periodPickerDate));
        draftSelectionChanged = true;
      }
      const monthButton = event.target.closest?.("[data-period-picker-month]");
      if (monthButton) {
        this._periodPickerState.draft = new Date(this._periodPickerState.cursor.getFullYear(), Number(monthButton.dataset.periodPickerMonth), 1);
        draftSelectionChanged = true;
      }
      const yearButton = event.target.closest?.("[data-period-picker-year]");
      if (yearButton) {
        this._periodPickerState.draft = new Date(Number(yearButton.dataset.periodPickerYear), this._periodPickerState.draft.getMonth(), 1);
        draftSelectionChanged = true;
      }
      const calendarNav = event.target.closest?.("[data-period-picker-calendar-nav]");
      if (calendarNav) {
        const direction = calendarNav.dataset.periodPickerCalendarNav === "next" ? 1 : -1;
        const months = this._periodPickerState.mode === "hour" ? direction : this._periodPickerState.mode === "day" ? direction * 12 : direction * 15;
        this._periodPickerState.cursor.setMonth(this._periodPickerState.cursor.getMonth() + months);
      }
      if (event.target.closest?.("[data-period-picker-now]")) {
        const now = new Date();
        this._periodPickerState.draft = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        this._periodPickerState.cursor = new Date(now.getFullYear(), now.getMonth(), 1);
      }
      if (event.target.closest?.("[data-period-picker-confirm]")) {
        if (this._periodPickerState.mode === "hour") {
          applySelectedHourDate(this._periodPickerState.draft);
          return;
        }
        this._periodPickerState.confirmed = new Date(this._periodPickerState.draft);
        this._periodPickerState.open = false;
        this._renderPeriodPicker();
        this.updatePriceSummary();
        this.renderPriceChart();
      }
      if (draftSelectionChanged) {
        this._updatePeriodPickerDraftSelection();
        return;
      }
      this._renderPeriodPicker();
    };
    root.addEventListener("click", handlePickerClick);
    dialog.addEventListener("click", handlePickerClick);
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      close();
    });
    window.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (this._soloChartLayer) this._clearSoloChartLayer();
      if (this._periodPickerState.open) close();
    });
    this._renderPeriodPicker();
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
    if (this._soloChartLayer) return Object.fromEntries(Object.keys(layers).map((key) => [key, key === this._soloChartLayer]));
    return layers;
  }

  _setSoloChartLayer(layer) {
    if (!layer) return;
    if (this._soloChartLayer === layer) {
      this._clearSoloChartLayer();
      return;
    } else {
      if (!this._soloChartLayer) this._soloChartLayerSnapshot = this._chartLayerState();
      this._soloChartLayer = layer;
    }
    this._syncChartLayerButtons();
    this.renderPriceChart();
  }

  _clearSoloChartLayer({ render = true } = {}) {
    if (!this._soloChartLayer) return false;
    this._applyChartLayerState(this._soloChartLayerSnapshot);
    this._soloChartLayer = null;
    this._soloChartLayerSnapshot = null;
    this._syncChartLayerButtons();
    if (render) this.renderPriceChart();
    return true;
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

  _applyDashboardCardVisibility(preferences) {
    if (!preferences || typeof preferences !== "object") return;
    for (const key of Object.keys(this._dashboardCardVisibility)) {
      if (["always", "config_only", "hidden"].includes(preferences[key])) this._dashboardCardVisibility[key] = preferences[key];
    }
    this._renderDashboardCardVisibility();
  }

  _dashboardCardIsConfigured(key) {
    if (key === "house") return Boolean(this._powerState?.consumption_entity);
    if (key === "solar") return Array.isArray(this._powerState?.solar_entities) && this._powerState.solar_entities.some(Boolean);
    if (key === "grid") return this._meterState?.configured === true;
    if (key === "battery") return Boolean(this._powerState?.battery_power_entity || this._powerState?.charging_entity || this._powerState?.discharging_entity || this._powerState?.soc_entity || this._powerState?.capacity_entity);
    return true;
  }

  _renderDashboardCardVisibility() {
    const visible = (key) => this._dashboardCardVisibility[key] !== "hidden"
      && (this._dashboardCardVisibility[key] === "always" || this._dashboardCardIsConfigured(key));
    const groups = {
      house: ["[data-live-power-tile=house]", "[data-daily-energy]"],
      solar: ["[data-live-power-tile=solar]", "[data-power-card=solar-history]", "[data-solar-evidence-card]"],
      grid: ["[data-live-power-tile=grid]", "[data-phase-history-card]"],
      battery: ["[data-live-power-tile=battery]", "[data-power-card=battery-history]", "[data-soc-card]"],
      invoice: ["[data-invoice-estimate-card]", "[data-cost-card]"],
    };
    for (const [key, selectors] of Object.entries(groups)) {
      for (const selector of selectors) {
        for (const node of this.host.querySelectorAll(selector)) node.hidden = !visible(key);
      }
    }
    for (const toggle of this.host.querySelectorAll("[data-dashboard-card-toggle]")) {
      const input = toggle.querySelector("input");
      const key = toggle.dataset.dashboardCardToggle;
      if (input && key in this._dashboardCardVisibility) input.checked = this._dashboardCardVisibility[key] !== "hidden";
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

  _applyPriceComparisonState(preferences) {
    if (!preferences || typeof preferences !== "object") return;
    for (const key of Object.keys(this._priceComparisonVisible)) {
      if (typeof preferences[key] === "boolean") this._priceComparisonVisible[key] = preferences[key];
    }
  }

  _applyPhaseHistoryPreference(preference) {
    if (["current", "voltage", "active_power"].includes(preference)) this._phaseHistoryMetric = preference;
  }

  _applyPhaseHistoryVisibility(preferences) {
    if (!preferences || typeof preferences !== "object") return;
    for (const phase of Object.keys(this._phaseHistoryVisible)) {
      if (typeof preferences[phase] === "boolean") this._phaseHistoryVisible[phase] = preferences[phase];
    }
  }

  _syncPhaseHistoryMetricButtons() {
    for (const button of this.host.querySelectorAll("[data-phase-metric]")) {
      const active = button.dataset.phaseMetric === this._phaseHistoryMetric;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    }
  }

  _syncPhaseHistoryVisibilityButtons() {
    for (const item of this.host.querySelectorAll("[data-phase-summary]")) {
      const active = this._phaseHistoryVisible[item.dataset.phaseSummary] === true;
      item.classList.toggle("active", active);
      item.classList.toggle("inactive", !active);
      item.setAttribute("aria-pressed", String(active));
    }
  }

  _syncChartLayerButtons() {
    const layers = this._effectiveChartLayerState();
    for (const button of this.host.querySelectorAll("[data-chart-layer]")) {
      const value = layers[button.dataset.chartLayer];
      if (typeof value !== "boolean") continue;
      button.classList.toggle("active", value);
      button.classList.toggle("solo-active", this._soloChartLayer === button.dataset.chartLayer);
      button.setAttribute("aria-pressed", String(value));
    }
    for (const button of this.host.querySelectorAll("[data-preview-layer]")) {
      const value = layers[button.dataset.previewLayer];
      if (typeof value !== "boolean") continue;
      button.classList.toggle("active", value);
      button.classList.toggle("solo-active", this._soloChartLayer === button.dataset.previewLayer);
      button.setAttribute("aria-pressed", String(value));
    }
  }

  async _loadChartPreferences() {
    if (!this.hass?.callWS) return;
    try {
      const response = await this.hass.callWS({ type: "elrakning/ui_preferences/get" });
      this._applyChartLayerState(response.chart_layers);
      this._applyPriceComparisonState(response.price_comparison);
      this._applyPhaseHistoryPreference(response.phase_history_metric);
      this._applyPhaseHistoryVisibility(response.phase_history_visible);
      this._applyConfigurationCardsVisibility(response.configuration_cards_visible, response.main_cards);
      this._applyDashboardCardVisibility(response.dashboard_card_visibility);
      this._chartPreferencesReady = true;
      this._syncChartLayerButtons();
      this._syncPriceComparisonControls();
      this._syncPhaseHistoryMetricButtons();
      this._syncPhaseHistoryVisibilityButtons();
      this.renderPriceChart();
    } catch {
      // Keep the first-use defaults for this session when preference loading fails.
    }
  }

  async _persistChartPreferences(updates = {}) {
    if (!this.hass?.callWS || !this._chartPreferencesReady) return;
    const payload = {
      type: "elrakning/ui_preferences/set",
      ...updates,
    };
    this._chartPreferencesSavePromise = this._chartPreferencesSavePromise
      .catch(() => {})
      .then(async () => {
        try {
          const response = await this.hass.callWS(payload);
          if (updates.price_comparison && response?.price_comparison) {
            this._applyPriceComparisonState(response.price_comparison);
            this._syncPriceComparisonControls();
            this.updatePriceSummary();
            this.renderPriceChart();
          }
          return response;
        } catch {
          // Keep the UI responsive when preference persistence is unavailable.
        }
      });
    return this._chartPreferencesSavePromise;
  }

  _bindChartLegend() {
    const previewSelectors = {
      spot: [".chart-bar", ".aggregated-chart-price"],
      average: [".chart-average"],
      import: [".aggregated-chart-import", ".chart-meter-import", ".chart-power-area-import"],
      export: [".aggregated-chart-export", ".chart-meter-export", ".chart-power-area-export"],
      solar: [".aggregated-chart-solar", ".chart-power-solar", ".chart-power-area-solar"],
      consumption: [".aggregated-chart-consumption", ".chart-power-consumption", ".chart-power-area-consumption"],
      charging: [".aggregated-chart-charging", ".chart-power-charging", ".chart-power-area-charging"],
      discharging: [".aggregated-chart-discharging", ".chart-power-discharging", ".chart-power-area-discharging"],
    };
    const setHoverPreview = (layer) => {
      if (this._soloChartLayer) return;
      const chart = this.host.querySelector(".price-chart");
      if (!chart || !previewSelectors[layer]) return;
      const allSeries = Object.values(previewSelectors).flat();
      chart.querySelectorAll(allSeries.join(",")).forEach((node) => {
        node.style.opacity = "0";
      });
      chart.querySelectorAll(previewSelectors[layer].join(",")).forEach((node) => {
        node.style.opacity = "";
      });
    };
    const clearHoverPreview = () => {
      const chart = this.host.querySelector(".price-chart");
      if (!chart) return;
      chart.querySelectorAll(Object.values(previewSelectors).flat().join(",")).forEach((node) => {
        node.style.opacity = "";
      });
    };
    const toggleLayer = (layer) => {
      if (this._soloChartLayer) {
        this._clearSoloChartLayer();
        return;
      }
      if (layer === "import" || layer === "export") this._meterPowerVisible[layer] = !this._meterPowerVisible[layer];
      else if (layer === "average") this._averageLineVisible = !this._averageLineVisible;
      else if (layer === "spot") this._spotBarsVisible = !this._spotBarsVisible;
      else if (layer in this._previewLayersVisible) this._previewLayersVisible[layer] = !this._previewLayersVisible[layer];
      else return;
      this._syncChartLayerButtons();
      this.renderPriceChart();
      this._persistChartPreferences({ chart_layers: this._chartLayerState() });
    };
    const bindLongPress = (button, layer) => {
      let timer = null;
      let startX = 0;
      let startY = 0;
      let longPressTriggered = false;
      const cancel = () => {
        if (timer !== null) window.clearTimeout(timer);
        timer = null;
        button.classList.remove("long-pressing");
      };
      button.addEventListener("pointerdown", (event) => {
        if (event.pointerType === "mouse" && event.button !== 0) return;
        longPressTriggered = false;
        startX = event.clientX;
        startY = event.clientY;
        button.classList.add("long-pressing");
        timer = window.setTimeout(() => {
          timer = null;
          longPressTriggered = true;
          button.classList.remove("long-pressing");
          this._setSoloChartLayer(layer);
        }, 600);
      });
      button.addEventListener("pointermove", (event) => {
        if (timer !== null && Math.hypot(event.clientX - startX, event.clientY - startY) > 8) cancel();
      });
      button.addEventListener("pointerup", (event) => {
        if (timer !== null) cancel();
        if (longPressTriggered) {
          event.preventDefault();
          button.dataset.longPressHandled = "true";
        }
      });
      button.addEventListener("pointerleave", cancel);
      button.addEventListener("pointercancel", cancel);
      button.addEventListener("contextmenu", (event) => event.preventDefault());
      button.addEventListener("click", (event) => {
        if (button.dataset.longPressHandled === "true") {
          delete button.dataset.longPressHandled;
          event.preventDefault();
          event.stopPropagation();
          return;
        }
        toggleLayer(layer);
      });
    };
    const bindHoverPreview = (button, layer) => {
      button.addEventListener("pointerenter", (event) => {
        if (event.pointerType === "touch" || button.disabled) return;
        setHoverPreview(layer);
      });
      button.addEventListener("pointerleave", (event) => {
        if (event.pointerType === "touch") return;
        clearHoverPreview();
      });
    };
    for (const button of this.host.querySelectorAll("[data-chart-layer]")) {
      bindHoverPreview(button, button.dataset.chartLayer);
      bindLongPress(button, button.dataset.chartLayer);
    }
    for (const button of this.host.querySelectorAll("[data-preview-layer]")) {
      bindHoverPreview(button, button.dataset.previewLayer);
      bindLongPress(button, button.dataset.previewLayer);
    }
    for (const control of this.host.querySelectorAll("[data-price-layer]")) {
      const input = control.querySelector("[data-price-toggle]");
      if (!input) continue;
      input.addEventListener("change", () => {
        const layer = control.dataset.priceLayer;
        if (!(layer in this._priceComparisonVisible) || input.disabled) return;
        this._priceComparisonVisible[layer] = input.checked;
        this.updatePriceSummary();
        this.renderPriceChart();
        this._persistChartPreferences({ price_comparison: { ...this._priceComparisonVisible } });
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
    toggle.addEventListener("click", () => this._openSiteSettings());
  }

  async _loadSiteIdentity() {
    if (!this.hass?.callWS) return null;
    const knownSiteId = this._siteState?.site_id || this._siteState?.current_site?.site_id;
    if (knownSiteId) return this._siteState;
    if (this._siteIdentityPromise) return this._siteIdentityPromise;
    const requestHass = this.hass;
    const request = (async () => {
      try {
        const state = await requestHass.callWS({ type: "elrakning/site_identity" });
        if (this.hass !== requestHass) return null;
        this._applySiteIdentityState(state);
        return state;
      } catch (error) {
        const result = this.host.querySelector("[data-site-settings-result]");
        if (result) result.textContent = "Installationer kunde inte hämtas.";
        return null;
      }
    })();
    this._siteIdentityPromise = request;
    request.finally(() => {
      if (this._siteIdentityPromise === request) this._siteIdentityPromise = null;
    }).catch(() => {});
    return request;
  }

  _applySiteIdentityState(state) {
    const reconciled = reconcileEllaSiteState(this._siteState, state, {
      loadForecast: this._loadForecast,
      pricePlan: this._pricePlan,
      ellaSelection: this._ellaSelection,
    });
    if (reconciled.changed) {
      this._siteContextGeneration += 1;
      this._powerHistoryRequestToken += 1;
      this._pricePlanRequestToken += 1;
      this._benchmarkEvidenceRequestToken += 1;
      this._loadForecast = reconciled.loadForecast;
      this._pricePlan = reconciled.pricePlan;
      this._benchmarkEvidence = { schema: "ella_replay_benchmark_evidence.v1", site_id: state?.current_site?.site_id || state?.site_id || null, available: false, status: "unavailable", blocker: "site_changed" };
      this._pricePlanContextKey = reconciled.changed ? null : this._pricePlanContextKey;
      this._ellaSelection = reconciled.ellaSelection;
    }
    this._siteState = state;
    this._renderSiteSettings();
    this._renderSiteAttention();
    this._renderPricePlanCards();
  }

  _renderSiteAttention() {
    const button = this.host.querySelector("[data-site-attention]");
    if (!button) return;
    const attention = Array.isArray(this._siteState?.site_attention)
      ? this._siteState.site_attention[0]
      : null;
    const visible = attention?.status === "action_required";
    button.hidden = !visible;
    if (!visible) {
      button.textContent = "";
      return;
    }
    const siteName = attention.site_name || attention.site_id || "En annan installation";
    button.textContent = `${siteName} behöver åtgärd`;
    button.title = attention.details_safe_for_ui || "Öppna installationsinställningar";
    button.onclick = () => this._openSiteSettings();
  }

  _renderSiteSettings() {
    const state = this._siteState || {};
    const current = state.current_site || state.site || {};
    const currentId = state.site_id || current.site_id || null;
    const name = this.host.querySelector("[data-site-current-name]");
    const id = this.host.querySelector("[data-site-current-id]");
    const created = this.host.querySelector("[data-site-current-created]");
    const select = this.host.querySelector("[data-site-select]");
    const activate = this.host.querySelector("[data-site-activate]");
    const configToggle = this.host.querySelector("[data-site-config-cards-toggle]");
    if (name) name.textContent = current.name || "Namnlös installation";
    if (id) id.textContent = currentId || "–";
    if (created) created.textContent = current.created_at ? `Skapad ${current.created_at}` : "";
    if (configToggle) configToggle.checked = this._configurationCardsVisible;
    for (const select of this.host.querySelectorAll("[data-dashboard-card-visibility]")) {
      select.value = this._dashboardCardVisibility[select.dataset.dashboardCardVisibility] || "always";
    }
    if (!select) return;
    const sites = Array.isArray(state.available_sites) ? state.available_sites : [];
    select.replaceChildren(...sites.map((site) => {
      const option = document.createElement("option");
      option.value = site.site_id || "";
      option.textContent = site.name || site.site_id || "Namnlös installation";
      option.selected = option.value === currentId;
      return option;
    }));
    if (activate) activate.disabled = !select.value || select.value === currentId;
  }

  _setSiteSettingsBusy(busy) {
    for (const control of this.host.querySelectorAll("[data-site-activate], [data-site-rename], [data-site-create], [data-site-select]")) control.disabled = busy;
  }

  async _openSiteSettings() {
    const dialog = this.host.querySelector("[data-site-settings-dialog]");
    if (!dialog) return;
    dialog.hidden = false;
    await this._loadSiteIdentity();
  }

  _bindSiteSettingsDialog() {
    const dialog = this.host.querySelector("[data-site-settings-dialog]");
    const close = this.host.querySelector("[data-site-settings-close]");
    const select = this.host.querySelector("[data-site-select]");
    const activate = this.host.querySelector("[data-site-activate]");
    const rename = this.host.querySelector("[data-site-rename]");
    const create = this.host.querySelector("[data-site-create]");
    const configToggle = this.host.querySelector("[data-site-config-cards-toggle]");
    if (!dialog || !close || !select || !activate || !rename || !create || !configToggle) return;
    const result = this.host.querySelector("[data-site-settings-result]");
    const currentId = () => this._siteState?.current_site?.site_id || this._siteState?.site_id || null;
    close.addEventListener("click", () => { dialog.hidden = true; });
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.hidden = true; });
    select.addEventListener("change", () => { activate.disabled = !select.value || select.value === currentId(); });
    configToggle.addEventListener("change", () => {
      this._applyConfigurationCardsVisibility(configToggle.checked);
      this._persistChartPreferences({ configuration_cards_visible: this._configurationCardsVisible });
    });
    for (const select of dialog.querySelectorAll("[data-dashboard-card-visibility]")) {
      select.addEventListener("change", () => {
        const key = select.dataset.dashboardCardVisibility;
        if (!(key in this._dashboardCardVisibility)) return;
        this._dashboardCardVisibility[key] = select.value;
        this._renderDashboardCardVisibility();
        this._persistChartPreferences({ dashboard_card_visibility: { ...this._dashboardCardVisibility } });
      });
    }
    rename.addEventListener("click", async () => {
      const id = currentId();
      const name = window.prompt("Namn på installationen", this._siteState?.current_site?.name || "");
      if (!id || name == null || !name.trim()) return;
      this._setSiteSettingsBusy(true);
      try {
        const response = await this.hass.callWS({ type: "elrakning/site_rename", site_id: id, name: name.trim() });
        if (!response?.success) throw new Error(response?.error || "site_rename_failed");
        this._applySiteIdentityState(response);
        this._renderSiteSettings();
        if (result) result.textContent = "Namnet sparades.";
      } catch (error) {
        if (result) result.textContent = `Namn kunde inte sparas: ${error.message}`;
      } finally { this._setSiteSettingsBusy(false); }
    });
    create.addEventListener("click", async () => {
      const name = window.prompt("Namn på ny installation", "Ny installation");
      if (name == null || !name.trim()) return;
      this._setSiteSettingsBusy(true);
      try {
        const response = await this.hass.callWS({ type: "elrakning/site_create", name: name.trim() });
        if (!response?.success) throw new Error(response?.error || "site_create_failed");
        this._applySiteIdentityState(response);
        this._renderSiteSettings();
        if (result) result.textContent = "Installationen skapades. Välj den och bekräfta byte om den ska aktiveras.";
      } catch (error) {
        if (result) result.textContent = `Installation kunde inte skapas: ${error.message}`;
      } finally { this._setSiteSettingsBusy(false); }
    });
    activate.addEventListener("click", async () => {
      const site = this._siteState?.available_sites?.find((item) => item.site_id === select.value);
      if (!site || select.value === currentId()) return;
      if (!window.confirm(`Byt aktiv installation till ${site.name || site.site_id}? Nya mappings tillhör därefter denna site. Gamla data raderas inte.`)) return;
      this._setSiteSettingsBusy(true);
      if (result) result.textContent = "Byter installation …";
      try {
        const response = await this.hass.callWS({ type: "elrakning/site_activate", site_id: site.site_id, confirm: true });
        if (!response?.success) throw new Error(response?.error || "site_activate_failed");
        this._applySiteIdentityState(response);
        this._renderSiteSettings();
        await this._refreshBackendState(true);
        if (result) result.textContent = "Installationen är aktiv.";
        window.location.reload();
      } catch (error) {
        if (result) result.textContent = `Byte kunde inte genomföras: ${error.message}`;
        await this._loadSiteIdentity();
      } finally { this._setSiteSettingsBusy(false); }
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
        this._persistChartPreferences({ main_cards: { ...this._mainCards } });
      });
    }
  }

  _bindDashboardCardToggles() {
    for (const toggle of this.host.querySelectorAll("[data-dashboard-card-toggle]")) {
      const input = toggle.querySelector("input");
      const key = toggle.dataset.dashboardCardToggle;
      if (!input || !(key in this._dashboardCardVisibility)) continue;
      input.checked = this._dashboardCardVisibility[key] !== "hidden";
      input.addEventListener("change", () => {
        this._dashboardCardVisibility[key] = input.checked ? "always" : "hidden";
        this._renderDashboardCardVisibility();
        this._persistChartPreferences({ dashboard_card_visibility: { ...this._dashboardCardVisibility } });
      });
    }
  }

  async _buildBoardDataSnapshot() {
    const call = async (type) => {
      try {
        return { status: "ok", data: await this.hass.callWS({ type }) };
      } catch (error) {
        return { status: "error", error_type: error?.name || "Error" };
      }
    };
    const [site, power, meter, provider, grid, forecast, evidence] = await Promise.all([
      call("elrakning/site_identity"),
      call("elrakning/power_state"),
      call("elrakning/meter_state"),
      call("elrakning/electricity_provider_state"),
      call("elrakning/grid/state"),
      call("elrakning/solar_forecast_state"),
      call("elrakning/solar_evidence_state"),
    ]);
    const siteData = site.data || {};
    const currentSiteId = siteData.current_site?.site_id || siteData.site_id || null;
    const allSites = Array.isArray(siteData.available_sites) ? siteData.available_sites : [];
    const foreignSiteIds = allSites
      .map((item) => item?.site_id)
      .filter((siteId) => siteId && siteId !== currentSiteId);
    const currentPayload = { power: power.data, meter: meter.data, provider: provider.data, grid: grid.data, forecast: forecast.data, evidence: evidence.data };
    const currentPayloadText = JSON.stringify(currentPayload);
    const ledger = Array.isArray(siteData.source_ledger) ? siteData.source_ledger : [];
    const foreignGenerationIds = ledger
      .filter((item) => item?.site_id && item.site_id !== currentSiteId)
      .map((item) => item.generation_id)
      .filter(Boolean);

    return sanitizeDebugData({
      board: {
        version: this.version,
        generated_at: new Date().toISOString(),
        runtime_status: siteData.runtime_status || null,
      },
      site: {
        current_site: siteData.current_site || siteData.site || null,
        available_sites: allSites,
        site_configured: siteData.site_configured ?? null,
        current_site_id: currentSiteId,
        current_site_name: siteData.current_site?.name || siteData.site?.name || null,
      },
      source_ledger: {
        current_site_logical_roles: siteData.logical_roles || [],
        current_site_source_ledger: siteData.source_ledger || [],
        current_site_ledger_count: ledger.length,
      },
      power: power.data,
      meter: meter.data,
      provider: provider.data,
      price: {
        binding: this._priceBinding || null,
        coordinator_state: this.priceData,
        source_state: this._priceState || null,
      },
      solar_context: {
        forecast: forecast.data,
        weather: this._powerHistory?.solar_weather || null,
        pvgis: this._powerHistory?.solar_pvgis || null,
        open_meteo: this._powerHistory?.solar_open_meteo || null,
        shadow: this._powerHistory?.solar_shadow || null,
        evidence: evidence.data || this._powerHistory?.solar_evidence || null,
      },
      battery: {
        configured: Boolean(power.data?.battery_power_entity || power.data?.soc_entity || power.data?.capacity_entity),
        power: { charging_kw: power.data?.charging_kw ?? null, discharging_kw: power.data?.discharging_kw ?? null },
        soc_percent: power.data?.soc_percent ?? null,
        capacity_kwh: power.data?.capacity_kwh ?? null,
      },
      cost: {
        configured: this._invoiceEstimateRaw != null,
        invoice_estimate: this._invoiceEstimateRaw || null,
        billing_source: this._billingHistory?.source || null,
        billing_history_loaded: Boolean(this._billingHistory),
      },
      frontend: {
        house: this.host.querySelector('[data-live-power-tile="house"]')?._livePowerRaw || null,
        solar: this.host.querySelector('[data-live-power-tile="solar"]')?._livePowerRaw || null,
        grid: this.host.querySelector('[data-live-power-tile="grid"]')?._livePowerRaw || null,
        battery: this.host.querySelector('[data-live-power-tile="battery"]')?._livePowerRaw || null,
        price: { status: this.priceData?.error || "available", period_count: this.priceData?.periods?.length || 0 },
        elhandel: this._electricityProviderState,
        elnat: this._eonGridState,
        cost: this._invoiceEstimateRaw || null,
      },
      diagnostics: {
        entries: this._diagnosticEntries || [],
        current_payload_contains_foreign_site_ids: foreignSiteIds.filter((siteId) => currentPayloadText.includes(siteId)),
      },
      site_isolation_check: {
        current_site_id: currentSiteId,
        foreign_site_ids_seen: foreignSiteIds.filter((siteId) => currentPayloadText.includes(siteId)),
        foreign_source_generation_ids_seen: foreignGenerationIds,
        foreign_binding_fingerprints_seen: [],
      },
      endpoints: { site, power, meter, provider, grid, forecast, evidence },
    });
  }

  _bindBoardDataDialog() {
    const open = this.host.querySelector("[data-board-data-toggle]");
    const dialog = this.host.querySelector("[data-board-data-dialog]");
    const text = this.host.querySelector("[data-board-data-text]");
    const copy = this.host.querySelector("[data-board-data-copy]");
    const close = this.host.querySelector("[data-board-data-close]");
    if (!open || !dialog || !text || !copy || !close) return;
    const dismiss = () => { dialog.hidden = true; };
    open.addEventListener("click", async () => {
      dialog.hidden = false;
      text.textContent = "Hämtar data …";
      copy.disabled = true;
      try {
        text.textContent = JSON.stringify(await this._buildBoardDataSnapshot(), null, 2);
        copy.disabled = false;
      } catch {
        text.textContent = JSON.stringify({ status: "error", error_type: "snapshot_failed" }, null, 2);
      }
    });
    copy.addEventListener("click", async () => {
      try {
        await this._copyText(text.textContent);
        copy.textContent = "Kopierat";
        window.setTimeout(() => { copy.textContent = "Kopiera"; }, 1500);
      } catch {
        copy.textContent = "Kunde inte kopiera";
      }
    });
    close.addEventListener("click", dismiss);
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dismiss(); });
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
    const eonSource = this.host.querySelector("[data-eon-grid-source]");
    const meterSource = this.host.querySelector("[data-meter-source]");
    const priceSource = this.host.querySelector('[data-card-source="price"]');
    const solarEvidenceCard = this.host.querySelector("[data-solar-evidence-card]");
    const benchmarkEvidenceCard = this.host.querySelector("[data-benchmark-evidence-card]");
    const liveSources = this.host.querySelectorAll("[data-live-power-source]");
    const diagnostics = this.host.querySelector("[data-diagnostics-card]");
    const phaseCopy = this.host.querySelector("[data-phase-history-copy]");
    const cardSources = this.host.querySelectorAll("[data-card-source]");
    if (source) source.hidden = !this._debugEnabled;
    if (eonSource) eonSource.hidden = !this._debugEnabled || this._eonGridState?.configured !== true;
    if (meterSource) meterSource.hidden = !this._debugEnabled || this._meterState?.configured !== true;
    if (priceSource) priceSource.hidden = !this._debugEnabled;
    applySolarEvidenceVisibility(solarEvidenceCard, this._debugEnabled, this._powerHistory?.solar_evidence?.available);
    applySolarEvidenceVisibility(benchmarkEvidenceCard, this._debugEnabled, this._benchmarkEvidence?.available);
    liveSources.forEach((button) => { button.hidden = !this._debugEnabled; });
    if (diagnostics) diagnostics.hidden = !this._debugEnabled;
    if (phaseCopy) phaseCopy.hidden = !this._debugEnabled || this.host.querySelector("[data-phase-history-card]")?.hidden !== false;
    cardSources.forEach((button) => {
      const card = button.closest(".card");
      button.hidden = !this._debugEnabled || Boolean(card?.hidden);
    });
    this._updateLivePowerCardInteractivity();
  }

  _bindMeterDialog() {
    const opens = this.host.querySelectorAll("[data-meter-configure]");
    const dialog = this.host.querySelector("[data-meter-dialog]");
    const cancel = this.host.querySelector("[data-meter-cancel]");
    const save = this.host.querySelector("[data-meter-save]");
    const clear = this.host.querySelector("[data-meter-clear]");
    const clearLast = this.host.querySelector("[data-meter-clear-last]");
    const result = this.host.querySelector("[data-meter-result]");
    const selectorsElement = this.host.querySelector("[data-meter-selectors]");
    const consumptionSelectorElement = this.host.querySelector("[data-meter-consumption-selector]");
    const invertToggle = this.host.querySelector("[data-meter-invert-power]");
    const title = this.host.querySelector("#meter-title");
    const loadSection = this.host.querySelector(".meter-load-section");
    if (!opens.length || !dialog || !cancel || !save || !result || !selectorsElement || !consumptionSelectorElement || !invertToggle) return;
    let mode = "meter";
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
    const applyMode = () => {
      const isHouseLoad = mode === "house_load";
      if (title) title.textContent = isHouseLoad ? "Husets last" : "Elmätare";
      invertToggle.closest("label")?.toggleAttribute("hidden", isHouseLoad);
      selectorsElement.hidden = isHouseLoad;
      if (loadSection) loadSection.hidden = !isHouseLoad;
      clear?.toggleAttribute("hidden", isHouseLoad);
      clearLast?.toggleAttribute("hidden", !isHouseLoad);
    };
    const selectorConfig = (field) => {
      if (field !== "energy_import_entity" && field !== "energy_export_entity") return { domain: "sensor" };
      const energyEntities = Object.entries(this.hass?.states || {})
        .filter(([, state]) => state?.attributes?.device_class === "energy"
          && ["Wh", "kWh", "MWh"].includes(state?.attributes?.unit_of_measurement))
        .map(([entityId]) => entityId);
      return { domain: "sensor", device_class: "energy", entity_id: energyEntities };
    };
    const buildMeterSelector = (labelText, field, value) => {
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
      return label;
    };
    const renderEntitySelector = (container, labelText, field, value) => {
      container.replaceChildren(buildMeterSelector(labelText, field, value));
    };
    const renderSelectors = (mapping) => {
      selectorsElement.replaceChildren(...fields.map(([labelText, field]) =>
        buildMeterSelector(labelText, field, mapping?.[field] || undefined)));
    };
    const renderConsumptionSelector = (state) => {
      renderEntitySelector(consumptionSelectorElement, "Husets last", "consumption_entity", state?.consumption_entity);
    };
    const currentPowerMapping = () => {
      const current = this._powerState || {};
      return {
        solar_entities: Array.isArray(current.solar_entities) ? [...current.solar_entities] : [],
        solar_array_metadata: current.solar_array_metadata ? structuredClone(current.solar_array_metadata) : {},
        consumption_entity: current.consumption_entity || "",
        charging_entity: current.charging_entity || "",
        discharging_entity: current.discharging_entity || "",
        battery_power_entity: current.battery_power_entity || "",
        invert_battery_power: current.invert_battery_power === true,
        soc_entity: current.soc_entity || "",
        capacity_entity: current.capacity_entity || "",
      };
    };
    const openDialog = async (event) => {
      mode = event.currentTarget.dataset.meterConfigure || "meter";
      applyMode();
      dialog.hidden = false;
      save.disabled = true;
      result.textContent = "Hämtar sparad konfiguration …";
      try {
        if (mode === "house_load") {
          const request = this._beginPowerStateRequest();
          const powerResponse = await request.hass.callWS({ type: "elrakning/power_state" });
          if (!this._isCurrentPowerStateContext(request)) return;
          const state = this._applyPowerStateResponse(request, powerResponse) ? powerResponse : this._powerState;
          renderConsumptionSelector(state);
        } else {
          const meterResponse = await this.hass.callWS({ type: "elrakning/meter_state" });
          this._applyMeterState(meterResponse);
          renderSelectors(meterResponse);
          invertToggle.checked = meterResponse.invert_power === true;
        }
        result.textContent = "Välj de entiteter som ska användas.";
        save.disabled = false;
      } catch {
        selectorsElement.replaceChildren();
        consumptionSelectorElement.replaceChildren();
        result.textContent = "Mätar- eller lastkonfigurationen kunde inte hämtas.";
      }
    };
    opens.forEach((open) => open.addEventListener("click", openDialog));
    save.addEventListener("click", async () => {
      if (mode === "house_load") {
        const powerMapping = currentPowerMapping();
        powerMapping.consumption_entity = consumptionSelectorElement.querySelector('[data-meter-field="consumption_entity"]')?.value || "";
        save.disabled = true;
        result.textContent = "Sparar …";
        try {
          const response = await this.hass.callWS({ type: "elrakning/power_save", ...powerMapping });
          if (!response?.success) throw new Error(response?.error || "power_save_failed");
          this._applyAuthoritativePowerState(response);
          await this.loadPowerHistory();
          close();
        } catch (error) {
          const details = this._websocketErrorDetails(error);
          save.disabled = false;
          result.textContent = `Husets last kunde inte sparas: ${details.code}: ${details.message}`;
        }
        return;
      }
      await this._recordMeterDiagnostic("INFO", "meter_save_clicked", "Meter save button clicked");
      const mapping = Object.fromEntries(fields.map(([, field]) => {
        const value = selectorsElement.querySelector(`[data-meter-field="${field}"]`)?.value;
        return [field, typeof value === "string" && value ? value : ""];
      }));
      mapping.invert_power = invertToggle.checked;
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
        this.loadBillingHistory();
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
      if (mode !== "meter") return;
      if (!window.confirm("Är du säker? Alla valda mätare tas bort.")) return;
      try {
        const response = await this.hass.callWS({ type: "elrakning/meter_store_clear" });
        if (!response.success) throw new Error(response.error || "meter_store_clear_failed");
        this._applyMeterState(response);
        this.loadBillingHistory();
        renderSelectors(response);
        invertToggle.checked = false;
        result.textContent = "Elmätare rensad.";
      } catch (error) {
        const details = this._websocketErrorDetails(error);
        result.textContent = `Elmätaren kunde inte rensas: ${details.code}: ${details.message}`;
      }
    });
    clearLast?.addEventListener("click", async () => {
      if (mode !== "house_load") return;
      if (!window.confirm("Är du säker? Husets last rensas.")) return;
      const mapping = currentPowerMapping();
      mapping.consumption_entity = "";
      save.disabled = true;
      result.textContent = "Rensar last …";
      try {
        this._resetPowerLivePoints();
        const response = await this.hass.callWS({ type: "elrakning/power_save", ...mapping });
        if (!response?.success) throw new Error(response?.error || "power_clear_failed");
        this._applyAuthoritativePowerState(response);
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
    const title = this.host.querySelector("#power-title");
    const selectorsElement = this.host.querySelector("[data-power-selectors]");
    const result = this.host.querySelector("[data-power-result]");
    const solarAnalysisStatus = this.host.querySelector("[data-power-solar-analysis-status]");
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
      if (solarAnalysisStatus) {
        const sunAvailable = this.hass?.states?.["sun.sun"] && !["unknown", "unavailable"].includes(this.hass.states["sun.sun"].state);
        solarAnalysisStatus.hidden = mode !== "solar" || sunAvailable;
        solarAnalysisStatus.textContent = mode === "solar" && !sunAvailable
          ? "Sun-integrationen krävs för solanalys. Lägg till Sun under Inställningar → Enheter och tjänster."
          : "";
      }
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
        if (multiple) {
          const metadata = state?.solar_array_metadata?.[current] || {};
          const metadataGrid = document.createElement("div");
          metadataGrid.className = "solar-array-metadata";
          [["Installerad effekt (kWp)", "capacity_kwp", "number"], ["Antal paneler", "panel_count", "number"], ["Lutning (°)", "tilt_deg", "number"], ["Azimut (°)", "azimuth_deg", "number"]].forEach(([text, key, type]) => {
            const metadataLabel = document.createElement("label");
            metadataLabel.textContent = text;
            const input = document.createElement("input");
            input.type = type;
            input.step = key === "panel_count" ? "1" : "any";
            input.min = key === "capacity_kwp" || key === "panel_count" ? "0" : "0";
            if (key === "tilt_deg") input.max = "90";
            if (key === "azimuth_deg") input.max = "360";
            input.dataset.solarMetadataField = key;
            input.value = metadata[key] ?? "";
            metadataLabel.append(input);
            metadataGrid.append(metadataLabel);
          });
          label.append(metadataGrid);
        }
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
      if (title) title.textContent = ({ solar: "Konfigurera sol", consumption: "Konfigurera last", battery: "Konfigurera batteri" })[mode] || "Konfigurera energi";
      if (clear) clear.textContent = ({ solar: "Rensa sol", consumption: "Rensa last", battery: "Rensa batteri" })[mode];
      save.disabled = true;
      result.textContent = "Hämtar sparad konfiguration …";
      try {
        const request = this._beginPowerStateRequest();
        const state = await request.hass.callWS({ type: "elrakning/power_state" });
        if (!this._isCurrentPowerStateContext(request)) return;
        const currentState = this._applyPowerStateResponse(request, state) ? state : this._powerState;
        solarCount = Math.max(2, currentState?.solar_entities?.length || 0);
        batteryMode = currentState?.battery_power_entity ? "combined" : "separate";
        batteryModeOptions.forEach((option) => { option.checked = option.value === batteryMode; });
        if (invertBatteryToggle) invertBatteryToggle.checked = currentState?.invert_battery_power === true;
        renderSelectors(currentState);
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
        solar_array_metadata: current.solar_array_metadata ? structuredClone(current.solar_array_metadata) : {},
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
        mapping.solar_array_metadata = {};
        selectorsElement.querySelectorAll('[data-power-field="solar_entities"]').forEach((selector) => {
          const entityId = selector.value || "";
          if (!entityId) return;
          const row = selector.closest(".meter-selector-label");
          const metadata = Object.fromEntries([...row.querySelectorAll("[data-solar-metadata-field]")]
            .map((input) => [input.dataset.solarMetadataField, input.value])
            .filter(([, value]) => value !== ""));
          if (Object.keys(metadata).length) mapping.solar_array_metadata[entityId] = metadata;
        });
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
        this._applyAuthoritativePowerState(response);
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
        solar_array_metadata: mode === "solar" ? {} : (current.solar_array_metadata ? structuredClone(current.solar_array_metadata) : {}),
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
        this._applyAuthoritativePowerState(response);
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
    this._powerState = state ? recomputeDailyEnergyState(state, this._powerHistory, this._meterPowerHistory) : null;
    const solarConfigured = Array.isArray(this._powerState?.solar_entities) && this._powerState.solar_entities.length > 0;
    const batteryConfigured = Boolean(this._powerState?.charging_entity || this._powerState?.discharging_entity || this._powerState?.soc_entity || this._powerState?.capacity_entity);
    const batteryPowerConfigured = Boolean(this._powerState?.battery_power_entity);
    const batteryIsConfigured = batteryConfigured || batteryPowerConfigured;
    const values = {
      solar: solarConfigured ? [["Effekt just nu", this._powerState.solar_kw, "kW"]] : [],
      battery: batteryIsConfigured ? [["Laddning", this._powerState.charging_kw, "kW"], ["Urladdning", this._powerState.discharging_kw, "kW"]] : [],
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
        const label = document.createElement("strong");
        label.textContent = labelText;
        const output = document.createElement("span");
        output.textContent = `${this._formatNumber(value)} ${unit}`;
        summaryNodes.push(label, output);
      });
      summary.replaceChildren(...summaryNodes);
      summary.hidden = validRows.length === 0;
    }
    this._renderLivePowerRow();
    this._renderMergedMeterSummary();
    this._renderDashboardCardVisibility();
    this._renderSocChart();
    this._renderBatteryHistoryCard();
    this._renderSolarHistoryCard();
  }

  _beginPowerStateRequest() {
    return {
      requestGeneration: ++this._powerStateRequestGeneration,
      mutationGeneration: this._powerStateMutationGeneration,
      lifecycleGeneration: this._powerStateLifecycleGeneration,
      hass: this.hass,
      connection: this.hass?.connection || null,
    };
  }

  _isCurrentPowerStateRequest(request) {
    return this._isCurrentPowerStateContext(request)
      && request.requestGeneration === this._powerStateRequestGeneration
      && request.mutationGeneration === this._powerStateMutationGeneration;
  }

  _isCurrentPowerStateContext(request) {
    return request
      && request.lifecycleGeneration === this._powerStateLifecycleGeneration
      && request.connection === (this.hass?.connection || null)
      && request.connection === this._eventConnection;
  }

  _applyPowerStateResponse(request, state) {
    if (!this._isCurrentPowerStateRequest(request)) return false;
    this._applyPowerState(state);
    return true;
  }

  _applyAuthoritativePowerState(state) {
    this._powerStateMutationGeneration += 1;
    this._applyPowerState(state);
  }

  _calculatePowerEnergy(seriesKey) {
    const points = this._powerHistory?.series?.[seriesKey]?.points;
    const now = new Date();
    const window = stockholmDayWindow(now);
    return integratePowerHistoryKwh(points, window.start, window.end, now);
  }

  _calculateMeterEnergy(field) {
    const points = this._meterPowerHistory?.points;
    if (!Array.isArray(points) || points.length < 2) return null;
    const now = new Date();
    const window = stockholmDayWindow(now);
    return integrateMeterHistoryKwh(points, field, window.start, window.end, now);
  }

  _refreshPowerEnergyState() {
    if (!this._powerState) return;
    this._applyPowerState(this._powerState);
  }

  _refreshDailyEnergyStateFromAcceptedHistory() {
    if (!this._powerState) return false;
    this._powerState = recomputeDailyEnergyState(this._powerState, this._powerHistory, this._meterPowerHistory);
    this._renderDailyEnergyCard();
    return true;
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
    if (!summary) {
      this._renderDailyEnergyCard();
      return;
    }
    const rows = [];
    if (loadConfigured) {
      rows.push(["Husets last", displayPowerValue(power.consumption_kw), "kW"]);
    }
    if (meterConfigured) {
      rows.push(["Nät just nu", displayPowerValue(meter.power_kw), "kW"]);
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

  _rebuildLivePowerMaxima() {
    const rebuilt = buildDailyObservedMaxima(this._powerHistory, this._meterPowerHistory, new Date());
    this._livePowerMaxima = rebuilt;
    this._renderLivePowerRow();
  }

  _renderLivePowerRow() {
    const row = this.host.querySelector("[data-live-power-row]");
    if (!row) return;
    const now = new Date();
    const date = now.toLocaleDateString("sv-SE");
    if (this._livePowerMaxima.date !== date) {
      this._livePowerMaxima = { date, house: 0, solar: 0, grid: 0, battery: 0 };
    }
    const meterState = {
      ...(this._meterState || {}),
      facility: this._eonGridState?.facility || this._meterState?.facility,
    };
    const currentTiles = buildLivePowerTiles(this._powerState || {}, meterState);
    for (const key of ["house", "solar", "grid", "battery"]) {
      if (Number.isFinite(currentTiles[key].value)) this._livePowerMaxima[key] = Math.max(this._livePowerMaxima[key], Math.abs(currentTiles[key].value));
    }
    const tiles = buildLivePowerTiles(this._powerState || {}, meterState, this._livePowerMaxima);
    for (const [key, tile] of Object.entries(tiles)) {
      const element = row.querySelector(`[data-live-power-tile="${key}"]`);
      if (!element) continue;
      const value = element.querySelector("[data-live-power-value]");
      const status = element.querySelector("[data-live-power-status]");
      const fill = element.querySelector("[data-live-power-fill]");
      if (value) value.textContent = Number.isFinite(tile.value) ? `${this._formatNumber(tile.value)} kW` : "—";
      if (status) status.textContent = tile.status;
      if (fill) {
        fill.style.backgroundColor = chartColor(tile.colorKey);
        fill.style.width = `${tile.fillPercent}%`;
      }
      if (status) status.style.color = Number.isFinite(tile.value) && tile.colorKey !== "neutral"
        ? chartColor(tile.colorKey)
        : "";
      const scale = element.querySelector("[data-live-power-scale]");
      if (scale) scale.textContent = `${this._formatNumber(tile.scaleMax)} kW`;
      if (key === "grid") {
        const gridMeta = element.querySelector("[data-live-power-grid-meta]");
        if (gridMeta) {
          const meta = Number.isFinite(tile.maxPhaseCurrentA) && Number.isFinite(tile.fuseAmpere)
            ? `${this._formatNumber(tile.maxPhaseCurrentA)} / ${this._formatNumber(tile.fuseAmpere)} A`
            : Number.isFinite(tile.fuseAmpere) ? `${this._formatNumber(tile.fuseAmpere)} A` : "";
          gridMeta.textContent = meta;
          gridMeta.hidden = !meta;
        }
        const fuseStatus = element.querySelector("[data-live-power-grid-fuse-status]");
        if (fuseStatus) {
          fuseStatus.textContent = "";
          fuseStatus.hidden = true;
        }
      }
      element.dataset.livePowerDirection = tile.direction || "idle";
      element._livePowerRaw = buildLivePowerProvenance(
        key,
        tile,
        this._powerState || {},
        meterState,
        this._meterPowerHistory || {},
        this._powerHistory || {},
        this.hass?.states || {},
        this._livePowerMaxima || {},
      );
      if (key === "grid") {
        element._livePowerRaw.display.direction = tile.direction;
        element._livePowerRaw.presentation.direction = tile.direction;
        element._livePowerRaw.presentation.fuse_ampere = tile.fuseAmpere;
        element._livePowerRaw.presentation.phase_current_a = tile.phaseCurrentA;
        element._livePowerRaw.presentation.fuse_utilization_percent = tile.fuseUtilizationPercent;
      element._livePowerRaw.history.daily_phase_max = this._meterPowerHistory?.daily_phase_max || {};
      element._livePowerRaw.history.daily_max_phase = this._meterPowerHistory?.daily_max_phase || null;
      }
    }
  }

  _bindLivePowerCards() {
    this._updateLivePowerCardInteractivity();
    this._renderLivePowerRow();
  }

  _updateLivePowerCardInteractivity() {
    for (const tile of this.host.querySelectorAll("[data-live-power-tile], [data-invoice-estimate-card]")) {
      tile.querySelector(".live-power-debug-footer")?.classList.toggle("visible", this._debugEnabled);
    }
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
    const exportKwh = this._calculateMeterEnergy("export_kw");
    const importKwh = this._calculateMeterEnergy("import_kw");
    const dailyEnergyDiagnostic = JSON.stringify({
      power_date: this._powerHistory?.date || null,
      meter_date: this._meterPowerHistory?.date || null,
      power_solar_points: this._powerHistory?.series?.solar?.points?.length || 0,
      power_consumption_points: this._powerHistory?.series?.consumption?.points?.length || 0,
      meter_points: this._meterPowerHistory?.points?.length || 0,
      solar_energy_kwh: Number.isFinite(power.solar_energy_kwh) ? power.solar_energy_kwh : null,
      consumption_energy_kwh: Number.isFinite(power.consumption_energy_kwh) ? power.consumption_energy_kwh : null,
      import_kwh: Number.isFinite(importKwh) ? importKwh : null,
      export_kwh: Number.isFinite(exportKwh) ? exportKwh : null,
    });
    if (dailyEnergyDiagnostic !== this._dailyEnergyDiagnosticSignature && (importKwh === null || exportKwh === null)) {
      this._dailyEnergyDiagnosticSignature = dailyEnergyDiagnostic;
      this._recordPowerFlowDiagnostic("daily_energy_inputs", {
        inputs: JSON.parse(dailyEnergyDiagnostic),
        reason: "meter_energy_unavailable",
      });
    }
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

  _buildCardSourceData(cardSource) {
    const power = this._powerState || {};
    const meter = this._meterState || {};
    const powerHistory = this._powerHistory || {};
    const meterHistory = this._meterPowerHistory || {};
    const sourceEntities = {
      solar: Array.isArray(power.solar_entities) ? [...power.solar_entities] : [],
      consumption: power.consumption_entity || null,
      charging: power.charging_entity || null,
      discharging: power.discharging_entity || null,
      soc: power.soc_entity || null,
      capacity: power.capacity_entity || null,
      meter_power: meter.power_entity || null,
      meter_import: meter.energy_import_entity || null,
      meter_export: meter.energy_export_entity || null,
    };
    if (cardSource === "energy") {
      const exportKwh = this._calculateMeterEnergy("export_kw");
      const importKwh = this._calculateMeterEnergy("import_kw");
      const solarBalance = buildEnergyBalance(power.solar_energy_kwh, exportKwh);
      const consumptionBalance = buildEnergyBalance(power.consumption_energy_kwh, importKwh);
      return {
        card: "energy",
        source_entities: sourceEntities,
        raw: {
          power_history: { solar: powerHistory.series?.solar || null, consumption: powerHistory.series?.consumption || null },
          meter_state: { energy_import_kwh: meter.energy_import_kwh, energy_export_kwh: meter.energy_export_kwh, energy_import_valid: meter.energy_import_valid, energy_export_valid: meter.energy_export_valid },
        },
        normalized: {
          solar_energy_today_kwh: power.solar_energy_kwh,
          house_consumption_today_kwh: power.consumption_energy_kwh,
          grid_import_today_kwh: importKwh,
          grid_export_today_kwh: exportKwh,
        },
        derived: {
          solar_local_kwh: solarBalance.local,
          solar_export_kwh: solarBalance.external,
          solar_local_percent: solarBalance.localPercent,
          solar_export_percent: solarBalance.externalPercent,
          consumption_local_kwh: consumptionBalance.local,
          consumption_import_kwh: consumptionBalance.external,
          consumption_local_percent: consumptionBalance.localPercent,
          consumption_import_percent: consumptionBalance.externalPercent,
        },
        timestamps: { history_date: powerHistory.date, meter_history_date: meterHistory.date },
      };
    }
    if (cardSource === "soc") {
      const points = Array.isArray(powerHistory.series?.soc?.points) ? powerHistory.series.soc.points : [];
      const lastPoint = points.at(-1) || null;
      return {
        card: "soc",
        source_entities: sourceEntities,
        raw: { current_state: power.soc_percent, history_points: points },
        normalized: { current_percent: Number.isFinite(power.soc_percent) ? power.soc_percent : lastPoint?.value_percent, canonical_points: points },
        derived: { estimated_segments: [], gap_count: points.filter((point) => point?.gap_before).length },
        provenance: { history_date: powerHistory.date, source: power.soc_entity ? "home_assistant" : null },
      };
    }
    if (cardSource === "battery-history") {
      const days = buildBatteryDailyHistory(
        powerHistory.series?.charging?.points,
        powerHistory.series?.discharging?.points,
        Number(power.capacity_kwh),
      );
      return {
        card: "battery-history",
        source_entities: sourceEntities,
        raw: {
          charging_points: powerHistory.series?.charging?.points || [],
          discharging_points: powerHistory.series?.discharging?.points || [],
          soc_points: powerHistory.series?.soc?.points || [],
          capacity_kwh: power.capacity_kwh,
        },
        normalized: { days },
        derived: { daily_buckets: days },
        provenance: { history_date: powerHistory.date },
      };
    }
    if (cardSource === "solar-history") {
      const days = buildSolarDailyHistory(
        powerHistory.series?.solar?.points,
        powerHistory.solar_forecast_baselines,
        new Date(),
        7,
        powerHistory.solar_forecast,
        powerHistory.solar_shadow?.days,
      );
      return {
        card: "solar-history",
        source_entities: sourceEntities,
        raw: {
          production_points: powerHistory.series?.solar?.points || [],
          forecast_baselines: powerHistory.solar_forecast_baselines || {},
          live_forecast: powerHistory.solar_forecast || null,
          solar_evidence: powerHistory.solar_evidence || { available: false, days: [] },
          weather: powerHistory.solar_weather || null,
          sun: powerHistory.solar_sun || null,
        },
        normalized: { days },
        derived: { daily_buckets: days },
        provenance: { history_date: powerHistory.date, source: sourceEntities.solar.length ? "home_assistant" : null },
      };
    }
    if (cardSource === "solar-evidence") {
      return {
        card: "solar-evidence",
        site_id: this._siteState?.site_id || this._siteState?.current_site?.site_id || null,
        evidence: powerHistory.solar_evidence || { available: false, days: [] },
      };
    }
    if (cardSource === "benchmark-evidence") {
      return {
        card: "benchmark-evidence",
        site_id: this._benchmarkEvidence?.site_id || this._siteState?.site_id || this._siteState?.current_site?.site_id || null,
        evidence: this._benchmarkEvidence || { available: false },
      };
    }
    return null;
  }

  _renderBatteryHistoryCard() {
    const card = this.host.querySelector('[data-power-card="battery-history"]');
    const chart = this.host.querySelector("[data-battery-history-chart]");
    if (!card || !chart) return;
    const power = this._powerState || {};
    const configured = Boolean(power.charging_entity || power.discharging_entity || power.battery_power_entity);
    card.hidden = !configured;
    chart.hidden = !configured;
    if (!configured) {
      chart.replaceChildren();
      return;
    }
    const capacity = Number(power.capacity_kwh);
    const days = buildBatteryDailyHistory(
      this._powerHistory?.series?.charging?.points,
      this._powerHistory?.series?.discharging?.points,
      capacity,
    );
    const values = days.flatMap((day) => [day.chargingKwh, day.dischargingKwh]).filter((value) => Number.isFinite(value));
    const maximum = values.length ? Math.max(...values) : 0;
    if (!values.length) {
      chart.textContent = "Ingen batterihistorik tillgänglig";
      return;
    }
    const width = 960;
    const height = 320;
    const plot = { left: 42, right: 8, top: 12, bottom: 50 };
    const plotWidth = width - plot.left - plot.right;
    const plotHeight = height - plot.top - plot.bottom;
    const range = Number.isFinite(capacity) && capacity > 0 ? capacity : Math.max(1, maximum);
    const y = (value) => plot.top + plotHeight - (Math.max(0, Number(value) || 0) / range) * plotHeight;
    const groupWidth = plotWidth / days.length;
    const barWidth = Math.min(24, groupWidth * .24);
    const barGap = Math.min(5, groupWidth * .05);
    const groupX = (index) => plot.left + groupWidth * index + groupWidth / 2;
    const formatEnergy = (value) => Number.isFinite(value) ? `${this._formatNumber(value)} kWh` : "—";
    const yLabels = [range, range / 2, 0];
    const grid = [0, range / 2, range].map((level) => `<line class="battery-history-gridline" x1="${plot.left}" y1="${y(level)}" x2="${width - plot.right}" y2="${y(level)}" />`).join("");
    const bars = days.map((day, index) => {
      const center = groupX(index);
      const chargingHeight = plot.top + plotHeight - y(day.chargingKwh);
      const dischargingHeight = plot.top + plotHeight - y(day.dischargingKwh);
      return `<g class="battery-history-day" data-battery-history-index="${index}"><rect class="battery-history-bar charging" fill="${chartColor("charging")}" x="${center - barGap / 2 - barWidth}" y="${y(day.chargingKwh)}" width="${barWidth}" height="${chargingHeight}" /><rect class="battery-history-bar discharging" fill="${chartColor("discharging")}" x="${center + barGap / 2}" y="${y(day.dischargingKwh)}" width="${barWidth}" height="${dischargingHeight}" /></g>`;
    }).join("");
    const yLabelMarkup = yLabels.map((level, index) => `<span class="battery-history-axis-label ${index === 0 ? "top" : index === 1 ? "middle" : "bottom"}">${this._formatNumber(level)}</span>`).join("");
    const xLabelMarkup = days.map((day, index) => `<span class="battery-history-x-label" style="left: ${(index + .5) / days.length * 100}%"><span class="battery-history-day-label">${day.label}</span><span class="battery-history-utilization">${Number.isFinite(day.utilizationPercent) ? `${this._formatNumber(day.utilizationPercent)} %` : "—"}</span></span>`).join("");
    chart.innerHTML = `<div class="battery-history-y-label-rail" aria-hidden="true">${yLabelMarkup}</div><svg class="battery-history-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Batteriets laddning och urladdning de senaste sju dagarna">${grid}${bars}</svg><div class="battery-history-x-label-rail" aria-hidden="true">${xLabelMarkup}</div><div class="soc-tooltip" hidden></div>`;
    const svg = chart.querySelector(".battery-history-svg");
    const tooltip = chart.querySelector(".soc-tooltip");
    let hoveredDay = null;
    const clear = () => {
      tooltip.hidden = true;
      hoveredDay?.classList.remove("hovered");
      hoveredDay = null;
    };
    const show = (event, index) => {
      const day = days[index];
      const group = svg.querySelector(`[data-battery-history-index="${index}"]`);
      if (!day || !group) return;
      if (hoveredDay !== group) {
        hoveredDay?.classList.remove("hovered");
        group.classList.add("hovered");
        hoveredDay = group;
      }
      renderSharedTooltip(tooltip, {
        fields: [
          { label: "Laddat", value: day.chargingKwh, formatted: formatEnergy(day.chargingKwh), rawValue: day.chargingKwh },
          { label: "Urladdat", value: day.dischargingKwh, formatted: formatEnergy(day.dischargingKwh), rawValue: day.dischargingKwh },
        ],
      });
      tooltip.hidden = false;
      positionChartTooltip(chart, tooltip, event.clientX, event.clientY, [], this._tooltipOrbit);
    };
    svg.addEventListener("pointermove", (event) => {
      const group = event.target.closest?.("[data-battery-history-index]");
      if (group) show(event, Number(group.dataset.batteryHistoryIndex));
    });
    svg.addEventListener("pointerleave", clear);
    svg.addEventListener("pointercancel", clear);
  }

  _renderSolarHistoryCard() {
    const card = this.host.querySelector('[data-power-card="solar-history"]');
    const chart = this.host.querySelector("[data-solar-history-chart]");
    if (!card || !chart) return;
    const power = this._powerState || {};
    const configured = Array.isArray(power.solar_entities) && power.solar_entities.length > 0;
    card.hidden = !configured;
    chart.hidden = !configured;
    if (!configured) {
      chart.replaceChildren();
      return;
    }
    const days = buildSolarDailyHistory(
      this._powerHistory?.series?.solar?.points,
      this._powerHistory?.solar_forecast_baselines,
      new Date(),
      7,
      this._powerHistory?.solar_forecast,
      this._powerHistory?.solar_shadow?.days,
    );
    const values = days.flatMap((day) => [day.producedKwh, day.forecastKwh]).filter((value) => Number.isFinite(value));
    if (!values.length) {
      chart.textContent = "Ingen solhistorik tillgänglig";
      return;
    }
    const niceMax = (value) => {
      const exponent = 10 ** Math.floor(Math.log10(Math.max(value, 1)));
      const normalized = value / exponent;
      const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
      return step * exponent;
    };
    const width = 960;
    const height = 320;
    const plot = { left: 42, right: 8, top: 12, bottom: 50 };
    const plotWidth = width - plot.left - plot.right;
    const plotHeight = height - plot.top - plot.bottom;
    const range = niceMax(Math.max(...values));
    const y = (value) => plot.top + plotHeight - (Math.max(0, Number(value) || 0) / range) * plotHeight;
    const groupWidth = plotWidth / days.length;
    const barWidth = Math.min(34, groupWidth * .5);
    const referenceBarWidth = barWidth;
    const groupX = (index) => plot.left + groupWidth * index + groupWidth / 2;
    const grid = [0, range / 2, range].map((level) => `<line class="solar-history-gridline" x1="${plot.left}" y1="${y(level)}" x2="${width - plot.right}" y2="${y(level)}" />`).join("");
    const bars = days.map((day, index) => {
      const center = groupX(index);
      const forecast = Number.isFinite(day.forecastKwh) && day.forecastKwh > 0
        ? `<rect class="solar-history-reference-bar" fill="${chartColor("socEstimated")}" x="${center - referenceBarWidth / 2}" y="${y(day.forecastKwh)}" width="${referenceBarWidth}" height="${plot.top + plotHeight - y(day.forecastKwh)}" />`
        : "";
      const actual = Number.isFinite(day.producedKwh)
        ? `<rect class="solar-history-bar" fill="${chartColor("solar")}" x="${center - barWidth / 2}" y="${y(day.producedKwh)}" width="${barWidth}" height="${plot.top + plotHeight - y(day.producedKwh)}" />`
        : "";
      return `<g class="solar-history-day" data-solar-history-index="${index}">${forecast}${actual}</g>`;
    }).join("");
    const yLabelMarkup = [range, range / 2, 0].map((level, index) => `<span class="solar-history-axis-label ${index === 0 ? "top" : index === 1 ? "middle" : "bottom"}">${this._formatNumber(level)}</span>`).join("");
    const evidenceDays = this._powerHistory?.solar_evidence?.days;
    const today = localDateKey(new Date());
    const xLabelMarkup = days.map((day, index) => {
      const evidenceStatus = solarEvidenceStatus(evidenceDays, day.date, today);
      const evidenceLabel = evidenceStatus === "✅" ? "Godkänd evidence" : evidenceStatus === "❌" ? "Exkluderad evidence" : "Evidence ej bedömd";
      return `<span class="solar-history-x-label" style="left: ${(index + .5) / days.length * 100}%"><span class="solar-history-day-label">${day.label}</span><span class="solar-history-utilization">${Number.isFinite(day.utilizationPercent) ? `${this._formatNumber(day.utilizationPercent)} %` : "—"}</span><span class="solar-history-evidence-status" title="${evidenceLabel}">${evidenceStatus}</span></span>`;
    }).join("");
    chart.innerHTML = `<div class="solar-history-y-label-rail" aria-hidden="true">${yLabelMarkup}</div><svg class="solar-history-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Solproduktion de senaste sju dagarna">${grid}${bars}</svg><div class="solar-history-x-label-rail" aria-hidden="true">${xLabelMarkup}</div><div class="soc-tooltip" hidden></div>`;
    const svg = chart.querySelector(".solar-history-svg");
    const tooltip = chart.querySelector(".soc-tooltip");
    let hoveredDay = null;
    const clear = () => {
      tooltip.hidden = true;
      hoveredDay?.classList.remove("hovered");
      hoveredDay = null;
    };
    const show = (event, index) => {
      const day = days[index];
      const group = svg.querySelector(`[data-solar-history-index="${index}"]`);
      if (!day || !group) return;
      hoveredDay?.classList.remove("hovered");
      group.classList.add("hovered");
      hoveredDay = group;
      renderSharedTooltip(tooltip, {
        fields: buildSolarHistoryTooltipFields(
          day,
          this._powerHistory?.solar_forecast,
          new Date(),
          this._powerHistory?.solar_weather,
          this._powerHistory?.solar_sun,
        ),
      });
      tooltip.hidden = false;
      positionChartTooltip(chart, tooltip, event.clientX, event.clientY, [], this._tooltipOrbit);
    };
    svg.addEventListener("pointermove", (event) => {
      const group = event.target.closest?.("[data-solar-history-index]");
      if (group) show(event, Number(group.dataset.solarHistoryIndex));
    });
    svg.addEventListener("pointerleave", clear);
    svg.addEventListener("pointercancel", clear);
  }

  _renderSolarEvidence() {
    const card = this.host.querySelector("[data-solar-evidence-card]");
    const tasks = this.host.querySelector("[data-solar-evidence-capture-tasks]");
    const summary = this.host.querySelector("[data-solar-evidence-summary]");
    const status = this.host.querySelector("[data-solar-evidence-status]");
    const list = this.host.querySelector("[data-solar-evidence-list]");
    const evidence = this._powerHistory?.solar_evidence;
    if (!card || !summary || !status || !list) return;
    const days = Array.isArray(evidence?.days) ? evidence.days : [];
    const captureTasks = formatSolarEvidenceCaptureTasks(evidence?.capture_tasks);
    const escape = (value) => String(value ?? "").replace(/[&<>\"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
    })[character]);
    if (tasks) {
      tasks.hidden = captureTasks.length === 0;
      tasks.innerHTML = captureTasks.map((task) => {
        const target = [task.target_date, task.target_site_ids.length ? `site ${task.target_site_ids.join(", ")}` : null].filter(Boolean).join(" · ");
        const times = [task.scheduled_at, task.started_at, task.finished_at].filter(Boolean).join(" → ");
        const error = task.error_type || task.error ? ` · ${task.error_type || "error"}${task.error ? `: ${task.error}` : ""}` : "";
        return `<div class="solar-evidence-capture-task"><strong>${escape(task.source)}</strong><span>${escape(task.outcome || "outcome saknas")}</span><small>${escape([target, times].filter(Boolean).join(" · ") || "Ingen tids- eller målmetadata")}${escape(error)}</small></div>`;
      }).join("");
    }
    applySolarEvidenceVisibility(card, this._debugEnabled, evidence?.available, captureTasks.length > 0);
    const sourceButton = card.querySelector('[data-card-source="solar-evidence"]');
    if (sourceButton) sourceButton.hidden = !this._debugEnabled;
    if (!evidence?.available) {
      summary.textContent = "Evidence-data saknas i payloaden.";
      status.textContent = "Capture-task-status visas utan att skapa ett outcome.";
      list.replaceChildren();
      return;
    }
    const progress = evidence.progress || {};
    const history = summarizeSolarEvidenceHistory(days);
    const omComplete = Number.isFinite(Number(progress.open_meteo_complete)) ? Number(progress.open_meteo_complete) : 0;
    const omTarget = Number.isFinite(Number(progress.open_meteo_target)) ? Number(progress.open_meteo_target) : 21;
    const commonComplete = Number.isFinite(Number(progress.forecast_solar_common)) ? Number(progress.forecast_solar_common) : 0;
    const commonTarget = Number.isFinite(Number(progress.forecast_solar_target)) ? Number(progress.forecast_solar_target) : 14;
    const storedRange = history.count
      ? `${history.first_date}–${history.last_date}`
      : "inga datum";
    summary.innerHTML = `<div class="solar-evidence-progress"><div><strong>Open-Meteo · historisk jämförelse</strong><span>${omComplete} / ${omTarget}</span><meter min="0" max="${omTarget}" value="${omComplete}"></meter></div><div><strong>Forecast.Solar common · historisk jämförelse</strong><span>${commonComplete} / ${commonTarget}</span><meter min="0" max="${commonTarget}" value="${commonComplete}"></meter></div></div><div class="solar-evidence-stored"><strong>Lagrad historik för vald site</strong><span>${history.count} datum · ${storedRange}</span></div><small class="solar-evidence-protocol">${evidence.protocol_version || "evidence-v1"} · LOCKED</small>`;
    status.textContent = evidence.status || "INSUFFICIENT – KEEP COLLECTING";
    list.innerHTML = [...days].sort((left, right) => String(right.date || "").localeCompare(String(left.date || ""))).map((day) => {
      const number = (value) => value !== null && value !== undefined && Number.isFinite(Number(value)) ? Number(value) : null;
      const actualValue = number(day.actual_kwh);
      const openMeteoValue = number(day.open_meteo_nominal_kwh);
      const forecastValue = number(day.forecast_solar_frozen_kwh);
      const display = (value) => value === null ? "—" : this._formatNumber(value);
      const omError = actualValue !== null && openMeteoValue !== null ? display(Math.abs(actualValue - openMeteoValue)) : "—";
      const forecastError = actualValue !== null && forecastValue !== null ? display(Math.abs(actualValue - forecastValue)) : "—";
      const state = !day.audit_semantics_version
        ? "HISTORIK · LEGACY / EJ OMVÄRDERAD"
        : day.audit_complete ? "✅ GODKÄND" : "❌ EXKLUDERAD";
      const reasons = Array.isArray(day.exclusion_reasons) && day.exclusion_reasons.length ? day.exclusion_reasons.join(", ") : "Ingen ytterligare orsak angiven";
      const common = day.common_forecast_solar_day ? " · Common" : "";
      return `<div class="solar-evidence-day"><div class="solar-evidence-day-heading"><strong>${day.date || "—"}</strong><span>${state}${common}</span></div><div class="solar-evidence-metrics"><span><b>Actual</b>${display(actualValue)} kWh</span><span><b>Open-Meteo</b>${display(openMeteoValue)} kWh</span><span><b>OM error</b>${omError} kWh</span><span><b>Forecast.Solar</b>${display(forecastValue)} kWh</span><span><b>FS error</b>${forecastError} kWh</span></div><small>${display(number(day.merged_points))} punkter · max gap ${display(number(day.max_internal_gap_minutes))} min · ${reasons}</small></div>`;
    }).join("");
  }

  _renderBenchmarkEvidence() {
    const card = this.host.querySelector("[data-benchmark-evidence-card]");
    const summary = this.host.querySelector("[data-benchmark-evidence-summary]");
    const status = this.host.querySelector("[data-benchmark-evidence-status]");
    const list = this.host.querySelector("[data-benchmark-evidence-list]");
    const evidence = this._benchmarkEvidence || {};
    if (!card || !summary || !status || !list) return;
    applySolarEvidenceVisibility(card, this._debugEnabled, evidence.available);
    const sourceButton = card.querySelector('[data-card-source="benchmark-evidence"]');
    if (sourceButton) sourceButton.hidden = !this._debugEnabled;
    if (!evidence.available) return;
    const horizon = evidence.horizon || {};
    const matrix = evidence.holdout_matrix || {};
    summary.textContent = `96 slots: ${horizon.actual_coverage || "0/96"} actual · ${horizon.available_slots || 0}/${horizon.required_slots || 96} causal slots · ${matrix.qualified_count || 0}/${matrix.candidate_count || 0} qualified windows`;
    status.textContent = evidence.blocker ? `BLOCKER: ${evidence.blocker}` : (evidence.status || "UNKNOWN");
    const rows = [
      ["Site", evidence.site_id || "—"],
      ["Resource", evidence.resource_id || evidence.ess?.resource_id || "—"],
      ["Load quality", evidence.frame_quality?.load || "—"],
      ["Load frame", evidence.load_frame?.frame_id || "—"],
      ["Frame known", evidence.frame_known_at || evidence.load_frame?.known_at || "—"],
      ["Decision at", horizon.decision_at || "—"],
      ["Horizon end", horizon.end_at || "—"],
      ["Economics causal", evidence.economics?.causal === true ? "yes" : "no"],
      ["Economics from", evidence.economics_applicability?.override_effective_from || evidence.economics_applicability?.valid_from || "—"],
      ["Last attempt", evidence.last_attempt?.at ? `${evidence.last_attempt.at} · ${evidence.last_attempt.reason || (evidence.last_attempt.accepted ? "accepted" : "blocked")}` : "—"],
      ["ESS", evidence.ess?.available === true ? "available" : (evidence.ess?.reason || "unavailable")],
      ["Source generations", Array.isArray(evidence.source_generations) ? evidence.source_generations.filter(Boolean).join(", ") || "—" : "—"],
      ["Provenance", evidence.frame_provenance ? Object.keys(evidence.frame_provenance).map((key) => `${key}:${Object.keys(evidence.frame_provenance[key] || {}).join("/") || "recorded"}`).join(", ") || "—" : "—"],
      ["Qualified", evidence.qualified === true ? "yes" : "no"],
      ["Fingerprint", evidence.fingerprint || "—"],
      ["Artifact", evidence.artifact?.artifact_id || "—"],
      ["Holdouts", Array.isArray(matrix.items) && matrix.items.length
        ? matrix.items.map((item) => `${item.kind}:${item.status}${item.reason ? ` (${item.reason})` : ""}`).join(" · ")
        : "—"],
      ["Persistent readback", evidence.artifact?.readback === true ? "verified" : "pending"],
    ];
    list.replaceChildren(...rows.map(([label, value]) => {
      const row = document.createElement("div");
      row.className = "solar-evidence-day";
      const strong = document.createElement("strong");
      strong.textContent = `${label}: `;
      row.append(strong, document.createTextNode(String(value)));
      return row;
    }));
  }

  _renderSocChart() {
    const card = this.host.querySelector("[data-soc-card]");
    const chart = this.host.querySelector("[data-soc-chart]");
    if (!card || !chart) return;
    const configured = Boolean(this._powerState?.soc_entity);
    card.hidden = !configured;
    if (!configured) {
      chart.replaceChildren();
      return;
    }
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
    const plot = { left: 44, right: 8, top: 8, bottom: 8 };
    const plotWidth = width - plot.left - plot.right;
    const plotHeight = height - plot.top - plot.bottom;
    const xStart = dayStart.getTime();
    const xEnd = points.at(-1).timestamp;
    const selectedEnd = this._ellaSelection?.end ? new Date(this._ellaSelection.end).getTime() : 0;
    const axisEnd = Math.max(xEnd, Number.isFinite(selectedEnd) ? selectedEnd : 0);
    const xDuration = Math.max(1, xEnd - xStart);
    const chartDuration = Math.max(1, axisEnd - xStart);
    const x = (timestamp) => xEnd <= xStart
      ? width - plot.right
      : plot.left + ((timestamp - xStart) / chartDuration) * plotWidth;
    const y = (value) => plot.top + (1 - Math.max(0, Math.min(100, value)) / 100) * plotHeight;
    const intervals = points.slice(1).map((point, index) => point.timestamp - points[index].timestamp).filter((interval) => interval > 0);
    const typicalInterval = intervals.length ? intervals.slice().sort((left, right) => left - right)[Math.floor(intervals.length / 2)] : 0;
    const maxGap = Math.max(30 * 60 * 1000, typicalInterval * 4, 2 * 60 * 60 * 1000);
    const segments = [];
    const estimatedSegments = [];
    let segment = [points[0]];
    points.slice(1).forEach((point, index) => {
      if (point.timestamp - points[index].timestamp > maxGap) {
        segments.push(segment);
        estimatedSegments.push([points[index], point]);
        segment = [];
      }
      segment.push(point);
    });
    segments.push(segment);
    const lineMarkup = segments.filter((segment) => segment.length >= 2).map((segment) => {
      const coordinates = segment.map((point) => `${x(point.timestamp)} ${y(point.value)}`).join(" L ");
      const area = `M ${x(segment[0].timestamp)} ${plot.top + plotHeight} L ${coordinates} L ${x(segment.at(-1).timestamp)} ${plot.top + plotHeight} Z`;
      return `<path class="soc-area" fill="${chartColor("soc")}" d="${area}" /><path class="soc-line" fill="none" stroke="${chartColor("soc")}" d="M ${coordinates}" />`;
    }).join("");
    const estimatedMarkup = estimatedSegments.map(([from, to]) => {
      const coordinates = `${x(from.timestamp)} ${y(from.value)} L ${x(to.timestamp)} ${y(to.value)}`;
      const area = `M ${x(from.timestamp)} ${plot.top + plotHeight} L ${coordinates} L ${x(to.timestamp)} ${plot.top + plotHeight} Z`;
      return `<path class="soc-estimated-area" fill="${chartColor("socEstimated")}" d="${area}" /><path class="soc-estimated-line" fill="none" stroke="${chartColor("socEstimated")}" d="M ${coordinates}" />`;
    }).join("");
    const singletonMarkup = segments.filter((segment) => segment.length === 1).map(([point]) =>
      `<circle class="soc-singleton" fill="${chartColor("soc")}" cx="${x(point.timestamp)}" cy="${y(point.value)}" r="3" />`).join("");
    const gridMarkup = [0, 50, 100].map((level) => {
      return `<line class="soc-gridline" x1="${plot.left}" y1="${y(level)}" x2="${width - plot.right}" y2="${y(level)}" />`;
    }).join("");
    const labelMarkup = `<div class="soc-label-rail" aria-hidden="true"><span class="soc-label top">100</span><span class="soc-label middle">50</span><span class="soc-label bottom">0</span></div>`;
    chart.innerHTML = `${labelMarkup}<svg class="soc-chart-svg" preserveAspectRatio="none" viewBox="0 0 ${width} ${height}" role="img" aria-label="Batteriets laddnivå idag">
      ${gridMarkup}${lineMarkup}${estimatedMarkup}${singletonMarkup}${this._ellaSelectionBandMarkup((timestamp) => x(timestamp), plot, xStart, axisEnd)}<g class="soc-hover" aria-hidden="true"></g>
    </svg><div class="soc-tooltip" hidden></div>`;
    const svg = chart.querySelector(".soc-chart-svg");
    const tooltip = chart.querySelector(".soc-tooltip");
    const hover = chart.querySelector(".soc-hover");
    const clear = () => {
      tooltip.hidden = true;
      hover.replaceChildren();
    };
    const update = (event) => {
      const pointer = pointerToPlotCoordinates(svg, event, plot, width, height);
      if (!pointer?.inside) {
        clear();
        return null;
      }
      const plotRatio = plotWidth > 0 ? (pointer.viewX - plot.left) / plotWidth : 0;
      const timestamp = xStart + plotRatio * xDuration;
      const point = points.reduce((nearest, candidate) => Math.abs(candidate.timestamp - timestamp) < Math.abs(nearest.timestamp - timestamp) ? candidate : nearest, points[0]);
      const pointX = x(point.timestamp);
      const pointY = y(point.value);
      renderSharedTooltip(tooltip, {
        title: new Date(point.timestamp).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" }),
        fields: [{ label: "Laddnivå", value: point.value, formatted: `${this._formatNumber(point.value)} %` }],
      });
      tooltip.hidden = false;
      hover.innerHTML = `<circle class="chart-hover-marker chart-hover-marker-soc" fill="${chartColor("soc")}" cx="${pointX}" cy="${pointY}" r="4" />`;
      positionChartTooltip(chart, tooltip, event.clientX, event.clientY, [], this._tooltipOrbit);
      return point;
    };
    svg.addEventListener("pointermove", update);
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
    const request = this._beginPowerStateRequest();
    try {
      const state = await request.hass.callWS({ type: "elrakning/power_state" });
      if (state?.success === false && state.error === "power_unavailable") return;
      this._applyPowerStateResponse(request, state);
      if (loadHistory) await this.loadPowerHistory();
    } catch {
      // Keep optional power cards unconfigured when state is unavailable.
    }
  }

  async loadPowerHistory(selectedDate = null) {
    if (!this.hass?.callWS) return;
    const siteState = await this._loadSiteIdentity();
    const siteId = siteState?.site_id || siteState?.current_site?.site_id
      || this._siteState?.site_id || this._siteState?.current_site?.site_id;
    if (!siteId) return;
    const confirmedDate = selectedDate instanceof Date ? selectedDate : this._periodPickerState?.confirmed;
    const requestedDate = confirmedDate ? localDateKey(new Date(confirmedDate)) : null;
    const siteContextGeneration = this._siteContextGeneration;
    const cycleKey = `${siteId}:${siteContextGeneration}:${requestedDate || ""}`;
    const existing = this._powerHistoryInFlight.get(cycleKey);
    if (existing) {
      this._recordPowerFlowDiagnostic("history_reused", { requested_date: requestedDate, site_id: siteId, active_history_jobs: this._powerHistoryInFlight.size });
      return existing.history;
    }
    const cycle = { history: null, enrichment: null };
    this._powerHistoryInFlight.set(cycleKey, cycle);
    this._recordPowerFlowDiagnostic("history_request_start", { requested_date: requestedDate, site_id: siteId, site_context_generation: siteContextGeneration, active_history_jobs: this._powerHistoryInFlight.size });
    cycle.history = this._loadPowerHistoryCycle({ requestedDate, cycle, siteId, siteContextGeneration });
    cycle.history.finally(() => {
      const cleanup = () => {
        if (this._powerHistoryInFlight.get(cycleKey) === cycle) this._powerHistoryInFlight.delete(cycleKey);
        this._recordPowerFlowDiagnostic("history_cycle_cleanup", {
          requested_date: requestedDate,
          site_id: siteId,
          enrichment_started: Boolean(cycle.enrichment),
          active_history_jobs: this._powerHistoryInFlight.size,
        });
      };
      if (cycle.enrichment) cycle.enrichment.finally(cleanup);
      else cleanup();
    }).catch(() => {});
    return cycle.history;
  }

  async _loadPowerHistoryCycle({ requestedDate, cycle, siteId, siteContextGeneration }) {
    const started = performance.now();
    const requestToken = ++this._powerHistoryRequestToken;
    const enrichmentToken = ++this._powerHistoryEnrichmentRequestToken;
    let stage = "request";
    let substage = "request";
    try {
      const response = await this.hass.callWS({ type: "elrakning/power_history", days: 7,
        ...(requestedDate ? { date: requestedDate } : {}),
      });
      stage = "response";
      this._recordPowerFlowDiagnostic("history_response_received", { requested_date: requestedDate, duration_ms: roundDiagnosticMs(performance.now() - started) });
      if (response?.error === "power_unavailable") return;
      const activeSiteId = this._siteState?.site_id || this._siteState?.current_site?.site_id || null;
      if (requestToken !== this._powerHistoryRequestToken || siteContextGeneration !== this._siteContextGeneration || siteId !== activeSiteId) {
        stage = "stale_guard";
        this._recordPowerFlowDiagnostic("history_stale_rejected", { requested_date: requestedDate, request_token: requestToken });
        return;
      }
      stage = "state_apply";
      const series = response?.success && response?.series && typeof response.series === "object" ? response.series : {};
      for (const [key, points] of Object.entries(this._powerLivePoints)) {
        if (!points.size) continue;
        const merged = new Map((Array.isArray(series[key]?.points) ? series[key].points : []).map((point) => [point.timestamp, point]));
        for (const [timestamp, point] of points) merged.set(timestamp, point);
        series[key] = { ...(series[key] || {}), points: [...merged.values()].sort((left, right) => new Date(left.timestamp) - new Date(right.timestamp)) };
      }
      const nextContextKey = `${siteId}:${siteContextGeneration}:${requestedDate || response?.date || ""}`;
      this._powerHistory = mergePowerHistoryRefreshState({
        response: { ...response, date: response?.date || requestedDate || null },
        series,
        existingState: this._powerHistory,
        contextKey: nextContextKey,
        previousContextKey: this._powerHistoryContextKey,
      });
      this._loadForecast = { available: false, reason: "enrichment_pending", frames: [] };
      this._powerHistoryContextKey = nextContextKey;
      this._refreshDailyEnergyStateFromAcceptedHistory();
      stage = "enrichment_start";
      this._recordPowerFlowDiagnostic("enrichment_request_start", { requested_date: requestedDate, active_enrichment_jobs: 1 });
      cycle.enrichment = this.loadPowerHistoryEnrichment({
        requestToken,
        enrichmentToken,
        siteContextGeneration,
        siteId,
        contextKey: this._powerHistoryContextKey,
        requestedDate,
      });
      try {
        stage = "history_render";
        const renderPhaseMs = {};
        const renderPhaseStart = performance.now();
        substage = "rebuild_live_power_maxima";
        this._rebuildLivePowerMaxima();
        renderPhaseMs.rebuild_live_power_maxima = roundDiagnosticMs(performance.now() - renderPhaseStart);
        let phaseStart = performance.now();
        substage = "refresh_power_energy_state";
        this._refreshPowerEnergyState();
        renderPhaseMs.refresh_power_energy_state = roundDiagnosticMs(performance.now() - phaseStart);
        phaseStart = performance.now();
        substage = "render_solar_evidence";
        this._renderSolarEvidence();
        renderPhaseMs.render_solar_evidence = roundDiagnosticMs(performance.now() - phaseStart);
        phaseStart = performance.now();
        substage = "render_price_plan_cards";
        this._renderPricePlanCards();
        renderPhaseMs.render_price_plan_cards = roundDiagnosticMs(performance.now() - phaseStart);
        phaseStart = performance.now();
        if (this.host.querySelector(".price-chart")) {
          substage = "render_price_chart";
          this.renderPriceChart();
        }
        renderPhaseMs.render_price_chart = roundDiagnosticMs(performance.now() - phaseStart);
        this._recordPowerFlowDiagnostic("history_render", {
          requested_date: requestedDate,
          duration_ms: roundDiagnosticMs(performance.now() - started),
          render_phase_ms: renderPhaseMs,
          ...(this._lastPowerChartRenderStats || {}),
        });
      } catch (error) {
        this._recordPowerFlowDiagnostic("history_render_failed", {
          requested_date: requestedDate,
          stage,
          substage,
          ...sanitizeDiagnosticError(error),
          duration_ms: roundDiagnosticMs(performance.now() - started),
        });
      }
    } catch (error) {
      this._recordPowerFlowDiagnostic("history_cycle_failed", {
        requested_date: requestedDate,
        stage,
        error_name: error?.name || "Error",
        duration_ms: roundDiagnosticMs(performance.now() - started),
      });
      if (requestToken !== this._powerHistoryRequestToken) return;
      this._powerHistory = { date: null, series: {}, solar_forecast_baselines: {}, solar_shadow: { available: false, days: [] }, solar_evidence: { available: false, days: [] }, solar_weather: { available: false, source: "smhi", status: "unavailable", current: {}, hourly_forecast: [] }, solar_sun: { available: false }, solar_pvgis: { available: false, source: "jrc_pvgis" }, solar_open_meteo: { available: false, source: "open_meteo" } };
      this._loadForecast = { available: false, reason: "history_unavailable", frames: [] };
      this._refreshPowerEnergyState();
    }
  }

  async loadPowerHistoryEnrichment({ requestToken, enrichmentToken, siteContextGeneration, siteId, contextKey, requestedDate }) {
    if (!this.hass?.callWS) return;
    const started = performance.now();
    let substage = "request";
    try {
      const response = await this.hass.callWS({
        type: "elrakning/power_history_enrichment",
        ...(requestedDate ? { date: requestedDate } : {}),
      });
      const guardReasons = [];
      if (requestToken !== this._powerHistoryRequestToken) guardReasons.push("history_request_token");
      if (enrichmentToken !== this._powerHistoryEnrichmentRequestToken) guardReasons.push("enrichment_request_token");
      if (siteContextGeneration !== this._siteContextGeneration) guardReasons.push("site_context_generation");
      const activeSiteId = this._siteState?.site_id || this._siteState?.current_site?.site_id || null;
      if (siteId !== activeSiteId) guardReasons.push("site_id");
      if (contextKey !== this._powerHistoryContextKey) guardReasons.push("history_context_key");
      if (guardReasons.length) {
        this._recordPowerFlowDiagnostic("enrichment_stale_rejected", { requested_date: requestedDate, reasons: guardReasons, duration_ms: roundDiagnosticMs(performance.now() - started) });
        return;
      }
      this._recordPowerFlowDiagnostic("enrichment_response_received", { requested_date: requestedDate, duration_ms: roundDiagnosticMs(performance.now() - started), accepted: true });
      const mergeStarted = performance.now();
      substage = "merge_state_apply";
      this._powerHistory = mergePowerHistoryEnrichmentState({
        response,
        existingState: this._powerHistory,
      });
      this._loadForecast = response?.load_forecast || { available: false, reason: "no_supported_history", frames: [] };
      substage = "render_solar_evidence";
      this._renderSolarEvidence();
      substage = "render_price_plan_cards";
      this._renderPricePlanCards();
      if (this.host.querySelector(".price-chart")) {
        substage = "render_price_chart";
        this.renderPriceChart();
      }
      this._recordPowerFlowDiagnostic("enrichment_merge", { requested_date: requestedDate, duration_ms: roundDiagnosticMs(performance.now() - mergeStarted), series: Object.keys(this._powerHistory.power_forecast?.series || {}) });
    } catch (error) {
      this._recordPowerFlowDiagnostic("enrichment_failed", {
        requested_date: requestedDate,
        substage,
        ...sanitizeDiagnosticError(error),
        duration_ms: roundDiagnosticMs(performance.now() - started),
      });
      // History remains available when optional enrichment is unavailable.
    }
  }

  _ellaSelectionBandMarkup(x, plot, startMs, endMs) {
    const selectionStart = new Date(this._ellaSelection?.start || 0).getTime();
    const selectionEnd = new Date(this._ellaSelection?.end || 0).getTime();
    if (!Number.isFinite(selectionStart) || !Number.isFinite(selectionEnd) || selectionEnd <= selectionStart || endMs <= startMs) return "";
    const left = Math.max(plot.left, x(Math.max(startMs, selectionStart)));
    const right = Math.min(960 - plot.right, x(Math.min(endMs, selectionEnd)));
    return right > left ? `<rect class="ella-selection-band" x="${left}" y="${plot.top}" width="${right - left}" height="${plot.height || 340 - plot.top - plot.bottom}" />` : "";
  }

  _clearPricePlanSelection({ recenterCurrent = false } = {}) {
    if (!this._ellaSelection) return;
    this._ellaSelection = null;
    this._renderPricePlanCards();
    this.renderPriceChart();
    this._renderSocChart();
    if (recenterCurrent) {
      const rail = this.host.querySelector("[data-price-plan-rail]");
      const blocks = this._pricePlan?.available === true && Array.isArray(this._pricePlan.plan_blocks)
        ? this._pricePlan.plan_blocks
        : [];
      centerCurrentPricePlanCard(rail, blocks);
    }
  }

  _bindPricePlanSelectionEvents() {
    const isPricePlanCardEvent = (event) => event.composedPath?.().some((node) => node?.classList?.contains("price-plan-card"))
      || event.target.closest?.(".price-plan-card");
    const railForEvent = (event) => event.composedPath?.().find((node) => node?.matches?.("[data-price-plan-rail]"))
      || event.target.closest?.("[data-price-plan-rail]")
      || null;
    const markKeyboardScroll = (event) => {
      const rail = railForEvent(event);
      if (rail && event.isTrusted === true && ["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(event.key)) {
        this._pricePlanUserScrollGesture = true;
      }
    };
    const resetUserScrollGesture = () => {
      this._pricePlanUserScrollGesture = false;
    };
    const clearUnlessCard = (event) => {
      if ((event.type === "pointerdown" || event.type === "click") && isPricePlanCardEvent(event)) return;
      const rail = railForEvent(event);
      if (event.type === "pointerdown" && rail && !isPricePlanCardEvent(event)) {
        this._pricePlanUserScrollGesture = event.isTrusted === true;
        return;
      }
      if (event.type === "pointerup" || event.type === "pointercancel") {
        this._pricePlanUserScrollGesture = false;
      }
      if ((event.type === "wheel" || event.type === "touchmove" || event.type === "scroll") && rail) {
        if (this._ellaSelection && isUserOriginPricePlanScroll(event, rail, this._pricePlanUserScrollGesture)) {
          this._clearPricePlanSelection({ recenterCurrent: true });
        }
        return;
      }
      this._clearPricePlanSelection();
    };
    this.host.addEventListener("pointerdown", clearUnlessCard);
    this.host.addEventListener("click", (event) => {
      if (isPricePlanCardEvent(event)) return;
      this._clearPricePlanSelection();
    });
    this.host.addEventListener("wheel", clearUnlessCard, { passive: true });
    this.host.addEventListener("touchmove", clearUnlessCard, { passive: true });
    this.host.addEventListener("scroll", clearUnlessCard, true);
    this.host.addEventListener("pointerup", resetUserScrollGesture, true);
    this.host.addEventListener("pointercancel", resetUserScrollGesture, true);
    this.host.addEventListener("keydown", markKeyboardScroll, true);
    this.host.addEventListener("keyup", resetUserScrollGesture, true);
  }

  _renderPricePlanCards() {
    const rail = this.host.querySelector("[data-price-plan-rail]");
    if (!rail) return;
    const plan = this._pricePlan || {};
    const blocks = plan.available === true && Array.isArray(plan.plan_blocks) ? plan.plan_blocks : [];
    if (!blocks.length) {
      this._pricePlanRailCenteredKey = null;
      rail.hidden = true;
      rail.replaceChildren();
      return;
    }
    const planKey = JSON.stringify({
      site_id: plan.site_id || null,
      plan_version: plan.plan_version || null,
      input_state_id: plan.input_state_id || null,
      plan_id: plan.plan_id || null,
      block_ids: blocks.map((block) => block?.plan_block_id || null),
    });
    const currentBlockId = currentPricePlanBlock(blocks)?.plan_block_id || null;
    const shouldCenterCurrentCard = this._pricePlanRailCenteredKey !== planKey;
    this._pricePlanRailCenteredKey = planKey;
    rail.hidden = false;
    rail.replaceChildren(...blocks.map((block) => {
      const start = typeof block?.start === "string" ? block.start : "";
      const end = typeof block?.end === "string" ? block.end : "";
      const isCurrent = block.plan_block_id === currentBlockId;
      const isSelected = this._ellaSelection?.id === block.plan_block_id;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `price-plan-card${isCurrent ? " current" : ""}${isSelected ? " selected" : ""}`;
      button.dataset.planBlockId = block.plan_block_id || "";
      button.dataset.planStart = start;
      button.dataset.planEnd = end;
      if (isCurrent) button.setAttribute("aria-current", "time");
      button.setAttribute("role", "listitem");
      button.setAttribute("aria-pressed", String(isSelected));
      const title = document.createElement("strong");
      title.textContent = `${this._formatTime(new Date(start))}–${this._formatTime(new Date(end))} · ${block.price_context?.title || block.title || "Okänd kostnadsperiod"}`;
      const action = document.createElement("b");
      action.className = "price-plan-action";
      action.textContent = block.primary_action?.label || "Normal drift";
      const reason = document.createElement("small");
      reason.textContent = block.short_reason || "Ingen verifierad rekommendation.";
      button.append(title, action, reason);
      button.addEventListener("pointerdown", (event) => event.stopPropagation());
      button.addEventListener("click", () => {
        this._ellaSelection = togglePricePlanSelection(this._ellaSelection, block, plan.plan_version || null);
        this._renderPricePlanCards();
        this.renderPriceChart();
        this._renderSocChart();
        if (this._debugEnabled) this._loadEllaDebugSnapshot(plan, block);
      });
      return button;
    }));
    if (shouldCenterCurrentCard) {
      scheduleCurrentPricePlanCenter(rail, blocks);
    }
  }

  _formatTime(value) {
    return value.toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" });
  }

  async loadSolarForecast() {
    if (!this.hass?.callWS) return;
    const siteState = await this._loadSiteIdentity();
    const siteId = siteState?.site_id || siteState?.current_site?.site_id
      || this._siteState?.site_id || this._siteState?.current_site?.site_id;
    if (!siteId) return;
    try {
      const response = await this.hass.callWS({ type: "elrakning/solar_forecast_state" });
      if (response?.success === false) return;
      this._powerHistory = {
        ...this._powerHistory,
        solar_forecast: response,
        solar_forecast_baselines: response?.baselines || {},
      };
      this._renderSolarHistoryCard();
    } catch {
      // Keep actual solar history available when forecast transport is unavailable.
    }
  }

  async loadSolarEvidence() {
    if (!this.hass?.callWS) return;
    const siteState = await this._loadSiteIdentity();
    const siteId = siteState?.site_id || siteState?.current_site?.site_id
      || this._siteState?.site_id || this._siteState?.current_site?.site_id;
    if (!siteId) return;
    try {
      const response = await this.hass.callWS({ type: "elrakning/solar_evidence_state" });
      if (response?.available === false) return;
      this._powerHistory = { ...this._powerHistory, solar_evidence: response };
      this._renderSolarEvidence();
    } catch {
      // Evidence is optional and must not affect the other cards.
    }
  }

  async loadBenchmarkEvidence() {
    if (!this.hass?.callWS) return;
    if (!this._siteState) await this._loadSiteIdentity();
    const siteId = this._siteState?.current_site?.site_id || this._siteState?.site_id;
    if (!siteId) return;
    const requestToken = ++this._benchmarkEvidenceRequestToken;
    const requestHass = this.hass;
    try {
      const response = await requestHass.callWS({ type: "elrakning/replay_benchmark_evidence", site_id: siteId });
      const currentSiteId = this._siteState?.current_site?.site_id || this._siteState?.site_id || null;
      if (requestToken !== this._benchmarkEvidenceRequestToken || this.hass !== requestHass || currentSiteId !== siteId || response?.site_id !== siteId) return;
      this._benchmarkEvidence = response || { available: false, status: "unavailable", blocker: "empty_response" };
      this._renderBenchmarkEvidence();
    } catch {
      if (requestToken !== this._benchmarkEvidenceRequestToken || this.hass !== requestHass) return;
      this._benchmarkEvidence = { available: false, status: "unavailable", blocker: "transport_unavailable" };
      this._renderBenchmarkEvidence();
    }
  }

  _appendPowerState(eventData) {
    if (eventData?.state) {
      for (const entry of eventData.points || []) this._appendPowerPoint(entry.series, entry.point);
      this._applyAuthoritativePowerState(eventData.state);
      if (this.host.querySelector(".price-chart")
        && this._getPriceChartLiveSignature() !== this._priceChartLiveSignature) {
        this.renderPriceChart({ liveUpdate: true });
      }
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
      ? this._powerHistory.series[series].points
      : [];
    const normalizedPoint = this._powerLivePoints[series].get(timestamp.toISOString());
    this._powerHistory.series = {
      ...this._powerHistory.series,
      [series]: {
        ...(this._powerHistory.series?.[series] || {}),
        points: mergePowerHistoryPoint(existing, normalizedPoint, timestamp.getTime()),
      },
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

  _recordPowerFlowDiagnostic(event, details = {}) {
    const siteId = this._siteState?.site_id || this._siteState?.current_site?.site_id || this._pricePlan?.site_id || null;
    const selectedDate = this._periodPickerState?.confirmed;
    const requestedDate = selectedDate instanceof Date && Number.isFinite(selectedDate.getTime()) ? localDateKey(selectedDate) : null;
    void this._recordDiagnostic("frontend_power_flow", "INFO", event, JSON.stringify({
      relative_ms: roundDiagnosticMs(performance.now()),
      request_generation: this._powerHistoryRequestToken,
      site_context_generation: this._siteContextGeneration,
      site_id: siteId,
      selected_date: requestedDate,
      ...details,
    }));
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

  _showSourceDataDialog(title, sourceLabel, data, copyLabel = "Kopiera") {
    const dialog = this.host.querySelector("[data-provider-source-dialog]");
    const heading = dialog?.querySelector("h2");
    const provider = this.host.querySelector("[data-provider-source-provider]");
    const text = this.host.querySelector("[data-provider-source-text]");
    const copy = this.host.querySelector("[data-provider-source-copy]");
    if (!dialog || !heading || !provider || !text || !copy) return;
    heading.textContent = title;
    provider.textContent = sourceLabel ? `Källa: ${sourceLabel}` : "";
    provider.hidden = !sourceLabel;
    text.textContent = JSON.stringify(sanitizeDebugData(data), null, 2);
    copy.disabled = false;
    copy.dataset.defaultLabel = copyLabel;
    copy.textContent = copyLabel;
    dialog.hidden = false;
  }

  async _loadEllaDebugSnapshot(plan, block) {
    const requestToken = ++this._ellaDebugRequestToken;
    const siteGeneration = this._siteContextGeneration;
    const siteId = plan?.site_id || this._siteState?.site_id;
    const request = {
      type: "elrakning/ella_action_plan/debug",
      site_id: siteId,
      plan_id: plan?.plan_id,
      revision: plan?.revision,
      plan_block_id: block?.plan_block_id,
    };
    try {
      const response = await this.hass.callWS(request);
      if (requestToken !== this._ellaDebugRequestToken
        || siteGeneration !== this._siteContextGeneration
        || this._pricePlan?.plan_id !== plan?.plan_id
        || this._pricePlan?.revision !== plan?.revision
        || this._siteState?.site_id && this._siteState.site_id !== siteId) return;
      if (response?.success === true && response?.available === true && response.snapshot) {
        this._showSourceDataDialog("ELLA · Visa data", `Planblock ${block.plan_block_id}`, response.snapshot, "Kopiera data");
        return;
      }
      this._showSourceDataDialog("ELLA · Visa data", `Planblock ${block.plan_block_id}`, {
        available: false,
        error: response?.error || "snapshot_unavailable",
        site_id: siteId,
        plan_id: plan?.plan_id,
        revision: plan?.revision,
        plan_block_id: block?.plan_block_id,
      }, "Kopiera data");
    } catch (error) {
      if (requestToken !== this._ellaDebugRequestToken || siteGeneration !== this._siteContextGeneration) return;
      const details = this._websocketErrorDetails(error);
      this._showSourceDataDialog("ELLA · Visa data", `Planblock ${block.plan_block_id}`, {
        available: false,
        error: details.code,
        message: details.message,
        site_id: siteId,
        plan_id: plan?.plan_id,
        revision: plan?.revision,
        plan_block_id: block?.plan_block_id,
      }, "Kopiera data");
    }
  }

  _buildPriceSourceData() {
    const mode = this._periodPickerState?.mode || "hour";
    const selected = new Date(this._periodPickerState?.confirmed || new Date());
    const year = selected.getFullYear();
    const month = selected.getMonth();
    const localPeriod = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    const selectedPeriod = mode === "hour"
      ? `${year}-${String(month + 1).padStart(2, "0")}-${String(selected.getDate()).padStart(2, "0")}`
      : mode === "day" ? localPeriod(selected) : String(year);
    const layers = this._effectiveChartLayerState();
    const visibleSeries = [
      layers.spot ? "price" : null,
      mode === "hour" && layers.average ? "average" : null,
      layers.import ? "buy" : null,
      layers.export ? "sell" : null,
      layers.solar ? "solar" : null,
      layers.consumption ? "load" : null,
      layers.charging ? "charging" : null,
      layers.discharging ? "discharging" : null,
    ].filter(Boolean);
    const periodInRange = (period, startMs, endMs) => {
      const startMsValue = new Date(period.start).getTime();
      const endMsValue = new Date(period.end).getTime();
      return Number.isFinite(startMsValue) && Number.isFinite(endMsValue) && startMsValue < endMs && endMsValue > startMs;
    };
    const priceSeries = [];
    const selectedPeriods = [];
    if (mode === "hour") {
      const start = new Date(year, month, selected.getDate());
      const end = new Date(start);
      end.setDate(end.getDate() + 1);
      this.priceData.periods.forEach((period, index) => {
        if (!periodInRange(period, start.getTime(), end.getTime())) return;
        selectedPeriods.push(period);
        priceSeries.push({
          timestamp: period.start,
          end: period.end,
          value: this._chartBarPrices?.[index] ?? this._comparisonPrice(period),
          category: priceCategory(this._chartBarPrices?.[index] ?? this._comparisonPrice(period), priceColorBands(this._chartBarPrices || [])),
          details: this._chartTooltipDetails?.get(index) || null,
        });
      });
    }
    const canonicalPoints = (points, startMs, endMs) => (Array.isArray(points) ? points : []).filter((point) => {
      const timestamp = new Date(point.timestamp).getTime();
      return Number.isFinite(timestamp) && timestamp >= startMs && timestamp < endMs;
    });
    let series;
    let groups;
    let priceAggregation;
    let coverage;
    let display;
    if (mode === "hour") {
      const current = this.priceData.periods.find((period) => new Date(period.start) <= new Date() && new Date() < new Date(period.end));
      const values = selectedPeriods.map((period) => this._comparisonPrice(period)).filter(Number.isFinite);
      series = {
        price: layers.spot ? priceSeries : [],
        average: layers.average ? [{ value: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null }] : [],
        buy: layers.import ? canonicalPoints(this._meterCanonicalPoints.map((point) => ({ ...point, value_kw: point.import_kw })), new Date(year, month, selected.getDate()).getTime(), new Date(year, month, selected.getDate() + 1).getTime()) : [],
        sell: layers.export ? canonicalPoints(this._meterCanonicalPoints.map((point) => ({ ...point, value_kw: point.export_kw })), new Date(year, month, selected.getDate()).getTime(), new Date(year, month, selected.getDate() + 1).getTime()) : [],
      };
      for (const [key, sourceKey] of [["solar", "solar"], ["load", "consumption"], ["charging", "charging"], ["discharging", "discharging"]]) {
        if (layers[sourceKey]) series[key] = canonicalPoints(this._powerCanonicalPoints?.[sourceKey], new Date(year, month, selected.getDate()).getTime(), new Date(year, month, selected.getDate() + 1).getTime());
      }
      const average = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
      display = { current_price_ore_per_kwh: current ? this._comparisonPrice(current) : null, average_ore_per_kwh: average, lowest_ore_per_kwh: values.length ? Math.min(...values) : null, highest_ore_per_kwh: values.length ? Math.max(...values) : null };
      priceAggregation = { method: "existing_hourly_price_series", trade_enabled: this._priceComparisonVisible.electricity, grid_enabled: this._priceComparisonVisible.grid, period_count: selectedPeriods.length, valid_period_count: values.length, missing_period_count: selectedPeriods.length - values.length, unit: "ore/kWh" };
      coverage = { period_count: selectedPeriods.length, valid_period_count: values.length };
    } else {
      const aggregatedPeriods = this._billingHistory ? (this._billingHistory.price_periods || []) : [];
      const aggregatedMeterPoints = this._billingHistory ? (this._billingHistory.energy_points || []) : [];
      const data = aggregatePriceAndEnergyByPeriod(aggregatedPeriods, aggregatedMeterPoints, this._powerHistory?.series, mode, selected, (period) => this._comparisonPrice(period));
      groups = data.map((item) => ({ period: item.label, price_average_ore_per_kwh: item.price, price_period_count: item.price_period_count, buy_kwh: item.energy.import ?? null, sell_kwh: item.energy.export ?? null, solar_kwh: item.energy.solar ?? null, load_kwh: item.energy.consumption ?? null, charging_kwh: item.energy.charging ?? null, discharging_kwh: item.energy.discharging ?? null }));
      series = {};
      for (const key of visibleSeries.filter((value) => value !== "price")) series[key] = groups.map((group) => ({ period: group.period, value: group[`${key === "buy" ? "buy" : key === "sell" ? "sell" : key}_kwh`] ?? null })).filter((point) => point.value !== null);
      if (layers.spot) series.price = groups.map((group) => ({ period: group.period, value: group.price_average_ore_per_kwh })).filter((point) => point.value !== null);
      const priceValues = data.map((item) => item.price).filter(Number.isFinite);
      const weightedDuration = data.reduce((sum, item) => sum + (Number.isFinite(item.price) ? Number(item.price_duration_ms || 0) : 0), 0);
      const average = weightedDuration ? data.reduce((sum, item) => sum + (Number.isFinite(item.price) ? item.price * Number(item.price_duration_ms || 0) : 0), 0) / weightedDuration : null;
      const current = this.priceData.periods.find((period) => new Date(period.start) <= new Date() && new Date() < new Date(period.end));
      display = { current_price_ore_per_kwh: current ? this._comparisonPrice(current) : null, average_ore_per_kwh: average, lowest_ore_per_kwh: priceValues.length ? Math.min(...priceValues) : null, highest_ore_per_kwh: priceValues.length ? Math.max(...priceValues) : null };
      const rangeStart = mode === "day" ? new Date(year, month, 1).getTime() : new Date(year, 0, 1).getTime();
      const rangeEnd = mode === "day" ? new Date(year, month + 1, 1).getTime() : new Date(year + 1, 0, 1).getTime();
      const relevantPeriods = aggregatedPeriods.filter((period) => mode === "year" || periodInRange(period, rangeStart, rangeEnd));
      const validPeriods = relevantPeriods.filter((period) => Number.isFinite(this._comparisonPrice(period)));
      priceAggregation = { method: "duration_weighted_average", trade_enabled: this._priceComparisonVisible.electricity, grid_enabled: this._priceComparisonVisible.grid, period_count: relevantPeriods.length, valid_period_count: validPeriods.length, missing_period_count: relevantPeriods.length - validPeriods.length, unit: "ore/kWh" };
      const coverageFor = (field, predicate = (item) => item[field] !== null) => {
        const available = data.filter(predicate);
        return {
          from: available.length ? new Date(available[0].startMs).toISOString() : null,
          to: available.length ? new Date(available.at(-1).endMs).toISOString() : null,
          completeness: available.length === data.length ? "full" : available.length ? "partial" : "missing",
          group_count: available.length,
          groups: available.map((item) => item.label),
        };
      };
      coverage = {
        group_count: groups.length,
        period: selectedPeriod,
        displayed_groups: groups.map((group) => group.period),
        price: coverageFor("price", (item) => Number.isFinite(item.price)),
        buy: coverageFor("import", (item) => Number.isFinite(item.energy.import)),
        sell: coverageFor("export", (item) => Number.isFinite(item.energy.export)),
        solar: coverageFor("solar", (item) => Number.isFinite(item.energy.solar)),
        load: coverageFor("consumption", (item) => Number.isFinite(item.energy.consumption)),
        charging: coverageFor("charging", (item) => Number.isFinite(item.energy.charging)),
        discharging: coverageFor("discharging", (item) => Number.isFinite(item.energy.discharging)),
        available_groups: groups.map((group) => group.period),
      };
    }
    const billingEnergySource = this._billingHistory?.energy_source || {};
    const billingSourceEntities = Array.isArray(billingEnergySource.source_entities)
      ? billingEnergySource.source_entities.map((source) => source?.entity_id || source?.source_entity).filter(Boolean)
      : [billingEnergySource.entity_id || billingEnergySource.source_entity].filter(Boolean);
    const sourceEntities = {
      buy: billingSourceEntities.length ? billingSourceEntities : [this._meterState?.energy_import_entity].filter(Boolean),
      sell: billingSourceEntities.length ? billingSourceEntities : [this._meterState?.energy_export_entity].filter(Boolean),
      solar: [this._powerState?.solar_entity].filter(Boolean),
      load: [this._powerState?.consumption_entity].filter(Boolean),
      charging: [this._powerState?.charging_entity].filter(Boolean),
      discharging: [this._powerState?.discharging_entity].filter(Boolean),
    };
    return {
      card: "price",
      mode,
      period: selectedPeriod,
      display,
      price: { series: series.price || [], aggregation: priceAggregation },
      energy: mode === "hour" ? { series, unit: "kW" } : { groups, unit: "kWh" },
      axes: mode === "hour" ? { price: { unit: "öre/kWh", side: "left" }, energy: { unit: "kW", side: "right" } } : { energy: { unit: "kWh", side: "left" }, price: { unit: "öre/kWh", side: "right" } },
      coverage,
      provenance: Object.fromEntries(Object.entries(sourceEntities).map(([key, entities]) => [key, { method: key === "buy" || key === "sell" ? (this._billingHistory?.integration_method || billingEnergySource.method || "canonical_meter_history") : "canonical_power_history", source_entities: entities }])),
      legend: {
        visible_series: visibleSeries,
        solo_series: this._soloChartLayer,
        solo_active: Boolean(this._soloChartLayer),
      },
      visible_series: visibleSeries,
    };
  }

  _bindMeterSourceDialog() {
    const open = this.host.querySelector("[data-meter-source]");
    if (!open) return;
    open.addEventListener("click", async () => {
      try {
        const response = await this.hass.callWS({ type: "elrakning/meter_source" });
        this._showSourceDataDialog("Source data", "Elmätare", response);
      } catch {
        this._showSourceDataDialog("Source data", "Elmätare", { error: "meter_source_unavailable" });
      }
    });
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
    const eonOpen = this.host.querySelector("[data-eon-grid-source]");
    const dialog = this.host.querySelector("[data-provider-source-dialog]");
    const close = this.host.querySelector("[data-provider-source-close]");
    const copy = this.host.querySelector("[data-provider-source-copy]");
    const provider = this.host.querySelector("[data-provider-source-provider]");
    const text = this.host.querySelector("[data-provider-source-text]");
    const heading = dialog?.querySelector("h2");
    const liveSources = [...this.host.querySelectorAll("[data-live-power-source]")];
    const cardSources = [...this.host.querySelectorAll("[data-card-source]")];
    if (!open || !eonOpen || !dialog || !close || !copy || !provider || !text || !heading) return;
    const dismiss = () => {
      dialog.hidden = true;
      heading.textContent = "Source data";
      provider.hidden = true;
      provider.textContent = "";
      text.textContent = "";
      copy.disabled = true;
    };
    const loadSource = async (event) => {
      const isEon = event.currentTarget === eonOpen;
      const liveSource = event.currentTarget.closest?.("[data-live-power-tile], [data-invoice-estimate-card]");
      const liveSourceName = event.currentTarget.dataset.livePowerSource;
      const cardSource = event.currentTarget.dataset.cardSource;
      dialog.hidden = false;
      heading.textContent = "Source data";
      text.textContent = "Hämtar Source data …";
      provider.hidden = true;
      provider.textContent = "";
      copy.disabled = true;
      copy.dataset.defaultLabel = "Kopiera";
      copy.textContent = "Kopiera";
      try {
        let source = liveSource
          ? liveSource._livePowerRaw || {}
          : isEon
          ? await this.hass.callWS({ type: "elrakning/grid/source_data" })
          : cardSource
          ? cardSource === "price"
            ? this._buildPriceSourceData()
            : cardSource === "cost"
            ? {
              source: cardSource,
              invoice_estimate: this._invoiceEstimateRaw,
              power_state: this._powerState,
              meter_state: this._meterState,
              power_history: this._powerHistory,
              meter_power_history: this._meterPowerHistory,
            }
            : this._buildCardSourceData(cardSource)
          : await this.hass.callWS({ type: "elrakning/electricity_provider_source_data", limit: 500 });
        if (isEon) {
          source = {
            ...source,
            current_month_cost: buildGridSourceCost(
              this._invoiceEstimateRaw,
              source.current_month_cost,
            ),
          };
        }
        const providerName = liveSource ? liveSourceName : source.provider_name || source.facility?.provider_name || (cardSource === "price" ? "Dagens elpris" : "");
        if (typeof providerName === "string" && providerName.trim()) {
          provider.textContent = `Källa: ${providerName.trim()}`;
          provider.hidden = false;
        }
        const safeSource = sanitizeDebugData(source);
        text.textContent = liveSource || isEon || cardSource
          ? JSON.stringify(safeSource, null, 2)
          : JSON.stringify({ facility: safeSource.facility, contracts: safeSource.contracts, invoices: safeSource.invoices.items, consumption: { total: safeSource.consumption.total, items: safeSource.consumption.items } }, null, 2);
        copy.disabled = false;
      } catch {
        text.textContent = "Source data kunde inte hämtas.";
      }
    };
    open.addEventListener("click", loadSource);
    eonOpen.addEventListener("click", loadSource);
    liveSources.forEach((button) => button.addEventListener("click", loadSource));
    cardSources.forEach((button) => button.addEventListener("click", loadSource));
    copy.addEventListener("click", async () => {
      try {
        await this._copyText(text.textContent);
        copy.textContent = "Kopierat";
        window.setTimeout(() => { copy.textContent = copy.dataset.defaultLabel || "Kopiera"; }, 1500);
      } catch {
        copy.textContent = "Kunde inte kopiera";
        window.setTimeout(() => { copy.textContent = copy.dataset.defaultLabel || "Kopiera"; }, 1500);
      }
    });
    close.addEventListener("click", dismiss);
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dismiss();
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !dialog.hidden) dismiss();
    });
  }

  _bindDiagnostics(loadInitial = false) {
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
      const requestGeneration = ++this._diagnosticsRequestGeneration;
      const lifecycleGeneration = this._diagnosticsLifecycleGeneration;
      const requestHass = this.hass;
      const isCurrentRequest = () => requestGeneration === this._diagnosticsRequestGeneration
        && lifecycleGeneration === this._diagnosticsLifecycleGeneration
        && this.hass === requestHass;
      try {
        const response = await requestHass.callWS({ type: "elrakning/diagnostics_state", include_inventory: false });
        if (!isCurrentRequest()) return false;
        render(response.logs);
        return true;
      } catch {
        if (isCurrentRequest()) status.textContent = "Varning";
        return false;
      }
    };
    this._loadDiagnosticsState = load;
    const domNodes = { list, status, copy, copyStatus, clear };
    const domChanged = Object.entries(domNodes).some(([key, node]) => this._diagnosticsDomNodes?.[key] !== node);
    if (!this._diagnosticsBound || domChanged) {
      copy.addEventListener("click", async () => {
        try {
          const loaded = await load();
          if (!loaded) copyStatus.textContent = "Varning";
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
      this._diagnosticsDomNodes = domNodes;
      if (!loadInitial && this._diagnosticEntries.length) render(this._diagnosticEntries);
    }
    if (loadInitial) load();
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
      const invoicePeriod = invoicePeriodLabel(latest);
      if (invoicePeriod) rows.push(["Senaste faktura", this._formatInvoiceMonth(invoicePeriod)]);
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
    this._renderInvoiceCardCosts();
  }

  _renderInvoiceEstimateCard() {
    const card = this.host.querySelector("[data-invoice-estimate-card]");
    const month = this.host.querySelector("[data-invoice-estimate-month]");
    const total = this.host.querySelector("[data-invoice-estimate-total]");
    const today = this.host.querySelector("[data-invoice-estimate-today]");
    const estimateStatus = this.host.querySelector("[data-invoice-estimate-status]");
    if (!card || !month || !total || !today) return;
    const billingHistory = this._billingHistory;
    const applicableGridPrice = billingHistory?.grid_price || null;
    let estimate = buildInvoiceEstimate(
      billingHistory?.price_periods,
      billingHistory?.energy_points,
      applicableGridPrice,
      this._electricityProviderState?.summary?.tariff?.fixed_fee_incl_vat_per_month,
      new Date(),
      billingHistory?.baseline_energy_points,
    );
    const monthlyForecast = billingHistory?.monthly_forecast;
    estimate = applyCanonicalMonthlyForecast(estimate, monthlyForecast);
    const configured = this._meterState?.configured === true;
    card.hidden = false;
    if (!configured || !billingHistory) {
      total.textContent = "Ej tillgängligt";
      month.textContent = "";
      if (estimateStatus) {
        estimateStatus.hidden = false;
        estimateStatus.textContent = this._costUnavailableReason === "meter_not_configured" ? "Mätare ej konfigurerad" : "Historik saknas";
      }
      today.hidden = true;
      today.textContent = "";
      this._invoiceEstimateRaw = null;
      card._livePowerRaw = null;
      this._renderInvoiceCardCosts();
      return;
    }
    month.textContent = estimate?.month ? this._formatInvoiceMonth(estimate.month).split(" ")[0] : "";
    if (estimateStatus) estimateStatus.hidden = true;
    if (!estimate) {
      card.hidden = false;
      total.textContent = "–";
      if (estimateStatus) { estimateStatus.hidden = false; estimateStatus.textContent = "Prisdata saknas"; }
      today.hidden = true;
      today.textContent = "";
      this._invoiceEstimateRaw = null;
      card._livePowerRaw = null;
      this._renderInvoiceCardCosts();
      return;
    }
    total.textContent = estimate.estimated_month_total_sek == null || !Number.isFinite(Number(estimate.estimated_month_total_sek))
      ? "–"
      : this._formatSek(Number(estimate.estimated_month_total_sek));
    const todayVariableCostSek = Number(billingHistory?.invoice_estimate?.today?.variable_cost_sek);
    today.hidden = !Number.isFinite(todayVariableCostSek);
    today.textContent = today.hidden ? "" : `+${this._formatSek(todayVariableCostSek)} idag`;
    const previousActual = billingHistory.previous_month_actual || buildPreviousMonthActual(
      billingHistory.invoice_sources || {
        trade: billingHistory.trade_invoices || this._electricityProviderState?.invoice_history,
        grid: billingHistory.grid_invoices,
      },
      estimate.month,
    );
    const availableMonths = buildInvoiceMonthHistory(estimate, billingHistory.invoice_sources || {
      trade: billingHistory.trade_invoices || this._electricityProviderState?.invoice_history,
      grid: billingHistory.grid_invoices,
    });
    if (!availableMonths.some((item) => item.month === this._costSelectedMonth)) this._costSelectedMonth = estimate.month;
    const comparison = buildInvoiceComparison(estimate, previousActual);
    const costAnalysis = buildCostAnalysisSeries(estimate, previousActual);
    this._invoiceEstimateRaw = {
      ...estimate,
      current_estimate: estimate,
      daily_breakdown_by_month: Object.fromEntries(this._billingDailyByMonth),
      previous_month_actual: previousActual,
      month_history: buildInvoiceMonthHistory(estimate, billingHistory.invoice_sources || {
        trade: billingHistory.trade_invoices || this._electricityProviderState?.invoice_history,
        grid: billingHistory.grid_invoices,
      }),
      comparison,
      cost_analysis: costAnalysis,
      provenance: buildInvoiceProvenance(estimate, { ...billingHistory, grid_price: applicableGridPrice }),
    };
    card._livePowerRaw = this._invoiceEstimateRaw;
    this._renderInvoiceCardCosts();
    const sourceButton = card.querySelector("[data-live-power-source]");
    if (sourceButton) sourceButton.hidden = !this._debugEnabled;
    this._updateLivePowerCardInteractivity();
  }

  _renderInvoiceCardCosts() {
    const estimate = this._invoiceEstimateRaw;
    for (const [provider, value] of [["elhandel", estimate?.trade?.total_so_far_sek], ["elnet", estimate?.grid?.total_so_far_sek]]) {
      const element = this.host.querySelector(`[data-provider-invoice-cost="${provider}"]`);
      if (!element) continue;
      const output = element.querySelector("strong");
      const available = value != null && Number.isFinite(Number(value));
      if (output) output.textContent = available ? this._formatSek(Number(value)) : "";
      element.hidden = !available;
    }
    this._renderCostCard();
    this._renderDashboardCardVisibility();
  }

  _renderCostCard() {
    const card = this.host.querySelector("[data-cost-card]");
    const status = this.host.querySelector("[data-cost-status]");
    const kpis = this.host.querySelector("[data-cost-kpis]");
    const chart = this.host.querySelector("[data-cost-chart]");
    const comparisonElement = this.host.querySelector("[data-cost-comparison]");
    const summary = this.host.querySelector("[data-cost-summary]");
    const historyChart = this.host.querySelector("[data-cost-history-chart]");
    const historyStatus = this.host.querySelector("[data-cost-history-status]");
    if (!card || !status || !kpis || !chart || !comparisonElement || !summary) return;
    const estimate = this._invoiceEstimateRaw;
    if (!estimate) {
      card.hidden = false;
      const reason = this._costUnavailableReason === "meter_not_configured"
        ? "Mätare ej konfigurerad"
        : this._costUnavailableReason === "history_missing"
          ? "Historik saknas"
          : "Prisdata saknas";
      status.textContent = reason;
      kpis.replaceChildren();
      chart.innerHTML = `<div class="cost-chart-unavailable">${reason}</div>`;
      summary.replaceChildren();
      if (historyChart) historyChart.innerHTML = `<div class="cost-chart-unavailable">Månadsserie ej tillgänglig · ${reason}</div>`;
      if (historyStatus) historyStatus.textContent = reason;
      comparisonElement.replaceChildren();
      return;
    }
    const currentMonth = estimate?.month || null;
    const selectedMonth = this._costSelectedMonth || currentMonth;
    const previous = estimate?.previous_month_actual;
    const showingCurrent = selectedMonth === currentMonth;
    const monthHistory = estimate?.month_history || [];
    const selectedIndex = monthHistory.findIndex((item) => item.month === selectedMonth);
    const selectedRecord = selectedIndex >= 0 ? monthHistory[selectedIndex] : null;
    const adjacentPrevious = selectedIndex >= 0 ? monthHistory[selectedIndex + 1] : null;
    const displayHistory = costHistoryDisplayOrder(monthHistory);
    card.hidden = !estimate;
    if (historyChart) {
      const valueForItem = (item) => item.current
        ? finiteCostNumber(item.estimated_total_sek)
        : finiteCostNumber(item.coverage === "complete" ? item.total_sek : item.known_amount_gross_sek);
      const valuedHistory = monthHistory.filter((item) => item.coverage !== "missing" && Number.isFinite(valueForItem(item)));
      const maxHistoryValue = Math.max(1, ...valuedHistory.map(valueForItem));
      historyChart.replaceChildren(...displayHistory.map((item) => {
        const itemElement = document.createElement("button");
        itemElement.type = "button";
        itemElement.dataset.costMonth = item.month;
        itemElement.setAttribute("role", "tab");
        itemElement.setAttribute("aria-selected", String(item.month === selectedMonth));
        const partial = item.coverage === "partial";
        const estimated = item.current && Number.isFinite(valueForItem(item));
        itemElement.className = `cost-history-bar-item${item.month === selectedMonth ? " selected" : ""}${estimated ? " estimated" : partial ? " partial" : item.coverage === "missing" ? " unavailable" : ""}`;
        const bar = document.createElement("div");
        bar.className = "cost-history-bar";
        const value = valueForItem(item);
        const hasValue = item.coverage !== "missing" && Number.isFinite(value);
        if (hasValue) bar.style.height = `${Math.max(value === 0 ? 3 : 8, value / maxHistoryValue * 62)}px`;
        const detail = estimated
          ? `Beräknad månadskostnad: ${this._formatSek(value)} · Status: ${item.coverage === "partial" ? "Estimat · Delvis underlag" : "Estimat"}`
          : `Elhandel: ${item.trade_sek == null ? "saknas" : this._formatSek(item.trade_sek)} · Elnät: ${item.grid_sek == null ? "saknas" : this._formatSek(item.grid_sek)} · Känd kostnad: ${hasValue ? this._formatSek(value) : "saknas"} · Status: ${item.coverage === "complete" ? "Komplett" : item.coverage === "partial" ? "Delvis underlag" : "Saknas"}`;
        bar.title = detail;
        itemElement.title = detail;
        const label = document.createElement("span");
        label.className = "cost-history-bar-label";
        label.textContent = this._formatInvoiceMonth(item.month).split(" ")[0];
        const amount = document.createElement("span");
        amount.className = "cost-history-bar-value";
        amount.textContent = hasValue ? this._formatSek(value) : "–";
        itemElement.setAttribute("aria-label", `${this._formatInvoiceMonth(item.month)}: ${amount.textContent} · ${detail}`);
        itemElement.append(label, bar, amount);
        return itemElement;
      }));
      if (historyStatus) historyStatus.textContent = valuedHistory.length ? `${valuedHistory.length} månader med känd kostnad av ${monthHistory.length}` : "Ingen användbar månadsserie";
    }
    if (!estimate) {
      status.textContent = "";
      kpis.replaceChildren();
      chart.replaceChildren();
      comparisonElement.replaceChildren();
      summary.replaceChildren();
      return;
    }
    const selectedCost = showingCurrent ? estimate.estimated_month_total_sek : selectedRecord?.coverage === "complete" ? selectedRecord.total_sek : selectedRecord?.known_amount_gross_sek;
    const comparisons = buildCostReferenceComparisons(monthHistory, selectedMonth, selectedCost);
    const kpiComparisons = buildCostKpiComparisons(estimate, previous, estimate?.cost_comparison_checkpoints);
    const currentRows = [
      ["Beräknad månadskostnad", estimate.estimated_month_total_sek],
      ["Kostnad hittills", estimate.total_so_far_sek],
      ["Beräknat återstående", estimate.forecast_remaining_total_sek],
    ];
    status.textContent = showingCurrent && estimate.forecast_confidence === "partial_data" ? "Delvis underlag" : showingCurrent ? "Estimerad" : selectedRecord?.coverage === "complete" ? "Fakturerad" : "Delvis underlag";
    kpis.replaceChildren(...currentRows.map(([label, value], index) => {
      const item = document.createElement("div");
      item.className = "cost-kpi";
      const name = document.createElement("span");
      name.textContent = label;
      const output = document.createElement("strong");
      const numericValue = finiteCostNumber(value);
      output.textContent = typeof value === "string" ? value : numericValue === null ? "–" : this._formatSek(numericValue);
      const comparison = kpiComparisons[index];
      const bubble = document.createElement("span");
      bubble.className = `cost-kpi-comparison${comparison.available ? ` ${comparison.direction}` : " unavailable"}`;
      if (comparison.available) {
        const percent = Number(comparison.difference_percent);
        if (!Number.isFinite(percent)) {
          bubble.textContent = "Ej jämförbart";
          bubble.classList.add("unavailable");
        } else {
          const sign = percent > 0 ? "+" : percent < 0 ? "−" : "";
          bubble.textContent = `${sign}${this._formatNumber(Math.abs(percent))} %`;
        }
      } else {
        bubble.textContent = "Ej jämförbart";
      }
      bubble.title = comparison.reason || "Jämförelse mot föregående månad";
      const valueRow = document.createElement("div");
      valueRow.className = "cost-kpi-value-row";
      valueRow.append(output, bubble);
      item.append(name, valueRow);
      return item;
    }));
    const dailyBreakdown = this._billingDailyByMonth.get(selectedMonth) || [];
    const series = buildDailyCostSeries(dailyBreakdown, selectedMonth);
    this._renderCostChart(chart, series);
    comparisonElement.replaceChildren();
    comparisonElement.append(...comparisons.map((comparison) => {
      const item = document.createElement("div");
      item.className = "cost-comparison-item";
      const label = document.createElement("span");
      label.className = "cost-comparison-label";
      label.textContent = comparison.label;
      const value = document.createElement("div");
      value.className = `cost-comparison-value${comparison.available ? ` ${comparison.direction}` : " unavailable"}`;
      if (comparison.available) {
        const direction = comparison.direction === "up" ? "Högre" : comparison.direction === "down" ? "Lägre" : "Oförändrad";
        const percent = comparison.difference_percent == null ? "" : ` · ${this._formatNumber(Math.abs(comparison.difference_percent))} %`;
        const partial = comparison.partial_baseline ? " · Delvis underlag" : "";
        value.textContent = `${direction} ${this._formatSek(Math.abs(comparison.difference_sek))}${percent}${partial}`;
      } else {
        value.textContent = "Ej tillgängligt";
      }
      item.append(label, value);
      return item;
    }));
    const rows = showingCurrent ? [
      ["Elhandel", estimate.trade?.total_so_far_sek],
      ["Elnät", estimate.grid?.total_so_far_sek],
      ["Fast kostnad", Number.isFinite(Number(estimate.trade?.accrued_fixed_fee_sek)) || Number.isFinite(Number(estimate.grid?.accrued_fixed_fee_sek)) ? (Number(estimate.trade?.accrued_fixed_fee_sek) || 0) + (Number(estimate.grid?.accrued_fixed_fee_sek) || 0) : null],
      ["Rörlig kostnad", Number.isFinite(Number(estimate.trade?.variable_cost_sek)) || Number.isFinite(Number(estimate.grid?.variable_cost_sek)) ? (Number(estimate.trade?.variable_cost_sek) || 0) + (Number(estimate.grid?.variable_cost_sek) || 0) : null],
      ["Import", Number.isFinite(Number(estimate.imported_kwh_so_far)) ? `${this._formatNumber(Number(estimate.imported_kwh_so_far))} kWh` : null],
      ["Beräknad import hela månaden", Number.isFinite(Number(estimate.forecast_import_kwh)) ? `${this._formatNumber(Number(estimate.forecast_import_kwh))} kWh` : null],
      ["Snittpris", Number.isFinite(Number(estimate.total_weighted_average_ore_per_kwh)) ? `${this._formatNumber(Number(estimate.total_weighted_average_ore_per_kwh))} öre/kWh` : null],
    ] : selectedRecord ? [
      ["Elhandel", selectedRecord.trade_sek == null ? "Saknas" : selectedRecord.trade_sek],
      ["Elnät", selectedRecord.grid_sek == null ? "Saknas" : selectedRecord.grid_sek],
      ["Känd kostnad", selectedRecord.known_amount_gross_sek],
      ["Total", selectedRecord.total_sek],
    ] : [];
    summary.replaceChildren(...rows.filter(([, value]) => value != null && (typeof value !== "number" || Number.isFinite(value))).map(([label, value]) => {
      const item = document.createElement("div");
      item.className = "cost-detail";
      const name = document.createElement("span");
      name.textContent = label;
      const output = document.createElement("strong");
      output.textContent = typeof value === "string" ? value : this._formatSek(Number(value));
      item.append(name, output);
      return item;
    }));
  }

  _renderCostChart(chart, series) {
    if (!chart) return;
    if (!series?.days?.length) {
      chart.innerHTML = '<div class="cost-chart-unavailable">Ingen daglig serie tillgänglig för vald månad</div>';
      return;
    }
    const width = 960;
    const height = 190;
    const plot = { left: 48, right: 12, top: 12, bottom: 28 };
    const all = series.days.map((day) => day.total_variable_cost_sek).filter((value) => Number.isFinite(value));
    const max = Math.max(1, ...all);
    const { x } = buildCostChartGeometry(width, plot, series.days_in_month);
    const y = (value) => plot.top + (1 - value / max) * (height - plot.top - plot.bottom);
    const grid = [0, .5, 1].map((ratio) => {
      const value = max * ratio;
      return `<line class="cost-chart-gridline" x1="${plot.left}" y1="${y(value)}" x2="${width - plot.right}" y2="${y(value)}" />`;
    }).join("");
    const axisOverlay = `<div class="chart-axis-overlay">${[0, .5, 1].map((ratio) => `<span class="chart-axis-overlay-label chart-axis-overlay-y-left" style="top:${(y(max * ratio) / height) * 100}%">${this._formatNumber(max * ratio)} kr</span>`).join("")}${[1, Math.ceil(series.days_in_month / 2), series.days_in_month].map((day) => `<span class="chart-axis-overlay-label chart-axis-overlay-x" data-cost-axis-day="${day}">${day}</span>`).join("")}</div>`;
    const barWidth = Math.max(3, (width - plot.left - plot.right) / Math.max(1, series.days_in_month) - 3);
    const bars = series.days.map((day) => {
      const value = Number.isFinite(day.total_variable_cost_sek) ? day.total_variable_cost_sek : 0;
      const barHeight = value > 0 ? Math.max(2, height - plot.bottom - y(value)) : 2;
      const className = day.status === "forecast" ? "cost-chart-bar cost-chart-bar-forecast" : day.status === "actual_plus_forecast" ? "cost-chart-bar cost-chart-bar-mixed" : day.available ? "cost-chart-bar cost-chart-bar-actual" : "cost-chart-bar cost-chart-bar-unavailable";
      return `<rect class="${className}" data-cost-day="${day.day}" x="${x(day.day) - barWidth / 2}" y="${height - plot.bottom - barHeight}" width="${barWidth}" height="${barHeight}" rx="2" />`;
    }).join("");
    chart.innerHTML = `<div class="cost-chart-legend"><span><i class="cost-chart-legend-actual"></i>Faktiskt</span><span><i class="cost-chart-legend-forecast"></i>Prognos</span><span><i class="cost-chart-legend-estimated"></i>Faktiskt + prognos</span></div><div class="cost-chart-plot"><svg class="cost-chart-svg" preserveAspectRatio="none" viewBox="0 0 ${width} ${height}" role="img" aria-label="Daglig rörlig kostnad över vald månad"><g>${grid}</g><g class="cost-chart-bars">${bars}</g><g class="cost-chart-hover" aria-hidden="true"></g><rect data-cost-chart-hit x="${plot.left}" y="${plot.top}" width="${width - plot.left - plot.right}" height="${height - plot.top - plot.bottom}" fill="transparent" /></svg>${axisOverlay}</div><div class="soc-tooltip" hidden></div>`;
    const svg = chart.querySelector("svg");
    const axis = chart.querySelector(".chart-axis-overlay");
    const screenMatrix = svg.getScreenCTM?.();
    const axisRect = axis?.getBoundingClientRect();
    if (screenMatrix && axisRect) {
      for (const tick of axis.querySelectorAll("[data-cost-axis-day]")) {
        const day = Number(tick.dataset.costAxisDay);
        tick.style.left = `${screenMatrix.a * x(day) + screenMatrix.e - axisRect.left}px`;
      }
    }
    const tooltip = chart.querySelector(".soc-tooltip");
    const hover = chart.querySelector(".cost-chart-hover");
    const nearest = (day) => series.days.reduce((best, point) => !best || Math.abs(point.day - day) < Math.abs(best.day - day) ? point : best, null);
    const clear = () => {
      tooltip.hidden = true;
      hover.replaceChildren();
    };
    const update = (event) => {
      const pointer = pointerToPlotCoordinates(svg, event, plot, width, height);
      if (!pointer?.inside) {
        clear();
        return;
      }
      const day = 1 + ((pointer.viewX - plot.left) / Math.max(1, width - plot.left - plot.right)) * (series.days_in_month - 1);
      const point = nearest(day);
      if (!point) {
        clear();
        return;
      }
      const fields = buildDailyCostTooltipFields(point).map((field) => ({ ...field, formatted: field.value }));
      if (!point) {
        clear();
        return;
      }
      renderSharedTooltip(tooltip, { title: `${point.day} ${this._formatInvoiceMonth(series.month || "").split(" ")[0]}`, fields });
      tooltip.hidden = false;
      const markerValue = Number.isFinite(point.total_variable_cost_sek) ? point.total_variable_cost_sek : 0;
      hover.innerHTML = `<rect class="chart-hover-marker" fill="${point.status === "forecast" ? "var(--secondary-text-color)" : "var(--el-solar-color, #77C2A1)"}" x="${x(point.day) - barWidth / 2}" y="${height - plot.bottom - Math.max(2, height - plot.bottom - y(markerValue))}" width="${barWidth}" height="${Math.max(2, height - plot.bottom - y(markerValue))}" rx="2" />`;
      positionChartTooltip(chart, tooltip, event.clientX, event.clientY, [], this._tooltipOrbit);
    };
    svg.addEventListener("pointerleave", clear);
    svg.addEventListener("pointercancel", clear);
    svg.addEventListener("pointerdown", update);
    svg.addEventListener("pointermove", update);
  }

  _bindCostCard() {
    const historyChart = this.host.querySelector("[data-cost-history-chart]");
    if (historyChart) historyChart.addEventListener("click", async (event) => {
      const button = event.target.closest?.("[data-cost-month]");
      if (!button) return;
      this._costSelectedMonth = button.dataset.costMonth || null;
      this._renderCostCard();
      if (this._costSelectedMonth && !this._billingDailyByMonth.has(this._costSelectedMonth)) {
        await this.loadBillingHistory(this._costSelectedMonth);
      }
    });
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
    const connectionChanged = Boolean(hass?.connection && this._eventConnection !== hass.connection);
    this.hass = hass;
    this._flushPerformanceWatchdogStartup();
    if (connectionChanged) {
      this._diagnosticsLifecycleGeneration += 1;
      this._diagnosticsRequestGeneration += 1;
      this._powerStateLifecycleGeneration += 1;
      this._powerStateRequestGeneration += 1;
    }
    this._bindDiagnostics(connectionChanged);
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
        () => {
          this.loadPriceData();
          this.loadBillingHistory();
        },
        "elrakning_price_update",
      );
      this._greenelyEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => {
          this.loadProviderState();
          this.loadRetainedHistory();
        },
        "elrakning_electricity_provider_update",
      );
      this._eonGridEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => this.loadEonGridState(),
        "elrakning_eon_grid_update",
      );
      this._meterEventUnsubscribePromise = hass.connection.subscribeEvents(
        (event) => {
          const entityId = event.data?.entity_id;
          const mapping = this._meterState || {};
          const phaseEntities = Object.values(mapping.phase_current_entities || {});
          if ([mapping.power_entity, mapping.energy_import_entity, mapping.energy_export_entity, ...phaseEntities].includes(entityId)) {
            this.loadMeterState();
          }
          // PowerManager owns live power state through elrakning_power_update;
          // generic state_changed must not reintroduce redundant power refreshes.
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
      this._solarForecastEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => this.loadSolarForecast(),
        "elrakning_solar_forecast_update",
      );
      this._loadForecastEventUnsubscribePromise = hass.connection.subscribeEvents(
        (event) => {
          const eventSiteId = event?.data?.site_id || null;
          const planSiteId = this._pricePlan?.site_id || null;
          const activeSiteId = this._siteState?.site_id
            || this._siteState?.current_site?.site_id
            || planSiteId;
          if (eventSiteId && (!activeSiteId || eventSiteId !== activeSiteId)) return;
          if (!eventSiteId && !activeSiteId) return;
          void Promise.allSettled([this.loadPowerHistory(), this.loadPricePlan()]);
          void this.loadBenchmarkEvidence();
        },
        "elrakning_load_forecast_update",
      );
      this._solarWeatherEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => this.loadPowerHistory(),
        "elrakning_solar_weather_update",
      );
      this._solarEvidenceEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => this.loadSolarEvidence(),
        "elrakning_solar_evidence_update",
      );
      this._benchmarkEvidenceEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => this.loadBenchmarkEvidence(),
        "elrakning_replay_benchmark_evidence_update",
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
    this._diagnosticsLifecycleGeneration += 1;
    this._diagnosticsRequestGeneration += 1;
    this._powerStateLifecycleGeneration += 1;
    this._powerStateRequestGeneration += 1;
    this._powerStateMutationGeneration += 1;
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
    if (this._eonGridEventUnsubscribePromise) {
      Promise.resolve(this._eonGridEventUnsubscribePromise)
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
      if (this._solarForecastEventUnsubscribePromise) {
        Promise.resolve(this._solarForecastEventUnsubscribePromise)
          .then((unsubscribe) => unsubscribe?.())
          .catch(() => {});
      }
      if (this._loadForecastEventUnsubscribePromise) {
        Promise.resolve(this._loadForecastEventUnsubscribePromise)
          .then((unsubscribe) => unsubscribe?.())
          .catch(() => {});
      }
    if (this._loadForecastEventUnsubscribePromise) {
      Promise.resolve(this._loadForecastEventUnsubscribePromise)
        .then((unsubscribe) => unsubscribe?.())
        .catch(() => {});
    }
    if (this._solarWeatherEventUnsubscribePromise) {
      Promise.resolve(this._solarWeatherEventUnsubscribePromise)
        .then((unsubscribe) => unsubscribe?.())
        .catch(() => {});
    }
    if (this._solarEvidenceEventUnsubscribePromise) {
      Promise.resolve(this._solarEvidenceEventUnsubscribePromise)
        .then((unsubscribe) => unsubscribe?.())
        .catch(() => {});
    }
    if (this._benchmarkEvidenceEventUnsubscribePromise) {
      Promise.resolve(this._benchmarkEvidenceEventUnsubscribePromise)
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
    this._eonGridEventUnsubscribePromise = null;
    this._meterEventUnsubscribePromise = null;
    this._meterPowerEventUnsubscribePromise = null;
    this._powerEventUnsubscribePromise = null;
    this._solarForecastEventUnsubscribePromise = null;
    this._loadForecastEventUnsubscribePromise = null;
    this._solarWeatherEventUnsubscribePromise = null;
    this._solarEvidenceEventUnsubscribePromise = null;
    this._diagnosticsEventUnsubscribePromise = null;
    this._readyEventUnsubscribePromise = null;
    this._connectionReadyListener = null;
    this._backendHydrationPromise = null;
    this._powerHistoryInFlight.clear();
    this._loadDiagnosticsState = null;
    this._diagnosticsBound = false;
    this._diagnosticsDomNodes = null;
    this._eventConnection = null;
    window.removeEventListener("resize", this._onThemeResize);
    window.removeEventListener("focus", this._onThemeFocus);
    document.removeEventListener("visibilitychange", this._onThemeVisibility);
    this._themeResizeObserver?.disconnect();
    this._themeResizeObserver = null;
    this._priceHeaderLayoutObserver?.disconnect();
    this._priceHeaderLayoutObserver = null;
    this._priceChartResizeObserver?.disconnect();
    this._priceChartResizeObserver = null;
    this._socCardHeightObserver?.disconnect();
    this._socCardHeightObserver = null;
    this._themeBackgroundReady = false;
    this._stopPerformanceWatchdog();
  }

  async _refreshBackendState(loadHistory = true) {
    if (this._backendHydrationPromise) return this._backendHydrationPromise;
    this._backendHydrationPromise = Promise.all([
      this.loadPriceData(),
      this.loadPricePlan(),
      this.loadProviderState(),
      this.loadEonGridState(),
      this.loadGridProviders(),
      this.loadRetainedHistory(),
      this.loadMeterState(loadHistory),
      this.loadPowerState(loadHistory),
      this.loadSolarEvidence(),
      this.loadBenchmarkEvidence(),
      this._loadDebugPreference(),
      this._loadChartPreferences(),
    ]).finally(() => {
      this._backendHydrationPromise = null;
      // Billing history is not required for initial live or chart history.
      // Defer its larger Recorder query until critical hydration is complete.
      void this.loadBillingHistory();
    });
    return this._backendHydrationPromise;
  }

  async loadPriceData(selectedDate = null) {
    if (!this.hass?.callWS) return;
    try {
      const request = { type: "elrakning/price_data" };
      const requestedDate = selectedDate instanceof Date ? selectedDate : null;
      if (requestedDate instanceof Date && Number.isFinite(requestedDate.getTime())) {
        request.date = `${requestedDate.getFullYear()}-${String(requestedDate.getMonth() + 1).padStart(2, "0")}-${String(requestedDate.getDate()).padStart(2, "0")}`;
      }
      const response = await this.hass.callWS(request);
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
    this._eonGridPrice = this.priceSnapshot.adjustments?.grid_price || null;
    this._updatePriceComparisonControls();
    this.updatePriceSummary();
    if (this.host.querySelector(".price-chart")) this.renderPriceChart();
    this._renderInvoiceEstimateCard();
  }

  async loadPricePlan(selectedDate = null) {
    if (!this.hass?.callWS) return;
    const siteState = await this._loadSiteIdentity();
    const requestedSiteId = siteState?.site_id || siteState?.current_site?.site_id
      || this._siteState?.site_id || this._siteState?.current_site?.site_id;
    if (!requestedSiteId) return;
    const requestToken = ++this._pricePlanRequestToken;
    const siteContextGeneration = this._siteContextGeneration;
    const previousPlan = this._pricePlan;
    const previousPlanContextKey = this._pricePlanContextKey
      || ellaPlanContextKey(previousPlan?.site_id, previousPlan?.date);
    try {
      const request = { type: "elrakning/ella_action_plan" };
      const requestedDate = selectedDate instanceof Date ? selectedDate : this._periodPickerState?.confirmed;
      const requestedDateKey = requestedDate instanceof Date && Number.isFinite(requestedDate.getTime())
        ? `${requestedDate.getFullYear()}-${String(requestedDate.getMonth() + 1).padStart(2, "0")}-${String(requestedDate.getDate()).padStart(2, "0")}`
        : previousPlan?.date || "";
      const requestContextKey = ellaPlanContextKey(requestedSiteId, requestedDateKey);
      if (requestedDate instanceof Date && Number.isFinite(requestedDate.getTime())) {
        request.date = requestedDateKey;
      }
      const response = await this.hass.callWS(request);
      if (requestToken !== this._pricePlanRequestToken || siteContextGeneration !== this._siteContextGeneration) return;
      const activeSiteId = this._siteState?.site_id || this._siteState?.current_site?.site_id || null;
      if (activeSiteId && response?.site_id && response.site_id !== activeSiteId) return;
      this._pricePlan = response && typeof response === "object"
        ? response
        : { available: false, reason: "invalid_plan_response", plan_blocks: [] };
      this._pricePlanContextKey = ellaPlanContextKey(
        this._pricePlan.site_id || requestedSiteId,
        this._pricePlan.date || requestedDateKey,
      );
      this._renderPricePlanCards();
      if (this.host.querySelector(".price-chart")) this.renderPriceChart();
    } catch {
      if (requestToken !== this._pricePlanRequestToken || siteContextGeneration !== this._siteContextGeneration) return;
      const requestedDate = selectedDate instanceof Date ? selectedDate : this._periodPickerState?.confirmed;
      const requestedDateKey = requestedDate instanceof Date && Number.isFinite(requestedDate.getTime())
        ? `${requestedDate.getFullYear()}-${String(requestedDate.getMonth() + 1).padStart(2, "0")}-${String(requestedDate.getDate()).padStart(2, "0")}`
        : previousPlan?.date || "";
      const requestedSiteId = this._siteState?.site_id
        || this._siteState?.current_site?.site_id
        || previousPlan?.site_id
        || null;
      const requestContextKey = ellaPlanContextKey(requestedSiteId, requestedDateKey);
      if (shouldPreserveEllaPlanOnTransportError(previousPlan, previousPlanContextKey, requestContextKey)) return;
      this._pricePlan = { available: false, reason: "plan_unavailable", plan_blocks: [] };
      this._pricePlanContextKey = requestContextKey;
      this._renderPricePlanCards();
    }
  }

  _bindPhaseHistoryCard() {
    for (const button of this.host.querySelectorAll("[data-phase-metric]")) {
      button.addEventListener("click", () => {
        this._phaseHistoryMetric = button.dataset.phaseMetric;
        for (const item of this.host.querySelectorAll("[data-phase-metric]")) {
          const active = item.dataset.phaseMetric === this._phaseHistoryMetric;
          item.classList.toggle("active", active);
          item.setAttribute("aria-pressed", String(active));
        }
        this._persistChartPreferences({ phase_history_metric: this._phaseHistoryMetric });
        this._renderPhaseHistoryCard();
      });
    }
    const summary = this.host.querySelector("[data-phase-history-summary]");
    const togglePhaseSummary = (event) => {
      const item = event.target.closest("[data-phase-summary]");
      if (!item || !summary.contains(item)) return;
      const phase = item.dataset.phaseSummary;
      if (!Object.hasOwn(this._phaseHistoryVisible, phase)) return;
      this._phaseHistoryVisible[phase] = item.getAttribute("aria-pressed") !== "true";
      this._syncPhaseHistoryVisibilityButtons();
      this._persistChartPreferences({ phase_history_visible: { ...this._phaseHistoryVisible } });
      this._renderPhaseHistoryCard();
    };
    summary?.addEventListener("click", togglePhaseSummary);
    summary?.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      togglePhaseSummary(event);
    });
    this._syncPhaseHistoryMetricButtons();
    this._syncPhaseHistoryVisibilityButtons();
    const copy = this.host.querySelector("[data-phase-history-copy]");
    copy?.addEventListener("click", () => {
      if (!this._debugEnabled || !this._meterPowerHistory?.phase_history) return;
      const metricLabels = { current: "Ström", voltage: "Spänning", active_power: "Effekt" };
      const phaseHistory = this._meterPowerHistory.phase_history;
      this._showSourceDataDialog("Source data", `Faser · ${metricLabels[this._phaseHistoryMetric] || this._phaseHistoryMetric}`, {
          metric: this._phaseHistoryMetric,
          active_phases: Object.keys(this._phaseHistoryVisible).filter((phase) => this._phaseHistoryVisible[phase]),
          phase_color_map: PHASE_COLOR_MAP,
          ...buildPhaseProvenance(
            this._phaseHistoryMetric,
            {
              ...(this._meterState || {}),
              phase_source_entities: this._meterPowerHistory.phase_source_entities || this._meterState?.phase_source_entities || {},
              phase_discovery_method: this._meterPowerHistory.phase_discovery_method || this._meterState?.phase_discovery_method || null,
            },
            this._meterPowerHistory,
            this.hass?.states || {},
          ),
          history_cache: {
            period_key: this._meterPowerHistory.date || null,
            loaded_at: this._meterPowerHistory.loaded_at || null,
            metric: this._phaseHistoryMetric,
            point_counts: phaseHistoryPointCounts(phaseHistory),
            recorder_loaded: this._meterHistorySummary?.success === true,
            last_live_merge_at: this._meterPowerHistory.last_live_merge_at || null,
            last_live_timestamp: this._meterPowerHistory.last_live_timestamp || null,
          },
          recorder_history: phaseHistory,
          sampling: {
            bucket_size_minutes: 5,
            method: "nearest_sample_per_five_minute_slot",
            raw_point_count: Object.values(phaseHistory[this._phaseHistoryMetric] || {}).reduce((count, series) => count + (Array.isArray(series?.points) ? series.points.length : 0), 0),
            rendered_point_count: Object.values(this._phaseRenderedHistory?.[this._phaseHistoryMetric] || {}).reduce((count, points) => count + (Array.isArray(points) ? points.length : 0), 0),
          },
          rendered_phase_history: this._phaseRenderedHistory?.[this._phaseHistoryMetric] || {},
          live_values: {
            current: this._meterState?.phase_current_a || {},
            voltage: this._meterState?.phase_voltage_v || {},
            active_power: this._meterState?.phase_active_power_kw || {},
          },
          rendered_history: phaseHistory[this._phaseHistoryMetric] || {},
        });
    });
  }

  _renderPhaseHistoryCard() {
    const card = this.host.querySelector("[data-phase-history-card]");
    const chart = this.host.querySelector("[data-phase-history-chart]");
    const summary = this.host.querySelector("[data-phase-history-summary]");
    if (!card || !chart || !summary) return;
    const history = this._meterPowerHistory?.phase_history || {};
    const metric = this._phaseHistoryMetric;
    const source = history[metric] || {};
    const rawPhasePoints = Object.fromEntries(["l1", "l2", "l3"].map((phase) => [
      phase,
      this._phaseHistoryVisible[phase] && Array.isArray(source[phase]?.points) ? source[phase].points.filter((point) => Number.isFinite(Number(point.value))) : [],
    ]));
    const cardAvailable = phaseHistoryAvailable(history, this._meterState || {});
    const hasActivePoints = Object.values(rawPhasePoints).some((points) => points.length);
    card.hidden = !cardAvailable;
    const copy = this.host.querySelector("[data-phase-history-copy]");
    if (copy) copy.hidden = !this._debugEnabled || !cardAvailable;
    const labels = { current: ["Ström", "A"], voltage: ["Spänning", "V"], active_power: ["Effekt", "kW"] };
    const [label, unit] = labels[metric];
    const live = metric === "current" ? this._meterState?.phase_current_a : metric === "voltage" ? this._meterState?.phase_voltage_v : this._meterState?.phase_active_power_kw;
    for (const phase of ["l1", "l2", "l3"]) {
      let item = summary.querySelector(`[data-phase-summary="${phase}"]`);
      if (!item) {
        item = document.createElement("div");
        item.dataset.phaseSummary = phase;
        item.tabIndex = 0;
        item.setAttribute("role", "button");
        const strong = document.createElement("strong");
        const indicator = document.createElement("i");
        indicator.className = `phase-history-phase-indicator ${phase}`;
        const phaseLabel = document.createElement("span");
        phaseLabel.className = `phase-history-phase-label ${phase}`;
        phaseLabel.textContent = phase.toUpperCase();
        item.append(indicator, phaseLabel, strong);
        summary.append(item);
      }
      const active = this._phaseHistoryVisible[phase] === true;
      item.className = `phase-history-summary-item ${phase}${active ? " active" : " inactive"}`;
      item.setAttribute("aria-pressed", String(active));
      const value = live?.[phase] != null ? Number(live[phase]) : rawPhasePoints[phase].at(-1)?.value;
      const formattedValue = metric === "voltage"
        ? Number(value).toLocaleString("sv-SE", { maximumFractionDigits: 1, minimumFractionDigits: 1 })
        : this._formatNumber(metric === "current" ? Math.abs(Number(value)) : Number(value));
      item.querySelector("strong").textContent = Number.isFinite(Number(value)) ? `${formattedValue} ${unit}` : "—";
      item.querySelector(".phase-history-phase-indicator").style.backgroundColor = PHASE_COLOR_MAP[phase];
    }
    if (!hasActivePoints) {
      chart.innerHTML = cardAvailable ? '<div class="phase-history-empty">Välj minst en fas</div>' : "";
      return;
    }
    const renderedWidth = chart.clientWidth || 960;
    const geometry = buildPhaseChartGeometry(renderedWidth, { metric });
    const { width, height, compact } = geometry;
    const plot = { left: geometry.plotLeft, right: geometry.plotRight, top: geometry.plotTop, bottom: geometry.plotBottom };
    const allPoints = Object.values(rawPhasePoints).flat();
    const timestamps = allPoints.map((point) => new Date(point.timestamp).getTime()).filter(Number.isFinite);
    const minTime = Math.min(...timestamps);
    const rawAxisEnd = phaseHistoryAxisEnd(allPoints);
    const firstDate = new Date(minTime);
    const dayStart = new Date(firstDate.getFullYear(), firstDate.getMonth(), firstDate.getDate()).getTime();
    const dayEndDate = new Date(dayStart);
    dayEndDate.setDate(dayEndDate.getDate() + 1);
    const useDayAxis = rawAxisEnd <= dayEndDate.getTime();
    const axisStart = useDayAxis ? dayStart : minTime;
    const phasePoints = Object.fromEntries(Object.entries(rawPhasePoints).map(([phase, points]) => [
      phase,
      buildCanonicalPhasePoints(points, axisStart, rawAxisEnd),
    ]));
    const axisEnd = phaseHistoryAxisEnd(Object.values(phasePoints).flat()) || rawAxisEnd;
    const timeRange = Math.max(1, axisEnd - axisStart);
    const fuse = resolveFuseAmpere(this._meterState, this._eonGridState);
    const renderedPhaseHistory = { [metric]: phasePoints };
    this._phaseRenderedHistory = renderedPhaseHistory;
    if (!Object.values(phasePoints).some((points) => points.length)) {
      chart.innerHTML = cardAvailable ? '<div class="phase-history-empty">Välj minst en fas</div>' : "";
      this._phaseRenderSignature = "empty";
      return;
    }
    const renderDomain = buildPhaseRenderDomain(allPoints, metric, fuse);
    const renderSignature = JSON.stringify({ metric, axisStart, axisEnd, fuse, phasePoints, geometry, domain: renderDomain });
    if (renderSignature === this._phaseRenderSignature && chart.querySelector(".phase-history-svg")) return;
    this._phaseRenderSignature = renderSignature;
    const { minValue, maxValue } = renderDomain;
    const x = (timestamp) => plot.left + ((new Date(timestamp).getTime() - axisStart) / timeRange) * (width - plot.left - plot.right);
    const y = (value) => plot.top + (maxValue - value) / (maxValue - minValue) * (height - plot.top - plot.bottom);
    const phaseColors = PHASE_COLOR_MAP;
    const grid = [0, 0.5, 1].map((ratio) => {
      const value = maxValue - ratio * (maxValue - minValue);
      return `<line class="phase-history-gridline" x1="${plot.left}" y1="${y(value)}" x2="${width - plot.right}" y2="${y(value)}" />`;
    }).join("");
    const yAxisLabels = [0, 0.5, 1].map((ratio) => {
      const value = maxValue - ratio * (maxValue - minValue);
      return `<span class="phase-history-axis-label" style="top:${(y(value) / height) * 100}%">${this._formatNumber(value)} ${unit}</span>`;
    }).join("");
    const threshold = metric === "current" && Number.isFinite(fuse) && fuse > 0
      ? `<line class="phase-history-threshold" x1="${plot.left}" y1="${y(fuse)}" x2="${width - plot.right}" y2="${y(fuse)}" /><text class="phase-history-reference-label" x="${width - plot.right - 4}" y="${y(fuse) - 4}" text-anchor="end">${this._formatNumber(fuse)} A · Säkring</text>`
      : "";
    const zero = metric === "active_power" ? `<line class="phase-history-zero-line" x1="${plot.left}" y1="${y(0)}" x2="${width - plot.right}" y2="${y(0)}" /><text class="phase-history-reference-label" x="${width - plot.right - 4}" y="${y(0) - 4}" text-anchor="end">0 kW</text>` : "";
    const tickCount = useDayAxis ? 8 : 6;
    const candidateTimeTicks = Array.from({ length: tickCount + 1 }, (_, index) => axisStart + timeRange * index / tickCount);
    const timeTicks = selectPhaseTimeTicks(candidateTimeTicks, geometry.plotWidth, compact ? 56 : 90);
    const timeAxis = timeTicks.map((timestamp, index) => {
      const date = new Date(timestamp);
      const labelText = useDayAxis ? date.toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" }) : date.toLocaleDateString("sv-SE", { day: "2-digit", month: "2-digit" });
      const transform = index === 0 ? "none" : index === timeTicks.length - 1 ? "translateX(-100%)" : "translateX(-50%)";
      return `<span class="phase-history-time-label" style="left:${(x(timestamp) / width) * 100}%;transform:${transform}">${labelText}</span>`;
    }).join("");
    const lines = Object.entries(phasePoints).map(([phase, points]) => {
      const segments = [];
      let segment = [];
      for (const point of points) {
        const previous = segment.at(-1);
        if (previous && new Date(point.timestamp).getTime() - new Date(previous.timestamp).getTime() > 5 * 60 * 1000) {
          if (segment.length > 1) segments.push(segment);
          segment = [];
        }
        segment.push(point);
      }
      if (segment.length > 1) segments.push(segment);
      const real = segments.map((items) => {
        const d = items.map((point, index) => `${index ? "L" : "M"} ${x(point.timestamp)} ${y(Number(point.value))}`).join(" ");
        return `<path class="phase-history-line" stroke="${phaseColors[phase]}" d="${d}" />`;
      }).join("");
      const interpolated = buildContinuousGapPairs(points, "value").map(([from, to]) => (
        `<path class="phase-history-line chart-interpolated-line" stroke="${phaseColors[phase]}" d="M ${x(from.timestamp)} ${y(Number(from.value))} L ${x(to.timestamp)} ${y(Number(to.value))}" />`
      )).join("");
      return `${real}${interpolated}`;
    }).join("");
    const svgMarkup = `<g data-phase-dynamic="grid">${grid}</g><g data-phase-dynamic="threshold">${threshold}</g><g data-phase-dynamic="zero">${zero}</g><g data-phase-dynamic="lines">${lines}</g><g class="phase-history-hover" aria-hidden="true"></g>`;
    const existingSvg = chart.querySelector(".phase-history-svg");
    const existingAxisOverlay = chart.querySelector(".phase-history-axis-overlay");
    if (existingSvg
      && existingAxisOverlay
      && existingSvg.querySelector('[data-phase-dynamic="grid"]')
      && existingSvg.querySelector('[data-phase-dynamic="threshold"]')
      && existingSvg.querySelector('[data-phase-dynamic="zero"]')
      && existingSvg.querySelector('[data-phase-dynamic="lines"]')) {
      existingSvg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      existingSvg.querySelector('[data-phase-dynamic="grid"]').innerHTML = grid;
      existingSvg.querySelector('[data-phase-dynamic="threshold"]').innerHTML = threshold;
      existingSvg.querySelector('[data-phase-dynamic="zero"]').innerHTML = zero;
      existingSvg.querySelector('[data-phase-dynamic="lines"]').innerHTML = lines;
      existingAxisOverlay.innerHTML = `${yAxisLabels}${timeAxis}`;
      this._phaseRenderSignature = renderSignature;
      this._phaseInteraction = {
        plot, width, height, axisStart, timeRange, phasePoints, phaseColors, metric, unit, x, y,
        svg: existingSvg,
        tooltip: chart.querySelector(".soc-tooltip"),
        hover: existingSvg.querySelector(".phase-history-hover"),
        canonicalTimestamps: [...new Set(Object.values(phasePoints).flat().map((point) => point.timestamp))]
          .sort((left, right) => new Date(left).getTime() - new Date(right).getTime()),
      };
      return;
    }
    // Recreate the interactive SVG when the canonical render state changes.
    // This prevents pointer handlers from retaining stale metric closures.
    chart.replaceChildren();
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("phase-history-svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${label} per fas`);
    const tooltip = document.createElement("div");
    tooltip.className = "soc-tooltip";
    tooltip.hidden = true;
    const axisOverlay = document.createElement("div");
    axisOverlay.className = "phase-history-axis-overlay";
    axisOverlay.innerHTML = `${yAxisLabels}${timeAxis}`;
    chart.append(svg, axisOverlay, tooltip);
    svg.innerHTML = svgMarkup;
    const hover = svg.querySelector(".phase-history-hover");
    const canonicalTimestamps = [...new Set(Object.values(phasePoints).flat().map((point) => point.timestamp))]
      .sort((left, right) => new Date(left).getTime() - new Date(right).getTime());
    const nearestCanonicalTimestamp = (timestamp) => canonicalTimestamps.reduce(
      (best, candidate) => !best || Math.abs(new Date(candidate).getTime() - timestamp.getTime())
        < Math.abs(new Date(best).getTime() - timestamp.getTime()) ? candidate : best,
      null,
    );
    const pointsAtCanonicalTimestamp = (timestamp) => Object.fromEntries(
      Object.entries(phasePoints).map(([phase, points]) => [
        phase,
        points.find((point) => point.timestamp === timestamp) || null,
      ]),
    );
    this._phaseInteraction = { plot, width, height, axisStart, timeRange, phasePoints, phaseColors, metric, unit, x, y, svg, tooltip, hover, canonicalTimestamps };
    const update = (event) => {
      const state = this._phaseInteraction || {};
      const activeSvg = state.svg || svg;
      const activePlot = state.plot || plot;
      const activeWidth = state.width || width;
      const activeHeight = state.height || height;
      const activeAxisStart = state.axisStart || axisStart;
      const activeTimeRange = state.timeRange || timeRange;
      const activePhasePoints = state.phasePoints || phasePoints;
      const activePhaseColors = state.phaseColors || phaseColors;
      const activeMetric = state.metric || metric;
      const activeUnit = state.unit || unit;
      const activeTooltip = state.tooltip || tooltip;
      const activeHover = state.hover || hover;
      const activeX = state.x || x;
      const activeY = state.y || y;
      const activeTimestamps = state.canonicalTimestamps || canonicalTimestamps;
      const pointer = pointerToPlotCoordinates(activeSvg, event, activePlot, activeWidth, activeHeight);
      if (!pointer?.inside) {
        clear();
        return;
      }
      const ratio = (pointer.viewX - activePlot.left) / Math.max(1, activeWidth - activePlot.left - activePlot.right);
      const timestamp = new Date(activeAxisStart + ratio * activeTimeRange);
      const selectedTimestamp = activeTimestamps.reduce(
        (best, candidate) => !best || Math.abs(new Date(candidate).getTime() - timestamp.getTime())
          < Math.abs(new Date(best).getTime() - timestamp.getTime()) ? candidate : best,
        null,
      );
      const selected = Object.fromEntries(Object.entries(activePhasePoints).map(([phase, points]) => [
        phase,
        points.find((point) => point.timestamp === selectedTimestamp) || null,
      ]));
      const fields = Object.entries(selected).filter(([, point]) => point).map(([phase, point]) => ({ label: phase.toUpperCase(), value: point.value, color: activePhaseColors[phase], formatted: `${activeMetric === "voltage" ? Number(point.value).toLocaleString("sv-SE", { maximumFractionDigits: 1, minimumFractionDigits: 1 }) : this._formatNumber(activeMetric === "current" ? Math.abs(Number(point.value)) : Number(point.value))} ${activeUnit}` }));
      renderSharedTooltip(activeTooltip, { title: new Date(selectedTimestamp).toLocaleString("sv-SE", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }), fields });
      activeTooltip.hidden = false;
      activeHover.innerHTML = Object.entries(selected).filter(([, point]) => point).map(([phase, point]) => `<circle class="chart-hover-marker" fill="${activePhaseColors[phase]}" cx="${activeX(point.timestamp)}" cy="${activeY(Number(point.value))}" r="4" />`).join("");
      positionChartTooltip(chart, activeTooltip, event.clientX, event.clientY, [], this._tooltipOrbit);
    };
    const clear = () => { tooltip.hidden = true; hover.replaceChildren(); };
    svg.addEventListener("pointermove", update);
    svg.addEventListener("pointerleave", clear);
  }

  async loadBillingHistory(targetMonth = null) {
    if (!this.hass?.callWS) return;
    const siteState = await this._loadSiteIdentity();
    const siteId = siteState?.site_id || siteState?.current_site?.site_id
      || this._siteState?.site_id || this._siteState?.current_site?.site_id;
    if (!siteId) return;
    try {
      const response = await this.hass.callWS({ type: "elrakning/billing_history", ...(targetMonth ? { month: targetMonth } : {}) });
      if (response?.success === true && response.target_month && Array.isArray(response.daily_breakdown)) {
        this._billingDailyByMonth.set(response.target_month, response.daily_breakdown);
      }
      if (!targetMonth) {
        this._billingHistory = response?.success === true ? response : null;
        this._billingHistoryStatus = response?.success === true ? null : response?.error || "billing_history_unavailable";
        this._costUnavailableReason = this._billingHistoryStatus === "site_unconfigured"
          ? "meter_not_configured"
          : this._billingHistoryStatus === "history_unavailable"
            ? "history_missing"
            : "billing_history_unavailable";
      }
      if (response?.success === true && this._invoiceEstimateRaw) {
        this._invoiceEstimateRaw.daily_breakdown_by_month = Object.fromEntries(this._billingDailyByMonth);
      }
    } catch {
      this._billingHistory = null;
      this._billingHistoryStatus = "billing_history_unavailable";
      this._costUnavailableReason = "billing_history_unavailable";
    }
    this._renderInvoiceEstimateCard();
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

  async loadEonGridState() {
    if (!this.hass?.callWS) return;
    try {
      const state = await this.hass.callWS({ type: "elrakning/grid/state" });
      this._applyEonGridState(state);
    } catch {
      // Keep the optional E.ON grid card unconfigured when state is unavailable.
    }
  }

  async loadGridProviders() {
    if (!this.hass?.callWS) return;
    try {
      const response = await this.hass.callWS({ type: "elrakning/grid/providers" });
      this._gridProviders = Array.isArray(response?.providers) ? response.providers : [];
      const select = this.host.querySelector("[data-grid-provider]");
      if (select) this._renderGridProviderOptions(select);
    } catch {
      this._gridProviders = [];
    }
  }

  _renderGridProviderOptions(select) {
    select.replaceChildren(...(this._gridProviders || []).map((provider) => {
      const option = document.createElement("option");
      option.value = provider.id;
      option.textContent = provider.name;
      return option;
    }));
  }

  _applyEonGridState(state) {
    const previousFuseAmpere = resolveFuseAmpere(this._meterState, this._eonGridState);
    this._eonGridState = state;
    this._eonGridPrice = state?.grid_price || state?.tariff?.grid_price || null;
    const configured = state?.configured === true;
    this._updatePriceComparisonControls();
    const status = this.host.querySelector("[data-eon-grid-status]");
    const provider = this.host.querySelector('[data-provider-name="elnet"]');
    const summary = this.host.querySelector("[data-eon-grid-summary]");
    const remove = this.host.querySelector("[data-eon-grid-remove]");
    const sourceButton = this.host.querySelector("[data-eon-grid-source]");
    if (!status || !provider || !summary) return;
    const agreement = state?.agreement || {};
    const facility = state?.facility || {};
    const tariff = state?.tariff || {};
    const consumption = state?.consumption || {};
    const cost = state?.cost || {};
    const dailyMaxPhaseCurrentA = Number.isFinite(Number(state?.daily_max_phase_current_a))
      ? Number(state.daily_max_phase_current_a)
      : this._meterPowerHistory?.daily_max_phase_current_a;
    const dailyFuseUtilizationPercent = Number.isFinite(Number(state?.daily_max_fuse_utilization_percent))
      ? Number(state.daily_max_fuse_utilization_percent)
      : this._meterPowerHistory?.daily_max_fuse_utilization_percent;
    const fuseAmpere = resolveFuseAmpere(this._meterState, state);
    const dailyMaxPhaseBase = state?.daily_max_phase || this._meterPowerHistory?.daily_max_phase || buildDailyMaxPhase(
      state?.daily_phase_max || this._meterPowerHistory?.daily_phase_max,
      fuseAmpere,
    );
    const fuseChanged = previousFuseAmpere !== fuseAmpere;
    const dailyMaxPhase = dailyMaxPhaseBase
      ? {
        ...dailyMaxPhaseBase,
        fuse_ampere: dailyMaxPhaseBase.fuse_ampere ?? (Number.isFinite(fuseAmpere) && fuseAmpere > 0 ? fuseAmpere : null),
        utilization_percent: dailyMaxPhaseBase.utilization_percent ?? (Number.isFinite(fuseAmpere) && fuseAmpere > 0 ? dailyMaxPhaseBase.ampere / fuseAmpere * 100 : null),
      }
      : null;
    provider.textContent = configured && state?.provider_name ? `${state.provider_name} · Elnät` : "";
    provider.hidden = !configured;
    const outage = state?.outage || {};
    status.textContent = configured
      ? outage.status === "outage"
        ? "Driftstörning"
        : outage.status === "no_known_outage"
          ? "Ingen känd driftstörning"
          : agreement.status === "future"
            ? "Konfigurerad"
            : agreement.status === "active"
              ? "Konfigurerad"
              : "Ej aktivt"
      : "Ej konfigurerad";
    status.hidden = false;
    remove && (remove.hidden = !configured);
    if (sourceButton) sourceButton.hidden = !this._debugEnabled || !configured;
    const rows = [];
    if (agreement.name) rows.push(["Avtal", agreement.name]);
    if (agreement.start_date) rows.push(["Avtal från", agreement.start_date]);
    if (facility.address?.street) rows.push(["Adress", facility.address.street]);
    if (facility.fuse_ampere != null) rows.push(["Säkring", `${this._formatNumber(facility.fuse_ampere)} A`]);
    if (facility.price_area) rows.push(["Elområde", facility.price_area]);
    if (facility.grid_area) rows.push(["Nätområde", facility.grid_area]);
    if (Number.isFinite(dailyMaxPhaseCurrentA)) {
      const phaseLabel = dailyMaxPhase?.phase ? `${dailyMaxPhase.phase.toUpperCase()} · ` : "";
      const fuseLabel = Number.isFinite(Number(dailyMaxPhase?.fuse_ampere ?? fuseAmpere))
        ? ` / ${this._formatNumber(Number(dailyMaxPhase.fuse_ampere ?? fuseAmpere))} A`
        : "";
      rows.push(["Max fas idag", `${phaseLabel}${this._formatNumber(dailyMaxPhase?.ampere ?? dailyMaxPhaseCurrentA)}${fuseLabel}`]);
    }
    if (Number.isFinite(dailyFuseUtilizationPercent)) {
      rows.push(["Högsta säkringsandel", `${this._formatNumber(dailyFuseUtilizationPercent)} %`]);
    }
    if (consumption.status === "ok") rows.push(["Förbrukning", `${this._formatNumber(consumption.consumption_kwh)} kWh`]);
    if (tariff.subscription_fee_sek_per_month != null) rows.push(["Abonnemang", this._formatSek(tariff.subscription_fee_sek_per_month) + "/mån"]);
    if (tariff.transfer_fee_ore_per_kwh != null) rows.push(["Överföring", `${this._formatNumber(tariff.transfer_fee_ore_per_kwh)} öre/kWh`]);
    if (tariff.energy_tax_ore_per_kwh != null) rows.push(["Energiskatt", `${this._formatNumber(tariff.energy_tax_ore_per_kwh)} öre/kWh`]);
    if (tariff.estimated_yearly_cost_sek != null) rows.push(["Beräknad årskostnad", this._formatSek(tariff.estimated_yearly_cost_sek)]);
    if (cost.total_sek != null) rows.push(["E.ON-kostnad", this._formatSek(cost.total_sek)]);
    summary.replaceChildren(...rows.flatMap(([label, value]) => {
      const left = document.createElement("strong");
      left.textContent = label;
      const right = document.createElement("span");
      right.textContent = value;
      return [left, right];
    }));
    summary.hidden = !configured || rows.length === 0;
    this._renderInvoiceCardCosts();
    this._updatePriceComparisonControls();
    if (this.host.querySelector(".price-chart") && this.priceData.periods.length) this.renderPriceChart();
    this._renderInvoiceEstimateCard();
    if (fuseChanged) this._renderPhaseHistoryCard();
  }

  _bindEonGridDialog() {
    const opens = this.host.querySelectorAll("[data-eon-grid-configure], [data-eon-grid-card-configure]");
    const dialog = this.host.querySelector("[data-eon-grid-dialog]");
    const appAccount = this.host.querySelector("[data-eon-grid-app-account]");
    const appPassword = this.host.querySelector("[data-eon-grid-app-password]");
    const result = this.host.querySelector("[data-eon-grid-result]");
    const appSave = this.host.querySelector("[data-eon-grid-app-save]");
    const cancel = this.host.querySelector("[data-eon-grid-cancel]");
    const remove = this.host.querySelector("[data-eon-grid-remove]");
    const providerSelect = this.host.querySelector("[data-grid-provider]");
    if (!opens.length || !dialog || !appAccount || !appPassword || !result || !appSave || !cancel || !remove || !providerSelect) return;
    this._renderGridProviderOptions(providerSelect);
    const close = () => {
      dialog.hidden = true;
      appAccount.value = "";
      appPassword.value = "";
      result.textContent = "";
    };
    const openDialog = async () => {
      dialog.hidden = false;
      if (!this._gridProviders?.length) await this.loadGridProviders();
      appAccount.focus();
    };
    opens.forEach((open) => open.addEventListener("click", openDialog));
    cancel.addEventListener("click", close);
    remove.addEventListener("click", async () => {
      remove.disabled = true;
      try { this._applyEonGridState(await this.hass.callWS({ type: "elrakning/grid/remove" })); close(); } finally { remove.disabled = false; }
    });
    appSave.addEventListener("click", async () => {
      if (!appAccount.value.trim() || !appPassword.value) return;
      appSave.disabled = true;
      result.textContent = "Verifierar session …";
      try {
          const selectedProvider = this._gridProviders?.find((item) => item.id === providerSelect.value);
          const authMethod = selectedProvider?.auth_methods?.[0];
          if (!selectedProvider || !authMethod) throw new Error("unsupported_provider");
          const response = await this.hass.callWS({ type: "elrakning/grid/login", provider: selectedProvider.id, auth_method: authMethod, account_id: appAccount.value.trim(), password: appPassword.value });
        if (!response.success) throw new Error(response.error || "configuration_failed");
        this._applyEonGridState(response);
        result.textContent = "E.ON är konfigurerat";
        window.setTimeout(close, 900);
      } catch (error) {
        result.textContent = error.message === "reauth_required" ? "E.ON-inloggningen behöver göras om." : "E.ON-inloggningen kunde inte verifieras.";
      } finally { appSave.disabled = false; }
    });
  }

  _applyProviderState(state) {
    this._electricityProviderState = state;
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
    this._updatePriceComparisonControls();
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
    const phaseDependenciesChanged = phaseMeterStateDependenciesChanged(this._meterState, state, this._eonGridState);
    const phaseChart = this.host.querySelector("[data-phase-history-chart]");
    const phaseDomNeedsRender = phaseChartDomNeedsRender(phaseChart);
    this._meterState = state;
    this._updateLivePhaseMaxima(state?.phase_current_a);
    const provider = this.host.querySelector('[data-provider-name="elmatare"]');
    const source = this.host.querySelector("[data-meter-source]");
    const label = providerLabel(state?.provider_name, state?.device_name);
    if (provider) {
      provider.textContent = label;
      provider.hidden = !label;
    }
    if (source) source.hidden = !this._debugEnabled || state?.configured !== true;
    this._renderLivePowerRow();
    this._renderMergedMeterSummary();
    if (phaseDependenciesChanged || phaseDomNeedsRender) this._renderPhaseHistoryCard();
  }

  _updateLivePhaseMaxima(phaseCurrentA, timestamp = new Date()) {
    if (!phaseCurrentA || typeof phaseCurrentA !== "object") return;
    const date = timestamp.toLocaleDateString("sv-SE");
    if (this._meterPowerHistory?.date !== date) {
      this._meterPowerHistory = {
        ...createMeterPowerHistoryState(date),
        ...this._meterPowerHistory,
        date,
        points: [],
        phase_history: {},
        daily_phase_max: {},
        daily_max_phase: null,
        daily_max_phase_current_a: null,
        daily_max_fuse_utilization_percent: null,
      };
    }
    const dailyPhaseMax = mergeDailyPhaseMaxima(this._meterPowerHistory.daily_phase_max, phaseCurrentA, timestamp);
    this._meterPowerHistory = {
      ...this._meterPowerHistory,
      daily_phase_max: dailyPhaseMax,
      daily_max_phase_current_a: Math.max(
        ...Object.values(dailyPhaseMax).map((item) => Number(item?.ampere)).filter(Number.isFinite),
        0,
      ) || null,
    };
    const fuseAmpere = resolveFuseAmpere(this._meterState, this._eonGridState);
    this._meterPowerHistory.daily_max_phase = buildDailyMaxPhase(dailyPhaseMax, fuseAmpere);
    const dailyMax = this._meterPowerHistory.daily_max_phase_current_a;
    this._meterPowerHistory.daily_max_fuse_utilization_percent = Number.isFinite(dailyMax) && Number.isFinite(fuseAmpere) && fuseAmpere > 0
      ? dailyMax / fuseAmpere * 100
      : null;
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
      const fuseAmpere = resolveFuseAmpere(this._meterState, this._eonGridState);
      const responseDate = response?.date || null;
      const existingDate = this._meterPowerHistory?.date || null;
      const samePeriod = !existingDate || !responseDate || existingDate === responseDate;
      const previousHistory = samePeriod ? this._meterPowerHistory : createMeterPowerHistoryState(responseDate);
      this._meterPowerHistory = {
        date: responseDate,
        points: Array.isArray(response?.points) ? response.points : previousHistory.points || [],
        phase_current_history: response?.phase_current_history || {},
        phase_history: mergePhaseHistory(previousHistory.phase_history, response?.phase_history),
        phase_source_entities: response?.phase_source_entities || this._meterState?.phase_source_entities || {},
        phase_discovery_method: response?.phase_discovery_method || this._meterState?.phase_discovery_method || null,
        daily_phase_max: response?.daily_phase_max || {},
        daily_max_phase: response?.daily_max_phase || buildDailyMaxPhase(response?.daily_phase_max || {}, fuseAmpere),
        daily_max_phase_current_a: Number.isFinite(Number(response?.daily_max_phase_current_a)) ? Number(response.daily_max_phase_current_a) : null,
        phase_current_source_entities: response?.phase_current_source_entities || this._meterState?.phase_current_source_entities || {},
        phase_current_discovery_method: response?.phase_current_discovery_method || this._meterState?.phase_current_discovery_method || null,
        loaded_at: new Date().toISOString(),
        last_live_merge_at: previousHistory.last_live_merge_at || null,
        last_live_timestamp: previousHistory.last_live_timestamp || null,
      };
      const dailyMaxPhase = this._meterPowerHistory.daily_max_phase_current_a;
      this._meterPowerHistory.daily_max_fuse_utilization_percent = Number.isFinite(dailyMaxPhase) && Number.isFinite(fuseAmpere) && fuseAmpere > 0
        ? dailyMaxPhase / fuseAmpere * 100
        : null;
      this._refreshDailyEnergyStateFromAcceptedHistory();
      this._rebuildLivePowerMaxima();
      if (this._eonGridState?.configured === true) this._applyEonGridState(this._eonGridState);
      this._renderPhaseHistoryCard();
      this._renderMergedMeterSummary();
      this._meterHistorySummary = response.history || {
        entity_id: response?.entity_id || entityId,
        success: true,
        date: response?.date || null,
        point_count: this._meterPowerHistory.points.length,
      };
    } catch (error) {
      if (requestToken !== this._meterHistoryRequestToken) return;
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
    const hasPhaseData = Boolean(point?.phase_current_a || point?.phase_voltage_v || point?.phase_active_power_kw);
    if (hasPhaseData) {
      this._updateLivePhaseMaxima(point.phase_current_a, point.timestamp ? new Date(point.timestamp) : new Date());
    }
    const meterMerge = mergeMeterPowerHistoryPoint(
      this._meterPowerHistory,
      point,
      this._meterState?.power_entity,
    );
    this._meterPowerHistory = meterMerge.history;
    if (hasPhaseData) this._renderLivePowerRow();
    if (!point?.timestamp || (point.entity_id && point.entity_id !== this._meterState?.power_entity)) {
      if (meterMerge.phaseRenderChanged) this._renderPhaseHistoryCard();
      return;
    }
    const phaseRenderChanged = meterMerge.phaseRenderChanged;
    if (phaseRenderChanged) this._renderPhaseHistoryCard();
    if (this.host.querySelector(".price-chart")
      && this._getPriceChartLiveSignature() !== this._priceChartLiveSignature) {
      this.renderPriceChart({ liveUpdate: true });
    }
  }

  _periodCustomerPrice(period) {
    return this._comparisonPrice(period);
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
    if (this._priceComparisonVisible.grid && this._hasGridPriceData()) {
      const rawGrid = period.grid_cost_ex_vat;
      const grid = rawGrid === null || rawGrid === undefined || rawGrid === ""
        ? null
        : Number(rawGrid);
      if (Number.isFinite(grid)) subtotal += grid;
    }
    return subtotal * 125;
  }

  _hasGridPriceData() {
    return this.priceData.periods.length > 0
      && this.priceData.periods.every((period) => {
        const rawGrid = period.grid_cost_ex_vat;
        return period.grid_contract_source_status === "ACTIVE"
          && rawGrid !== null
          && rawGrid !== undefined
          && rawGrid !== ""
          && Number.isFinite(Number(rawGrid));
      });
  }

  _hasTradePriceData() {
    return this._providerConfigured === true
      && this.priceData.periods.length > 0
      && this.priceData.periods.every((period) => Number.isFinite(Number(period.electricity_cost_ex_vat)));
  }

  _updatePriceComparisonControls() {
    const availability = {
      electricity: this._hasTradePriceData(),
      grid: this._eonGridState?.configured === true && this._hasGridPriceData(),
    };
    const titles = {
      electricity: "Visa elhandelskostnad i prisjämförelsen",
      grid: "Visa elnätskostnad i prisjämförelsen",
    };
    const unavailableTitles = {
      electricity: "Elhandel saknas",
      grid: "Elnätspris saknas",
    };
    for (const [layer, available] of Object.entries(availability)) {
      const control = this.host.querySelector(`[data-price-layer="${layer}"]`);
      const input = control?.querySelector("[data-price-toggle]");
      if (!control || !input) continue;
      input.disabled = !available;
      input.checked = available && this._priceComparisonVisible[layer];
      control.title = available ? titles[layer] : unavailableTitles[layer];
      control.classList.toggle("is-disabled", !available);
    }
  }

  _syncPriceComparisonControls() {
    for (const control of this.host.querySelectorAll("[data-price-layer]")) {
      const layer = control.dataset.priceLayer;
      const input = control.querySelector("[data-price-toggle]");
      if (input && typeof this._priceComparisonVisible[layer] === "boolean") {
        input.checked = this._priceComparisonVisible[layer];
      }
    }
  }

  updatePriceSummary() {
    const sourcePeriods = Array.isArray(this.priceSnapshot?.periods)
      ? this.priceSnapshot.periods
      : [];
    const periods = this._periodPickerState?.mode === "hour"
      ? selectHourlyPricePeriods(sourcePeriods, this._periodPickerState.confirmed)
      : sourcePeriods;
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
        history_source: point.history_source || null,
        history_interval_id: point.history_interval_id || null,
        source_resolution_seconds: Number.isFinite(Number(point.source_resolution_seconds))
          ? Number(point.source_resolution_seconds)
          : null,
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

  _getPriceChartLiveSignature() {
    const periods = this.priceData?.periods || [];
    if (!periods.length) return JSON.stringify({ periods: 0 });
    const firstTimestamp = new Date(periods[0].start).getTime();
    if (!Number.isFinite(firstTimestamp)) return JSON.stringify({ periods: periods.length });
    const dayStart = new Date(firstTimestamp);
    dayStart.setHours(0, 0, 0, 0);
    const dayStartMs = dayStart.getTime();
    const slotMs = 5 * 60 * 1000;
    const historyTimestamps = [
      ...(Array.isArray(this._meterPowerHistory?.points) ? this._meterPowerHistory.points : []),
      ...Object.values(this._powerHistory?.series || {}).flatMap((series) => Array.isArray(series?.points) ? series.points : []),
    ].map((point) => new Date(point.timestamp).getTime()).filter(Number.isFinite);
    const anchorTimestamp = historyTimestamps.length ? Math.max(...historyTimestamps) : Date.now();
    const slotTimestamp = Math.floor(anchorTimestamp / slotMs) * slotMs;
    const pointSignature = (points, valueKeys) => {
      const selected = nearestMeterPoint(points, slotTimestamp, slotMs / 2);
      if (!selected) return null;
      return {
        timestamp: selected.timestamp || null,
        values: valueKeys.map((key) => normalizeMeterValue(selected[key])),
      };
    };
    const meterPoints = Array.isArray(this._meterPowerHistory?.points) ? this._meterPowerHistory.points : [];
    const power = {};
    for (const key of ["solar", "consumption", "charging", "discharging"]) {
      const points = Array.isArray(this._powerHistory?.series?.[key]?.points)
        ? this._powerHistory.series[key].points
        : [];
      power[key] = pointSignature(points.map((point) => ({
        timestamp: point.timestamp,
        import_kw: point.value_kw,
      })), ["import_kw"]);
    }
    return JSON.stringify({
      date: new Date(dayStartMs).toISOString().slice(0, 10),
      periods: periods.length,
      slot: slotTimestamp,
      meter: pointSignature(meterPoints, ["import_kw", "export_kw"]),
      power,
    });
  }

  _getPriceChartRenderCacheKey() {
    const pointSignature = (points) => {
      const values = Array.isArray(points) ? points : [];
      const first = values[0];
      const last = values.at(-1);
      const compact = (point) => point ? [point.timestamp || null, point.value_kw ?? point.value ?? null, point.import_kw ?? null, point.export_kw ?? null] : null;
      return [values.length, compact(first), compact(last)];
    };
    const series = Object.fromEntries(["solar", "consumption", "charging", "discharging"].map((key) => [
      key,
      pointSignature(this._powerHistory?.series?.[key]?.points),
    ]));
    const forecast = Object.fromEntries(["solar", "consumption", "charging", "discharging", "import", "export"].map((key) => [
      key,
      pointSignature(this._powerHistory?.power_forecast?.series?.[key]?.forecast_points),
    ]));
    const widthBucket = Math.max(1, Math.round((this._priceChartRenderedWidth || 960) / 16) * 16);
    return JSON.stringify({
      site: this._siteState?.site_id || this._siteState?.current_site?.site_id || null,
      date: this._periodPickerState?.confirmed ? localDateKey(this._periodPickerState.confirmed) : null,
      mode: this._periodPickerState?.mode || null,
      width: widthBucket,
      selection: this._ellaSelection
        ? [this._ellaSelection.id, this._ellaSelection.start, this._ellaSelection.end, this._ellaSelection.revision]
        : null,
      periods: [this.priceData?.periods?.length || 0, this.priceData?.periods?.[0]?.start || null, this.priceData?.periods?.at(-1)?.end || null],
      layers: this._effectiveChartLayerState(),
      series,
      forecast,
    });
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
    const color = chartSeriesColor(className);
    const segments = this.buildMeterDisplaySegments(points, key).map((segment) => {
      if (segment.length < 2) return "";
      return `<path class="${className}" fill="none" stroke="${color}" d="${this.buildSmoothMeterPath(segment, key, x, meterY)}" />`;
    }).join("");
    const interpolated = buildContinuousGapPairs(points, key).map(([from, to]) => {
      if (!isVisiblePowerValue(from?.[key]) || !isVisiblePowerValue(to?.[key])) return "";
      return `<path class="${className} chart-interpolated-line" fill="none" stroke="${color}" d="M ${x(from.timestamp)} ${meterY(from[key])} L ${x(to.timestamp)} ${meterY(to[key])}" />`;
    }).join("");
    return `${segments}${interpolated}`;
  }

  buildForecastDisplayMarkup(points, key, className, x, meterY) {
    const color = chartSeriesColor(className);
    return buildForecastSegments(points, key).map((segment) => (
      `<path class="${className}" fill="none" stroke="${color}" d="${this.buildSmoothMeterPath(segment, key, x, meterY)}" />`
    )).join("");
  }

  buildMeterDisplayAreaMarkup(points, key, className, x, meterY) {
    const color = chartSeriesColor(className);
    const segments = this.buildMeterDisplaySegments(points, key).map((segment) => {
      if (segment.length < 2) return "";
      const first = segment[0];
      const last = segment.at(-1);
      const firstX = x(first.timestamp);
      const lastX = x(last.timestamp);
      const baselineY = meterY(0);
      return `<path class="${className}" fill="${color}" d="M ${firstX} ${baselineY} L ${firstX} ${meterY(first[key])} ${this.buildSmoothMeterPath(segment, key, x, meterY).slice(1)} L ${lastX} ${baselineY} Z" />`;
    }).join("");
    const interpolated = buildContinuousGapPairs(points, key).map(([from, to]) => {
      if (!isVisiblePowerValue(from?.[key]) || !isVisiblePowerValue(to?.[key])) return "";
      const baselineY = meterY(0);
      return `<path class="${className} chart-interpolated-area" fill="${color}" d="M ${x(from.timestamp)} ${baselineY} L ${x(from.timestamp)} ${meterY(from[key])} L ${x(to.timestamp)} ${meterY(to[key])} L ${x(to.timestamp)} ${baselineY} Z" />`;
    }).join("");
    return `${segments}${interpolated}`;
  }

  renderPriceChart(options = {}) {
    const started = performance.now();
    if (this._periodPickerState?.mode !== "hour") {
      this._renderAggregatedPriceChart();
      this._recordSlowRender("price-chart", performance.now() - started);
      return;
    }
    const averageToggle = this.host.querySelector('[data-meter-legend] [data-chart-layer="average"]');
    if (averageToggle) averageToggle.hidden = false;
    this._renderHourlyPriceChart(options);
    this._recordSlowRender("price-chart", performance.now() - started);
  }

  _updateAggregatedPriceSummary(data) {
    const availablePrices = data.filter((item) => Number.isFinite(item.price));
    const weightedDuration = availablePrices.reduce((sum, item) => sum + Number(item.price_duration_ms || 0), 0);
    const average = weightedDuration > 0
      ? availablePrices.reduce((sum, item) => sum + item.price * Number(item.price_duration_ms || 0), 0) / weightedDuration
      : null;
    const lowest = availablePrices.reduce((result, item) => !result || item.price < result ? item.price : result, null);
    const highest = availablePrices.reduce((result, item) => !result || item.price > result ? item.price : result, null);
    for (const [key, value] of [["average", average], ["lowest", lowest], ["highest", highest]]) {
      const element = this.host.querySelector(`[data-price="${key}"]`);
      if (!element) continue;
      element.textContent = Number.isFinite(value) ? this.formatPrice(value) : "–";
      element.classList.remove("cheap", "normal", "expensive");
      if (key === "lowest" && Number.isFinite(value)) element.classList.add("cheap");
      if (key === "highest" && Number.isFinite(value)) element.classList.add("expensive");
      const time = this.host.querySelector(`[data-time="${key}"]`);
      if (time) time.textContent = "";
    }
  }

  _renderAggregatedPriceChart() {
    const chart = this.host.querySelector(".price-chart");
    if (!chart || !this.priceData.periods.length) return;
    const mode = this._periodPickerState.mode;
    const selectedDate = this._periodPickerState.confirmed;
    const aggregatedPeriods = this._billingHistory ? (this._billingHistory.price_periods || []) : [];
    const aggregatedMeterPoints = this._billingHistory ? (this._billingHistory.energy_points || []) : [];
    const priceForPeriod = (period) => this._comparisonPrice(period);
    const data = aggregatePriceAndEnergyByPeriod(
      aggregatedPeriods,
      aggregatedMeterPoints,
      this._powerHistory?.series,
      mode,
      selectedDate,
      priceForPeriod,
    );
    const legend = this.host.querySelector("[data-meter-legend]");
    if (legend) {
      legend.hidden = data.length === 0;
      const averageToggle = legend.querySelector('[data-chart-layer="average"]');
      if (averageToggle) averageToggle.hidden = true;
    }
    if (!data.length) {
      chart.innerHTML = '<div class="empty-chart"><strong>Ingen data för vald period.</strong></div>';
      return;
    }
    this._updateAggregatedPriceSummary(data);
    const width = 960;
    const height = 350;
    const priceValues = data.map((item) => item.price).filter(Number.isFinite);
    const energyValues = data.flatMap((item) => Object.values(item.energy)).filter(Number.isFinite);
    const priceMax = Math.max(1, ...priceValues);
    const energyMax = Math.max(1, ...energyValues);
    const leftAxisLabels = [0, .5, 1].map((ratio) => this._formatNumber(energyMax * ratio));
    const rightAxisLabels = [0, .5, 1].map((ratio) => this._formatNumber(priceMax * ratio));
    const renderedWidth = chart.getBoundingClientRect().width || chart.clientWidth || width;
    this._priceChartRenderedWidth = renderedWidth;
    const geometry = buildPriceChartGeometry(width, height, {
      dualAxis: true,
      containerWidth: renderedWidth,
      leftAxisLabels,
      rightAxisLabels,
      leftAxisGutter: measuredPriceAxisGutter(chart, leftAxisLabels),
      rightAxisGutter: measuredPriceAxisGutter(chart, rightAxisLabels),
    });
    chart.style.setProperty("--price-axis-left-gutter", `${(geometry.leftInset / width) * 100}%`);
    chart.style.setProperty("--price-axis-right-gutter", `${(geometry.rightInset / width) * 100}%`);
    const { plot, plotWidth, plotHeight } = geometry;
    const bands = buildPriceCategoryBands(plot.left, width - plot.right, data.length);
    const xStep = bands[0]?.end - bands[0]?.start || plotWidth;
    const x = (index) => bands[index]?.center ?? plot.left;
    const priceY = (value) => plot.top + (1 - value / priceMax) * plotHeight;
    const energyY = (value) => plot.top + (1 - value / energyMax) * plotHeight;
    const series = [
      ["price", "Pris", "priceNormal", priceY, "ore/kWh"],
      ["import", "Köp", "import", energyY, "kWh"],
      ["export", "Sälj", "export", energyY, "kWh"],
      ["solar", "Sol", "solar", energyY, "kWh"],
      ["consumption", "Last", "consumption", energyY, "kWh"],
      ["charging", "Laddning", "charging", energyY, "kWh"],
      ["discharging", "Urladdning", "discharging", energyY, "kWh"],
    ];
    const layers = this._effectiveChartLayerState();
    const visibleSeries = series.filter(([key]) => key === "price" ? layers.spot : layers[key]);
    const seriesCount = Math.max(1, visibleSeries.length);
    const barWidth = Math.max(2, Math.min(18, xStep / seriesCount - 3));
    const groupWidth = seriesCount * barWidth + (seriesCount - 1);
    const bars = data.map((item, index) => visibleSeries.map(([key, , colorKey, scale], seriesIndex) => {
      const value = key === "price" ? item.price : item.energy[key];
      if (!Number.isFinite(value)) return "";
      const yValue = scale(value);
      const color = key === "price" ? chartColor("priceNormal") : chartColor(colorKey);
      return `<rect class="aggregated-chart-bar aggregated-chart-${key}" data-group-index="${index}" fill="${color}" x="${x(index) - groupWidth / 2 + seriesIndex * (barWidth + 1)}" y="${yValue}" width="${barWidth}" height="${plot.top + plotHeight - yValue}" rx="1" />`;
    }).join("")).join("");
    const grid = [0, .5, 1].map((ratio) => `<line class="chart-meter-gridline" x1="${plot.left}" y1="${plot.top + (1 - ratio) * plotHeight}" x2="${width - plot.right}" y2="${plot.top + (1 - ratio) * plotHeight}" />`).join("");
    const axisOverlay = `<div class="chart-axis-overlay">${[0, .5, 1].map((ratio, index) => `<span class="chart-axis-overlay-label chart-axis-overlay-y-left" style="top:${((plot.top + (1 - ratio) * plotHeight) / height) * 100}%">${leftAxisLabels[index]}</span><span class="chart-axis-overlay-label chart-axis-overlay-y-right" style="top:${((plot.top + (1 - ratio) * plotHeight) / height) * 100}%">${rightAxisLabels[index]}</span>`).join("")}${data.map((item, index) => `<span class="chart-axis-overlay-label chart-axis-overlay-x" data-group-index="${index}" style="left:${(x(index) / width) * 100}%">${item.label}</span>`).join("")}</div>`;
    chart.innerHTML = `<svg class="chart-svg aggregated-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Aggregerat elpris och energi"><g>${grid}</g>${bars}<rect class="aggregated-chart-hit" x="${plot.left}" y="${plot.top}" width="${plotWidth}" height="${plotHeight}" fill="transparent" /></svg>${axisOverlay}<div class="chart-tooltip" hidden></div>`;
    const svg = chart.querySelector("svg");
    const tooltip = chart.querySelector(".chart-tooltip");
    const groupNodes = [...svg.querySelectorAll("[data-group-index]")];
    const clearGroupHover = () => {
      groupNodes.forEach((node) => node.classList.remove("hovered", "dimmed"));
    };
    const setGroupHover = (index) => {
      groupNodes.forEach((node) => {
        const active = Number(node.dataset.groupIndex) === index;
        node.classList.toggle("hovered", active);
        node.classList.toggle("dimmed", !active);
      });
    };
    const show = (event) => {
      const bounds = svg.getBoundingClientRect();
      const viewX = ((event.clientX - bounds.left) / bounds.width) * width;
      const viewY = ((event.clientY - bounds.top) / bounds.height) * height;
      const index = aggregatedPriceGroupIndex(viewX, plot.left, plotWidth, data.length);
      if (index < 0 || viewY < plot.top || viewY > plot.top + plotHeight) { tooltip.hidden = true; clearGroupHover(); return; }
      setGroupHover(index);
      const item = data[index];
      const fields = [];
      if (layers.spot && Number.isFinite(item.price)) fields.push({ label: "Pris", value: item.price, formatted: `${this.formatPrice(item.price)} öre/kWh` });
      for (const [key, label] of [["import", "Köp"], ["export", "Sälj"], ["solar", "Sol"], ["consumption", "Last"], ["charging", "Laddning"], ["discharging", "Urladdning"]]) {
        if (layers[key] && Number.isFinite(item.energy[key])) fields.push({ label, value: item.energy[key], formatted: `${this._formatNumber(item.energy[key])} kWh` });
      }
      renderSharedTooltip(tooltip, { title: item.label, fields });
      tooltip.hidden = false;
      positionChartTooltip(chart, tooltip, event.clientX, event.clientY, [], this._tooltipOrbit);
    };
    svg.addEventListener("mousemove", show);
    svg.addEventListener("mouseleave", () => { tooltip.hidden = true; clearGroupHover(); });
  }

  _renderHourlyPriceChart(options = {}) {
    const chart = this.host.querySelector(".price-chart");
    if (!chart) return;
    const liveUpdate = options.liveUpdate === true;
    const renderCacheKey = this._getPriceChartRenderCacheKey();
    if (!liveUpdate && this._priceChartRenderCacheKey === renderCacheKey && chart.querySelector(".chart-svg")) {
      this._lastPowerChartRenderStats = { ...(this._lastPowerChartRenderStats || {}), cache_hit: true };
      return;
    }

    if (!this.priceData.periods.length) {
      this._priceChartLiveSignature = this._getPriceChartLiveSignature();
      const legend = this.host.querySelector("[data-meter-legend]");
      if (legend) legend.hidden = true;
      const message = this.priceData.error === "site_unconfigured"
        ? "<strong>Ej konfigurerad</strong>"
        : this.priceData.error === "missing_integration"
        ? "<strong>Ingen Nord Pool-sensor hittades.</strong><span>Lägg till Nord Pool i Home Assistant för att visa dagens elpris.</span>"
        : "<strong>Dagens Nord Pool-priser kunde inte hämtas.</strong>";
      chart.innerHTML = `<div class="empty-chart">${message}</div>`;
      return;
    }

    const periods = this._periodPickerState?.mode === "hour"
      ? selectHourlyPricePeriods(this.priceData.periods, this._periodPickerState.confirmed)
      : this.priceData.periods;
    if (!periods.length) {
      this._priceChartLiveSignature = this._getPriceChartLiveSignature();
      const legend = this.host.querySelector("[data-meter-legend]");
      if (legend) legend.hidden = true;
      chart.innerHTML = "<div class=\"empty-chart\"><strong>Ingen prisdata för vald dag.</strong></div>";
      return;
    }
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
    const axisLabels = ["0 kW", "5 kW", "10 kW"];
    const renderedWidth = chart.getBoundingClientRect().width || chart.clientWidth || width;
    this._priceChartRenderedWidth = renderedWidth;
    const geometry = buildPriceChartGeometry(width, height, {
      containerWidth: renderedWidth,
      leftAxisLabels: axisLabels,
      leftAxisGutter: measuredPriceAxisLabelGutter(chart, axisLabels),
    });
    chart.style.setProperty("--price-axis-left-gutter", `${(geometry.leftInset / width) * 100}%`);
    chart.style.setProperty("--price-axis-right-gutter", `${(geometry.rightInset / width) * 100}%`);
    const { plot, plotWidth, plotHeight } = geometry;
    const valueRange = range || 1;
    const y = (price) => plot.top + ((maximum - price) / valueRange) * plotHeight;
    const zeroY = Math.max(plot.top, Math.min(plot.top + plotHeight, y(0)));
    const firstStart = new Date(periods[0].start);
    const dayStart = new Date(firstStart.getFullYear(), firstStart.getMonth(), firstStart.getDate());
    const dayEnd = new Date(dayStart);
    dayEnd.setDate(dayEnd.getDate() + 1);
    const dayDuration = dayEnd.getTime() - dayStart.getTime();
    this._chartGeometry = {
      ...geometry,
      dayStartMs: dayStart.getTime(),
      dayDuration,
    };
    const now = new Date();
    const actualDayEnd = localDateKey(dayStart) === localDateKey(now)
      ? now.getTime()
      : dayEnd.getTime();
    const currentPeriod = periods.find((period) => {
      const start = new Date(period.start);
      const end = new Date(period.end);
      return start <= now && now < end;
    });
    const x = (timestamp) => plot.left + ((new Date(timestamp).getTime() - dayStart.getTime()) / dayDuration) * plotWidth;
    const energyHistory = this.priceSnapshot?.energy_history || {};
    const rawMeterPoints = Array.isArray(this._meterPowerHistory?.points)
      ? this._meterPowerHistory.points.filter((point) => {
        const timestamp = new Date(point.timestamp).getTime();
        return !forecastPointIsMarked(point)
          && Number.isFinite(timestamp) && timestamp >= dayStart.getTime() && timestamp <= actualDayEnd;
      })
      : [];
    const historicalMeterPoints = energyHistoryToMeterStepPoints(energyHistory).filter((point) => (
      point.timestamp >= dayStart.getTime() && point.timestamp <= actualDayEnd
    ));
    const useHistoricalMeter = rawMeterPoints.length === 0 && historicalMeterPoints.length > 0;
    const meterPoints = useHistoricalMeter ? historicalMeterPoints : rawMeterPoints;
    this._meterTooltipPoints = meterPoints;
    const meterCanonicalPoints = useHistoricalMeter
      ? meterPoints
      : this.buildCanonicalMeterPoints(meterPoints, dayStart, dayEnd);
    this._meterCanonicalPoints = meterCanonicalPoints;
    this._meterCanonicalPointMap = new Map(
      meterCanonicalPoints
        .filter((point) => point.raw_timestamp !== null)
        .map((point) => [point.timestamp, point]),
    );
    const renderBudget = Math.min(1024, Math.max(128, Math.ceil(renderedWidth * 2)));
    const meterRenderPoints = decimateDisplayPoints(meterPoints, {
      targetPoints: renderBudget,
      valueKeys: ["import_kw", "export_kw"],
    });
    const historicalMeterDisplayPoints = energyHistoryToMeterCurvePoints(energyHistory).filter((point) => (
      point.timestamp >= dayStart.getTime() && point.timestamp <= actualDayEnd
    ));
    const meterDisplayPoints = useHistoricalMeter
      ? this.prepareMeterDisplayPoints(decimateDisplayPoints(historicalMeterDisplayPoints, {
        targetPoints: renderBudget,
        valueKeys: ["import_kw", "export_kw"],
      }))
      : this.prepareMeterDisplayPoints(this.buildCanonicalMeterPoints(meterRenderPoints, dayStart, dayEnd));
    const powerCanonicalPoints = {};
    const powerDisplayPoints = {};
    const powerDisplayGeometry = {};
    for (const key of ["solar", "consumption", "charging", "discharging"]) {
      const rawPoints = Array.isArray(this._powerHistory?.series?.[key]?.points)
        ? this._powerHistory.series[key].points.filter((point) => {
          const timestamp = new Date(point.timestamp).getTime();
          return !forecastPointIsMarked(point)
            && Number.isFinite(timestamp) && timestamp >= dayStart.getTime() && timestamp <= actualDayEnd;
        })
        : [];
      const historicalPoints = energyIntervalsToStepPoints(energyHistory?.series?.[key]).filter((point) => (
        point.timestamp >= dayStart.getTime() && point.timestamp <= actualDayEnd
      ));
      const useHistoricalPower = rawPoints.length === 0 && historicalPoints.length > 0;
      const renderRawPoints = decimateDisplayPoints(rawPoints, {
        targetPoints: renderBudget,
        valueKeys: ["value_kw"],
      });
      powerCanonicalPoints[key] = useHistoricalPower
        ? historicalPoints
        : this.buildCanonicalPowerPoints(renderRawPoints, dayStart, dayEnd);
      const historicalPowerDisplayPoints = energyIntervalsToCurvePoints(energyHistory?.series?.[key]).filter((point) => (
        point.timestamp >= dayStart.getTime() && point.timestamp <= actualDayEnd
      ));
      const displaySource = useHistoricalPower
        ? decimateDisplayPoints(historicalPowerDisplayPoints, {
          targetPoints: renderBudget,
          valueKeys: ["value_kw"],
        })
        : powerCanonicalPoints[key];
      powerDisplayPoints[key] = displaySource.map((point) => ({
        ...point,
        value_kw: Number.isFinite(Number(point.value_kw)) ? Number(point.value_kw) : null,
      }));
    }
    this._lastPowerChartRenderStats = {
      cache_hit: false,
      render_budget: renderBudget,
      raw_points: {
        meter: meterPoints.length,
        solar: this._powerHistory?.series?.solar?.points?.length || 0,
        consumption: this._powerHistory?.series?.consumption?.points?.length || 0,
        charging: this._powerHistory?.series?.charging?.points?.length || 0,
        discharging: this._powerHistory?.series?.discharging?.points?.length || 0,
      },
      display_points: {
        meter: meterDisplayPoints.length,
        solar: powerDisplayPoints.solar.length,
        consumption: powerDisplayPoints.consumption.length,
        charging: powerDisplayPoints.charging.length,
        discharging: powerDisplayPoints.discharging.length,
      },
    };
    const activeSiteId = this._siteState?.site_id || this._siteState?.current_site?.site_id || this._pricePlan?.site_id || null;
    const loadForecastPoints = selectLoadForecastPoints(this._loadForecast?.frames, {
      siteId: activeSiteId,
      selectedDate: dayStart,
      now,
    });
    const forecastSeries = this._powerHistory?.power_forecast?.series || {};
    const forecastSource = (key, fallback) => forecastSeries[key]?.available === true ? forecastSeries[key] : fallback;
    const forecastSources = {
      import: forecastSource("import", this._meterPowerHistory),
      export: forecastSource("export", this._meterPowerHistory),
      solar: forecastSource("solar", this._powerHistory?.series?.solar),
      consumption: forecastSource("consumption", this._powerHistory?.series?.consumption),
      charging: forecastSource("charging", this._powerHistory?.series?.charging),
      discharging: forecastSource("discharging", this._powerHistory?.series?.discharging),
    };
    const powerForecastPoints = Object.fromEntries(
      Object.entries(forecastSources).map(([key, source]) => [key, selectPowerForecastPoints(source, {
        siteId: activeSiteId,
        selectedDate: dayStart,
        now,
        includeElapsed: false,
      })]),
    );
    if (loadForecastPoints.length) powerForecastPoints.consumption = loadForecastPoints;
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
    const forecastMaximum = Math.max(
      0,
      ...Object.values(powerForecastPoints).flatMap((points) => points.map((point) => Math.abs(Number(point.value_kw))))
        .filter(Number.isFinite),
    );
    const hasActualPowerData = meterDisplayPoints.some((point) => (
      Number.isFinite(Number(point.import_kw)) || Number.isFinite(Number(point.export_kw))
    )) || Object.values(powerDisplayPoints).some((points) => points.some((point) => Number.isFinite(Number(point.value_kw))));
    const hasForecastPowerData = Object.values(powerForecastPoints).some((points) => points.length > 0);
    const meterBase = hasActualPowerData
      ? Math.max(10, meterMaximum)
      : hasForecastPowerData
        ? Math.max(1, forecastMaximum)
        : 10;
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
    const powerForecastLinesFor = (key, className, visible) => visible && powerForecastPoints[key]?.length > 1
      ? this.buildForecastDisplayMarkup(powerForecastPoints[key], "value_kw", `${className} chart-power-forecast`, x, meterY)
      : "";
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
      powerForecastLinesFor("import", "chart-meter-import", visibleLayers.import),
      powerForecastLinesFor("export", "chart-meter-export", visibleLayers.export),
      powerLinesFor("solar", "chart-power-solar", visibleLayers.solar),
      powerLinesFor("consumption", "chart-power-consumption", visibleLayers.consumption),
      powerForecastLinesFor("solar", "chart-power-solar", visibleLayers.solar),
      powerForecastLinesFor("consumption", "chart-power-consumption", visibleLayers.consumption),
      powerLinesFor("charging", "chart-power-charging", visibleLayers.charging),
      powerLinesFor("discharging", "chart-power-discharging", visibleLayers.discharging),
      powerForecastLinesFor("charging", "chart-power-charging", visibleLayers.charging),
      powerForecastLinesFor("discharging", "chart-power-discharging", visibleLayers.discharging),
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
      ? meterGridLevels.map((level) => `<line class="chart-meter-gridline" x1="${plot.left}" y1="${meterY(level)}" x2="${width - plot.right}" y2="${meterY(level)}" />`).join("")
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
        trade_customer_price_ore_per_kwh: Number(period.trade_customer_price_ore_per_kwh),
        grid_provider: period.grid_provider || null,
        grid_contract_source_status: period.grid_contract_source_status || null,
        grid_contract_preview_applied: period.grid_contract_preview_applied === true,
        grid_vat_included: period.grid_vat_included === true,
        grid_transfer_ore_per_kwh: Number(period.grid_transfer_ore_per_kwh),
        grid_energy_tax_ore_per_kwh: Number(period.grid_energy_tax_ore_per_kwh),
        grid_variable_ore_per_kwh: Number(period.grid_variable_ore_per_kwh),
        total_customer_price_ore_per_kwh: Number(period.total_customer_price_ore_per_kwh),
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
      const edges = buildHourlyBarEdges(period.start, period.end, dayStart, dayEnd, plot.left, width - plot.right);
      if (!edges) return "";
      const barColor = chartColor(category === "cheap" ? "priceCheap" : category === "expensive" ? "priceExpensive" : "priceNormal");
      return `<rect class="chart-bar ${category}" fill="${barColor}" data-index="${index}" x="${edges.left}" y="${top}" width="${Math.max(1, edges.right - edges.left)}" height="${Math.max(1, bottom - top)}" rx="1" />`;
    }).join("") : "";
    const hourLabels = buildHourlyBoundaryHours(renderedWidth).map((hour) => {
      const hourDate = new Date(dayStart);
      hourDate.setHours(hourDate.getHours() + hour);
      const edge = hour === 0 ? " edge-start" : hour === 24 ? " edge-end" : "";
      return `<span class="chart-axis-overlay-label chart-axis-overlay-x${edge}" style="left:${(x(hourDate) / width) * 100}%">${String(hour).padStart(2, "0")}</span>`;
    }).join("");
    const axisOverlayMarkup = `<div class="chart-axis-overlay">${meterVisible ? meterGridLevels.map((level) => `<span class="chart-axis-overlay-label chart-axis-overlay-y-left" style="top:${(meterY(level) / height) * 100}%">${this._formatNumber(level)} kW</span>`).join("") : ""}${hourLabels}</div>`;
    const legend = this.host.querySelector("[data-meter-legend]");
    if (legend) legend.hidden = periods.length === 0 && meterPoints.length === 0;
    this._chartHoverGeometry = {
      x,
      y,
      meterY,
      meterDisplayY: (key, timestamp) => this.meterDisplayYAt(meterDisplayGeometry[key], timestamp, x),
      powerDisplayY: (key, timestamp) => this.meterDisplayYAt(powerDisplayGeometry[key], timestamp, x),
    };
    const dynamicChartMarkup = {
      grid: meterGrid,
      areas: meterAreas,
      lines: meterLines,
    };
    const existingSvg = liveUpdate ? chart.querySelector(".chart-svg") : null;
    if (existingSvg
      && existingSvg.querySelector('[data-price-dynamic="grid"]')
      && existingSvg.querySelector('[data-price-dynamic="areas"]')
      && existingSvg.querySelector('[data-price-dynamic="lines"]')) {
      for (const [key, markup] of Object.entries(dynamicChartMarkup)) {
        existingSvg.querySelector(`[data-price-dynamic="${key}"]`).innerHTML = markup;
      }
      const overlay = chart.querySelector(".chart-axis-overlay");
      if (overlay) overlay.outerHTML = axisOverlayMarkup;
      this._priceChartLiveSignature = this._getPriceChartLiveSignature();
      this._priceChartRenderCacheKey = renderCacheKey;
      return;
    }
    chart.innerHTML = `<svg class="chart-svg" preserveAspectRatio="none" viewBox="0 0 ${width} ${height}" role="img" aria-label="Dagens elpris i 15-minutersperioder">
      <line class="chart-axis" x1="${plot.left}" y1="${zeroY}" x2="${width - plot.right}" y2="${zeroY}" />
      <g data-price-dynamic="grid">${meterGrid}</g>
      ${bars}
      <g data-price-dynamic="areas">${meterAreas}</g>
      <g data-price-dynamic="lines">${this._ellaSelectionBandMarkup(x, plot, dayStart.getTime(), dayEnd.getTime())}${meterLines}</g>
      ${visibleLayers.average ? `<line class="chart-average" stroke="${chartColor("priceNormal")}" x1="${plot.left}" y1="${y(average)}" x2="${width - plot.right}" y2="${y(average)}" />` : ""}
      <g class="chart-hover-markers" aria-hidden="true"></g>
    </svg>${axisOverlayMarkup}<div class="chart-tooltip" hidden></div>`;
    this.bindChartTooltips();
    this._priceChartLiveSignature = this._getPriceChartLiveSignature();
    this._priceChartRenderCacheKey = renderCacheKey;
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

  _buildVisibleTooltipFields(comparisonPrice, details, layers = this._chartLayerState()) {
    const fields = [];
    const add = (label, value, formatted, className = "") => {
      if (tooltipValueIsPresent(value)) fields.push({ label, value, formatted, className });
    };
    const gridVisible = this._priceComparisonVisible.grid && this._eonGridPrice && this._hasGridPriceData();
    if (layers.spot && Number.isFinite(comparisonPrice)) {
      const label = "Spotpris";
      const value = gridVisible && !this._priceComparisonVisible.electricity
        ? Number(this._eonGridPrice.variable_total_ore_per_kwh_gross)
        : comparisonPrice;
      if (Number.isFinite(value)) add(label, value, this.formatPrice(value));
    }
    if (layers.import && isVisiblePowerValue(details?.import_kw)) {
      add("Import", details.import_kw, `${this._formatNumber(details.import_kw)} kW`, "tooltip-meter-import");
    }
    if (layers.export && isVisiblePowerValue(details?.export_kw)) {
      add("Export", details.export_kw, `${this._formatNumber(details.export_kw)} kW`, "tooltip-meter-export");
    }
    const powerRows = [
      ["solar", "Sol", "tooltip-power-solar"],
      ["consumption", "Last", "tooltip-power-consumption"],
      ["charging", "Laddning", "tooltip-power-charging"],
      ["discharging", "Urladdning", "tooltip-power-discharging"],
    ];
    for (const [key, label, className] of powerRows) {
      if (layers[key] && isVisiblePowerValue(details?.[`${key}_kw`])) {
        add(label, details[`${key}_kw`], `${this._formatNumber(details[`${key}_kw`])} kW`, className);
      }
    }
    return fields;
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
      const meterSeries = { import_kw: "import", export_kw: "export" };
      const meterValue = (key) => canonicalMeterPoint && Number.isFinite(Number(canonicalMeterPoint[key]))
        ? Number(canonicalMeterPoint[key])
        : energyHistoryIntervalValueAt(this.priceSnapshot?.energy_history, meterSeries[key], tooltipTimestamp);
      const powerValue = (key) => {
        const point = this._powerCanonicalPointMaps?.[key]?.get(tooltipTimestamp);
        return point && Number.isFinite(Number(point.value_kw))
          ? Number(point.value_kw)
          : energyHistoryIntervalValueAt(this.priceSnapshot?.energy_history, key, tooltipTimestamp);
      };
      const barPrice = this._chartBarPrices?.[index];
      const hoverSnapshot = {
        hoverTime: tooltipTimestamp,
        meterSampleTime: canonicalMeterPoint
          ? canonicalMeterPoint.timestamp
          : (Number.isFinite(meterValue("import_kw")) || Number.isFinite(meterValue("export_kw")) ? tooltipTimestamp : null),
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
      const tooltipFields = this._buildVisibleTooltipFields(comparisonPrice, {
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
        renderSharedTooltip(tooltip, {
          title: time,
          fields: tooltipFields,
        });
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
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-spot" fill="${chartColor("neutral")}" cx="${priceMarkerX}" cy="${hoverGeometry.y(hoverSnapshot.priceBarValue)}" r="4" />`);
        }
        const importDisplayY = meterMarkerX === null
          ? null
          : hoverGeometry.meterDisplayY("import_kw", hoverSnapshot.meterSampleTime);
        if (visibleLayers.import && meterMarkerX !== null && isVisiblePowerValue(hoverSnapshot.importValue) && Number.isFinite(importDisplayY)) {
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-import" fill="${chartColor("import")}" cx="${meterMarkerX}" cy="${importDisplayY}" r="4" />`);
        }
        const exportDisplayY = meterMarkerX === null
          ? null
          : hoverGeometry.meterDisplayY("export_kw", hoverSnapshot.meterSampleTime);
        if (visibleLayers.export && meterMarkerX !== null && isVisiblePowerValue(hoverSnapshot.exportValue) && Number.isFinite(exportDisplayY)) {
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-export" fill="${chartColor("export")}" cx="${meterMarkerX}" cy="${exportDisplayY}" r="4" />`);
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
          const displayY = hoverGeometry.powerDisplayY?.(key, hoverSnapshot.hoverTime);
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-${className}" fill="${chartColor(className)}" cx="${priceMarkerX}" cy="${Number.isFinite(displayY) ? displayY : hoverGeometry.meterY(value)}" r="4" />`);
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
  const panel = new ElrakningPanel(host, version);
  panel.render();
  return panel;
}
