"""Ranking fallback tests. The client is fake and does not call Claude."""

from __future__ import annotations

import time
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

import ai.rank as rank_module
from ai.rank import rank_phrases


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    with rank_module._cache_lock:
        rank_module._cache.clear()
    yield
    with rank_module._cache_lock:
        rank_module._cache.clear()


CANDIDATES = ["need_water", "need_bathroom", "need_suction", "need_position"]


def test_timeout_returns_original_order() -> None:
    def create(**_kwargs: object) -> object:
        time.sleep(5)
        return _reply(["need_position", "need_suction", "need_bathroom", "need_water"])

    started = time.perf_counter()
    ranked = rank_phrases(_context(), client=_Client(create))
    elapsed = time.perf_counter() - started
    assert ranked == CANDIDATES
    assert 2.5 <= elapsed < 3.5


def test_unknown_id_returns_original_order() -> None:
    def create(**_kwargs: object) -> object:
        return _reply(["need_water", "not_a_phrase", "need_bathroom", "need_suction"])

    ranked = rank_phrases(_context(), client=_Client(create))
    assert ranked == CANDIDATES


def test_valid_permutation_returns_ranked_order() -> None:
    seen: dict[str, str] = {}

    def create(**kwargs: object) -> object:
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert isinstance(content, str)
        seen["content"] = content
        return _reply(["need_position", "need_water", "need_bathroom", "need_suction"])

    context = _context()
    context["last_selections"] = [
        "drop_oldest",
        "pain_here",
        "need_water",
        "yes_yes",
        "yes_no",
        "need_suction",
    ]
    context["room"] = "12"
    context["name"] = "Ada"
    ranked = rank_phrases(context, client=_Client(create))
    assert ranked == ["need_position", "need_water", "need_bathroom", "need_suction"]
    content = seen["content"]
    assert "drop_oldest" not in content
    assert "Ada" not in content
    assert '"room"' not in content
    assert "need_position" in content


def test_identical_calls_within_60_seconds_hit_the_client_once() -> None:
    calls = {"n": 0}

    def create(**_kwargs: object) -> object:
        calls["n"] += 1
        return _reply(["need_position", "need_water", "need_bathroom", "need_suction"])

    first = rank_phrases(_context(), client=_Client(create), clock=lambda: 0.0)
    second = rank_phrases(_context(), client=_Client(create), clock=lambda: 10.0)
    assert calls["n"] == 1
    assert first == second
    assert second == ["need_position", "need_water", "need_bathroom", "need_suction"]


def test_cache_miss_after_61_seconds() -> None:
    calls = {"n": 0}
    now = {"t": 0.0}

    def clock() -> float:
        return now["t"]

    def create(**_kwargs: object) -> object:
        calls["n"] += 1
        return _reply(["need_position", "need_water", "need_bathroom", "need_suction"])

    rank_phrases(_context(), client=_Client(create), clock=clock)
    now["t"] = 61.0
    rank_phrases(_context(), client=_Client(create), clock=clock)
    assert calls["n"] == 2


def test_fallback_is_not_cached() -> None:
    calls = {"n": 0}

    def create(**_kwargs: object) -> object:
        calls["n"] += 1
        raise RuntimeError("down")

    rank_phrases(_context(), client=_Client(create), clock=lambda: 0.0)
    rank_phrases(_context(), client=_Client(create), clock=lambda: 1.0)
    assert calls["n"] == 2


def test_different_last_selections_is_a_cache_miss() -> None:
    calls = {"n": 0}

    def create(**_kwargs: object) -> object:
        calls["n"] += 1
        return _reply(["need_position", "need_water", "need_bathroom", "need_suction"])

    other = _context()
    other["last_selections"] = ["yes_yes"]
    rank_phrases(_context(), client=_Client(create), clock=lambda: 0.0)
    rank_phrases(other, client=_Client(create), clock=lambda: 1.0)
    assert calls["n"] == 2


def test_client_exception_returns_original_order() -> None:
    def create(**_kwargs: object) -> object:
        raise RuntimeError("claude unavailable")

    ranked = rank_phrases(_context(), client=_Client(create))
    assert ranked == CANDIDATES


class _Client:
    def __init__(self, create) -> None:
        self.messages = _Messages(create)


class _Messages:
    def __init__(self, create) -> None:
        self._create = create

    def create(self, **kwargs: object) -> object:
        return self._create(**kwargs)


def _context() -> dict[str, object]:
    return {
        "time_of_day": "evening",
        "category": "needs",
        "last_selections": ["need_water", "pain_here"],
        "candidates": list(CANDIDATES),
    }


def _reply(ids: list[str]) -> object:
    import json

    block = SimpleNamespace(type="text", text=json.dumps(ids))
    return SimpleNamespace(content=[block])
