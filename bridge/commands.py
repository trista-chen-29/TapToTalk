"""Commands the bridge sends to the Pico. CONTRACT.md section 2."""

from __future__ import annotations

LED_COMMANDS: tuple[str, ...] = (
    "LED idle",
    "LED listening",
    "LED phrase",
    "LED sent",
    "LED alert",
)


def cfg_hold_ms(hold_ms: int) -> str:
    """Format the hold-time command, for example CFG hold_ms 1000."""
    if isinstance(hold_ms, bool) or not isinstance(hold_ms, int) or hold_ms <= 0:
        raise ValueError("hold_ms must be a positive integer")
    return f"CFG hold_ms {hold_ms}"
