#!/usr/bin/env python3
"""Re-enable the retained SAJ Home Assistant config entry for telemetry/UI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from retire_legacy_ha import atomic_replace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config-entries",
        type=Path,
        default=Path("/config/.storage/core.config_entries"),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("refusing mutation without --apply")

    config = json.loads(args.config_entries.read_text(encoding="utf-8"))
    targets = [
        item
        for item in config["data"]["entries"]
        if item.get("domain") == "saj_h2_modbus"
    ]
    assert len(targets) == 1, targets
    targets[0]["disabled_by"] = None
    atomic_replace(
        args.config_entries,
        json.dumps(config, ensure_ascii=False, separators=(",", ":")),
    )
    print(json.dumps({"enabled_saj_entry": targets[0]["entry_id"]}))


if __name__ == "__main__":
    main()
