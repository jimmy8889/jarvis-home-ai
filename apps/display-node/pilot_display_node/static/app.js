const elements = Object.fromEntries(
  [
    "clock", "date", "core-state", "core-detail", "registry", "rooms", "players",
    "hostname", "node-detail", "temperature", "storage", "updated",
    "energy-state", "energy-solar", "energy-home", "energy-grid",
    "energy-grid-direction", "energy-battery", "energy-battery-direction",
    "energy-soc", "soc-fill", "energy-flow", "flow-solar", "flow-grid",
    "flow-battery", "flow-home", "particles-solar", "particles-grid", "particles-battery",
    "particles-home",
    "node-solar", "node-grid", "node-home", "node-battery",
    "flow-vehicle", "flow-server", "particles-vehicle", "particles-server",
    "node-vehicle", "node-server", "energy-vehicle", "energy-server", "vehicle-state",
    "daily-generated", "daily-home", "daily-export", "daily-generated-large",
    "daily-home-large", "daily-export-large", "vehicle-soc", "vehicle-connected",
    "tariff-buy", "tariff-fit", "tariff-chart", "energy-chart", "chart-legend",
    "weather-condition", "weather-icon", "weather-temperature", "weather-detail",
    "temperature-grid", "forecast-row",
    "music-state", "now-playing-list", "music-query", "music-search-button",
    "music-output", "music-message", "music-results",
    "onscreen-keyboard", "keyboard-keys", "keyboard-space", "keyboard-delete",
    "keyboard-clear", "keyboard-search", "keyboard-close",
    "assistant-overlay", "assistant-room", "assistant-response", "assistant-provider",
    "console-now-playing", "console-track", "console-artist", "console-video-panel",
    "console-video-input", "console-video-play", "console-video-pause",
    "console-video-stop", "console-video-message", "console-video-target", "console-clock", "console-date",
    "console-weather-icon", "console-weather-temperature", "console-weather-condition",
    "console-energy-solar", "console-energy-home", "console-energy-battery",
    "console-energy-soc", "console-artwork", "console-progress-fill", "console-play-toggle",
  ].map((id) => [id.replaceAll("-", "_"), document.querySelector(`#${id}`)]),
);

const dashboardPages = ["home", "history", "daily", "climate", "music", "system"];
function pageNames() {
  return document.body.dataset.mode === "media-console"
    ? ["media", ...dashboardPages]
    : dashboardPages;
}
const number = new Intl.NumberFormat("en-AU", { maximumFractionDigits: 1 });
let mediaModel = null;
let lastSuccessfulUpdate = 0;
const selectedOutputKey = "pilot-display-selected-output";
let eventCursor = null;
let liveSnapshotsSupported = true;
let lastAssistantEvent = null;
let assistantOverlayTimer = null;
let dashboardModel = null;
let mediaPollPromise = null;
let lastMediaObservedAt = 0;
let currentMediaEntries = [];
let mediaCommandSequence = 0;
let musicSearchSequence = 0;
let activeHouseSceneIndex = 0;
const HOUSE_SCENES = Object.freeze({
  "house-day": "/assets/house-day.png",
  "house-day-tesla": "/assets/house-day-tesla.png",
  "house-night": "/assets/house-night.png",
  "house-night-tesla": "/assets/house-night-tesla.png",
});
const flowDiagram = document.querySelector(".flow-lines");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
let smilPaused = null;

function applyPerformanceProfile(profile) {
  const normalized = profile === "low-power" ? "low-power" : "balanced";
  if (document.body.dataset.performanceProfile !== normalized) {
    document.body.dataset.performanceProfile = normalized;
    smilPaused = null;
  }
  syncAnimationActivity();
}

function syncAnimationActivity() {
  const homeVisible = document.querySelector('.page.active')?.dataset.page === "home";
  const pagePaused = document.hidden || !homeVisible || reducedMotion.matches;
  document.body.classList.toggle("motion-paused", pagePaused);
  const pauseSmil = pagePaused || document.body.dataset.performanceProfile === "low-power";
  if (smilPaused === pauseSmil) return;
  if (pauseSmil) flowDiagram?.pauseAnimations?.();
  else flowDiagram?.unpauseAnimations?.();
  smilPaused = pauseSmil;
}

if (typeof reducedMotion.addEventListener === "function") {
  reducedMotion.addEventListener("change", syncAnimationActivity);
} else {
  reducedMotion.addListener(syncAnimationActivity);
}

function renderHouseScene(value, power, vehicle) {
  const images = [...document.querySelectorAll(".energy-house")];
  if (images.length !== 2) return;
  const configuredDay = value.scene?.is_day;
  const isDay = typeof configuredDay === "boolean" ? configuredDay : false;
  const scene = `house-${isDay ? "day" : "night"}${vehicle.connected ? "-tesla" : ""}`;
  const current = images[activeHouseSceneIndex];
  if (current?.dataset.scene === scene) return;

  const nextIndex = activeHouseSceneIndex === 0 ? 1 : 0;
  const next = images[nextIndex];
  next.dataset.scene = scene;
  next.src = HOUSE_SCENES[scene];
  const reveal = () => {
    if (next.dataset.scene !== scene) return;
    images.forEach((image, index) => image.classList.toggle("active", index === nextIndex));
    activeHouseSceneIndex = nextIndex;
  };
  if (next.complete && next.naturalWidth > 0) {
    requestAnimationFrame(reveal);
  } else {
    next.addEventListener("load", reveal, { once: true });
  }
}

function updateClock() {
  const now = new Date();
  elements.clock.textContent = new Intl.DateTimeFormat("en-AU", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(now);
  elements.date.textContent = new Intl.DateTimeFormat("en-AU", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(now);
  if (elements.console_clock) elements.console_clock.textContent = elements.clock.textContent;
  if (elements.console_date) elements.console_date.textContent = elements.date.textContent;
}

function watts(value, signed = false) {
  if (typeof value !== "number") return "—";
  const magnitude = Math.abs(value);
  const formatted = magnitude >= 1000
    ? `${number.format(magnitude / 1000)} kW`
    : `${number.format(magnitude)} W`;
  if (!signed || value === 0) return formatted;
  return `${value > 0 ? "+" : "−"}${formatted}`;
}

function gigabytes(bytes) {
  return typeof bytes === "number" ? `${number.format(bytes / 1e9)} GB` : "—";
}

function setFlow(path, particles, node, value, reverse = false, threshold = 25) {
  if (!path || !particles || !node) return;
  const magnitude = typeof value === "number" ? Math.abs(value) : 0;
  const active = magnitude >= threshold;
  const direction = active && reverse;
  path.classList.toggle("active", active);
  path.classList.toggle("reverse", direction);
  particles.classList.toggle("active", active);
  particles.classList.toggle("reverse", direction);
  node.classList.toggle("active", active);
  const normalized = Math.min(1, magnitude / 6000);
  // Quantising avoids invalidating the SVG paint tree for sensor noise while
  // retaining a visibly power-scaled speed and intensity.
  const speedSeconds = Math.round((2.5 - (normalized * 1.7)) * 10) / 10;
  const speed = `${speedSeconds.toFixed(1)}s`;
  const steps = String(Math.max(8, Math.round(speedSeconds * 10)));
  const strength = String((Math.round((0.45 + (normalized * 0.55)) * 20) / 20).toFixed(2));
  if (path.dataset.flowSpeed !== speed) {
    path.dataset.flowSpeed = speed;
    path.style.setProperty("--flow-speed", speed);
  }
  if (path.dataset.flowStrength !== strength) {
    path.dataset.flowStrength = strength;
    path.style.setProperty("--flow-strength", strength);
  }
  if (path.dataset.flowSteps !== steps) {
    path.dataset.flowSteps = steps;
    path.style.setProperty("--flow-steps", steps);
  }
}

function renderEnergy(energy = {}) {
  const power = energy.power || {};
  const solar = power.solar_w ?? energy.solar?.value;
  const home = power.home_load_w ?? energy.home_load?.value;
  const grid = power.grid_w ?? energy.grid?.value;
  const battery = power.battery_w ?? energy.battery?.value;
  const soc = power.battery_soc_percent ?? energy.battery_soc?.value;
  const directions = power.directions || {};
  elements.energy_solar.textContent = watts(solar);
  elements.energy_home.textContent = watts(home);
  elements.energy_grid.textContent = watts(grid);
  const batteryActive = typeof battery === "number" && Math.abs(battery) >= 100;
  elements.energy_battery.textContent = batteryActive ? watts(battery) : "";
  elements.energy_soc.textContent = typeof soc === "number" ? `${number.format(soc)}%` : "—";
  elements.energy_grid_direction.textContent = directions.grid || energy.grid?.direction || "Unknown";
  elements.energy_battery_direction.textContent = batteryActive
    ? (directions.battery || energy.battery?.direction || "Unknown")
    : "Idle";
  elements.energy_state.textContent = energy.status === "ok" ? "Live" : "Unavailable";
  elements.energy_state.className = `data-state ${energy.status === "ok" ? "online" : "offline"}`;
  const clampedSoc = typeof soc === "number" ? Math.max(0, Math.min(100, soc)) : 0;
  elements.soc_fill.style.width = `${clampedSoc}%`;

  setFlow(elements.flow_solar, elements.particles_solar, elements.node_solar, solar);
  setFlow(elements.flow_grid, elements.particles_grid, elements.node_grid, grid, grid < 0, 100);
  setFlow(
    elements.flow_battery,
    elements.particles_battery,
    elements.node_battery,
    battery,
    battery < 0,
    100,
  );
  setFlow(elements.flow_home, elements.particles_home, elements.node_home, home);
  const batteryDirection = directions.battery || energy.battery?.direction;
  const batteryDischarging = batteryDirection === "discharging" || (
    !batteryDirection && typeof battery === "number" && battery >= 25
  );
  elements.energy_flow.classList.toggle(
    "battery-feeding-home",
    batteryDischarging && typeof home === "number" && home >= 25,
  );
  elements.energy_flow.setAttribute(
    "aria-label",
    `Solar ${watts(solar)}, home load ${watts(home)}, grid ${
      energy.grid?.direction || "unknown"
    } ${watts(grid)}, battery ${
      energy.battery?.direction || "unknown"
    } ${watts(battery)}, state of charge ${
      typeof soc === "number" ? `${number.format(soc)} percent` : "unknown"
    }`,
  );
}

function energyKWh(value) {
  return typeof value === "number" ? `${number.format(value)} kWh` : "—";
}

function renderLineChart(svg, series, options = {}) {
  if (!svg) return;
  svg.replaceChildren();
  const svgNamespace = "http://www.w3.org/2000/svg";
  const width = options.width || 960;
  const height = options.height || 380;
  const left = 48;
  const right = width - 18;
  const top = 24;
  const bottom = height - (options.showTimeAxis ? 42 : 30);
  const startedAt = Date.parse(options.startedAt || "");
  const endedAt = Date.parse(options.endedAt || "");
  const hasTimeDomain = Number.isFinite(startedAt) && Number.isFinite(endedAt) && endedAt > startedAt;
  const all = series.flatMap((item) => visibleHistorySegments(item).flat()).map((point) => point.value)
    .filter((value) => typeof value === "number");
  if (!all.length) {
    const message = document.createElementNS(svgNamespace, "text");
    message.setAttribute("x", String(width / 2));
    message.setAttribute("y", String(height / 2));
    message.setAttribute("text-anchor", "middle");
    message.setAttribute("fill", "#8190a4");
    message.textContent = "Waiting for history";
    svg.append(message);
    return;
  }
  const min = options.zeroFloor ? Math.min(0, ...all) : Math.min(...all);
  const max = Math.max(...all);
  const span = Math.max(1, max - min);
  const yFor = (value) => top + ((bottom - top) * (1 - ((value - min) / span)));
  const xFor = (point, index, pointCount) => {
    const at = Date.parse(point.at || "");
    if (hasTimeDomain && Number.isFinite(at)) {
      const fraction = Math.max(0, Math.min(1, (at - startedAt) / (endedAt - startedAt)));
      return left + ((right - left) * fraction);
    }
    return left + ((right - left) * index / Math.max(1, pointCount - 1));
  };
  const definitions = document.createElementNS(svgNamespace, "defs");
  svg.append(definitions);
  for (let line = 0; line <= 4; line += 1) {
    const y = top + ((bottom - top) * line / 4);
    const grid = document.createElementNS(svgNamespace, "line");
    grid.setAttribute("x1", String(left)); grid.setAttribute("x2", String(right));
    grid.setAttribute("y1", String(y)); grid.setAttribute("y2", String(y));
    grid.setAttribute("stroke", "rgba(255,255,255,.09)"); svg.append(grid);
  }
  const zeroY = yFor(0);
  const zeroLine = document.createElementNS(svgNamespace, "line");
  zeroLine.setAttribute("x1", String(left)); zeroLine.setAttribute("x2", String(right));
  zeroLine.setAttribute("y1", String(zeroY)); zeroLine.setAttribute("y2", String(zeroY));
  zeroLine.setAttribute("stroke", "rgba(255,255,255,.22)");
  zeroLine.setAttribute("stroke-width", "1.5");
  svg.append(zeroLine);
  series.forEach((item, seriesIndex) => {
    const segments = visibleHistorySegments(item);
    if (!segments.length) return;
    const gradientId = `pilot-chart-gradient-${seriesIndex}`;
    const gradient = document.createElementNS(svgNamespace, "linearGradient");
    gradient.setAttribute("id", gradientId);
    gradient.setAttribute("x1", "0"); gradient.setAttribute("x2", "0");
    gradient.setAttribute("y1", "0"); gradient.setAttribute("y2", "1");
    for (const [offset, opacity] of [["0%", ".42"], ["58%", ".18"], ["100%", ".03"]]) {
      const stop = document.createElementNS(svgNamespace, "stop");
      stop.setAttribute("offset", offset);
      stop.setAttribute("stop-color", item.color || "#55b6ff");
      stop.setAttribute("stop-opacity", opacity);
      gradient.append(stop);
    }
    definitions.append(gradient);
    segments.forEach((points) => {
      if (!points.length) return;
      const rawCoordinates = points.map((point, index) => ({
        x: xFor(point, index, points.length),
        y: yFor(point.value),
      }));
      const coordinates = item.render_mode === "step"
        ? rawCoordinates.flatMap((point, index) => (
          index === 0 ? [point] : [{ x: point.x, y: rawCoordinates[index - 1].y }, point]
        ))
        : rawCoordinates;
      const area = document.createElementNS(svgNamespace, "path");
      area.setAttribute(
        "d",
        `M ${coordinates[0].x.toFixed(1)} ${zeroY.toFixed(1)} ` +
        coordinates.map((point) => `L ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ") +
        ` L ${coordinates.at(-1).x.toFixed(1)} ${zeroY.toFixed(1)} Z`,
      );
      area.setAttribute("fill", `url(#${gradientId})`);
      svg.append(area);
      const path = document.createElementNS(svgNamespace, "polyline");
      path.setAttribute("fill", "none"); path.setAttribute("stroke", item.color || "#55b6ff");
      path.setAttribute("stroke-width", options.strokeWidth || "4");
      path.setAttribute("stroke-linecap", "round"); path.setAttribute("stroke-linejoin", "round");
      path.setAttribute("points", coordinates.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" "));
      svg.append(path);
    });
  });
  if (options.showTimeAxis && hasTimeDomain) {
    const formatTime = new Intl.DateTimeFormat([], { hour: "numeric" });
    for (let tick = 0; tick <= 4; tick += 1) {
      const fraction = tick / 4;
      const x = left + ((right - left) * fraction);
      const label = document.createElementNS(svgNamespace, "text");
      label.setAttribute("x", String(x));
      label.setAttribute("y", String(height - 8));
      label.setAttribute("text-anchor", tick === 0 ? "start" : tick === 4 ? "end" : "middle");
      label.setAttribute("fill", "#8190a4");
      label.setAttribute("font-size", "13");
      label.textContent = formatTime.format(new Date(startedAt + ((endedAt - startedAt) * fraction)));
      svg.append(label);
    }
  }
}

function visibleHistorySegments(item = {}) {
  const points = item.points || [];
  const threshold = Number(item.activity_threshold_w);
  if (!Number.isFinite(threshold) || threshold <= 0) return points.length ? [points] : [];
  const segments = [];
  let active = [];
  points.forEach((point) => {
    if (typeof point.value === "number" && Math.abs(point.value) >= threshold) {
      active.push(point);
    } else if (active.length) {
      segments.push(active);
      active = [];
    }
  });
  if (active.length) segments.push(active);
  return segments;
}

function weatherGlyph(condition = "") {
  if (condition.includes("rain") || condition.includes("pour")) return "☂";
  if (condition.includes("cloud")) return "☁";
  if (condition.includes("storm")) return "ϟ";
  if (condition.includes("night")) return "☾";
  return "☀";
}

function renderDashboard(value = {}) {
  dashboardModel = value;
  renderEnergy(value);
  const daily = value.daily || {};
  for (const element of [elements.daily_generated, elements.daily_generated_large]) {
    if (element) element.textContent = energyKWh(daily.solar_generated_kwh);
  }
  for (const element of [elements.daily_home, elements.daily_home_large]) {
    if (element) element.textContent = energyKWh(daily.home_used_kwh);
  }
  for (const element of [elements.daily_export, elements.daily_export_large]) {
    if (element) element.textContent = energyKWh(daily.grid_exported_kwh);
  }
  const power = value.power || {};
  const vehicle = value.vehicle || {};
  const vehicleDrawingPower = typeof vehicle.power_w === "number" && Math.abs(vehicle.power_w) >= 100;
  elements.energy_vehicle.textContent = vehicleDrawingPower
    ? watts(vehicle.power_w)
    : (vehicle.connected ? "Plugged in" : "Away");
  elements.energy_server.textContent = watts(power.server_rack_w);
  elements.vehicle_state.textContent = vehicle.connected
    ? (vehicle.charging ? "Charging" : "Plugged in") : "Not connected";
  elements.vehicle_soc.textContent = typeof vehicle.state_of_charge_percent === "number"
    ? `${number.format(vehicle.state_of_charge_percent)}%` : "—";
  elements.vehicle_connected.textContent = vehicle.connected
    ? (vehicle.charging ? `${watts(vehicle.power_w)} · charging` : "Plugged in")
    : "Not plugged in";
  setFlow(elements.flow_vehicle, elements.particles_vehicle, elements.node_vehicle, vehicle.power_w, false, 100);
  setFlow(elements.flow_server, elements.particles_server, elements.node_server, power.server_rack_w);
  elements.node_vehicle.classList.toggle("connected", vehicle.connected === true);
  elements.node_battery.classList.toggle("charging", power.directions?.battery === "charging");
  elements.node_battery.classList.toggle("discharging", power.directions?.battery === "discharging");
  renderHouseScene(value, power, vehicle);
  if (elements.console_energy_solar) elements.console_energy_solar.textContent = watts(power.solar_w);
  if (elements.console_energy_home) elements.console_energy_home.textContent = watts(power.home_load_w);
  if (elements.console_energy_battery) elements.console_energy_battery.textContent = watts(power.battery_w);
  if (elements.console_energy_soc) {
    elements.console_energy_soc.textContent = typeof power.battery_soc_percent === "number"
      ? `${number.format(power.battery_soc_percent)}% · ${power.directions?.battery || "idle"}`
      : "State of charge unavailable";
  }

  const history = value.history?.series || [];
  renderLineChart(elements.energy_chart, history, {
    zeroFloor: true,
    startedAt: value.history?.started_at,
    endedAt: value.history?.ended_at,
    showTimeAxis: true,
  });
  elements.chart_legend.replaceChildren(...history.map((item) => {
    const legend = textNode("span", "", item.label);
    legend.style.setProperty("--legend-color", item.color);
    return legend;
  }));
  const tariff = value.tariff || {};
  elements.tariff_buy.textContent = typeof tariff.import_cents_per_kwh === "number"
    ? `${number.format(tariff.import_cents_per_kwh)}¢/kWh` : "—";
  elements.tariff_fit.textContent = typeof tariff.feed_in_cents_per_kwh === "number"
    ? `${number.format(tariff.feed_in_cents_per_kwh)}¢/kWh` : "—";
  renderLineChart(elements.tariff_chart, [{
    color: "#61e6a8",
    points: (tariff.feed_in_forecast || []).map((point) => ({
      at: point.at,
      value: point.cents_per_kwh,
    })),
  }], { width: 420, height: 90, strokeWidth: "3" });

  document.querySelectorAll("[data-charge-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.chargeMode === value.controls?.tesla_charging_mode?.value);
  });
  const weather = value.weather || {};
  elements.weather_condition.textContent = weather.condition || "Unavailable";
  elements.weather_icon.textContent = weatherGlyph(weather.condition || "");
  elements.weather_temperature.textContent = typeof weather.temperature_c === "number"
    ? `${number.format(weather.temperature_c)}°` : "—";
  const details = [];
  if (typeof weather.humidity_percent === "number") details.push(`${number.format(weather.humidity_percent)}% humidity`);
  if (typeof weather.wind_speed === "number") details.push(`${number.format(weather.wind_speed)} ${weather.wind_speed_unit || ""} wind`);
  elements.weather_detail.textContent = details.join(" · ") || "Weather station unavailable";
  if (elements.console_weather_icon) elements.console_weather_icon.textContent = weatherGlyph(weather.condition || "");
  if (elements.console_weather_temperature) {
    elements.console_weather_temperature.textContent = typeof weather.temperature_c === "number"
      ? `${number.format(weather.temperature_c)}°` : "—";
  }
  if (elements.console_weather_condition) {
    elements.console_weather_condition.textContent = weather.condition || "Weather unavailable";
  }
  elements.temperature_grid.replaceChildren(...(value.temperatures || []).map((item) => {
    const card = textNode("article", "temperature-card", "");
    card.append(textNode("span", "", item.label), textNode("strong", "", typeof item.temperature_c === "number" ? `${number.format(item.temperature_c)}°` : "—"));
    return card;
  }));
  elements.forecast_row.replaceChildren(...(weather.forecast || []).slice(0, 5).map((item) => {
    const card = textNode("article", "forecast-card", "");
    const date = item.at ? new Date(item.at) : null;
    card.append(
      textNode("span", "", date && !Number.isNaN(date.valueOf()) ? new Intl.DateTimeFormat("en-AU", { weekday: "short" }).format(date) : "—"),
      textNode("b", "", weatherGlyph(item.condition || "")),
      textNode("strong", "", `${item.high_temperature_c ?? "—"}° / ${item.low_temperature_c ?? "—"}°`),
      textNode("small", "", typeof item.precipitation_probability === "number" ? `${item.precipitation_probability}% rain` : (item.condition || "")),
    );
    return card;
  }));
}

function textNode(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

function musicPlayerEntries(value) {
  const players = value?.media?.players || {};
  const roomId = value?.room_id || value?.media?.room_id;
  return Object.values(players).filter((item) => (
    item?.player?.kind === "music" &&
    item.player.control_enabled === true &&
    item.player.enabled === true
  )).sort((left, right) => {
    const leftPlaying = left.effective?.playback_state === "playing" ? 1 : 0;
    const rightPlaying = right.effective?.playback_state === "playing" ? 1 : 0;
    if (leftPlaying !== rightPlaying) return rightPlaying - leftPlaying;
    const leftLocal = left.player?.room_id === roomId ? 1 : 0;
    const rightLocal = right.player?.room_id === roomId ? 1 : 0;
    return rightLocal - leftLocal;
  });
}

function artworkURL(raw) {
  if (typeof raw !== "string" || !raw.startsWith("https://")) return "";
  return "/api/artwork?url=" + encodeURIComponent(raw);
}

function effectiveArtwork(effective = {}) {
  const media = effective.media || {};
  return artworkURL(
    effective.artwork_url || media.artwork_url || media.image_url ||
    media.artwork?.source_url || "",
  );
}

function syncMusicOutputs(value) {
  const previous = elements.music_output.value || localStorage.getItem(selectedOutputKey);
  const rooms = Array.isArray(value?.rooms) ? value.rooms : [];
  const deviceRoomId = value?.room_id || value?.media?.room_id;
  const available = [];
  for (const room of rooms.filter((room) => !deviceRoomId || room.id === deviceRoomId)) {
    if (room.music_enabled === false) continue;
    const player = room.players?.find(
      (item) => item.id === room.default_music_player_id && item.control_enabled,
    );
    if (!player) continue;
    available.push({ id: player.id, name: room.name });
  }
  const signature = JSON.stringify(available);
  if (elements.music_output.dataset.signature !== signature) {
    elements.music_output.replaceChildren(...available.map((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.name;
      return option;
    }));
    elements.music_output.dataset.signature = signature;
  }
  if ([...elements.music_output.options].some((option) => option.value === previous)) {
    elements.music_output.value = previous;
  }
  if (!elements.music_output.value && elements.music_output.options.length) {
    elements.music_output.selectedIndex = 0;
  }
  if (elements.music_output.value) {
    localStorage.setItem(selectedOutputKey, elements.music_output.value);
  }
}

function makeTrackCard(player) {
  const card = textNode("article", "track-card control-card", "");
  card.dataset.playerId = player.id;
  const artwork = textNode("div", "track-artwork", "");
  const placeholder = textNode("span", "", "♪");
  const image = document.createElement("img");
  image.alt = "";
  image.hidden = true;
  image.addEventListener("error", () => {
    image.hidden = true;
    image.dataset.source = "";
    placeholder.hidden = false;
  });
  artwork.append(placeholder, image);
  const copy = textNode("div", "track-copy", "");
  copy.append(
    textNode("strong", "track-title", player.name),
    textNode("span", "track-artist", "Ready"),
    textNode("small", "track-context", player.name),
  );
  const progress = textNode("div", "track-progress", "");
  progress.append(textNode("i", "", ""));
  copy.append(progress, textNode("small", "up-next", ""));
  const controls = textNode("div", "track-controls", "");
  for (const [action, label] of [["play", "▶"], ["pause", "Ⅱ"], ["stop", "■"]]) {
    const button = textNode("button", "", label);
    button.type = "button";
    button.dataset.mediaAction = action;
    button.ariaLabel = `${action} ${player.name}`;
    button.addEventListener("click", () => sendMedia(action, { player_id: card.dataset.playerId }));
    controls.append(button);
  }
  const volume = document.createElement("input");
  volume.type = "range";
  volume.min = "0";
  volume.max = "100";
  volume.value = "30";
  volume.ariaLabel = `${player.name} volume`;
  volume.addEventListener("change", () => sendMedia("set_volume", {
    player_id: card.dataset.playerId,
    volume: Number(volume.value),
  }));
  card.append(artwork, copy, controls, volume);
  return card;
}

function updateProgressNode(node, position, duration, playing) {
  if (!node) return;
  node.dataset.position = typeof position === "number" ? String(position) : "0";
  node.dataset.duration = typeof duration === "number" ? String(duration) : "0";
  node.dataset.playing = playing ? "true" : "false";
  node.dataset.observedAt = String(Date.now());
  updateProgressClock(node);
}

function updateProgressClock(node) {
  const duration = Number(node.dataset.duration || 0);
  let position = Number(node.dataset.position || 0);
  if (node.dataset.playing === "true") {
    position += Math.max(0, Date.now() - Number(node.dataset.observedAt || Date.now())) / 1000;
  }
  const percent = duration > 0 ? Math.max(0, Math.min(100, position / duration * 100)) : 0;
  node.style.width = `${percent.toFixed(2)}%`;
}

function updateTrackCard(card, entry) {
  const player = entry.player;
  const effective = entry.effective || {};
  const media = effective.media || {};
  card.dataset.playerId = player.id;
  card.querySelector(".track-title").textContent = media.title || player.name;
  card.querySelector(".track-artist").textContent = media.artist || media.album || "Ready to play";
  card.querySelector(".track-context").textContent = `${player.name} · ${effective.playback_state || "unknown"}`;
  const queueItems = effective.queue?.items || entry.queue?.items || [];
  const currentIndex = effective.queue?.index ?? entry.queue?.index ?? 0;
  const next = Array.isArray(queueItems)
    ? queueItems.find((_item, index) => index > currentIndex)
    : null;
  card.querySelector(".up-next").textContent = next
    ? "Up next · " + (next.title || next.name || "Untitled")
    : "";
  const image = card.querySelector(".track-artwork img");
  const placeholder = card.querySelector(".track-artwork span");
  const source = effectiveArtwork(effective);
  if (source) {
    if (image.dataset.source !== source) {
      image.dataset.source = source;
      image.src = source;
    }
    image.hidden = false;
    placeholder.hidden = true;
  } else if (!source) {
    image.dataset.source = "";
    image.removeAttribute("src");
    image.hidden = true;
    placeholder.hidden = false;
  }
  updateProgressNode(
    card.querySelector(".track-progress i"),
    effective.position_seconds,
    effective.duration_seconds,
    effective.playback_state === "playing",
  );
  const volume = card.querySelector('input[type="range"]');
  if (typeof effective.volume_percent === "number" && document.activeElement !== volume) {
    volume.value = String(effective.volume_percent);
  }
  card.classList.toggle("is-playing", effective.playback_state === "playing");
}

function renderTrackCards(entries) {
  const existing = new Map(
    [...elements.now_playing_list.querySelectorAll("[data-player-id]")]
      .map((card) => [card.dataset.playerId, card]),
  );
  elements.now_playing_list.querySelector(".empty")?.remove();
  if (!entries.length) {
    const empty = textNode("article", "empty compact", "");
    empty.append(
      textNode("span", "music-note", "♪"),
      textNode("strong", "", "No music player available"),
      textNode("small", "", "Pilot is waiting for the room music endpoint."),
    );
    elements.now_playing_list.replaceChildren(empty);
    return;
  }
  for (const entry of entries) {
    const player = entry.player;
    const card = existing.get(player.id) || makeTrackCard(player);
    existing.delete(player.id);
    updateTrackCard(card, entry);
    elements.now_playing_list.append(card);
  }
  existing.forEach((card) => card.remove());
}

function renderConsolePlayer(entries, roomId) {
  if (!elements.console_track) return;
  const active = entries.find((entry) => (
    entry.player?.room_id === roomId && entry.effective?.playback_state === "playing"
  )) || entries.find((entry) => entry.effective?.playback_state === "playing") ||
    entries.find((entry) => entry.player?.room_id === roomId && entry.effective?.media?.title);
  const effective = active?.effective || {};
  const media = effective.media || {};
  elements.console_track.textContent = media.title || "Ready for music";
  elements.console_artist.textContent = media.artist || media.album || "Choose an album, video or the Shield";
  elements.console_now_playing.classList.toggle("active", Boolean(media.title));
  elements.console_now_playing.dataset.playerId = active?.player?.id || "";
  const artwork = effectiveArtwork(effective);
  if (artwork) {
    if (elements.console_artwork.dataset.source !== artwork) {
      elements.console_artwork.dataset.source = artwork;
      elements.console_artwork.src = artwork;
    }
    elements.console_artwork.hidden = false;
  } else {
    elements.console_artwork.dataset.source = "";
    elements.console_artwork.removeAttribute("src");
    elements.console_artwork.hidden = true;
  }
  const playing = effective.playback_state === "playing";
  elements.console_play_toggle.textContent = playing ? "Ⅱ" : "▶";
  elements.console_play_toggle.dataset.consoleMediaAction = playing ? "pause" : "play";
  elements.console_play_toggle.ariaLabel = playing ? "Pause" : "Play";
  updateProgressNode(
    elements.console_progress_fill,
    effective.position_seconds,
    effective.duration_seconds,
    playing,
  );
}

elements.console_artwork?.addEventListener("error", () => {
  elements.console_artwork.hidden = true;
  elements.console_artwork.dataset.source = "";
});

function renderMusicControls(value) {
  mediaModel = value;
  syncMusicOutputs(value);
  currentMediaEntries = musicPlayerEntries(value);
  const roomId = value?.room_id || value?.media?.room_id;
  const visibleEntries = currentMediaEntries.filter((entry) => (
    entry.player?.room_id === roomId ||
    ["playing", "paused"].includes(entry.effective?.playback_state)
  ));
  renderTrackCards(visibleEntries);
  renderConsolePlayer(currentMediaEntries, roomId);
  const providerOnline = value?.media?.providers?.music_assistant?.status === "ok";
  const roomPlayers = currentMediaEntries.filter((entry) => entry.player?.room_id === roomId);
  elements.music_state.textContent = providerOnline
    ? `${roomPlayers.length} ${roomPlayers.length === 1 ? "room output" : "room outputs"}`
    : "Music offline";
  elements.music_state.className = `data-state ${providerOnline ? "online" : "offline"}`;
}

elements.music_output.addEventListener("change", () => {
  if (elements.music_output.value) {
    localStorage.setItem(selectedOutputKey, elements.music_output.value);
  }
});

document.querySelectorAll("[data-charge-mode]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await postJSON("/api/dashboard/actions", {
        action: "set_tesla_charging_mode",
        value: button.dataset.chargeMode,
      });
      await updateDashboard();
    } catch (error) {
      elements.updated.textContent = String(error);
    }
  });
});

async function postJSON(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || `HTTP ${response.status}`);
  return value;
}

function applyDisplayMode(mode) {
  if (!["display", "media-console"].includes(mode)) return;
  const normalized = mode === "media-console" ? "media-console" : "display";
  document.body.dataset.mode = normalized;
  const requested = window.location.hash.slice(1);
  const fallback = normalized === "media-console" ? "media" : "home";
  const target = pageNames().includes(requested) ? requested : fallback;
  if (requested !== target) {
    window.history.replaceState(null, "", `#${target}`);
  }
  showPage(target);
}

function mediaObservedAt(value) {
  const timestamp = Date.parse(value?.media?.observed_at || "");
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function acceptMediaState(value) {
  const observedAt = mediaObservedAt(value);
  if (observedAt && observedAt < lastMediaObservedAt) return false;
  lastMediaObservedAt = Math.max(lastMediaObservedAt, observedAt);
  const incomingMedia = value?.media || {};
  const previousMedia = mediaModel?.media || {};
  const roomScoped = Boolean(incomingMedia.room_id);
  const merged = {
    ...(mediaModel || {}),
    ...value,
    mode: value.mode || mediaModel?.mode,
    room_id: value.room_id || mediaModel?.room_id || incomingMedia.room_id,
    rooms: value.rooms || mediaModel?.rooms || [],
    media: {
      ...previousMedia,
      ...incomingMedia,
      players: roomScoped
        ? { ...(previousMedia.players || {}), ...(incomingMedia.players || {}) }
        : (incomingMedia.players || previousMedia.players || {}),
    },
  };
  if (merged.mode) applyDisplayMode(merged.mode);
  renderMusicControls(merged);
  return true;
}

async function updateMedia(force = false) {
  if (mediaPollPromise) {
    if (!force) return mediaPollPromise;
    await mediaPollPromise;
  }
  mediaPollPromise = (async () => {
    try {
      const response = await fetch("/api/media", { cache: "no-store" });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || `HTTP ${response.status}`);
      acceptMediaState(value);
    } catch (error) {
      elements.music_message.textContent = String(error);
      elements.music_state.textContent = "Music offline";
      elements.music_state.className = "data-state offline";
    } finally {
      mediaPollPromise = null;
    }
  })();
  return mediaPollPromise;
}

async function sendMedia(action, extra = {}) {
  const playerId = extra.player_id || elements.music_output.value;
  if (!playerId) {
    elements.music_message.textContent = "This display has no accepted music output.";
    return;
  }
  const commandSequence = ++mediaCommandSequence;
  elements.music_message.textContent = `${action.replaceAll("_", " ")}…`;
  document.body.classList.add("media-command-busy");
  try {
    await postJSON("/api/media", { action, player_id: playerId, ...extra });
    if (commandSequence === mediaCommandSequence) {
      elements.music_message.textContent = action === "play_media"
        ? `Starting in ${elements.music_output.selectedOptions[0]?.textContent || "this room"}…`
        : "Command accepted";
    }
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    await updateMedia(true);
  } catch (error) {
    elements.music_message.textContent = String(error);
  } finally {
    if (commandSequence === mediaCommandSequence) {
      document.body.classList.remove("media-command-busy");
    }
  }
}

function flattenSearchResults(value) {
  const results = [];
  const seen = new Set();
  const visit = (candidate, fallbackKind = "other") => {
    if (Array.isArray(candidate)) {
      candidate.forEach((item) => visit(item, fallbackKind));
      return;
    }
    if (!candidate || typeof candidate !== "object") return;
    const uri = candidate.uri || candidate.media_uri;
    const title = candidate.name || candidate.title;
    if (typeof uri === "string" && typeof title === "string" && !seen.has(uri)) {
      seen.add(uri);
      const rawKind = String(candidate.media_type || candidate.type || fallbackKind).toLowerCase();
      const kind = ["artist", "album", "track", "playlist", "radio"].find((value) => rawKind.includes(value)) || "other";
      const artists = Array.isArray(candidate.artists)
        ? candidate.artists.map((artist) => artist.name).filter(Boolean).join(", ")
        : "";
      const image = candidate.image_url || candidate.artwork_url || candidate.thumbnail ||
        candidate.metadata?.images?.[0]?.path || "";
      results.push({
        uri,
        title,
        subtitle: candidate.artist || artists || candidate.album?.name || candidate.album || candidate.media_type || "",
        kind,
        image,
      });
      return;
    }
    Object.entries(candidate).forEach(([key, nested]) => visit(nested, key));
  };
  visit(value);
  return results.slice(0, 40);
}

function resultArtwork(result, className = "result-artwork") {
  const source = artworkURL(result.image);
  if (!source) return textNode("span", `${className} placeholder`, result.kind === "artist" ? "♫" : "♪");
  const image = document.createElement("img");
  image.className = className;
  image.src = source;
  image.alt = "";
  image.loading = "lazy";
  image.referrerPolicy = "no-referrer";
  image.addEventListener("error", () => image.replaceWith(textNode("span", `${className} placeholder`, "♪")));
  return image;
}

function resultButton(result, compact = false) {
  const button = textNode("button", compact || result.kind === "track" ? "search-result track-result" : "music-tile", "");
  button.type = "button";
  button.append(
    resultArtwork(result),
    (() => {
      const copy = textNode("span", "result-copy", "");
      copy.append(textNode("strong", "", result.title), textNode("small", "", result.subtitle || result.kind));
      return copy;
    })(),
  );
  button.addEventListener("click", () => {
    if (["artist", "album", "playlist"].includes(result.kind)) browseMusic(result);
    else sendMedia("play_media", { media_uri: result.uri });
  });
  return button;
}

function renderSearchGroups(results) {
  elements.music_results.replaceChildren();
  const order = ["artist", "album", "track", "playlist", "radio", "other"];
  for (const kind of order) {
    const values = results.filter((result) => result.kind === kind);
    if (!values.length) continue;
    const section = textNode("section", `music-result-group ${kind}`, "");
    section.append(textNode("h2", "", kind === "track" ? "Songs" : `${kind[0].toUpperCase()}${kind.slice(1)}s`));
    const list = textNode("div", "music-result-list", "");
    values.forEach((result) => list.append(resultButton(result, kind === "track")));
    section.append(list);
    elements.music_results.append(section);
  }
}

async function browseMusic(result) {
  elements.music_message.textContent = `Opening ${result.title}…`;
  try {
    const value = await postJSON("/api/media/browse", { uri: result.uri, media_type: result.kind });
    const back = textNode("button", "music-back", "‹ Back to results");
    back.type = "button";
    back.addEventListener("click", searchMusic);
    const hero = textNode("section", "music-detail-hero", "");
    hero.append(resultArtwork(result, "detail-artwork"));
    const copy = textNode("div", "", "");
    copy.append(textNode("span", "eyebrow", result.kind), textNode("h2", "", result.title), textNode("p", "", result.subtitle));
    const play = textNode("button", "detail-play", "▶ Play");
    play.type = "button";
    play.addEventListener("click", () => sendMedia("play_media", { media_uri: result.uri }));
    copy.append(play);
    hero.append(copy);
    elements.music_results.replaceChildren(back, hero);
    for (const sectionValue of value.sections || []) {
      const section = textNode("section", `music-result-group ${sectionValue.id || ""}`, "");
      section.append(textNode("h2", "", sectionValue.title || "Music"));
      const list = textNode("div", "music-result-list", "");
      flattenSearchResults(sectionValue.items).forEach((item) => list.append(resultButton(item, sectionValue.id === "tracks")));
      section.append(list);
      elements.music_results.append(section);
    }
    elements.music_message.textContent = result.title;
    closeKeyboard();
  } catch (error) {
    elements.music_message.textContent = String(error);
  }
}

async function searchMusic() {
  const query = elements.music_query.value.trim();
  if (!query) return;
  const searchSequence = ++musicSearchSequence;
  elements.music_message.textContent = "Searching…";
  try {
    const value = await postJSON("/api/media/search", { query, limit: 12 });
    if (searchSequence !== musicSearchSequence) return;
    const results = flattenSearchResults(value);
    renderSearchGroups(results);
    elements.music_message.textContent = results.length
      ? `${results.length} results`
      : "No results";
    closeKeyboard();
  } catch (error) {
    if (searchSequence === musicSearchSequence) elements.music_message.textContent = String(error);
  }
}

elements.music_search_button.addEventListener("click", searchMusic);
elements.music_query.addEventListener("keydown", (event) => {
  if (event.key === "Enter") searchMusic();
});

document.querySelectorAll("[data-console-target]").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.disabled) return;
    const target = button.dataset.consoleTarget;
    if (["music", "home"].includes(target)) {
      showPage(target);
      window.location.hash = target;
      return;
    }
    elements.console_video_panel.hidden = false;
    if (target === "video") {
      elements.console_video_input.focus();
    } else if (target === "shield") {
      elements.console_video_message.textContent =
        "Shield source control is ready for the Denon input mapping.";
    }
  });
});

async function sendVideo(action, extra = {}) {
  elements.console_video_message.textContent = `${action}…`;
  try {
    await postJSON("/api/video", { action, room_id: "media-room", ...extra });
    elements.console_video_message.textContent = "Command sent";
  } catch (error) {
    elements.console_video_message.textContent = String(error);
  }
}

elements.console_video_play?.addEventListener("click", () => {
  const mediaId = elements.console_video_input.value.trim();
  if (mediaId) sendVideo("play", { media_id: mediaId });
});
elements.console_video_pause?.addEventListener("click", () => sendVideo("pause"));
elements.console_video_stop?.addEventListener("click", () => sendVideo("stop"));
document.querySelectorAll("[data-console-media-action]").forEach((button) => {
  button.addEventListener("click", () => {
    const playerId = elements.console_now_playing.dataset.playerId || elements.music_output.value;
    const action = button.dataset.consoleMediaAction;
    if (action) sendMedia(action, { player_id: playerId });
  });
});

function openKeyboard() {
  elements.onscreen_keyboard.inert = false;
  elements.onscreen_keyboard.hidden = false;
  document.body.classList.add("keyboard-open");
}

function closeKeyboard() {
  document.body.classList.remove("keyboard-open");
  elements.onscreen_keyboard.hidden = true;
  elements.onscreen_keyboard.inert = true;
  if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
}

function renderAssistantEvents(events = []) {
  const latest = [...events].reverse().find((event) => (
    event?.type === "pilot.assistant.completed.v1"
  ));
  if (!latest || latest.id === lastAssistantEvent || latest.revision === lastAssistantEvent) {
    return;
  }
  lastAssistantEvent = latest.id || latest.revision;
  const payload = latest.payload || {};
  const response = payload.response_text || payload.text;
  if (!response) return;
  elements.assistant_room.textContent = payload.room_id
    ? "Pilot · " + payload.room_id.replaceAll("-", " ")
    : "Pilot";
  elements.assistant_response.textContent = response;
  elements.assistant_provider.textContent = payload.provider
    ? "Answered locally by " + payload.provider
    : "Local assistant";
  elements.assistant_overlay.hidden = false;
  window.clearTimeout(assistantOverlayTimer);
  assistantOverlayTimer = window.setTimeout(() => {
    elements.assistant_overlay.hidden = true;
  }, 10000);
}

function appendSearchKey(key) {
  elements.music_query.value += key;
  elements.music_query.dispatchEvent(new Event("input", { bubbles: true }));
}

for (const keys of ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]) {
  const row = textNode("div", "keyboard-row", "");
  row.dataset.keys = keys;
  for (const key of keys) {
    const button = textNode("button", "keyboard-key", key);
    button.type = "button";
    button.addEventListener("click", () => appendSearchKey(key));
    row.append(button);
  }
  elements.keyboard_keys.append(row);
}
elements.onscreen_keyboard.inert = true;
elements.music_query.addEventListener("focus", openKeyboard);
elements.keyboard_space.addEventListener("click", () => {
  appendSearchKey(" ");
});
elements.keyboard_delete.addEventListener("click", () => {
  elements.music_query.value = elements.music_query.value.slice(0, -1);
});
elements.keyboard_clear.addEventListener("click", () => {
  elements.music_query.value = "";
});
elements.keyboard_search.addEventListener("click", searchMusic);
elements.keyboard_close.addEventListener("click", closeKeyboard);

function showPage(name) {
  if (!pageNames().includes(name)) return;
  document.querySelectorAll(".page").forEach((page) => {
    page.classList.toggle("active", page.dataset.page === name);
  });
  document.querySelectorAll("nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.target === name);
  });
  syncAnimationActivity();
}

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    showPage(button.dataset.target);
    window.location.hash = button.dataset.target;
  });
});
window.addEventListener("hashchange", () => showPage(window.location.hash.slice(1)));
document.addEventListener("visibilitychange", syncAnimationActivity);

let swipeStart = null;
const pages = document.querySelector("#pages");
pages.addEventListener("pointerdown", (event) => {
  swipeStart = { x: event.clientX, y: event.clientY };
});
pages.addEventListener("pointerup", (event) => {
  if (!swipeStart) return;
  const dx = event.clientX - swipeStart.x;
  const dy = event.clientY - swipeStart.y;
  swipeStart = null;
  if (Math.abs(dx) < 70 || Math.abs(dx) < Math.abs(dy)) return;
  const active = document.querySelector(".page.active")?.dataset.page || "home";
  const names = pageNames();
  const index = names.indexOf(active);
  showPage(names[Math.max(0, Math.min(names.length - 1, index + (dx < 0 ? 1 : -1)))]);
});
pages.addEventListener("pointercancel", () => { swipeStart = null; });

async function updateLiveSnapshot() {
  if (!liveSnapshotsSupported) return;
  const query = eventCursor ? "?cursor=" + encodeURIComponent(eventCursor) : "";
  try {
    const response = await fetch("/api/events/snapshot" + query, { cache: "no-store" });
    if ([404, 405, 501].includes(response.status)) {
      liveSnapshotsSupported = false;
      return;
    }
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || "Live state unavailable");
    eventCursor = value.cursor || eventCursor;
    renderAssistantEvents(value.events || []);
    if (value.energy) {
      renderEnergy(value.energy);
    }
    if (value.media) {
      acceptMediaState({
        rooms: mediaModel?.rooms || [],
        room_id: mediaModel?.room_id || value.media.room_id,
        media: value.media,
      });
    }
    lastSuccessfulUpdate = Date.now();
    document.body.classList.remove("stale");
  } catch (_error) {
    if (Date.now() - lastSuccessfulUpdate > 20000) {
      document.body.classList.add("stale");
    }
  }
}

async function updateDashboard() {
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || `HTTP ${response.status}`);
    renderDashboard(value);
    lastSuccessfulUpdate = Date.now();
    document.body.classList.remove("stale");
  } catch (error) {
    elements.updated.textContent = `Dashboard: ${String(error)}`;
  }
}

async function updateStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const value = await response.json();
    applyPerformanceProfile(value.performance_profile);
    applyDisplayMode(value.mode);
    const localVideoEnabled = value.features?.local_video === true;
    if (elements.console_video_target) {
      elements.console_video_target.disabled = !localVideoEnabled;
      const detail = elements.console_video_target.querySelector("small");
      const action = elements.console_video_target.querySelector("b");
      if (detail) detail.textContent = localVideoEnabled
        ? "Supervised mpv playback"
        : "Enable after native playback acceptance";
      if (action) action.textContent = localVideoEnabled ? "Open" : "Planned";
      if (!localVideoEnabled) elements.console_video_panel.hidden = true;
    }
    const core = value.core || {};
    const connected = core.connected === true;
    elements.core_state.textContent = connected ? "Core online" : "Core offline";
    elements.core_state.className = `state ${connected ? "online" : "offline"}`;
    elements.core_detail.textContent = connected ? "Ready" : "Unavailable";
    elements.registry.textContent = core.registry_revision
      ? `Registry ${core.registry_revision}`
      : "No registry";
    elements.rooms.textContent =
      typeof core.room_count === "number" ? String(core.room_count) : "—";
    elements.players.textContent =
      typeof core.player_count === "number"
        ? `${core.player_count} configured players`
        : "No player data";
    elements.hostname.textContent = value.hostname || "Pilot display";
    elements.node_detail.textContent = value.ip_address || "No network address";
    elements.temperature.textContent =
      typeof value.cpu_temperature_c === "number"
        ? `CPU ${number.format(value.cpu_temperature_c)}°C`
        : "CPU —";
    elements.storage.textContent = `Storage ${gigabytes(value.disk?.free_bytes)} free`;
    renderEnergy(value.surface?.energy || {});
    lastSuccessfulUpdate = Date.now();
    document.body.classList.remove("stale");
    elements.updated.textContent = `Updated ${new Date().toLocaleTimeString("en-AU", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    })}`;
  } catch (error) {
    elements.core_state.textContent = "Node error";
    elements.core_state.className = "state offline";
    elements.core_detail.textContent = "Retrying";
    elements.updated.textContent = String(error);
    if (Date.now() - lastSuccessfulUpdate > 20000) {
      document.body.classList.add("stale");
      elements.core_state.textContent = "State stale";
    }
  }
}

updateClock();
showPage(window.location.hash.slice(1) || "home");
updateStatus();
updateMedia();
updateDashboard();
updateLiveSnapshot();
setInterval(updateClock, 1000);
setInterval(updateStatus, 5000);
setInterval(updateMedia, 10000);
setInterval(updateDashboard, 30000);
setInterval(updateLiveSnapshot, 2500);
setInterval(() => {
  document.querySelectorAll(".track-progress i, #console-progress-fill")
    .forEach(updateProgressClock);
}, 1000);
