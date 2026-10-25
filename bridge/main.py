"""Serve the local UI and run the tap state machine on port 8765."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from aiohttp import web

from bridge.commands import cfg_hold_ms
from bridge.keyboard import KeyboardLink
from bridge.log import utc_now
from bridge.phrases import load_phrases
from bridge.profile import Profile, load_profile
from bridge.serial_link import SerialLink
from bridge.state import Effect, Machine, NurseCall, Selected, State

logger = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
LOOP_TICK_S = 0.1
LED_RESEND_S = 5.0


class CommandSink(Protocol):
    def send(self, command: str) -> None: ...

    def close(self) -> None: ...


class KeyboardSink(Protocol):
    def set_hold_ms(self, hold_ms: int) -> None: ...

    def close(self) -> None: ...


@dataclass
class Runtime:
    """Mutable bridge state. Kept off the app mapping so it can change later."""

    profile: Profile
    machine: Machine
    sockets: set[web.WebSocketResponse] = field(default_factory=set)
    events: asyncio.Queue[tuple[str, str]] = field(default_factory=asyncio.Queue)
    publish_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_led: str = "LED idle"
    last_state: State | None = None
    last_state_change: float = 0.0
    last_led_send: float = 0.0
    serial: CommandSink | None = None
    keyboard: KeyboardSink | None = None
    runner: asyncio.Task[None] | None = None
    inputs_enabled: bool = False
    profile_path: Path | None = None


RUNTIME: web.AppKey[Runtime] = web.AppKey("runtime", Runtime)


def led_resend_due(
    now: float,
    last_state_change: float,
    last_led_send: float,
    *,
    interval: float = LED_RESEND_S,
) -> bool:
    """True when the LED command should be repeated. CONTRACT.md section 2."""
    quiet = now - last_state_change
    since_send = now - last_led_send
    return quiet >= interval and since_send >= interval


def copy_state(state: State) -> State:
    """Copy a state message so a caller cannot change the stored snapshot."""
    return {
        "type": state["type"],
        "mode": state["mode"],
        "highlight_index": state["highlight_index"],
        "category": state["category"],
        "phrases": [
            {"id": item["id"], "text": item["text"]} for item in state["phrases"]
        ],
    }


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
    runtime = request.app[RUNTIME]
    try:
        async with runtime.publish_lock:
            runtime.sockets.add(socket)
            await socket.send_json(runtime.machine.snapshot())
        async for _message in socket:
            # UI select messages are not applied yet. Sensor and keyboard
            # events enter through the serial link and the keyboard listener.
            pass
    finally:
        runtime.sockets.discard(socket)
    return socket


async def asset(request: web.Request) -> web.FileResponse:
    """Serve only explicitly routed public assets, never the repo root."""
    return web.FileResponse(WEB_ROOT / request.match_info["name"])


def create_app() -> web.Application:
    """Build the bridge server without starting serial or the keyboard."""
    profile = load_profile()
    catalog = load_phrases(language=profile["language"])
    machine = Machine(catalog)
    now = time.monotonic()
    runtime = Runtime(
        profile=profile,
        machine=machine,
        last_state=machine.snapshot(),
        last_state_change=now,
        last_led_send=now,
    )
    app = web.Application()
    app[RUNTIME] = runtime
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/", index)
    # Fixed filenames avoid exposing profiles, logs, secrets, or source files.
    for name in ("index.html", "dashboard.html", "styles.css", "bridge.js"):
        app.router.add_get("/{name:" + name.replace(".", r"\.") + "}", asset)
    return app


async def on_startup(app: web.Application) -> None:
    """Run the tick loop. Serial starts only when main() asks for it."""
    runtime = app[RUNTIME]
    runtime.runner = asyncio.create_task(run_bridge(app), name="bridge-loop")
    if not runtime.inputs_enabled:
        return
    loop = asyncio.get_running_loop()
    link = SerialLink(
        loop,
        runtime.events,
        on_connect=lambda: on_serial_connect(app),
    )
    runtime.serial = link
    link.start()
    keyboard = KeyboardLink(loop, runtime.events, runtime.profile["hold_ms"])
    runtime.keyboard = keyboard
    keyboard.start()


async def on_cleanup(app: web.Application) -> None:
    """Stop the tick loop and release the serial port."""
    runtime = app[RUNTIME]
    runner = runtime.runner
    if runner is not None:
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner
    if runtime.serial is not None:
        await asyncio.to_thread(runtime.serial.close)
    if runtime.keyboard is not None:
        runtime.keyboard.close()


def on_serial_connect(app: web.Application) -> None:
    """Send the profile hold time and the current lamp when the Pico opens."""
    send_hold_config(app)
    runtime = app[RUNTIME]
    send_led(runtime, runtime.last_led, time.monotonic())


def send_hold_config(app: web.Application) -> None:
    """Send CFG hold_ms from the profile. An edit applies on the next session."""
    runtime = app[RUNTIME]
    try:
        profile = load_profile(runtime.profile_path)
    except Exception:
        logger.warning("profile was not reloaded; keeping the previous hold time")
        profile = runtime.profile
    else:
        runtime.profile = profile
        if runtime.keyboard is not None:
            runtime.keyboard.set_hold_ms(profile["hold_ms"])
    if runtime.serial is not None:
        runtime.serial.send(cfg_hold_ms(profile["hold_ms"]))


def send_led(runtime: Runtime, command: str, now: float) -> None:
    """Remember the lamp command and write it if a port is open."""
    runtime.last_led = command
    runtime.last_led_send = now
    if runtime.serial is not None:
        runtime.serial.send(command)


async def publish(
    app: web.Application,
    state: State,
    effects: list[Effect],
    now: float,
) -> None:
    """Log a choice, send LED commands, and broadcast a changed state."""
    runtime = app[RUNTIME]
    async with runtime.publish_lock:
        for effect in effects:
            if isinstance(effect, Selected):
                logger.info(
                    "selected phrase_id=%s source=%s",
                    effect.phrase_id,
                    effect.source,
                )
            elif isinstance(effect, NurseCall):
                logger.info(
                    "nurse_call phrase_id=%s source=%s",
                    effect.phrase_id,
                    effect.source,
                )
                await broadcast(
                    runtime,
                    {
                        "type": "alert",
                        "kind": "nurse_call",
                        "phrase_id": effect.phrase_id,
                        "timestamp": utc_now(),
                    },
                )
            elif isinstance(effect, str):
                send_led(runtime, effect, now)
        if state != runtime.last_state:
            runtime.last_state = copy_state(state)
            runtime.last_state_change = now
            logger.info(
                "state mode=%s highlight=%s category=%s",
                state["mode"],
                state["highlight_index"],
                state["category"],
            )
            await broadcast(runtime, runtime.last_state)


async def broadcast(runtime: Runtime, payload: dict[str, object]) -> None:
    """Send one JSON message to every open socket."""
    dead: list[web.WebSocketResponse] = []
    for socket in list(runtime.sockets):
        if socket.closed:
            dead.append(socket)
            continue
        try:
            await socket.send_json(payload)
        except Exception:
            logger.warning("dropped a socket message")
            dead.append(socket)
    for socket in dead:
        runtime.sockets.discard(socket)


async def handle_item(
    app: web.Application,
    item: tuple[str, str],
    now: float,
) -> None:
    """Run one serial or keyboard event through the shared machine."""
    event, source = item
    runtime = app[RUNTIME]
    machine = runtime.machine
    previous = machine.snapshot()["mode"]
    if event == "RESET":
        state, effects = machine.reset()
    else:
        state, effects = machine.handle(event, source, now)
    if previous == "idle" and state["mode"] == "category":
        send_hold_config(app)
    await publish(app, state, effects, now)


async def run_once(app: web.Application) -> None:
    """Apply at most one queued event, then the idle and lamp timers."""
    runtime = app[RUNTIME]
    try:
        item = await asyncio.wait_for(runtime.events.get(), timeout=LOOP_TICK_S)
    except TimeoutError:
        item = None
    now = time.monotonic()
    if item is not None:
        await handle_item(app, item, now)
        now = time.monotonic()
    state, effects = runtime.machine.tick(now)
    await publish(app, state, effects, now)
    if led_resend_due(now, runtime.last_state_change, runtime.last_led_send):
        send_led(runtime, runtime.last_led, now)


async def run_bridge(app: web.Application) -> None:
    """Keep the state machine moving until the app shuts down."""
    while True:
        try:
            await run_once(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("bridge loop failed")
            await asyncio.sleep(LOOP_TICK_S)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    app = create_app()
    app[RUNTIME].inputs_enabled = True
    print("Patient page: http://localhost:8765")
    print("WebSocket: ws://localhost:8765")
    web.run_app(app, host="localhost", port=8765)


if __name__ == "__main__":
    main()
