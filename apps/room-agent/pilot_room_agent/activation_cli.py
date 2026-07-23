from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .activation import ActivationGate, configuration_fingerprint
from .config import Settings, load_settings


REQUIRED_CHECKS = {
    "silent_validation",
    "microphone_capture",
    "speaker_playback",
    "simultaneous_input_output",
}


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_gid = path.parent.stat().st_gid
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temporary, 0o640)
        os.chown(temporary, -1, parent_gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_receipt(path: Path, settings: Settings, max_age: int) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        receipt = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("acceptance receipt is unreadable or invalid") from error
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
        raise ValueError("acceptance receipt schema is invalid")
    if receipt.get("room_id") != settings.room_id:
        raise ValueError("acceptance receipt belongs to a different room")
    for field, expected in (
        ("capture_device", settings.capture_alsa_device),
        ("playback_device", settings.playback_alsa_device),
        ("speaker_node", settings.speaker_node),
    ):
        if receipt.get(field) != expected:
            raise ValueError(f"acceptance receipt {field} no longer matches")
    checks = receipt.get("checks")
    if (
        not isinstance(checks, list)
        or not all(isinstance(item, str) for item in checks)
        or not REQUIRED_CHECKS.issubset(set(checks))
    ):
        raise ValueError("acceptance receipt is missing required successful checks")
    try:
        created = datetime.fromisoformat(str(receipt["created_at"]))
    except (KeyError, ValueError) as error:
        raise ValueError("acceptance receipt timestamp is invalid") from error
    if created.tzinfo is None:
        raise ValueError("acceptance receipt timestamp must include a timezone")
    age = (datetime.now(UTC) - created.astimezone(UTC)).total_seconds()
    if age < -300 or age > max_age:
        raise ValueError("acceptance receipt is stale")
    receipt["sha256"] = sha256(raw).hexdigest()
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect, arm, or disarm supervised room audio activation"
    )
    parser.add_argument("--config", default="/etc/pilot/room.toml")
    parser.add_argument("--state-path")
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("status")

    arm = subparsers.add_parser("arm")
    arm.add_argument("--receipt", required=True)
    arm.add_argument("--observer", required=True)
    arm.add_argument("--confirm-room", required=True)
    arm.add_argument("--max-receipt-age", type=int, default=3600)
    arm.add_argument("--yes", action="store_true")

    disarm = subparsers.add_parser("disarm")
    disarm.add_argument("--observer", required=True)
    disarm.add_argument("--yes", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings(args.config)
    if args.state_path:
        settings = Settings(
            **{
                **settings.__dict__,
                "audio_activation_state_path": args.state_path,
            }
        )
    path = Path(settings.audio_activation_state_path)
    if args.action == "status":
        status = ActivationGate(settings).status()
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0 if status["allowed"] else 1

    if not args.yes:
        raise SystemExit("refusing to change activation without --yes")
    observer = args.observer.strip()
    if not observer or len(observer) > 200:
        raise SystemExit("observer must be between 1 and 200 characters")

    now = datetime.now(UTC).isoformat()
    if args.action == "disarm":
        _write_state(
            path,
            {
                "schema_version": 1,
                "armed": False,
                "room_id": settings.room_id,
                "disarmed_at": now,
                "observer": observer,
            },
        )
        print(f"Room audio disarmed for {settings.room_id}.")
        return 0

    if args.confirm_room != settings.room_id:
        raise SystemExit("--confirm-room must exactly match the configured room")
    if not 60 <= args.max_receipt_age <= 86_400:
        raise SystemExit("--max-receipt-age must be between 60 and 86400")
    try:
        receipt = _load_receipt(
            Path(args.receipt), settings, args.max_receipt_age
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    _write_state(
        path,
        {
            "schema_version": 1,
            "armed": True,
            "room_id": settings.room_id,
            "accepted_at": now,
            "observer": observer,
            "acceptance_receipt_sha256": receipt["sha256"],
            "configuration_fingerprint": configuration_fingerprint(settings),
        },
    )
    print(f"Room audio armed for {settings.room_id} after supervised acceptance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
