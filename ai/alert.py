"""Nurse alert. CONTRACT.md section 8.

The stub does not send anything. A later Fetch.ai agent must dedupe repeats
within 60 seconds and keep the alert inside the local dashboard.
"""

from __future__ import annotations


def send_alert(phrase_id: str, timestamp: str) -> None:
    """Accept a nurse-call request. This stub does not send it."""
    if not isinstance(phrase_id, str) or not isinstance(timestamp, str):
        raise TypeError("phrase_id and timestamp must be strings")
