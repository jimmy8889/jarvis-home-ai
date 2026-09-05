from __future__ import annotations

import fcntl
from pathlib import Path
from typing import IO


class ControllerOwnership:
    """Process-level complement to Proxmox fencing.

    Proxmox prevents two LXCs running. This lock prevents an operator utility or
    duplicate service instance inside the active guest from opening a second
    SAJ command connection.
    """

    def __init__(self, path: Path):
        self.path = path
        self.handle: IO[str] | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise RuntimeError(f"energy controller ownership is already held: {self.path}") from None
        self.handle = handle

    def release(self) -> None:
        if self.handle is None:
            return
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None

    def __enter__(self) -> "ControllerOwnership":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()
