"""Nurse alerts. CONTRACT.md section 10.

The stub does not send anything. A later Fetch.ai agent must dedupe repeats
of the same kind within 60 seconds and keep the alert on the local dashboard.
"""

from __future__ import annotations

ALERT_KINDS = frozenset({"nurse_call", "no_activity"})


def send_alert(kind: str, phrase_id: str | None, timestamp: str) -> None:
    """Accept a nurse_call or no_activity alert. This stub does not send it."""
    if kind not in ALERT_KINDS:
        raise ValueError("kind must be nurse_call or no_activity")
    if not isinstance(timestamp, str):
        raise TypeError("timestamp must be a string")
    if kind == "no_activity":
        if phrase_id is not None:
            raise ValueError("no_activity phrase_id must be null")
        return
    if not isinstance(phrase_id, str):
        raise TypeError("nurse_call phrase_id must be a string")
