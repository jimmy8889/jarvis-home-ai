from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp
from aiohttp import web


CORE = "http://127.0.0.1:8788"
WEB_ROOT = Path(__file__).with_name("web")


async def index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_ROOT / "index.html")


async def asset(request: web.Request) -> web.FileResponse:
    name = request.match_info["name"]
    target = WEB_ROOT / "assets" / name
    if name != Path(name).name or target.suffix.lower() != ".png" or not target.is_file():
        raise web.HTTPNotFound(text="dashboard asset not found")
    return web.FileResponse(target)


async def proxy(request: web.Request) -> web.StreamResponse:
    target = CORE + request.path_qs
    headers = {key: value for key, value in request.headers.items() if key.lower() not in {"host", "content-length"}}
    # The core listener is local to the LXC and otherwise sees every proxied
    # request as 127.0.0.1. Overwrite (never trust) this header so sensitive
    # vehicle controls can allow the configured Home Assistant host only.
    headers["X-Energy-Manager-Client-IP"] = request.remote or "unknown"
    body = await request.read()
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=5)
    session: aiohttp.ClientSession = request.app["session"]
    async with session.request(request.method, target, headers=headers, data=body, timeout=timeout) as response:
        outgoing = web.StreamResponse(status=response.status, headers={key: value for key, value in response.headers.items() if key.lower() not in {"content-length", "transfer-encoding", "connection"}})
        await outgoing.prepare(request)
        try:
            async for chunk in response.content.iter_chunked(8192):
                await outgoing.write(chunk)
            await outgoing.write_eof()
        except (ConnectionResetError, aiohttp.ClientConnectionError):
            # EventSource clients routinely disconnect during navigation or
            # dashboard refresh. That is not a dashboard service failure.
            pass
        return outgoing


async def make_app() -> web.Application:
    app = web.Application()
    app["session"] = aiohttp.ClientSession()
    app.router.add_get("/", index)
    app.router.add_get("/assets/{name}", asset)
    app.router.add_route("*", "/api/{tail:.*}", proxy)
    app.router.add_get("/healthz", proxy)
    app.router.add_get("/readyz", proxy)
    async def cleanup(application: web.Application) -> None:
        await application["session"].close()
    app.on_cleanup.append(cleanup)
    return app


def main() -> None:
    # Do not let an embedded EventSource connection block a dashboard-only
    # service restart. The independent controller continues on port 8788.
    web.run_app(make_app(), host="0.0.0.0", port=8787, shutdown_timeout=3.0)


if __name__ == "__main__":
    main()
