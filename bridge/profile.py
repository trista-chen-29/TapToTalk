"""Load the bedside profile. CONTRACT.md section 5.

The file holds settings only. profile_id is a label such as bed-1.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypedDict

from bridge.commands import TOUCH_HOLDOVER_MS_MAX, TOUCH_HOLDOVER_MS_MIN
from bridge.phrases import load_phrases

PROFILE_PATH = Path(__file__).with_name("profile.json")
INPUTS = frozenset({"touch", "key", "both"})
OUTPUTS = frozenset({"audio", "screen", "both"})
MENUS = frozenset({"categories", "fixed"})
_PROFILE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class Profile(TypedDict):
    profile_id: str
    input: str
    output: str
    menu: str
    fixed_buttons: list[str]
    language: str
    hold_ms: int
    touch_holdover_ms: int
    audio_on: bool
    idle_alert_minutes: int


def load_profile(path: Path | None = None) -> Profile:
    """Return the bedside profile after checking it against the contract."""
    profile_path = path or PROFILE_PATH
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("profile must be a JSON object")

    profile_id = raw.get("profile_id")
    if not isinstance(profile_id, str) or _PROFILE_ID.fullmatch(profile_id) is None:
        raise ValueError("profile_id must be a label such as bed-1")

    choice_input = raw.get("input")
    output = raw.get("output")
    menu = raw.get("menu")
    if choice_input not in INPUTS:
        raise ValueError("input must be touch, key, or both")
    if output not in OUTPUTS:
        raise ValueError("output must be audio, screen, or both")
    if menu not in MENUS:
        raise ValueError("menu must be categories or fixed")

    language = raw.get("language")
    if not isinstance(language, str) or not language:
        raise ValueError("language must be a string")

    hold_ms = raw.get("hold_ms")
    touch_holdover_ms = raw.get("touch_holdover_ms")
    idle_alert_minutes = raw.get("idle_alert_minutes")
    audio_on = raw.get("audio_on")
    if isinstance(hold_ms, bool) or not isinstance(hold_ms, int) or hold_ms <= 0:
        raise ValueError("hold_ms must be a positive integer")
    if (
        isinstance(touch_holdover_ms, bool)
        or not isinstance(touch_holdover_ms, int)
        or not TOUCH_HOLDOVER_MS_MIN <= touch_holdover_ms <= TOUCH_HOLDOVER_MS_MAX
    ):
        raise ValueError("touch_holdover_ms must be an integer from 20 to 400")
    if (
        isinstance(idle_alert_minutes, bool)
        or not isinstance(idle_alert_minutes, int)
        or idle_alert_minutes <= 0
    ):
        raise ValueError("idle_alert_minutes must be a positive integer")
    if not isinstance(audio_on, bool):
        raise ValueError("audio_on must be true or false")

    buttons = raw.get("fixed_buttons")
    if not isinstance(buttons, list) or not all(
        isinstance(item, str) for item in buttons
    ):
        raise ValueError("fixed_buttons must be a list of phrase ids")
    if len(buttons) != len(set(buttons)):
        raise ValueError("fixed_buttons must not repeat a phrase id")
    known = {item["id"] for item in load_phrases()["phrases"]}
    unknown = [item for item in buttons if item not in known]
    if unknown:
        raise ValueError(f"unknown fixed_buttons: {unknown}")
    if menu == "fixed" and not 2 <= len(buttons) <= 4:
        raise ValueError("fixed menu needs 2 to 4 buttons")
    if menu == "categories" and len(buttons) > 4:
        raise ValueError("fixed_buttons cannot list more than 4 phrase ids")

    return {
        "profile_id": profile_id,
        "input": choice_input,
        "output": output,
        "menu": menu,
        "fixed_buttons": list(buttons),
        "language": language,
        "hold_ms": hold_ms,
        "touch_holdover_ms": touch_holdover_ms,
        "audio_on": audio_on,
        "idle_alert_minutes": idle_alert_minutes,
    }
