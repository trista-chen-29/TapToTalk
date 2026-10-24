"""Load the locked phrase catalog. CONTRACT.md section 4."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypedDict

CATEGORIES: tuple[str, ...] = ("needs", "pain_comfort", "people", "yes_no")
CALL_NURSE_ID = "person_nurse"
CALL_NURSE_TEXT = "Call nurse"
PHRASES_PATH = Path(__file__).with_name("phrases.json")
_PHRASE_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class Phrase(TypedDict):
    id: str
    text: str
    category: str


class Catalog(TypedDict):
    categories: list[str]
    phrases: list[Phrase]


def load_phrases(path: Path | None = None) -> Catalog:
    """Return the phrase catalog. List order is the fixed fallback order."""
    catalog_path = path or PHRASES_PATH
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("phrase catalog must be a JSON object")

    categories = raw.get("categories")
    phrases = raw.get("phrases")
    if categories != list(CATEGORIES):
        raise ValueError(f"categories must be {list(CATEGORIES)}")
    if not isinstance(phrases, list) or len(phrases) != 16:
        raise ValueError("catalog must contain exactly 16 phrases")

    seen: set[str] = set()
    per_category = {category: 0 for category in CATEGORIES}
    normalized: list[Phrase] = []
    for item in phrases:
        if not isinstance(item, dict):
            raise ValueError("each phrase must be an object")
        phrase_id = item.get("id")
        text = item.get("text")
        category = item.get("category")
        if not isinstance(phrase_id, str) or _PHRASE_ID.fullmatch(phrase_id) is None:
            raise ValueError(f"invalid phrase id: {phrase_id!r}")
        if phrase_id in seen:
            raise ValueError(f"duplicate phrase id: {phrase_id}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"phrase {phrase_id} needs text")
        if category not in CATEGORIES:
            raise ValueError(f"phrase {phrase_id} has unknown category {category!r}")
        seen.add(phrase_id)
        per_category[category] += 1
        normalized.append({"id": phrase_id, "text": text, "category": category})

    if any(count != 4 for count in per_category.values()):
        raise ValueError("each category must contain exactly 4 phrases")

    nurse = next(item for item in normalized if item["id"] == CALL_NURSE_ID)
    if nurse["text"] != CALL_NURSE_TEXT or nurse["category"] != "people":
        raise ValueError("person_nurse must be the people phrase 'Call nurse'")

    return {"categories": list(CATEGORIES), "phrases": normalized}
