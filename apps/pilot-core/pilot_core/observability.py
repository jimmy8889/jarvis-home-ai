from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def evaluate_observability(
    snapshot: dict[str, Any],
    *,
    device_stale_after_seconds: int = 90,
) -> dict[str, Any]:
    """Turn the operations snapshot into stable checks and actionable alerts."""

    generated_at = _timestamp(snapshot.get("generated_at")) or datetime.now(UTC)
    alerts: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    stale_devices = 0
    offline_devices = 0
    unresolved_players = 0
    unhealthy_integrations = 0

    for integration_id, integration in sorted(snapshot.get("integrations", {}).items()):
        configured = integration.get("configured") is True
        status = str(integration.get("status", "unknown"))
        if not configured:
            checks.append(
                {
                    "kind": "integration",
                    "id": integration_id,
                    "status": "not_configured",
                }
            )
            continue
        healthy = status == "ok"
        checks.append(
            {
                "kind": "integration",
                "id": integration_id,
                "status": "ok" if healthy else "error",
            }
        )
        if not healthy:
            unhealthy_integrations += 1
            alerts.append(
                {
                    "severity": "warning",
                    "code": "INTEGRATION_UNHEALTHY",
                    "title": f"{integration_id.replace('_', ' ').title()} is unhealthy",
                    "detail": f"Configured provider reported {status}.",
                    "integration_id": integration_id,
                }
            )

    for room_id, room_state in sorted(snapshot.get("rooms", {}).items()):
        devices = room_state.get("devices") or []
        if not devices:
            checks.append(
                {
                    "kind": "room_endpoint",
                    "id": room_id,
                    "room_id": room_id,
                    "status": "not_enrolled",
                }
            )
        for device in devices:
            device_id = str(device.get("id", "unknown"))
            connected = device.get("connected") is True
            health = device.get("health") or {}
            health_at = _timestamp(health.get("updated_at"))
            age_seconds = (
                max(0, int((generated_at - health_at).total_seconds()))
                if health_at
                else None
            )
            stale = age_seconds is None or age_seconds > device_stale_after_seconds
            ready = (health.get("payload") or {}).get("ready") is True
            status = "ok"
            if not connected:
                status = "offline"
                offline_devices += 1
            elif stale:
                status = "stale"
                stale_devices += 1
            elif not ready:
                status = "not_ready"
            checks.append(
                {
                    "kind": "device",
                    "id": device_id,
                    "room_id": room_id,
                    "status": status,
                    "telemetry_age_seconds": age_seconds,
                }
            )
            if status != "ok":
                alerts.append(
                    {
                        "severity": "warning",
                        "code": f"DEVICE_{status.upper()}",
                        "title": f"{device.get('name') or device_id} is {status.replace('_', ' ')}",
                        "detail": (
                            f"Room endpoint {device_id} in {room_id} needs attention."
                        ),
                        "room_id": room_id,
                        "device_id": device_id,
                    }
                )

    media_players = (snapshot.get("media") or {}).get("players") or {}
    for player_id, player_state in sorted(media_players.items()):
        player = player_state.get("player") or {}
        if player.get("kind") not in {"music", "video"}:
            continue
        status = str(player_state.get("status", "unresolved"))
        resolved = status == "ok"
        checks.append(
            {
                "kind": "media_player",
                "id": player_id,
                "room_id": player.get("room_id"),
                "status": "ok" if resolved else "unresolved",
                "control_enabled": player.get("control_enabled") is True,
            }
        )
        if not resolved:
            unresolved_players += 1
            alerts.append(
                {
                    "severity": "warning",
                    "code": "PLAYER_UNRESOLVED",
                    "title": f"{player.get('name') or player_id} is unresolved",
                    "detail": (
                        "Neither Music Assistant nor Home Assistant returned "
                        "usable state for this player."
                    ),
                    "room_id": player.get("room_id"),
                    "player_id": player_id,
                }
            )

    safety = snapshot.get("safety") or {}
    unarmed_rooms = list(safety.get("unarmed_rooms") or [])
    if safety.get("audible_actions_gated") is True:
        alerts.append(
            {
                "severity": "info",
                "code": "AUDIO_GATED",
                "title": "Audible actions are safely locked",
                "detail": (
                    "Supervised activation is still required in "
                    + ", ".join(unarmed_rooms)
                    + "."
                ),
                "room_ids": unarmed_rooms,
            }
        )

    warning_count = sum(alert["severity"] == "warning" for alert in alerts)
    critical_count = sum(alert["severity"] == "critical" for alert in alerts)
    status = (
        "critical"
        if critical_count
        else "degraded"
        if warning_count
        else "guarded"
        if safety.get("audible_actions_gated") is True
        else "healthy"
    )
    return {
        "generated_at": generated_at.isoformat(),
        "status": status,
        "summary": {
            "critical_alert_count": critical_count,
            "warning_alert_count": warning_count,
            "info_alert_count": sum(alert["severity"] == "info" for alert in alerts),
            "stale_device_count": stale_devices,
            "offline_device_count": offline_devices,
            "unresolved_player_count": unresolved_players,
            "unhealthy_integration_count": unhealthy_integrations,
        },
        "alerts": alerts,
        "checks": checks,
    }


def prometheus_metrics(
    snapshot: dict[str, Any],
    observability: dict[str, Any],
) -> str:
    """Render a small stable Prometheus exposition without third-party state."""

    lines = [
        "# HELP pilot_core_up Whether Pilot Core generated this snapshot.",
        "# TYPE pilot_core_up gauge",
        "pilot_core_up 1",
    ]
    summary = snapshot.get("summary") or {}
    for key, metric in (
        ("room_count", "pilot_core_rooms"),
        ("device_count", "pilot_core_devices"),
        ("connected_device_count", "pilot_core_devices_connected"),
        ("pending_command_count", "pilot_core_commands_pending"),
    ):
        lines.extend(
            [
                f"# TYPE {metric} gauge",
                f"{metric} {int(summary.get(key, 0))}",
            ]
        )

    for integration_id, integration in sorted(snapshot.get("integrations", {}).items()):
        if integration.get("configured") is not True:
            continue
        lines.append(
            "pilot_core_integration_healthy"
            f'{{integration_id="{_label(integration_id)}"}} '
            f"{1 if integration.get('status') == 'ok' else 0}"
        )

    for room_id, room_state in sorted(snapshot.get("rooms", {}).items()):
        armed = any(
            device.get("connected") is True
            and (
                ((device.get("health") or {}).get("payload") or {})
                .get("audio_activation", {})
                .get("allowed")
                is True
            )
            for device in room_state.get("devices") or []
        )
        lines.append(
            f'pilot_core_room_audio_armed{{room_id="{_label(room_id)}"}} '
            f"{1 if armed else 0}"
        )
        for device in room_state.get("devices") or []:
            lines.append(
                "pilot_core_device_connected"
                f'{{room_id="{_label(room_id)}",'
                f'device_id="{_label(str(device.get("id", "")))}"}} '
                f"{1 if device.get('connected') is True else 0}"
            )

    for player_id, player_state in sorted(
        ((snapshot.get("media") or {}).get("players") or {}).items()
    ):
        player = player_state.get("player") or {}
        if player.get("kind") not in {"music", "video"}:
            continue
        lines.append(
            "pilot_core_player_resolved"
            f'{{room_id="{_label(str(player.get("room_id", "")))}",'
            f'player_id="{_label(player_id)}"}} '
            f"{1 if player_state.get('status') == 'ok' else 0}"
        )

    lines.append(
        "pilot_core_observability_status"
        f'{{status="{_label(str(observability.get("status", "unknown")))}"}} 1'
    )
    return "\n".join(lines) + "\n"


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
