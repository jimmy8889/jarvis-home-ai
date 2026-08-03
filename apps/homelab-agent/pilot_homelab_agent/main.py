from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _number(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cpu_times() -> tuple[int, int]:
    fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    values = [int(value) for value in fields]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_ratio(sample_seconds: float = 0.25) -> float | None:
    before_total, before_idle = _cpu_times()
    time.sleep(sample_seconds)
    after_total, after_idle = _cpu_times()
    total = after_total - before_total
    if total <= 0:
        return None
    busy = total - (after_idle - before_idle)
    return max(0.0, min(busy / total, 1.0))


def memory() -> tuple[int | None, int | None]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0]) * 1024
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    return (total - available if total is not None and available is not None else None, total)


def temperatures() -> list[dict[str, Any]]:
    readings: list[dict[str, Any]] = []
    for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        chip = (hwmon / "name").read_text().strip() if (hwmon / "name").exists() else hwmon.name
        for source in sorted(hwmon.glob("temp*_input")):
            prefix = source.name.removesuffix("_input")
            label_file = hwmon / f"{prefix}_label"
            label = label_file.read_text().strip() if label_file.exists() else prefix
            raw = _number(source.read_text().strip())
            if raw is None:
                continue
            value = raw / 1000 if abs(raw) > 250 else raw
            if -20 <= value <= 150:
                readings.append(
                    {
                        "id": f"{chip}:{label}",
                        "label": f"{chip} {label}",
                        "temperature_c": round(value, 1),
                    }
                )
    return readings


def gpus() -> list[dict[str, Any]]:
    if shutil.which("nvidia-smi") is None:
        return []
    fields = [
        "index",
        "name",
        "utilization.gpu",
        "memory.used",
        "memory.total",
        "temperature.gpu",
        "power.draw",
    ]
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    readings = []
    for line in result.stdout.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != len(fields):
            continue
        used_mib = _number(values[3])
        total_mib = _number(values[4])
        utilization = _number(values[2])
        readings.append(
            {
                "index": int(values[0]),
                "name": values[1],
                "utilization_ratio": utilization / 100 if utilization is not None else None,
                "memory_used_bytes": int(used_mib * 1024 * 1024) if used_mib is not None else None,
                "memory_total_bytes": int(total_mib * 1024 * 1024) if total_mib is not None else None,
                "temperature_c": _number(values[5]),
                "power_watts": _number(values[6]),
            }
        )
    return readings


def snapshot(hostname: str | None = None) -> dict[str, Any]:
    memory_used, memory_total = memory()
    disk = shutil.disk_usage("/")
    return {
        "hostname": hostname or socket.gethostname(),
        "role": "compute",
        "cpu_ratio": cpu_ratio(),
        "load_average": list(os.getloadavg()),
        "memory_used_bytes": memory_used,
        "memory_total_bytes": memory_total,
        "root_used_bytes": disk.used,
        "root_total_bytes": disk.total,
        "uptime_seconds": int(float(Path("/proc/uptime").read_text().split()[0])),
        "temperatures": temperatures(),
        "gpus": gpus(),
    }


def post(core_url: str, device_id: str, token: str, payload: dict[str, Any]) -> None:
    request = Request(
        f"{core_url.rstrip('/')}/v1/devices/{device_id}/homelab/telemetry",
        data=json.dumps(payload, separators=(",", ":")).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        if response.status != 202:
            raise RuntimeError(f"Pilot Core returned HTTP {response.status}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Publish read-only host telemetry to Pilot Core")
    result.add_argument("--core-url", required=True)
    result.add_argument("--device-id", required=True)
    result.add_argument("--token-file", required=True)
    result.add_argument("--hostname")
    result.add_argument("--interval", type=max_interval, default=15)
    result.add_argument("--once", action="store_true")
    return result


def max_interval(raw: str) -> int:
    value = int(raw)
    if value < 5 or value > 300:
        raise argparse.ArgumentTypeError("interval must be between 5 and 300 seconds")
    return value


def main() -> None:
    arguments = parser().parse_args()
    token = Path(arguments.token_file).read_text().strip()
    if not token:
        raise SystemExit("device token is empty")
    while True:
        started = time.monotonic()
        try:
            post(
                arguments.core_url,
                arguments.device_id,
                token,
                snapshot(arguments.hostname),
            )
        except (HTTPError, URLError, OSError, RuntimeError) as error:
            print(f"telemetry publish failed: {error}", flush=True)
        if arguments.once:
            return
        time.sleep(max(1, arguments.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
