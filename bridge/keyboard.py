"""Keyboard fallback. CONTRACT.md section 3.

Space is TAP. Enter held for hold_ms is HOLD. Enter still held at 3 seconds
is HOLD_LONG, matching the Pico. Shift+Enter is SELECT. Esc returns to idle.
The bridge feeds these events to the same state machine as serial events.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

HOLD_LONG_MS = 3000
_SHIFT_NAMES = frozenset({"shift", "shift_l", "shift_r"})
_NAMED_KEYS = frozenset({"space", "enter", "esc"})
Schedule = Callable[[float, Callable[[], None]], Callable[[], None]]


def key_name(key: object) -> str | None:
    """Map one pynput key to space, enter, esc, or shift."""
    if key is None:
        return None
    name = getattr(key, "name", None)
    if name in _SHIFT_NAMES:
        return "shift"
    if name in _NAMED_KEYS:
        return name
    if getattr(key, "char", None) == " ":
        return "space"
    return None


def _thread_schedule(delay: float, callback: Callable[[], None]) -> Callable[[], None]:
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()
    return timer.cancel


class KeyboardLink:
    """Listen for the contract keys and queue TAP, HOLD, SELECT, or RESET."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[tuple[str, str]],
        hold_ms: int,
        *,
        schedule: Schedule | None = None,
    ) -> None:
        self._check_hold_ms(hold_ms)
        self._loop = loop
        self._queue = queue
        self._hold_ms = hold_ms
        self._schedule = schedule or _thread_schedule
        self._lock = threading.Lock()
        self._shift_down = False
        self._space_down = False
        self._enter_down = False
        self._enter_select = False
        self._hold_sent = False
        self._long_sent = False
        self._cancels: list[Callable[[], None]] = []
        self._listener: object | None = None

    def start(self) -> None:
        """Start the global key listener. Failure leaves the bridge running."""
        if self._listener is not None:
            return
        try:
            from pynput import keyboard
        except Exception:
            logger.warning("keyboard listener unavailable")
            return

        def on_press(key: object) -> None:
            self._safe(key, self.handle_press)

        def on_release(key: object) -> None:
            self._safe(key, self.handle_release)

        try:
            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            listener.daemon = True
            listener.start()
        except Exception:
            logger.warning("keyboard listener did not start")
            return
        self._listener = listener

    def close(self) -> None:
        """Stop the listener and any pending Enter hold."""
        with self._lock:
            self._cancel_timer()
        listener = self._listener
        self._listener = None
        if listener is not None:
            stop = getattr(listener, "stop", None)
            if stop is not None:
                try:
                    stop()
                except Exception:
                    logger.warning("keyboard listener did not stop")

    def set_hold_ms(self, hold_ms: int) -> None:
        """Use a new Enter hold time on the next press."""
        self._check_hold_ms(hold_ms)
        with self._lock:
            self._hold_ms = hold_ms

    def handle_press(self, name: str) -> None:
        """Apply one key-down. Repeats while the key stays down are ignored."""
        emit: str | None = None
        with self._lock:
            if name == "shift":
                self._shift_down = True
            elif name == "esc":
                emit = "RESET"
            elif name == "space":
                if not self._space_down:
                    self._space_down = True
                    emit = "TAP"
            elif name == "enter":
                if not self._enter_down:
                    self._enter_down = True
                    self._hold_sent = False
                    self._long_sent = False
                    if self._shift_down:
                        self._enter_select = True
                        emit = "SELECT"
                    else:
                        self._enter_select = False
                        self._cancel_timer()
                        self._arm(self._hold_ms / 1000, self._fire_hold)
                        if self._hold_ms < HOLD_LONG_MS:
                            self._arm(HOLD_LONG_MS / 1000, self._fire_long)
        if emit is not None:
            self._emit(emit)

    def handle_release(self, name: str) -> None:
        """Apply one key-up. A short Enter does not become a TAP."""
        with self._lock:
            if name == "shift":
                self._shift_down = False
            elif name == "space":
                self._space_down = False
            elif name == "enter":
                self._enter_down = False
                self._enter_select = False
                self._cancel_timer()

    def _fire_hold(self) -> None:
        emit = False
        with self._lock:
            if self._enter_down and not self._enter_select and not self._hold_sent:
                self._hold_sent = True
                emit = True
        if emit:
            self._emit("HOLD")

    def _fire_long(self) -> None:
        emit = False
        with self._lock:
            if self._enter_down and not self._enter_select and not self._long_sent:
                self._long_sent = True
                emit = True
        if emit:
            self._emit("HOLD_LONG")

    def _arm(self, delay: float, callback: Callable[[], None]) -> None:
        self._cancels.append(self._schedule(delay, callback))

    def _cancel_timer(self) -> None:
        cancels = self._cancels
        self._cancels = []
        for cancel in cancels:
            cancel()

    def _emit(self, event: str) -> None:
        try:
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait,
                (event, "keyboard"),
            )
        except RuntimeError:
            logger.warning("dropped keyboard event; event loop is closed")

    def _safe(self, key: object, handler: Callable[[str], None]) -> None:
        try:
            name = key_name(key)
            if name is not None:
                handler(name)
        except Exception:
            logger.warning("keyboard event failed")

    @staticmethod
    def _check_hold_ms(hold_ms: int) -> None:
        if isinstance(hold_ms, bool) or not isinstance(hold_ms, int) or hold_ms <= 0:
            raise ValueError("hold_ms must be a positive integer")
