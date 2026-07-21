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
        for area_id in self._area_ids(room):
            page = self.intelligence.catalog(
                area_id=area_id,
                include_missing=False,
                limit=1000,
            )
            for entity in page["entities"]:
                if not self.intelligence.is_relevant(entity):
                    continue
                if entity["entity_id"] in seen:
                    continue
                seen.add(entity["entity_id"])
                entities.append(self._project_entity(entity))
        entities.sort(key=lambda item: (item["domain"], item["name"].casefold()))
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
        if entity.get("area_id") not in self._area_ids(room):
            raise HomeActionForbidden("entity is not mapped to the selected room")
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
            "actions": self.available_actions(entity),
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

    @staticmethod
    def _area_ids(room: Room) -> tuple[str, ...]:
        return room.home_area_ids or (room.id,)
