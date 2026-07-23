from __future__ import annotations

import argparse
import os

import uvicorn

from .api import create_app
from .config import load_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot Core orchestration API")
    parser.add_argument(
        "--config",
        default=os.environ.get("PILOT_CORE_CONFIG", "/etc/pilot/core.toml"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    uvicorn.run(
        create_app(settings),
        host=settings.server.listen_host,
        port=settings.server.listen_port,
    )


if __name__ == "__main__":
    main()
