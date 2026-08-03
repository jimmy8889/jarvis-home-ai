from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from typing import Any
from uuid import uuid4

from .config import Room
from .home_intelligence import HomeIntelligence
from .integrations import (
    IntegrationRequestFailed,
    IntegrationUnavailable,
    Integrations,
)
from .storage import Store


class HomeActionError(RuntimeError):
    pass


class HomeActionForbidden(HomeActionError):
    pass


class HomeActionConflict(HomeActionError):
    pass


LIGHT_COLOR_RGB: dict[str, tuple[int, int, int]] = {
    "amber": (255, 191, 0),
    "blue": (0, 90, 255),
    "cool_white": (201, 226, 255),
    "cyan": (0, 255, 255),
    "green": (0, 255, 0),
    "indigo": (75, 0, 130),
    "magenta": (255, 0, 255),
    "orange": (255, 128, 0),
    "pink": (255, 105, 180),
    "purple": (160, 32, 240),
    "red": (255, 0, 0),
    "teal": (0, 255, 170),
    "warm_white": (255, 214, 170),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
}
LIGHT_COLOUR_MODES = frozenset({"hs", "rgb", "rgbw", "rgbww", "xy"})


@dataclass(frozen=True)
class ActionPlan:
    domain: str
    service: str
    service_data: dict[str, Any]
    risk: str
    confirmation_required: bool
    description: str


class HomeActions:
    """Governed Home Assistant projections and entity-scoped actions."""

    CONTROL_DOMAINS = frozenset(
        {
            "alarm_control_panel",
            "climate",
            "cover",
            "fan",
            "input_boolean",
            "light",
            "lock",
            "scene",
            "switch",
        }
    )

    def __init__(
        self,
        store: Store,
        intelligence: HomeIntelligence,
        integrations: Integrations,
        rooms: tuple[Room, ...],
    ) -> None:
        self.store = store
        self.intelligence = intelligence
        self.integrations = integrations
        self.rooms = {room.id: room for room in rooms}

    def room_projection(self, room_id: str) -> dict[str, Any]:
        room = self.rooms.get(room_id)
        if room is None:
            raise KeyError(room_id)
        entities: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = self.intelligence.catalog(include_missing=False, limit=5_000)
        for entity in page["entities"]:
            presentation = self.intelligence.presentation(entity)
            if not presentation["included"]:
                continue
            if presentation["room"]["id"] != room.id:
                continue
            if entity["entity_id"] in seen:
                continue
            seen.add(entity["entity_id"])
            entities.append(self._project_entity(entity))
        entities.sort(
            key=lambda item: (
                -item["presentation"]["priority"],
                item["presentation"]["section"],
                item["name"].casefold(),
            )
        )
        return {
            "room": {
                "id": room.id,
                "name": room.name,
                "home_area_ids": list(self._area_ids(room)),
            },
            "entity_count": len(entities),
            "entities": entities,
            "freshness": self.intelligence.sync_status(),
        }

    def model_manifest(self) -> dict[str, Any]:
        """Return the shared semantic model used before calibrated GLB geometry exists."""
        rooms = [
            {
                "id": room.id,
                "name": room.name,
                "home_area_ids": list(self._area_ids(room)),
                "geometry_node": None,
                "camera": None,
                "entity_count": self.room_projection(room.id)["entity_count"],
            }
            for room in sorted(self.rooms.values(), key=lambda item: item.id)
        ]
        canonical = json.dumps(rooms, sort_keys=True, separators=(",", ":")).encode()
        return {
            "schema_version": "1.0",
            "model_version": hashlib.sha256(canonical).hexdigest()[:16],
            "presentation": "semantic-2d",
            "geometry": None,
            "rooms": rooms,
            "capabilities": {
                "typed_actions": True,
                "confirmation": True,
                "audit": True,
                "live_events": False,
                "glb_geometry": False,
            },
        }

    def authorize_room(
        self,
        device: dict[str, Any],
        requested_room_id: str | None,
    ) -> str:
        room_id = requested_room_id or str(device["room_id"])
        if room_id not in self.rooms:
            raise KeyError(room_id)
        if room_id != device["room_id"] and "portable-client" not in device["capabilities"]:
            raise HomeActionForbidden("fixed-room device cannot access another room")
        return room_id

    def prepare(
        self,
        device: dict[str, Any],
        room_id: str,
        entity_id: str,
        action: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        entity = self.intelligence.entity(entity_id.casefold())
        if entity is None or entity["missing"]:
            raise KeyError(entity_id)
        if entity["unavailable"] or entity["stale"]:
            raise HomeActionConflict("entity is unavailable or stale")
        room = self.rooms[room_id]
        presentation = self.intelligence.presentation(entity)
        if presentation["room"]["id"] != room.id:
            raise HomeActionForbidden("entity is not mapped to the selected room")
        if not presentation["room"]["authoritative"]:
            raise HomeActionForbidden(
                "entity room mapping is inferred and cannot authorize an action"
            )
        if not presentation["included"]:
            raise HomeActionForbidden("entity is excluded from Pilot")
        plan = self._plan(entity, action, parameters)
        request = self.store.create_home_action(
            request_id=str(uuid4()),
            principal_type="device",
            principal_id=str(device["id"]),
            room_id=room_id,
            entity_id=entity["entity_id"],
            action=action,
            parameters=parameters,
            risk=plan.risk,
            confirmation_required=plan.confirmation_required,
            ttl_seconds=120 if plan.confirmation_required else 30,
        )
        return {
            **request,
            "description": plan.description,
            "entity": self._project_entity(entity),
        }

    async def execute(
        self,
        request_id: str,
        device: dict[str, Any],
        *,
        confirm: bool,
    ) -> dict[str, Any]:
        existing = self.store.get_home_action(request_id)
        if existing is None or existing["principal_id"] != device["id"]:
            raise KeyError(request_id)
        entity = self.intelligence.entity(existing["entity_id"])
        if entity is None or entity["missing"]:
            raise HomeActionConflict("entity no longer exists")
        plan = self._plan(entity, existing["action"], existing["parameters"])
        try:
            self.store.claim_home_action(
                request_id,
                str(device["id"]),
                confirm=confirm,
            )
        except ValueError as error:
            raise HomeActionConflict(str(error)) from None
        try:
            provider = await self.integrations.home_assistant_typed_action(
                plan.domain,
                plan.service,
                entity["entity_id"],
                plan.service_data,
            )
            reconciliation = await self._reconcile(entity, existing["action"], plan)
            status = (
                "succeeded"
                if reconciliation["matched"] is True
                else "unverified"
                if reconciliation["matched"] is None
                else "failed"
            )
            result = {
                "provider": provider,
                "reconciliation": reconciliation,
            }
            return self.store.complete_home_action(request_id, status, result)
        except (IntegrationUnavailable, IntegrationRequestFailed, HomeActionError) as error:
            result = {"error": str(error)}
            self.store.complete_home_action(request_id, "failed", result)
            raise HomeActionError(str(error)) from None

    def available_actions(self, entity: dict[str, Any]) -> list[str]:
        domain = entity["domain"]
        if domain in {"light", "switch", "input_boolean"}:
            actions = ["turn_on", "turn_off", "toggle"]
            if domain == "light":
                actions.append("set_brightness")
                supported_modes = entity.get("attributes", {}).get(
                    "supported_color_modes", []
                )
                if isinstance(supported_modes, (list, tuple)) and any(
                    str(mode).casefold() in LIGHT_COLOUR_MODES
                    for mode in supported_modes
                ):
                    actions.append("set_color")
            return actions
        if domain == "fan":
            return ["turn_on", "turn_off", "toggle", "set_percentage"]
        if domain == "climate":
            return ["turn_on", "turn_off", "set_temperature", "set_hvac_mode"]
        if domain == "cover":
            return ["open", "close", "stop", "set_position"]
        if domain == "scene":
            return ["activate"]
        if domain == "lock":
            return ["lock", "unlock"]
        if domain == "alarm_control_panel":
            return ["arm_home", "arm_away", "disarm"]
        return []

    def _plan(
        self,
        entity: dict[str, Any],
        action: str,
        parameters: dict[str, Any],
    ) -> ActionPlan:
        domain = entity["domain"]
        if action not in self.available_actions(entity):
            raise HomeActionConflict("action is not supported for this entity")
        data: dict[str, Any] = {}
        service = action
        if action == "set_brightness":
            value = self._number(parameters, "value", 0, 100)
            service = "turn_on"
            data["brightness_pct"] = round(value)
        elif action == "set_color":
            service = "turn_on"
            colour = str(parameters.get("color", "")).strip().casefold()
            colour = colour.replace("-", "_").replace(" ", "_")
            rgb_keys = ("red", "green", "blue")
            supplied_rgb = [key in parameters for key in rgb_keys]
            if colour and any(supplied_rgb):
                raise HomeActionConflict("use either color or RGB values, not both")
            if colour:
                rgb = LIGHT_COLOR_RGB.get(colour)
                if rgb is None:
                    raise HomeActionConflict("unsupported light color")
            elif all(supplied_rgb):
                rgb = tuple(
                    self._integer(parameters, key, 0, 255) for key in rgb_keys
                )
            else:
                raise HomeActionConflict(
                    "set_color requires a supported color or red, green, and blue"
                )
            data["rgb_color"] = list(rgb)
            if "brightness" in parameters:
                brightness = self._number(parameters, "brightness", 0, 100)
                data["brightness_pct"] = round(brightness)
        elif action == "set_percentage":
            value = self._number(parameters, "value", 0, 100)
            data["percentage"] = round(value)
        elif action == "set_temperature":
            value = self._number(parameters, "value", 10, 35)
            data["temperature"] = round(value, 1)
        elif action == "set_hvac_mode":
            value = str(parameters.get("value", "")).strip()
            if value not in {"off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only"}:
                raise HomeActionConflict("invalid HVAC mode")
            data["hvac_mode"] = value
        elif action == "open":
            service = "open_cover"
        elif action == "close":
            service = "close_cover"
        elif action == "stop":
            service = "stop_cover"
        elif action == "set_position":
            value = self._number(parameters, "value", 0, 100)
            service = "set_cover_position"
            data["position"] = round(value)
        elif action == "activate":
            service = "turn_on"
        elif action == "arm_home":
            service = "alarm_arm_home"
        elif action == "arm_away":
            service = "alarm_arm_away"
        elif action == "disarm":
            service = "alarm_disarm"

        attributes = entity.get("attributes", {})
        garage = (
            domain == "cover"
            and str(attributes.get("device_class", "")).casefold() == "garage"
        )
        high_risk = domain in {"lock", "alarm_control_panel"} or garage
        risk = "high" if high_risk else "medium" if domain in {"cover", "scene"} else "low"
        confirmation = high_risk
        description = f"{action.replace('_', ' ').title()} {entity['name']}"
        return ActionPlan(
            domain=domain,
            service=service,
            service_data=data,
            risk=risk,
            confirmation_required=confirmation,
            description=description,
        )

    async def _reconcile(
        self,
        entity: dict[str, Any],
        action: str,
        plan: ActionPlan,
    ) -> dict[str, Any]:
        last: dict[str, Any] | None = None
        matched: bool | None = None
        attempts = 0
        for delay in (0.15, 0.35, 0.75):
            attempts += 1
            await asyncio.sleep(delay)
            raw = await self.integrations.home_assistant_state(entity["entity_id"])
            last = {
                "entity_id": raw.get("entity_id", entity["entity_id"]),
                "state": str(raw.get("state", ""))[:128],
                "last_changed": raw.get("last_changed"),
                "attributes": {
                    key: raw.get("attributes", {}).get(key)
                    for key in (
                        "brightness",
                        "current_position",
                        "hvac_mode",
                        "percentage",
                        "rgb_color",
                        "temperature",
                    )
                    if key in raw.get("attributes", {})
                },
            }
            matched = self._matches(entity, action, plan, last)
            if matched is not False:
                break
        return {
            "matched": matched,
            "observed": last,
            "attempts": attempts,
        }

    @staticmethod
    def _matches(
        before: dict[str, Any],
        action: str,
        plan: ActionPlan,
        observed: dict[str, Any],
    ) -> bool | None:
        state = observed["state"]
        attributes = observed["attributes"]
        if action == "turn_on":
            return state == "on"
        if action == "turn_off":
            return state == "off"
        if action == "toggle":
            expected = "off" if before["state"] == "on" else "on"
            return state == expected
        if action == "set_brightness":
            expected = plan.service_data["brightness_pct"] * 255 / 100
            actual = attributes.get("brightness")
            return isinstance(actual, (int, float)) and abs(actual - expected) <= 5
        if action == "set_color":
            if state != "on":
                return False
            expected_rgb = plan.service_data["rgb_color"]
            actual_rgb = attributes.get("rgb_color")
            if not (
                isinstance(actual_rgb, (list, tuple))
                and len(actual_rgb) == 3
                and all(isinstance(value, (int, float)) for value in actual_rgb)
            ):
                return None
            colour_matches = all(
                abs(float(actual) - float(expected)) <= 12
                for actual, expected in zip(actual_rgb, expected_rgb, strict=True)
            )
            expected_brightness = plan.service_data.get("brightness_pct")
            if expected_brightness is None:
                return colour_matches
            actual_brightness = attributes.get("brightness")
            brightness_matches = isinstance(actual_brightness, (int, float)) and abs(
                actual_brightness - expected_brightness * 255 / 100
            ) <= 5
            return colour_matches and brightness_matches
        if action == "set_percentage":
            return attributes.get("percentage") == plan.service_data["percentage"]
        if action == "set_temperature":
            actual = attributes.get("temperature")
            return isinstance(actual, (int, float)) and abs(
                actual - plan.service_data["temperature"]
            ) <= 0.2
        if action == "set_hvac_mode":
            return (
                state == plan.service_data["hvac_mode"]
                or attributes.get("hvac_mode") == plan.service_data["hvac_mode"]
            )
        if action == "open":
            return state in {"open", "opening"}
        if action == "close":
            return state in {"closed", "closing"}
        if action == "stop":
            return state not in {"opening", "closing"}
        if action == "set_position":
            actual = attributes.get("current_position")
            return isinstance(actual, (int, float)) and abs(
                actual - plan.service_data["position"]
            ) <= 3
        if action == "lock":
            return state in {"locked", "locking"}
        if action == "unlock":
            return state in {"unlocked", "unlocking"}
        if action == "arm_home":
            return state in {"armed_home", "arming"}
        if action == "arm_away":
            return state in {"armed_away", "arming"}
        if action == "disarm":
            return state == "disarmed"
        if action == "activate":
            return None
        return None

    def _project_entity(self, entity: dict[str, Any]) -> dict[str, Any]:
        presentation = self.intelligence.presentation(entity)
        actions = self.available_actions(entity)
        presentation["supported_actions"] = actions
        entity = self.intelligence.public_entity(entity)
        return {
            "entity_id": entity["entity_id"],
            "domain": entity["domain"],
            "name": entity["name"],
            "state": entity["state"],
            "attributes": entity["attributes"],
            "area_id": entity["area_id"],
            "availability": entity["availability"],
            "unavailable": entity["unavailable"],
            "stale": entity["stale"],
            "observed_at": entity["observed_at"],
            "actions": actions,
            "presentation": presentation,
        }

    @staticmethod
    def _number(
        parameters: dict[str, Any],
        key: str,
        minimum: float,
        maximum: float,
    ) -> float:
        value = parameters.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HomeActionConflict(f"{key} must be a number")
        selected = float(value)
        if selected < minimum or selected > maximum:
            raise HomeActionConflict(
                f"{key} must be between {minimum:g} and {maximum:g}"
            )
        return selected

    @classmethod
    def _integer(
        cls,
        parameters: dict[str, Any],
        key: str,
        minimum: int,
        maximum: int,
    ) -> int:
        value = cls._number(parameters, key, minimum, maximum)
        if not value.is_integer():
            raise HomeActionConflict(f"{key} must be a whole number")
        return int(value)

    @staticmethod
    def _area_ids(room: Room) -> tuple[str, ...]:
        return room.home_area_ids or (room.id,)
