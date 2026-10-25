"""USB serial link to the Pico. CONTRACT.md sections 1 and 2.

A missing board must not stop the bridge. Keyboard input keeps working.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable, Iterable
from typing import Protocol

import serial
from serial.tools import list_ports

logger = logging.getLogger(__name__)

PICO_VID = 0x2E8A
SERIAL_PORT_ENV = "TAPTOTALK_SERIAL_PORT"
BAUD = 115200
READ_TIMEOUT_S = 0.2
RETRY_S = 1.0
MAX_SERIAL_LINE_BYTES = 64
SERIAL_EVENTS = frozenset({"TAP", "HOLD", "HOLD_LONG", "SELECT"})


class SerialPort(Protocol):
    def readline(self, size: int = -1) -> bytes: ...

    def write(self, data: bytes) -> int: ...

    def close(self) -> None: ...


def accept_line(line: str) -> str | None:
    """Return TAP, HOLD, HOLD_LONG, or SELECT when the line is exactly that."""
    text = line.strip("\r\n")
    if text in SERIAL_EVENTS:
        return text
    return None


def find_pico_port(
    ports: Iterable[object] | None = None,
    *,
    env: str | None = None,
) -> str | None:
    """Find a Raspberry Pi Pico by USB vendor id, unless the env var is set."""
    if env is None:
        env = os.environ.get(SERIAL_PORT_ENV, "")
    chosen = env.strip()
    if chosen:
        return chosen
    found = list_ports.comports() if ports is None else ports
    for port in found:
        vid = getattr(port, "vid", None)
        device = getattr(port, "device", None)
        if vid == PICO_VID and isinstance(device, str) and device:
            return device
    return None


def open_serial(port_name: str) -> serial.Serial:
    """Open the Pico at the contract baud rate."""
    return serial.Serial(
        port=port_name,
        baudrate=BAUD,
        timeout=READ_TIMEOUT_S,
        write_timeout=READ_TIMEOUT_S,
        exclusive=True,
    )


class SerialLink:
    """Read Pico events on a thread and write commands from the bridge loop."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[tuple[str, str]],
        *,
        on_connect: Callable[[], None] | None = None,
        port_finder: Callable[[], str | None] | None = None,
        port_opener: Callable[[str], SerialPort] | None = None,
    ) -> None:
        self._loop = loop
        self._queue = queue
        self._on_connect = on_connect
        self._find_port = port_finder or find_pico_port
        self._open_port = port_opener or open_serial
        self._stop = threading.Event()
        self._io_lock = threading.Lock()
        self._port: SerialPort | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the reader. A second call does nothing."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="taptotalk-serial",
            daemon=True,
        )
        self._thread.start()

    def send(self, command: str) -> None:
        """Write one command line. Drop it if the Pico is not open."""
        if "\n" in command or "\r" in command:
            logger.warning("refusing serial command with a line break")
            return
        try:
            payload = (command + "\n").encode("ascii")
        except UnicodeEncodeError:
            logger.warning("refusing non-ascii serial command")
            return
        with self._io_lock:
            port = self._port
            if port is None:
                return
            try:
                port.write(payload)
            except Exception:
                logger.warning("serial write failed")

    def close(self) -> None:
        """Stop the reader and close the port. Safe to call more than once."""
        self._stop.set()
        with self._io_lock:
            port = self._port
            self._port = None
        if port is not None:
            try:
                port.close()
            except Exception:
                logger.warning("could not close serial port")
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _run(self) -> None:
        missing_logged = False
        while not self._stop.is_set():
            try:
                name = self._find_port()
            except Exception:
                logger.warning("serial port scan failed")
                name = None
            if not name:
                if not missing_logged:
                    logger.info("no Pico found, keyboard only")
                    missing_logged = True
                if self._stop.wait(RETRY_S):
                    return
                continue
            missing_logged = False
            try:
                port = self._open_port(name)
            except Exception:
                logger.warning("could not open serial port %s", name)
                if self._stop.wait(RETRY_S):
                    return
                continue
            with self._io_lock:
                self._port = port
            logger.info("Pico serial open %s", name)
            self._schedule_connect()
            try:
                self._read(port)
            finally:
                with self._io_lock:
                    owns_port = self._port is port
                    if owns_port:
                        self._port = None
                # close() takes ownership when shutdown interrupts a read.
                # Do not concurrently close the same descriptor twice.
                if owns_port:
                    try:
                        port.close()
                    except Exception:
                        logger.warning("could not close serial port")
            if self._stop.wait(RETRY_S):
                return

    def _read(self, port: SerialPort) -> None:
        pending = bytearray()
        discard_line = False
        while not self._stop.is_set():
            with self._io_lock:
                if self._port is not port:
                    return
            # Serial is full duplex. A blocking read must not own the write/close
            # lock: the bridge sends CFG and LED commands even with no input.
            try:
                raw = port.readline(MAX_SERIAL_LINE_BYTES + 1)
            except Exception:
                if not self._stop.is_set():
                    logger.warning("serial read failed")
                return
            if not raw:
                continue
            # readline() may return a partial line when its timeout expires.
            # Wait for LF, including when a chunk happens to be exactly HOLD:
            # the remaining bytes may be _LONG rather than a separate event.
            for byte in raw:
                if byte == 10:
                    if not discard_line:
                        self._accept_complete_line(pending)
                    pending.clear()
                    discard_line = False
                elif not discard_line:
                    if len(pending) >= MAX_SERIAL_LINE_BYTES:
                        pending.clear()
                        discard_line = True
                        logger.info("ignored oversized serial line")
                    else:
                        pending.append(byte)

    def _accept_complete_line(self, raw: bytearray) -> None:
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            logger.info("ignored non-ascii serial line")
            return
        event = accept_line(text)
        if event is not None:
            self._emit(event)
        elif text.strip("\r\n"):
            logger.info("ignored unknown serial line")

    def _emit(self, event: str) -> None:
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, (event, "tap"))
        except RuntimeError:
            logger.warning("dropped serial event; event loop is closed")

    def _schedule_connect(self) -> None:
        if self._on_connect is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._on_connect)
        except RuntimeError:
            logger.warning("could not report serial connect")
