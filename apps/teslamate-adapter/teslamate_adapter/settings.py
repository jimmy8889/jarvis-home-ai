from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MAX_SECRET_BYTES = 16_384


def _secret(name: str) -> str:
    value = os.environ.get(name)
    if value is not None:
        return value.strip()
    file_name = os.environ.get(f"{name}_FILE", "").strip()
    if not file_name:
        return ""
    path = Path(file_name)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{name} secret file is not a regular file")
    if path.stat().st_size > MAX_SECRET_BYTES:
        raise RuntimeError(f"{name} secret file exceeds the size limit")
    return path.read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class Settings:
    database_url: str
    bearer_token: str
    host: str = "0.0.0.0"
    port: int = 8781
    statement_timeout_ms: int = 5_000
    maximum_response_bytes: int = 8_000_000


def load_settings() -> Settings:
    database_url = _secret("TESLAMATE_DATABASE_URL")
    bearer_token = _secret("PILOT_TESLAMATE_ADAPTER_TOKEN")
    if not database_url:
        raise RuntimeError("TESLAMATE_DATABASE_URL is required")
    if len(bearer_token) < 32:
        raise RuntimeError(
            "PILOT_TESLAMATE_ADAPTER_TOKEN must be at least 32 characters"
        )
    timeout = int(os.environ.get("TESLAMATE_STATEMENT_TIMEOUT_MS", "5000"))
    if not 250 <= timeout <= 30_000:
        raise RuntimeError("TESLAMATE_STATEMENT_TIMEOUT_MS must be 250..30000")
    response_limit = int(os.environ.get("TESLAMATE_MAXIMUM_RESPONSE_BYTES", "8000000"))
    if not 100_000 <= response_limit <= 16_000_000:
        raise RuntimeError("TESLAMATE_MAXIMUM_RESPONSE_BYTES must be 100000..16000000")
    return Settings(
        database_url=database_url,
        bearer_token=bearer_token,
        host=os.environ.get("PILOT_TESLAMATE_ADAPTER_HOST", "0.0.0.0"),
        port=int(os.environ.get("PILOT_TESLAMATE_ADAPTER_PORT", "8781")),
        statement_timeout_ms=timeout,
        maximum_response_bytes=response_limit,
    )
