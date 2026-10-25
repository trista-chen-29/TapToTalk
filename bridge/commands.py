"""Commands the bridge sends to the Pico. CONTRACT.md section 2."""

from __future__ import annotations

LED_COMMANDS: tuple[str, ...] = (
    "LED idle",
    "LED listening",
    "LED phrase",
    "LED sent",
    "LED alert",
)

# How long a brief gap still counts as the same touch. CONTRACT.md section 5.
TOUCH_HOLDOVER_MS_MIN = 20
TOUCH_HOLDOVER_MS_MAX = 400


def cfg_hold_ms(hold_ms: int) -> str:
    """Format the hold-time command, for example CFG hold_ms 1000."""
    if isinstance(hold_ms, bool) or not isinstance(hold_ms, int) or hold_ms <= 0:
        raise ValueError("hold_ms must be a positive integer")
    return f"CFG hold_ms {hold_ms}"


def cfg_touch_holdover_ms(touch_holdover_ms: int) -> str:
    """Format the tap-sensitivity command, for example CFG touch_holdover_ms 150."""
    if (
        isinstance(touch_holdover_ms, bool)
        or not isinstance(touch_holdover_ms, int)
        or not TOUCH_HOLDOVER_MS_MIN <= touch_holdover_ms <= TOUCH_HOLDOVER_MS_MAX
    ):
        raise ValueError("touch_holdover_ms must be an integer from 20 to 400")
    return f"CFG touch_holdover_ms {touch_holdover_ms}"
