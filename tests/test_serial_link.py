"""Serial port discovery and the Pico line filter. No real board required."""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

from bridge.serial_link import (
    SERIAL_PORT_ENV,
    SerialLink,
    accept_line,
    find_pico_port,
)


class _ListedPort:
    def __init__(self, vid: int | None, device: str) -> None:
        self.vid = vid
        self.device = device


class FakePort:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)
        self.written: list[bytes] = []
        self.closed = False

    def readline(self) -> bytes:
        if self.closed:
            raise OSError("closed")
        if self._lines:
            return self._lines.pop(0)
        time.sleep(0.02)
        return b""

    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        return len(data)

    def close(self) -> None:
        self.closed = True


class AcceptLineTests(unittest.TestCase):
    def test_exact_events_only(self) -> None:
        self.assertEqual(accept_line("TAP\n"), "TAP")
        self.assertEqual(accept_line("HOLD\r\n"), "HOLD")
        self.assertEqual(accept_line("HOLD_LONG\n"), "HOLD_LONG")
        self.assertEqual(accept_line("SELECT"), "SELECT")
        for line in ("tap\n", "TAP extra\n", " LED idle\n", "TAP \n", "\n", ""):
            with self.subTest(line=line):
                self.assertIsNone(accept_line(line))


class FindPortTests(unittest.TestCase):
    def test_vendor_id_match(self) -> None:
        ports = [
            _ListedPort(0x1234, "/dev/other"),
            _ListedPort(0x2E8A, "/dev/pico"),
        ]
        self.assertEqual(find_pico_port(ports, env=""), "/dev/pico")

    def test_env_override_wins(self) -> None:
        ports = [_ListedPort(0x2E8A, "/dev/pico")]
        self.assertEqual(find_pico_port(ports, env="/dev/custom"), "/dev/custom")

    def test_blank_env_falls_through(self) -> None:
        ports = [_ListedPort(0x2E8A, "/dev/pico")]
        self.assertEqual(find_pico_port(ports, env="  "), "/dev/pico")

    def test_missing_board(self) -> None:
        self.assertIsNone(find_pico_port([_ListedPort(None, "/dev/none")], env=""))

    def test_process_env(self) -> None:
        with patch.dict("os.environ", {SERIAL_PORT_ENV: "/dev/from-env"}):
            self.assertEqual(find_pico_port([], env=None), "/dev/from-env")


class SerialLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_reader_queues_only_known_events(self) -> None:
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        opened = FakePort(
            [b"TAP\n", b"\xff\n", b"nope\n", b"HOLD\r\n", b"HOLD_LONG\n", b"SELECT\n"]
        )
        connected = asyncio.Event()
        link = SerialLink(
            asyncio.get_running_loop(),
            queue,
            on_connect=connected.set,
            port_finder=lambda: "/dev/fake",
            port_opener=lambda _name: opened,
        )
        link.start()
        self.addAsyncCleanup(asyncio.to_thread, link.close)
        await asyncio.wait_for(connected.wait(), timeout=2)
        got = [await asyncio.wait_for(queue.get(), timeout=2) for _ in range(4)]
        self.assertEqual(
            got,
            [
                ("TAP", "tap"),
                ("HOLD", "tap"),
                ("HOLD_LONG", "tap"),
                ("SELECT", "tap"),
            ],
        )
        self.assertTrue(queue.empty())
        link.send("LED listening")
        self.assertIn(b"LED listening\n", opened.written)

    async def test_missing_pico_keeps_running(self) -> None:
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        link = SerialLink(
            asyncio.get_running_loop(),
            queue,
            port_finder=lambda: None,
        )
        with self.assertLogs("bridge.serial_link", level="INFO") as caught:
            link.start()
            await asyncio.sleep(0.05)
            await asyncio.to_thread(link.close)
        self.assertTrue(
            any("no Pico found, keyboard only" in line for line in caught.output)
        )
        self.assertTrue(queue.empty())

    def test_send_before_open_does_not_raise(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            link = SerialLink(loop, asyncio.Queue(), port_finder=lambda: None)
            link.send("LED idle")
            with self.assertLogs("bridge.serial_link", level="WARNING") as caught:
                link.send("bad\ncommand")
            self.assertTrue(any("line break" in line for line in caught.output))
        finally:
            loop.close()
