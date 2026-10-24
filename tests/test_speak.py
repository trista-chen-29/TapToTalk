"""Cartesia speech failure paths. No network and no key material."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ai.speak import speak


class SpeakFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch("ai.speak._AUDIO_DIR", Path(directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_key_prints_and_returns(self) -> None:
        previous = os.environ.get("CARTESIA_API_KEY")
        os.environ["CARTESIA_API_KEY"] = ""
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                result = speak("person_nurse", "Call nurse")
        finally:
            if previous is None:
                os.environ.pop("CARTESIA_API_KEY", None)
            else:
                os.environ["CARTESIA_API_KEY"] = previous
        self.assertIsNone(result)
        self.assertIn("CARTESIA_API_KEY is not set", buffer.getvalue())

    def test_call_failure_prints_reason_without_the_key(self) -> None:
        secret = "sk_car_test_secret_value"
        previous = os.environ.get("CARTESIA_API_KEY")
        os.environ["CARTESIA_API_KEY"] = secret
        buffer = io.StringIO()
        try:
            with (
                patch(
                    "ai.speak._synthesize",
                    side_effect=RuntimeError(f"request failed for {secret}"),
                ),
                redirect_stdout(buffer),
            ):
                result = speak("person_nurse", "Call nurse")
        finally:
            if previous is None:
                os.environ.pop("CARTESIA_API_KEY", None)
            else:
                os.environ["CARTESIA_API_KEY"] = previous
        output = buffer.getvalue()
        self.assertIsNone(result)
        self.assertIn("Cartesia speech failed", output)
        self.assertIn("request failed", output)
        self.assertNotIn(secret, output)
        self.assertIn("[redacted]", output)

    def test_rejects_non_strings(self) -> None:
        with self.assertRaises(TypeError):
            speak("person_nurse", 1)  # type: ignore[arg-type]
