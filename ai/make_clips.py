"""Write phrase and category clips into bridge/audio/.

Reads bridge/phrases.json and speaks only the phrase text from that file,
plus the spoken category names in CATEGORY_SPOKEN_NAMES. Person 1 owns
bridge/audio/. This script is the only writer.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from ai.speak import synthesize

# Person 1 should confirm the names.
CATEGORY_SPOKEN_NAMES = {
    "needs": "Needs",
    "pain_comfort": "Pain or comfort",
    "people": "People",
    "yes_no": "Yes or no",
}

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PHRASES_PATH = _REPO_ROOT / "bridge" / "phrases.json"
_AUDIO_DIR = _REPO_ROOT / "bridge" / "audio"
_SAFE_ID = re.compile(r"[a-z0-9_]+\Z")


@dataclass(frozen=True)
class ClipJob:
    """One clip: a safe file id and the only text Cartesia may speak."""

    clip_id: str
    text: str


@dataclass(frozen=True)
class ClipReport:
    """Counts from one run. failed holds clip ids, not spoken text."""

    written: int
    skipped: int
    failed: tuple[str, ...]


def clip_jobs(catalog: dict[str, object]) -> list[ClipJob]:
    """Build phrase clips, then category clips, from the catalog only."""
    phrases = catalog.get("phrases")
    categories = catalog.get("categories")
    if not isinstance(phrases, list) or not isinstance(categories, list):
        raise ValueError("phrases.json must contain phrases and categories lists")

    jobs: list[ClipJob] = []
    for item in phrases:
        if not isinstance(item, dict):
            raise ValueError("each phrase must be an object")
        phrase_id = item.get("id")
        text = item.get("text")
        if not isinstance(phrase_id, str) or not isinstance(text, str):
            raise ValueError("each phrase needs a string id and text")
        jobs.append(ClipJob(phrase_id, text))

    for category in categories:
        if not isinstance(category, str):
            raise ValueError("each category must be a string")
        spoken = CATEGORY_SPOKEN_NAMES.get(category)
        if spoken is None:
            jobs.append(ClipJob(f"cat_{category}", ""))
            continue
        jobs.append(ClipJob(f"cat_{category}", spoken))
    return jobs


def write_clips(
    jobs: list[ClipJob],
    audio_dir: Path,
    *,
    force: bool,
) -> ClipReport:
    """Write missing WAV files. An existing file is left in place unless force."""
    written = 0
    skipped = 0
    failed: list[str] = []
    audio_dir.mkdir(parents=True, exist_ok=True)

    for job in jobs:
        try:
            path = _wav_path(audio_dir, job.clip_id)
        except ValueError as exc:
            failed.append(job.clip_id)
            print(f"failed {job.clip_id}: {exc}")
            continue
        if path.exists() and not force:
            skipped += 1
            print(f"skipped {job.clip_id}")
            continue
        if job.text == "":
            failed.append(job.clip_id)
            print(f"failed {job.clip_id}: no spoken text")
            continue
        try:
            audio = synthesize(job.text)
            _write_wav(path, audio)
        except Exception as exc:
            failed.append(job.clip_id)
            print(f"failed {job.clip_id}: {exc}")
            continue
        written += 1
        print(f"wrote {job.clip_id}")

    return ClipReport(written, skipped, tuple(failed))


def main(argv: list[str] | None = None) -> int:
    """Generate clips for every phrase and category."""
    parser = argparse.ArgumentParser(
        description="Write TapToTalk phrase and category clips."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace a clip even when the WAV file already exists.",
    )
    args = parser.parse_args(argv)
    catalog = json.loads(_PHRASES_PATH.read_text(encoding="utf-8"))
    report = write_clips(clip_jobs(catalog), _AUDIO_DIR, force=args.force)
    print(f"written {report.written}")
    print(f"skipped {report.skipped}")
    print(f"failed {len(report.failed)}")
    return 1 if report.failed else 0


def _wav_path(audio_dir: Path, clip_id: str) -> Path:
    if not _SAFE_ID.fullmatch(clip_id):
        raise ValueError("clip id is not a safe filename")
    path = (audio_dir / f"{clip_id}.wav").resolve()
    if audio_dir.resolve() not in path.parents:
        raise ValueError("clip path escapes the audio directory")
    return path


def _write_wav(path: Path, audio: bytes) -> None:
    if len(audio) < 44 or not audio.startswith(b"RIFF"):
        raise RuntimeError("Cartesia returned audio that is not a WAV file")
    partial = path.with_suffix(".wav.partial")
    try:
        partial.write_bytes(audio)
        partial.replace(path)
    finally:
        if partial.exists():
            partial.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
