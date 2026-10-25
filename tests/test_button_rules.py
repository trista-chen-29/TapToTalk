"""CONTRACT.md section 4 button rules.

One test per input row, checked in idle, category, and phrase mode.
The clock value on every step is explicit. A session starts on HOLD.
Esc uses Machine.reset.
"""

from __future__ import annotations

import unittest

from bridge.phrases import load_phrases
from bridge.state import Machine, NurseCall, Selected, State

NEEDS = ["need_water", "need_bathroom", "need_suction", "need_position"]
PAIN = ["pain_here", "pain_medicine", "comfort_hot", "comfort_cold"]
NURSE = [NurseCall("person_nurse", "tap"), "LED alert"]


def phrase_ids(state: State) -> list[str]:
    return [item["id"] for item in state["phrases"]]


class ButtonRuleTests(unittest.TestCase):
    def test_tap(self) -> None:
        with self.subTest(mode="idle"):
            machine = Machine(load_phrases())
            state, effects = machine.handle("TAP", "tap", 0.0)
            self.assertEqual(state["mode"], "idle")
            self.assertEqual(state["highlight_index"], 0)
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, [])

        with self.subTest(mode="category"):
            machine = Machine(load_phrases())
            machine.handle("HOLD", "tap", 0.0)
            state, effects = machine.handle("TAP", "tap", 1.0)
            self.assertEqual(state["mode"], "category")
            self.assertEqual(state["highlight_index"], 1)
            self.assertEqual(state["category"], "pain_comfort")
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, ["LED listening"])

        with self.subTest(mode="phrase"):
            machine = Machine(load_phrases())
            machine.handle("HOLD", "tap", 0.0)
            machine.handle("HOLD", "tap", 1.0)
            state, effects = machine.handle("TAP", "tap", 2.0)
            self.assertEqual(state["mode"], "phrase")
            self.assertEqual(state["highlight_index"], 1)
            self.assertEqual(state["category"], "needs")
            self.assertEqual(phrase_ids(state), NEEDS)
            self.assertEqual(effects, ["LED phrase"])

    def test_hold(self) -> None:
        with self.subTest(mode="idle"):
            machine = Machine(load_phrases())
            state, effects = machine.handle("HOLD", "tap", 0.0)
            self.assertEqual(state["mode"], "category")
            self.assertEqual(state["highlight_index"], 0)
            self.assertEqual(state["category"], "needs")
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, ["LED listening"])

        with self.subTest(mode="category"):
            machine = Machine(load_phrases())
            machine.handle("HOLD", "tap", 0.0)
            machine.handle("TAP", "tap", 1.0)
            state, effects = machine.handle("HOLD", "tap", 2.0)
            self.assertEqual(state["mode"], "phrase")
            self.assertEqual(state["highlight_index"], 0)
            self.assertEqual(state["category"], "pain_comfort")
            self.assertEqual(phrase_ids(state), PAIN)
            self.assertEqual(effects, ["LED phrase"])

        with self.subTest(mode="phrase"):
            machine = Machine(load_phrases())
            machine.handle("HOLD", "tap", 0.0)
            machine.handle("HOLD", "tap", 1.0)
            machine.handle("TAP", "tap", 2.0)
            state, effects = machine.handle("HOLD", "tap", 3.0)
            self.assertEqual(state["mode"], "idle")
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(
                effects,
                [Selected("need_bathroom", "tap"), "LED sent"],
            )

    def test_hold_long(self) -> None:
        with self.subTest(mode="idle"):
            machine = Machine(load_phrases())
            state, effects = machine.handle("HOLD_LONG", "tap", 0.0)
            self.assertEqual(state["mode"], "idle")
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, NURSE)

        with self.subTest(mode="category"):
            machine = Machine(load_phrases())
            started, _effects = machine.handle("HOLD", "tap", 0.0)
            self.assertEqual(started["mode"], "category")
            state, effects = machine.handle("HOLD_LONG", "tap", 1.0)
            self.assertEqual(state["mode"], "idle")
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, NURSE)

        with self.subTest(mode="phrase"):
            machine = Machine(load_phrases())
            machine.handle("HOLD", "tap", 0.0)
            opened, _effects = machine.handle("HOLD", "tap", 1.0)
            self.assertEqual(opened["mode"], "phrase")
            state, effects = machine.handle("HOLD_LONG", "tap", 2.0)
            self.assertEqual(state["mode"], "idle")
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, NURSE)

    def test_select(self) -> None:
        with self.subTest(mode="idle"):
            machine = Machine(load_phrases())
            state, effects = machine.handle("SELECT", "tap", 0.0)
            self.assertEqual(state["mode"], "idle")
            self.assertEqual(state["highlight_index"], 0)
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, [])

        with self.subTest(mode="category"):
            machine = Machine(load_phrases())
            machine.handle("HOLD", "tap", 0.0)
            machine.handle("TAP", "tap", 1.0)
            state, effects = machine.handle("SELECT", "tap", 2.0)
            self.assertEqual(state["mode"], "phrase")
            self.assertEqual(state["highlight_index"], 0)
            self.assertEqual(state["category"], "pain_comfort")
            self.assertEqual(phrase_ids(state), PAIN)
            self.assertEqual(effects, ["LED phrase"])

        with self.subTest(mode="phrase"):
            machine = Machine(load_phrases())
            machine.handle("HOLD", "tap", 0.0)
            machine.handle("SELECT", "tap", 1.0)
            machine.handle("TAP", "tap", 2.0)
            state, effects = machine.handle("SELECT", "tap", 3.0)
            self.assertEqual(state["mode"], "idle")
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(
                effects,
                [Selected("need_bathroom", "tap"), "LED sent"],
            )

    def test_eight_second_timeout(self) -> None:
        with self.subTest(mode="category"):
            machine = Machine(load_phrases())
            machine.handle("HOLD", "tap", 0.0)
            state, effects = machine.tick(7.0)
            self.assertEqual(state["mode"], "category")
            self.assertEqual(effects, [])
            state, effects = machine.tick(8.0)
            self.assertEqual(state["mode"], "idle")
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, ["LED idle"])

        with self.subTest(mode="phrase"):
            machine = Machine(load_phrases())
            machine.handle("HOLD", "tap", 0.0)
            machine.handle("HOLD", "tap", 1.0)
            state, effects = machine.tick(8.0)
            self.assertEqual(state["mode"], "phrase")
            self.assertEqual(effects, [])
            state, effects = machine.tick(9.0)
            self.assertEqual(state["mode"], "idle")
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, ["LED idle"])

    def test_esc_reset(self) -> None:
        with self.subTest(mode="category"):
            machine = Machine(load_phrases())
            machine.handle("HOLD", "tap", 0.0)
            state, effects = machine.reset()
            self.assertEqual(state["mode"], "idle")
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, ["LED idle"])

        with self.subTest(mode="phrase"):
            machine = Machine(load_phrases())
            machine.handle("HOLD", "tap", 0.0)
            machine.handle("HOLD", "tap", 1.0)
            state, effects = machine.reset()
            self.assertEqual(state["mode"], "idle")
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, ["LED idle"])

        with self.subTest(mode="idle"):
            machine = Machine(load_phrases())
            state, effects = machine.reset()
            self.assertEqual(state["mode"], "idle")
            self.assertIsNone(state["category"])
            self.assertEqual(phrase_ids(state), [])
            self.assertEqual(effects, [])
