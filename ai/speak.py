"""Speech. CONTRACT.md section 9.

The stub returns without playing audio and without raising. A later change
plays bridge/audio/<phrase id>.wav when that clip exists, and otherwise
calls Cartesia. A failure must stay quiet so the on-screen text can stand in.
"""

from __future__ import annotations


def speak(phrase_id: str, text: str) -> None:
    """Accept a phrase id and its text. This stub does not play audio."""
    if not isinstance(phrase_id, str) or not isinstance(text, str):
        raise TypeError("phrase_id and text must be strings")
