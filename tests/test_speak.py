"""Cartesia speech failure paths. No network and no key material."""

from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ai.speak import _public_reason, speak


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

    def test_mismatched_text_is_not_spoken_or_printed(self) -> None:
        secret = "My name is Ada Lovelace, room 12B, born 1980-04-02"
        buffer = io.StringIO()
        with (
            patch("ai.speak._synthesize", side_effect=AssertionError("called")),
            patch("ai.speak._play_wav", side_effect=AssertionError("played")),
            patch("ai.speak._load_api_key", side_effect=AssertionError("key")),
            redirect_stdout(buffer),
        ):
            result = speak("person_nurse", secret)
        output = buffer.getvalue()
        self.assertIsNone(result)
        self.assertIn("does not match the catalog", output)
        self.assertNotIn("Ada", output)
        self.assertNotIn("12B", output)
        self.assertNotIn("1980-04-02", output)

    def test_failure_reason_strips_catalog_text(self) -> None:
        secret = "sk_car_test_secret_value"
        phrase = "Call nurse"
        previous = os.environ.get("CARTESIA_API_KEY")
        os.environ["CARTESIA_API_KEY"] = secret
        echoed = (
            "Error code: 400 - "
            f"{{'transcript': '{phrase}', 'detail': 'bad'}} for {secret}"
        )
        buffer = io.StringIO()
        try:
            with (
                patch("ai.speak._synthesize", side_effect=RuntimeError(echoed)),
                redirect_stdout(buffer),
            ):
                result = speak("person_nurse", phrase)
        finally:
            if previous is None:
                os.environ.pop("CARTESIA_API_KEY", None)
            else:
                os.environ["CARTESIA_API_KEY"] = previous
        output = buffer.getvalue()
        self.assertIsNone(result)
        self.assertIn("Cartesia speech failed", output)
        self.assertIn("[redacted]", output)
        self.assertNotIn(phrase, output)
        self.assertNotIn(secret, output)
        self.assertNotIn("sk_car_", output)

    def test_public_reason_strips_escaped_request_text(self) -> None:
        text = 'Say "hello"'
        escaped = json.dumps(text)[1:-1]
        reason = _public_reason(
            RuntimeError(f"body {escaped} and {text}"),
            "sk_car_test_secret_value",
            text,
        )
        self.assertNotIn("hello", reason)
        self.assertNotIn(escaped, reason)
        self.assertNotIn("sk_car_", reason)
        self.assertIn("[redacted]", reason)
