from __future__ import annotations

import logging

import uvicorn

from .api import create_app
from .config import Settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.bind_port)


if __name__ == "__main__":
    main()
