from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException

from .config import Settings
from .service import Coordinator


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    coordinator: Coordinator | None = None
    task: asyncio.Task | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal coordinator, task
        coordinator = Coordinator(settings)
        task = asyncio.create_task(coordinator.run_forever())
        yield
        await coordinator.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title="Ben Energy Optimizer", version="1.0.0", lifespan=lifespan)

    @app.get("/healthz")
    def healthz(): return coordinator.health() if coordinator else {"status": "starting"}

    @app.get("/readyz")
    def readyz():
        if not coordinator or not coordinator.last_plan: raise HTTPException(503, "no plan")
        return coordinator.health()

    @app.get("/v1/plan")
    def plan():
        if not coordinator or not coordinator.last_plan: raise HTTPException(503, "no plan")
        return coordinator.last_plan
    return app


def main():
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.bind_port)
