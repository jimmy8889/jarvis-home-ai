from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, HTTPException

from .config import Settings
from . import __version__
from .service import Coordinator


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    coordinator: Coordinator | None = None
    task: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal coordinator, task
        coordinator = Coordinator(settings)
        task = asyncio.create_task(coordinator.run_forever(), name="energy-optimizer")
        try:
            yield
        finally:
            await coordinator.close()
            if task:
                await task

    app = FastAPI(title="Pilot Energy Optimizer", version=__version__, lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        if coordinator is None:
            return {"status": "starting"}
        return coordinator.health()

    @app.get("/readyz")
    async def readyz():
        if coordinator is None:
            raise HTTPException(status_code=503, detail="coordinator is starting")
        ready, reason = coordinator.readiness()
        if not ready:
            raise HTTPException(status_code=503, detail=reason)
        return coordinator.health()

    @app.get("/v1/plan")
    async def plan():
        if coordinator is None or coordinator.last_plan is None:
            raise HTTPException(status_code=503, detail="no successful plan yet")
        return coordinator.last_plan.to_dict()

    return app
