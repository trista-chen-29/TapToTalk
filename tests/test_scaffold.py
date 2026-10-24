"""Locks the Step 0 catalog and the contract stubs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai.alert import send_alert
from ai.hello import echo
from ai.rank import rank_phrases
from ai.speak import speak
from bridge.log import save_selection
from bridge.phrases import CALL_NURSE_ID, CATEGORIES, load_phrases

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
        self.assertIsNone(speak("I need water"))
        self.assertIsNone(send_alert("person_nurse", "2026-10-24T02:15:00Z"))


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

    def test_save_selection_rejects_bad_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "taptotalk.db"
            with self.assertRaises(ValueError):
                save_selection("need_water", "needs", "sensor", db_path=db_path)


if __name__ == "__main__":
    unittest.main()
