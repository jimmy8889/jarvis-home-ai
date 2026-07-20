from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import math
import re
from typing import Any

from .config import IntegrationSettings, Room
from .integrations import IntegrationRequestFailed, IntegrationUnavailable, Integrations
from .storage import Store


class HomeResolutionError(ValueError):
    """A read request did not resolve safely to exactly one entity."""


_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")
_NON_WORD = re.compile(r"[^a-z0-9]+")
_SAFE_ATTRIBUTES = frozenset(
    {
        "attribution",
        "battery_level",
        "brightness",
        "color_mode",
        "current_position",
        "current_temperature",
        "device_class",
        "friendly_name",
        "humidity",
        "hvac_action",
        "hvac_mode",
        "icon",
        "media_album_name",
        "media_artist",
        "media_content_type",
        "media_duration",
        "media_position",
        "media_title",
        "percentage",
        "position",
        "source",
        "source_list",
        "state_class",
        "supported_color_modes",
        "supported_features",
        "temperature",
        "unit_of_measurement",
        "volume_level",
    }
)
_ENERGY_DEFAULTS: dict[str, tuple[str, ...]] = {
    "solar": ("sensor.pv_power_mqtt_abs",),
    "grid": ("sensor.saj_ct_grid_power_total",),
    "battery": ("sensor.saj_battery_power_2",),
    "battery_soc": (
        "sensor.saj_battery_1_soc",
        "sensor.saj_battery_soc",
        "sensor.saj_battery_state_of_charge",
    ),
    "home_load": ("sensor.saj_home_load",),
}
HOME_READ_TOOL_NAMES = frozenset(
    {
        "search_home_entities",
        "read_home_entity",
        "get_home_area_summary",
        "get_energy_snapshot",
    }
)


def _clean_text(value: Any, limit: int) -> str:
    text = _CONTROL_CHARACTERS.sub(" ", str(value or ""))
    return " ".join(text.split())[:limit]


def _slug(value: str) -> str:
    return _NON_WORD.sub("_", value.casefold()).strip("_")[:128]


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 2:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _clean_text(value, 300)
    if isinstance(value, (list, tuple)):
        return [
            safe
            for item in list(value)[:20]
            if (safe := _safe_value(item, depth=depth + 1)) is not None
        ]
    return None


def _parse_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _numeric_state(entity: dict[str, Any]) -> float | None:
    try:
        value = float(entity["state"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class HomeIntelligence:
    """Read-only, normalized Home Assistant world-state catalogue."""

    def __init__(
        self,
        store: Store,
        integrations: Integrations,
        settings: IntegrationSettings,
        rooms: tuple[Room, ...] = (),
    ) -> None:
        self.store = store
        self.integrations = integrations
        self.settings = settings
        self.rooms = rooms
        self._sync_lock = asyncio.Lock()
        self._stopping = asyncio.Event()

    @property
    def configured(self) -> bool:
        return bool(self.settings.home_assistant_url)

    def sync_status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "sync_interval_seconds": self.settings.home_catalog_sync_interval_seconds,
            "stale_after_seconds": self.settings.home_catalog_stale_after_seconds,
            **self.store.home_catalog_sync_status(
                self.settings.home_catalog_stale_after_seconds
            ),
        }

    async def sync(self) -> dict[str, Any]:
        if self._sync_lock.locked():
            return {**self.sync_status(), "status": "already_running"}
        async with self._sync_lock:
            sync_id = self.store.begin_home_catalog_sync()
            try:
                states_result, registry_result = await asyncio.gather(
                    self.integrations.home_assistant_states(),
                    self.integrations.home_assistant_registry_snapshot(),
                    return_exceptions=True,
                )
                if isinstance(states_result, BaseException):
                    raise states_result
                registry: dict[str, Any] | None = None
                entity_metadata: dict[str, dict[str, Any]] | None = None
                entity_metadata_available = False
                metadata_status = "unavailable"
                metadata_error: str | None = None
                if isinstance(registry_result, dict):
                    registry = self.normalize_registry_snapshot(registry_result)
                    entity_metadata = registry.pop("entity_metadata")
                    entity_metadata_available = bool(
                        registry.pop("entity_metadata_available")
                    )
                    metadata_status = (
                        "complete"
                        if all(registry_result.get("supported", {}).values())
                        else "partial"
                    )
                else:
                    metadata_error = str(registry_result)
                synced_at = datetime.now(UTC).isoformat()
                records = self.normalize_snapshot(
                    states_result,
                    synced_at=synced_at,
                    registry_metadata=entity_metadata,
                )
                return self.store.replace_home_catalog(
                    sync_id,
                    records,
                    registry,
                    metadata_status=metadata_status,
                    metadata_error=metadata_error,
                    preserve_entity_metadata=not entity_metadata_available,
                )
            except Exception as error:
                self.store.fail_home_catalog_sync(sync_id, str(error))
                raise

    async def run(self) -> None:
        self._stopping.clear()
        while not self._stopping.is_set():
            try:
                await self.sync()
            except (IntegrationUnavailable, IntegrationRequestFailed, ValueError):
                pass
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=self.settings.home_catalog_sync_interval_seconds,
                )
            except TimeoutError:
                continue

    async def stop(self) -> None:
        self._stopping.set()

    def normalize_snapshot(
        self,
        states: list[dict[str, Any]],
        *,
        synced_at: str | None = None,
        registry_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if len(states) > self.settings.home_catalog_max_entities:
            raise ValueError("state snapshot exceeds the configured entity limit")
        synchronized = synced_at or datetime.now(UTC).isoformat()
        metadata = registry_metadata or {}
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in states:
            entity_id = _clean_text(raw.get("entity_id"), 255).casefold()
            if not _ENTITY_ID.fullmatch(entity_id) or entity_id in seen:
                continue
            seen.add(entity_id)
            domain, local_id = entity_id.split(".", 1)
            raw_attributes = raw.get("attributes")
            attributes = raw_attributes if isinstance(raw_attributes, dict) else {}
            entity_metadata = metadata.get(entity_id) or {}
            friendly_name = _clean_text(
                entity_metadata.get("name")
                or entity_metadata.get("original_name")
                or attributes.get("friendly_name")
                or local_id.replace("_", " ").title(),
                200,
            )
            state = _clean_text(raw.get("state"), 256)
            aliases = self._aliases(
                friendly_name,
                local_id,
                entity_metadata.get("aliases"),
            )
            area_id = self._area_id(
                entity_id,
                friendly_name,
                entity_metadata.get("area_id"),
            )
            device_id = _clean_text(entity_metadata.get("device_id"), 128) or None
            unique_id = _clean_text(entity_metadata.get("unique_id"), 255)
            availability = (
                "unavailable"
                if state.casefold() == "unavailable"
                else "unknown"
                if state.casefold() in {"", "unknown", "none"}
                else "available"
            )
            safe_attributes = {
                key: safe
                for key, value in attributes.items()
                if key in _SAFE_ATTRIBUTES
                and (safe := _safe_value(value)) is not None
            }
            normalized.append(
                {
                    "entity_id": entity_id,
                    "stable_id": unique_id or entity_id,
                    "domain": domain,
                    "name": friendly_name,
                    "state": state,
                    "attributes": safe_attributes,
                    "area_id": area_id,
                    "device_id": device_id,
                    "aliases": aliases,
                    "availability": availability,
                    "observed_at": _parse_timestamp(
                        raw.get("last_updated") or raw.get("last_changed")
                    ),
                    "synced_at": synchronized,
                }
            )
        return normalized

    def normalize_registry_snapshot(
        self,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        raw_floors = snapshot.get("floors")
        raw_areas = snapshot.get("areas")
        raw_devices = snapshot.get("devices")
        raw_entities = snapshot.get("entities")

        floors = (
            [
                {
                    "id": _slug(_clean_text(item.get("floor_id"), 128)),
                    "name": _clean_text(item.get("name"), 200),
                    "level": (
                        int(item["level"])
                        if isinstance(item.get("level"), int)
                        and -100 <= item["level"] <= 100
                        else None
                    ),
                }
                for item in raw_floors
                if _slug(_clean_text(item.get("floor_id"), 128))
                and _clean_text(item.get("name"), 200)
            ]
            if isinstance(raw_floors, list)
            else None
        )
        areas = (
            [
                {
                    "id": _slug(_clean_text(item.get("area_id"), 128)),
                    "name": _clean_text(item.get("name"), 200),
                    "floor_id": (
                        _slug(_clean_text(item.get("floor_id"), 128)) or None
                    ),
                }
                for item in raw_areas
                if _slug(_clean_text(item.get("area_id"), 128))
                and _clean_text(item.get("name"), 200)
            ]
            if isinstance(raw_areas, list)
            else None
        )
        devices = (
            [
                {
                    "id": _clean_text(item.get("id"), 128),
                    "name": _clean_text(
                        item.get("name_by_user") or item.get("name") or "Device",
                        200,
                    ),
                    "area_id": _slug(_clean_text(item.get("area_id"), 128)) or None,
                    "manufacturer": _clean_text(item.get("manufacturer"), 120) or None,
                    "model": _clean_text(item.get("model"), 120) or None,
                }
                for item in raw_devices
                if _clean_text(item.get("id"), 128)
            ]
            if isinstance(raw_devices, list)
            else None
        )
        devices_by_id = {
            item["id"]: item for item in (devices or [])
        }
        entity_metadata: dict[str, dict[str, Any]] = {}
        if isinstance(raw_entities, list):
            for item in raw_entities:
                entity_id = _clean_text(item.get("entity_id"), 255).casefold()
                if not _ENTITY_ID.fullmatch(entity_id):
                    continue
                device_id = _clean_text(item.get("device_id"), 128) or None
                direct_area = _slug(_clean_text(item.get("area_id"), 128)) or None
                device_area = (
                    devices_by_id.get(device_id, {}).get("area_id")
                    if device_id
                    else None
                )
                aliases = item.get("aliases")
                entity_metadata[entity_id] = {
                    "unique_id": _clean_text(item.get("unique_id"), 255),
                    "name": _clean_text(item.get("name"), 200),
                    "original_name": _clean_text(item.get("original_name"), 200),
                    "area_id": direct_area or device_area,
                    "device_id": device_id,
                    "aliases": aliases if isinstance(aliases, list) else [],
                }
        return {
            "floors": floors,
            "areas": areas,
            "devices": devices,
            "entity_metadata": entity_metadata,
            "entity_metadata_available": isinstance(raw_entities, list),
        }

    def _aliases(
        self,
        friendly_name: str,
        local_id: str,
        raw_aliases: Any,
    ) -> list[str]:
        candidates: list[Any] = [friendly_name, local_id.replace("_", " ")]
        if isinstance(raw_aliases, list):
            candidates.extend(raw_aliases[:20])
        aliases: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            alias = _clean_text(candidate, 200)
            folded = alias.casefold()
            if alias and folded not in seen:
                aliases.append(alias)
                seen.add(folded)
        return aliases

    def _area_id(
        self,
        entity_id: str,
        friendly_name: str,
        registry_area_id: Any,
    ) -> str | None:
        registered = _slug(_clean_text(registry_area_id, 128))
        if registered:
            return registered
        haystack = f" {entity_id.replace('.', ' ').replace('_', ' ')} {friendly_name.casefold()} "
        matches: list[str] = []
        for room in self.rooms:
            names = {_slug(room.id), _slug(room.name)}
            if any(
                name and f" {name.replace('_', ' ')} " in haystack
                for name in names
            ):
                matches.append(_slug(room.id))
        return matches[0] if len(set(matches)) == 1 else None

    def catalog(
        self,
        *,
        query: str | None = None,
        domain: str | None = None,
        area_id: str | None = None,
        availability: str | None = None,
        include_missing: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        result = self.store.search_home_entities(
            query=query,
            domain=domain,
            area_id=area_id,
            availability=availability,
            include_missing=include_missing,
            limit=limit,
            stale_after_seconds=self.settings.home_catalog_stale_after_seconds,
        )
        return {
            **result,
            "query": {
                "q": query,
                "domain": domain,
                "area_id": area_id,
                "availability": availability,
                "include_missing": include_missing,
                "limit": limit,
            },
        }

    def entity(self, entity_id: str) -> dict[str, Any] | None:
        return self.store.get_home_entity(
            entity_id,
            self.settings.home_catalog_stale_after_seconds,
        )

    def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        area_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        normalized = " ".join(query.casefold().split())[:200]
        if not normalized:
            raise HomeResolutionError("search query must not be empty")
        raw = self.store.search_home_entities(
            query=normalized,
            domain=domain,
            area_id=area_id,
            include_missing=False,
            limit=max(100, limit),
            stale_after_seconds=self.settings.home_catalog_stale_after_seconds,
        )
        tokens = set(normalized.split())
        scored: list[tuple[int, dict[str, Any], str]] = []
        for entity in raw["entities"]:
            fields = {
                entity["entity_id"].casefold(),
                entity["name"].casefold(),
                *(alias.casefold() for alias in entity["aliases"]),
            }
            score = 0
            reason = "partial_match"
            if normalized == entity["entity_id"].casefold():
                score, reason = 1000, "exact_entity_id"
            elif normalized in fields:
                score, reason = 900, "exact_name_or_alias"
            else:
                words = set(" ".join(fields).replace("_", " ").split())
                matches = len(tokens & words)
                score = matches * 100
                if normalized in " ".join(fields):
                    score += 60
                if area_id and entity["area_id"] == area_id:
                    score += 30
            if entity["availability"] == "available":
                score += 5
            if entity["stale"]:
                score -= 20
            scored.append((score, entity, reason))
        scored.sort(key=lambda item: (-item[0], item[1]["name"].casefold()))
        matches = [
            {**entity, "match_score": score, "match_reason": reason}
            for score, entity, reason in scored[: min(max(limit, 1), 100)]
            if score > 0
        ]
        ambiguous = (
            len(matches) > 1
            and matches[0]["match_score"] < 1000
            and matches[0]["match_score"] - matches[1]["match_score"] <= 10
        )
        return {"query": query, "matches": matches, "ambiguous": ambiguous}

    def resolve(
        self,
        query: str,
        *,
        domain: str | None = None,
        area_id: str | None = None,
    ) -> dict[str, Any]:
        direct = self.entity(query.casefold())
        if direct and not direct["missing"]:
            if domain and direct["domain"] != domain:
                raise HomeResolutionError("entity does not match the requested domain")
            if area_id and direct["area_id"] != area_id:
                raise HomeResolutionError("entity does not match the requested area")
            return direct
        result = self.search(query, domain=domain, area_id=area_id, limit=5)
        if not result["matches"]:
            raise HomeResolutionError(f"no entity matched: {query}")
        if result["ambiguous"]:
            candidates = ", ".join(
                item["entity_id"] for item in result["matches"][:3]
            )
            raise HomeResolutionError(f"entity request is ambiguous: {candidates}")
        return result["matches"][0]

    def area_summary(self, area: str) -> dict[str, Any]:
        area_id = _slug(area)
        result = self.catalog(area_id=area_id, limit=500)
        if result["total"] == 0:
            raise HomeResolutionError(f"unknown or empty area: {area}")
        entities = result["entities"]
        return {
            "area_id": area_id,
            "entity_count": result["total"],
            "available_count": sum(not item["unavailable"] for item in entities),
            "unavailable_count": sum(item["unavailable"] for item in entities),
            "stale_count": sum(item["stale"] for item in entities),
            "by_domain": self._counts(entities, "domain"),
            "entities": entities[:100],
        }

    def coverage(self) -> dict[str, Any]:
        return self.store.home_catalog_coverage(
            self.settings.home_catalog_stale_after_seconds
        )

    def areas(self) -> list[dict[str, Any]]:
        return self.store.home_area_summaries(
            self.settings.home_catalog_stale_after_seconds
        )

    def floors(self) -> list[dict[str, Any]]:
        return self.store.home_floor_summaries()

    def devices(
        self,
        *,
        area_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        return self.store.home_device_summaries(area_id=area_id, limit=limit)

    def energy_snapshot(self) -> dict[str, Any]:
        configured = {
            "solar": self.settings.energy_solar_power_entity_id,
            "grid": self.settings.energy_grid_power_entity_id,
            "battery": self.settings.energy_battery_power_entity_id,
            "battery_soc": self.settings.energy_battery_soc_entity_id,
            "home_load": self.settings.energy_home_load_entity_id,
        }
        measurements: dict[str, dict[str, Any]] = {}
        for name, configured_entity_id in configured.items():
            candidates = (
                (configured_entity_id,) if configured_entity_id else _ENERGY_DEFAULTS[name]
            )
            entity = next(
                (
                    candidate
                    for entity_id in candidates
                    if (candidate := self.entity(entity_id)) is not None
                    and not candidate["missing"]
                ),
                None,
            )
            measurements[name] = self._energy_measurement(
                entity,
                percent=name == "battery_soc",
            )
        measurements["grid"]["direction"] = self._direction(
            measurements["grid"]["value"], "importing", "exporting"
        )
        measurements["battery"]["direction"] = self._direction(
            measurements["battery"]["value"], "discharging", "charging"
        )
        available = sum(
            item["value"] is not None for item in measurements.values()
        )
        return {
            "status": (
                "ok"
                if available == len(measurements)
                else "unavailable"
                if available == 0
                else "partial"
            ),
            **measurements,
        }

    @staticmethod
    def _counts(items: list[dict[str, Any]], field: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            key = str(item.get(field) or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _direction(value: Any, positive: str, negative: str) -> str:
        if not isinstance(value, (int, float)) or abs(value) < 25:
            return "idle"
        return positive if value > 0 else negative

    @staticmethod
    def _energy_measurement(
        entity: dict[str, Any] | None,
        *,
        percent: bool,
    ) -> dict[str, Any]:
        value = _numeric_state(entity) if entity else None
        unit = (
            str(entity["attributes"].get("unit_of_measurement") or "")
            if entity
            else ""
        )
        if value is not None and percent:
            if not 0 <= value <= 100:
                value = None
        elif value is not None:
            if unit.casefold() == "kw":
                value *= 1000
            elif unit.casefold() not in {"w", "watt", "watts"}:
                value = None
        return {
            "value": round(value, 1) if value is not None else None,
            "unit": "%" if percent else "W",
            "entity_id": entity["entity_id"] if entity else None,
            "observed_at": entity["observed_at"] if entity else None,
            "stale": entity["stale"] if entity else True,
            "unavailable": entity["unavailable"] if entity else True,
        }
