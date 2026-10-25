"""Exercise real HTTP and WebSocket connections to the local bridge."""

import asyncio
import unittest

from aiohttp import WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from bridge.main import create_app


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.client = TestClient(TestServer(create_app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_public_pages_and_assets(self) -> None:
        for path, expected in (
            ("/", "connection-status"),
            ("/index.html", "connection-status"),
            ("/dashboard.html", "Nurse requests"),
            ("/styles.css", ".screen"),
            ("/bridge.js", "Test message received"),
        ):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status, 200)
                self.assertIn(expected, await response.text())

    async def test_each_connection_receives_initial_state(self) -> None:
        for _ in range(2):
            async with self.client.ws_connect("/") as socket:
                state = await socket.receive_json(timeout=2)
                self.assertEqual(
                    state,
                    {
                        "type": "state",
                        "mode": "idle",
                        "highlight_index": 0,
                        "category": None,
                        "phrases": [],
                    },
                )

    async def test_shutdown_closes_connected_browser_sockets(self) -> None:
        socket = await self.client.ws_connect("/")
        await socket.receive_json(timeout=2)
        await asyncio.wait_for(self.client.server.app.shutdown(), timeout=2)
        message = await socket.receive(timeout=2)
        self.assertEqual(message.type, WSMsgType.CLOSE)
        self.assertEqual(message.data, 1001)

    async def test_private_files_are_not_served(self) -> None:
        for path in ("/.env", "/bridge/profile.json", "/CONTRACT.md"):
            response = await self.client.get(path)
            self.assertEqual(response.status, 404)

    async def test_other_website_cannot_open_socket(self) -> None:
        with self.assertRaises(WSServerHandshakeError) as caught:
            await self.client.ws_connect("/", origin="https://example.com")
        self.assertEqual(caught.exception.status, 403)
