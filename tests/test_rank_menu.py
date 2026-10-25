"""Phrase order follows ranking, and falls back to the catalog. FR8 and FR9."""

from __future__ import annotations

import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from bridge.main import RUNTIME, create_app, time_of_day

NEEDS = ["need_water", "need_bathroom", "need_suction", "need_position"]


def phrase_ids(state: dict[str, object]) -> list[str]:
    phrases = state["phrases"]
    assert isinstance(phrases, list)
    return [str(item["id"]) for item in phrases]


class TimeOfDayTests(unittest.TestCase):
    def test_labels_cover_the_day_without_a_clock_time(self) -> None:
        labels = {
            0: "night",
            4: "night",
            5: "morning",
            11: "morning",
            12: "afternoon",
            16: "afternoon",
            17: "evening",
            20: "evening",
            21: "night",
        }
        self.assertEqual(
            {hour: time_of_day(hour) for hour in labels},
            labels,
        )


class RankMenuTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.save_patch = patch("bridge.main.save_selection", return_value=1)
        self.speak_patch = patch("bridge.main.speak")
        self.recent_patch = patch(
            "bridge.main.recent_phrase_ids",
            return_value=["pain_here", "need_water"],
        )
        self.save_patch.start()
        self.speak_patch.start()
        self.recent_patch.start()
        self.addCleanup(self.save_patch.stop)
        self.addCleanup(self.speak_patch.stop)
        self.addCleanup(self.recent_patch.stop)
        self.app = create_app()
        self.runtime = self.app[RUNTIME]
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def wait_rank(self, previous: asyncio.Task[None] | None) -> None:
        """Wait for the ranking started after ``previous``."""
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            task = self.runtime.rank_task
            if task is not None and task is not previous:
                await asyncio.wait_for(task, timeout=2)
                return
            await asyncio.sleep(0.01)
        self.fail("ranking did not start")

    async def test_ready_ranking_is_the_first_phrase_list(self) -> None:
        seen: dict[str, object] = {}

        def reverse(context: dict[str, object]) -> list[str]:
            seen.update(context)
            candidates = context["candidates"]
            assert isinstance(candidates, list)
            return [str(item) for item in reversed(candidates)]

        self.runtime.rank_phrases = reverse
        async with self.client.ws_connect("/") as socket:
            initial = await socket.receive_json(timeout=2)
            self.assertEqual(initial["mode"], "idle")
            previous = self.runtime.rank_task
            self.runtime.events.put_nowait(("HOLD", "tap"))
            category = await socket.receive_json(timeout=2)
            self.assertEqual(category["category"], "needs")
            await self.wait_rank(previous)
            self.assertEqual(
                set(seen),
                {"time_of_day", "category", "last_selections", "candidates"},
            )
            self.assertEqual(seen["category"], "needs")
            self.assertEqual(seen["last_selections"], ["pain_here", "need_water"])
            self.assertEqual(seen["candidates"], NEEDS)
            self.assertIn(
                seen["time_of_day"],
                {"morning", "afternoon", "evening", "night"},
            )
            self.assertNotIn("I need", str(seen))
            self.runtime.events.put_nowait(("SELECT", "tap"))
            opened = await socket.receive_json(timeout=2)
            self.assertEqual(opened["mode"], "phrase")
            self.assertEqual(opened["highlight_index"], 0)
            self.assertEqual(phrase_ids(opened), list(reversed(NEEDS)))
            with self.assertRaises(TimeoutError):
                await socket.receive_json(timeout=0.2)

    async def test_same_order_and_failure_keep_the_catalog(self) -> None:
        def same(context: dict[str, object]) -> list[str]:
            candidates = context["candidates"]
            assert isinstance(candidates, list)
            return [str(item) for item in candidates]

        self.runtime.rank_phrases = same
        async with self.client.ws_connect("/") as socket:
            await socket.receive_json(timeout=2)
            previous = self.runtime.rank_task
            self.runtime.events.put_nowait(("HOLD", "tap"))
            await socket.receive_json(timeout=2)
            await self.wait_rank(previous)
            self.runtime.events.put_nowait(("SELECT", "tap"))
            opened = await socket.receive_json(timeout=2)
            self.assertEqual(phrase_ids(opened), NEEDS)
            with self.assertRaises(TimeoutError):
                await socket.receive_json(timeout=0.2)

    async def test_ranking_failure_keeps_the_catalog(self) -> None:
        def fail(_context: dict[str, object]) -> list[str]:
            raise RuntimeError("ranking unavailable")

        self.runtime.rank_phrases = fail
        async with self.client.ws_connect("/") as socket:
            await socket.receive_json(timeout=2)
            previous = self.runtime.rank_task
            self.runtime.events.put_nowait(("HOLD", "keyboard"))
            await socket.receive_json(timeout=2)
            await self.wait_rank(previous)
            self.runtime.events.put_nowait(("SELECT", "keyboard"))
            opened = await socket.receive_json(timeout=2)
            self.assertEqual(phrase_ids(opened), NEEDS)
            with self.assertRaises(TimeoutError):
                await socket.receive_json(timeout=0.2)

    async def test_late_ranking_updates_until_the_highlight_moves(self) -> None:
        release = threading.Event()

        def slow(context: dict[str, object]) -> list[str]:
            release.wait(3)
            candidates = context["candidates"]
            assert isinstance(candidates, list)
            return [str(item) for item in reversed(candidates)]

        self.runtime.rank_phrases = slow
        try:
            async with self.client.ws_connect("/") as socket:
                await socket.receive_json(timeout=2)
                self.runtime.events.put_nowait(("HOLD", "tap"))
                await socket.receive_json(timeout=2)
                self.runtime.events.put_nowait(("SELECT", "tap"))
                opened = await socket.receive_json(timeout=2)
                self.assertEqual(phrase_ids(opened), NEEDS)
                release.set()
                ranked = await socket.receive_json(timeout=2)
                self.assertEqual(phrase_ids(ranked), list(reversed(NEEDS)))
                self.assertEqual(ranked["highlight_index"], 0)
        finally:
            release.set()

    async def test_moving_the_highlight_keeps_catalog_order(self) -> None:
        release = threading.Event()

        def slow(context: dict[str, object]) -> list[str]:
            release.wait(3)
            candidates = context["candidates"]
            assert isinstance(candidates, list)
            return [str(item) for item in reversed(candidates)]

        self.runtime.rank_phrases = slow
        try:
            async with self.client.ws_connect("/") as socket:
                await socket.receive_json(timeout=2)
                self.runtime.events.put_nowait(("HOLD", "tap"))
                await socket.receive_json(timeout=2)
                self.runtime.events.put_nowait(("SELECT", "tap"))
                opened = await socket.receive_json(timeout=2)
                self.assertEqual(phrase_ids(opened), NEEDS)
                self.runtime.events.put_nowait(("TAP", "tap"))
                moved = await socket.receive_json(timeout=2)
                self.assertEqual(moved["highlight_index"], 1)
                self.assertEqual(phrase_ids(moved), NEEDS)
                release.set()
                with self.assertRaises(TimeoutError):
                    await socket.receive_json(timeout=0.3)
                self.assertEqual(phrase_ids(self.runtime.machine.snapshot()), NEEDS)
        finally:
            release.set()

    async def test_nurse_call_does_not_wait_for_ranking(self) -> None:
        release = threading.Event()

        def slow(context: dict[str, object]) -> list[str]:
            release.wait(3)
            candidates = context["candidates"]
            assert isinstance(candidates, list)
            return [str(item) for item in candidates]

        self.runtime.rank_phrases = slow
        try:
            async with self.client.ws_connect("/") as socket:
                await socket.receive_json(timeout=2)
                self.runtime.events.put_nowait(("HOLD", "tap"))
                category = await socket.receive_json(timeout=2)
                self.assertEqual(category["mode"], "category")
                self.assertIsNotNone(self.runtime.rank_task)
                started = time.monotonic()
                self.runtime.events.put_nowait(("HOLD_LONG", "tap"))
                first = await socket.receive_json(timeout=1)
                second = await socket.receive_json(timeout=1)
                self.assertLess(time.monotonic() - started, 1)
                self.assertEqual(first["type"], "alert")
                self.assertEqual(first["kind"], "nurse_call")
                self.assertEqual(first["phrase_id"], "person_nurse")
                self.assertEqual(second["mode"], "idle")
        finally:
            release.set()

    async def test_changing_category_ranks_that_category(self) -> None:
        seen: list[list[str]] = []

        def record(context: dict[str, object]) -> list[str]:
            candidates = context["candidates"]
            assert isinstance(candidates, list)
            ids = [str(item) for item in candidates]
            seen.append(ids)
            return ids

        self.runtime.rank_phrases = record
        async with self.client.ws_connect("/") as socket:
            await socket.receive_json(timeout=2)
            previous = self.runtime.rank_task
            self.runtime.events.put_nowait(("HOLD", "tap"))
            await socket.receive_json(timeout=2)
            await self.wait_rank(previous)
            first = self.runtime.rank_task
            self.runtime.events.put_nowait(("TAP", "tap"))
            await socket.receive_json(timeout=2)
            await self.wait_rank(first)
            self.assertEqual(seen[0], NEEDS)
            self.assertEqual(seen[-1][0], "pain_here")
