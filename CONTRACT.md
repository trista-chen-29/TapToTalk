# CONTRACT.md: TapToTalk module interfaces

Version: v1.0

This file is the source of truth for every message that crosses a module boundary. All three people agree to changes here before code changes. If code and this file disagree, the file wins until both are fixed in one pull request.

Owners: firmware and bridge (Person 1), web and storage (Person 2), ai (Person 3). Names are still TBD.

Any change to a message, field, or id bumps the minor version in this header, for example v1.0 to v1.1. Breaking changes (a removed field, a renamed id) need all three owners to approve before they merge.

## 1. Pico to bridge (USB serial)

Transport: USB serial at 115200 baud, text, ASCII, one message per line, terminated by `\n`.

Messages sent by the Pico:

| Message | Meaning |
| --- | --- |
| `TAP` | A short, debounced touch on the sensor (under 1 second) |
| `HOLD` | Touch held for 1 second or more |
| `SELECT` | Key switch pressed (backup input; also used as the select action) |

The Pico never sends anything else. Unknown lines are ignored and logged by the bridge.

Board default for this contract: Raspberry Pi Pico or Pico W (Hardware Plan B). Touch input GP14, key switch GP15 with a 10k pull-down to GND, LED data GP16. Switch to ESP32 (Plan A) only if the whole team agrees; do not mix the two pinouts.

## 2. Bridge to Pico (LED commands)

| Command | LED colour | Meaning |
| --- | --- | --- |
| `LED idle` | off | Waiting for input |
| `LED listening` | blue | Patient is in a menu |
| `LED sent` | green | Phrase is being spoken |
| `LED alert` | red | "Call nurse" was sent |

The Pico acknowledges nothing. The bridge re-sends the command if the state has not changed for 5 seconds.

## 3. Keyboard input (fallback)

The bridge maps keys to the same events as the sensor:

| Key | Event |
| --- | --- |
| Space | `TAP` |
| Enter | `HOLD` (on press held for 1 second) |
| Shift+Enter | `SELECT` |
| Esc | Return to idle |

A keyboard event must go through the same state machine as a serial event. No separate code path.

## 4. Phrase data

Phrases live in `bridge/phrases.json`. Each phrase has one id, one text, and one category. List order is the fixed fallback order.

```json
{
  "categories": ["needs", "pain_comfort", "people", "yes_no"],
  "phrases": [
    {"id": "need_water", "text": "I need water", "category": "needs"},
    {"id": "need_bathroom", "text": "I need the bathroom", "category": "needs"},
    {"id": "need_suction", "text": "I need suction", "category": "needs"},
    {"id": "need_position", "text": "Please change my position", "category": "needs"},
    {"id": "pain_here", "text": "I am in pain", "category": "pain_comfort"},
    {"id": "pain_medicine", "text": "I need pain medicine", "category": "pain_comfort"},
    {"id": "comfort_hot", "text": "I am too hot", "category": "pain_comfort"},
    {"id": "comfort_cold", "text": "I am too cold", "category": "pain_comfort"},
    {"id": "person_nurse", "text": "Call nurse", "category": "people"},
    {"id": "person_family", "text": "Please call my family", "category": "people"},
    {"id": "person_doctor", "text": "I want to see the doctor", "category": "people"},
    {"id": "person_thanks", "text": "Thank you", "category": "people"},
    {"id": "yes_yes", "text": "Yes", "category": "yes_no"},
    {"id": "yes_no", "text": "No", "category": "yes_no"},
    {"id": "yes_not_sure", "text": "I am not sure", "category": "yes_no"},
    {"id": "yes_repeat", "text": "Please say that again", "category": "yes_no"}
  ]
}
```

Rules:

- `id` is lowercase snake_case and never changes once shipped (the request log uses it).
- Exactly 4 categories and exactly 16 phrases, four in each category.
- "Call nurse" must exist with id `person_nurse`. The alert path depends on that id.
- The category id `yes_no` and the phrase id `yes_no` ("No") are different fields. Do not rename either one.

## 5. Bridge to web UI

Transport: WebSocket from the bridge at `ws://localhost:8765`. JSON messages.

Bridge to UI, sent on every state change:

```json
{
  "type": "state",
  "mode": "category",
  "highlight_index": 2,
  "category": "needs",
  "phrases": [{"id": "need_water", "text": "I need water"}]
}
```

- `mode` is `idle`, `category`, or `phrase`.
- `highlight_index` indexes categories in category mode and phrases in phrase mode.
- `phrases` is empty in category mode and holds the ranked list in phrase mode.

UI to bridge, sent when a person presses Speak or a phrase is clicked:

```json
{"type": "select", "phrase_id": "need_water", "source": "ui"}
```

The bridge treats a UI select the same as a `SELECT` event.

How selection confirmation, request history, alert updates, acknowledgements, and connection errors reach the UI is still open. See "Open implementation decisions" below. Do not invent new message types without a contract revision.

## 6. Bridge to AI: phrase ranking (Claude)

Module: `ai/rank.py`, function `rank_phrases(context) -> list[str]`.

Input (`context`), and nothing else:

```json
{
  "time_of_day": "evening",
  "category": "needs",
  "last_selections": ["need_water", "pain_here", "need_water"],
  "candidates": ["need_water", "need_bathroom", "need_suction", "need_position"]
}
```

- `time_of_day` is one of `morning`, `afternoon`, `evening`, `night`.
- `last_selections` holds at most 5 phrase ids, oldest first.
- Never include names, IDs, room numbers, timestamps with dates, or free text from the patient.

Output: a list of phrase ids, ranked, containing exactly the candidate ids.

Failure rule: if the call errors, times out after 3 seconds, or returns an id not in `candidates`, return `candidates` unchanged. Cache a successful ranking for 60 seconds, keyed on the input.

The current stub returns `candidates` unchanged and does not call Claude.

## 7. Bridge to AI: speech (Cartesia)

Module: `ai/speak.py`, function `speak(text) -> None`.

- Input: the phrase text only.
- Output: audio played through the laptop speaker.
- Failure rule: if Cartesia fails, `speak` returns without error and the bridge shows the text on screen. Do not block the state machine on audio.

The current stub returns without playing audio and without raising.

## 8. Bridge to AI: nurse alert (Fetch.ai)

Module: `ai/alert.py`, function `send_alert(phrase_id, timestamp) -> None`.

Alert payload to the Fetch.ai agent:

```json
{"type": "nurse_call", "phrase_id": "person_nurse", "timestamp": "2026-10-24T02:15:00Z"}
```

Agent rules:

- Dedupe: a second `nurse_call` within 60 seconds is merged into the first and not re-sent to the dashboard.
- Escalate: if no acknowledgement arrives within 2 minutes, mark the alert as escalated on the dashboard.
- The agent sends the alert to the nurse dashboard tab in the web UI. It does not send anything to an outside party.

The current stub does not send an alert.

## 9. Request log (storage)

Module: `bridge/log.py`, SQLite file `bridge/taptotalk.db` (gitignored).

Table `selections`:

| Column | Type | Note |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | auto |
| `phrase_id` | TEXT | from `phrases.json` |
| `category` | TEXT | |
| `source` | TEXT | `tap`, `keyboard`, or `ui` |
| `selected_at` | TEXT | ISO 8601 UTC |

Table `alerts`:

| Column | Type | Note |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | auto |
| `created_at` | TEXT | ISO 8601 UTC |
| `escalated` | INTEGER | 0 or 1 |
| `acknowledged` | INTEGER | 0 or 1 |

`save_selection(phrase_id, category, source)` writes one `selections` row. Alert inserts, acknowledgements, and escalation updates are not specified yet. See the open alert-lifecycle decision.

"Frequent asks" for the ranker are computed from `selections`, the last 30 days only, when that calculation is in scope. No table stores names or identifiers. The v1.0 ranker input contains only the last five selections. Do not add fields silently.

## 10. State machine (plain language)

These behaviors are agreed. Exact highlight indexes and wraparound are still open.

- Idle: screen shows the 4 categories. Nothing moves until the first tap.
- Category mode: each `TAP` moves the highlight to the next category. `HOLD` or `SELECT` opens the highlighted category.
- Phrase mode: the screen shows that category's 4 phrases, ranked so the most likely one is first. `TAP` moves the highlight. `HOLD` or `SELECT` chooses.
- Speak: the chosen phrase is spoken, shown on screen, saved to the log, and the system returns to idle. If the phrase id is `person_nurse`, the alert also goes to the nurse dashboard.
- Timeout: after 8 seconds with no input, return to idle. Reset the timer on each accepted input. Do not select or speak a phrase because a timeout occurred.

## Open implementation decisions

Resolve these together before integration. v1.0 remains the current interface until an agreed revision is recorded here.

- State transitions: specify the initial highlight, first `TAP` behavior from idle, wraparound, `HOLD` / `SELECT` behavior in every mode, and the post-selection display duration.
- WebSocket gaps: define how selection confirmation, request history, alert updates, acknowledgements, and connection errors reach the UI. Specify validation for UI phrase ids and behavior after reconnect.
- Alert lifecycle: decide how the dashboard acknowledges an alert, how acknowledgements reach the agent and SQLite, and what happens when the agent is unavailable. Specify whether an acknowledged call inside the dedupe window can create a new request.
- Ownership: Person 2 owns storage behavior, but `bridge/log.py` is inside Person 1's folder. Agree on that shared-file boundary before implementation.
- Privacy wording: resolve the conflict between "do not upload request history" in `AGENTS.md` and the last-five phrase ids sent to Claude in section 6. Record the exact allowed data. Use synthetic history in the demo meanwhile.
- Ranking context: the 30-day frequent-asks calculation is not a v1.0 ranker field. Do not add it without a contract revision.
- Firmware: define debounce and re-arm behavior so a long press never also emits `TAP`. Keep sensor reads non-blocking and verify behavior on the actual board.
