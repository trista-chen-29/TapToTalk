"""Locks the v1.1 catalog, profile, and contract stubs."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.hello import echo
from ai.rank import rank_phrases
from ai.speak import speak
from bridge.commands import LED_COMMANDS, cfg_hold_ms
from bridge.log import connect, save_selection
from bridge.phrases import CALL_NURSE_ID, CATEGORIES, load_phrases, phrases_path
from bridge.profile import PROFILE_PATH, load_profile
from bridge.state import Machine, NurseCall

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

    def test_spanish_catalog_keeps_english_ids(self) -> None:
        english = load_phrases(language="en")
        spanish = load_phrases(language="es")
        self.assertEqual(spanish["categories"], list(CATEGORIES))
        self.assertEqual(
            [(item["id"], item["category"]) for item in spanish["phrases"]],
            [(item["id"], item["category"]) for item in english["phrases"]],
        )
        by_id = {item["id"]: item["text"] for item in spanish["phrases"]}
        self.assertEqual(by_id["person_nurse"], "Llame a la enfermera")
        nurse = next(item for item in spanish["phrases"] if item["id"] == CALL_NURSE_ID)
        self.assertEqual(nurse["category"], "people")
        self.assertNotIn("I need water", by_id.values())
        self.assertEqual(len(by_id), 16)
        self.assertEqual(english["phrases"][0]["text"], "I need water")

    def test_mandarin_and_russian_catalogs_keep_english_ids(self) -> None:
        english = load_phrases(language="en")
        english_rows = [(item["id"], item["category"]) for item in english["phrases"]]
        samples = {
            "zh": ("我需要水", "请叫护士"),
            "ru": ("Мне нужна вода", "Позовите медсестру"),
            "hi": ("मुझे पानी चाहिए", "नर्स को बुलाइए"),
            "vi": ("Tôi cần nước", "Gọi y tá"),
        }
        for language, (water, nurse_text) in samples.items():
            with self.subTest(language=language):
                catalog = load_phrases(language=language)
                self.assertEqual(catalog["categories"], list(CATEGORIES))
                rows = [(item["id"], item["category"]) for item in catalog["phrases"]]
                self.assertEqual(rows, english_rows)
                by_id = {item["id"]: item["text"] for item in catalog["phrases"]}
                self.assertEqual(by_id["need_water"], water)
                self.assertEqual(by_id["person_nurse"], nurse_text)
                nurse = next(
                    item for item in catalog["phrases"] if item["id"] == CALL_NURSE_ID
                )
                self.assertEqual(nurse["category"], "people")
                self.assertNotIn("I need water", by_id.values())
                self.assertEqual(len(by_id), 16)
        self.assertEqual(english["phrases"][0]["text"], "I need water")

    def test_missing_language_fails_clearly(self) -> None:
        with self.assertRaises(FileNotFoundError) as raised:
            load_phrases(language="fr")
        self.assertIn("'fr'", str(raised.exception))

    def test_spanish_phrase_text_is_on_screen(self) -> None:
        machine = Machine(load_phrases(language="es"))
        machine.handle("HOLD", "key", 0.0)
        state, _effects = machine.handle("HOLD", "key", 1.0)
        self.assertEqual(state["mode"], "phrase")
        self.assertEqual(state["category"], "needs")
        shown = [(item["id"], item["text"]) for item in state["phrases"]]
        self.assertEqual(
            shown,
            [
                ("need_water", "Necesito agua"),
                ("need_bathroom", "Necesito ir al baño"),
                ("need_suction", "Necesito succión"),
                ("need_position", "Por favor, cambie mi posición"),
            ],
        )

    def test_spanish_catalog_still_calls_the_nurse(self) -> None:
        machine = Machine(load_phrases(language="es"))
        _state, effects = machine.handle("HOLD_LONG", "key", 0.0)
        nurse = next(item for item in effects if isinstance(item, NurseCall))
        self.assertEqual(nurse.phrase_id, CALL_NURSE_ID)

    def test_mandarin_and_russian_text_is_on_screen(self) -> None:
        samples = {
            "zh": ("我需要水", "我需要上厕所", "我需要吸痰", "请帮我换个姿势"),
            "ru": (
                "Мне нужна вода",
                "Мне нужно в туалет",
                "Мне нужно отсасывание",
                "Пожалуйста, поменяйте моё положение",
            ),
            "hi": (
                "मुझे पानी चाहिए",
                "मुझे शौचालय जाना है",
                "मुझे सक्शन चाहिए",
                "कृपया मेरी स्थिति बदलें",
            ),
            "vi": (
                "Tôi cần nước",
                "Tôi cần đi vệ sinh",
                "Tôi cần hút đờm",
                "Xin hãy đổi tư thế cho tôi",
            ),
        }
        for language, texts in samples.items():
            with self.subTest(language=language):
                machine = Machine(load_phrases(language=language))
                machine.handle("HOLD", "key", 0.0)
                state, _effects = machine.handle("HOLD", "key", 1.0)
                shown = [item["text"] for item in state["phrases"]]
                self.assertEqual(shown, list(texts))
                _state, effects = machine.handle("HOLD_LONG", "key", 2.0)
                nurse = next(item for item in effects if isinstance(item, NurseCall))
                self.assertEqual(nurse.phrase_id, CALL_NURSE_ID)


class StubTests(unittest.TestCase):
    def test_echo_returns_input(self) -> None:
        self.assertEqual(echo("taptotalk ai hello"), "taptotalk ai hello")

    def test_rank_keeps_candidate_order(self) -> None:
        candidates = ["need_position", "need_water"]
        saved = {
            name: os.environ.get(name)
            for name in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")
        }
        os.environ["ANTHROPIC_API_KEY"] = ""
        os.environ["CLAUDE_API_KEY"] = ""
        try:
            ranked = rank_phrases(
                {
                    "time_of_day": "evening",
                    "category": "needs",
                    "last_selections": ["need_water"],
                    "candidates": candidates,
                }
            )
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.assertEqual(ranked, candidates)
        self.assertIsNot(ranked, candidates)

    def test_rank_rejects_bad_candidates(self) -> None:
        self.assertEqual(rank_phrases({"candidates": ["need_water", 1]}), [])

    def test_speak_and_alert_are_quiet(self) -> None:
        previous = os.environ.get("CARTESIA_API_KEY")
        os.environ["CARTESIA_API_KEY"] = ""
        try:
            with (
                patch("ai.speak._play_wav"),
                patch("ai.speak._load_api_key", return_value=None),
            ):
                self.assertIsNone(speak("need_water", "I need water"))
        finally:
            if previous is None:
                os.environ.pop("CARTESIA_API_KEY", None)
            else:
                os.environ["CARTESIA_API_KEY"] = previous


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
        self.assertEqual(profile["language"], "en")
        self.assertEqual(profile["hold_ms"], 1000)
        self.assertEqual(profile["fixed_buttons"][-1], "person_nurse")
        self.assertEqual(cfg_hold_ms(profile["hold_ms"]), "CFG hold_ms 1000")
        self.assertIn("LED phrase", LED_COMMANDS)

    def test_language_paths_keep_english_ids(self) -> None:
        self.assertEqual(phrases_path("en").name, "phrases.json")
        self.assertEqual(phrases_path("es").name, "phrases.es.json")
        self.assertEqual(phrases_path("zh").name, "phrases.zh.json")
        self.assertEqual(phrases_path("ru").name, "phrases.ru.json")
        self.assertEqual(phrases_path("hi").name, "phrases.hi.json")
        self.assertEqual(phrases_path("vi").name, "phrases.vi.json")
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

    def test_saved_profile_stays_english_while_es_can_be_selected(self) -> None:
        saved = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved["language"], "en")
        self.assertEqual(load_profile()["language"], "en")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            chosen = dict(saved)
            chosen["language"] = "es"
            path.write_text(json.dumps(chosen), encoding="utf-8")
            selected = load_profile(path)
        self.assertEqual(selected["language"], "es")
        spanish = load_phrases(language=selected["language"])
        self.assertEqual(spanish["phrases"][0]["text"], "Necesito agua")
        self.assertEqual(
            json.loads(PROFILE_PATH.read_text(encoding="utf-8"))["language"],
            "en",
        )

    def test_saved_profile_stays_english_while_zh_and_ru_can_be_selected(self) -> None:
        saved = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        samples = {
            "zh": "我需要水",
            "ru": "Мне нужна вода",
            "hi": "मुझे पानी चाहिए",
            "vi": "Tôi cần nước",
        }
        self.assertEqual(saved["language"], "en")
        for language, text in samples.items():
            with self.subTest(language=language):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "profile.json"
                    chosen = dict(saved)
                    chosen["language"] = language
                    path.write_text(json.dumps(chosen), encoding="utf-8")
                    selected = load_profile(path)
                self.assertEqual(selected["language"], language)
                catalog = load_phrases(language=selected["language"])
                self.assertEqual(catalog["phrases"][0]["text"], text)
        self.assertEqual(
            json.loads(PROFILE_PATH.read_text(encoding="utf-8"))["language"],
            "en",
        )


if __name__ == "__main__":
    unittest.main()
