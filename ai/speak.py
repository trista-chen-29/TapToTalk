"""Speech. CONTRACT.md section 7.

The stub returns without playing audio and without raising. Cartesia comes
later. A failure must stay quiet so the on-screen text can stand in.
"""

from __future__ import annotations


def speak(text: str) -> None:
    """Accept phrase text. This stub does not play audio."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
