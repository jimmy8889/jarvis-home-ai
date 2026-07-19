const elements = {
  clock: document.querySelector("#clock"),
  date: document.querySelector("#date"),
  coreState: document.querySelector("#core-state"),
  coreDetail: document.querySelector("#core-detail"),
  registry: document.querySelector("#registry"),
  rooms: document.querySelector("#rooms"),
  players: document.querySelector("#players"),
  hostname: document.querySelector("#hostname"),
  nodeDetail: document.querySelector("#node-detail"),
  temperature: document.querySelector("#temperature"),
  storage: document.querySelector("#storage"),
  updated: document.querySelector("#updated"),
};

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

function gigabytes(bytes) {
  return typeof bytes === "number" ? `${number.format(bytes / 1e9)} GB` : "—";
}

async function updateStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const value = await response.json();
    const core = value.core || {};
    const connected = core.connected === true;
    elements.coreState.textContent = connected ? "Core online" : "Core offline";
    elements.coreState.className = `state ${connected ? "online" : "offline"}`;
    elements.coreDetail.textContent = connected ? "Ready" : "Unavailable";
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
    elements.nodeDetail.textContent = value.ip_address || "No network address";
    elements.temperature.textContent =
      typeof value.cpu_temperature_c === "number"
        ? `CPU ${number.format(value.cpu_temperature_c)}°C`
        : "CPU —";
    elements.storage.textContent = `Storage ${gigabytes(value.disk?.free_bytes)} free`;
    elements.updated.textContent = `Updated ${new Date().toLocaleTimeString("en-AU", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    })}`;
  } catch (error) {
    elements.coreState.textContent = "Node error";
    elements.coreState.className = "state offline";
    elements.coreDetail.textContent = "Retrying";
    elements.updated.textContent = String(error);
  }
}

updateClock();
updateStatus();
setInterval(updateClock, 1000);
setInterval(updateStatus, 15000);
