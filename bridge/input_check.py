"""Count real FR1/FR2 input without speaking, logging selections, or sending alerts.

Stop the bridge and close Thonny first. Run `python -m bridge.input_check`
for Pico input, or add `--source keyboard` to test the keyboard listener.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import Counter

from bridge.commands import cfg_hold_ms, cfg_touch_holdover_ms
from bridge.keyboard import KeyboardLink
from bridge.profile import load_profile
from bridge.serial_link import SerialLink


async def check_input(seconds: int, source: str) -> None:
    """Print each received input event and totals for one diagnostic session."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    profile = load_profile()
    link: SerialLink | None = None
    keyboard: KeyboardLink | None = None
    counts: Counter[str] = Counter()

    def connected() -> None:
        print("Pico connected. Reading events from installed firmware.", flush=True)
        if link is not None:
            link.send(cfg_hold_ms(profile["hold_ms"]))
            link.send(cfg_touch_holdover_ms(profile["touch_holdover_ms"]))

    try:
        if source in {"serial", "both"}:
            link = SerialLink(loop, queue, on_connect=connected)
            link.start()
        if source in {"keyboard", "both"}:
            keyboard = KeyboardLink(loop, queue, profile["hold_ms"])
            keyboard.start()
        print(
            f"Listening for {seconds}s. Events are counted only; "
            "no speech, selection records, or nurse alerts.",
            flush=True,
        )
        deadline = loop.time() + seconds
        while (remaining := deadline - loop.time()) > 0:
            try:
                event, origin = await asyncio.wait_for(queue.get(), timeout=remaining)
            except TimeoutError:
                break
            counts[event] += 1
            print(f"{origin}: {event} (total {counts[event]})", flush=True)
    finally:
        if keyboard is not None:
            keyboard.close()
        if link is not None:
            await asyncio.to_thread(link.close)
        print(
            "Totals: "
            + ", ".join(
                f"{event}={counts[event]}"
                for event in ("TAP", "HOLD", "HOLD_LONG", "SELECT", "RESET")
            ),
            flush=True,
        )


def main() -> None:
    """Run a bounded, local-only input check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", choices=("serial", "keyboard", "both"), default="serial"
    )
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error("--seconds must be between 1 and 600")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        asyncio.run(check_input(args.seconds, args.source))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
