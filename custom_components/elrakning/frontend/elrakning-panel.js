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

export function buildDailyObservedMaxima(powerHistory = {}, meterHistory = {}, now = new Date()) {
  const date = new Date(now).toLocaleDateString("sv-SE");
  const maxFor = (points, value) => (Array.isArray(points) ? points : [])
    .filter((point) => new Date(point?.timestamp).toLocaleDateString("sv-SE") === date)
    .map((point) => Math.abs(Number(value(point))))
    .filter(Number.isFinite)
    .reduce((maximum, current) => Math.max(maximum, current), 0);
  const series = powerHistory?.series || {};
  const meterPoints = Array.isArray(meterHistory?.points) ? meterHistory.points : [];
  const gridMaximum = meterPoints
    .filter((point) => new Date(point?.timestamp).toLocaleDateString("sv-SE") === date)
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
  const house = finiteMagnitude(powerState.consumption_kw);
  const solar = finiteMagnitude(powerState.solar_kw);
  const gridPower = Number(meterState.power_kw);
  let grid = { value: null, status: "Ej tillgängligt", direction: null };
  if (Number.isFinite(gridPower)) {
    const normalized = displayPowerValue(gridPower);
    grid = normalized === 0
      ? { value: 0, status: "Ingen överföring", direction: null }
      : normalized > 0
        ? { value: normalized, status: "Importerar", direction: "import" }
        : { value: Math.abs(normalized), status: "Exporterar", direction: "export" };
  }
  const fuseAmpere = Number(meterState.facility?.fuse_ampere ?? meterState.fuse_ampere);
  const phaseValues = meterState.phase_current_a && typeof meterState.phase_current_a === "object"
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
  const battery = chargingActive && dischargingActive
    ? { value: null, status: "Inkonsekvent data", direction: "invalid", colorKey: "neutral", charging, discharging }
    : chargingActive
      ? { value: charging, status: "Laddar", direction: "charging", colorKey: "charging", charging, discharging }
      : dischargingActive
        ? { value: discharging, status: "Urladdar", direction: "discharging", colorKey: "discharging", charging, discharging }
        : { value: 0, status: "Vilar", direction: null, colorKey: "neutral", charging, discharging };
  const withScale = (tile, key) => {
    const current = Number.isFinite(tile.value) ? Math.abs(tile.value) : 0;
    const maxToday = Math.max(0, Number.isFinite(Number(maxima[key])) ? Number(maxima[key]) : current);
    const scaleMax = Math.max(1, maxToday);
    return { ...tile, maxToday, scaleMax, fillPercent: Math.max(0, Math.min(100, current / scaleMax * 100)) };
  };
  return {
    house: withScale({ value: house, status: house === null ? "Ej tillgängligt" : "Förbrukar", colorKey: "consumption" }, "house"),
    solar: withScale({ value: solar, status: solar === null ? "Ej tillgängligt" : "Producerar", colorKey: "solar" }, "solar"),
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
  if (point?.phase_current_a || point?.phase_voltage_v || point?.phase_active_power_kw) {
    const timestamp = point.timestamp || new Date().toISOString();
    const phaseHistory = mergePhaseHistory(history.phase_history, {});
    for (const [metric, values] of [["current", point.phase_current_a], ["voltage", point.phase_voltage_v], ["active_power", point.phase_active_power_kw]]) {
      if (!values || typeof values !== "object") continue;
      phaseHistory[metric] = { ...(phaseHistory[metric] || {}) };
      for (const phase of ["l1", "l2", "l3"]) {
        const raw = values[phase];
        const value = raw == null ? NaN : Number(raw);
        if (!Number.isFinite(value)) continue;
        const points = Array.isArray(phaseHistory[metric][phase]?.points) ? [...phaseHistory[metric][phase].points] : [];
        const nextPoint = { timestamp, value: metric === "current" ? Math.abs(value) : value };
        const index = points.findIndex((item) => item.timestamp === timestamp);
        if (index >= 0) points[index] = { ...points[index], ...nextPoint }; else points.push(nextPoint);
        points.sort((left, right) => new Date(left.timestamp) - new Date(right.timestamp));
        phaseHistory[metric][phase] = { ...(phaseHistory[metric][phase] || {}), points: points.slice(-2000) };
      }
    }
    next = { ...next, phase_history: phaseHistory, last_live_merge_at: new Date().toISOString(), last_live_timestamp: timestamp };
  }
  if (!point?.timestamp || (point.entity_id && point.entity_id !== powerEntityId)) return next;
  const timestamp = new Date(point.timestamp);
  if (Number.isNaN(timestamp.getTime())) return next;
  const date = timestamp.toLocaleDateString("sv-SE");
  const currentDate = next.date || date;
  if (date !== currentDate) return next;
  const points = Array.isArray(next.points) ? [...next.points] : [];
  const nextPoint = { timestamp: timestamp.toISOString(), import_kw: normalizeMeterValue(point.import_kw), export_kw: normalizeMeterValue(point.export_kw) };
  const index = points.findIndex((item) => item.timestamp === nextPoint.timestamp);
  if (index >= 0) points[index] = nextPoint; else points.push(nextPoint);
  points.sort((left, right) => new Date(left.timestamp) - new Date(right.timestamp));
  return { ...next, date: currentDate, points };
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

const DEBUG_SENSITIVE_KEY = /(token|password|secret|cookie|authorization|customer[_-]?id|account[_-]?id|point[_-]?of[_-]?delivery|installation[_-]?(?:id|identifier)|premise[_-]?id|session[_-]?id|email|first[_-]?name|last[_-]?name|address|street|postal[_-]?code|postcode|city|ip(?:[_-]?address)?|meter[_-]?id|facility[_-]?id|site[_-]?id|bill[_-]?location[_-]?id|contract[_-]?id|invoice[_-]?key|user[_-]?id|pod)/i;

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

export function buildLivePowerProvenance(key, tile, powerState = {}, meterState = {}, meterHistory = {}, powerHistory = {}, states = {}, liveMaxima = {}) {
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
  const seriesMaximum = (series) => {
    const values = Array.isArray(series?.points) ? series.points.map((point) => Math.abs(Number(point.value_kw))).filter(Number.isFinite) : [];
    return values.length ? Math.max(...values) : null;
  };
  const historyMaxCandidates = key === "grid"
    ? [
      seriesMaximum({ points: (meterHistory.points || []).map((point) => ({ value_kw: point.import_kw })) }),
      seriesMaximum({ points: (meterHistory.points || []).map((point) => ({ value_kw: point.export_kw })) }),
    ]
    : key === "battery"
      ? [seriesMaximum(powerHistory.series?.charging), seriesMaximum(powerHistory.series?.discharging)]
      : [seriesMaximum(powerHistory.series?.[key === "house" ? "consumption" : key])];
  const historyMax = historyMaxCandidates.filter(Number.isFinite).length
    ? Math.max(...historyMaxCandidates.filter(Number.isFinite))
    : null;
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
    result_kw: tile?.maxToday ?? null,
    max_source: "raw_history_plus_live_daily_max",
    presentation_max_matches_history: !Number.isFinite(historyMax) || !Number.isFinite(Number(tile?.maxToday))
      ? null
      : Math.abs(historyMax - Number(tile.maxToday)) < 1e-9,
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
      max_today_kw: tile?.maxToday ?? null,
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

export function buildInvoiceEstimate(periods, meterPoints, gridPrice, tradeFixedFee = null, now = new Date()) {
  const current = new Date(now);
  const nowMs = current.getTime();
  if (!Array.isArray(periods) || !periods.length || !Array.isArray(meterPoints)) return null;
  const monthStart = new Date(current.getFullYear(), current.getMonth(), 1);
  const nextMonth = new Date(current.getFullYear(), current.getMonth() + 1, 1);
  const gridGross = Number(gridPrice?.variable_total_ore_per_kwh_gross);
  const points = meterPoints
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
  const importedKwh = coveredEnergyPeriods > 0 ? coveredEnergyKwh : null;
  const tradeVariableSek = rows.reduce((sum, row) => sum + row.trade_cost_sek, 0);
  const gridVariableSek = rows.reduce((sum, row) => sum + row.grid_cost_sek, 0);
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
  const pricedImportKwh = rows.reduce((sum, row) => sum + row.import_kwh, 0);
  const observedDailyImportKwh = importedKwh > 0 && coveredDays > 0 ? importedKwh / coveredDays : null;
  const tradeWeighted = pricedImportKwh > 0
    ? rows.reduce((sum, row) => sum + row.import_kwh * row.trade_price_ore_per_kwh_gross, 0) / pricedImportKwh
    : null;
  const gridWeighted = pricedImportKwh > 0 ? gridGross : null;
  const fixedTrade = tradeFixedFee != null && Number.isFinite(Number(tradeFixedFee)) ? Number(tradeFixedFee) : null;
  const gridFixed = Number.isFinite(Number(gridPrice?.fixed_monthly_sek)) ? Number(gridPrice.fixed_monthly_sek) : null;
  const accruedGridFixed = gridFixed === null ? null : gridFixed * Math.min(1, elapsedMs / monthMs);
  const accruedTradeFixed = fixedTrade === null ? null : fixedTrade * Math.min(1, elapsedMs / monthMs);
  const variableSoFarSek = tradeVariableSek + gridVariableSek;
  const fixedSoFarSek = (accruedTradeFixed || 0) + (accruedGridFixed || 0);
  const missingPastDays = missingPastMs / 86400000;
  const forecastMissingPastKwh = observedDailyImportKwh === null ? null : observedDailyImportKwh * missingPastDays;
  const forecastFutureKwh = observedDailyImportKwh === null ? null : observedDailyImportKwh * remainingDays;
  const forecastImportKwh = importedKwh !== null && forecastMissingPastKwh !== null && forecastFutureKwh !== null && tradeWeighted !== null && gridWeighted !== null
    ? importedKwh + forecastMissingPastKwh + forecastFutureKwh
    : null;
  const forecastVariableSek = forecastImportKwh === null
    ? null
    : forecastImportKwh * (tradeWeighted + gridWeighted) / 100;
  const forecastFixedSek = (fixedTrade || 0) + (gridFixed || 0);
  return {
    month: `${current.getFullYear()}-${String(current.getMonth() + 1).padStart(2, "0")}`,
    imported_kwh_so_far: importedKwh,
    trade: { variable_cost_sek: tradeVariableSek, fixed_fee_sek: fixedTrade, accrued_fixed_fee_sek: accruedTradeFixed, total_so_far_sek: tradeVariableSek + (accruedTradeFixed || 0) },
    grid: { variable_cost_sek: gridVariableSek, fixed_fee_sek: gridFixed, accrued_fixed_fee_sek: accruedGridFixed, total_so_far_sek: gridVariableSek + (accruedGridFixed || 0) },
    total_so_far_sek: variableSoFarSek + fixedSoFarSek,
    estimated_month_total_sek: forecastVariableSek === null ? null : forecastVariableSek + forecastFixedSek,
    forecast_import_kwh: forecastImportKwh,
    forecast_remaining_kwh: forecastImportKwh === null ? null : Math.max(0, forecastImportKwh - importedKwh),
    forecast_missing_past_kwh: forecastMissingPastKwh,
    forecast_future_kwh: forecastFutureKwh,
    forecast_remaining_days: remainingDays,
    forecast_remaining_trade_variable_sek: forecastImportKwh === null || tradeWeighted === null ? null : Math.max(0, forecastImportKwh - importedKwh) * tradeWeighted / 100,
    forecast_remaining_grid_variable_sek: forecastImportKwh === null || gridWeighted === null ? null : Math.max(0, forecastImportKwh - importedKwh) * gridWeighted / 100,
    forecast_remaining_total_sek: forecastVariableSek === null ? null : forecastVariableSek - variableSoFarSek,
    missing_past_estimated_kwh: forecastMissingPastKwh,
    forecast_method: "actual imported energy and volume-weighted observed gross prices; missing past and future energy use the observed covered-duration average",
    forecast_confidence: rows.length && missingPricePeriods === 0 && missingEnergyPeriods === 0 && coveredDurationMs >= elapsedMs - 1 ? "complete_available_data" : "partial_data",
    data_coverage: { period_count: rows.length, observed_periods: observedPricePeriods, covered_energy_periods: coveredEnergyPeriods, missing_price_periods: missingPricePeriods, missing_energy_periods: missingEnergyPeriods, coverage_percent: elapsedMs ? coveredDurationMs / elapsedMs * 100 : 0, first_period: coveredStartMs ? new Date(coveredStartMs).toISOString() : null, last_period: coveredEndMs ? new Date(coveredEndMs).toISOString() : null, observed_duration_ms: coveredDurationMs, covered_duration_ms: coveredDurationMs, missing_past_duration_ms: missingPastMs, remaining_future_duration_ms: remainingDays * 86400000, elapsed_month_duration_ms: elapsedMs, periods: { observed_covered: { duration_ms: coveredDurationMs, kwh: importedKwh }, missing_past: { duration_ms: missingPastMs, estimated_kwh: forecastMissingPastKwh }, future_remaining: { duration_ms: remainingDays * 86400000, estimated_kwh: forecastFutureKwh } } },
    trade_weighted_average_ore_per_kwh: tradeWeighted,
    grid_weighted_average_ore_per_kwh: gridWeighted,
    total_weighted_average_ore_per_kwh: tradeWeighted === null || gridWeighted === null ? null : tradeWeighted + gridWeighted,
    completeness: { trade_variable: rows.length > 0, trade_fixed: fixedTrade !== null, grid_variable: rows.length > 0 && Number.isFinite(gridGross), grid_fixed: gridFixed !== null, export_credit: false },
    export_energy_kwh: null,
    rows,
    trade_fixed_fee_source: fixedTrade !== null ? "provider_summary.tariff.fixed_fee_incl_vat_per_month" : null,
  };
}

export function previousCalendarMonth(month) {
  if (typeof month !== "string" || !/^\d{4}-\d{2}$/.test(month)) return null;
  const [year, monthNumber] = month.split("-").map(Number);
  if (monthNumber < 1 || monthNumber > 12) return null;
  const date = new Date(Date.UTC(year, monthNumber - 1, 1));
  date.setUTCMonth(date.getUTCMonth() - 1);
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function buildPreviousMonthActual(invoiceSources = {}, selectedMonth) {
  const month = previousCalendarMonth(selectedMonth);
  const normalizeProvider = (items) => {
    const matches = (Array.isArray(items) ? items : []).filter((invoice) => invoice && invoice.month === month);
    const normalized = matches.map((invoice) => {
      const periodCost = Number(invoice.period_cost_before_credits_sek);
      const amountDue = Number(invoice.amount_due_sek);
      const comparisonValue = Number.isFinite(periodCost) ? periodCost : Number.isFinite(amountDue) ? amountDue : null;
      return {
        invoice_exists: true,
        billing_period: invoice.billing_period || invoice.month,
        period_cost_sek: Number.isFinite(periodCost) ? periodCost : null,
        period_cost_before_credits_sek: Number.isFinite(periodCost) ? periodCost : null,
        credits_applied_sek: Number.isFinite(Number(invoice.credits_applied_sek)) ? Number(invoice.credits_applied_sek) : null,
        amount_due_sek: Number.isFinite(amountDue) ? amountDue : null,
        comparison_value_sek: comparisonValue,
        source: invoice.source || null,
      };
    });
    const comparable = normalized.filter((invoice) => Number.isFinite(invoice.comparison_value_sek));
    const total = comparable.reduce((sum, invoice) => sum + invoice.comparison_value_sek, 0);
    const sumField = (field) => {
      const values = normalized.map((invoice) => invoice[field]).filter((value) => Number.isFinite(value));
      return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
    };
    return {
      available: matches.length > 0,
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
  const gridMatches = Array.isArray(invoiceSources.grid) ? invoiceSources.grid.filter((invoice) => invoice && invoice.month === month) : [];
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
  return {
    month,
    trade,
    grid,
    coverage,
    total_sek: coverage === "complete" && Number.isFinite(trade.total_sek) && Number.isFinite(grid.total_sek) ? trade.total_sek + grid.total_sek : null,
    comparison: {
      available: coverage === "complete" && Number.isFinite(trade.total_sek) && Number.isFinite(grid.total_sek),
      coverage,
      reason: coverage === "partial" && !grid.available ? "previous_grid_invoice_missing" : null,
    },
  };
}

export function buildInvoiceComparison(estimate, previousActual) {
  const current = Number(estimate?.estimated_month_total_sek);
  const previous = Number(previousActual?.total_sek);
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
      integration_method: billingHistory.integration_method || "trapezoidal_power_integration",
      result_kwh: estimate.imported_kwh_so_far,
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
      forecast_trade_variable_sek: estimate.forecast_remaining_trade_variable_sek ?? null,
      forecast_grid_variable_sek: estimate.forecast_remaining_grid_variable_sek ?? null,
      total_sek: estimate.forecast_remaining_total_sek ?? null,
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

export function buildSolarDailyHistory(points, forecastBaselines, now = new Date(), dayCount = 7, liveForecast = null) {
  const current = new Date(now);
  const todayStart = new Date(current.getFullYear(), current.getMonth(), current.getDate());
  const days = Math.max(1, Math.min(7, Math.trunc(Number(dayCount) || 7)));
  const forecastByDate = forecastBaselines && typeof forecastBaselines === "object" ? forecastBaselines : {};
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
    const comparisonExpectedKwh = isToday ? expectedSoFarKwh : forecastKwh;
    const comparisonBasis = isToday ? "forecast_so_far" : "full_day_forecast";
    const comparisonIsValid = Number.isFinite(actualKwh) && Number.isFinite(comparisonExpectedKwh)
      && actualKwh >= 0 && comparisonExpectedKwh > 0;
    const forecastAccuracyPercent = comparisonIsValid
      ? Math.max(0, Math.min(100, Math.min(actualKwh, comparisonExpectedKwh) / Math.max(actualKwh, comparisonExpectedKwh) * 100))
      : null;
    const forecastDeviationPercent = comparisonIsValid
      ? (actualKwh - comparisonExpectedKwh) / comparisonExpectedKwh * 100
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
      forecastComparisonExpectedKwh: comparisonExpectedKwh,
      forecastComparisonBasis: comparisonBasis,
      rawDayForecastKwh: forecastKwh,
      rawExpectedSoFarKwh: expectedSoFarKwh,
      actualSoFarKwh: isToday ? actualKwh : null,
      performanceRatio: comparisonIsValid ? actualKwh / comparisonExpectedKwh : null,
      performanceDeltaPercent: forecastDeviationPercent,
    };
  });
}

export function buildSolarHistoryTooltipLines(day, liveForecast, now = new Date(), weather = null, sun = null) {
  const lines = [];
  if (Number.isFinite(day?.producedKwh)) {
    lines.push(`Producerat: ${day.producedKwh} kWh`);
  }
  const today = new Date(now).toLocaleDateString("sv-SE");
  if (day?.date === today) {
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
  if (day?.date === today) {
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
    this._meterPowerHistory = createMeterPowerHistoryState();
    this._livePowerMaxima = { date: null, house: 0, solar: 0, grid: 0, battery: 0 };
    this._meterTooltipPoints = [];
    this._meterCanonicalPoints = [];
    this._meterCanonicalPointMap = new Map();
    this._meterHistorySummary = null;
    this._meterHistoryRequestToken = 0;
    this._powerState = null;
    this._powerHistory = { date: null, series: {}, solar_forecast_baselines: {}, solar_weather: { available: false, source: "smhi", status: "unavailable", current: {}, hourly_forecast: [] }, solar_sun: { available: false } };
    this._powerHistoryRequestToken = 0;
    this._solarForecastEventUnsubscribePromise = null;
    this._powerLivePoints = Object.fromEntries(["solar", "consumption", "charging", "discharging", "soc"].map((key) => [key, new Map()]));
    this._backendHydrationPromise = null;
    this._readyEventUnsubscribePromise = null;
    this._eonGridEventUnsubscribePromise = null;
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
    this._phaseHistoryMetric = "current";
    this._phaseHistoryVisible = { l1: true, l2: true, l3: true };
    this._providerConfigured = false;
    this._electricityProviderState = null;
    this._billingHistory = null;
    this._costSelectedMonth = null;
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

        <section class="live-power-row" data-live-power-row aria-label="Aktuell effekt">
          <article class="live-power-tile" data-live-power-tile="house">
            <div class="live-power-heading"><span class="live-power-title">Hus</span><button type="button" class="configuration-control live-power-configure" data-meter-configure hidden>Konfigurera</button></div>
            <strong class="live-power-value" data-live-power-value>–</strong>
            <span class="live-power-status" data-live-power-status>Ej tillgängligt</span>
            <div class="live-power-bar" aria-hidden="true"><span data-live-power-fill></span></div>
            <div class="live-power-scale"><span>0</span><span data-live-power-scale>1,00 kW</span></div>
            <span class="live-power-grid-fuse-status live-power-grid-fuse-status-spacer" aria-hidden="true"></span>
            <div class="live-power-debug-footer"><span class="live-power-copy-feedback" data-live-power-copy-feedback aria-live="polite"></span><button type="button" class="live-power-action" data-live-power-source="house" hidden>Visa data</button></div>
          </article>
          <article class="live-power-tile" data-live-power-tile="solar">
            <div class="live-power-heading"><span class="live-power-title">Sol</span><button type="button" class="configuration-control live-power-configure" data-power-configure="solar" hidden>Konfigurera</button></div>
            <strong class="live-power-value" data-live-power-value>–</strong>
            <span class="live-power-status" data-live-power-status>Ej tillgängligt</span>
            <div class="live-power-bar" aria-hidden="true"><span data-live-power-fill></span></div>
            <div class="live-power-scale"><span>0</span><span data-live-power-scale>1,00 kW</span></div>
            <span class="live-power-grid-fuse-status live-power-grid-fuse-status-spacer" aria-hidden="true"></span>
            <div class="live-power-debug-footer"><span class="live-power-copy-feedback" data-live-power-copy-feedback aria-live="polite"></span><button type="button" class="live-power-action" data-live-power-source="solar" hidden>Visa data</button></div>
          </article>
          <article class="live-power-tile" data-live-power-tile="grid">
            <div class="live-power-heading"><span class="live-power-title">Nät</span><span class="live-power-grid-meta" data-live-power-grid-meta hidden></span><button type="button" class="configuration-control live-power-configure" data-eon-grid-configure hidden>Konfigurera</button></div>
            <strong class="live-power-value" data-live-power-value>–</strong>
            <span class="live-power-status" data-live-power-status>Ej tillgängligt</span>
            <div class="live-power-bar" aria-hidden="true"><span data-live-power-fill></span></div>
            <div class="live-power-scale"><span>0</span><span data-live-power-scale>1,00 kW</span></div>
            <span class="live-power-grid-fuse-status live-power-grid-fuse-status-spacer" aria-hidden="true"></span>
            <div class="live-power-debug-footer"><span class="live-power-copy-feedback" data-live-power-copy-feedback aria-live="polite"></span><button type="button" class="live-power-action" data-live-power-source="grid" hidden>Visa data</button></div>
          </article>
          <article class="live-power-tile" data-live-power-tile="battery">
            <div class="live-power-heading"><span class="live-power-title">Batteri</span><button type="button" class="configuration-control live-power-configure" data-power-configure="battery" hidden>Konfigurera</button></div>
            <strong class="live-power-value" data-live-power-value>–</strong>
            <span class="live-power-status" data-live-power-status>Ej tillgängligt</span>
            <div class="live-power-bar" aria-hidden="true"><span data-live-power-fill></span></div>
            <div class="live-power-scale"><span>0</span><span data-live-power-scale>1,00 kW</span></div>
            <span class="live-power-grid-fuse-status live-power-grid-fuse-status-spacer" aria-hidden="true"></span>
            <div class="live-power-debug-footer"><span class="live-power-copy-feedback" data-live-power-copy-feedback aria-live="polite"></span><button type="button" class="live-power-action" data-live-power-source="battery" hidden>Visa data</button></div>
          </article>
          <article class="live-power-tile invoice-estimate-card" data-invoice-estimate-card hidden aria-labelledby="invoice-estimate-title">
            <h2 id="invoice-estimate-title" class="visually-hidden">Estimerad faktura</h2>
            <div class="live-power-heading"><span class="live-power-title">Estimerad faktura</span></div>
            <span class="live-power-grid-meta invoice-estimate-month" data-invoice-estimate-month></span>
            <strong class="live-power-value" data-invoice-estimate-total>–</strong>
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
            <div class="phase-history-heading">
              <h2 id="phase-history-title">Faser</h2>
              <div class="phase-history-metric-selector" role="group" aria-label="Fasmätning">
                <button type="button" data-phase-metric="current" aria-pressed="true">Ström</button>
                <button type="button" data-phase-metric="voltage" aria-pressed="false">Spänning</button>
                <button type="button" data-phase-metric="active_power" aria-pressed="false">Effekt</button>
              </div>
            </div>
            <div class="phase-history-summary" data-phase-history-summary></div>
            <div class="phase-history-chart" data-phase-history-chart></div>
            <button type="button" data-phase-history-copy hidden>Visa data</button>
          </article>
          <article class="card cost-card" data-cost-card hidden aria-labelledby="cost-title">
            <div class="card-heading"><h2 id="cost-title">Kostnad</h2><span class="status" data-cost-period></span></div>
            <div class="cost-navigation"><button type="button" data-cost-previous aria-label="Föregående månad">‹</button><span data-cost-selected-period></span><button type="button" data-cost-next aria-label="Nästa månad">›</button></div>
            <div class="cost-summary" data-cost-summary></div>
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
            <button type="button" data-provider-source hidden>Vad har vi för data?</button>
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
              <button type="button" data-eon-grid-source hidden>Vad har vi för data?</button>
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
      <div class="provider-source-dialog" data-provider-source-dialog hidden role="dialog" aria-modal="true" aria-labelledby="provider-source-dialog-title">
        <div class="provider-dialog-card">
          <h2 id="provider-source-dialog-title">Source data</h2>
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
          --solar-color: var(--el-solar-color);
          --consumption-color: var(--el-consumption-color);
          --grid-import-color: var(--el-import-color);
          --grid-export-color: var(--el-export-color);
          --charging-color: var(--el-charging-color);
          --discharging-color: var(--el-discharging-color);
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
          background: rgba(255, 255, 255, 0.12);
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
          background: rgba(0, 0, 0, 0.30);
          background: color-mix(in srgb, var(--primary-background-color) 70%, transparent);
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
          background: color-mix(in srgb, var(--primary-background-color) 70%, transparent);
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
          font-size: 10px;
          font-weight: 400;
          line-height: 1;
        }

        .battery-history-axis-label {
          color: var(--secondary-text-color);
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
          font-size: 10px;
          font-weight: 400;
          line-height: 1;
        }

        .solar-history-axis-label {
          color: var(--secondary-text-color);
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

        .solar-history-bar {
          fill: var(--solar-color);
          fill-opacity: .78;
          rx: 4;
          ry: 4;
        }

        .solar-history-reference-bar {
          fill-opacity: .9;
          rx: 4;
          ry: 4;
        }

        .solar-history-day.hovered .solar-history-bar,
        .solar-history-day.hovered .solar-history-reference-bar {
          fill-opacity: 1;
        }

        .daily-energy-row {
          align-items: stretch;
          display: grid;
          gap: 16px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .battery-history-row {
          margin-top: 16px;
        }

        @container (max-width: 760px) {
          .daily-energy-row {
            align-items: start;
            grid-template-columns: 1fr;
          }
        }

        .daily-energy-card {
          --daily-energy-local-color: var(--el-solar-color);
          --daily-energy-export-color: var(--el-export-color);
          --daily-energy-import-color: var(--el-import-color);
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
          min-width: 0;
          transition: width 120ms ease;
        }

        .daily-energy-segment.local {
          background: rgba(119, 194, 161, 0.70);
          background: color-mix(in srgb, var(--daily-energy-local-color) 70%, var(--ha-card-background, var(--card-background-color)));
        }

        .daily-energy-segment.supply {
          background: rgba(119, 194, 161, 0.70);
          background: color-mix(in srgb, var(--daily-energy-local-color) 70%, var(--ha-card-background, var(--card-background-color)));
        }

        .daily-energy-segment.export {
          background: rgba(114, 170, 246, 0.70);
          background: color-mix(in srgb, var(--daily-energy-export-color) 70%, var(--ha-card-background, var(--card-background-color)));
        }

        .daily-energy-segment.import {
          background: rgba(240, 160, 106, 0.70);
          background: color-mix(in srgb, var(--daily-energy-import-color) 70%, var(--ha-card-background, var(--card-background-color)));
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
          --soc-color: var(--el-solar-color);
          display: block;
          min-height: 0;
          min-width: 0;
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
          color: var(--secondary-text-color);
          font-size: 10px;
          font-weight: 400;
          line-height: 1;
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
          margin-top: 16px;
        }

        .cost-card {
          min-width: 0;
        }

        .cost-summary {
          display: grid;
          gap: 8px 14px;
          grid-template-columns: minmax(0, 1fr) auto;
          margin-top: 16px;
        }

        .cost-navigation {
          align-items: center;
          display: flex;
          gap: 12px;
          justify-content: space-between;
          margin-top: 14px;
        }

        .cost-navigation button {
          background: transparent;
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          color: var(--primary-text-color);
          font: inherit;
          line-height: 1;
          padding: 4px 9px;
        }

        .cost-navigation span {
          color: var(--secondary-text-color);
          font-size: 13px;
        }

        .cost-summary span {
          color: var(--secondary-text-color);
        }

        .cost-summary strong {
          font-weight: 500;
          text-align: right;
        }

        .card-source-action {
          margin-top: 16px;
        }

        .phase-history-card {
          min-width: 0;
        }

        .phase-history-heading {
          align-items: center;
          display: flex;
          gap: 16px;
          justify-content: space-between;
        }

        .phase-history-heading h2 {
          font-size: inherit;
          margin: 0;
        }

        .phase-history-metric-selector {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
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
          display: grid;
          gap: 8px;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          margin: 16px 0 8px;
        }

        .phase-history-summary div {
          color: var(--secondary-text-color);
          cursor: pointer;
          opacity: 0.48;
          text-align: center;
          transition: opacity 120ms ease;
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
          margin-right: 3px;
          width: 6px;
        }

        .phase-history-summary strong {
          color: var(--primary-text-color);
          display: block;
          font-size: 18px;
          font-weight: 500;
        }

        .phase-history-chart {
          min-height: 180px;
          overflow-anchor: none;
          position: relative;
        }

        .phase-history-svg {
          display: block;
          height: auto;
          width: 100%;
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
          fill: var(--secondary-text-color);
          font-size: 10px;
        }

        .phase-history-reference-label {
          font-weight: 400;
        }

        .phase-history-axis-label {
          fill: var(--secondary-text-color);
          font-size: 10px;
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
          grid-row: 2;
          margin-left: 0;
          justify-self: start;
          text-align: left;
        }

        .invoice-estimate-card .live-power-value {
          grid-row: 3;
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


        .live-power-row {
          align-items: stretch;
          display: grid;
          gap: 12px;
          grid-template-columns: repeat(5, minmax(0, 1fr));
          margin-bottom: 16px;
        }

        .live-power-tile {
          background: var(--ha-card-glass-tint, var(--ha-card-background, var(--card-background-color)));
          border: var(--ha-card-border-width, 1px) var(--ha-card-border-style, solid) var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-glass-inset-shadow, var(--ha-card-box-shadow, none));
          box-sizing: border-box;
          container-type: inline-size;
          display: grid;
          align-content: start;
          grid-template-rows: auto auto auto 5px auto 12px minmax(0, auto);
          row-gap: 4px;
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

        .live-power-bar {
          background: rgba(255, 255, 255, 0.14);
          background: color-mix(in srgb, var(--secondary-text-color) 14%, transparent);
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

        .live-power-tile.debug-copy-enabled .live-power-debug-footer.visible {
          display: flex;
        }

        .live-power-tile.debug-copy-enabled {
          cursor: pointer;
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
          gap: 16px;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        }

        .price-section {
          --solar-color: var(--el-solar-color);
          --consumption-color: var(--el-consumption-color);
          --grid-import-color: var(--el-import-color);
          --grid-export-color: var(--el-export-color);
          --charging-color: var(--el-charging-color);
          --discharging-color: var(--el-discharging-color);
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
          fill: var(--secondary-text-color);
          font-size: var(--card-chart-label-size);
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
    this._bindEonGridDialog();
    this._bindRetainedHistory();
    this._bindMeterDialog();
    this._bindPowerDialog();
    this._bindDebugToggle();
    this._bindConfigurationCardsToggle();
    this._bindMainCardToggles();
    this._bindProviderSourceDialog();
    this._bindMeterSourceDialog();
    this._bindLivePowerCards();
    this._bindPhaseHistoryCard();
        this._bindDiagnostics();
    this._bindMainInvoiceParser();
    this._bindCostCard();
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
      this._applyPriceComparisonState(response.price_comparison);
      this._applyPhaseHistoryPreference(response.phase_history_metric);
      this._applyPhaseHistoryVisibility(response.phase_history_visible);
      this._applyConfigurationCardsVisibility(response.configuration_cards_visible, response.main_cards);
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

  async _persistChartPreferences() {
    if (!this.hass?.callWS || !this._chartPreferencesReady) return;
    try {
      await this.hass.callWS({
        type: "elrakning/ui_preferences/set",
        chart_layers: this._chartLayerState(),
        price_comparison: this._priceComparisonVisible,
        phase_history_metric: this._phaseHistoryMetric,
        phase_history_visible: this._phaseHistoryVisible,
        configuration_cards_visible: this._configurationCardsVisible,
        main_cards: this._mainCards,
      });
    } catch {
      // Keep the UI responsive when preference persistence is unavailable.
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
        this._priceComparisonVisible[layer] = input.checked;
        this.updatePriceSummary();
        this.renderPriceChart();
        this._persistChartPreferences();
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
    const eonSource = this.host.querySelector("[data-eon-grid-source]");
    const meterSource = this.host.querySelector("[data-meter-source]");
    const liveSources = this.host.querySelectorAll("[data-live-power-source]");
    const diagnostics = this.host.querySelector("[data-diagnostics-card]");
    const phaseCopy = this.host.querySelector("[data-phase-history-copy]");
    const cardSources = this.host.querySelectorAll("[data-card-source]");
    if (source) source.hidden = !this._debugEnabled;
    if (eonSource) eonSource.hidden = !this._debugEnabled || this._eonGridState?.configured !== true;
    if (meterSource) meterSource.hidden = !this._debugEnabled || this._meterState?.configured !== true;
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
        this.loadBillingHistory();
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
    this._renderSocChart();
    this._renderBatteryHistoryCard();
    this._renderSolarHistoryCard();
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

  async _copyLivePowerTile(tile) {
    const raw = tile?._livePowerRaw;
    const feedback = tile?.querySelector("[data-live-power-copy-feedback]");
    if (!raw || !feedback) return;
    try {
      await this._copyText(JSON.stringify(raw, null, 2));
      feedback.textContent = "Kopierat";
      window.clearTimeout(tile._livePowerFeedbackTimer);
      tile._livePowerFeedbackTimer = window.setTimeout(() => { feedback.textContent = ""; }, 1400);
    } catch {
      feedback.textContent = "Kunde inte kopiera";
    }
  }

  _bindLivePowerCards() {
    this._updateLivePowerCardInteractivity();
    this._renderLivePowerRow();
  }

  _updateLivePowerCardInteractivity() {
    const enabled = this._debugEnabled;
    for (const tile of this.host.querySelectorAll("[data-live-power-tile]")) {
      if (tile.matches("[data-invoice-estimate-card]")) continue;
      if (enabled && !tile._livePowerCopyEnabled) {
        const copy = () => { void this._copyLivePowerTile(tile); };
        const clickHandler = (event) => {
          if (event.target.closest("[data-meter-source], [data-live-power-source]")) return;
          copy();
        };
        const keydownHandler = (event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          copy();
        };
        tile.addEventListener("click", clickHandler);
        tile.addEventListener("keydown", keydownHandler);
        tile._livePowerCopyEnabled = true;
        tile._livePowerCopyClickHandler = clickHandler;
        tile._livePowerCopyKeydownHandler = keydownHandler;
        tile.tabIndex = 0;
        tile.setAttribute("role", "button");
        tile.classList.add("debug-copy-enabled");
        tile.querySelector(".live-power-debug-footer")?.classList.add("visible");
      } else if (!enabled && tile._livePowerCopyEnabled) {
        tile.removeEventListener("click", tile._livePowerCopyClickHandler);
        tile.removeEventListener("keydown", tile._livePowerCopyKeydownHandler);
        window.clearTimeout(tile._livePowerFeedbackTimer);
        const feedback = tile.querySelector("[data-live-power-copy-feedback]");
        if (feedback) feedback.textContent = "";
        delete tile._livePowerCopyEnabled;
        delete tile._livePowerCopyClickHandler;
        delete tile._livePowerCopyKeydownHandler;
        tile.removeAttribute("tabindex");
        tile.removeAttribute("role");
        tile.classList.remove("debug-copy-enabled");
        tile.querySelector(".live-power-debug-footer")?.classList.remove("visible");
      }
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
        ? `<rect class="solar-history-reference-bar" fill="${chartColor("solarForecast")}" x="${center - referenceBarWidth / 2}" y="${y(day.forecastKwh)}" width="${referenceBarWidth}" height="${plot.top + plotHeight - y(day.forecastKwh)}" />`
        : "";
      const actual = Number.isFinite(day.producedKwh)
        ? `<rect class="solar-history-bar" fill="${chartColor("solar")}" x="${center - barWidth / 2}" y="${y(day.producedKwh)}" width="${barWidth}" height="${plot.top + plotHeight - y(day.producedKwh)}" />`
        : "";
      return `<g class="solar-history-day" data-solar-history-index="${index}">${forecast}${actual}</g>`;
    }).join("");
    const yLabelMarkup = [range, range / 2, 0].map((level, index) => `<span class="solar-history-axis-label ${index === 0 ? "top" : index === 1 ? "middle" : "bottom"}">${this._formatNumber(level)}</span>`).join("");
    const xLabelMarkup = days.map((day, index) => `<span class="solar-history-x-label" style="left: ${(index + .5) / days.length * 100}%"><span class="solar-history-day-label">${day.label}</span><span class="solar-history-utilization">${Number.isFinite(day.utilizationPercent) ? `${this._formatNumber(day.utilizationPercent)} %` : "—"}</span></span>`).join("");
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
    const xDuration = Math.max(1, xEnd - xStart);
    const x = (timestamp) => xEnd <= xStart
      ? width - plot.right
      : plot.left + ((timestamp - xStart) / xDuration) * plotWidth;
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
      ${gridMarkup}${lineMarkup}${estimatedMarkup}${singletonMarkup}<g class="soc-hover" aria-hidden="true"></g>
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
      const response = await this.hass.callWS({ type: "elrakning/power_history", days: 7 });
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
        solar_analysis: response?.solar_analysis || { available: false, days: [] },
        solar_forecast: response?.solar_forecast || { available: false },
        solar_forecast_baselines: response?.solar_forecast_baselines || response?.solar_forecast?.baselines || {},
        solar_weather: response?.solar_weather || { available: false, source: "smhi", status: "unavailable", current: {}, hourly_forecast: [] },
        solar_sun: response?.solar_sun || { available: false },
      };
      this._rebuildLivePowerMaxima();
      this._refreshPowerEnergyState();
      if (this.host.querySelector(".price-chart")) this.renderPriceChart();
    } catch {
      if (requestToken !== this._powerHistoryRequestToken) return;
      this._powerHistory = { date: null, series: {}, solar_forecast_baselines: {}, solar_weather: { available: false, source: "smhi", status: "unavailable", current: {}, hourly_forecast: [] }, solar_sun: { available: false } };
      this._refreshPowerEnergyState();
    }
  }

  async loadSolarForecast() {
    if (!this.hass?.callWS) return;
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

  _showSourceDataDialog(title, sourceLabel, data) {
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
    copy.textContent = "Kopiera";
    dialog.hidden = false;
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
      const liveSource = event.currentTarget.closest?.("[data-live-power-tile]");
      const liveSourceName = event.currentTarget.dataset.livePowerSource;
      const cardSource = event.currentTarget.dataset.cardSource;
      dialog.hidden = false;
      heading.textContent = "Source data";
      text.textContent = "Hämtar Source data …";
      provider.hidden = true;
      provider.textContent = "";
      copy.disabled = true;
      try {
        const source = liveSource
          ? liveSource._livePowerRaw || {}
          : isEon
          ? await this.hass.callWS({ type: "elrakning/grid/source_data" })
          : cardSource
          ? {
            source: cardSource,
            invoice_estimate: cardSource === "cost" ? this._invoiceEstimateRaw : undefined,
            power_state: this._powerState,
            meter_state: this._meterState,
            power_history: this._powerHistory,
            meter_power_history: this._meterPowerHistory,
          }
          : await this.hass.callWS({ type: "elrakning/electricity_provider_source_data", limit: 500 });
        const providerName = liveSource ? liveSourceName : source.provider_name || source.facility?.provider_name;
        if (typeof providerName === "string" && providerName.trim()) {
          provider.textContent = `Källa: ${providerName.trim()}`;
          provider.hidden = false;
        }
        const safeSource = sanitizeDebugData(source);
        text.textContent = liveSource || isEon
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
        window.setTimeout(() => { copy.textContent = "Kopiera"; }, 1500);
      } catch {
        copy.textContent = "Kunde inte kopiera";
        window.setTimeout(() => { copy.textContent = "Kopiera"; }, 1500);
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
    this._renderInvoiceCardCosts();
  }

  _renderInvoiceEstimateCard() {
    const card = this.host.querySelector("[data-invoice-estimate-card]");
    const month = this.host.querySelector("[data-invoice-estimate-month]");
    const total = this.host.querySelector("[data-invoice-estimate-total]");
    if (!card || !month || !total) return;
    const billingHistory = this._billingHistory;
    const estimate = buildInvoiceEstimate(
      billingHistory?.price_periods,
      billingHistory?.energy_points,
      this._eonGridPrice,
      this._electricityProviderState?.summary?.tariff?.fixed_fee_incl_vat_per_month,
    );
    const configured = this._meterState?.configured === true;
    card.hidden = !configured || !billingHistory;
    if (!configured || !billingHistory) {
      this._invoiceEstimateRaw = null;
      card._livePowerRaw = null;
      this._renderInvoiceCardCosts();
      return;
    }
    month.textContent = estimate?.month ? this._formatInvoiceMonth(estimate.month).split(" ")[0] : "";
    if (!estimate) {
      total.textContent = "–";
      this._invoiceEstimateRaw = null;
      card._livePowerRaw = null;
      this._renderInvoiceCardCosts();
      return;
    }
    total.textContent = estimate.estimated_month_total_sek == null || !Number.isFinite(Number(estimate.estimated_month_total_sek))
      ? "–"
      : this._formatSek(Number(estimate.estimated_month_total_sek));
    const previousActual = billingHistory.previous_month_actual || buildPreviousMonthActual(
      billingHistory.invoice_sources || {
        trade: billingHistory.trade_invoices || this._electricityProviderState?.invoice_history,
        grid: billingHistory.grid_invoices,
      },
      estimate.month,
    );
    if (!this._costSelectedMonth || this._costSelectedMonth > estimate.month) this._costSelectedMonth = estimate.month;
    const comparison = buildInvoiceComparison(estimate, previousActual);
    this._invoiceEstimateRaw = {
      ...estimate,
      current_estimate: estimate,
      previous_month_actual: previousActual,
      comparison,
      provenance: buildInvoiceProvenance(estimate, { ...billingHistory, grid_price: this._eonGridPrice || billingHistory.grid_price }),
    };
    card._livePowerRaw = this._invoiceEstimateRaw;
    this._renderInvoiceCardCosts();
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
  }

  _renderCostCard() {
    const card = this.host.querySelector("[data-cost-card]");
    const period = this.host.querySelector("[data-cost-period]");
    const summary = this.host.querySelector("[data-cost-summary]");
    const selectedPeriod = this.host.querySelector("[data-cost-selected-period]");
    const previousButton = this.host.querySelector("[data-cost-previous]");
    const nextButton = this.host.querySelector("[data-cost-next]");
    if (!card || !period || !summary) return;
    const estimate = this._invoiceEstimateRaw;
    const currentMonth = estimate?.month || null;
    const selectedMonth = this._costSelectedMonth || currentMonth;
    const previous = estimate?.previous_month_actual;
    const showingCurrent = selectedMonth === currentMonth;
    const rows = showingCurrent ? [
      ["Status", estimate?.forecast_confidence === "partial_data" ? "Delvis underlag" : "Estimerad"],
      ["Estimerad månad", Number.isFinite(Number(estimate?.estimated_month_total_sek)) ? this._formatSek(Number(estimate.estimated_month_total_sek)) : null],
      ["Kostnad hittills", Number.isFinite(Number(estimate?.total_so_far_sek)) ? this._formatSek(Number(estimate.total_so_far_sek)) : null],
      ["Prognos återstående", Number.isFinite(Number(estimate?.forecast_remaining_total_sek)) ? this._formatSek(Number(estimate.forecast_remaining_total_sek)) : null],
      ["Elhandel", Number.isFinite(Number(estimate?.trade?.total_so_far_sek)) ? this._formatSek(Number(estimate.trade.total_so_far_sek)) : null],
      ["Elnät", Number.isFinite(Number(estimate?.grid?.total_so_far_sek)) ? this._formatSek(Number(estimate.grid.total_so_far_sek)) : null],
      ["Fast kostnad", Number.isFinite(Number(estimate?.trade?.accrued_fixed_fee_sek)) || Number.isFinite(Number(estimate?.grid?.accrued_fixed_fee_sek)) ? this._formatSek((Number(estimate?.trade?.accrued_fixed_fee_sek) || 0) + (Number(estimate?.grid?.accrued_fixed_fee_sek) || 0)) : null],
      ["Rörlig kostnad", Number.isFinite(Number(estimate?.trade?.variable_cost_sek)) || Number.isFinite(Number(estimate?.grid?.variable_cost_sek)) ? this._formatSek((Number(estimate?.trade?.variable_cost_sek) || 0) + (Number(estimate?.grid?.variable_cost_sek) || 0)) : null],
      ["Importerad energi", Number.isFinite(Number(estimate?.imported_kwh_so_far)) ? `${this._formatNumber(Number(estimate.imported_kwh_so_far))} kWh` : null],
      ["Prognostiserad import", Number.isFinite(Number(estimate?.forecast_import_kwh)) ? `${this._formatNumber(Number(estimate.forecast_import_kwh))} kWh` : null],
      ["Genomsnittligt totalpris", Number.isFinite(Number(estimate?.total_weighted_average_ore_per_kwh)) ? `${this._formatNumber(Number(estimate.total_weighted_average_ore_per_kwh))} öre/kWh` : null],
    ] : previous?.month === selectedMonth ? [
      ["Status", previous.coverage === "complete" ? "Fakturerad" : "Delvis underlag"],
      ["Elhandel", Number.isFinite(Number(previous.trade?.comparison_value_sek)) ? this._formatSek(Number(previous.trade.comparison_value_sek)) : null],
      ["Elnät", Number.isFinite(Number(previous.grid?.comparison_value_sek)) ? this._formatSek(Number(previous.grid.comparison_value_sek)) : null],
      ["Total", Number.isFinite(Number(previous.total_sek)) ? this._formatSek(Number(previous.total_sek)) : null],
    ] : [["Status", "Data saknas"]];
    card.hidden = !estimate || !rows.length;
    period.textContent = selectedMonth ? this._formatInvoiceMonth(selectedMonth) : "";
    if (selectedPeriod) selectedPeriod.textContent = period.textContent;
    if (previousButton) previousButton.disabled = !selectedMonth;
    if (nextButton) nextButton.disabled = !selectedMonth || selectedMonth >= currentMonth;
    summary.replaceChildren(...rows.flatMap(([label, value]) => {
      const name = document.createElement("span");
      name.textContent = label;
      const output = document.createElement("strong");
      output.textContent = value;
      return [name, output];
    }));
  }

  _bindCostCard() {
    const previous = this.host.querySelector("[data-cost-previous]");
    const next = this.host.querySelector("[data-cost-next]");
    if (previous) previous.addEventListener("click", () => {
      const current = this._costSelectedMonth || this._invoiceEstimateRaw?.month;
      if (!current) return;
      this._costSelectedMonth = previousCalendarMonth(current);
      this._renderCostCard();
    });
    if (next) next.addEventListener("click", () => {
      const current = this._costSelectedMonth || this._invoiceEstimateRaw?.month;
      if (!current) return;
      const [year, month] = current.split("-").map(Number);
      const nextMonth = new Date(Date.UTC(year, month, 1));
      const nextValue = `${nextMonth.getUTCFullYear()}-${String(nextMonth.getUTCMonth() + 1).padStart(2, "0")}`;
      if (nextValue <= (this._invoiceEstimateRaw?.month || nextValue)) {
        this._costSelectedMonth = nextValue;
        this._renderCostCard();
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
      this._solarForecastEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => this.loadSolarForecast(),
        "elrakning_solar_forecast_update",
      );
      this._solarWeatherEventUnsubscribePromise = hass.connection.subscribeEvents(
        () => this.loadPowerHistory(),
        "elrakning_solar_weather_update",
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
    if (this._solarWeatherEventUnsubscribePromise) {
      Promise.resolve(this._solarWeatherEventUnsubscribePromise)
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
    this._solarWeatherEventUnsubscribePromise = null;
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
    this._socCardHeightObserver?.disconnect();
    this._socCardHeightObserver = null;
    this._themeBackgroundReady = false;
  }

  async _refreshBackendState(loadHistory = true) {
    if (this._backendHydrationPromise) return this._backendHydrationPromise;
    this._backendHydrationPromise = Promise.all([
      this.loadPriceData(),
      this.loadProviderState(),
      this.loadEonGridState(),
      this.loadGridProviders(),
      this.loadRetainedHistory(),
      this.loadMeterState(loadHistory),
      this.loadPowerState(loadHistory),
      this.loadBillingHistory(),
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
    this._eonGridPrice = this.priceSnapshot.adjustments?.grid_price || null;
    this._updatePriceComparisonControls();
    this.updatePriceSummary();
    if (this.host.querySelector(".price-chart")) this.renderPriceChart();
    this._renderInvoiceEstimateCard();
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
        this._persistChartPreferences();
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
      this._persistChartPreferences();
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
        item.append(strong, indicator, phaseLabel);
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
    const width = 960;
    const height = 300;
    const plot = { left: 44, right: 8, top: 12, bottom: 24 };
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
    const renderSignature = JSON.stringify({ metric, axisStart, axisEnd, fuse, phasePoints });
    if (renderSignature === this._phaseRenderSignature && chart.querySelector(".phase-history-svg")) return;
    this._phaseRenderSignature = renderSignature;
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
    if (!Number.isFinite(minValue) || !Number.isFinite(maxValue) || maxValue <= minValue) { minValue = 0; maxValue = 1; }
    const x = (timestamp) => plot.left + ((new Date(timestamp).getTime() - axisStart) / timeRange) * (width - plot.left - plot.right);
    const y = (value) => plot.top + (maxValue - value) / (maxValue - minValue) * (height - plot.top - plot.bottom);
    const phaseColors = PHASE_COLOR_MAP;
    const grid = [0, 0.5, 1].map((ratio) => {
      const value = maxValue - ratio * (maxValue - minValue);
      return `<line class="phase-history-gridline" x1="${plot.left}" y1="${y(value)}" x2="${width - plot.right}" y2="${y(value)}" /><text class="phase-history-axis-label" x="4" y="${y(value) + 3}">${this._formatNumber(value)} ${unit}</text>`;
    }).join("");
    const threshold = metric === "current" && Number.isFinite(fuse) && fuse > 0
      ? `<line class="phase-history-threshold" x1="${plot.left}" y1="${y(fuse)}" x2="${width - plot.right}" y2="${y(fuse)}" /><text class="phase-history-reference-label" x="${width - plot.right - 4}" y="${y(fuse) - 4}" text-anchor="end">${this._formatNumber(fuse)} A · Säkring</text>`
      : "";
    const zero = metric === "active_power" ? `<line class="phase-history-zero-line" x1="${plot.left}" y1="${y(0)}" x2="${width - plot.right}" y2="${y(0)}" /><text class="phase-history-reference-label" x="${width - plot.right - 4}" y="${y(0) - 4}" text-anchor="end">0 kW</text>` : "";
    const tickCount = useDayAxis ? 8 : 6;
    const timeTicks = Array.from({ length: tickCount + 1 }, (_, index) => axisStart + timeRange * index / tickCount);
    const timeAxis = timeTicks.map((timestamp) => {
      const date = new Date(timestamp);
      const labelText = useDayAxis ? date.toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" }) : date.toLocaleDateString("sv-SE", { day: "2-digit", month: "2-digit" });
      return `<text class="phase-history-time-label" x="${x(timestamp)}" y="${height - 5}" text-anchor="middle">${labelText}</text>`;
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
    const svgMarkup = `${grid}${threshold}${zero}${lines}${timeAxis}<g class="phase-history-hover" aria-hidden="true"></g>`;
    let svg = chart.querySelector(".phase-history-svg");
    let tooltip = chart.querySelector(".soc-tooltip");
    if (!svg || !tooltip) {
      chart.replaceChildren();
      svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.classList.add("phase-history-svg");
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", `${label} per fas`);
      tooltip = document.createElement("div");
      tooltip.className = "soc-tooltip";
      tooltip.hidden = true;
      chart.append(svg, tooltip);
    }
    svg.innerHTML = svgMarkup;
    const hover = svg.querySelector(".phase-history-hover");
    const nearest = (timestamp) => Object.fromEntries(Object.entries(phasePoints).map(([phase, points]) => [phase, points.reduce((best, point) => !best || Math.abs(new Date(point.timestamp) - timestamp) < Math.abs(new Date(best.timestamp) - timestamp) ? point : best, null)]));
    const update = (event) => {
      const pointer = pointerToPlotCoordinates(svg, event, plot, width, height);
      if (!pointer?.inside) {
        clear();
        return;
      }
      const ratio = (pointer.viewX - plot.left) / Math.max(1, width - plot.left - plot.right);
      const timestamp = new Date(axisStart + ratio * timeRange);
      const selected = nearest(timestamp);
      const fields = Object.entries(selected).filter(([, point]) => point).map(([phase, point]) => ({ label: phase.toUpperCase(), value: point.value, color: phaseColors[phase], formatted: `${metric === "voltage" ? Number(point.value).toLocaleString("sv-SE", { maximumFractionDigits: 1, minimumFractionDigits: 1 }) : this._formatNumber(metric === "current" ? Math.abs(Number(point.value)) : Number(point.value))} ${unit}` }));
      renderSharedTooltip(tooltip, { title: timestamp.toLocaleString("sv-SE", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }), fields });
      tooltip.hidden = false;
      hover.innerHTML = Object.entries(selected).filter(([, point]) => point).map(([phase, point]) => `<circle class="chart-hover-marker" fill="${phaseColors[phase]}" cx="${x(point.timestamp)}" cy="${y(Number(point.value))}" r="4" />`).join("");
      positionChartTooltip(chart, tooltip, event.clientX, event.clientY, [], this._tooltipOrbit);
    };
    const clear = () => { tooltip.hidden = true; hover.replaceChildren(); };
    if (svg.dataset.phaseHistoryBound !== "true") {
      svg.addEventListener("pointermove", update);
      svg.addEventListener("pointerleave", clear);
      svg.dataset.phaseHistoryBound = "true";
    }
  }

  async loadBillingHistory() {
    if (!this.hass?.callWS) return;
    try {
      const response = await this.hass.callWS({ type: "elrakning/billing_history" });
      this._billingHistory = response?.success === true ? response : null;
    } catch {
      this._billingHistory = null;
    }
    this._renderInvoiceEstimateCard();
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
    this._eonGridState = state;
    this._eonGridPrice = state?.grid_price || state?.tariff?.grid_price || null;
    const configured = state?.configured === true;
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
  }

  _bindEonGridDialog() {
    const open = this.host.querySelector("[data-eon-grid-configure]");
    const dialog = this.host.querySelector("[data-eon-grid-dialog]");
    const appAccount = this.host.querySelector("[data-eon-grid-app-account]");
    const appPassword = this.host.querySelector("[data-eon-grid-app-password]");
    const result = this.host.querySelector("[data-eon-grid-result]");
    const appSave = this.host.querySelector("[data-eon-grid-app-save]");
    const cancel = this.host.querySelector("[data-eon-grid-cancel]");
    const remove = this.host.querySelector("[data-eon-grid-remove]");
    const providerSelect = this.host.querySelector("[data-grid-provider]");
    if (!open || !dialog || !appAccount || !appPassword || !result || !appSave || !cancel || !remove || !providerSelect) return;
    this._renderGridProviderOptions(providerSelect);
    const close = () => {
      dialog.hidden = true;
      appAccount.value = "";
      appPassword.value = "";
      result.textContent = "";
    };
    open.addEventListener("click", async () => {
      dialog.hidden = false;
      if (!this._gridProviders?.length) await this.loadGridProviders();
      appAccount.focus();
    });
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
    this._renderPhaseHistoryCard();
    this._renderInvoiceEstimateCard();
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
      this._rebuildLivePowerMaxima();
      if (this._eonGridState?.configured === true) this._applyEonGridState(this._eonGridState);
      this._renderPhaseHistoryCard();
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
      this._meterPowerHistory = mergeMeterPowerHistoryPoint(
        this._meterPowerHistory,
        point,
        this._meterState?.power_entity,
      );
      this._renderLivePowerRow();
      this._renderPhaseHistoryCard();
    }
    if (!point?.timestamp || (point.entity_id && point.entity_id !== this._meterState?.power_entity)) return;
    this._meterPowerHistory = mergeMeterPowerHistoryPoint(
      this._meterPowerHistory,
      point,
      this._meterState?.power_entity,
    );
    if (this.host.querySelector(".price-chart")) this.renderPriceChart();
    this._renderInvoiceEstimateCard();
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
    if (this._priceComparisonVisible.grid && this._hasGridPriceData()) {
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
    input.checked = this._priceComparisonVisible.grid;
    control.title = available ? "Visa elnätskostnad i prisjämförelsen" : "Elnätspris saknas";
    control.classList.toggle("is-disabled", !available);
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
      const start = new Date(period.start);
      const end = new Date(period.end);
      const startX = x(period.start);
      const barWidth = ((end.getTime() - start.getTime()) / dayDuration) * plotWidth;
      const barColor = chartColor(category === "cheap" ? "priceCheap" : category === "expensive" ? "priceExpensive" : "priceNormal");
      return `<rect class="chart-bar ${category}" fill="${barColor}" data-index="${index}" x="${startX}" y="${top}" width="${Math.max(1, barWidth - 1)}" height="${Math.max(1, bottom - top)}" rx="1" />`;
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
      ${visibleLayers.average ? `<line class="chart-average" stroke="${chartColor("priceNormal")}" x1="${plot.left}" y1="${y(average)}" x2="${width - plot.right}" y2="${y(average)}" />` : ""}
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
          markers.push(`<circle class="chart-hover-marker chart-hover-marker-${className}" fill="${chartColor(className)}" cx="${priceMarkerX}" cy="${hoverGeometry.meterY(value)}" r="4" />`);
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
