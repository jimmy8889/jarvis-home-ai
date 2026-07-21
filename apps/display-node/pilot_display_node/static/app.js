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
    "onscreen-keyboard", "keyboard-keys", "keyboard-space", "keyboard-delete",
    "keyboard-clear", "keyboard-search", "keyboard-close",
    "assistant-overlay", "assistant-room", "assistant-response", "assistant-provider",
  ].map((id) => [id.replaceAll("-", "_"), document.querySelector(`#${id}`)]),
);

const pageNames = ["home", "energy", "music", "system"];
const number = new Intl.NumberFormat("en-AU", { maximumFractionDigits: 1 });
let mediaModel = null;
let lastSuccessfulUpdate = 0;
const selectedOutputKey = "pilot-display-selected-output";
let eventCursor = null;
let liveSnapshotsSupported = true;
let lastAssistantEvent = null;
let assistantOverlayTimer = null;

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
  const previous = elements.music_output.value || localStorage.getItem(selectedOutputKey);
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
  if (!elements.music_output.value && elements.music_output.options.length) {
    elements.music_output.selectedIndex = 0;
  }
  if (elements.music_output.value) {
    localStorage.setItem(selectedOutputKey, elements.music_output.value);
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
      showPage("music");
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
    closeKeyboard();
  } catch (error) {
    elements.music_message.textContent = String(error);
  }
}

elements.music_search_button.addEventListener("click", searchMusic);
elements.music_query.addEventListener("keydown", (event) => {
  if (event.key === "Enter") searchMusic();
});

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
      elements.home_track.textContent = current.media?.title || "Nothing playing";
      elements.home_artist.textContent = current.media?.artist || "Pilot network is quiet";
      elements.home_player.textContent = active
        ? (active.player?.name || "Pilot player") + " · " + (current.playback_state || "idle")
        : "—";
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
updateLiveSnapshot();
setInterval(updateClock, 1000);
setInterval(updateStatus, 5000);
setInterval(updateMedia, 5000);
setInterval(updateLiveSnapshot, 2500);
