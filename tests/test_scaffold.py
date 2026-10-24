"""Locks the v1.1 catalog, profile, and contract stubs."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from ai.alert import send_alert
from ai.hello import echo
from ai.rank import rank_phrases
from ai.speak import speak
from bridge.commands import LED_COMMANDS, cfg_hold_ms
from bridge.log import connect, save_selection
from bridge.phrases import CALL_NURSE_ID, CATEGORIES, load_phrases, phrases_path
from bridge.profile import load_profile

EXPECTED = (
    ("need_water", "I need water", "needs"),
    ("need_bathroom", "I need the bathroom", "needs"),
    ("need_suction", "I need suction", "needs"),
    ("need_position", "Please change my position", "needs"),
    ("pain_here", "I am in pain", "pain_comfort"),
    ("pain_medicine", "I need pain medicine", "pain_comfort"),
    ("comfort_hot", "I am too hot", "pain_comfort"),
    ("comfort_cold", "I am too cold", "pain_comfort"),
    ("person_nurse", "Call nurse", "people"),
    ("person_family", "Please call my family", "people"),
    ("person_doctor", "I want to see the doctor", "people"),
    ("person_thanks", "Thank you", "people"),
    ("yes_yes", "Yes", "yes_no"),
    ("yes_no", "No", "yes_no"),
    ("yes_not_sure", "I am not sure", "yes_no"),
    ("yes_repeat", "Please say that again", "yes_no"),
)


class CatalogTests(unittest.TestCase):
    def test_locked_phrases(self) -> None:
        catalog = load_phrases()
        self.assertEqual(catalog["categories"], list(CATEGORIES))
        rows = [
            (item["id"], item["text"], item["category"]) for item in catalog["phrases"]
        ]
        self.assertEqual(tuple(rows), EXPECTED)
        nurse = next(item for item in catalog["phrases"] if item["id"] == CALL_NURSE_ID)
        self.assertEqual(nurse["text"], "Call nurse")


class StubTests(unittest.TestCase):
    def test_echo_returns_input(self) -> None:
        self.assertEqual(echo("taptotalk ai hello"), "taptotalk ai hello")

    def test_rank_keeps_candidate_order(self) -> None:
        candidates = ["need_position", "need_water"]
        ranked = rank_phrases(
            {
                "time_of_day": "evening",
                "category": "needs",
                "last_selections": ["need_water"],
                "candidates": candidates,
            }
        )
        self.assertEqual(ranked, candidates)
        self.assertIsNot(ranked, candidates)

    def test_rank_rejects_bad_candidates(self) -> None:
        with self.assertRaises(TypeError):
            rank_phrases({"candidates": ["need_water", 1]})

    def test_speak_and_alert_are_quiet(self) -> None:
        previous = os.environ.get("CARTESIA_API_KEY")
        os.environ["CARTESIA_API_KEY"] = ""
        try:
            self.assertIsNone(speak("need_water", "I need water"))
        finally:
            if previous is None:
                os.environ.pop("CARTESIA_API_KEY", None)
            else:
                os.environ["CARTESIA_API_KEY"] = previous
        self.assertIsNone(
            send_alert("nurse_call", "person_nurse", "2026-10-24T02:15:00Z")
        )
        self.assertIsNone(send_alert("no_activity", None, "2026-10-24T02:20:00Z"))

    def test_alert_rejects_a_phrase_on_no_activity(self) -> None:
        with self.assertRaises(ValueError):
            send_alert("no_activity", "person_nurse", "2026-10-24T02:20:00Z")


class LogTests(unittest.TestCase):
    def test_save_selection_inserts_one_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "taptotalk.db"
            row_id = save_selection(
                "need_water",
                "needs",
                "keyboard",
                db_path=db_path,
                selected_at="2026-10-24T02:15:00Z",
            )
            self.assertEqual(row_id, 1)
            self.assertTrue(db_path.exists())

    def test_save_selection_accepts_fixed_and_stores_alert_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "taptotalk.db"
            save_selection("person_nurse", "people", "fixed", db_path=db_path)
            connection = connect(db_path)
            try:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(alerts)")
                }
            finally:
                connection.close()
            self.assertIn("kind", columns)

    def test_save_selection_rejects_bad_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "taptotalk.db"
            with self.assertRaises(ValueError):
                save_selection("need_water", "needs", "sensor", db_path=db_path)


class ProfileTests(unittest.TestCase):
    def test_default_profile_and_commands(self) -> None:
        profile = load_profile()
        self.assertEqual(profile["profile_id"], "bed-1")
        self.assertEqual(profile["hold_ms"], 1000)
        self.assertEqual(profile["fixed_buttons"][-1], "person_nurse")
        self.assertEqual(cfg_hold_ms(profile["hold_ms"]), "CFG hold_ms 1000")
        self.assertIn("LED phrase", LED_COMMANDS)

    def test_language_paths_keep_english_ids(self) -> None:
        self.assertEqual(phrases_path("en").name, "phrases.json")
        self.assertEqual(phrases_path("es").name, "phrases.es.json")
        english = load_phrases()
        translated = {
            "categories": english["categories"],
            "phrases": [
                {**item, "text": item["text"] + " (es)"} for item in english["phrases"]
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "phrases.es.json"
            path.write_text(json.dumps(translated), encoding="utf-8")
            loaded = load_phrases(path)
            self.assertEqual(
                [item["id"] for item in loaded["phrases"]],
                [item["id"] for item in english["phrases"]],
            )
            self.assertNotEqual(loaded["phrases"][0]["text"], "I need water")


if __name__ == "__main__":
    unittest.main()
