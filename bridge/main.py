"""Serve the local UI and the contract WebSocket on port 8765."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


async def index(request: web.Request) -> web.StreamResponse:
    """Serve the patient page, or upgrade to a WebSocket at the same URL."""
    socket = web.WebSocketResponse(heartbeat=30)
    if not socket.can_prepare(request).ok:
        return web.FileResponse(WEB_ROOT / "index.html")

    # Only the local page may open a browser connection. Non-browser local
    # clients may omit Origin, which is useful for integration tests.
    if request.headers.get("Origin") not in (
        None,
        "http://localhost:8765",
        "http://127.0.0.1:8765",
        "http://[::1]:8765",
    ):
        raise web.HTTPForbidden(text="Open the page from the local bridge.")

    await socket.prepare(request)
    await socket.send_json(
        {
            "type": "state",
            "mode": "idle",
            "highlight_index": 0,
            "category": None,
            "phrases": [],
        }
    )
    async for _message in socket:
        # Input handling belongs to the future state machine. Do not echo
        # arbitrary messages or treat them as selections.
        pass
    return socket


async def asset(request: web.Request) -> web.FileResponse:
    """Serve only explicitly routed public assets, never the repo root."""
    return web.FileResponse(WEB_ROOT / request.match_info["name"])


def create_app() -> web.Application:
    """Build the bridge server without starting it (also used by tests)."""
    app = web.Application()
    app.router.add_get("/", index)
    # Fixed filenames avoid exposing profiles, logs, secrets, or source files.
    for name in ("index.html", "dashboard.html", "styles.css", "bridge.js"):
        app.router.add_get("/{name:" + name.replace(".", r"\.") + "}", asset)
    return app


def main() -> None:
    print("Patient page: http://localhost:8765")
    print("WebSocket: ws://localhost:8765")
    web.run_app(create_app(), host="localhost", port=8765)


if __name__ == "__main__":
    main()
