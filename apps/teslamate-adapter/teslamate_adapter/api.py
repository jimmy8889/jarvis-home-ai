from __future__ import annotations

import hmac
from datetime import date, datetime
import json
from typing import Any, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .database import TeslaMateRepository
from .settings import Settings, load_settings


class Repository(Protocol):
    def ready(self) -> bool: ...
    def cars(self) -> list[dict[str, Any]]: ...
    def drives(
        self, car_id: int, *, limit: int, before_id: int | None
    ) -> list[dict[str, Any]]: ...
    def drive(self, car_id: int, drive_id: int) -> dict[str, Any] | None: ...
    def drive_positions(
        self, car_id: int, drive_id: int, *, limit: int
    ) -> list[dict[str, Any]]: ...
    def charges(
        self, car_id: int, *, limit: int, before_id: int | None
    ) -> list[dict[str, Any]]: ...
    def battery_health(
        self, car_id: int, *, manual_baseline_kwh: float | None = None
    ) -> dict[str, Any]: ...


def _payload(value: Any) -> Any:
    return jsonable_encoder(
        value,
        custom_encoder={
            datetime: lambda item: item.isoformat(),
            date: lambda item: item.isoformat(),
        },
    )


def _bounded_payload(value: Any, maximum_bytes: int) -> Any:
    payload = _payload(value)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > maximum_bytes:
        raise HTTPException(status_code=502, detail="bounded response limit exceeded")
    return payload


def create_app(
    settings: Settings | None = None, repository: Repository | None = None
) -> FastAPI:
    configured = settings or load_settings()
    repo = repository or TeslaMateRepository(
        configured.database_url,
        statement_timeout_ms=configured.statement_timeout_ms,
    )
    app = FastAPI(
        title="Pilot TeslaMate Adapter", version="0.1.0", docs_url=None, redoc_url=None
    )

    def authenticate(authorization: str = Header(default="")) -> None:
        scheme, _, supplied = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            supplied, configured.bearer_token
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token"
            )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def ready() -> dict[str, str]:
        try:
            if not repo.ready():
                raise RuntimeError("database session is not read-only")
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="TeslaMate database unavailable"
            ) from error
        return {"status": "ready", "database_mode": "read_only"}

    @app.get("/v1/cars", dependencies=[Depends(authenticate)])
    def cars() -> Any:
        return _bounded_payload(
            {"items": repo.cars()}, configured.maximum_response_bytes
        )

    @app.get("/v1/cars/{car_id}/drives", dependencies=[Depends(authenticate)])
    def drives(
        car_id: int,
        limit: int = Query(50, ge=1, le=200),
        before_id: int | None = Query(None, ge=1),
    ) -> Any:
        rows = repo.drives(car_id, limit=limit, before_id=before_id)
        has_more = len(rows) > limit
        items = rows[:limit]
        return _bounded_payload(
            {
                "items": items,
                "next_cursor": items[-1]["id"] if has_more and items else None,
            },
            configured.maximum_response_bytes,
        )

    @app.get(
        "/v1/cars/{car_id}/drives/{drive_id}", dependencies=[Depends(authenticate)]
    )
    def drive(car_id: int, drive_id: int) -> Any:
        item = repo.drive(car_id, drive_id)
        if item is None:
            raise HTTPException(status_code=404, detail="drive not found")
        return _bounded_payload(item, configured.maximum_response_bytes)

    @app.get(
        "/v1/cars/{car_id}/drives/{drive_id}/positions",
        dependencies=[Depends(authenticate)],
    )
    def positions(
        car_id: int, drive_id: int, limit: int = Query(2000, ge=2, le=5000)
    ) -> Any:
        items = repo.drive_positions(car_id, drive_id, limit=limit)
        return _bounded_payload(
            {"items": items, "truncated": len(items) == limit},
            configured.maximum_response_bytes,
        )

    @app.get("/v1/cars/{car_id}/charges", dependencies=[Depends(authenticate)])
    def charges(
        car_id: int,
        limit: int = Query(50, ge=1, le=200),
        before_id: int | None = Query(None, ge=1),
    ) -> Any:
        rows = repo.charges(car_id, limit=limit, before_id=before_id)
        has_more = len(rows) > limit
        items = rows[:limit]
        return _bounded_payload(
            {
                "items": items,
                "next_cursor": items[-1]["id"] if has_more and items else None,
            },
            configured.maximum_response_bytes,
        )

    @app.get("/v1/cars/{car_id}/battery-health", dependencies=[Depends(authenticate)])
    def capacity(
        car_id: int, manual_baseline_kwh: float | None = Query(None, ge=20, le=200)
    ) -> Any:
        return _bounded_payload(
            repo.battery_health(car_id, manual_baseline_kwh=manual_baseline_kwh),
            configured.maximum_response_bytes,
        )

    @app.exception_handler(Exception)
    async def unhandled(_request: Any, _error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=503, content={"detail": "TeslaMate data unavailable"}
        )

    return app
