"""Tap state machine. CONTRACT.md sections 4 and 7.

No serial, keyboard, network, or clock reads happen here. The caller passes
`now` in seconds from any monotonic clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from bridge.phrases import CALL_NURSE_ID, Catalog

IDLE_TIMEOUT_S = 8.0
SENT_LED_S = 2.0
ALERT_LED_S = 5.0
_EVENTS = frozenset({"TAP", "HOLD", "HOLD_LONG", "SELECT"})
_TIMED_LAMPS = frozenset({"LED sent", "LED alert"})


class PhraseView(TypedDict):
    id: str
    text: str


class State(TypedDict):
    type: str
    mode: str
    highlight_index: int
    category: str | None
    phrases: list[PhraseView]


@dataclass(frozen=True)
class Selected:
    """A phrase was chosen. The bridge logs this; it does not speak or store it."""

    phrase_id: str
    source: str


@dataclass(frozen=True)
class NurseCall:
    """A 3-second hold asked for the nurse. phrase_id is person_nurse."""

    phrase_id: str
    source: str


Effect = Selected | NurseCall | str


class Machine:
    """Category and phrase menu from the contract button table.

    Phrase order is the catalog order. Ranking is intentionally not called.
    """

    def __init__(self, catalog: Catalog) -> None:
        self._categories = list(catalog["categories"])
        self._phrases = [
            {
                "id": item["id"],
                "text": item["text"],
                "category": item["category"],
            }
            for item in catalog["phrases"]
        ]
        self._mode = "idle"
        self._highlight = 0
        self._category: str | None = None
        self._open: list[PhraseView] = []
        self._heard_at: float | None = None
        self._led = "LED idle"
        self._led_until: float | None = None

    def snapshot(self) -> State:
        """Current UI state in the section 7 shape."""
        if self._mode == "idle":
            return {
                "type": "state",
                "mode": "idle",
                "highlight_index": 0,
                "category": None,
                "phrases": [],
            }
        phrases: list[PhraseView] = []
        if self._mode == "phrase":
            phrases = [{"id": item["id"], "text": item["text"]} for item in self._open]
        return {
            "type": "state",
            "mode": self._mode,
            "highlight_index": self._highlight,
            "category": self._category,
            "phrases": phrases,
        }

    def handle(self, event: str, source: str, now: float) -> tuple[State, list[Effect]]:
        """Apply one TAP, HOLD, HOLD_LONG, or SELECT.

        Unknown events leave the state as it is. A TAP in idle does the same.
        HOLD is the 1-second action. In idle it starts a session.
        HOLD_LONG is the separate 3-second event from the Pico, and it calls
        the nurse from every mode. A long press still emits HOLD first.
        """
        if event not in _EVENTS:
            return self.snapshot(), []
        if event == "HOLD_LONG":
            return self._call_nurse(source, now)
        if self._mode == "idle":
            if event in {"TAP", "SELECT"}:
                return self.snapshot(), []
            return self._enter_category(now)
        if self._mode == "category":
            self._heard_at = now
            if event == "TAP":
                self._advance(self._categories)
                self._category = self._categories[self._highlight]
                return self.snapshot(), ["LED listening"]
            return self._enter_phrase(now)
        self._heard_at = now
        if event == "TAP":
            self._advance(self._open)
            return self.snapshot(), ["LED phrase"]
        return self._choose(source, now)

    def tick(self, now: float) -> tuple[State, list[Effect]]:
        """Return to idle after 8 quiet seconds, then clear a timed lamp."""
        if (
            self._mode != "idle"
            and self._heard_at is not None
            and now - self._heard_at >= IDLE_TIMEOUT_S
        ):
            self._go_idle()
            self._led_until = None
            return self._lamp("LED idle")
        if self._led_until is not None and now >= self._led_until:
            self._led_until = None
            if self._led in _TIMED_LAMPS:
                return self._lamp("LED idle")
        return self.snapshot(), []

    def reset(self) -> tuple[State, list[Effect]]:
        """Return to idle immediately. Esc uses this path."""
        self._go_idle()
        self._led_until = None
        return self._lamp("LED idle")

    def _enter_category(self, now: float) -> tuple[State, list[Effect]]:
        if not self._categories:
            return self.snapshot(), []
        self._mode = "category"
        self._highlight = 0
        self._category = self._categories[0]
        self._open = []
        self._heard_at = now
        self._led_until = None
        self._led = "LED listening"
        return self.snapshot(), ["LED listening"]

    def _enter_phrase(self, now: float) -> tuple[State, list[Effect]]:
        if not self._categories:
            return self.snapshot(), []
        category = self._categories[self._highlight]
        self._mode = "phrase"
        self._category = category
        self._open = [
            {"id": item["id"], "text": item["text"]}
            for item in self._phrases
            if item["category"] == category
        ]
        self._highlight = 0
        self._heard_at = now
        self._led_until = None
        self._led = "LED phrase"
        return self.snapshot(), ["LED phrase"]

    def _call_nurse(self, source: str, now: float) -> tuple[State, list[Effect]]:
        self._go_idle()
        self._led = "LED alert"
        self._led_until = now + ALERT_LED_S
        return self.snapshot(), [NurseCall(CALL_NURSE_ID, source), "LED alert"]

    def _choose(self, source: str, now: float) -> tuple[State, list[Effect]]:
        if not self._open:
            return self.snapshot(), []
        phrase_id = self._open[self._highlight]["id"]
        self._go_idle()
        self._led = "LED sent"
        self._led_until = now + SENT_LED_S
        return self.snapshot(), [Selected(phrase_id, source), "LED sent"]

    def _advance(self, items: list[object]) -> None:
        count = len(items)
        if count == 0:
            return
        self._highlight = (self._highlight + 1) % count

    def _go_idle(self) -> None:
        self._mode = "idle"
        self._highlight = 0
        self._category = None
        self._open = []
        self._heard_at = None

    def _lamp(self, command: str) -> tuple[State, list[Effect]]:
        if self._led == command:
            return self.snapshot(), []
        self._led = command
        return self.snapshot(), [command]
