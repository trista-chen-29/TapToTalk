"""UI select messages become SELECT events. CONTRACT.md section 7."""

from __future__ import annotations

import asyncio
import contextlib
import time
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from bridge.main import RUNTIME, create_app


class UiSelectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.save_patch = patch("bridge.main.save_selection", return_value=1)
        self.speak_patch = patch("bridge.main.speak")
        self.save_selection = self.save_patch.start()
        self.speak = self.speak_patch.start()
        self.addCleanup(self.save_patch.stop)
        self.addCleanup(self.speak_patch.stop)
        self.app = create_app()
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        # Stop the tick loop so a queued SELECT stays observable.
        runner = self.app[RUNTIME].runner
        self.assertIsNotNone(runner)
        assert runner is not None
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner

    def _enter_phrase_mode(self) -> str:
        """Open the first category and return the highlighted phrase id."""
        machine = self.app[RUNTIME].machine
        now = time.monotonic()
        machine.handle("HOLD", "keyboard", now)
        state, _effects = machine.handle("SELECT", "keyboard", now)
        self.assertEqual(state["mode"], "phrase")
        phrase_id = state["phrases"][state["highlight_index"]]["id"]
        self.assertEqual(phrase_id, "need_water")
        return phrase_id

    def _queued(self) -> list[tuple[str, str]]:
        events = self.app[RUNTIME].events
        queued: list[tuple[str, str]] = []
        while True:
            try:
                queued.append(events.get_nowait())
            except asyncio.QueueEmpty:
                return queued

    async def test_valid_select_in_phrase_mode_queues_one_select(self) -> None:
        with self.assertNoLogs("bridge.main", level="WARNING"):
            async with self.client.ws_connect("/") as socket:
                initial = await socket.receive_json(timeout=2)
                self.assertEqual(initial["mode"], "idle")
                phrase_id = self._enter_phrase_mode()
                await socket.send_json(
                    {"type": "select", "phrase_id": phrase_id, "source": "ui"}
                )
        self.assertEqual(self._queued(), [("SELECT", "ui")])
        self.save_selection.assert_not_called()
        self.speak.assert_not_called()

    async def test_select_for_a_phrase_that_is_not_highlighted_is_ignored(self) -> None:
        with self.assertLogs("bridge.main", level="WARNING") as caught:
            async with self.client.ws_connect("/") as socket:
                await socket.receive_json(timeout=2)
                highlighted = self._enter_phrase_mode()
                self.assertNotEqual(highlighted, "need_bathroom")
                await socket.send_json(
                    {"type": "select", "phrase_id": "need_bathroom", "source": "ui"}
                )
        self.assertEqual(self._queued(), [])
        self.assertTrue(any("not highlighted" in line for line in caught.output))
        self.save_selection.assert_not_called()
        self.speak.assert_not_called()

    async def test_select_outside_phrase_mode_is_ignored(self) -> None:
        with self.assertLogs("bridge.main", level="WARNING") as caught:
            async with self.client.ws_connect("/") as socket:
                state = await socket.receive_json(timeout=2)
                self.assertEqual(state["mode"], "idle")
                await socket.send_json(
                    {"type": "select", "phrase_id": "need_water", "source": "ui"}
                )
                self.app[RUNTIME].machine.handle("HOLD", "keyboard", time.monotonic())
                self.assertEqual(
                    self.app[RUNTIME].machine.snapshot()["mode"], "category"
                )
                await socket.send_json(
                    {"type": "select", "phrase_id": "need_water", "source": "ui"}
                )
        self.assertEqual(self._queued(), [])
        self.assertGreaterEqual(len(caught.output), 2)
        self.assertTrue(all("ignored" in line for line in caught.output))
        self.save_selection.assert_not_called()
        self.speak.assert_not_called()

    async def test_unknown_phrase_id_is_ignored(self) -> None:
        with self.assertLogs("bridge.main", level="WARNING") as caught:
            async with self.client.ws_connect("/") as socket:
                await socket.receive_json(timeout=2)
                self._enter_phrase_mode()
                await socket.send_json(
                    {"type": "select", "phrase_id": "not_a_phrase", "source": "ui"}
                )
        self.assertEqual(self._queued(), [])
        self.assertTrue(any("unknown phrase" in line for line in caught.output))
        self.save_selection.assert_not_called()
        self.speak.assert_not_called()

    async def test_malformed_json_and_wrong_type_are_ignored(self) -> None:
        with self.assertLogs("bridge.main", level="WARNING") as caught:
            async with self.client.ws_connect("/") as socket:
                await socket.receive_json(timeout=2)
                phrase_id = self._enter_phrase_mode()
                await socket.send_str("{")
                await socket.send_json(
                    {"type": "tap", "phrase_id": phrase_id, "source": "ui"}
                )
        self.assertEqual(self._queued(), [])
        self.assertGreaterEqual(len(caught.output), 2)
        self.assertTrue(all("ignored" in line for line in caught.output))
        self.save_selection.assert_not_called()
        self.speak.assert_not_called()
