"""Load the locked phrase catalog. CONTRACT.md section 6."""

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
_LANGUAGE = re.compile(r"^[a-z]{2,8}$")


class Phrase(TypedDict):
    id: str
    text: str
    category: str


class Catalog(TypedDict):
    categories: list[str]
    phrases: list[Phrase]


def phrases_path(language: str = "en") -> Path:
    """English stays in phrases.json. Other languages use phrases.<language>.json."""
    if language == "en":
        return PHRASES_PATH
    if _LANGUAGE.fullmatch(language) is None:
        raise ValueError("language must be a short lowercase code such as en")
    return PHRASES_PATH.with_name(f"phrases.{language}.json")


def load_phrases(path: Path | None = None, *, language: str = "en") -> Catalog:
    """Return the phrase catalog. English list order is the fixed fallback order."""
    catalog_path = path if path is not None else phrases_path(language)
    if not catalog_path.is_file():
        if path is None:
            raise FileNotFoundError(f"no phrase catalog for language {language!r}")
        raise FileNotFoundError(f"phrase catalog not found: {catalog_path}")
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
    if nurse["category"] != "people":
        raise ValueError("person_nurse must stay in the people category")
    if catalog_path.name == "phrases.json" and nurse["text"] != CALL_NURSE_TEXT:
        raise ValueError("person_nurse must be the people phrase 'Call nurse'")
    if catalog_path.name != "phrases.json":
        english_ids = [item["id"] for item in load_phrases()["phrases"]]
        if [item["id"] for item in normalized] != english_ids:
            raise ValueError(
                "a language file must keep the English phrase ids in order"
            )

    return {"categories": list(CATEGORIES), "phrases": normalized}
