from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import math
import os
from pathlib import Path
import secrets
from typing import Any

import httpx

from .config import Settings, Vehicle, VehicleControl
from .integrations import (
    IntegrationRequestFailed,
    IntegrationUnavailable,
    Integrations,
)
from .secret_values import read_secret
from .storage import Store


HIGH_RISK_ACTIONS = frozenset(
    {
        "unlock",
        "remote_start",
        "homelink",
        "valet_on",
        "valet_off",
        "open_frunk",
        "open_trunk",
        "close_trunk",
        "vent_windows",
        "close_windows",
        "install_software",
    }
)
DIRECT_ACTIONS = frozenset(
    {
        "wake",
        "destination_workflow",
        "climate_on",
        "climate_off",
        "set_temperature",
        "set_seat_heat",
        "set_seat_climate",
        "set_steering_heat",
        "start_charging",
        "stop_charging",
        "set_charge_limit",
        "sentry_on",
        "sentry_off",
        "flash_lights",
        "lock",
    }
)
ALLOWED_ATTACHMENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "application/pdf": ".pdf",
}


class VehicleError(ValueError):
    pass


class VehicleProviderUnavailable(RuntimeError):
    pass


class TeslaMateClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings.integrations
        self.transport = transport

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.settings.teslamate_adapter_url:
            raise VehicleProviderUnavailable("TeslaMate adapter is not configured")
        token = read_secret(self.settings.teslamate_adapter_token_env)
        if not token:
            raise VehicleProviderUnavailable("TeslaMate adapter token is not configured")
        try:
            async with httpx.AsyncClient(
                timeout=15,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    f"{self.settings.teslamate_adapter_url}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                if len(response.content) > 8_000_000:
                    raise ValueError("TeslaMate adapter response is too large")
                return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise VehicleProviderUnavailable("TeslaMate adapter is unavailable") from error

    async def drives(
        self, car_id: int, *, limit: int, cursor: int | None
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/cars/{car_id}/drives",
            {"limit": limit, **({"before_id": cursor} if cursor else {})},
        )

    async def drive(self, car_id: int, drive_id: int) -> dict[str, Any]:
        return await self._get(f"/v1/cars/{car_id}/drives/{drive_id}")

    async def drive_positions(
        self, car_id: int, drive_id: int, *, limit: int = 2_000
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/cars/{car_id}/drives/{drive_id}/positions", {"limit": limit}
        )

    async def charges(
        self, car_id: int, *, limit: int, cursor: int | None
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/cars/{car_id}/charges",
            {"limit": limit, **({"before_id": cursor} if cursor else {})},
        )

    async def battery_health(
        self, car_id: int, *, manual_baseline_kwh: float | None
    ) -> dict[str, Any]:
        params = (
            {"manual_baseline_kwh": manual_baseline_kwh}
            if manual_baseline_kwh is not None
            else None
        )
        return await self._get(f"/v1/cars/{car_id}/battery-health", params)


class VehicleAttachments:
    def __init__(self, store: Store, root: str, max_bytes: int) -> None:
        self.store = store
        self.root = Path(root)
        self.max_bytes = max_bytes

    async def save(
        self,
        maintenance_id: str,
        filename: str,
        content_type: str,
        chunks: AsyncIterator[bytes],
    ) -> dict[str, Any]:
        normalized_type = content_type.partition(";")[0].strip().lower()
        extension = ALLOWED_ATTACHMENT_TYPES.get(normalized_type)
        if extension is None:
            raise VehicleError("receipt must be JPEG, HEIC, HEIF, or PDF")
        if not Path(filename).name.lower().endswith(extension):
            filename = f"{Path(filename).name or 'receipt'}{extension}"
        directory = self.root / maintenance_id
        directory.mkdir(parents=True, exist_ok=True)
        attachment_id = secrets.token_hex(16)
        destination = directory / f"{attachment_id}{extension}"
        temporary = directory / f".{attachment_id}.upload"
        digest = sha256()
        size = 0
        try:
            with temporary.open("xb") as handle:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise VehicleError("receipt exceeds configured size limit")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if size == 0:
                raise VehicleError("receipt is empty")
            with temporary.open("rb") as uploaded:
                signature = uploaded.read(32)
            if not self._signature_matches(normalized_type, signature):
                raise VehicleError("receipt content does not match its declared type")
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        try:
            return self.store.create_vehicle_attachment(
                attachment_id,
                maintenance_id,
                filename=Path(filename).name[:200],
                content_type=normalized_type,
                digest=digest.hexdigest(),
                size_bytes=size,
                path=str(destination),
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    @staticmethod
    def _signature_matches(content_type: str, signature: bytes) -> bool:
        if content_type == "image/jpeg":
            return signature.startswith(b"\xff\xd8\xff")
        if content_type == "application/pdf":
            return signature.startswith(b"%PDF-")
        if content_type in {"image/heic", "image/heif"}:
            return len(signature) >= 12 and signature[4:8] == b"ftyp" and signature[
                8:12
            ] in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
        return False


class VehicleService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        integrations: Integrations,
        *,
        teslamate: TeslaMateClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.integrations = integrations
        self.teslamate = teslamate or TeslaMateClient(settings)
        self.vehicles = {vehicle.id: vehicle for vehicle in settings.vehicles if vehicle.enabled}
        self._state_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def vehicle(self, vehicle_id: str) -> Vehicle:
        vehicle = self.vehicles.get(vehicle_id)
        if vehicle is None:
            raise KeyError(vehicle_id)
        return vehicle

    def list_vehicles(self) -> list[dict[str, Any]]:
        return [
            {
                "id": vehicle.id,
                "name": vehicle.name,
                "default_climate_target_c": vehicle.default_climate_target_c,
                "usable_battery_capacity_kwh": vehicle.manual_battery_baseline_kwh,
                "available_controls": self._available_controls(vehicle),
            }
            for vehicle in self.vehicles.values()
        ]

    @staticmethod
    def _available_controls(vehicle: Vehicle) -> list[str]:
        controls = set(vehicle.controls_map())
        if any(action.startswith("set_seat_heat_") for action in controls):
            controls.add("set_seat_heat")
            controls = {
                action
                for action in controls
                if not action.startswith("set_seat_heat_")
            }
        if any(action.startswith("set_seat_climate_") for action in controls):
            controls.add("set_seat_climate")
            controls = {
                action
                for action in controls
                if not action.startswith("set_seat_climate_")
            }
        return sorted(controls)

    async def overview(self, vehicle_id: str) -> dict[str, Any]:
        vehicle = self.vehicle(vehicle_id)
        saved_snapshot = self.store.get_vehicle_snapshot(vehicle_id)
        telemetry = vehicle.telemetry_map()
        states = {
            key: self._state_cache[(vehicle_id, key)]
            for key in telemetry
            if (vehicle_id, key) in self._state_cache
        }
        tasks = {
            key: asyncio.create_task(self.integrations.home_assistant_state(entity_id))
            for key, entity_id in telemetry.items()
            if key not in states
        }
        errors = 0
        if tasks:
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, result in zip(tasks, results, strict=True):
                if isinstance(result, dict):
                    states[key] = result
                    self._state_cache[(vehicle_id, key)] = result
                else:
                    errors += 1
        values = {key: self._state_value(key, state) for key, state in states.items()}
        saved_values = (saved_snapshot or {}).get("state") or {}
        cached_fields: list[str] = []
        for key, value in saved_values.items():
            if values.get(key) is None and value is not None:
                values[key] = value
                cached_fields.append(key)
        capacity = vehicle.manual_battery_baseline_kwh
        soc = _finite(values.get("battery_percent"))
        charge_limit = _finite(values.get("charge_limit_percent"))
        if capacity is not None:
            values["usable_battery_capacity_kwh"] = capacity
            if soc is not None:
                values["stored_energy_kwh"] = round(capacity * soc / 100, 2)
            if soc is not None and charge_limit is not None:
                values["energy_to_charge_limit_kwh"] = round(
                    capacity * max(charge_limit - soc, 0) / 100,
                    2,
                )
        tyre_values = {
            corner.removeprefix("tyre_").removesuffix("_bar"): self._tyre_value(
                values.pop(corner, None), states.get(corner)
            )
            for corner in (
                "tyre_front_left_bar",
                "tyre_front_right_bar",
                "tyre_rear_left_bar",
                "tyre_rear_right_bar",
            )
        }
        observed_values = [
            str(state.get("last_updated"))
            for state in states.values()
            if state.get("last_updated")
        ]
        observed_at = max(observed_values) if observed_values else None
        freshness = "unavailable"
        if observed_at:
            try:
                age = datetime.now(UTC) - datetime.fromisoformat(observed_at)
                freshness = "fresh" if age <= timedelta(minutes=15) else "stale"
            except ValueError:
                freshness = "unverified"
        result = {
            "schema_version": "pilot.vehicle.v1",
            "id": vehicle.id,
            "name": vehicle.name,
            "observed_at": observed_at,
            "freshness": freshness,
            "state": values,
            "tyres": tyre_values,
            "available_controls": self._available_controls(vehicle),
            "providers": {
                "home_assistant": {
                    "status": "ok" if errors == 0 else "partial",
                    "configured_entity_count": len(tasks),
                    "available_entity_count": len(states),
                    "cached_field_count": len(cached_fields),
                },
                "teslamate": {
                    "status": "configured"
                    if self.settings.integrations.teslamate_adapter_url
                    else "not_configured"
                },
            },
        }
        if states:
            self.store.save_vehicle_snapshot(vehicle_id, result)
        elif saved_snapshot:
            result["freshness"] = "stale"
            result["observed_at"] = saved_snapshot.get("observed_at")
            result["providers"]["home_assistant"]["status"] = "cached"
        return result

    async def run_state_updates(self) -> None:
        """Maintain a bounded HA cache without ever issuing a wake command."""

        entity_targets: dict[str, list[tuple[str, str]]] = {}
        for vehicle in self.vehicles.values():
            for key, entity_id in vehicle.telemetry:
                entity_targets.setdefault(entity_id, []).append((vehicle.id, key))
        if not entity_targets:
            return
        while True:
            try:
                async for update in self.integrations.home_assistant_state_changes(
                    set(entity_targets)
                ):
                    entity_id = str(update.get("entity_id") or "")
                    state = update.get("state")
                    if not isinstance(state, dict):
                        continue
                    for vehicle_id, key in entity_targets.get(entity_id, []):
                        self._state_cache[(vehicle_id, key)] = state
                        self.store.record_client_event(
                            "pilot.vehicle.state.v1",
                            {
                                "privacy": "sensitive",
                                "vehicle_id": vehicle_id,
                                "field": key,
                                "value": self._state_value(key, state),
                                "observed_at": state.get("last_updated"),
                            },
                            required_capability="vehicle-read",
                        )
            except (IntegrationRequestFailed, IntegrationUnavailable):
                await asyncio.sleep(5)

    @staticmethod
    def _state_value(key: str, payload: dict[str, Any]) -> Any:
        state = payload.get("state")
        if state in {None, "", "unknown", "unavailable"}:
            return None
        if key in {
            "online",
            "locked",
            "doors",
            "windows",
            "frunk",
            "trunk",
            "charge_port",
            "software_update",
        }:
            return str(state).lower() in {
                "on",
                "true",
                "yes",
                "locked",
                "online",
                "open",
            }
        if key in {"latitude", "longitude"}:
            attribute = (payload.get("attributes") or {}).get(key)
            return _finite(attribute)
        numeric_keys = {
            "battery_percent",
            "rated_range_km",
            "ideal_range_km",
            "odometer_km",
            "latitude",
            "longitude",
            "inside_temperature_c",
            "outside_temperature_c",
            "charge_limit_percent",
            "charge_rate_kw",
            "time_to_full_hours",
            "energy_added_kwh",
        }
        if key in numeric_keys or key.startswith("tyre_"):
            try:
                value = float(state)
                return value if math.isfinite(value) else None
            except (TypeError, ValueError):
                return None
        return str(state)[:500]

    @staticmethod
    def _tyre_value(value: Any, state: dict[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {"value_bar": None, "status": "unavailable"}
        unit = str((state or {}).get("attributes", {}).get("unit_of_measurement", "bar"))
        normalized = float(value)
        if unit.casefold() in {"psi", "lb/in²"}:
            normalized *= 0.0689476
        elif unit.casefold() in {"kpa"}:
            normalized /= 100
        verified = 1.5 <= normalized <= 4.0
        return {
            "value_bar": round(normalized, 2),
            "status": "plausible" if verified else "abnormal_unverified",
            "source_unit": unit,
        }

    async def drives(
        self, vehicle_id: str, *, limit: int, cursor: int | None
    ) -> dict[str, Any]:
        vehicle = self.vehicle(vehicle_id)
        result = await self.teslamate.drives(
            vehicle.teslamate_car_id, limit=limit, cursor=cursor
        )
        items = [self._drive_view(item) for item in result.get("items", [])]
        return {"items": items, "next_cursor": result.get("next_cursor")}

    async def drive(self, vehicle_id: str, drive_id: int) -> dict[str, Any]:
        vehicle = self.vehicle(vehicle_id)
        detail_task = asyncio.create_task(
            self.teslamate.drive(vehicle.teslamate_car_id, drive_id)
        )
        positions_task = asyncio.create_task(
            self.teslamate.drive_positions(vehicle.teslamate_car_id, drive_id)
        )
        detail, positions = await asyncio.gather(detail_task, positions_task)
        result = self._drive_view(detail)
        result["positions"] = positions.get("items", [])
        result["positions_truncated"] = bool(positions.get("truncated"))
        return result

    @staticmethod
    def _drive_view(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        distance = _finite(item.get("distance"))
        start_range = _finite(item.get("start_rated_range_km"))
        end_range = _finite(item.get("end_rated_range_km"))
        efficiency = _finite(item.get("configured_efficiency_wh_per_km"))
        energy = None
        consumption = None
        if (
            distance
            and distance > 0
            and start_range is not None
            and end_range is not None
            and efficiency is not None
        ):
            range_used = start_range - end_range
            if range_used > 0:
                energy = range_used * efficiency / 1000
                consumption = energy * 1000 / distance
        result["estimated_energy_kwh"] = round(energy, 2) if energy is not None else None
        result["estimated_consumption_wh_per_km"] = (
            round(consumption, 1) if consumption is not None else None
        )
        result["incomplete"] = any(
            item.get(key) is None
            for key in ("end_date", "distance", "start_battery_level", "end_battery_level")
        )
        return result

    async def charges(
        self, vehicle_id: str, *, limit: int, cursor: int | None
    ) -> dict[str, Any]:
        vehicle = self.vehicle(vehicle_id)
        result = await self.teslamate.charges(
            vehicle.teslamate_car_id, limit=limit, cursor=cursor
        )
        items: list[dict[str, Any]] = []
        for raw in result.get("items", []):
            item = dict(raw)
            added = _finite(item.get("charge_energy_added"))
            used = _finite(item.get("charge_energy_used"))
            item["efficiency_percent"] = (
                round(added / used * 100, 1) if added is not None and used and used > 0 else None
            )
            item["charge_type"] = "DC" if item.get("dc_fast_charger") else "AC"
            item["incomplete"] = item.get("end_date") is None
            items.append(item)
        return {"items": items, "next_cursor": result.get("next_cursor")}

    async def battery_health(self, vehicle_id: str) -> dict[str, Any]:
        vehicle = self.vehicle(vehicle_id)
        result = await self.teslamate.battery_health(
            vehicle.teslamate_car_id,
            manual_baseline_kwh=vehicle.manual_battery_baseline_kwh,
        )
        result["label"] = "Estimate based on qualified TeslaMate charging sessions"
        return result

    def maintenance(self, vehicle_id: str, odometer_km: float | None) -> list[dict[str, Any]]:
        self.vehicle(vehicle_id)
        return [
            self._maintenance_due(item, odometer_km)
            for item in self.store.list_vehicle_maintenance(vehicle_id)
        ]

    @staticmethod
    def _maintenance_due(
        item: dict[str, Any], odometer_km: float | None, *, today: date | None = None
    ) -> dict[str, Any]:
        result = dict(item)
        current_date = today or datetime.now(UTC).date()
        due_date = None
        if item.get("next_due_date"):
            try:
                due_date = date.fromisoformat(str(item["next_due_date"]))
            except ValueError:
                pass
        due_odometer = _finite(item.get("next_due_odometer_km"))
        days_remaining = (due_date - current_date).days if due_date else None
        km_remaining = (
            due_odometer - odometer_km
            if due_odometer is not None and odometer_km is not None
            else None
        )
        overdue = (days_remaining is not None and days_remaining < 0) or (
            km_remaining is not None and km_remaining < 0
        )
        warning = (days_remaining is not None and days_remaining <= item["warning_days"]) or (
            km_remaining is not None and km_remaining <= item["warning_km"]
        )
        result.update(
            {
                "due_status": "overdue" if overdue else "due_soon" if warning else "scheduled",
                "days_remaining": days_remaining,
                "km_remaining": round(km_remaining, 1) if km_remaining is not None else None,
            }
        )
        return result

    def request_action(
        self,
        *,
        principal_id: str,
        vehicle_id: str,
        action: str,
        parameters: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        vehicle = self.vehicle(vehicle_id)
        if action == "destination_workflow":
            destination_id = str(parameters.get("destination_id", ""))
            if set(parameters) != {"destination_id"} or not destination_id:
                raise VehicleError("destination_id is required")
            if self.store.get_vehicle_destination(vehicle_id, destination_id) is None:
                raise KeyError(destination_id)
        elif action == "set_seat_heat":
            seat = str(parameters.get("seat", ""))
            if f"set_seat_heat_{seat}" not in vehicle.controls_map():
                raise VehicleError("seat heating position is unsupported")
        elif action in {"set_seat_climate", "set_seat_climate_front_right"}:
            if "set_seat_climate_front_right" not in vehicle.controls_map():
                raise VehicleError("front right seat climate is unsupported")
        elif action not in vehicle.controls_map():
            raise VehicleError("vehicle action is unsupported")
        self._validate_action_parameters(action, parameters)
        confirmation_required = action in HIGH_RISK_ACTIONS
        return self.store.create_vehicle_action(
            secrets.token_hex(16),
            idempotency_key,
            principal_id,
            vehicle_id,
            action,
            parameters,
            risk="high" if confirmation_required else "standard",
            confirmation_required=confirmation_required,
        )

    @staticmethod
    def _validate_action_parameters(action: str, parameters: dict[str, Any]) -> None:
        allowed_keys = {
            "set_temperature": {"temperature_c"},
            "set_seat_heat": {"seat", "level"},
            "set_seat_climate": {"mode"},
            "set_steering_heat": {"level"},
            "set_charge_limit": {"percent"},
            "destination_workflow": {"destination_id"},
        }.get(action, set())
        if set(parameters) != allowed_keys:
            raise VehicleError("vehicle action parameters are invalid")
        if action == "set_temperature" and not 15 <= float(parameters["temperature_c"]) <= 30:
            raise VehicleError("temperature_c must be 15..30")
        if action in {"set_seat_heat", "set_steering_heat"} and int(parameters["level"]) not in range(4):
            raise VehicleError("heating level must be 0..3")
        if action == "set_seat_heat" and parameters["seat"] not in {
            "front_left",
            "front_right",
            "rear_left",
            "rear_center",
            "rear_right",
        }:
            raise VehicleError("seat position is invalid")
        if action == "set_seat_climate" and parameters["mode"] not in {
            "off",
            "heat_low",
            "heat_medium",
            "heat_high",
            "cool_low",
            "cool_medium",
            "cool_high",
        }:
            raise VehicleError("seat climate mode is invalid")
        if action == "set_charge_limit" and not 50 <= int(parameters["percent"]) <= 100:
            raise VehicleError("charge limit must be 50..100")

    async def execute_action(
        self, request_id: str, principal_id: str, *, confirmed: bool = False
    ) -> dict[str, Any]:
        action = self.store.claim_vehicle_action(
            request_id, principal_id, confirmed=confirmed
        )
        if action["action"] == "destination_workflow":
            result = await self._destination_workflow(action)
        else:
            result = await self._single_action(action)
        self.store.record_client_event(
            "pilot.vehicle.action.v1",
            {
                "privacy": "sensitive",
                **{
                    key: result.get(key)
                    for key in ("id", "vehicle_id", "action", "status", "steps")
                },
            },
            required_capability="vehicle-control",
        )
        return result

    async def _single_action(self, request: dict[str, Any]) -> dict[str, Any]:
        vehicle = self.vehicle(request["vehicle_id"])
        control_key = request["action"]
        if control_key == "set_seat_heat":
            control_key = f"set_seat_heat_{request['parameters']['seat']}"
        elif control_key == "set_seat_climate":
            control_key = "set_seat_climate_front_right"
        control = vehicle.controls_map()[control_key]
        try:
            provider_result = await self._call_control(
                control, request["action"], request["parameters"]
            )
            if control.observable_entity_id:
                state = await self.integrations.home_assistant_state(
                    control.observable_entity_id
                )
                status = (
                    "reconciled"
                    if self._observable_matches(
                        request["action"], state, request["parameters"]
                    )
                    else "unverified"
                )
            else:
                status = "unverified"
            return self.store.complete_vehicle_action(
                request["id"], status, {"provider": provider_result}
            )
        except (IntegrationRequestFailed, IntegrationUnavailable) as error:
            return self.store.complete_vehicle_action(
                request["id"], "failed", {"error": str(error)}
            )

    async def _destination_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        vehicle = self.vehicle(request["vehicle_id"])
        controls = vehicle.controls_map()
        destination = self.store.get_vehicle_destination(
            vehicle.id, request["parameters"]["destination_id"]
        )
        if destination is None:
            return self.store.complete_vehicle_action(
                request["id"], "failed", {"error": "destination was removed"}
            )
        steps: list[dict[str, Any]] = []

        async def run_step(
            name: str, control: VehicleControl | None, parameters: dict[str, Any]
        ) -> bool:
            if control is None:
                steps.append({"step": name, "status": "unsupported"})
                self.store.update_vehicle_action_steps(request["id"], steps)
                return False
            try:
                await self._call_control(control, control.action, parameters)
                steps.append({"step": name, "status": "accepted"})
                self.store.update_vehicle_action_steps(request["id"], steps)
                return True
            except (IntegrationRequestFailed, IntegrationUnavailable) as error:
                steps.append({"step": name, "status": "failed", "error": str(error)})
                self.store.update_vehicle_action_steps(request["id"], steps)
                return False

        overview = await self.overview(vehicle.id)
        state = str(overview["state"].get("state") or "").casefold()
        if state in {"asleep", "offline"} or overview["state"].get("online") is False:
            woke = await run_step("wake", controls.get("wake"), {})
            if woke:
                await self._wait_until_online(vehicle, timeout_seconds=60)
        else:
            steps.append({"step": "wake", "status": "not_required"})
            self.store.update_vehicle_action_steps(request["id"], steps)

        if destination["climate_enabled"]:
            await run_step("climate", controls.get("climate_on"), {})
            temperature = destination.get("temperature_c") or vehicle.default_climate_target_c
            await run_step(
                "temperature",
                controls.get("set_temperature"),
                {"temperature_c": temperature},
            )
            seat_mode = destination.get("seat_climate_mode")
            if seat_mode:
                await run_step(
                    "front_right_seat",
                    controls.get("set_seat_climate_front_right"),
                    {"mode": seat_mode},
                )
        else:
            steps.append({"step": "climate", "status": "disabled"})
            self.store.update_vehicle_action_steps(request["id"], steps)
        route_ok = await run_step(
            "route",
            controls.get("send_route"),
            {
                "latitude": destination["latitude"],
                "longitude": destination["longitude"],
            },
        )
        final_status = "unverified" if route_ok else "failed"
        return self.store.complete_vehicle_action(
            request["id"], final_status, {"steps": steps, "compensation": "none"}
        )

    async def _wait_until_online(self, vehicle: Vehicle, *, timeout_seconds: int) -> bool:
        online_entity = vehicle.telemetry_map().get("online")
        if not online_entity:
            return False
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            try:
                state = await self.integrations.home_assistant_state(online_entity)
                if self._state_value("online", state) is True:
                    return True
            except (IntegrationRequestFailed, IntegrationUnavailable):
                pass
            await asyncio.sleep(2)
        return False

    async def _call_control(
        self,
        control: VehicleControl,
        action: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        service_data: dict[str, Any] = {}
        if action == "set_temperature":
            service_data["temperature"] = float(parameters["temperature_c"])
        elif action in {"set_seat_heat", "set_steering_heat"}:
            level = int(parameters["level"])
            if control.domain == "select":
                seat_options = ["Off", "Heat Low", "Heat Medium", "Heat High"]
                steering_options = ["Off", "Low", "High", "Auto"]
                options = (
                    seat_options if action == "set_seat_heat" else steering_options
                )
                service_data["option"] = options[level]
            else:
                service_data["level"] = level
        elif action in {"set_seat_climate", "set_seat_climate_front_right"}:
            seat_options = {
                "off": "Off",
                "heat_low": "Heat Low",
                "heat_medium": "Heat Medium",
                "heat_high": "Heat High",
                "cool_low": "Cool Low",
                "cool_medium": "Cool Medium",
                "cool_high": "Cool High",
            }
            service_data["option"] = seat_options[str(parameters["mode"])]
        elif action == "climate_on":
            # Tesla Custom exposes heat_cool/off but does not advertise the
            # optional climate.turn_on/turn_off feature flags. Driving the
            # entity through its declared HVAC mode is deterministic and
            # avoids Home Assistant returning HTTP 500.
            service_data["hvac_mode"] = "heat_cool"
        elif action == "climate_off":
            service_data["hvac_mode"] = "off"
        elif action == "set_charge_limit":
            service_data["value"] = int(parameters["percent"])
        elif action == "send_route":
            provider_vehicle_id = read_secret(control.provider_vehicle_id_env)
            if not provider_vehicle_id:
                raise IntegrationUnavailable(
                    "Tesla navigation vehicle identifier is not configured"
                )
            service_data = {
                "command": "SEND_GPS_TO_VEHICLE",
                "parameters": {
                    "path_vars": {"vehicle_id": provider_vehicle_id},
                    "lat": float(parameters["latitude"]),
                    "lon": float(parameters["longitude"]),
                    "order": 0,
                },
            }
        return await self.integrations.home_assistant_vehicle_action(
            control.domain,
            control.service,
            entity_id=control.entity_id,
            device_id=control.device_id,
            service_data=service_data,
        )

    @staticmethod
    def _observable_matches(
        action: str,
        state: dict[str, Any],
        parameters: dict[str, Any] | None = None,
    ) -> bool:
        value = str(state.get("state") or "").casefold()
        parameters = parameters or {}
        if action == "set_temperature":
            observed = _finite((state.get("attributes") or {}).get("temperature"))
            expected_temperature = _finite(parameters.get("temperature_c"))
            return (
                observed is not None
                and expected_temperature is not None
                and abs(observed - expected_temperature) <= 0.5
            )
        if action == "set_charge_limit":
            observed = _finite(state.get("state"))
            expected_limit = _finite(parameters.get("percent"))
            return observed is not None and observed == expected_limit
        if action == "set_seat_heat":
            level = int(parameters.get("level", -1))
            options = ["off", "heat low", "heat medium", "heat high"]
            return level in range(4) and value == options[level]
        if action in {"set_seat_climate", "set_seat_climate_front_right"}:
            expected = str(parameters.get("mode", "")).replace("_", " ")
            return value == expected
        if action == "set_steering_heat":
            level = int(parameters.get("level", -1))
            options = ["off", "low", "high", "auto"]
            return level in range(4) and value == options[level]
        if action == "install_software":
            return value == "installing" or bool(
                (state.get("attributes") or {}).get("in_progress")
            )
        expected = {
            "lock": {"locked", "on"},
            "unlock": {"unlocked", "off"},
            "climate_on": {"heat", "cool", "auto", "on"},
            "climate_off": {"off"},
            "start_charging": {"charging", "on"},
            "stop_charging": {"stopped", "disconnected", "off"},
            "sentry_on": {"on"},
            "sentry_off": {"off"},
            "open_frunk": {"open", "opening"},
            "open_trunk": {"open", "opening"},
            "close_trunk": {"closed", "closing"},
            "vent_windows": {"open", "opening"},
            "close_windows": {"closed", "closing"},
            "valet_on": {"on"},
            "valet_off": {"off"},
        }.get(action)
        return expected is not None and value in expected


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None
