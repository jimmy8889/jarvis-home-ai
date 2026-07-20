const elements = Object.fromEntries(
  [
    "clock", "date", "core-state", "core-detail", "registry", "rooms", "players",
    "hostname", "node-detail", "temperature", "storage", "updated", "home-solar",
    "home-load", "home-soc", "home-track", "home-artist", "home-player",
    "energy-state", "energy-solar", "energy-home", "energy-grid",
    "energy-grid-direction", "energy-battery", "energy-battery-direction",
    "energy-soc", "soc-fill", "energy-flow", "flow-solar", "flow-grid",
    "flow-battery", "particles-solar", "particles-grid", "particles-battery",
    "node-solar", "node-grid", "node-home", "node-battery",
    "music-state", "now-playing-list", "music-query", "music-search-button",
    "music-output", "music-message", "music-results",
  ].map((id) => [id.replaceAll("-", "_"), document.querySelector(`#${id}`)]),
);

const pageNames = ["home", "energy", "music", "system"];
const number = new Intl.NumberFormat("en-AU", { maximumFractionDigits: 1 });
let mediaModel = null;

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

function setFlow(path, particles, node, value, reverse = false) {
  const magnitude = typeof value === "number" ? Math.abs(value) : 0;
  const active = magnitude >= 25;
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
  const solar = energy.solar?.value;
  const home = energy.home_load?.value;
  const grid = energy.grid?.value;
  const battery = energy.battery?.value;
  const soc = energy.battery_soc?.value;

  elements.home_solar.textContent = watts(solar);
  elements.home_load.textContent = watts(home);
  elements.home_soc.textContent = typeof soc === "number" ? `${number.format(soc)}%` : "—";
  elements.energy_solar.textContent = watts(solar);
  elements.energy_home.textContent = watts(home);
  elements.energy_grid.textContent = watts(grid);
  elements.energy_battery.textContent = watts(battery);
  elements.energy_soc.textContent = typeof soc === "number" ? `${number.format(soc)}%` : "—";
  elements.energy_grid_direction.textContent = energy.grid?.direction || "Unknown";
  elements.energy_battery_direction.textContent = energy.battery?.direction || "Unknown";
  elements.energy_state.textContent = energy.status === "ok" ? "Live" : "Unavailable";
  elements.energy_state.className = `data-state ${energy.status === "ok" ? "online" : "offline"}`;
  const clampedSoc = typeof soc === "number" ? Math.max(0, Math.min(100, soc)) : 0;
  elements.soc_fill.style.width = `${clampedSoc}%`;

  setFlow(elements.flow_solar, elements.particles_solar, elements.node_solar, solar);
  setFlow(elements.flow_grid, elements.particles_grid, elements.node_grid, grid, grid < 0);
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
  elements.home_track.textContent = first?.title || "Nothing playing";
  elements.home_artist.textContent = first?.artist || "Pilot network is quiet";
  elements.home_player.textContent = first
    ? `${first.player_name} · ${first.state}`
    : "—";

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
  const previous = elements.music_output.value;
  const rooms = Array.isArray(value?.rooms) ? value.rooms : [];
  elements.music_output.replaceChildren();
  for (const room of rooms) {
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

  const entries = musicPlayerEntries(value);
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
  const visit = (candidate) => {
    if (Array.isArray(candidate)) {
      candidate.forEach(visit);
      return;
    }
    if (!candidate || typeof candidate !== "object") return;
    const uri = candidate.uri || candidate.media_uri;
    const title = candidate.name || candidate.title;
    if (typeof uri === "string" && typeof title === "string") {
      results.push({
        uri,
        title,
        subtitle: candidate.artist || candidate.album || candidate.media_type || "",
      });
      return;
    }
    Object.values(candidate).forEach(visit);
  };
  visit(value);
  return results.slice(0, 12);
}

async function searchMusic() {
  const query = elements.music_query.value.trim();
  if (!query) return;
  elements.music_message.textContent = "Searching…";
  try {
    const value = await postJSON("/api/media/search", { query, limit: 12 });
    const results = flattenSearchResults(value);
    elements.music_results.replaceChildren();
    for (const result of results) {
      const button = textNode("button", "search-result", "");
      button.type = "button";
      button.append(
        textNode("strong", "", result.title),
        textNode("small", "", result.subtitle || "Music Assistant"),
      );
      button.addEventListener("click", () => sendMedia("play_media", {
        media_uri: result.uri,
      }));
      elements.music_results.append(button);
    }
    elements.music_message.textContent = results.length
      ? `${results.length} results`
      : "No results";
  } catch (error) {
    elements.music_message.textContent = String(error);
  }
}

elements.music_search_button.addEventListener("click", searchMusic);
elements.music_query.addEventListener("keydown", (event) => {
  if (event.key === "Enter") searchMusic();
});

function showPage(name) {
  if (!pageNames.includes(name)) return;
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
  const index = pageNames.indexOf(active);
  showPage(pageNames[Math.max(0, Math.min(pageNames.length - 1, index + (dx < 0 ? 1 : -1)))]);
});
pages.addEventListener("pointercancel", () => { swipeStart = null; });

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
  }
}

updateClock();
showPage(window.location.hash.slice(1) || "home");
updateStatus();
updateMedia();
setInterval(updateClock, 1000);
setInterval(updateStatus, 10000);
setInterval(updateMedia, 10000);
