from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import re
import time
from typing import Any
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import WebSocketException

from .config import IntegrationSettings
from .secret_values import read_secret


class IntegrationUnavailable(RuntimeError):
    pass


class IntegrationRequestFailed(RuntimeError):
    pass


_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_DENON_SOURCE_COMMANDS = {
    "aux 1": "SIAUX1",
    "aux 2": "SIAUX2",
    "blu-ray": "SIBD",
    "bluetooth": "SIBT",
    "cbl/sat": "SISAT/CBL",
    "cd": "SICD",
    "dvd": "SIDVD",
    "game": "SIGAME",
    "heos music": "SIHEOS",
    "media player": "SIMPLAY",
    "phono": "SIPHONO",
    "tv audio": "SITV",
    "tuner": "SITUNER",
}


class Integrations:
    def __init__(
        self,
        settings: IntegrationSettings,
        transport: httpx.AsyncBaseTransport | None = None,
        websocket_factory: Any | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.websocket_factory = websocket_factory or websocket_connect

    async def music_assistant(self, command: str, args: dict[str, Any]) -> Any:
        if not self.settings.music_assistant_url:
            raise IntegrationUnavailable("Music Assistant URL is not configured")
        token = read_secret(self.settings.music_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Music Assistant token is not configured")
        payload = {"message_id": str(uuid4()), "command": command, "args": args}
        try:
            async with httpx.AsyncClient(
                timeout=10, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(
                    f"{self.settings.music_assistant_url}/api",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(
                f"Music Assistant request failed: {error}"
            ) from error

    async def home_assistant_conversation(
        self,
        text: str,
        language: str = "en",
        conversation_id: str | None = None,
        agent_id: str | None = None,
        device_id: str | None = None,
    ) -> Any:
        if not self.settings.home_assistant_url:
            raise IntegrationUnavailable("Home Assistant URL is not configured")
        token = read_secret(self.settings.home_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        payload: dict[str, Any] = {"text": text, "language": language}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if agent_id:
            payload["agent_id"] = agent_id
        if device_id:
            payload["device_id"] = device_id
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(
                    f"{self.settings.home_assistant_url}/api/conversation/process",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(
                f"Home Assistant request failed: {error}"
            ) from error

    async def home_assistant_state(self, entity_id: str) -> dict[str, Any]:
        if not _ENTITY_ID.fullmatch(entity_id):
            raise IntegrationRequestFailed("Home Assistant entity ID is invalid")
        if not self.settings.home_assistant_url:
            raise IntegrationUnavailable("Home Assistant URL is not configured")
        token = read_secret(self.settings.home_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        try:
            async with httpx.AsyncClient(
                timeout=10, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.get(
                    f"{self.settings.home_assistant_url}/api/states/{entity_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("state response is not an object")
                return payload
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(
                f"Home Assistant state request failed: {error}"
            ) from error

    async def home_assistant_states(self) -> list[dict[str, Any]]:
        """Fetch one read-only state snapshot for the local entity catalogue."""

        if not self.settings.home_assistant_url:
            raise IntegrationUnavailable("Home Assistant URL is not configured")
        token = read_secret(self.settings.home_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.get(
                    f"{self.settings.home_assistant_url}/api/states",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                if len(response.content) > 64_000_000:
                    raise ValueError("state snapshot is too large")
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("state snapshot is not an array")
                if len(payload) > self.settings.home_catalog_max_entities:
                    raise ValueError("state snapshot exceeds the configured entity limit")
                if not all(isinstance(item, dict) for item in payload):
                    raise ValueError("state snapshot contains an invalid entry")
                return payload
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(
                f"Home Assistant state snapshot failed: {error}"
            ) from error

    async def home_assistant_registry_snapshot(self) -> dict[str, Any]:
        """Read HA registries over its authenticated, local WebSocket API.

        Registry commands are versioned by Home Assistant. Unsupported commands
        are reported per section instead of failing the state catalogue.
        """

        if not self.settings.home_assistant_url:
            raise IntegrationUnavailable("Home Assistant URL is not configured")
        token = read_secret(self.settings.home_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        base = httpx.URL(self.settings.home_assistant_url)
        if base.scheme not in {"http", "https"} or not base.host:
            raise IntegrationRequestFailed("Home Assistant URL is invalid")
        websocket_url = base.copy_with(
            scheme="wss" if base.scheme == "https" else "ws",
            path="/api/websocket",
            query=None,
            fragment=None,
        )
        commands = (
            ("areas", "config/area_registry/list"),
            ("devices", "config/device_registry/list"),
            ("entities", "config/entity_registry/list"),
            ("floors", "config/floor_registry/list"),
        )
        try:
            async with self.websocket_factory(
                str(websocket_url),
                open_timeout=10,
                close_timeout=5,
                max_size=16_000_000,
            ) as socket:
                required = await self._websocket_json(socket)
                if required.get("type") != "auth_required":
                    raise ValueError("Home Assistant did not request authentication")
                await socket.send(
                    json.dumps(
                        {"type": "auth", "access_token": token},
                        separators=(",", ":"),
                    )
                )
                authenticated = await self._websocket_json(socket)
                if authenticated.get("type") != "auth_ok":
                    raise ValueError("Home Assistant WebSocket authentication failed")
                result: dict[str, Any] = {
                    "areas": None,
                    "devices": None,
                    "entities": None,
                    "floors": None,
                    "supported": {},
                }
                for message_id, (name, command) in enumerate(commands, start=1):
                    await socket.send(
                        json.dumps(
                            {"id": message_id, "type": command},
                            separators=(",", ":"),
                        )
                    )
                    response = await self._websocket_json(socket)
                    if (
                        response.get("type") != "result"
                        or response.get("id") != message_id
                    ):
                        raise ValueError("Home Assistant registry response is invalid")
                    success = response.get("success") is True
                    result["supported"][name] = success
                    payload = response.get("result")
                    if success:
                        if not isinstance(payload, list):
                            raise ValueError(
                                f"Home Assistant {name} registry is not an array"
                            )
                        if len(payload) > self.settings.home_catalog_max_entities:
                            raise ValueError(
                                f"Home Assistant {name} registry exceeds the limit"
                            )
                        if not all(isinstance(item, dict) for item in payload):
                            raise ValueError(
                                f"Home Assistant {name} registry is invalid"
                            )
                        result[name] = payload
                return result
        except (OSError, TimeoutError, ValueError, WebSocketException) as error:
            raise IntegrationRequestFailed(
                f"Home Assistant registry snapshot failed: {error}"
            ) from error

    @staticmethod
    async def _websocket_json(socket: Any) -> dict[str, Any]:
        message = await asyncio.wait_for(socket.recv(), timeout=10)
        if isinstance(message, bytes):
            if len(message) > 16_000_000:
                raise ValueError("Home Assistant WebSocket message is too large")
            message = message.decode("utf-8")
        if not isinstance(message, str) or len(message) > 16_000_000:
            raise ValueError("Home Assistant WebSocket message is invalid")
        payload = json.loads(message)
        if not isinstance(payload, dict):
            raise ValueError("Home Assistant WebSocket payload is not an object")
        return payload

    async def home_assistant_media_player_command(
        self,
        entity_id: str,
        action: str,
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        if not _ENTITY_ID.fullmatch(entity_id) or not entity_id.startswith(
            "media_player."
        ):
            raise IntegrationRequestFailed("Home Assistant media player is invalid")
        services = {
            "power_on": "turn_on",
            "power_off": "turn_off",
            "select_source": "select_source",
        }
        service = services.get(action)
        if service is None:
            raise IntegrationRequestFailed("Home Assistant media action is invalid")
        if action == "select_source" and not source:
            raise IntegrationRequestFailed("source is required")
        if not self.settings.home_assistant_url:
            raise IntegrationUnavailable("Home Assistant URL is not configured")
        token = read_secret(self.settings.home_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        payload: dict[str, Any] = {"entity_id": entity_id}
        if source:
            payload["source"] = source
        try:
            async with httpx.AsyncClient(
                timeout=15, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(
                    (
                        f"{self.settings.home_assistant_url}"
                        f"/api/services/media_player/{service}"
                    ),
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                if isinstance(result, list):
                    return {"changed_states": result}
                if isinstance(result, dict):
                    return result
                raise ValueError("service response is not an object or array")
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(
                f"Home Assistant media command failed: {error}"
            ) from error

    async def home_assistant_typed_action(
        self,
        domain: str,
        service: str,
        entity_id: str,
        service_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one entity-scoped service from Pilot's fixed allowlist."""

        allowed = {
            "light": {"turn_on", "turn_off", "toggle"},
            "switch": {"turn_on", "turn_off", "toggle"},
            "input_boolean": {"turn_on", "turn_off", "toggle"},
            "input_select": {"select_option"},
            "fan": {"turn_on", "turn_off", "toggle", "set_percentage"},
            "climate": {"turn_on", "turn_off", "set_temperature", "set_hvac_mode"},
            "cover": {"open_cover", "close_cover", "stop_cover", "set_cover_position"},
            "scene": {"turn_on"},
            "script": {"turn_on"},
            "lock": {"lock", "unlock"},
            "alarm_control_panel": {
                "alarm_arm_home",
                "alarm_arm_away",
                "alarm_disarm",
            },
        }
        if service not in allowed.get(domain, set()):
            raise IntegrationRequestFailed("Home Assistant typed action is not allowed")
        if not _ENTITY_ID.fullmatch(entity_id) or not entity_id.startswith(f"{domain}."):
            raise IntegrationRequestFailed("Home Assistant action entity is invalid")
        permitted_keys = {
            "brightness_pct",
            "color_temp_kelvin",
            "percentage",
            "temperature",
            "hvac_mode",
            "position",
            "option",
        }
        if set(service_data) - permitted_keys:
            raise IntegrationRequestFailed("Home Assistant action data is invalid")
        if not self.settings.home_assistant_url:
            raise IntegrationUnavailable("Home Assistant URL is not configured")
        token = read_secret(self.settings.home_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        payload = {"entity_id": entity_id, **service_data}
        try:
            async with httpx.AsyncClient(
                timeout=15, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(
                    f"{self.settings.home_assistant_url}/api/services/{domain}/{service}",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                if isinstance(result, list):
                    return {"changed_state_count": min(len(result), 10_000)}
                if isinstance(result, dict):
                    return {"accepted": True}
                raise ValueError("service response is not an object or array")
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(
                f"Home Assistant typed action failed: {error}"
            ) from error

    async def denon_avr_command(
        self,
        control_endpoint: str,
        action: str,
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        endpoint = httpx.URL(control_endpoint)
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.host
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or endpoint.path not in {"", "/"}
        ):
            raise IntegrationRequestFailed("Denon control endpoint is invalid")
        commands = {
            "power_on": "PWON",
            "power_off": "PWSTANDBY",
        }
        command = commands.get(action)
        if action == "select_source":
            if not source:
                raise IntegrationRequestFailed("source is required")
            command = _DENON_SOURCE_COMMANDS.get(source.strip().casefold())
            if command is None:
                raise IntegrationRequestFailed("Denon source is not allowed")
        if command is None:
            raise IntegrationRequestFailed("Denon media action is invalid")
        url = endpoint.copy_with(
            path="/goform/formiPhoneAppDirect.xml",
            query=command.encode(),
        )
        try:
            async with httpx.AsyncClient(
                timeout=8, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise IntegrationRequestFailed(
                f"Denon AVR command failed: {error}"
            ) from error
        return {
            "accepted": True,
            "action": action,
            "source": source if action == "select_source" else None,
        }

    async def home_assistant_weather(self) -> dict[str, Any]:
        entity_id = self.settings.weather_entity_id
        if not entity_id:
            raise IntegrationUnavailable(
                "Home Assistant weather entity is not configured"
            )
        current = await self.home_assistant_state(entity_id)
        token = read_secret(self.settings.home_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        try:
            async with httpx.AsyncClient(
                timeout=15, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(
                    (
                        f"{self.settings.home_assistant_url}"
                        "/api/services/weather/get_forecasts?return_response"
                    ),
                    headers={"Authorization": f"Bearer {token}"},
                    json={"entity_id": entity_id, "type": "daily"},
                )
                response.raise_for_status()
                forecast_response = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(
                f"Home Assistant weather forecast request failed: {error}"
            ) from error
        return {
            "entity_id": entity_id,
            "current": current,
            "forecast_response": forecast_response,
        }

    async def home_assistant_temperature_history(
        self,
        entity_id: str,
    ) -> dict[str, Any]:
        if not _ENTITY_ID.fullmatch(entity_id) or not entity_id.startswith("sensor."):
            raise IntegrationRequestFailed(
                "Home Assistant temperature entity ID is invalid"
            )
        current = await self.home_assistant_state(entity_id)
        token = read_secret(self.settings.home_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        started_at = datetime.now(UTC) - timedelta(
            hours=self.settings.temperature_history_hours
        )
        period = started_at.isoformat().replace("+00:00", "Z")
        try:
            async with httpx.AsyncClient(
                timeout=20, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.get(
                    (f"{self.settings.home_assistant_url}/api/history/period/{period}"),
                    headers={"Authorization": f"Bearer {token}"},
                    params={
                        "filter_entity_id": entity_id,
                        "minimal_response": "",
                        "no_attributes": "",
                    },
                )
                response.raise_for_status()
                history = response.json()
                if not isinstance(history, list):
                    raise ValueError("history response is not an array")
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(
                f"Home Assistant temperature history request failed: {error}"
            ) from error
        return {
            "entity_id": entity_id,
            "period_hours": self.settings.temperature_history_hours,
            "current": current,
            "history": history,
        }

    async def home_assistant_energy(self) -> dict[str, dict[str, Any]]:
        """Read the configured energy sensors without exposing unrelated HA state."""

        entity_ids = {
            "solar": self.settings.energy_solar_power_entity_id,
            "grid": self.settings.energy_grid_power_entity_id,
            "battery": self.settings.energy_battery_power_entity_id,
            "battery_soc": self.settings.energy_battery_soc_entity_id,
            "home_load": self.settings.energy_home_load_entity_id,
        }
        if not all(entity_ids.values()):
            raise IntegrationUnavailable(
                "Home Assistant energy entities are not fully configured"
            )
        results = await asyncio.gather(
            *(self.home_assistant_state(entity_id) for entity_id in entity_ids.values()),
            return_exceptions=True,
        )
        states: dict[str, dict[str, Any]] = {}
        failed: list[str] = []
        for (name, _entity_id), result in zip(
            entity_ids.items(), results, strict=True
        ):
            if isinstance(result, dict):
                states[name] = result
            else:
                failed.append(name)
        if failed:
            raise IntegrationRequestFailed(
                "Home Assistant energy state unavailable: " + ", ".join(failed)
            )
        return states

    async def home_assistant_selected_states(
        self, entity_ids: list[str] | tuple[str, ...]
    ) -> dict[str, dict[str, Any]]:
        """Read an explicit, bounded set of Home Assistant entities."""

        unique = tuple(dict.fromkeys(entity_ids))
        if not unique or len(unique) > 64:
            raise IntegrationRequestFailed(
                "Home Assistant state request must contain between 1 and 64 entities"
            )
        if any(not _ENTITY_ID.fullmatch(entity_id) for entity_id in unique):
            raise IntegrationRequestFailed("Home Assistant entity ID is invalid")
        results = await asyncio.gather(
            *(self.home_assistant_state(entity_id) for entity_id in unique),
            return_exceptions=True,
        )
        return {
            entity_id: result
            for entity_id, result in zip(unique, results, strict=True)
            if isinstance(result, dict)
        }

    async def home_assistant_history(
        self,
        entity_ids: list[str] | tuple[str, ...],
        *,
        hours: int | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Read history for an explicit sensor set in one bounded request."""

        unique = tuple(dict.fromkeys(entity_ids))
        if not unique or len(unique) > 8:
            raise IntegrationRequestFailed(
                "Home Assistant history request must contain between 1 and 8 entities"
            )
        if started_at is None:
            if hours is None or not 1 <= hours <= 168:
                raise IntegrationRequestFailed("Home Assistant history period is invalid")
            started_at = datetime.now(UTC) - timedelta(hours=hours)
        elif hours is not None:
            raise IntegrationRequestFailed(
                "Home Assistant history period must use hours or explicit bounds"
            )
        if started_at.tzinfo is None:
            raise IntegrationRequestFailed("Home Assistant history start must include a timezone")
        if ended_at is not None:
            if ended_at.tzinfo is None or ended_at <= started_at:
                raise IntegrationRequestFailed("Home Assistant history end is invalid")
            if ended_at - started_at > timedelta(hours=168):
                raise IntegrationRequestFailed("Home Assistant history period is invalid")
        if any(
            not _ENTITY_ID.fullmatch(entity_id)
            or not entity_id.startswith("sensor.")
            for entity_id in unique
        ):
            raise IntegrationRequestFailed("Home Assistant history entity ID is invalid")
        token = read_secret(self.settings.home_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        period = started_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        params = {
            "filter_entity_id": ",".join(unique),
            "minimal_response": "",
            "no_attributes": "",
        }
        if ended_at is not None:
            params["end_time"] = (
                ended_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            )
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.get(
                    f"{self.settings.home_assistant_url}/api/history/period/{period}",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
                response.raise_for_status()
                raw = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(
                f"Home Assistant energy history request failed: {error}"
            ) from error
        if not isinstance(raw, list):
            raise IntegrationRequestFailed(
                "Home Assistant energy history response is invalid"
            )
        history: dict[str, list[dict[str, Any]]] = {entity_id: [] for entity_id in unique}
        for series in raw:
            if not isinstance(series, list) or not series:
                continue
            series_entity_id: str | None = None
            series_states: list[dict[str, Any]] = []
            malformed = False
            for state in series:
                if not isinstance(state, dict):
                    malformed = True
                    break
                if "entity_id" in state:
                    entity_id = state["entity_id"]
                    if (
                        not isinstance(entity_id, str)
                        or entity_id not in history
                        or (
                            series_entity_id is not None
                            and entity_id != series_entity_id
                        )
                    ):
                        malformed = True
                        break
                    series_entity_id = entity_id
                if series_entity_id is None:
                    malformed = True
                    break
                series_states.append(state)
            if not malformed and series_entity_id is not None:
                history[series_entity_id].extend(series_states)
        return history

    async def diagnostics(self) -> dict[str, Any]:
        """Run read-only provider checks without returning URLs or credentials."""

        home_assistant, music_assistant = await asyncio.gather(
            self._home_assistant_diagnostic(),
            self._music_assistant_diagnostic(),
        )
        return {
            "home_assistant": home_assistant,
            "music_assistant": music_assistant,
        }

    async def _home_assistant_diagnostic(self) -> dict[str, Any]:
        url = self.settings.home_assistant_url
        token = read_secret(self.settings.home_assistant_token_env)
        return await self._diagnostic_request(
            "home_assistant",
            bool(url),
            bool(token),
            "GET",
            f"{url}/api/" if url else "",
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )

    async def _music_assistant_diagnostic(self) -> dict[str, Any]:
        url = self.settings.music_assistant_url
        token = read_secret(self.settings.music_assistant_token_env)
        return await self._diagnostic_request(
            "music_assistant",
            bool(url),
            bool(token),
            "POST",
            f"{url}/api" if url else "",
            headers={"Authorization": f"Bearer {token}"} if token else {},
            json={
                "message_id": str(uuid4()),
                "command": "players/all",
                "args": {},
            },
        )

    async def _diagnostic_request(
        self,
        provider: str,
        configured: bool,
        credential_configured: bool,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider": provider,
            "configured": configured,
            "credential_configured": credential_configured,
            "reachable": False,
            "latency_ms": None,
            "status": "not_configured",
        }
        if not configured or not credential_configured:
            if configured:
                result["status"] = "credential_missing"
            return result
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=10, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
            result["reachable"] = True
            result["status"] = "ok"
        except httpx.HTTPStatusError as error:
            result["status"] = "http_error"
            result["http_status"] = error.response.status_code
        except httpx.HTTPError:
            result["status"] = "connection_error"
        finally:
            result["latency_ms"] = round((time.monotonic() - started) * 1000)
        return result
