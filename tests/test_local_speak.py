"""Local-first speech routing with synthetic catalog IDs and mocked playback."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.speak import speak, speak_category


class LocalSpeakTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.audio_dir = Path(directory.name)
        self.profile = {"audio_on": True, "output": "both", "language": "en"}
        catalog = {"phrases": [{"id": "synthetic_phrase", "text": "Synthetic phrase"}]}
        for target, value in (
            ("_AUDIO_DIR", self.audio_dir),
            ("load_profile", self.profile),
            ("load_phrases", catalog),
        ):
            patcher = patch(
                f"ai.speak.{target}",
                **(
                    {"return_value": value}
                    if target != "_AUDIO_DIR"
                    else {"new": value}
                ),
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        self.clip = self.audio_dir / "synthetic_phrase.wav"

    def test_local_clip_plays_without_key_or_network(self) -> None:
        self.clip.write_bytes(b"synthetic-audio")
        with (
            patch("ai.speak._play_wav") as play,
            patch("ai.speak._load_api_key", side_effect=AssertionError("key accessed")),
            patch("ai.speak._synthesize", side_effect=AssertionError("network called")),
        ):
            self.assertIsNone(speak("synthetic_phrase", "Synthetic phrase"))
        play.assert_called_once_with(b"synthetic-audio")

    def test_missing_clip_uses_existing_live_fallback(self) -> None:
        with (
            patch("ai.speak._load_api_key", return_value="synthetic-key"),
            patch("ai.speak._synthesize", return_value=b"live-audio") as synth,
            patch("ai.speak._play_wav") as play,
        ):
            speak("synthetic_phrase", "Synthetic phrase")
        synth.assert_called_once_with("synthetic-key", "Synthetic phrase")
        play.assert_called_once_with(b"live-audio")

    def test_failed_local_playback_uses_live_fallback(self) -> None:
        self.clip.write_bytes(b"broken-clip")
        with (
            patch("ai.speak._load_api_key", return_value="synthetic-key"),
            patch("ai.speak._synthesize", return_value=b"live-audio") as synth,
            patch(
                "ai.speak._play_wav", side_effect=[RuntimeError("bad clip"), None]
            ) as play,
        ):
            speak("synthetic_phrase", "Synthetic phrase")
        synth.assert_called_once()
        self.assertEqual(play.call_count, 2)

    def test_both_playback_paths_failing_return_without_error(self) -> None:
        self.clip.write_bytes(b"broken-clip")
        with (
            patch("ai.speak._load_api_key", return_value="synthetic-key"),
            patch("ai.speak._synthesize", return_value=b"live-audio"),
            patch("ai.speak._play_wav", side_effect=RuntimeError("no output device")),
        ):
            self.assertIsNone(speak("synthetic_phrase", "Synthetic phrase"))

    def test_failed_clip_without_key_returns_for_text_fallback(self) -> None:
        self.clip.write_bytes(b"broken-clip")
        with (
            patch("ai.speak._play_wav", side_effect=RuntimeError("bad clip")),
            patch("ai.speak._load_api_key", return_value=None),
            patch("ai.speak._synthesize") as synth,
        ):
            self.assertIsNone(speak("synthetic_phrase", "Synthetic phrase"))
        synth.assert_not_called()

    def test_unknown_and_path_traversal_ids_never_play_or_call_network(self) -> None:
        with (
            patch("ai.speak._play_wav") as play,
            patch("ai.speak._load_api_key") as key,
        ):
            for phrase_id in ("unknown_phrase", "../synthetic_phrase", "/tmp/clip", ""):
                speak(phrase_id, "Synthetic phrase")
        play.assert_not_called()
        key.assert_not_called()

    def test_symlink_outside_audio_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "clip.wav"
            outside.write_bytes(b"outside")
            self.clip.symlink_to(outside)
            with (
                patch("ai.speak._play_wav") as play,
                patch("ai.speak._load_api_key") as key,
            ):
                speak("synthetic_phrase", "Synthetic phrase")
            play.assert_not_called()
            key.assert_not_called()

    def test_audio_off_and_screen_only_make_no_audio_or_network_calls(self) -> None:
        self.clip.write_bytes(b"synthetic-audio")
        with (
            patch("ai.speak._play_wav") as play,
            patch("ai.speak._load_api_key") as key,
        ):
            self.profile["audio_on"] = False
            speak("synthetic_phrase", "Synthetic phrase")
            self.profile.update(audio_on=True, output="screen")
            speak("synthetic_phrase", "Synthetic phrase")
        play.assert_not_called()
        key.assert_not_called()

    def test_other_language_never_plays_english_cached_clip(self) -> None:
        self.clip.write_bytes(b"english-audio")
        self.profile["language"] = "es"
        with (
            patch("ai.speak._load_api_key", return_value=None),
            patch("ai.speak._play_wav") as play,
        ):
            speak("synthetic_phrase", "Synthetic phrase")
        play.assert_not_called()


class CategoryClipTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.audio_dir = Path(directory.name)
        self.profile = {"audio_on": True, "output": "both", "language": "en"}
        self.catalog = {
            "categories": ["needs", "pain_comfort", "people", "yes_no"],
            "phrases": [],
        }
        for target, value in (
            ("_AUDIO_DIR", self.audio_dir),
            ("load_profile", self.profile),
            ("load_phrases", self.catalog),
        ):
            patcher = patch(
                f"ai.speak.{target}",
                **(
                    {"return_value": value}
                    if target != "_AUDIO_DIR"
                    else {"new": value}
                ),
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_category_clip_plays_without_a_live_call(self) -> None:
        clip = self.audio_dir / "cat_needs.wav"
        clip.write_bytes(b"needs-audio")
        with (
            patch("ai.speak._play_wav") as play,
            patch("ai.speak._load_api_key", side_effect=AssertionError("key accessed")),
            patch("ai.speak._synthesize", side_effect=AssertionError("network called")),
        ):
            self.assertIsNone(speak_category("needs"))
        play.assert_called_once()
        self.assertEqual(play.call_args.args[0], b"needs-audio")
        self.assertIn("stop", play.call_args.kwargs)

    def test_missing_category_clip_stays_silent(self) -> None:
        with (
            patch("ai.speak._play_wav") as play,
            patch("ai.speak._load_api_key") as key,
        ):
            speak_category("pain_comfort")
        play.assert_not_called()
        key.assert_not_called()

    def test_audio_off_and_other_language_skip_the_clip(self) -> None:
        clip = self.audio_dir / "cat_needs.wav"
        clip.write_bytes(b"needs-audio")
        with patch("ai.speak._play_wav") as play:
            self.profile["audio_on"] = False
            speak_category("needs")
            self.profile.update(audio_on=True, output="screen")
            speak_category("needs")
            self.profile.update(output="both", language="es")
            speak_category("needs")
            speak_category("not_a_category")
        play.assert_not_called()

    def test_a_new_highlight_stops_the_previous_clip(self) -> None:
        for name in ("cat_needs.wav", "cat_pain_comfort.wav"):
            (self.audio_dir / name).write_bytes(b"audio")
        stops = []

        def play(_audio: bytes, *, stop: object) -> None:
            stops.append(stop)

        with patch("ai.speak._play_wav", side_effect=play):
            speak_category("needs")
            speak_category("pain_comfort")
        self.assertTrue(stops[0].is_set())
        self.assertFalse(stops[1].is_set())


class RealCatalogSpeechTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.audio_dir = Path(directory.name)
        self.profile = {"audio_on": True, "output": "both", "language": "en"}
        for target, value in (
            ("_AUDIO_DIR", self.audio_dir),
            ("load_profile", self.profile),
        ):
            patcher = patch(
                f"ai.speak.{target}",
                **(
                    {"return_value": value}
                    if target != "_AUDIO_DIR"
                    else {"new": value}
                ),
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_english_profile_still_plays_its_wav(self) -> None:
        (self.audio_dir / "need_water.wav").write_bytes(b"english-water")
        with (
            patch("ai.speak._play_wav") as play,
            patch("ai.speak._load_api_key", side_effect=AssertionError("key")),
            patch("ai.speak._synthesize", side_effect=AssertionError("network")),
        ):
            speak("need_water", "I need water")
        play.assert_called_once_with(b"english-water")

    def test_spanish_text_does_not_play_english_wav_or_call_cartesia(self) -> None:
        (self.audio_dir / "need_water.wav").write_bytes(b"english-water")
        self.profile["language"] = "es"
        with (
            patch("ai.speak._play_wav") as play,
            patch("ai.speak._load_api_key", return_value=None),
            patch("ai.speak._synthesize", side_effect=AssertionError("network")),
        ):
            speak("need_water", "Necesito agua")
        play.assert_not_called()

    def test_spanish_rejects_english_phrase_text(self) -> None:
        (self.audio_dir / "need_water.wav").write_bytes(b"english-water")
        self.profile["language"] = "es"
        with (
            patch("ai.speak._play_wav") as play,
            patch("ai.speak._load_api_key", side_effect=AssertionError("key")),
            patch("ai.speak._synthesize", side_effect=AssertionError("network")),
        ):
            speak("need_water", "I need water")
        play.assert_not_called()

    def test_spanish_category_highlight_stays_silent(self) -> None:
        (self.audio_dir / "cat_needs.wav").write_bytes(b"english-needs")
        self.profile["language"] = "es"
        with (
            patch("ai.speak._play_wav") as play,
            patch("ai.speak._load_api_key", side_effect=AssertionError("key")),
            patch("ai.speak._synthesize", side_effect=AssertionError("network")),
        ):
            speak_category("needs")
        play.assert_not_called()
