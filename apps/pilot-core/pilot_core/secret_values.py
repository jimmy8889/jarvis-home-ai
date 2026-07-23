from __future__ import annotations

import os
from pathlib import Path


MAX_SECRET_BYTES = 16_384


class SecretValueError(RuntimeError):
    """A configured secret file could not be read safely."""


def read_secret(name: str) -> str:
    """Read a secret from NAME or NAME_FILE without exposing its source.

    Direct environment variables remain supported for development. Production
    deployments use Docker secret files and set only the corresponding
    ``*_FILE`` variable in the container environment.
    """

    value = os.environ.get(name)
    if value is not None:
        return value.strip()
    file_name = os.environ.get(f"{name}_FILE", "").strip()
    if not file_name:
        return ""
    path = Path(file_name)
    try:
        if path.is_symlink() or not path.is_file():
            raise SecretValueError(f"{name} secret file is not a regular file")
        if path.stat().st_size > MAX_SECRET_BYTES:
            raise SecretValueError(f"{name} secret file exceeds the size limit")
        return path.read_text(encoding="utf-8").strip()
    except SecretValueError:
        raise
    except (OSError, UnicodeError) as error:
        raise SecretValueError(f"unable to read {name} secret file") from error
