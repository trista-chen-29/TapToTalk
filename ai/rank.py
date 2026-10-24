"""Phrase ranking. CONTRACT.md section 6.

The stub returns candidates unchanged. A later change may call Claude and
must still fall back to this order on error, timeout, or an unknown id.
"""

from __future__ import annotations


def rank_phrases(context: dict[str, object]) -> list[str]:
    """Return candidate phrase ids. This stub does not reorder them."""
    candidates = context.get("candidates", [])
    if not isinstance(candidates, list) or not all(
        isinstance(item, str) for item in candidates
    ):
        raise TypeError("candidates must be a list of phrase ids")
    return list(candidates)
