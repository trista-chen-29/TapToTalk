"""Category highlight names play from saved clips. FR12."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from bridge.main import RUNTIME, create_app


class CategoryAudioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.speak_patch = patch("bridge.main.speak")
        self.speak_patch.start()
        self.addCleanup(self.speak_patch.stop)
        self.heard: list[str] = []
        self.app = create_app()
        self.runtime = self.app[RUNTIME]
        self.runtime.speak_category = self.heard.append
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def wait_heard(self, count: int) -> None:
        for _ in range(50):
            if len(self.heard) >= count:
                return
            await asyncio.sleep(0.01)
        self.fail(f"heard {self.heard}")

    async def test_category_changes_play_the_saved_name(self) -> None:
        async with self.client.ws_connect("/") as socket:
            await socket.receive_json(timeout=2)
            self.runtime.events.put_nowait(("HOLD", "keyboard"))
            state = await socket.receive_json(timeout=2)
            self.assertEqual(state["category"], "needs")
            await self.wait_heard(1)
            self.runtime.events.put_nowait(("TAP", "keyboard"))
            state = await socket.receive_json(timeout=2)
            self.assertEqual(state["category"], "pain_comfort")
            await self.wait_heard(2)
            self.assertEqual(self.heard, ["needs", "pain_comfort"])
            self.runtime.events.put_nowait(("SELECT", "keyboard"))
            opened = await socket.receive_json(timeout=2)
            self.assertEqual(opened["mode"], "phrase")
            await asyncio.sleep(0.05)
            self.assertEqual(self.heard, ["needs", "pain_comfort"])
