#!/usr/bin/env python3
"""Text-preserving retirement of legacy Home Assistant energy writers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile

import yaml


LEGACY_IDS = {
    "1735345285087",
    "1765833422326", "1765833452084", "1765833509638", "1765833528080",
    "1765837458603", "1765837567828", "1765837657637", "1765837692266",
    "1765867169342", "1766090320814", "1766169660776", "1766438137098",
    "1766537330474", "1769678731886", "1776131680954", "1776229152383",
    "1776229308254", "1776229407032", "1784693132363",
}


def atomic_replace(path: Path, content: str) -> None:
    stat = path.stat()
    fd, temporary = tempfile.mkstemp(prefix=f"{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.st_mode)
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def retire_automations(path: Path) -> list[tuple[str, str]]:
    raw = path.read_text(encoding="utf-8")
    blocks = re.split(r"(?m)(?=^- id:)", raw)
    kept: list[str] = []
    removed: list[tuple[str, str]] = []
    for block in blocks:
        if not block:
            continue
        match = re.match(r"^- id:\s*['\"]?([^'\"\n]+)", block)
        automation_id = match.group(1).strip() if match else ""
        alias_match = re.search(r"(?m)^  alias:\s*(.+)$", block)
        alias = alias_match.group(1).strip() if alias_match else ""
        if automation_id in LEGACY_IDS or automation_id.startswith("energy_optimizer_"):
            removed.append((automation_id, alias))
        else:
            kept.append(block)
    rendered = "".join(kept)
    parsed = yaml.safe_load(rendered)
    assert isinstance(parsed, list)
    remaining_ids = {str(item.get("id")) for item in parsed}
    assert not (LEGACY_IDS & remaining_ids)
    assert not any(item.startswith("energy_optimizer_") for item in remaining_ids)
    atomic_replace(path, rendered)
    return removed


def disable_saj_entry(path: Path) -> str:
    config = json.loads(path.read_text(encoding="utf-8"))
    targets = [item for item in config["data"]["entries"] if item.get("domain") == "saj_h2_modbus"]
    assert len(targets) == 1, targets
    targets[0]["disabled_by"] = "user"
    atomic_replace(path, json.dumps(config, ensure_ascii=False, separators=(",", ":")))
    return str(targets[0]["entry_id"])


def remove_orphaned_automation_entities(path: Path) -> list[str]:
    """Remove UI registry remnants after their YAML definitions are retired."""
    registry = json.loads(path.read_text(encoding="utf-8"))
    entities = registry["data"]["entities"]
    removed = [
        item["entity_id"]
        for item in entities
        if item.get("entity_id", "").startswith("automation.energy_optimizer_")
    ]
    registry["data"]["entities"] = [
        item
        for item in entities
        if not item.get("entity_id", "").startswith("automation.energy_optimizer_")
    ]
    atomic_replace(path, json.dumps(registry, ensure_ascii=False, separators=(",", ":")))
    return removed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--automations", type=Path, default=Path("/config/automations.yaml"))
    parser.add_argument("--config-entries", type=Path, default=Path("/config/.storage/core.config_entries"))
    parser.add_argument(
        "--entity-registry",
        type=Path,
        default=Path("/config/.storage/core.entity_registry"),
    )
    parser.add_argument(
        "--disable-saj",
        action="store_true",
        help="also disable the SAJ integration; omitted by default",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("refusing mutation without --apply")
    removed = retire_automations(args.automations)
    orphaned = remove_orphaned_automation_entities(args.entity_registry)
    entry_id = disable_saj_entry(args.config_entries) if args.disable_saj else None
    print(json.dumps({
        "removed_automations": removed,
        "removed_orphaned_entities": orphaned,
        "disabled_saj_entry": entry_id,
    }))


if __name__ == "__main__":
    main()
