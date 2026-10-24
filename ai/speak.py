"""Speech. CONTRACT.md section 9.

This pass calls Cartesia and plays the returned audio. A missing key or a
failed call returns without raising, so on-screen text can stand in.

Model and voice come from Cartesia's Sonic 3.6 docs
(https://docs.cartesia.ai/build-with-cartesia/tts-models/latest):
model ``sonic-3.6``, voice Skylar (en-US female).
Playback uses miniaudio, which talks to Core Audio on this Mac.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

import miniaudio
from dotenv import load_dotenv

# Sonic 3.6 is the current stable model id. Skylar is a documented en-US voice.
MODEL_ID = "sonic-3.6"
VOICE_ID = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"
_REQUEST_TIMEOUT_SECONDS = 15.0
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_SECRET_RE = re.compile(r"sk_car_[A-Za-z0-9_-]+")
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


def speak(phrase_id: str, text: str) -> None:
    """Speak one catalog phrase through Cartesia. Failures stay quiet."""
    if not isinstance(phrase_id, str) or not isinstance(text, str):
        raise TypeError("phrase_id and text must be strings")
    if phrase_id == "" or text == "":
        print("Cartesia speech skipped: phrase_id and text must be non-empty")
        return

    api_key = _load_api_key()
    if api_key is None:
        print("Cartesia speech skipped: CARTESIA_API_KEY is not set")
        return

    try:
        audio = _synthesize(api_key, text)
        _play_wav(audio)
    except Exception as exc:
        print(f"Cartesia speech failed: {_public_reason(exc, api_key)}")
        return
    print("Played Cartesia audio.")


def _load_api_key() -> str | None:
    """Read CARTESIA_API_KEY from the environment or the repo .env file."""
    load_dotenv(_ENV_PATH, override=False)
    key = os.environ.get("CARTESIA_API_KEY", "").strip()
    return key or None


def _synthesize(api_key: str, text: str) -> bytes:
    """Request one WAV clip. The phrase id is not sent."""
    from cartesia import Cartesia

    with Cartesia(api_key=api_key) as client:
        response = client.tts.generate(
            model_id=MODEL_ID,
            transcript=text,
            voice=VOICE_ID,
            language="en",
            output_format={
                "container": "wav",
                "encoding": "pcm_s16le",
                "sample_rate": 44100,
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        return response.read()


def _play_wav(audio: bytes) -> None:
    """Play WAV bytes on the default output device and wait until they finish."""
    decoded = miniaudio.wav_read_s16(audio)
    if decoded.num_frames <= 0:
        raise RuntimeError("Cartesia returned no audio samples")

    finished = threading.Event()
    source = miniaudio.stream_raw_pcm_memory(
        decoded.samples,
        nchannels=decoded.nchannels,
        sample_width=2,
    )

    def watched():
        try:
            requested = yield b""
            while True:
                try:
                    chunk = source.send(requested)
                except StopIteration:
                    return
                requested = yield chunk
        finally:
            finished.set()

    stream = watched()
    next(stream)
    device = miniaudio.PlaybackDevice(
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=decoded.nchannels,
        sample_rate=decoded.sample_rate,
        backends=[miniaudio.Backend.COREAUDIO],
    )
    try:
        if device.backend.lower() == "null":
            raise RuntimeError("no playback device is available")
        device.start(stream)
        if not finished.wait(timeout=decoded.duration + 2.0):
            raise RuntimeError("playback did not finish")
        # Core Audio still has a short buffer after the last frame is queued.
        time.sleep(0.3)
    finally:
        device.close()


def _public_reason(error: BaseException, api_key: str) -> str:
    """Return an error reason with any API key removed."""
    message = f"{type(error).__name__}: {error}".strip()
    if api_key:
        message = message.replace(api_key, "[redacted]")
    message = _SECRET_RE.sub("[redacted]", message)
    message = _BEARER_RE.sub("Bearer [redacted]", message)
    if len(message) > 500:
        message = message[:500] + "..."
    return message


def main() -> None:
    """Speak the catalog phrase 'Call nurse' once."""
    speak("person_nurse", "Call nurse")


if __name__ == "__main__":
    main()
