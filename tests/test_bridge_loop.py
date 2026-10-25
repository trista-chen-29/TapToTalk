"""The bridge loop broadcasts state and forwards LED commands."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from bridge.main import (
    RUNTIME,
    create_app,
    handle_item,
    led_resend_due,
    on_serial_connect,
    publish,
    run_once,
)
from bridge.profile import PROFILE_PATH, load_profile
from bridge.state import Selected


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
        self.save_patch = patch("bridge.main.save_selection", return_value=1)
        self.speak_patch = patch("bridge.main.speak")
        self.save_selection = self.save_patch.start()
        self.speak = self.speak_patch.start()
        self.addCleanup(self.save_patch.stop)
        self.addCleanup(self.speak_patch.stop)
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
                ("HOLD", "category", 0, "needs"),
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
                "CFG touch_holdover_ms 150",
                "LED listening",
                "LED listening",
                "LED phrase",
                "LED sent",
            ],
        )
        self.save_selection.assert_called_once_with("pain_here", "pain_comfort", "tap")
        self.speak.assert_called_once_with("pain_here", "I am in pain")

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
            self.app[RUNTIME].events.put_nowait(("HOLD", "keyboard"))
            state = await socket.receive_json(timeout=2)
            self.assertEqual(state["mode"], "category")
            self.app[RUNTIME].events.put_nowait(("RESET", "keyboard"))
            state = await socket.receive_json(timeout=2)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(self.serial.sent[-1], "LED idle")

    async def test_connect_sends_hold_time_then_led(self) -> None:
        on_serial_connect(self.app)
        self.assertEqual(
            self.serial.sent,
            ["CFG hold_ms 1000", "CFG touch_holdover_ms 150", "LED idle"],
        )

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
        self.save_selection.assert_not_called()
        self.speak.assert_not_called()

    async def test_profile_edit_changes_the_next_session_hold(self) -> None:
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        keys = _Keyboard()
        self.app[RUNTIME].keyboard = keys
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            raw["hold_ms"] = 1500
            raw["touch_holdover_ms"] = 80
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.app[RUNTIME].profile_path = path
            async with self.client.ws_connect("/") as socket:
                await socket.receive_json(timeout=2)
                self.app[RUNTIME].events.put_nowait(("HOLD", "tap"))
                state = await socket.receive_json(timeout=2)
                self.assertEqual(state["mode"], "category")
                self.assertEqual(self.serial.sent[0], "CFG hold_ms 1500")
                self.assertEqual(self.serial.sent[1], "CFG touch_holdover_ms 80")
                self.assertEqual(keys.hold_ms, 1500)
                raw["hold_ms"] = 800
                raw["touch_holdover_ms"] = 200
                path.write_text(json.dumps(raw), encoding="utf-8")
                self.app[RUNTIME].events.put_nowait(("RESET", "keyboard"))
                idle = await socket.receive_json(timeout=2)
                self.assertEqual(idle["mode"], "idle")
                self.serial.sent.clear()
                self.app[RUNTIME].events.put_nowait(("HOLD", "tap"))
                state = await socket.receive_json(timeout=2)
        self.assertEqual(state["mode"], "category")
        self.assertEqual(self.serial.sent[0], "CFG hold_ms 800")
        self.assertEqual(self.serial.sent[1], "CFG touch_holdover_ms 200")
        self.assertEqual(keys.hold_ms, 800)

    async def test_selected_effect_saves_once_and_speaks_once(self) -> None:
        state = self.app[RUNTIME].machine.snapshot()
        await publish(
            self.app,
            state,
            [Selected("need_bathroom", "keyboard"), "LED sent"],
            0.0,
        )
        self.save_selection.assert_called_once_with(
            "need_bathroom", "needs", "keyboard"
        )
        self.speak.assert_called_once_with("need_bathroom", "I need the bathroom")
        self.assertIn("LED sent", self.serial.sent)

    async def test_speech_failure_is_logged_and_not_raised(self) -> None:
        self.speak.side_effect = RuntimeError("playback failed")
        state = self.app[RUNTIME].machine.snapshot()
        with self.assertLogs("bridge.main", level="WARNING") as caught:
            await publish(
                self.app,
                state,
                [Selected("yes_yes", "ui")],
                0.0,
            )
        self.save_selection.assert_called_once_with("yes_yes", "yes_no", "ui")
        self.speak.assert_called_once_with("yes_yes", "Yes")
        self.assertTrue(any("speech failed" in line for line in caught.output))


class AlertRuleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.app = create_app()
        self.runtime = self.app[RUNTIME]
        self.serial = RecordingSerial()
        self.runtime.serial = self.serial
        self.socket = _RecordingSocket()
        self.runtime.sockets.add(self.socket)
        self.clock = _Clock(0.0)
        self.runtime.clock = self.clock
        self.runtime.last_input_at = 0.0

    def _alerts(self, kind: str) -> list[dict[str, object]]:
        return [
            item
            for item in self.socket.sent
            if item.get("type") == "alert" and item.get("kind") == kind
        ]

    async def _nurse_call(self, now: float) -> None:
        self.clock.now = now
        await handle_item(self.app, ("HOLD_LONG", "tap"), now)

    async def test_second_nurse_call_within_60_seconds_is_not_broadcast(self) -> None:
        await self._nurse_call(1000.0)
        await self._nurse_call(1059.0)
        alerts = self._alerts("nurse_call")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["phrase_id"], "person_nurse")
        self.assertTrue(str(alerts[0]["timestamp"]).endswith("Z"))
        self.assertEqual(self.serial.sent, ["LED alert", "LED alert"])
        self.assertEqual(self.runtime.last_nurse_call_at, 1000.0)

    async def test_nurse_call_after_61_seconds_is_broadcast_again(self) -> None:
        await self._nurse_call(1000.0)
        await self._nurse_call(1061.0)
        alerts = self._alerts("nurse_call")
        self.assertEqual(len(alerts), 2)
        self.assertEqual(alerts[0]["phrase_id"], "person_nurse")
        self.assertEqual(alerts[1]["phrase_id"], "person_nurse")
        self.assertEqual(self.serial.sent, ["LED alert", "LED alert"])
        self.assertEqual(self.runtime.last_nurse_call_at, 1061.0)

    async def test_no_activity_fires_once_until_the_next_session(self) -> None:
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        raw["idle_alert_minutes"] = 2
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.runtime.profile_path = path
            self.runtime.profile = load_profile(path)
            limit = 2 * 60
            self.runtime.last_input_at = 0.0

            self.clock.now = limit - 1
            await run_once(self.app)
            self.assertEqual(self._alerts("no_activity"), [])

            self.clock.now = limit
            await run_once(self.app)
            alerts = self._alerts("no_activity")
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0]["type"], "alert")
            self.assertEqual(alerts[0]["kind"], "no_activity")
            self.assertIsNone(alerts[0]["phrase_id"])
            self.assertTrue(str(alerts[0]["timestamp"]).endswith("Z"))
            self.assertEqual(
                set(alerts[0]),
                {"type", "kind", "phrase_id", "timestamp"},
            )
            self.assertIn('"phrase_id": null', json.dumps(alerts[0]))

            self.clock.now = limit + 10000
            await run_once(self.app)
            self.assertEqual(len(self._alerts("no_activity")), 1)

            self.clock.now = limit + 10000
            self.runtime.events.put_nowait(("HOLD", "tap"))
            await run_once(self.app)
            self.assertEqual(self.runtime.machine.snapshot()["mode"], "category")
            self.assertEqual(len(self._alerts("no_activity")), 1)

            self.runtime.events.put_nowait(("RESET", "keyboard"))
            await run_once(self.app)
            self.assertEqual(self.runtime.machine.snapshot()["mode"], "idle")
            ended = self.clock.now
            self.assertEqual(len(self._alerts("no_activity")), 1)

            self.clock.now = ended + limit - 1
            await run_once(self.app)
            self.assertEqual(len(self._alerts("no_activity")), 1)

            self.clock.now = ended + limit
            await run_once(self.app)
            alerts = self._alerts("no_activity")
            self.assertEqual(len(alerts), 2)
            self.assertIsNone(alerts[1]["phrase_id"])

            self.clock.now = ended + limit + 10000
            await run_once(self.app)
            self.assertEqual(len(self._alerts("no_activity")), 2)


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _RecordingSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.closed = False

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)


class _Keyboard:
    def __init__(self) -> None:
        self.hold_ms = 0

    def set_hold_ms(self, hold_ms: int) -> None:
        self.hold_ms = hold_ms

    def close(self) -> None:
        return None
