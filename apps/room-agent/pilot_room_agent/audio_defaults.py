from __future__ import annotations

import argparse
import re
import subprocess
import time

from .config import load_settings


NODE_LINE = re.compile(r"\*?\s*(\d+)\.\s+(\S+)")


def parse_node_ids(status: str) -> dict[str, int]:
    nodes: dict[str, int] = {}
    for line in status.splitlines():
        match = NODE_LINE.search(line)
        if match:
            nodes[match.group(2)] = int(match.group(1))
    return nodes


def _wpctl(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["wpctl", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


def apply_defaults(config_path: str, attempts: int = 30, delay: float = 1.0) -> None:
    settings = load_settings(config_path)
    requested = [node for node in (settings.microphone_node, settings.speaker_node) if node]
    if not requested:
        raise RuntimeError("no microphone_node or speaker_node is configured")

    last_detail = ""
    for attempt in range(1, attempts + 1):
        status = _wpctl("status", "--name")
        last_detail = (status.stdout or status.stderr).strip()
        if status.returncode == 0:
            nodes = parse_node_ids(status.stdout)
            missing = [node for node in requested if node not in nodes]
            if not missing:
                for node in requested:
                    result = _wpctl("set-default", str(nodes[node]))
                    if result.returncode != 0:
                        raise RuntimeError(result.stderr.strip() or f"wpctl failed for {node}")
                print("Pilot audio defaults applied: " + ", ".join(requested), flush=True)
                return
            last_detail = "missing nodes: " + ", ".join(missing)
        if attempt < attempts:
            time.sleep(delay)
    raise RuntimeError(f"audio defaults unavailable after {attempts} attempts: {last_detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply configured Pilot PipeWire defaults")
    parser.add_argument("--config", default="/etc/pilot/room.toml")
    parser.add_argument("--attempts", type=int, default=30)
    args = parser.parse_args()
    apply_defaults(args.config, attempts=args.attempts)


if __name__ == "__main__":
    main()
