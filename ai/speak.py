"""Speech. CONTRACT.md section 9.

Play a catalog clip first, then fall back to Cartesia. Missing keys and audio
failures return without raising, so the bridge can keep text on screen.

Model and voice come from Cartesia's Sonic 3.6 docs
(https://docs.cartesia.ai/build-with-cartesia/tts-models/latest):
model ``sonic-3.6``, voice Skylar (en-US female).
Playback uses miniaudio, which talks to Core Audio on this Mac.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

import miniaudio
from dotenv import load_dotenv

from bridge.phrases import load_phrases
from bridge.profile import load_profile

# Sonic 3.6 is the current stable model id. Skylar is a documented en-US voice.
MODEL_ID = "sonic-3.6"
VOICE_ID = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"
_REQUEST_TIMEOUT_SECONDS = 15.0
_AUDIO_DIR = Path(__file__).resolve().parents[1] / "bridge" / "audio"
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_SECRET_RE = re.compile(r"sk_car_[A-Za-z0-9_-]+")
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


def speak(phrase_id: str, text: str) -> None:
    """Play a local catalog clip first; use Cartesia only as a fallback.

    Cartesia receives the catalog text for ``phrase_id``. A different
    ``text`` is refused. This synchronous helper must run off the bridge
    event loop. The bridge remains responsible for selection confirmation
    and on-screen feedback.
    """
    if not isinstance(phrase_id, str) or not isinstance(text, str):
        raise TypeError("phrase_id and text must be strings")
    if phrase_id == "" or text == "":
        print("Cartesia speech skipped: phrase_id and text must be non-empty")
        return

    try:
        profile = load_profile()
        catalog = load_phrases(language=profile["language"])
        known_text = {phrase["id"]: phrase["text"] for phrase in catalog["phrases"]}
        if (
            re.fullmatch(r"[a-z][a-z0-9_]*", phrase_id) is None
            or phrase_id not in known_text
        ):
            print("Speech skipped: unknown phrase id")
            return
        catalog_text = known_text[phrase_id]
        if text != catalog_text:
            print("Speech skipped: text does not match the catalog")
            return
        if not profile["audio_on"] or profile["output"] == "screen":
            return
        # Current clip naming is English-only. Never play an English cached
        # recording for a different language profile.
        root = _AUDIO_DIR.resolve()
        clip = (root / f"{phrase_id}.wav").resolve()
        if root not in clip.parents:
            print("Speech skipped: clip path is outside the audio directory")
            return
    except Exception:
        print("Speech skipped: catalog or profile is unavailable")
        return

    if profile["language"] == "en":
        try:
            if clip.is_file():
                _play_wav(clip.read_bytes())
                print("Played local audio.")
                return
        except Exception:
            # Do not expose arbitrary decoder/device errors or credentials.
            print("Local clip unavailable; trying speech fallback.")

    api_key = _load_api_key()
    if api_key is None:
        print("Cartesia speech skipped: CARTESIA_API_KEY is not set")
        return

    try:
        audio = _synthesize(api_key, catalog_text)
        _play_wav(audio)
    except Exception as exc:
        print(f"Cartesia speech failed: {_public_reason(exc, api_key, catalog_text)}")
        return
    print("Played Cartesia audio.")


_category_stop = threading.Event()
_category_stop_lock = threading.Lock()


def speak_category(category_id: str) -> None:
    """Play the saved category-name clip. Never calls Cartesia.

    A newer highlight or a leave from category mode stops this clip so a tap
    is not stuck behind audio. Missing clips stay silent.
    """
    if not isinstance(category_id, str):
        return
    try:
        profile = load_profile()
        catalog = load_phrases(language=profile["language"])
        if (
            category_id not in catalog["categories"]
            or not profile["audio_on"]
            or profile["output"] == "screen"
            or profile["language"] != "en"
        ):
            return
        root = _AUDIO_DIR.resolve()
        clip = (root / f"cat_{category_id}.wav").resolve()
        if root not in clip.parents or not clip.is_file():
            return
        audio = clip.read_bytes()
    except Exception:
        print("Category clip unavailable.")
        return

    stop = _claim_category_playback()
    try:
        _play_wav(audio, stop=stop)
    except Exception:
        print("Category clip unavailable.")
        return
    if not stop.is_set():
        print("Played category audio.")


def stop_category_audio() -> None:
    """Stop the category-name clip if one is playing."""
    with _category_stop_lock:
        _category_stop.set()


def _claim_category_playback() -> threading.Event:
    """Mark any current category clip as finished and return a fresh stop."""
    global _category_stop
    with _category_stop_lock:
        _category_stop.set()
        stop = threading.Event()
        _category_stop = stop
        return stop


def _load_api_key() -> str | None:
    """Read CARTESIA_API_KEY from the environment or the repo .env file."""
    load_dotenv(_ENV_PATH, override=False)
    key = os.environ.get("CARTESIA_API_KEY", "").strip()
    return key or None


def synthesize(text: str) -> bytes:
    """Return a WAV clip for catalog text. Sends that text and nothing else."""
    if not isinstance(text, str) or text == "":
        raise ValueError("text must be a non-empty string")
    api_key = _load_api_key()
    if api_key is None:
        raise RuntimeError("CARTESIA_API_KEY is not set")
    try:
        return _synthesize(api_key, text)
    except Exception as exc:
        raise RuntimeError(_public_reason(exc, api_key, text)) from None


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


def _play_wav(audio: bytes, *, stop: threading.Event | None = None) -> None:
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

    def stopped() -> bool:
        return stop is not None and stop.is_set()

    def watched():
        try:
            requested = yield b""
            while not stopped():
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
        deadline = time.monotonic() + decoded.duration + 2.0
        while not finished.is_set():
            if stopped() or time.monotonic() >= deadline:
                break
            finished.wait(0.05)
        if not finished.is_set() and not stopped():
            raise RuntimeError("playback did not finish")
        # Core Audio still has a short buffer after the last frame is queued.
        if not stopped():
            time.sleep(0.3)
    finally:
        device.close()


def _public_reason(error: BaseException, api_key: str, request_text: str = "") -> str:
    """Return an error reason with the API key and request text removed.

    Cartesia puts the response body in the exception message, and that body
    can quote the transcript. The request object itself is not printed.
    """
    message = f"{type(error).__name__}: {error}".strip()
    message = _redact(message, api_key)
    message = _redact(message, request_text)
    message = _SECRET_RE.sub("[redacted]", message)
    message = _BEARER_RE.sub("Bearer [redacted]", message)
    if len(message) > 500:
        message = message[:500] + "..."
    return message


def _redact(message: str, secret: str) -> str:
    if secret == "":
        return message
    message = message.replace(secret, "[redacted]")
    escaped = json.dumps(secret)[1:-1]
    if escaped != secret:
        message = message.replace(escaped, "[redacted]")
    return message


def main() -> None:
    """Speak the catalog phrase 'Call nurse' once."""
    speak("person_nurse", "Call nurse")


if __name__ == "__main__":
    main()
