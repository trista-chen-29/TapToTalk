"""Ranking fallback tests. The client is fake and does not call Claude."""

from __future__ import annotations

import time
from types import SimpleNamespace

from ai.rank import rank_phrases

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
