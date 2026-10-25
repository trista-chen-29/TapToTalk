"""Run the real firmware input/command logic with synthetic Pico peripherals."""

from __future__ import annotations

import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

FIRMWARE = Path(__file__).resolve().parents[1] / "firmware" / "main.py"


class FirmwareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 0
        pins: dict[int, object] = {}

        class Pin:
            IN = 0
            PULL_UP = 1

            def __init__(self, number: int, *_args: object) -> None:
                self.level = int(number == 15)
                pins[number] = self

            def value(self) -> int:
                return self.level

        class PWM:
            def __init__(self, _pin: Pin) -> None:
                self.duty = 0

            def freq(self, _value: int) -> None:
                pass

            def duty_u16(self, value: int) -> None:
                self.duty = value

        poller = SimpleNamespace(register=lambda *_args: None, poll=lambda _timeout: [])
        modules = {
            "machine": SimpleNamespace(Pin=Pin, PWM=PWM),
            "time": SimpleNamespace(
                ticks_ms=lambda: self.now,
                ticks_diff=lambda end, start: end - start,
            ),
            "select": SimpleNamespace(poll=lambda: poller, POLLIN=1),
        }
        self.firmware = {"__name__": "firmware_test"}
        with patch.dict("sys.modules", modules):
            exec(compile(FIRMWARE.read_text(), str(FIRMWARE), "exec"), self.firmware)
        self.touch = self.firmware["touch"]
        self.key = self.firmware["key"]
        self.events: list[str] = []
        self.firmware["emit"] = self.events.append

    def sample_touch(self, until: int, level: Callable[[int], int]) -> None:
        for now in range(self.now, until, self.firmware["POLL_MS"]):
            self.now = now
            self.touch.pin.level = level(now)
            self.touch.update(now)
        self.now = until

    def test_narrow_pulses_reach_both_hold_thresholds_once(self) -> None:
        # A 1 ms pulse every 20 ms represents the flickering metal sensor.
        self.sample_touch(4100, lambda now: int(100 <= now < 3700 and now % 20 == 0))
        self.assertEqual(self.events, ["HOLD", "HOLD_LONG"])

    def test_smoothing_does_not_turn_a_short_touch_into_a_hold(self) -> None:
        self.sample_touch(1500, lambda now: int(100 <= now < 1080 and now % 20 == 0))
        self.assertEqual(self.events, ["TAP"])

    def test_release_before_three_seconds_does_not_call_the_nurse(self) -> None:
        self.sample_touch(3900, lambda now: int(100 <= now < 3060 and now % 20 == 0))
        self.assertEqual(self.events, ["HOLD"])

    def test_ten_short_touches_produce_ten_taps(self) -> None:
        self.sample_touch(
            6100,
            lambda now: int(now % 600 < 100 and now >= 600 and now % 20 == 0),
        )
        self.sample_touch(6500, lambda _now: 0)
        self.assertEqual(self.events, ["TAP"] * 10)

    def test_key_bounce_and_held_key_produce_one_select(self) -> None:
        for now in range(500):
            self.now = now
            self.key.pin.level = int(now < 100 or (now < 120 and now % 2 == 0))
            self.key.update(now)
        self.assertEqual(self.events, ["SELECT"])

    def test_bridge_commands_set_led_and_keep_long_hold_at_three_seconds(self) -> None:
        command = self.firmware["handle_command"]
        command("LED listening")
        self.assertEqual([p.duty for p in self.firmware["channels"]], [0, 0, 65535])
        self.assertFalse(self.firmware["local"].active)
        command("CFG hold_ms 800")
        self.assertEqual(self.touch.hold_ms, 800)
        self.assertEqual(self.touch.long_ms, 3000)
        command("CFG hold_ms 3000")
        command("CFG hold_ms invalid")
        self.assertEqual(self.touch.hold_ms, 800)
        self.assertEqual(self.touch.long_ms, 3000)
        self.assertEqual(self.touch.holdover_ms, self.firmware["TOUCH_HOLDOVER_MS"])
        command("CFG touch_holdover_ms 40")
        self.assertEqual(self.touch.holdover_ms, 40)
        self.assertEqual(self.touch.hold_ms, 800)
        self.assertEqual(self.touch.long_ms, 3000)
        command("CFG touch_holdover_ms 19")
        command("CFG touch_holdover_ms 401")
        command("CFG touch_holdover_ms invalid")
        self.assertEqual(self.touch.holdover_ms, 40)
        self.assertEqual(self.touch.long_ms, 3000)
        command("LED unknown")
        self.assertEqual([p.duty for p in self.firmware["channels"]], [0, 0, 65535])

    def test_gap_longer_than_holdover_ends_the_press(self) -> None:
        self.firmware["handle_command"]("CFG touch_holdover_ms 40")

        def level(now: int) -> int:
            if now < 100 or now >= 1600:
                return 0
            if 700 <= now < 780:
                return 0
            return int(now % 20 == 0)

        self.sample_touch(2000, level)
        self.assertEqual(self.events, ["TAP", "TAP"])

    def test_gap_inside_default_holdover_stays_one_press(self) -> None:
        def level(now: int) -> int:
            if not (100 <= now < 1600):
                return 0
            if 700 <= now < 780:
                return 0
            return int(now % 20 == 0)

        self.sample_touch(2200, level)
        self.assertEqual(self.events, ["HOLD"])

    def test_max_holdover_cannot_invent_a_hold(self) -> None:
        self.firmware["handle_command"]("CFG touch_holdover_ms 400")
        self.sample_touch(2000, lambda now: int(100 <= now < 300 and now % 20 == 0))
        self.assertEqual(self.events, ["TAP"])
