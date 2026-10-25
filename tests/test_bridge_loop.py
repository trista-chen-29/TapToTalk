"""The bridge loop broadcasts state and forwards LED commands."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from bridge.main import RUNTIME, create_app, led_resend_due, on_serial_connect
from bridge.profile import PROFILE_PATH


class RecordingSerial:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, command: str) -> None:
        self.sent.append(command)

    def close(self) -> None:
        return None


class LedResendTests(unittest.TestCase):
    def test_resend_after_five_quiet_seconds(self) -> None:
        self.assertFalse(led_resend_due(4.9, 0.0, 0.0))
        self.assertTrue(led_resend_due(5.0, 0.0, 0.0))
        self.assertFalse(led_resend_due(8.0, 4.0, 4.0))
        self.assertTrue(led_resend_due(9.0, 4.0, 4.0))
        self.assertFalse(led_resend_due(10.0, 0.0, 6.0))
        self.assertTrue(led_resend_due(11.0, 0.0, 6.0))


class BridgeLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.app = create_app()
        self.serial = RecordingSerial()
        self.app[RUNTIME].serial = self.serial
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_events_change_mode_and_led(self) -> None:
        async with self.client.ws_connect("/") as socket:
            initial = await socket.receive_json(timeout=2)
            self.assertEqual(initial["mode"], "idle")
            expected = [
                ("TAP", "category", 0, "needs"),
                ("TAP", "category", 1, "pain_comfort"),
                ("SELECT", "phrase", 0, "pain_comfort"),
                ("SELECT", "idle", 0, None),
            ]
            for event, mode, highlight, category in expected:
                self.app[RUNTIME].events.put_nowait((event, "tap"))
                state = await socket.receive_json(timeout=2)
                self.assertEqual(state["type"], "state")
                self.assertEqual(state["mode"], mode)
                self.assertEqual(state["highlight_index"], highlight)
                self.assertEqual(state["category"], category)
            self.assertEqual(state["phrases"], [])
        self.assertEqual(
            self.serial.sent,
            [
                "CFG hold_ms 1000",
                "LED listening",
                "LED listening",
                "LED phrase",
                "LED sent",
            ],
        )

    async def test_two_sockets_receive_the_same_state(self) -> None:
        async with (
            self.client.ws_connect("/") as first,
            self.client.ws_connect("/") as second,
        ):
            self.assertEqual((await first.receive_json(timeout=2))["mode"], "idle")
            self.assertEqual((await second.receive_json(timeout=2))["mode"], "idle")
            self.app[RUNTIME].events.put_nowait(("HOLD", "tap"))
            left = await first.receive_json(timeout=2)
            right = await second.receive_json(timeout=2)
        self.assertEqual(left, right)
        self.assertEqual(left["mode"], "category")

    async def test_reset_returns_both_sockets_to_idle(self) -> None:
        async with self.client.ws_connect("/") as socket:
            await socket.receive_json(timeout=2)
            self.app[RUNTIME].events.put_nowait(("TAP", "keyboard"))
            state = await socket.receive_json(timeout=2)
            self.assertEqual(state["mode"], "category")
            self.app[RUNTIME].events.put_nowait(("RESET", "keyboard"))
            state = await socket.receive_json(timeout=2)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(self.serial.sent[-1], "LED idle")

    async def test_connect_sends_hold_time_then_led(self) -> None:
        on_serial_connect(self.app)
        self.assertEqual(self.serial.sent, ["CFG hold_ms 1000", "LED idle"])

    async def test_hold_long_alerts_the_dashboard_and_turns_the_lamp_red(self) -> None:
        async with self.client.ws_connect("/") as socket:
            await socket.receive_json(timeout=2)
            self.app[RUNTIME].events.put_nowait(("HOLD_LONG", "tap"))
            alert = await socket.receive_json(timeout=2)
        self.assertEqual(alert["type"], "alert")
        self.assertEqual(alert["kind"], "nurse_call")
        self.assertEqual(alert["phrase_id"], "person_nurse")
        self.assertTrue(str(alert["timestamp"]).endswith("Z"))
        self.assertEqual(self.serial.sent, ["LED alert"])

    async def test_profile_edit_changes_the_next_session_hold(self) -> None:
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        keys = _Keyboard()
        self.app[RUNTIME].keyboard = keys
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            raw["hold_ms"] = 1500
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.app[RUNTIME].profile_path = path
            async with self.client.ws_connect("/") as socket:
                await socket.receive_json(timeout=2)
                self.app[RUNTIME].events.put_nowait(("TAP", "tap"))
                state = await socket.receive_json(timeout=2)
                self.assertEqual(state["mode"], "category")
                self.assertEqual(self.serial.sent[0], "CFG hold_ms 1500")
                self.assertEqual(keys.hold_ms, 1500)
                raw["hold_ms"] = 800
                path.write_text(json.dumps(raw), encoding="utf-8")
                self.app[RUNTIME].events.put_nowait(("RESET", "keyboard"))
                idle = await socket.receive_json(timeout=2)
                self.assertEqual(idle["mode"], "idle")
                self.serial.sent.clear()
                self.app[RUNTIME].events.put_nowait(("HOLD", "tap"))
                state = await socket.receive_json(timeout=2)
        self.assertEqual(state["mode"], "category")
        self.assertEqual(self.serial.sent[0], "CFG hold_ms 800")
        self.assertEqual(keys.hold_ms, 800)


class _Keyboard:
    def __init__(self) -> None:
        self.hold_ms = 0

    def set_hold_ms(self, hold_ms: int) -> None:
        self.hold_ms = hold_ms

    def close(self) -> None:
        return None
