"""Fixed button mode. CONTRACT.md section 4. FR15.

The demo profile stays on the category menu. These tests load a temporary
profile and never write bridge/profile.json.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from bridge.main import RUNTIME, create_app
from bridge.phrases import load_phrases
from bridge.profile import PROFILE_PATH, load_profile
from bridge.state import Machine, NurseCall, Selected

BUTTONS = ["yes_yes", "pain_here", "person_nurse"]


def write_profile(directory: str, **overrides: object) -> Path:
    """Write one temporary profile and return its path."""
    raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    raw["fixed_buttons"] = list(BUTTONS)
    raw.update(overrides)
    path = Path(directory) / "profile.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def machine_for(menu: str) -> Machine:
    """Build a machine from a temporary profile with this menu."""
    with tempfile.TemporaryDirectory() as directory:
        profile = load_profile(write_profile(directory, menu=menu))
    return Machine(
        load_phrases(language=profile["language"]),
        menu=profile["menu"],
        fixed_buttons=profile["fixed_buttons"],
    )


def phrase_ids(state: dict[str, object]) -> list[str]:
    phrases = state["phrases"]
    assert isinstance(phrases, list)
    return [str(item["id"]) for item in phrases]


class FixedMenuTests(unittest.TestCase):
    def test_tap_selects_the_first_button(self) -> None:
        machine = machine_for("fixed")
        state, effects = machine.handle("HOLD", "tap", 0.0)
        self.assertEqual(state["mode"], "phrase")
        self.assertIsNone(state["category"])
        self.assertEqual(state["highlight_index"], 0)
        self.assertEqual(phrase_ids(state), BUTTONS)
        self.assertEqual(state["phrases"][0]["text"], "Yes")
        self.assertEqual(state["phrases"][1]["text"], "I am in pain")
        self.assertEqual(state["phrases"][2]["text"], "Call nurse")
        self.assertEqual(effects, ["LED phrase"])

        state, effects = machine.handle("TAP", "tap", 1.0)
        self.assertEqual(state["mode"], "idle")
        self.assertIsNone(state["category"])
        self.assertEqual(phrase_ids(state), [])
        self.assertEqual(effects, [Selected("yes_yes", "tap"), "LED sent"])

    def test_hold_advances_the_highlight_and_does_not_select(self) -> None:
        machine = machine_for("fixed")
        machine.handle("HOLD", "tap", 0.0)
        state, effects = machine.handle("HOLD", "tap", 1.0)
        self.assertEqual(state["mode"], "phrase")
        self.assertEqual(state["highlight_index"], 1)
        self.assertEqual(phrase_ids(state), BUTTONS)
        self.assertEqual(effects, ["LED phrase"])
        self.assertFalse(any(isinstance(item, Selected) for item in effects))

        state, _effects = machine.handle("HOLD", "tap", 2.0)
        self.assertEqual(state["highlight_index"], 2)
        state, effects = machine.handle("HOLD", "tap", 3.0)
        self.assertEqual(state["highlight_index"], 0)
        self.assertEqual(state["mode"], "phrase")
        self.assertEqual(effects, ["LED phrase"])

    def test_select_chooses_the_highlighted_button(self) -> None:
        machine = machine_for("fixed")
        machine.handle("HOLD", "tap", 0.0)
        machine.handle("HOLD", "tap", 1.0)
        state, effects = machine.handle("SELECT", "keyboard", 2.0)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, [Selected("pain_here", "keyboard"), "LED sent"])

    def test_categories_menu_is_unchanged(self) -> None:
        machine = machine_for("categories")
        state, effects = machine.handle("HOLD", "tap", 0.0)
        self.assertEqual(state["mode"], "category")
        self.assertEqual(state["highlight_index"], 0)
        self.assertEqual(state["category"], "needs")
        self.assertEqual(phrase_ids(state), [])
        self.assertEqual(effects, ["LED listening"])

        state, effects = machine.handle("TAP", "tap", 1.0)
        self.assertEqual(state["mode"], "category")
        self.assertEqual(state["highlight_index"], 1)
        self.assertEqual(state["category"], "pain_comfort")
        self.assertEqual(effects, ["LED listening"])
        self.assertFalse(any(isinstance(item, Selected) for item in effects))

    def test_hold_long_still_calls_the_nurse(self) -> None:
        idle = machine_for("fixed")
        state, effects = idle.handle("HOLD_LONG", "tap", 0.0)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, [NurseCall("person_nurse", "tap"), "LED alert"])

        opened = machine_for("fixed")
        started, _effects = opened.handle("HOLD", "tap", 0.0)
        self.assertEqual(started["mode"], "phrase")
        state, effects = opened.handle("HOLD_LONG", "tap", 1.0)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(phrase_ids(state), [])
        self.assertEqual(effects, [NurseCall("person_nurse", "tap"), "LED alert"])

        categories = machine_for("categories")
        categories.handle("HOLD", "tap", 0.0)
        state, effects = categories.handle("HOLD_LONG", "keyboard", 1.0)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, [NurseCall("person_nurse", "keyboard"), "LED alert"])

    def test_reset_and_eight_second_timeout_return_to_idle(self) -> None:
        machine = machine_for("fixed")
        machine.handle("HOLD", "tap", 0.0)
        state, effects = machine.tick(8.0)
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(effects, ["LED idle"])

        machine.handle("HOLD", "tap", 9.0)
        state, effects = machine.reset()
        self.assertEqual(state["mode"], "idle")
        self.assertIsNone(state["category"])
        self.assertEqual(phrase_ids(state), [])
        self.assertEqual(effects, ["LED idle"])

    def test_fixed_list_is_not_reordered(self) -> None:
        machine = machine_for("fixed")
        machine.handle("HOLD", "tap", 0.0)
        self.assertIsNone(
            machine.reorder_open_phrases(["person_nurse", "yes_yes", "pain_here"])
        )
        self.assertEqual(phrase_ids(machine.snapshot()), BUTTONS)


class FixedButtonBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.save_patch = patch("bridge.main.save_selection", return_value=1)
        self.speak_patch = patch("bridge.main.speak")
        self.save_selection = self.save_patch.start()
        self.speak = self.speak_patch.start()
        self.addCleanup(self.save_patch.stop)
        self.addCleanup(self.speak_patch.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app()
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    def use_profile(self, **overrides: object) -> None:
        path = write_profile(self.directory.name, **overrides)
        self.app[RUNTIME].profile_path = path

    async def test_person_nurse_tap_alerts(self) -> None:
        self.use_profile(menu="fixed")
        async with self.client.ws_connect("/") as socket:
            self.assertEqual((await socket.receive_json(timeout=2))["mode"], "idle")
            self.app[RUNTIME].events.put_nowait(("HOLD", "tap"))
            opened = await socket.receive_json(timeout=2)
            self.assertEqual(opened["mode"], "phrase")
            self.assertIsNone(opened["category"])
            self.assertEqual(phrase_ids(opened), BUTTONS)
            self.assertEqual(opened["phrases"][0]["text"], "Yes")

            self.app[RUNTIME].events.put_nowait(("HOLD", "tap"))
            moved = await socket.receive_json(timeout=2)
            self.assertEqual(moved["highlight_index"], 1)
            self.assertEqual(moved["mode"], "phrase")

            self.app[RUNTIME].events.put_nowait(("HOLD", "tap"))
            moved = await socket.receive_json(timeout=2)
            self.assertEqual(moved["highlight_index"], 2)

            self.app[RUNTIME].events.put_nowait(("TAP", "tap"))
            alert = await socket.receive_json(timeout=2)
            self.assertEqual(alert["type"], "alert")
            self.assertEqual(alert["kind"], "nurse_call")
            self.assertEqual(alert["phrase_id"], "person_nurse")
            self.assertTrue(str(alert["timestamp"]).endswith("Z"))
            state = await socket.receive_json(timeout=2)
            self.assertEqual(state["type"], "state")
            self.assertEqual(state["mode"], "idle")

        self.save_selection.assert_called_once_with("person_nurse", "people", "tap")
        self.speak.assert_called_once_with("person_nurse", "Call nurse")

    async def test_audio_off_selects_and_alerts_without_speech(self) -> None:
        self.use_profile(
            menu="fixed",
            audio_on=False,
            fixed_buttons=["person_nurse", "yes_yes"],
        )
        async with self.client.ws_connect("/") as socket:
            await socket.receive_json(timeout=2)
            self.app[RUNTIME].events.put_nowait(("HOLD", "tap"))
            opened = await socket.receive_json(timeout=2)
            self.assertEqual(phrase_ids(opened), ["person_nurse", "yes_yes"])
            self.app[RUNTIME].events.put_nowait(("TAP", "tap"))
            alert = await socket.receive_json(timeout=2)
            self.assertEqual(alert["kind"], "nurse_call")
            self.assertEqual(alert["phrase_id"], "person_nurse")
            state = await socket.receive_json(timeout=2)
            self.assertEqual(state["mode"], "idle")

        self.save_selection.assert_called_once_with("person_nurse", "people", "tap")
        self.speak.assert_not_called()

    async def test_fixed_mode_does_not_rank(self) -> None:
        calls: list[object] = []

        def rank(context: dict[str, object]) -> list[str]:
            calls.append(context)
            return []

        self.app[RUNTIME].rank_phrases = rank
        self.use_profile(menu="fixed")
        async with self.client.ws_connect("/") as socket:
            await socket.receive_json(timeout=2)
            self.app[RUNTIME].events.put_nowait(("HOLD", "tap"))
            opened = await socket.receive_json(timeout=2)
            self.assertEqual(opened["mode"], "phrase")
            self.assertEqual(phrase_ids(opened), BUTTONS)
        self.assertEqual(calls, [])

    async def test_categories_profile_still_opens_the_category_menu(self) -> None:
        self.use_profile(menu="categories")
        async with self.client.ws_connect("/") as socket:
            await socket.receive_json(timeout=2)
            self.app[RUNTIME].events.put_nowait(("HOLD", "tap"))
            state = await socket.receive_json(timeout=2)
        self.assertEqual(state["mode"], "category")
        self.assertEqual(state["category"], "needs")
        self.assertEqual(state["phrases"], [])
        self.speak.assert_not_called()
