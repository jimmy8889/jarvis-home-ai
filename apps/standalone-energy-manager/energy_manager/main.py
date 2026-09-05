from __future__ import annotations

import asyncio
import logging
import signal

import uvicorn

from .api import create_app
from .config import Settings
from .ownership import ControllerOwnership
from .service import EnergyManager


async def run() -> None:
    settings = Settings.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with ControllerOwnership(settings.data_dir / "controller.lock"):
        manager = EnergyManager(settings)
        await manager.start()
        server = uvicorn.Server(uvicorn.Config(
            create_app(manager),
            host=settings.bind_host,
            port=settings.bind_port,
            log_level="info",
            # SSE dashboard clients are deliberately long-lived. Bound their
            # shutdown so systemd still reaches manager.stop(), which restores
            # the inverter safe state and releases flexible-load leases.
            timeout_graceful_shutdown=5,
        ))
        try:
            await server.serve()
        finally:
            await manager.stop()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
