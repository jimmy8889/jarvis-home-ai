from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .service import EnergyManager
from . import __version__


TripProfile = Literal["no_trip", "distance_100_km", "distance_200_km", "target_80", "target_100"]
VehicleAction = Literal[
    "lock", "unlock", "unlock_charge_port", "open_charge_port", "close_charge_port",
    "climate_on", "climate_off", "set_climate_temperature",
    "steering_heat_on", "steering_heat_off", "defrost_on", "defrost_off",
    "vent_windows", "close_windows", "wake", "flash_lights", "sound_horn",
]


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_sell_price_per_kwh: float | None = Field(default=None, ge=0, le=20)
    # Public range is 0.0-100.0 c/kWh, represented internally as AUD/kWh.
    ev_opportunistic_fit_max_per_kwh: float | None = Field(default=None, ge=0, le=1)
    ev_grid_allowed: StrictBool | None = None
    ev_charge_limit_pct: int | None = Field(default=None, ge=50, le=100)
    ev_trip_profile: TripProfile | None = None
    ev_trip_requirement: str | None = None
    control_enabled: StrictBool | None = None
    hot_water_fixed_timer: StrictBool | None = None
    hot_water_enabled: StrictBool | None = None


class VehicleControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: VehicleAction
    value: float | StrictBool | None = None


def create_app(manager: EnergyManager) -> FastAPI:
    app = FastAPI(title="Standalone Energy Manager", version=__version__)
    web_root = Path(__file__).with_name("web")

    def authorize(authorization: str | None = Header(default=None)) -> None:
        token = manager.settings.secret("api_token")
        if not token or authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="valid bearer token required")

    def authorize_vehicle(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        peer = request.client.host if request.client else ""
        forwarded = request.headers.get("X-Energy-Manager-Client-IP", "") if peer in {"127.0.0.1", "::1"} else ""
        if (forwarded or peer) == manager.settings.home_assistant_host:
            return
        token = manager.settings.secret("api_token")
        if token and authorization == f"Bearer {token}":
            return
        raise HTTPException(status_code=401, detail="vehicle control requires trusted Home Assistant or bearer token")

    @app.get("/")
    async def dashboard() -> FileResponse:
        return FileResponse(web_root / "index.html")

    @app.get("/assets/{name}")
    async def dashboard_asset(name: str) -> FileResponse:
        asset = web_root / "assets" / name
        if name != Path(name).name or asset.suffix.lower() != ".png" or not asset.is_file():
            raise HTTPException(status_code=404, detail="dashboard asset not found")
        return FileResponse(asset)

    @app.get("/api/v1/snapshot")
    async def snapshot() -> dict[str, Any]:
        return manager.snapshot()

    @app.get("/api/v1/plan")
    async def plan() -> dict[str, Any]:
        return {
            "current": manager.command.as_dict() if manager.command else None,
            "rolling": manager.rolling_plan,
        }

    @app.get("/api/v1/settings")
    async def settings() -> dict[str, Any]:
        return manager.public_settings()

    @app.get("/api/v1/vehicle")
    async def vehicle() -> dict[str, Any]:
        return manager.vehicle_snapshot()

    @app.post("/api/v1/vehicle/control", dependencies=[Depends(authorize_vehicle)])
    async def vehicle_control(payload: VehicleControl, request: Request) -> dict[str, Any]:
        try:
            status = await manager.loads.vehicle_control(payload.action, payload.value)
            await manager.storage.event("tesla_ble_manual_control", {
                "action": payload.action,
                "value": payload.value,
                "source_ip": request.headers.get("X-Energy-Manager-Client-IP") or (request.client.host if request.client else "unknown"),
                "status": status,
            })
            return {"status": status, "action": payload.action, "vehicle": manager.vehicle_snapshot()}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/series")
    async def series(limit: int = Query(default=288, ge=1, le=8640)) -> list[dict[str, Any]]:
        return await manager.storage.recent_outcomes(limit)

    @app.get("/api/v1/ups/series")
    async def ups_series(
        minutes: int = Query(default=60, ge=1, le=360),
        limit: int = Query(default=720, ge=60, le=1200),
    ) -> list[dict[str, Any]]:
        return manager.ups_series(minutes=minutes, limit=limit)

    @app.get("/api/v1/outages")
    async def outages(limit: int = Query(default=100, ge=1, le=1000)) -> list[dict[str, Any]]:
        return await manager.storage.recent_outages(limit)

    @app.get("/api/v1/daily")
    async def daily(limit: int = Query(default=30, ge=1, le=365)) -> list[dict[str, Any]]:
        return await manager.storage.daily_series(limit)

    @app.get("/api/v1/history")
    async def history(limit: int = Query(default=100, ge=1, le=1000)) -> list[dict[str, Any]]:
        return await manager.storage.recent_events(limit)

    @app.get("/api/v1/events")
    async def events(limit: int = Query(default=100, ge=1, le=1000)) -> list[dict[str, Any]]:
        return await manager.storage.recent_events(limit)

    @app.get("/api/v1/stream")
    async def stream() -> StreamingResponse:
        async def generate():
            while True:
                yield f"data: {json.dumps(manager.snapshot(), separators=(',', ':'), default=str)}\n\n"
                await asyncio.sleep(2)
        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.put("/api/v1/settings")
    async def update_settings(payload: SettingsPatch) -> dict[str, Any]:
        try:
            return await manager.update_settings(payload.model_dump(exclude_unset=True, exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/override", dependencies=[Depends(authorize)])
    async def override(payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action")
        if action == "disable":
            return await manager.update_settings({"control_enabled": False})
        if action == "enable":
            return await manager.update_settings({"control_enabled": True})
        if action == "stop_ev":
            result = await manager.loads.set_ev(False, 0, safety_reduction=True)
            return {"status": result}
        if action == "stop_hot_water":
            result = await manager.loads.set_hot_water(False)
            return {"status": result}
        if action == "safe_state":
            command = await manager.force_safe_stop("manual_override_safe_state")
            return {"status": "safe_state", "command": command.as_dict()}
        raise HTTPException(status_code=422, detail="unsupported override")

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "uptime_seconds": (datetime.now(UTC) - manager.started_at).total_seconds()}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        telemetry = manager.telemetry
        now = datetime.now(UTC)
        telemetry_ready = telemetry is not None and telemetry.healthy and (now - telemetry.measured_at).total_seconds() < 10
        fit = manager.amber.current.get("feedIn") if manager.amber else None
        amber_ready = fit is not None and fit.start <= now < fit.end and (now - fit.received_at).total_seconds() <= 330
        command_ready = manager.command is not None and manager.command.expires_at is not None and manager.command.expires_at > now and manager.command_phase not in {"failed", "starting"}
        actuator_ready = manager.devices.hot_water_available and (
            not manager.devices.ev_home or not manager.devices.ev_plugged or manager.devices.ev_ble_available
        )
        ready = telemetry_ready and (not manager.settings.control_enabled or (amber_ready and command_ready and actuator_ready))
        payload = {
            "ready": ready,
            "telemetry_ready": telemetry_ready,
            "amber_ready": amber_ready,
            "command_ready": command_ready,
            "actuator_ready": actuator_ready,
            "control_enabled": manager.settings.control_enabled,
            "command_phase": manager.command_phase,
            "error": manager.command_error,
        }
        return JSONResponse(payload, status_code=200 if ready else 503)

    return app
