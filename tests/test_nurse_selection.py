"""Confirmed selections share the direct-call alert path over real test sockets."""

from __future__ import annotations

import tempfile
import time
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from bridge import log
from bridge.main import RUNTIME, create_app


class NurseSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "synthetic.db"
        save = patch(
            "bridge.main.save_selection",
            side_effect=partial(log.save_selection, db_path=self.db_path),
        )
        alert = patch("bridge.main.save_alert", return_value=1)
        speech = patch("bridge.main.speak")
        self.save = save.start()
        self.alert = alert.start()
        self.speak = speech.start()
        self.addCleanup(save.stop)
        self.addCleanup(alert.stop)
        self.addCleanup(speech.stop)
        self.app = create_app()
        self.runtime = self.app[RUNTIME]
        self.now = time.monotonic()
        self.runtime.clock = lambda: self.now
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.dashboard = await self.client.ws_connect("/")
        await self.dashboard.receive_json(timeout=2)

    async def event(self, event: str, source: str = "keyboard") -> dict:
        self.now += 0.1
        self.runtime.events.put_nowait((event, source))
        return await self.dashboard.receive_json(timeout=2)

    async def open_people(self, source: str = "keyboard") -> None:
        for event in ("HOLD", "TAP", "TAP", "SELECT"):
            state = await self.event(event, source)
        self.assertEqual(state["mode"], "phrase")
        self.assertEqual(state["category"], "people")
        self.assertEqual(state["phrases"][0]["id"], "person_nurse")

    def rows(self) -> list:
        connection = log.connect(self.db_path)
        try:
            return connection.execute("SELECT * FROM selections ORDER BY id").fetchall()
        finally:
            connection.close()

    def assert_alert(self, message: dict) -> None:
        self.assertEqual(set(message), {"type", "kind", "phrase_id", "timestamp"})
        self.assertEqual(message["type"], "alert")
        self.assertEqual(message["kind"], "nurse_call")
        self.assertEqual(message["phrase_id"], "person_nurse")
        self.assertTrue(message["timestamp"].endswith("Z"))

    async def assert_idle_after_alert(self) -> None:
        state = await self.dashboard.receive_json(timeout=2)
        self.assertEqual(state["type"], "state")
        self.assertEqual(state["mode"], "idle")

    async def test_keyboard_confirmation_alerts_logs_once_and_speaks(self) -> None:
        await self.open_people()
        self.assert_alert(await self.event("SELECT"))
        await self.assert_idle_after_alert()
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["phrase_id"], "person_nurse")
        self.assertEqual(self.rows()[0]["category"], "people")
        self.assertEqual(self.rows()[0]["source"], "keyboard")
        self.save.assert_called_once()
        self.speak.assert_called_once_with("person_nurse", "Call nurse")

    async def test_sensor_hold_confirmation_uses_same_alert_path(self) -> None:
        await self.open_people("tap")
        self.assert_alert(await self.event("HOLD", "tap"))
        await self.assert_idle_after_alert()
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["source"], "tap")
        self.speak.assert_called_once_with("person_nurse", "Call nurse")

    async def test_audio_failure_does_not_prevent_alert_or_selection_row(self) -> None:
        self.speak.side_effect = RuntimeError("synthetic audio failure")
        await self.open_people()
        with self.assertLogs("bridge.main", level="WARNING"):
            self.assert_alert(await self.event("SELECT"))
            await self.assert_idle_after_alert()
        self.assertEqual(len(self.rows()), 1)
        self.speak.assert_called_once()

    async def test_alert_is_sent_before_speech_can_finish(self) -> None:
        import threading

        release = threading.Event()
        self.speak.side_effect = lambda *_: release.wait(timeout=5)
        await self.open_people()
        try:
            self.assert_alert(await self.event("SELECT"))
            self.assertFalse(release.is_set())
        finally:
            release.set()
        await self.assert_idle_after_alert()

    async def test_other_phrase_logs_and_speaks_without_nurse_alert(self) -> None:
        await self.open_people()
        state = await self.event("TAP")
        self.assertEqual(state["highlight_index"], 1)
        state = await self.event("SELECT")
        # An erroneous alert would be the first received frame instead of idle.
        self.assertEqual(state["type"], "state")
        self.assertEqual(state["mode"], "idle")
        self.assertIsNone(self.runtime.last_nurse_call_at)
        self.assertEqual(len(self.rows()), 1)
        self.speak.assert_called_once_with("person_family", "Please call my family")

    async def test_normal_and_direct_calls_share_the_60_second_window(self) -> None:
        await self.open_people()
        self.assert_alert(await self.event("SELECT"))
        await self.assert_idle_after_alert()
        first = self.runtime.last_nurse_call_at
        self.now = first + 10
        # HOLD_LONG from a category must still return idle, but suppress its alert.
        await self.event("HOLD")
        state = await self.event("HOLD_LONG")
        self.assertEqual(state["type"], "state")
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(self.runtime.last_nurse_call_at, first)
        self.now = first + 60
        self.assert_alert(await self.event("HOLD_LONG"))
        # A direct call does not insert another phrase selection or play audio.
        self.assertEqual(len(self.rows()), 1)
        self.speak.assert_called_once()

    async def test_repeated_normal_calls_log_each_choice_but_dedupe_alerts(
        self,
    ) -> None:
        await self.open_people()
        self.assert_alert(await self.event("SELECT"))
        await self.assert_idle_after_alert()
        first = self.runtime.last_nurse_call_at
        await self.open_people()
        state = await self.event("SELECT")
        self.assertEqual(state["type"], "state")
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(self.runtime.last_nurse_call_at, first)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(self.speak.call_count, 2)
