"""Serve the local UI and run the tap state machine on port 8765."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from aiohttp import WSMsgType, web

from ai.rank import rank_phrases
from ai.speak import speak, speak_category, stop_category_audio
from bridge.commands import cfg_hold_ms
from bridge.keyboard import KeyboardLink
from bridge.log import recent_phrase_ids, save_selection, utc_now
from bridge.phrases import CALL_NURSE_ID, Catalog, Phrase, load_phrases
from bridge.profile import Profile, load_profile
from bridge.serial_link import SerialLink
from bridge.state import Effect, Machine, NurseCall, Selected, State

logger = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
LOOP_TICK_S = 0.1
LED_RESEND_S = 5.0
NURSE_CALL_DEDUPE_S = 60.0
# serial_link.py queues Pico input as "tap". keyboard.py queues "keyboard".
_LOG_SOURCES = {
    "tap": "tap",
    "keyboard": "keyboard",
    "ui": "ui",
    "fixed": "fixed",
}


class CommandSink(Protocol):
    def send(self, command: str) -> None: ...

    def close(self) -> None: ...


Ranker = Callable[[dict[str, object]], list[str]]


@dataclass(frozen=True)
class RankResult:
    """One finished ranking for the category that was highlighted."""

    epoch: int
    category: str
    candidates: tuple[str, ...]
    order: tuple[str, ...]


class KeyboardSink(Protocol):
    def set_hold_ms(self, hold_ms: int) -> None: ...

    def close(self) -> None: ...


@dataclass
class Runtime:
    """Mutable bridge state. Kept off the app mapping so it can change later."""

    profile: Profile
    machine: Machine
    catalog: Catalog
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
    last_nurse_call_at: float | None = None
    last_input_at: float = 0.0
    no_activity_sent: bool = False
    clock: Callable[[], float] = time.monotonic
    rank_phrases: Ranker | None = None
    speak_category: Callable[[str], None] | None = None
    category_epoch: int = 0
    rank_task: asyncio.Task[None] | None = None
    rank_result: RankResult | None = None
    phrase_epoch: int = 0


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
        async for message in socket:
            # Speak and phrase clicks arrive as JSON text. CONTRACT.md section 7.
            if message.type != WSMsgType.TEXT:
                continue
            apply_ui_select(runtime, message.data)
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
        catalog=catalog,
        last_state=machine.snapshot(),
        last_state_change=now,
        last_led_send=now,
        last_input_at=now,
    )
    app = web.Application()
    app[RUNTIME] = runtime
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
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


async def on_shutdown(app: web.Application) -> None:
    """Close browser sockets so shutdown can promptly release the Pico port."""
    await asyncio.gather(
        *(
            socket.close(code=1001, message=b"Bridge stopping")
            for socket in tuple(app[RUNTIME].sockets)
        )
    )


async def on_cleanup(app: web.Application) -> None:
    """Stop the tick loop and release the serial port."""
    runtime = app[RUNTIME]
    stop_category_audio()
    rank_task = cancel_rank(runtime)
    if rank_task is not None:
        with contextlib.suppress(asyncio.CancelledError):
            await rank_task
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


def apply_ui_select(runtime: Runtime, raw: str) -> None:
    """Queue SELECT when the page confirms the highlighted phrase.

    CONTRACT.md section 7. A message that does not match is ignored.
    """
    try:
        _apply_ui_select(runtime, raw)
    except Exception:
        logger.warning("ignored UI select")


def _apply_ui_select(runtime: Runtime, raw: str) -> None:
    """Accept one UI select, or log a warning and leave the queue unchanged."""
    if not isinstance(raw, str):
        logger.warning("ignored UI message that is not JSON")
        return
    try:
        message = json.loads(raw)
    except ValueError:
        logger.warning("ignored UI message that is not JSON")
        return
    if not isinstance(message, dict):
        logger.warning("ignored UI message")
        return
    if message.get("type") != "select" or message.get("source") != "ui":
        logger.warning("ignored UI message")
        return

    phrase_id = message.get("phrase_id")
    if (
        not isinstance(phrase_id, str)
        or _catalog_phrase(runtime.catalog, phrase_id) is None
    ):
        logger.warning("ignored UI select for an unknown phrase")
        return

    snapshot = runtime.machine.snapshot()
    if snapshot["mode"] != "phrase":
        logger.warning("ignored UI select outside phrase mode")
        return
    phrases = snapshot["phrases"]
    index = snapshot["highlight_index"]
    highlighted = phrases[index]["id"] if 0 <= index < len(phrases) else None
    if phrase_id != highlighted:
        logger.warning("ignored UI select for a phrase that is not highlighted")
        return
    runtime.events.put_nowait(("SELECT", "ui"))


def _catalog_phrase(catalog: Catalog, phrase_id: str) -> Phrase | None:
    """Return the catalog entry for one phrase id."""
    for phrase in catalog["phrases"]:
        if phrase["id"] == phrase_id:
            return phrase
    return None


def _log_source(source: str) -> str | None:
    """Map an input source onto tap, keyboard, ui, or fixed."""
    return _LOG_SOURCES.get(source)


async def _speak(phrase_id: str, text: str) -> None:
    """Speak one phrase off the event loop. A failure stays in the log."""
    try:
        await asyncio.to_thread(speak, phrase_id, text)
    except Exception:
        logger.warning("speech failed phrase_id=%s", phrase_id)


async def publish_nurse_call(
    runtime: Runtime, phrase_id: str, source: str, now: float
) -> None:
    """Use the same nurse-call broadcast and dedupe window for every source.

    Called under publish_lock, before selection logging or audio can fail.
    """
    logger.info("nurse_call phrase_id=%s source=%s", phrase_id, source)
    last_sent = runtime.last_nurse_call_at
    if last_sent is not None and now - last_sent < NURSE_CALL_DEDUPE_S:
        return
    runtime.last_nurse_call_at = now
    await broadcast(
        runtime,
        {
            "type": "alert",
            "kind": "nurse_call",
            "phrase_id": phrase_id,
            "timestamp": utc_now(),
        },
    )


async def publish(
    app: web.Application,
    state: State,
    effects: list[Effect],
    now: float,
) -> None:
    """Log a choice, speak it, send LED commands, and broadcast a changed state.

    A nurse call less than 60 seconds after the last broadcast is not sent
    again. The LED effect for that call is still applied.
    """
    runtime = app[RUNTIME]
    async with runtime.publish_lock:
        for effect in effects:
            if isinstance(effect, Selected):
                logger.info(
                    "selected phrase_id=%s source=%s",
                    effect.phrase_id,
                    effect.source,
                )
                phrase = _catalog_phrase(runtime.catalog, effect.phrase_id)
                if phrase is None:
                    logger.warning("selected unknown phrase_id=%s", effect.phrase_id)
                else:
                    source = _log_source(effect.source)
                    if source is None:
                        logger.warning(
                            "selected phrase_id=%s source cannot be logged",
                            effect.phrase_id,
                        )
                    else:
                        if effect.phrase_id == CALL_NURSE_ID:
                            await publish_nurse_call(
                                runtime, effect.phrase_id, effect.source, now
                            )
                        save_selection(effect.phrase_id, phrase["category"], source)
                        await _speak(effect.phrase_id, phrase["text"])
            elif isinstance(effect, NurseCall):
                await publish_nurse_call(runtime, effect.phrase_id, effect.source, now)
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


def time_of_day(hour: int) -> str:
    """Map a local hour to the four labels ranking is allowed to see.

    Morning is 05–11, afternoon is 12–16, evening is 17–20, and night is
    21–04. The clock time itself is not sent.
    """
    if 5 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 16:
        return "afternoon"
    if 17 <= hour <= 20:
        return "evening"
    return "night"


def candidates_for(catalog: Catalog, category: str) -> list[str]:
    """Catalog ids for one category, in file order."""
    return [
        phrase["id"] for phrase in catalog["phrases"] if phrase["category"] == category
    ]


def ranking_context(
    catalog: Catalog,
    category: str,
    candidates: list[str],
) -> dict[str, object]:
    """Build the section 8 object from ids and time of day only."""
    allowed = {phrase["id"] for phrase in catalog["phrases"]}
    try:
        last = recent_phrase_ids(5)
    except Exception:
        logger.warning("could not read recent selections for ranking")
        last = []
    return {
        "time_of_day": time_of_day(datetime.now().hour),
        "category": category,
        "last_selections": [phrase_id for phrase_id in last if phrase_id in allowed][
            :5
        ],
        "candidates": list(candidates),
    }


def call_ranker(
    ranker: Ranker,
    catalog: Catalog,
    category: str,
    candidates: list[str],
) -> list[str]:
    """Run one ranking call. Used from a worker thread."""
    return ranker(ranking_context(catalog, category, candidates))


def _string_list(order: object) -> list[str] | None:
    if not isinstance(order, list) or not all(isinstance(item, str) for item in order):
        return None
    return list(order)


def _silence_rank_cancel(task: asyncio.Task[None]) -> None:
    """Mark a cancelled ranking task retrieved so shutdown stays quiet."""
    try:
        task.exception()
    except (asyncio.CancelledError, asyncio.InvalidStateError):
        return


def cancel_rank(runtime: Runtime) -> asyncio.Task[None] | None:
    """Drop an in-flight ranking so it cannot reorder after the patient moves."""
    runtime.phrase_epoch += 1
    runtime.rank_result = None
    task = runtime.rank_task
    runtime.rank_task = None
    if task is not None and not task.done():
        task.cancel()
        task.add_done_callback(_silence_rank_cancel)
    return task


def start_rank(app: web.Application, category: str, candidates: list[str]) -> None:
    """Rank one highlighted category without waiting for Claude."""
    runtime = app[RUNTIME]
    if runtime.rank_phrases is None or not candidates:
        return
    cancel_rank(runtime)
    epoch = runtime.phrase_epoch
    runtime.rank_task = asyncio.create_task(
        finish_rank(app, epoch, category, list(candidates)),
        name="phrase-rank",
    )


async def finish_rank(
    app: web.Application,
    epoch: int,
    category: str,
    candidates: list[str],
) -> None:
    """Store a ranking, and update an open phrase list that is still on top."""
    runtime = app[RUNTIME]
    ranker = runtime.rank_phrases
    if ranker is None:
        return
    try:
        order = await asyncio.to_thread(
            call_ranker, ranker, runtime.catalog, category, candidates
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("phrase ranking failed; keeping the fixed order")
        return
    ranked = _string_list(order)
    if ranked is None or runtime.phrase_epoch != epoch:
        return
    if ranked == candidates:
        logger.info("ranking kept catalog order category=%s", category)
        return
    if Counter(ranked) != Counter(candidates):
        logger.warning("phrase ranking was not used; keeping the fixed order")
        return
    snapshot = runtime.machine.snapshot()
    if (
        runtime.phrase_epoch != epoch
        or snapshot["category"] != category
        or snapshot["mode"] not in {"category", "phrase"}
    ):
        return
    runtime.rank_result = RankResult(
        epoch=epoch,
        category=category,
        candidates=tuple(candidates),
        order=tuple(ranked),
    )
    logger.info("ranked category=%s order=%s", category, ",".join(ranked))
    if snapshot["mode"] != "phrase":
        return
    state = runtime.machine.reorder_open_phrases(ranked)
    if state is None:
        if snapshot["highlight_index"] == 0:
            logger.warning("phrase ranking was not used; keeping the fixed order")
        return
    await publish(app, state, [], runtime.clock())


def apply_pending_rank(runtime: Runtime, previous: str, state: State) -> State:
    """Use a finished ranking as the first phrase list when it is ready."""
    if previous == "phrase" or state["mode"] != "phrase":
        return state
    result = runtime.rank_result
    category = state["category"]
    if (
        result is None
        or category is None
        or result.epoch != runtime.phrase_epoch
        or result.category != category
    ):
        return state
    current = [item["id"] for item in state["phrases"]]
    if list(result.candidates) != current:
        return state
    ranked = runtime.machine.reorder_open_phrases(list(result.order))
    if ranked is None:
        return state
    return ranked


def follow_category_audio(app: web.Application, before: State, state: State) -> None:
    """Play the saved category name when that highlight changes.

    The clip runs off the event loop. Leaving the category menu drops a play
    that has not started. A live voice call is never used for this.
    """
    runtime = app[RUNTIME]
    player = runtime.speak_category
    if player is None:
        return
    category = state["category"]
    if state["mode"] == "category" and category is not None:
        if before["mode"] == "category" and before["category"] == category:
            return
        runtime.category_epoch += 1
        asyncio.create_task(
            _play_category(app, player, category, runtime.category_epoch),
            name="category-audio",
        )
        return
    if before["mode"] == "category":
        runtime.category_epoch += 1
        stop_category_audio()


async def _play_category(
    app: web.Application,
    player: Callable[[str], None],
    category_id: str,
    epoch: int,
) -> None:
    """Play one category clip unless the highlight has already moved on."""
    runtime = app[RUNTIME]

    def play_if_current() -> None:
        if runtime.category_epoch != epoch:
            return
        player(category_id)

    try:
        await asyncio.to_thread(play_if_current)
    except Exception:
        logger.warning("category audio failed category=%s", category_id)


def follow_rank(app: web.Application, before: State, state: State) -> None:
    """Start ranking for a newly highlighted category, or cancel it."""
    runtime = app[RUNTIME]
    if before["mode"] == "phrase" or (
        state["mode"] == "idle" and before["mode"] != "idle"
    ):
        cancel_rank(runtime)
        return
    category = state["category"]
    if (
        state["mode"] == "category"
        and category is not None
        and category != before["category"]
    ):
        start_rank(app, category, candidates_for(runtime.catalog, category))


async def handle_item(
    app: web.Application,
    item: tuple[str, str],
    now: float,
) -> None:
    """Run one serial or keyboard event through the shared machine."""
    event, source = item
    runtime = app[RUNTIME]
    machine = runtime.machine
    before = machine.snapshot()
    previous = before["mode"]
    runtime.last_input_at = now
    if event == "RESET":
        state, effects = machine.reset()
    else:
        state, effects = machine.handle(event, source, now)
    if previous == "idle" and state["mode"] == "category":
        runtime.no_activity_sent = False
        send_hold_config(app)
    state = apply_pending_rank(runtime, previous, state)
    await publish(app, state, effects, now)
    follow_rank(app, before, state)
    follow_category_audio(app, before, state)


async def publish_no_activity(app: web.Application, now: float) -> None:
    """Broadcast one no-activity alert per idle period.

    The quiet time is profile idle_alert_minutes with no input. A new session
    (idle to category) arms one more alert for the following idle period.
    CONTRACT.md section 7.
    """
    runtime = app[RUNTIME]
    async with runtime.publish_lock:
        if runtime.no_activity_sent:
            return
        if runtime.machine.snapshot()["mode"] != "idle":
            return
        limit_s = runtime.profile["idle_alert_minutes"] * 60
        if now - runtime.last_input_at < limit_s:
            return
        runtime.no_activity_sent = True
        logger.info("no_activity")
        await broadcast(
            runtime,
            {
                "type": "alert",
                "kind": "no_activity",
                "phrase_id": None,
                "timestamp": utc_now(),
            },
        )


async def run_once(app: web.Application) -> None:
    """Apply at most one queued event, then the idle and lamp timers."""
    runtime = app[RUNTIME]
    try:
        item = await asyncio.wait_for(runtime.events.get(), timeout=LOOP_TICK_S)
    except TimeoutError:
        item = None
    now = runtime.clock()
    if item is not None:
        await handle_item(app, item, now)
        now = runtime.clock()
    state, effects = runtime.machine.tick(now)
    await publish(app, state, effects, now)
    await publish_no_activity(app, now)
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
    app[RUNTIME].rank_phrases = rank_phrases
    app[RUNTIME].speak_category = speak_category
    print("Patient page: http://localhost:8765")
    print("WebSocket: ws://localhost:8765")
    web.run_app(app, host="localhost", port=8765)


if __name__ == "__main__":
    main()
