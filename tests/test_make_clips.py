"""Clip generation uses catalog text only and does not call Cartesia."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.make_clips import ClipJob, ClipReport, clip_jobs, main, write_clips

PHRASES = Path(__file__).resolve().parents[1] / "bridge" / "phrases.json"


class ClipJobTests(unittest.TestCase):
    def test_catalog_covers_every_phrase_and_category(self) -> None:
        catalog = json.loads(PHRASES.read_text(encoding="utf-8"))
        jobs = clip_jobs(catalog)
        spoken = {job.clip_id: job.text for job in jobs}
        phrase_ids = [item["id"] for item in catalog["phrases"]]
        category_ids = [f"cat_{category}" for category in catalog["categories"]]
        self.assertEqual(list(spoken), phrase_ids + category_ids)
        self.assertEqual(spoken["need_water"], "I need water")
        self.assertEqual(spoken["person_nurse"], "Call nurse")
        self.assertEqual(spoken["cat_needs"], "Needs")
        self.assertEqual(spoken["cat_pain_comfort"], "Pain or comfort")
        self.assertEqual(spoken["cat_people"], "People")
        self.assertEqual(spoken["cat_yes_no"], "Yes or no")

    def test_unknown_category_has_no_spoken_text(self) -> None:
        jobs = clip_jobs({"phrases": [], "categories": ["other"]})
        self.assertEqual(jobs, [ClipJob("cat_other", "")])

    def test_spanish_jobs_use_spanish_text_and_skip_categories(self) -> None:
        catalog = json.loads(
            (PHRASES.parent / "phrases.es.json").read_text(encoding="utf-8")
        )
        jobs = clip_jobs(catalog, language="es")
        spoken = {job.clip_id: job.text for job in jobs}
        phrase_ids = [item["id"] for item in catalog["phrases"]]
        self.assertEqual(list(spoken), phrase_ids)
        self.assertEqual(spoken["need_water"], "Necesito agua")
        self.assertEqual(spoken["person_nurse"], "Llame a la enfermera")
        self.assertTrue(all(not clip_id.startswith("cat_") for clip_id in spoken))

    def test_mandarin_and_russian_jobs_skip_english_category_names(self) -> None:
        samples = {
            "zh": ("我需要水", "请叫护士"),
            "ru": ("Мне нужна вода", "Позовите медсестру"),
        }
        for language, (water, nurse) in samples.items():
            with self.subTest(language=language):
                catalog = json.loads(
                    (PHRASES.parent / f"phrases.{language}.json").read_text(
                        encoding="utf-8"
                    )
                )
                jobs = clip_jobs(catalog, language=language)
                spoken = {job.clip_id: job.text for job in jobs}
                self.assertEqual(spoken["need_water"], water)
                self.assertEqual(spoken["person_nurse"], nurse)
                self.assertTrue(
                    all(not clip_id.startswith("cat_") for clip_id in spoken)
                )


class WriteClipTests(unittest.TestCase):
    def test_skips_existing_file_unless_force(self) -> None:
        calls: list[str] = []

        def fake(text: str, language: str = "en") -> bytes:
            calls.append(text)
            self.assertEqual(language, "en")
            return _wav()

        with tempfile.TemporaryDirectory() as directory:
            audio_dir = Path(directory)
            existing = audio_dir / "need_water.wav"
            existing.write_bytes(b"keep")
            jobs = [ClipJob("need_water", "I need water"), ClipJob("yes_yes", "Yes")]
            with patch("ai.make_clips.synthesize", side_effect=fake):
                report = write_clips(jobs, audio_dir, force=False)
                self.assertEqual(report.written, 1)
                self.assertEqual(report.skipped, 1)
                self.assertEqual(report.failed, ())
                self.assertEqual(calls, ["Yes"])
                self.assertEqual(existing.read_bytes(), b"keep")

                report = write_clips(jobs[:1], audio_dir, force=True)
            self.assertEqual(report.written, 1)
            self.assertEqual(calls, ["Yes", "I need water"])
            self.assertTrue(existing.read_bytes().startswith(b"RIFF"))

    def test_failure_records_the_id_and_writes_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio_dir = Path(directory)
            with patch(
                "ai.make_clips.synthesize",
                side_effect=RuntimeError("down"),
            ):
                report = write_clips(
                    [ClipJob("need_water", "I need water")],
                    audio_dir,
                    force=False,
                )
            self.assertEqual(report.written, 0)
            self.assertEqual(report.failed, ("need_water",))
            self.assertEqual(list(audio_dir.glob("*.wav")), [])

    def test_missing_spoken_text_does_not_call_cartesia(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio_dir = Path(directory)
            with patch(
                "ai.make_clips.synthesize", side_effect=AssertionError("called")
            ):
                report = write_clips(
                    [ClipJob("cat_other", "")],
                    audio_dir,
                    force=False,
                )
            self.assertEqual(report.failed, ("cat_other",))

    def test_spanish_write_passes_spanish_text_without_real_synthesis(self) -> None:
        catalog = json.loads(
            (PHRASES.parent / "phrases.es.json").read_text(encoding="utf-8")
        )
        seen: list[tuple[str, str]] = []

        def fake(text: str, language: str = "en") -> bytes:
            seen.append((text, language))
            return _wav()

        jobs = clip_jobs(catalog, language="es")
        with tempfile.TemporaryDirectory() as directory:
            with patch("ai.make_clips.synthesize", side_effect=fake):
                report = write_clips(
                    jobs,
                    Path(directory),
                    force=False,
                    language="es",
                )
        self.assertEqual(report.failed, ())
        self.assertEqual(report.written, 16)
        self.assertEqual(seen[0], ("Necesito agua", "es"))
        self.assertTrue(all(language == "es" for _text, language in seen))
        self.assertNotIn("Needs", [text for text, _language in seen])


class SpanishClipCommandTests(unittest.TestCase):
    def test_default_command_keeps_english_clips(self) -> None:
        with patch(
            "ai.make_clips.write_clips",
            return_value=ClipReport(0, 0, ()),
        ) as write:
            self.assertEqual(main([]), 0)
        jobs = write.call_args.args[0]
        audio_dir = write.call_args.args[1]
        spoken = {job.clip_id: job.text for job in jobs}
        self.assertEqual(audio_dir.name, "audio")
        self.assertEqual(spoken["need_water"], "I need water")
        self.assertEqual(spoken["person_nurse"], "Call nurse")
        self.assertEqual(spoken["cat_needs"], "Needs")
        self.assertEqual(write.call_args.kwargs["language"], "en")

    def test_spanish_command_uses_a_separate_directory(self) -> None:
        with (
            patch(
                "ai.make_clips.write_clips",
                return_value=ClipReport(0, 0, ()),
            ) as write,
            patch("ai.make_clips.synthesize", side_effect=AssertionError("called")),
        ):
            self.assertEqual(main(["--language", "es"]), 0)
        jobs = write.call_args.args[0]
        audio_dir = write.call_args.args[1]
        self.assertEqual(audio_dir.name, "es")
        self.assertEqual(audio_dir.parent.name, "audio")
        self.assertEqual(jobs[0], ClipJob("need_water", "Necesito agua"))
        self.assertEqual(jobs[8].text, "Llame a la enfermera")
        self.assertTrue(all(not job.clip_id.startswith("cat_") for job in jobs))
        self.assertEqual(write.call_args.kwargs["language"], "es")
        self.assertFalse((audio_dir).exists())

    def test_missing_language_fails_before_writing(self) -> None:
        with (
            patch("ai.make_clips.write_clips", side_effect=AssertionError("write")),
            patch("ai.make_clips.synthesize", side_effect=AssertionError("called")),
            self.assertRaises(FileNotFoundError) as raised,
        ):
            main(["--language", "fr"])
        self.assertIn("'fr'", str(raised.exception))

    def test_mandarin_and_russian_commands_use_separate_directories(self) -> None:
        samples = {
            "zh": ("我需要水", "请叫护士"),
            "ru": ("Мне нужна вода", "Позовите медсестру"),
        }
        for language, (water, nurse) in samples.items():
            with self.subTest(language=language):
                with (
                    patch(
                        "ai.make_clips.write_clips",
                        return_value=ClipReport(0, 0, ()),
                    ) as write,
                    patch(
                        "ai.make_clips.synthesize",
                        side_effect=AssertionError("called"),
                    ),
                ):
                    self.assertEqual(main(["--language", language]), 0)
                jobs = write.call_args.args[0]
                audio_dir = write.call_args.args[1]
                self.assertEqual(audio_dir.name, language)
                self.assertEqual(audio_dir.parent.name, "audio")
                self.assertEqual(jobs[0].text, water)
                self.assertEqual(jobs[8].text, nurse)
                self.assertTrue(all(not job.clip_id.startswith("cat_") for job in jobs))
                self.assertEqual(write.call_args.kwargs["language"], language)
                self.assertFalse(audio_dir.exists())


def _wav() -> bytes:
    return b"RIFF" + b"\x00" * 40
