"""Ranking fallback tests. The client is fake and does not call Claude."""

from __future__ import annotations

import json
import logging
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


def test_poisoned_context_is_absent_from_the_request_and_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Identity fields stay off the Claude call. Only the cleaned payload is logged."""
    secrets = (
        "Ada Lovelace",
        "12B",
        "1980-04-02",
        "bed-1",
        "please tell my daughter I love her",
        "sk-ant-should-not-log",
        "date_of_birth",
        "profile_id",
    )
    context = _context()
    context["last_selections"] = [
        "yes_repeat",
        "pain_here",
        "need_water",
        "yes_yes",
        "yes_no",
        "need_suction",
    ]
    context["name"] = "Ada Lovelace"
    context["room"] = "12B"
    context["date_of_birth"] = "1980-04-02"
    context["profile"] = {
        "profile_id": "bed-1",
        "name": "Ada Lovelace",
        "room": "12B",
        "date_of_birth": "1980-04-02",
        "note": "please tell my daughter I love her",
    }
    context["patient_note"] = "please tell my daughter I love her"
    context["ANTHROPIC_API_KEY"] = "sk-ant-should-not-log"
    expected = {
        "time_of_day": "evening",
        "category": "needs",
        "last_selections": [
            "pain_here",
            "need_water",
            "yes_yes",
            "yes_no",
            "need_suction",
        ],
        "candidates": list(CANDIDATES),
    }
    expected_json = json.dumps(expected, separators=(",", ":"))
    seen: list[dict[str, object]] = []

    def create(**kwargs: object) -> object:
        seen.append(kwargs)
        return _reply(["need_position", "need_water", "need_bathroom", "need_suction"])

    with caplog.at_level(logging.INFO, logger="ai.rank"):
        ranked = rank_phrases(context, client=_Client(create), clock=lambda: 0.0)
        again = _context()
        again["name"] = "someone else entirely"
        again["last_selections"] = list(expected["last_selections"])
        ranked_again = rank_phrases(again, client=_Client(create), clock=lambda: 1.0)

    assert ranked == ["need_position", "need_water", "need_bathroom", "need_suction"]
    assert ranked_again == ranked
    assert len(seen) == 1
    kwargs = seen[0]
    assert set(kwargs) == {"model", "max_tokens", "thinking", "messages"}
    assert kwargs["thinking"] == {"type": "disabled"}
    messages = kwargs["messages"]
    assert isinstance(messages, list)
    content = messages[0]["content"]
    assert isinstance(content, str)
    instruction, body = content.split("\n", 1)
    assert instruction.startswith("Rank the candidate phrase ids")
    assert body == expected_json
    assert json.loads(body) == expected

    rank_logs = [record for record in caplog.records if record.name == "ai.rank"]
    assert len(rank_logs) == 1
    assert rank_logs[0].getMessage() == expected_json
    assert rank_logs[0].getMessage() == body
    blob = "\n".join([content, caplog.text, str(rank_logs[0].args)])
    for secret in secrets:
        assert secret not in blob
    assert "someone else entirely" not in blob


def test_non_catalog_values_skip_the_call_and_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Free text in a contract field is not sent and is not logged."""
    secrets = (
        "Ada Lovelace",
        "12B",
        "1980-04-02",
        "bed-1",
        "please tell my daughter I love her",
    )
    poisoned_candidates = [
        "need_water",
        "please tell my daughter I love her",
    ]
    cases = [
        {
            "time_of_day": "evening",
            "category": "Ada Lovelace is in room 12B",
            "last_selections": ["need_water"],
            "candidates": list(CANDIDATES),
            "name": "Ada Lovelace",
            "room": "12B",
            "date_of_birth": "1980-04-02",
            "profile": {"profile_id": "bed-1", "name": "Ada Lovelace"},
        },
        {
            **_context(),
            "last_selections": ["need_water", "born 1980-04-02"],
        },
        {
            **_context(),
            "candidates": list(poisoned_candidates),
        },
        {
            "time_of_day": "night",
            "category": "Ada Lovelace is in room 12B",
            "last_selections": ["born 1980-04-02", "need_water"],
            "candidates": list(poisoned_candidates),
            "name": "Ada Lovelace",
            "room": "12B",
            "date_of_birth": "1980-04-02",
            "profile": {
                "profile_id": "bed-1",
                "name": "Ada Lovelace",
                "room": "12B",
                "date_of_birth": "1980-04-02",
            },
            "patient_note": "please tell my daughter I love her",
        },
    ]
    calls = {"n": 0}

    def create(**_kwargs: object) -> object:
        calls["n"] += 1
        return _reply(["need_position", "need_water", "need_bathroom", "need_suction"])

    with caplog.at_level(logging.INFO, logger="ai.rank"):
        for context in cases:
            caplog.clear()
            ranked = rank_phrases(context, client=_Client(create), clock=lambda: 0.0)
            assert ranked == context["candidates"]
            assert calls["n"] == 0
            assert [
                record for record in caplog.records if record.name == "ai.rank"
            ] == []
            for secret in secrets:
                assert secret not in caplog.text

        valid = rank_phrases(_context(), client=_Client(create), clock=lambda: 1.0)
    assert calls["n"] == 1
    assert valid == ["need_position", "need_water", "need_bathroom", "need_suction"]


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
    block = SimpleNamespace(type="text", text=json.dumps(ids))
    return SimpleNamespace(content=[block])
