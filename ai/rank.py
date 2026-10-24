"""Phrase ranking. CONTRACT.md section 8.

Claude reorders the candidate ids. A timeout, error, or invalid response
returns the candidate list unchanged. Caching is intentionally not here.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

_TIMEOUT_SECONDS = 3.0
_DEFAULT_MODEL = "claude-haiku-5-5"
_TIME_OF_DAY = frozenset({"morning", "afternoon", "evening", "night"})
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_ALLOWED_KEYS = ("time_of_day", "category", "last_selections", "candidates")


def rank_phrases(
    context: dict[str, object],
    client: object | None = None,
) -> list[str]:
    """Return candidate ids in ranked order, or the original order on failure."""
    try:
        candidates = _candidate_ids(context)
    except Exception:
        return []
    try:
        payload = _ranking_context(context, candidates)
        if payload is None:
            return candidates
        raw = _call_with_deadline(client, payload)
        ranked = _accepted_order(raw, candidates)
        return ranked if ranked is not None else candidates
    except Exception:
        return candidates


def _candidate_ids(context: dict[str, object]) -> list[str]:
    raw = context.get("candidates", [])
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return []
    return list(raw)


def _ranking_context(
    context: dict[str, object],
    candidates: list[str],
) -> dict[str, object] | None:
    """Keep the four contract fields. Anything else is dropped."""
    if not candidates:
        return None
    time_of_day = context.get("time_of_day")
    category = context.get("category")
    if (
        time_of_day not in _TIME_OF_DAY
        or not isinstance(category, str)
        or category == ""
    ):
        return None
    raw_selections = context.get("last_selections", [])
    if not isinstance(raw_selections, list):
        return None
    selections = [item for item in raw_selections if isinstance(item, str)][-5:]
    payload = {
        "time_of_day": time_of_day,
        "category": category,
        "last_selections": selections,
        "candidates": candidates,
    }
    return {key: payload[key] for key in _ALLOWED_KEYS}


def _call_with_deadline(client: object | None, payload: dict[str, object]) -> str:
    """Stop waiting after 3 seconds. A hung worker must not block the caller."""
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_invoke, client, payload)
    try:
        return future.result(timeout=_TIMEOUT_SECONDS)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _invoke(client: object | None, payload: dict[str, object]) -> str:
    caller = _bound_client(client)
    message = caller.messages.create(
        model=_model(),
        max_tokens=256,
        messages=[{"role": "user", "content": _prompt(payload)}],
    )
    return _message_text(message)


def _bound_client(client: object | None) -> object:
    if client is not None:
        return client
    from anthropic import Anthropic

    api_key = _load_api_key()
    if api_key is None:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    # max_retries=0 keeps the SDK from retrying past the 3-second limit.
    created = Anthropic(api_key=api_key, timeout=_TIMEOUT_SECONDS, max_retries=0)
    return created.with_options(timeout=_TIMEOUT_SECONDS, max_retries=0)


def _prompt(payload: dict[str, object]) -> str:
    body = json.dumps(
        {key: payload[key] for key in _ALLOWED_KEYS},
        separators=(",", ":"),
    )
    return (
        "Rank the candidate phrase ids using only the JSON object below. "
        "Reply with a JSON array of those ids in ranked order, each id once, "
        "and no other text.\n"
        f"{body}"
    )


def _message_text(message: object) -> str:
    blocks = getattr(message, "content", None)
    if not isinstance(blocks, list):
        raise RuntimeError("ranking response has no content")
    parts: list[str] = []
    for block in blocks:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "")
            if isinstance(text, str):
                parts.append(text)
    if not parts:
        raise RuntimeError("ranking response has no text")
    return "".join(parts)


def _accepted_order(raw: str, candidates: list[str]) -> list[str] | None:
    parsed = json.loads(raw.strip())
    if not isinstance(parsed, list) or not all(
        isinstance(item, str) for item in parsed
    ):
        return None
    if Counter(parsed) != Counter(candidates):
        return None
    return list(parsed)


def _model() -> str:
    load_dotenv(_ENV_PATH, override=False)
    model = os.environ.get("CLAUDE_MODEL", "").strip()
    return model or _DEFAULT_MODEL


def _load_api_key() -> str | None:
    """Read the key from .env. The example file names it ANTHROPIC_API_KEY."""
    load_dotenv(_ENV_PATH, override=False)
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None
