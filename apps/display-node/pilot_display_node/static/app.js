const elements = Object.fromEntries(
  [
    "clock", "date", "core-state", "core-detail", "registry", "rooms", "players",
    "hostname", "node-detail", "temperature", "storage", "updated", "home-solar",
    "home-load", "home-soc", "home-track", "home-artist", "home-player",
    "energy-state", "energy-solar", "energy-home", "energy-grid",
    "energy-grid-direction", "energy-battery", "energy-battery-direction",
    "energy-soc", "soc-fill", "music-state", "now-playing-list",
  ].map((id) => [id.replaceAll("-", "_"), document.querySelector(`#${id}`)]),
);

const pageNames = ["home", "energy", "music", "system"];
const number = new Intl.NumberFormat("en-AU", { maximumFractionDigits: 1 });

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
  button.addEventListener("click", () => showPage(button.dataset.target));
});

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
updateStatus();
setInterval(updateClock, 1000);
setInterval(updateStatus, 10000);
