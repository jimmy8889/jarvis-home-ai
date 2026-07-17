"use strict";

const state = {
  token: sessionStorage.getItem("pilot-core-admin-token") || "",
  refreshTimer: null,
  loading: false,
};

const elements = {
  accessPanel: document.querySelector("#access-panel"),
  accessForm: document.querySelector("#access-form"),
  accessError: document.querySelector("#access-error"),
  tokenInput: document.querySelector("#token-input"),
  dashboard: document.querySelector("#dashboard"),
  connectionPill: document.querySelector("#connection-pill"),
  refreshButton: document.querySelector("#refresh-button"),
  disconnectButton: document.querySelector("#disconnect-button"),
  toast: document.querySelector("#toast"),
};

const text = (selector, value) => {
  const element = document.querySelector(selector);
  if (element) {
    element.textContent = String(value);
  }
};

const clear = (element) => {
  while (element.firstChild) {
    element.removeChild(element.firstChild);
  }
};

const node = (tag, className, content) => {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  if (content !== undefined) {
    element.textContent = String(content);
  }
  return element;
};

const titleCase = (value) =>
  String(value || "")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());

const formatTime = (value) => {
  if (!value) {
    return "never";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "unknown";
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
};

const formatRelative = (value) => {
  if (!value) {
    return "never";
  }
  const date = new Date(value);
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(seconds) < 60) {
    return formatter.format(seconds, "second");
  }
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) {
    return formatter.format(minutes, "minute");
  }
  return formatter.format(Math.round(minutes / 60), "hour");
};

const formatDuration = (seconds) => {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) {
    return `${days}d ${hours}h`;
  }
  if (hours) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
};

const setConnection = (kind, label) => {
  elements.connectionPill.className = `status-pill status-${kind}`;
  clear(elements.connectionPill);
  elements.connectionPill.append(node("span", "status-dot"));
  elements.connectionPill.append(document.createTextNode(label));
};

const showToast = (message) => {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    elements.toast.hidden = true;
  }, 3200);
};

const api = async (path, options = {}) => {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 12000);
  try {
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${state.token}`);
    if (options.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path, {
      ...options,
      headers,
      signal: controller.signal,
      cache: "no-store",
    });
    if (response.status === 401) {
      throw new Error("unauthorized");
    }
    if (!response.ok) {
      let detail = `Pilot Core returned ${response.status}`;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        // Keep the status-based message when the response is not JSON.
      }
      throw new Error(detail);
    }
    return await response.json();
  } finally {
    window.clearTimeout(timeout);
  }
};

const badge = (label, kind) => {
  const element = node("span", `status-pill status-${kind}`);
  element.append(node("span", "status-dot"));
  element.append(document.createTextNode(label));
  return element;
};

const healthKind = (status) => {
  if (status === "ok" || status === "succeeded") {
    return "good";
  }
  if (
    status === "not_configured" ||
    status === "configured" ||
    status === "queued" ||
    status === "delivered"
  ) {
    return "warning";
  }
  return "bad";
};

const renderSummary = (payload) => {
  const summary = payload.summary;
  text("#metric-rooms", summary.room_count);
  text(
    "#metric-rooms-detail",
    `${summary.armed_room_count} armed · ${summary.unarmed_room_count} locked`,
  );
  text(
    "#metric-devices",
    `${summary.connected_device_count}/${summary.device_count}`,
  );
  text("#metric-devices-detail", "Connected room endpoints");
  text(
    "#metric-integrations",
    `${summary.healthy_integration_count}/${summary.configured_integration_count}`,
  );
  text("#metric-integrations-detail", "Configured providers healthy");
  text("#metric-safety", payload.safety.audible_actions_gated ? "Locked" : "Armed");
  text(
    "#metric-safety-detail",
    payload.safety.audible_actions_gated
      ? "Audible actions fail closed"
      : "All rooms supervised",
  );

  const allDevicesConnected =
    summary.device_count > 0 &&
    summary.connected_device_count === summary.device_count;
  const allIntegrationsHealthy =
    summary.configured_integration_count > 0 &&
    summary.healthy_integration_count === summary.configured_integration_count;
  const observedStatus = payload.observability?.status;
  let posture = {
    healthy: "Nominal",
    guarded: "Guarded",
    degraded: "Attention",
    critical: "Critical",
  }[observedStatus] || "Attention";
  if (!observedStatus && allDevicesConnected && allIntegrationsHealthy) {
    posture = payload.safety.audible_actions_gated ? "Guarded" : "Nominal";
  }
  text("#system-posture", posture);
  document
    .querySelector("#hero-orbit")
    .classList.toggle("warning", posture !== "Nominal");
  text(
    "#hero-subtitle",
    `${summary.connected_device_count} endpoints connected · ` +
      `${summary.healthy_integration_count} integrations healthy · ` +
      `refreshed ${formatRelative(payload.generated_at)}`,
  );
  text("#last-updated", `Updated ${formatTime(payload.generated_at)}`);
};

const renderObservability = (payload) => {
  const observability = payload.observability || {
    status: "unknown",
    alerts: [],
  };
  const statusElement = document.querySelector("#observability-status");
  const kind = {
    healthy: "good",
    guarded: "warning",
    degraded: "warning",
    critical: "bad",
  }[observability.status] || "neutral";
  statusElement.className = `status-pill status-${kind}`;
  clear(statusElement);
  statusElement.append(node("span", "status-dot"));
  statusElement.append(
    document.createTextNode(titleCase(observability.status)),
  );

  const list = document.querySelector("#alert-list");
  clear(list);
  text("#alert-total", observability.alerts.length);
  if (!observability.alerts.length) {
    list.append(node("p", "timeline-empty", "No active alerts."));
    return;
  }
  observability.alerts.forEach((alert) => {
    const alertKind = {
      critical: "bad",
      warning: "warning",
      info: "",
    }[alert.severity] || "";
    list.append(
      timelineRow(
        alertKind,
        alert.title,
        alert.detail,
        observability.generated_at,
      ),
    );
  });
};

const renderRooms = (payload) => {
  const list = document.querySelector("#room-list");
  clear(list);

  Object.values(payload.rooms).forEach((roomState) => {
    const room = roomState.room;
    const devices = roomState.devices || [];
    const players = room.players || [];
    const connected = devices.filter((device) => device.connected).length;
    const armed = devices.some(
      (device) =>
        device.connected &&
        device.health?.payload?.audio_activation?.allowed === true,
    );

    const card = node("article", "room-card");
    const head = node("div", "room-head");
    const roomTitle = node("div", "room-title");
    roomTitle.append(node("span", "room-monogram", room.name.slice(0, 1)));
    const titleCopy = node("div");
    titleCopy.append(node("strong", "", room.name));
    titleCopy.append(
      node(
        "small",
        "",
        `${connected}/${devices.length} devices connected · ${players.length} players`,
      ),
    );
    roomTitle.append(titleCopy);
    head.append(roomTitle);
    head.append(badge(armed ? "Audio armed" : "Audio locked", armed ? "good" : "warning"));
    card.append(head);

    const body = node("div", "room-body");

    const endpointColumn = node("div", "room-column");
    endpointColumn.append(node("span", "column-label", "Endpoints"));
    if (!devices.length) {
      endpointColumn.append(node("p", "action-note", "No enrolled endpoint."));
    }
    devices.forEach((device) => {
      const line = node("div", "device-line");
      const meta = node("div", "device-meta");
      meta.append(node("strong", "", device.name));
      const uptime = device.health?.payload?.uptime_seconds;
      meta.append(
        node(
          "small",
          "",
          `${device.id} · ${uptime == null ? "no telemetry" : `${formatDuration(uptime)} up`}`,
        ),
      );
      line.append(meta);
      line.append(
        badge(device.connected ? "Connected" : "Offline", device.connected ? "good" : "bad"),
      );
      endpointColumn.append(line);
    });
    const visiblePlayers = players.filter((player) =>
      ["music", "video"].includes(player.kind),
    );
    if (visiblePlayers.length) {
      endpointColumn.append(
        node("span", "column-label column-label-secondary", "Media players"),
      );
    }
    visiblePlayers.forEach((player) => {
      const playerState = payload.media?.players?.[player.id];
      const effective = playerState?.effective || {};
      const line = node("div", "player-line");
      const meta = node("div", "player-meta");
      meta.append(node("strong", "", player.name));
      const volume =
        effective.volume_percent == null
          ? ""
          : ` · ${effective.volume_percent}%`;
      const access = player.control_enabled ? "control ready" : "read only";
      meta.append(
        node(
          "small",
          "",
          `${titleCase(player.protocol)}${volume} · ${access}`,
        ),
      );
      line.append(meta);
      const stateLabel =
        playerState?.status === "ok"
          ? titleCase(effective.playback_state || "available")
          : "Unresolved";
      const stateKind =
        playerState?.status === "ok" && effective.available
          ? effective.powered
            ? "good"
            : "neutral"
          : "bad";
      line.append(badge(stateLabel, stateKind));
      endpointColumn.append(line);
    });
    body.append(endpointColumn);

    const sourcesColumn = node("div", "room-column");
    sourcesColumn.append(node("span", "column-label", "Source state"));
    const sourceGrid = node("div", "source-grid");
    const sources = roomState.sources || {};
    ["critical", "assistant", "bluetooth", "airplay", "music"].forEach((source) => {
      const chip = node("span", "source-chip", titleCase(source));
      if (sources[source]?.active) {
        chip.classList.add("active");
      }
      sourceGrid.append(chip);
    });
    sourcesColumn.append(sourceGrid);
    const foreground = roomState.focus?.foreground;
    sourcesColumn.append(
      node(
        "p",
        "action-note",
        foreground ? `${titleCase(foreground)} has focus.` : "No active foreground source.",
      ),
    );
    body.append(sourcesColumn);

    const actionsColumn = node("div", "room-column");
    actionsColumn.append(node("span", "column-label", "Safe controls"));
    const actions = node("div", "room-actions");
    const cancelButton = node("button", "button button-quiet button-small", "Clear transient state");
    cancelButton.type = "button";
    cancelButton.disabled = devices.length === 0;
    cancelButton.addEventListener("click", () => sendCancel(room.id, cancelButton));
    actions.append(cancelButton);
    actions.append(
      node(
        "p",
        "action-note",
        devices.length === 0
          ? "No room endpoint is enrolled. Provider state remains read only."
          : armed
            ? "Audible controls remain intentionally absent from this operations view."
            : "Playback and volume stay locked until supervised activation.",
      ),
    );
    actionsColumn.append(actions);
    body.append(actionsColumn);

    card.append(body);
    list.append(card);
  });
};

const renderIntegrations = (payload) => {
  const list = document.querySelector("#integration-list");
  clear(list);
  Object.entries(payload.integrations).forEach(([id, integration]) => {
    const line = node("div", "integration-line");
    const name = node("div", "integration-name");
    name.append(node("strong", "", titleCase(id)));
    const detail =
      integration.status === "ok"
        ? `${integration.latency_ms ?? "—"} ms response`
        : titleCase(integration.status);
    name.append(node("small", "", detail));
    line.append(name);
    line.append(badge(titleCase(integration.status), healthKind(integration.status)));
    list.append(line);
  });
};

const renderSafety = (payload) => {
  const gated = payload.safety.audible_actions_gated;
  const badgeElement = document.querySelector("#safety-badge");
  badgeElement.className = `status-pill status-${gated ? "warning" : "good"}`;
  clear(badgeElement);
  badgeElement.append(node("span", "status-dot"));
  badgeElement.append(document.createTextNode(gated ? "Locked" : "Armed"));
  text(
    "#safety-copy",
    gated
      ? `Remote audio is blocked in ${payload.safety.unarmed_rooms
          .map(titleCase)
          .join(", ")}. Telemetry and non-audible cancellation remain available.`
      : "Every registered room has a connected endpoint with a matching supervised activation receipt.",
  );
  text("#audible-action-state", gated ? "Blocked" : "Available");
  text("#armed-room-count", payload.safety.armed_rooms.length);
  text("#pending-command-count", payload.summary.pending_command_count);
};

const timelineRow = (kind, title, detail, timestamp) => {
  const row = node("div", "timeline-row");
  row.append(node("span", `timeline-mark ${kind}`));
  const copy = node("div", "timeline-copy");
  copy.append(node("strong", "", title));
  copy.append(node("small", "", detail));
  row.append(copy);
  row.append(node("span", "timeline-time", formatRelative(timestamp)));
  return row;
};

const renderCommands = (payload) => {
  const list = document.querySelector("#command-list");
  clear(list);
  text("#command-total", payload.commands.length);
  if (!payload.commands.length) {
    list.append(node("p", "timeline-empty", "No commands have been issued."));
    return;
  }
  payload.commands.slice(0, 8).forEach((command) => {
    const action = titleCase(command.payload?.action || "command");
    list.append(
      timelineRow(
        healthKind(command.status),
        `${action} · ${titleCase(command.status)}`,
        `${command.room_id} / ${command.device_id} · command ${command.id}`,
        command.completed_at || command.delivered_at || command.created_at,
      ),
    );
  });
};

const eventDetail = (event) => {
  if (event.type === "source_state") {
    return `${titleCase(event.payload?.source)} ${event.payload?.active ? "active" : "inactive"}`;
  }
  if (event.type === "health") {
    const ready = event.payload?.ready;
    return ready === true ? "Endpoint reported ready" : "Endpoint health update";
  }
  return `${event.room_id} / ${event.device_id}`;
};

const renderEvents = (payload) => {
  const list = document.querySelector("#event-list");
  clear(list);
  text("#event-total", payload.events.length);
  if (!payload.events.length) {
    list.append(node("p", "timeline-empty", "No telemetry has been recorded."));
    return;
  }
  payload.events.slice(0, 8).forEach((event) => {
    list.append(
      timelineRow(
        event.type === "health" ? "good" : "",
        titleCase(event.type),
        eventDetail(event),
        event.created_at,
      ),
    );
  });
};

const renderDeployment = (payload) => {
  text("#deployment-release", payload.deployment.release);
  text("#deployment-version", payload.deployment.version);
  text("#deployment-uptime", formatDuration(payload.deployment.uptime_seconds));
  text("#deployment-registry", payload.registry_revision);
};

const render = (payload) => {
  renderSummary(payload);
  renderRooms(payload);
  renderIntegrations(payload);
  renderSafety(payload);
  renderObservability(payload);
  renderCommands(payload);
  renderEvents(payload);
  renderDeployment(payload);
};

const loadDashboard = async ({ announce = false } = {}) => {
  if (!state.token || state.loading) {
    return;
  }
  state.loading = true;
  elements.refreshButton.disabled = true;
  setConnection("neutral", "Refreshing");
  try {
    const payload = await api("/v1/operations");
    render(payload);
    elements.accessPanel.hidden = true;
    elements.dashboard.hidden = false;
    elements.refreshButton.hidden = false;
    elements.disconnectButton.hidden = false;
    setConnection("good", "Live");
    if (announce) {
      showToast("Pilot Core state refreshed.");
    }
  } catch (error) {
    if (error.message === "unauthorized") {
      disconnect("The administrator token was not accepted.");
    } else {
      setConnection("bad", "Unavailable");
      showToast(error.name === "AbortError" ? "Pilot Core timed out." : error.message);
    }
  } finally {
    state.loading = false;
    elements.refreshButton.disabled = false;
  }
};

const sendCancel = async (roomId, button) => {
  button.disabled = true;
  try {
    const response = await api(`/v1/rooms/${encodeURIComponent(roomId)}/control`, {
      method: "POST",
      body: JSON.stringify({ action: "cancel", expires_in_seconds: 30 }),
    });
    const status = response.command?.status || "queued";
    showToast(`Transient state clear ${status}.`);
    window.setTimeout(() => loadDashboard(), 700);
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
};

const disconnect = (message = "") => {
  state.token = "";
  sessionStorage.removeItem("pilot-core-admin-token");
  elements.tokenInput.value = "";
  elements.accessPanel.hidden = false;
  elements.dashboard.hidden = true;
  elements.refreshButton.hidden = true;
  elements.disconnectButton.hidden = true;
  setConnection("neutral", "Awaiting access");
  window.clearInterval(state.refreshTimer);
  state.refreshTimer = null;
  if (message) {
    elements.accessError.textContent = message;
    elements.accessError.hidden = false;
  }
};

elements.accessForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.accessError.hidden = true;
  state.token = elements.tokenInput.value.trim();
  if (!state.token) {
    return;
  }
  sessionStorage.setItem("pilot-core-admin-token", state.token);
  await loadDashboard();
  if (state.token && !state.refreshTimer) {
    state.refreshTimer = window.setInterval(loadDashboard, 15000);
  }
});

elements.refreshButton.addEventListener("click", () =>
  loadDashboard({ announce: true }),
);
elements.disconnectButton.addEventListener("click", () => disconnect());

if (state.token) {
  loadDashboard();
  state.refreshTimer = window.setInterval(loadDashboard, 15000);
}
