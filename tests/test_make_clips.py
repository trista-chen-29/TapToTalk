"""Clip generation uses catalog text only and does not call Cartesia."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.make_clips import ClipJob, clip_jobs, write_clips

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


class WriteClipTests(unittest.TestCase):
    def test_skips_existing_file_unless_force(self) -> None:
        calls: list[str] = []

        def fake(text: str) -> bytes:
            calls.append(text)
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


def _wav() -> bytes:
    return b"RIFF" + b"\x00" * 40
