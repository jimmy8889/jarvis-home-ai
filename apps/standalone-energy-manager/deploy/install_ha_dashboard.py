#!/usr/bin/env python3
"""Install the standalone display-only Home Assistant dashboard."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile


def atomic_json(path: Path, value: dict) -> None:
    stat = path.stat()
    fd, temporary = tempfile.mkstemp(prefix=f"{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.st_mode)
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("/config/.storage/lovelace.energy_control"),
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("/config/.storage/lovelace_dashboards"),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("refusing mutation without --apply")

    dashboard = json.loads(args.source.read_text(encoding="utf-8"))
    assert dashboard["views"]
    assert all(view.get("type") == "sections" for view in dashboard["views"])
    assert "energy_optimizer_" not in json.dumps(dashboard)

    storage = json.loads(args.target.read_text(encoding="utf-8"))
    assert storage.get("key") == "lovelace.energy_control"
    storage["data"]["config"] = dashboard
    atomic_json(args.target, storage)

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    entry = next(item for item in registry["data"]["items"] if item.get("id") == "energy_control")
    entry["title"] = "Energy Manager"
    entry["icon"] = "mdi:home-lightning-bolt"
    atomic_json(args.registry, registry)
    print(json.dumps({
        "dashboard": storage["key"],
        "title": dashboard["title"],
        "views": len(dashboard["views"]),
        "sections": sum(len(view.get("sections", [])) for view in dashboard["views"]),
    }))


if __name__ == "__main__":
    main()
