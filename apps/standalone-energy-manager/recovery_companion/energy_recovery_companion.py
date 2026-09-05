#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import struct
import time


STATE = Path(os.getenv("ENERGY_RECOVERY_STATE", "/var/lib/energy-recovery/armed.json"))
SECRET = Path(os.getenv("ENERGY_RECOVERY_SECRET", "/etc/energy-recovery/hmac_secret"))
NUT_HOST = os.getenv("ENERGY_RECOVERY_NUT_HOST", "127.0.0.1")
NUT_PORT = int(os.getenv("ENERGY_RECOVERY_NUT_PORT", "3493"))
UPS_NAME = os.getenv("ENERGY_RECOVERY_UPS", "nutdev1")
LISTEN = os.getenv("ENERGY_RECOVERY_LISTEN", "10.0.1.206")
PORT = int(os.getenv("ENERGY_RECOVERY_PORT", "8766"))
NODES = (
    ("pvedell", "10.0.1.120", "74:86:7a:e2:55:ce"),
    ("pvebackup", "10.0.1.129", "18:c0:4d:1c:47:ce"),
    ("pve3080", "10.0.1.6", "10:ff:e0:37:e8:27"),
)


def verify(timestamp: str, body: bytes, signature: str, now: int | None = None) -> bool:
    try:
        issued = int(timestamp)
        secret = SECRET.read_text(encoding="utf-8").strip().encode()
    except (ValueError, OSError):
        return False
    if abs((now or int(time.time())) - issued) > 60:
        return False
    expected = hmac.new(secret, timestamp.encode() + b"\n" + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def nut_mains_valid() -> bool:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(NUT_HOST, NUT_PORT), 3)
    try:
        writer.write(f"LIST VAR {UPS_NAME}\n".encode())
        await writer.drain()
        values: dict[str, str] = {}
        while True:
            line = (await asyncio.wait_for(reader.readline(), 3)).decode(errors="replace").strip()
            if line == f"END LIST VAR {UPS_NAME}":
                break
            parts = line.split('"')
            head = parts[0].split()
            if len(head) >= 3 and head[0] == "VAR" and len(parts) >= 2:
                values[head[2]] = parts[1]
        status = set(values.get("ups.status", "").split())
        return "OL" in status and float(values.get("input.voltage", "0")) >= 180
    finally:
        writer.close()
        await writer.wait_closed()


def wol(mac: str) -> None:
    raw = bytes.fromhex(mac.replace(":", ""))
    packet = b"\xff" * 6 + raw * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, ("10.0.1.255", 9))


async def responds(host: str) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, 8006), 2)
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def recovery_loop() -> None:
    stable_since: float | None = None
    while True:
        if not STATE.exists():
            stable_since = None
            await asyncio.sleep(5)
            continue
        valid = await nut_mains_valid()
        stable_since = stable_since or time.monotonic() if valid else None
        if stable_since and time.monotonic() - stable_since >= 300:
            record = json.loads(STATE.read_text(encoding="utf-8"))
            for name, host, mac in NODES:
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline and not await responds(host):
                    wol(mac)
                    await asyncio.sleep(10)
                record.setdefault("recovery", {})[name] = "online" if await responds(host) else "timeout"
                STATE.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
            STATE.unlink(missing_ok=True)
            stable_since = None
        await asyncio.sleep(5)


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        lines = header.decode(errors="replace").split("\r\n")
        method, path, _ = lines[0].split()
        headers = {key.lower(): value.strip() for key, value in (line.split(":", 1) for line in lines[1:] if ":" in line)}
        length = int(headers.get("content-length", "0"))
        body = await asyncio.wait_for(reader.readexactly(length), 5) if length else b""
        if method != "POST" or path != "/v1/arm" or not verify(headers.get("x-energy-timestamp", ""), body, headers.get("x-energy-signature", "")):
            status, payload = "403 Forbidden", {"error": "invalid signed request"}
        else:
            epoch = str(json.loads(body).get("epoch", ""))
            if not epoch:
                raise ValueError("missing epoch")
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({"epoch": epoch, "armed_at": time.time()}, separators=(",", ":")), encoding="utf-8")
            status, payload = "200 OK", {"armed": True, "epoch": epoch}
    except Exception as exc:
        status, payload = "400 Bad Request", {"error": type(exc).__name__}
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    writer.write(f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(encoded)}\r\nConnection: close\r\n\r\n".encode() + encoded)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def main() -> None:
    server = await asyncio.start_server(handle, LISTEN, PORT)
    async with server:
        await asyncio.gather(server.serve_forever(), recovery_loop())


if __name__ == "__main__":
    asyncio.run(main())
