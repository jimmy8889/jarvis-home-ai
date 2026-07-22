const elements = Object.fromEntries(
  [
    "clock", "date", "core-state", "core-detail", "registry", "rooms", "players",
    "hostname", "node-detail", "temperature", "storage", "updated",
    "energy-state", "energy-solar", "energy-home", "energy-grid",
    "energy-grid-direction", "energy-battery", "energy-battery-direction",
    "energy-soc", "soc-fill", "energy-flow", "flow-solar", "flow-grid",
    "flow-battery", "particles-solar", "particles-grid", "particles-battery",
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
    "console-video-stop", "console-video-message",
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
  path.classList.toggle("active", active);
  path.classList.toggle("reverse", active && reverse);
  particles.classList.toggle("active", active);
  particles.classList.toggle("reverse", active && reverse);
  node.classList.toggle("active", active);
  const normalized = Math.min(1, magnitude / 6000);
  path.style.setProperty("--flow-speed", `${(2.5 - (normalized * 1.7)).toFixed(2)}s`);
  path.style.setProperty("--flow-strength", String((0.45 + (normalized * 0.55)).toFixed(2)));
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
  elements.energy_battery.textContent = watts(battery);
  elements.energy_soc.textContent = typeof soc === "number" ? `${number.format(soc)}%` : "—";
  elements.energy_grid_direction.textContent = directions.grid || energy.grid?.direction || "Unknown";
  elements.energy_battery_direction.textContent = directions.battery || energy.battery?.direction || "Unknown";
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
  );
  elements.node_home.classList.toggle("active", typeof home === "number" && home >= 25);
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
  const width = options.width || 960;
  const height = options.height || 380;
  const all = series.flatMap((item) => item.points || []).map((point) => point.value)
    .filter((value) => typeof value === "number");
  if (!all.length) {
    const message = document.createElementNS("http://www.w3.org/2000/svg", "text");
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
  for (let line = 0; line <= 4; line += 1) {
    const y = 24 + ((height - 54) * line / 4);
    const grid = document.createElementNS("http://www.w3.org/2000/svg", "line");
    grid.setAttribute("x1", "48"); grid.setAttribute("x2", String(width - 18));
    grid.setAttribute("y1", String(y)); grid.setAttribute("y2", String(y));
    grid.setAttribute("stroke", "rgba(255,255,255,.09)"); svg.append(grid);
  }
  for (const item of series) {
    const points = item.points || [];
    if (!points.length) continue;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    path.setAttribute("fill", "none"); path.setAttribute("stroke", item.color || "#55b6ff");
    path.setAttribute("stroke-width", options.strokeWidth || "4");
    path.setAttribute("stroke-linecap", "round"); path.setAttribute("stroke-linejoin", "round");
    path.setAttribute("points", points.map((point, index) => {
      const x = 48 + ((width - 66) * index / Math.max(1, points.length - 1));
      const y = 24 + ((height - 54) * (1 - ((point.value - min) / span)));
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" "));
    svg.append(path);
  }
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
  elements.energy_vehicle.textContent = watts(vehicle.power_w);
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
  const house = document.querySelector(".energy-house");
  if (house) house.src = vehicle.connected ? "/assets/house-energy.png" : "/assets/house-no-car.png";

  const history = value.history?.series || [];
  renderLineChart(elements.energy_chart, history, { zeroFloor: true });
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
    points: (tariff.feed_in_forecast || []).map((point) => ({ value: point.cents_per_kwh })),
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

function renderNowPlaying(nowPlaying = {}) {
  const items = Array.isArray(nowPlaying.items) ? nowPlaying.items : [];
  elements.music_state.textContent = nowPlaying.status === "ok"
    ? `${items.length} active`
    : "Unavailable";
  elements.music_state.className = `data-state ${nowPlaying.status === "ok" ? "online" : "offline"}`;

  const first = items[0];
  elements.now_playing_list.replaceChildren();
  if (!items.length) {
    const empty = textNode("article", "empty", "");
    empty.append(
      textNode("span", "music-note", "♪"),
      textNode("strong", "", "Nothing playing"),
      textNode("small", "", "Active music across the Pilot network will appear here."),
    );
    elements.now_playing_list.append(empty);
    return;
  }

  for (const item of items) {
    const card = textNode("article", "track-card", "");
    const glyph = textNode("div", "track-glyph", item.state === "paused" ? "Ⅱ" : "♪");
    const copy = textNode("div", "track-copy", "");
    copy.append(
      textNode("strong", "", item.title || "Unknown title"),
      textNode("span", "", item.artist || item.album || "Unknown artist"),
      textNode("small", "", `${item.player_name || "Unknown player"} · ${item.state}`),
    );
    const volume = textNode(
      "div",
      "track-volume",
      typeof item.volume_percent === "number" ? `${item.volume_percent}%` : "",
    );
    card.append(glyph, copy, volume);
    elements.now_playing_list.append(card);
  }
}

function musicPlayerEntries(value) {
  const players = value?.media?.players || {};
  return Object.values(players).filter((item) => (
    item?.player?.kind === "music" &&
    item.player.control_enabled === true &&
    item.player.enabled === true
  ));
}

function renderMusicControls(value) {
  mediaModel = value;
  const previous = elements.music_output.value || localStorage.getItem(selectedOutputKey);
  const rooms = Array.isArray(value?.rooms) ? value.rooms : [];
  elements.music_output.replaceChildren();
  for (const room of rooms) {
    if (room.music_enabled === false) continue;
    const player = room.players?.find(
      (item) => item.id === room.default_music_player_id && item.control_enabled,
    );
    if (!player) continue;
    const option = document.createElement("option");
    option.value = player.id;
    option.textContent = room.name;
    elements.music_output.append(option);
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

  const entries = musicPlayerEntries(value);
  const activeConsole = entries.find((entry) => entry.effective?.playback_state === "playing") ||
    entries.find((entry) => entry.effective?.media?.title);
  if (elements.console_track) {
    elements.console_track.textContent = activeConsole?.effective?.media?.title || "Ready";
    elements.console_artist.textContent = activeConsole?.effective?.media?.artist || "Choose music or video";
    elements.console_now_playing.classList.toggle("active", Boolean(activeConsole));
  }
  elements.now_playing_list.replaceChildren();
  if (!entries.length) {
    elements.now_playing_list.append(
      textNode("article", "empty compact", "No controllable music players are available."),
    );
    return;
  }
  for (const entry of entries) {
    const player = entry.player;
    const effective = entry.effective || {};
    const media = effective.media || {};
    const card = textNode("article", "track-card control-card", "");
    const copy = textNode("div", "track-copy", "");
    copy.append(
      textNode("strong", "", media.title || player.name),
      textNode("span", "", media.artist || `${player.name} · ${effective.playback_state || "unknown"}`),
    );
    if (
      typeof effective.position_seconds === "number" &&
      typeof effective.duration_seconds === "number" &&
      effective.duration_seconds > 0
    ) {
      const progress = textNode("div", "track-progress", "");
      const fill = textNode("i", "", "");
      const percent = Math.max(
        0,
        Math.min(100, (effective.position_seconds / effective.duration_seconds) * 100),
      );
      fill.style.width = percent + "%";
      progress.append(fill);
      copy.append(progress);
    }
    const queueItems = effective.queue?.items || entry.queue?.items || [];
    if (Array.isArray(queueItems) && queueItems.length > 1) {
      const currentIndex = effective.queue?.index ?? entry.queue?.index ?? 0;
      const next = queueItems.find((_item, index) => index > currentIndex);
      if (next) {
        copy.append(
          textNode(
            "small",
            "up-next",
            "Up next · " + (next.title || next.name || "Untitled"),
          ),
        );
      }
    }
    const controls = textNode("div", "track-controls", "");
    for (const [action, label] of [["play", "▶"], ["pause", "Ⅱ"], ["stop", "■"]]) {
      const button = textNode("button", "", label);
      button.type = "button";
      button.ariaLabel = `${action} ${player.name}`;
      button.addEventListener("click", () => sendMedia(action, { player_id: player.id }));
      controls.append(button);
    }
    const volume = document.createElement("input");
    volume.type = "range";
    volume.min = "0";
    volume.max = "100";
    volume.value = typeof effective.volume_percent === "number"
      ? String(effective.volume_percent)
      : "30";
    volume.ariaLabel = `${player.name} volume`;
    volume.addEventListener("change", () => sendMedia("set_volume", {
      player_id: player.id,
      volume: Number(volume.value),
    }));
    card.append(copy, controls, volume);
    elements.now_playing_list.append(card);
  }
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

async function updateMedia() {
  try {
    const response = await fetch("/api/media", { cache: "no-store" });
    const value = await response.json();
    const firstModeRead = !document.body.dataset.mode;
    document.body.dataset.mode = value.mode || "display";
    if (
      firstModeRead &&
      value.mode === "media-console" &&
      !window.location.hash
    ) {
      showPage("media");
    }
    if (!response.ok) throw new Error(value.detail || `HTTP ${response.status}`);
    renderMusicControls(value);
    elements.music_message.textContent = "";
  } catch (error) {
    elements.music_message.textContent = String(error);
  }
}

async function sendMedia(action, extra = {}) {
  const playerId = extra.player_id || elements.music_output.value;
  if (!playerId) return;
  elements.music_message.textContent = `${action.replaceAll("_", " ")}…`;
  try {
    await postJSON("/api/media", { action, player_id: playerId, ...extra });
    elements.music_message.textContent = "Done";
    await Promise.all([updateStatus(), updateMedia()]);
  } catch (error) {
    elements.music_message.textContent = String(error);
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
  if (!result.image) return textNode("span", `${className} placeholder`, result.kind === "artist" ? "♫" : "♪");
  const image = document.createElement("img");
  image.className = className;
  image.src = result.image;
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
  elements.music_message.textContent = "Searching…";
  try {
    const value = await postJSON("/api/media/search", { query, limit: 12 });
    const results = flattenSearchResults(value);
    renderSearchGroups(results);
    elements.music_message.textContent = results.length
      ? `${results.length} results`
      : "No results";
    closeKeyboard();
  } catch (error) {
    elements.music_message.textContent = String(error);
  }
}

elements.music_search_button.addEventListener("click", searchMusic);
elements.music_query.addEventListener("keydown", (event) => {
  if (event.key === "Enter") searchMusic();
});

document.querySelectorAll("[data-console-target]").forEach((button) => {
  button.addEventListener("click", () => {
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

function openKeyboard() {
  elements.onscreen_keyboard.hidden = false;
  document.body.classList.add("keyboard-open");
}

function closeKeyboard() {
  elements.onscreen_keyboard.hidden = true;
  document.body.classList.remove("keyboard-open");
  elements.music_query.blur();
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

for (const key of "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") {
  const button = textNode("button", "", key);
  button.type = "button";
  button.addEventListener("click", () => {
    elements.music_query.value += key;
  });
  elements.keyboard_keys.append(button);
}
elements.music_query.addEventListener("focus", openKeyboard);
elements.keyboard_space.addEventListener("click", () => {
  elements.music_query.value += " ";
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
}

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    showPage(button.dataset.target);
    window.location.hash = button.dataset.target;
  });
});
window.addEventListener("hashchange", () => showPage(window.location.hash.slice(1)));

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
      const merged = {
        rooms: mediaModel?.rooms || [],
        media: value.media,
      };
      renderMusicControls(merged);
      const entries = musicPlayerEntries(merged);
      const active = entries.find((entry) => entry.effective?.playback_state === "playing") ||
        entries.find((entry) => entry.effective?.media?.title);
      const current = active?.effective || {};
      elements.music_state.textContent = entries.length
        ? entries.length + " available"
        : "No players";
      elements.music_state.className = "data-state " + (entries.length ? "online" : "offline");
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
    renderNowPlaying(value.surface?.now_playing || {});
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
setInterval(updateMedia, 5000);
setInterval(updateDashboard, 30000);
setInterval(updateLiveSnapshot, 2500);
