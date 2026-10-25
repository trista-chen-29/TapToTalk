"""Keyboard keys produce the same events as the Pico."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable
from types import SimpleNamespace

from bridge.keyboard import HOLD_LONG_MS, KeyboardLink, key_name
from bridge.phrases import load_phrases
from bridge.state import Machine

CATALOG = load_phrases()


class KeyNameTests(unittest.TestCase):
    def test_contract_keys(self) -> None:
        self.assertEqual(key_name(SimpleNamespace(name="space", char=None)), "space")
        self.assertEqual(key_name(SimpleNamespace(name=None, char=" ")), "space")
        self.assertEqual(key_name(SimpleNamespace(name="enter", char=None)), "enter")
        self.assertEqual(key_name(SimpleNamespace(name="esc", char=None)), "esc")
        self.assertEqual(key_name(SimpleNamespace(name="shift", char=None)), "shift")
        self.assertEqual(key_name(SimpleNamespace(name="shift_r", char=None)), "shift")
        self.assertIsNone(key_name(SimpleNamespace(name="a", char="a")))
        self.assertIsNone(key_name(None))


class KeyboardEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.pending: list[dict[str, object]] = []

    async def asyncSetUp(self) -> None:
        self.queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self.link = KeyboardLink(
            asyncio.get_running_loop(),
            self.queue,
            1000,
            schedule=self._schedule,
        )

    def _schedule(
        self,
        delay: float,
        callback: Callable[[], None],
    ) -> Callable[[], None]:
        job: dict[str, object] = {
            "delay": delay,
            "callback": callback,
            "cancelled": False,
        }
        self.pending.append(job)

        def cancel() -> None:
            job["cancelled"] = True

        return cancel

    def _fire(self, index: int = -1) -> None:
        job = self.pending[index]
        if not job["cancelled"]:
            callback = job["callback"]
            assert callable(callback)
            callback()

    async def test_space_is_tap_once_per_press(self) -> None:
        self.link.handle_press("space")
        self.link.handle_press("space")
        await asyncio.sleep(0)
        self.assertEqual(self.queue.get_nowait(), ("TAP", "keyboard"))
        self.assertTrue(self.queue.empty())
        self.link.handle_release("space")
        self.link.handle_press("space")
        await asyncio.sleep(0)
        self.assertEqual(self.queue.get_nowait(), ("TAP", "keyboard"))

    async def test_enter_held_for_hold_ms_is_hold(self) -> None:
        self.link.handle_press("enter")
        self.assertEqual(
            [job["delay"] for job in self.pending],
            [1.0, HOLD_LONG_MS / 1000],
        )
        await asyncio.sleep(0)
        self.assertTrue(self.queue.empty())
        self._fire(0)
        await asyncio.sleep(0)
        self.assertEqual(self.queue.get_nowait(), ("HOLD", "keyboard"))
        self._fire(1)
        await asyncio.sleep(0)
        self.assertEqual(self.queue.get_nowait(), ("HOLD_LONG", "keyboard"))

    async def test_short_enter_is_not_a_tap(self) -> None:
        self.link.handle_press("enter")
        self.link.handle_release("enter")
        self._fire(0)
        self._fire(1)
        await asyncio.sleep(0)
        self.assertTrue(self.queue.empty())

    async def test_shift_enter_is_select(self) -> None:
        self.link.handle_press("shift")
        self.link.handle_press("enter")
        await asyncio.sleep(0)
        self.assertEqual(self.queue.get_nowait(), ("SELECT", "keyboard"))
        self.assertEqual(self.pending, [])

    async def test_esc_returns_to_idle_event(self) -> None:
        self.link.handle_press("esc")
        await asyncio.sleep(0)
        self.assertEqual(self.queue.get_nowait(), ("RESET", "keyboard"))

    async def test_new_hold_time_applies_to_the_next_press(self) -> None:
        self.link.set_hold_ms(250)
        self.link.handle_press("enter")
        self.assertEqual(
            [job["delay"] for job in self.pending],
            [0.25, HOLD_LONG_MS / 1000],
        )

    def test_keyboard_events_match_serial_state(self) -> None:
        serial = Machine(CATALOG)
        keys = Machine(CATALOG)
        now = 0.0
        for event in ("TAP", "TAP", "HOLD", "TAP", "SELECT"):
            serial_state, serial_effects = serial.handle(event, "tap", now)
            key_state, key_effects = keys.handle(event, "keyboard", now)
            self.assertEqual(serial_state, key_state)
            self.assertEqual(
                [item for item in serial_effects if isinstance(item, str)],
                [item for item in key_effects if isinstance(item, str)],
            )
            now += 1.0
        self.assertEqual(serial_state["mode"], "idle")
