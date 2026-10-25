"""Phrase ranking. CONTRACT.md section 8.

Claude reorders the candidate ids. A timeout, error, invalid value, or
invalid response returns the candidate list unchanged. A successful ranking
is remembered in memory for 60 seconds. Failures are not cached.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from bridge.phrases import load_phrases

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 3.0
_CACHE_SECONDS = 60.0
_DEFAULT_MODEL = "claude-haiku-5-5"
_TIME_OF_DAY = frozenset({"morning", "afternoon", "evening", "night"})
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_ALLOWED_KEYS = ("time_of_day", "category", "last_selections", "candidates")
_cache: dict[str, tuple[float, list[str]]] = {}
_cache_lock = threading.Lock()


def rank_phrases(
    context: dict[str, object],
    client: object | None = None,
    *,
    clock: Callable[[], float] | None = None,
) -> list[str]:
    """Return candidate ids in ranked order, or the original order on failure."""
    now = time.monotonic if clock is None else clock
    try:
        candidates = _candidate_ids(context)
    except Exception:
        return []
    try:
        payload = _ranking_context(context, candidates)
        if payload is None:
            return candidates
        cached = _cached_ranking(payload, now)
        if cached is not None:
            return cached
        raw = _call_with_deadline(client, payload)
        ranked = _accepted_order(raw, candidates)
        if ranked is None:
            return candidates
        _store_ranking(payload, ranked, now)
        return list(ranked)
    except Exception:
        return candidates


def _cache_key(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cached_ranking(
    payload: dict[str, object],
    clock: Callable[[], float],
) -> list[str] | None:
    key = _cache_key(payload)
    with _cache_lock:
        stored = _cache.get(key)
        if stored is None:
            return None
        stored_at, ranking = stored
        if clock() - stored_at >= _CACHE_SECONDS:
            return None
        return list(ranking)


def _store_ranking(
    payload: dict[str, object],
    ranking: list[str],
    clock: Callable[[], float],
) -> None:
    with _cache_lock:
        _cache[_cache_key(payload)] = (clock(), list(ranking))


def _candidate_ids(context: dict[str, object]) -> list[str]:
    raw = context.get("candidates", [])
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return []
    return list(raw)


def _ranking_context(
    context: dict[str, object],
    candidates: list[str],
) -> dict[str, object] | None:
    """Keep the four contract fields, and only catalog ids as values.

    Extra keys are dropped. ``last_selections`` keeps the newest five
    strings. A category, selection, or candidate that is not in the catalog
    rejects the whole request so nothing is sent.
    """
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
    phrase_ids, categories = _catalog_ids()
    if (
        category not in categories
        or any(item not in phrase_ids for item in selections)
        or any(item not in phrase_ids for item in candidates)
    ):
        return None
    payload = {
        "time_of_day": time_of_day,
        "category": category,
        "last_selections": selections,
        "candidates": candidates,
    }
    return {key: payload[key] for key in _ALLOWED_KEYS}


def _catalog_ids() -> tuple[frozenset[str], frozenset[str]]:
    catalog = load_phrases()
    phrase_ids = frozenset(phrase["id"] for phrase in catalog["phrases"])
    categories = frozenset(catalog["categories"])
    return phrase_ids, categories


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
    body = _payload_json(payload)
    logger.info("%s", body)
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


def _payload_json(payload: dict[str, object]) -> str:
    """The only JSON sent to Claude, in contract key order."""
    return json.dumps(
        {key: payload[key] for key in _ALLOWED_KEYS},
        separators=(",", ":"),
    )


def _prompt(payload: dict[str, object]) -> str:
    return (
        "Rank the candidate phrase ids using only the JSON object below. "
        "Reply with a JSON array of those ids in ranked order, each id once, "
        "and no other text.\n"
        f"{_payload_json(payload)}"
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
