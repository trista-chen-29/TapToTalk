"""Table-driven tests for the contract button rules. Fake clock, no I/O."""

from __future__ import annotations

import unittest

from bridge.phrases import load_phrases
from bridge.state import (
    ALERT_LED_S,
    IDLE_TIMEOUT_S,
    SENT_LED_S,
    Machine,
    NurseCall,
    Selected,
)

CATALOG = load_phrases()
NEEDS = [
    "need_water",
    "need_bathroom",
    "need_suction",
    "need_position",
]


def drive(
    events: list[str],
    *,
    source: str = "tap",
    start: float = 0.0,
) -> tuple[Machine, float, dict[str, object], list[object]]:
    machine = Machine(CATALOG)
    now = start
    state: dict[str, object] = machine.snapshot()
    effects: list[object] = []
    for event in events:
        state, effects = machine.handle(event, source, now)
        now += 1.0
    return machine, now, state, effects


class ContractTableTests(unittest.TestCase):
    def test_contract_table(self) -> None:
        cases: list[dict[str, object]] = [
            {
                "name": "idle TAP stays idle with no effects",
                "setup": [],
                "event": "TAP",
                "mode": "idle",
                "highlight_index": 0,
                "category": None,
                "phrase_ids": [],
                "effects": [],
            },
            {
                "name": "idle HOLD starts a session",
                "setup": [],
                "event": "HOLD",
                "mode": "category",
                "highlight_index": 0,
                "category": "needs",
                "phrase_ids": [],
                "effects": ["LED listening"],
            },
            {
                "name": "idle SELECT is ignored",
                "setup": [],
                "event": "SELECT",
                "mode": "idle",
                "highlight_index": 0,
                "category": None,
                "phrase_ids": [],
                "effects": [],
            },
            {
                "name": "category TAP highlights the next category",
                "setup": ["HOLD"],
                "event": "TAP",
                "mode": "category",
                "highlight_index": 1,
                "category": "pain_comfort",
                "phrase_ids": [],
                "effects": ["LED listening"],
            },
            {
                "name": "category TAP wraps to the first category",
                "setup": ["HOLD", "TAP", "TAP", "TAP"],
                "event": "TAP",
                "mode": "category",
                "highlight_index": 0,
                "category": "needs",
                "phrase_ids": [],
                "effects": ["LED listening"],
            },
            {
                "name": "category HOLD opens phrases",
                "setup": ["HOLD"],
                "event": "HOLD",
                "mode": "phrase",
                "highlight_index": 0,
                "category": "needs",
                "phrase_ids": NEEDS,
                "effects": ["LED phrase"],
            },
            {
                "name": "category SELECT opens phrases",
                "setup": ["HOLD"],
                "event": "SELECT",
                "mode": "phrase",
                "highlight_index": 0,
                "category": "needs",
                "phrase_ids": NEEDS,
                "effects": ["LED phrase"],
            },
            {
                "name": "phrase TAP highlights the next phrase",
                "setup": ["HOLD", "HOLD"],
                "event": "TAP",
                "mode": "phrase",
                "highlight_index": 1,
                "category": "needs",
                "phrase_ids": NEEDS,
                "effects": ["LED phrase"],
            },
            {
                "name": "phrase TAP wraps to the first phrase",
                "setup": ["HOLD", "HOLD", "TAP", "TAP", "TAP"],
                "event": "TAP",
                "mode": "phrase",
                "highlight_index": 0,
                "category": "needs",
                "phrase_ids": NEEDS,
                "effects": ["LED phrase"],
            },
            {
                "name": "phrase HOLD chooses the highlighted phrase",
                "setup": ["HOLD", "HOLD", "TAP"],
                "event": "HOLD",
                "source": "keyboard",
                "mode": "idle",
                "highlight_index": 0,
                "category": None,
                "phrase_ids": [],
                "effects": [Selected("need_bathroom", "keyboard"), "LED sent"],
            },
            {
                "name": "phrase SELECT chooses the highlighted phrase",
                "setup": ["HOLD", "SELECT"],
                "event": "SELECT",
                "mode": "idle",
                "highlight_index": 0,
                "category": None,
                "phrase_ids": [],
                "effects": [Selected("need_water", "tap"), "LED sent"],
            },
        ]
        for case in cases:
            with self.subTest(case=case["name"]):
                _machine, now, _prior, _prior_effects = drive(
                    list(case["setup"]),  # type: ignore[arg-type]
                )
                source = str(case.get("source", "tap"))
                state, effects = _machine.handle(str(case["event"]), source, now)
                self.assertEqual(
                    state,
                    {
                        "type": "state",
                        "mode": case["mode"],
                        "highlight_index": case["highlight_index"],
                        "category": case["category"],
                        "phrases": [
                            {
                                "id": phrase_id,
                                "text": next(
                                    item["text"]
                                    for item in CATALOG["phrases"]
                                    if item["id"] == phrase_id
                                ),
                            }
                            for phrase_id in case["phrase_ids"]  # type: ignore[union-attr]
                        ],
                    },
                )
                self.assertEqual(effects, case["effects"])
                for phrase in state["phrases"]:
                    self.assertEqual(set(phrase), {"id", "text"})

    def test_phrase_order_is_catalog_order(self) -> None:
        machine, now, _state, _effects = drive(["HOLD", "TAP"])
        state, _effects = machine.handle("HOLD", "tap", now)
        self.assertEqual(
            [item["id"] for item in state["phrases"]],
            ["pain_here", "pain_medicine", "comfort_hot", "comfort_cold"],
        )

    def test_call_nurse_phrase_can_be_chosen(self) -> None:
        machine, now, _state, _effects = drive(["HOLD", "TAP", "TAP"])
        state, _effects = machine.handle("HOLD", "tap", now)
        self.assertEqual(state["category"], "people")
        self.assertEqual(state["phrases"][0]["id"], "person_nurse")
        state, effects = machine.handle("SELECT", "tap", now + 1)
        self.assertEqual(effects[0], Selected("person_nurse", "tap"))
        self.assertEqual(state["mode"], "idle")


class TimerTests(unittest.TestCase):
    def test_eight_seconds_without_input_returns_to_idle(self) -> None:
        machine = Machine(CATALOG)
        machine.handle("HOLD", "tap", 0.0)
        state, effects = machine.tick(IDLE_TIMEOUT_S - 0.001)
        self.assertEqual(state["mode"], "category")
        self.assertEqual(effects, [])
        state, effects = machine.tick(IDLE_TIMEOUT_S)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(state["category"], None)
        self.assertEqual(state["phrases"], [])
        self.assertEqual(effects, ["LED idle"])
        state, effects = machine.tick(IDLE_TIMEOUT_S + 5)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, [])

    def test_input_restarts_the_idle_timer(self) -> None:
        machine = Machine(CATALOG)
        machine.handle("HOLD", "tap", 0.0)
        machine.handle("TAP", "tap", 7.0)
        state, effects = machine.tick(8.0)
        self.assertEqual(state["mode"], "category")
        self.assertEqual(state["highlight_index"], 1)
        self.assertEqual(effects, [])
        state, effects = machine.tick(7.0 + IDLE_TIMEOUT_S)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, ["LED idle"])

    def test_hold_long_calls_the_nurse_from_every_mode(self) -> None:
        setups = ([], ["HOLD"], ["HOLD", "HOLD"])
        for setup in setups:
            with self.subTest(setup=setup):
                machine, now, _prior, _effects = drive(setup)
                state, effects = machine.handle("HOLD_LONG", "tap", now)
                self.assertEqual(state["mode"], "idle")
                self.assertEqual(state["phrases"], [])
                self.assertEqual(
                    effects,
                    [NurseCall("person_nurse", "tap"), "LED alert"],
                )
                cleared, lamp = machine.tick(now + ALERT_LED_S)
                self.assertEqual(cleared["mode"], "idle")
                self.assertEqual(lamp, ["LED idle"])

    def test_hold_then_hold_long_starts_then_calls_the_nurse(self) -> None:
        machine = Machine(CATALOG)
        state, effects = machine.handle("HOLD", "tap", 0.0)
        self.assertEqual(state["mode"], "category")
        self.assertEqual(effects, ["LED listening"])
        state, effects = machine.handle("HOLD_LONG", "tap", 2.0)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects[0], NurseCall("person_nurse", "tap"))
        self.assertEqual(effects[1], "LED alert")

    def test_idle_tick_does_not_time_out(self) -> None:
        machine = Machine(CATALOG)
        state, effects = machine.tick(100.0)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, [])

    def test_sent_led_returns_to_idle_after_two_seconds(self) -> None:
        machine, now, _state, effects = drive(["HOLD", "HOLD", "SELECT"])
        self.assertEqual(effects[-1], "LED sent")
        state, effects = machine.tick(now - 1 + SENT_LED_S - 0.001)
        self.assertEqual(effects, [])
        self.assertEqual(state["mode"], "idle")
        state, effects = machine.tick(now - 1 + SENT_LED_S)
        self.assertEqual(effects, ["LED idle"])
        state, effects = machine.tick(now - 1 + SENT_LED_S + 1)
        self.assertEqual(effects, [])

    def test_new_input_cancels_the_sent_lamp(self) -> None:
        machine, now, _state, _effects = drive(["HOLD", "HOLD", "SELECT"])
        chosen_at = now - 1
        state, effects = machine.handle("HOLD", "tap", chosen_at + 1)
        self.assertEqual(state["mode"], "category")
        self.assertEqual(effects, ["LED listening"])
        state, effects = machine.tick(chosen_at + SENT_LED_S)
        self.assertEqual(state["mode"], "category")
        self.assertEqual(effects, [])


class ResetAndIgnoreTests(unittest.TestCase):
    def test_reset_returns_to_idle(self) -> None:
        machine, _now, _state, _effects = drive(["HOLD", "HOLD", "TAP"])
        state, effects = machine.reset()
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(state["highlight_index"], 0)
        self.assertIsNone(state["category"])
        self.assertEqual(state["phrases"], [])
        self.assertEqual(effects, ["LED idle"])
        state, effects = machine.reset()
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, [])

    def test_reset_clears_a_sent_lamp(self) -> None:
        machine, _now, _state, _effects = drive(["HOLD", "SELECT", "SELECT"])
        state, effects = machine.reset()
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, ["LED idle"])
        state, effects = machine.tick(100.0)
        self.assertEqual(effects, [])

    def test_unknown_event_is_ignored(self) -> None:
        machine = Machine(CATALOG)
        before = machine.snapshot()
        state, effects = machine.handle("NOPE", "tap", 0.0)
        self.assertEqual(state, before)
        self.assertEqual(effects, [])
        machine.handle("HOLD", "tap", 0.0)
        state, effects = machine.handle("LED idle", "tap", 7.0)
        self.assertEqual(state["mode"], "category")
        self.assertEqual(state["highlight_index"], 0)
        self.assertEqual(effects, [])
        state, effects = machine.tick(IDLE_TIMEOUT_S)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, ["LED idle"])

    def test_reorder_applies_only_while_the_first_phrase_is_highlighted(self) -> None:
        machine, _now, state, _effects = drive(["HOLD", "SELECT"])
        self.assertEqual([item["id"] for item in state["phrases"]], NEEDS)
        self.assertIsNone(machine.reorder_open_phrases(["need_water"]))
        self.assertIsNone(machine.reorder_open_phrases(["need_water", "need_water"]))
        ranked = machine.reorder_open_phrases(list(reversed(NEEDS)))
        self.assertIsNotNone(ranked)
        assert ranked is not None
        self.assertEqual(
            [item["id"] for item in ranked["phrases"]],
            list(reversed(NEEDS)),
        )
        self.assertEqual(ranked["highlight_index"], 0)
        self.assertIsNone(machine.reorder_open_phrases(list(reversed(NEEDS))))
        machine.handle("TAP", "tap", 10.0)
        self.assertIsNone(machine.reorder_open_phrases(NEEDS))
        self.assertEqual(
            [item["id"] for item in machine.snapshot()["phrases"]],
            list(reversed(NEEDS)),
        )
        self.assertIsNone(Machine(CATALOG).reorder_open_phrases(list(reversed(NEEDS))))

    def test_select_in_idle_does_not_start_the_timer(self) -> None:
        machine = Machine(CATALOG)
        state, effects = machine.handle("SELECT", "keyboard", 0.0)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, [])
        state, effects = machine.tick(IDLE_TIMEOUT_S)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, [])
