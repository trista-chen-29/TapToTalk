# CONTRACT.md: TapToTalk module interfaces

Version: v1.7 (2026-10-25)

Owners: firmware and bridge (Person 1), web and storage (Person 2), ai (Person 3).

This file is the source of truth for every message that crosses a module boundary. All three people agree to a change here before any code changes. If code and this file disagree, this file wins until both are fixed in one pull request.

## Changelog

- v1.7: added profile field `touch_holdover_ms` and `CFG touch_holdover_ms <n>` for tap sensitivity (FR16). Default 150 ms. The Pico accepts 20 to 400 ms. `CFG hold_ms` and the 3000 ms nurse hold are unchanged.
- v1.6: the bridge plays `cat_<category>.wav` when the highlighted category changes (FR12). A missing clip stays silent. Category highlights never call Cartesia.
- v1.5: the bridge calls `rank_phrases` when a category is highlighted (FR8). Catalog order stays on screen when ranking is not ready, fails, or the highlight has moved (FR9).
- v1.4: removed the Fetch.ai agent. Nurse alerts are bridge logic in bridge/main.py, with no external service. The ai module covers only Claude and Cartesia.
- v1.3: a `TAP` in idle is ignored (FR20). A session still starts on `HOLD`.
- v1.2: added the `HOLD_LONG` message for the 3-second direct nurse call (FR19), its keyboard key, and the key switch pull-up wiring note.
- v1.1: added `LED phrase`, the `CFG hold_ms <n>` command, the patient profile file, audio clips, the no-activity alert, the mode-based button rules, and the direct nurse call.
- v1.0: first contract.

## 1. Pico to bridge (USB serial)

Transport: USB serial at 115200 baud, text, ASCII, one message per line, ending in `\n`.

Messages sent by the Pico:

| Message | Meaning |
| --- | --- |
| `TAP` | A short, debounced touch on the touch sensor (shorter than the hold time) |
| `HOLD` | A touch held for at least the hold time (default 1000 ms) |
| `HOLD_LONG` | The same touch still held at 3000 ms. Sent once, after `HOLD`. Fixed, `CFG hold_ms` does not change it |
| `SELECT` | The key switch was pressed (backup input) |

The Pico sends nothing else. The bridge logs and ignores unknown lines.

Board: Raspberry Pi Pico, chosen 2026-10-23. The ESP32 is a backup only, if the Pico touch module fails. Touch input GP14, key switch GP15 with a 10k pull-down to GND (a module with its own resistor that reads 0 when pressed, such as the HW-483, uses the Pico's internal pull-up instead; the messages are the same), LED red GP16, LED green GP17, LED blue GP18. Put 220 ohm in series on each LED colour unless the module already has resistors. Confirm each pin against the module datasheet before wiring.

## 2. Bridge to Pico (commands)

| Command | LED colour | Meaning |
| --- | --- | --- |
| `LED idle` | off | Waiting for input |
| `LED listening` | solid blue | Category mode: the patient is choosing a category |
| `LED phrase` | blinking blue | Phrase mode: the patient is choosing a phrase |
| `LED sent` | green | A phrase is being spoken |
| `LED alert` | red | A nurse call or a no-activity alert was sent |

`CFG hold_ms <n>` sets the hold time in milliseconds for the touch and key inputs. The bridge sends it at the start of each session, from the patient profile. Default `1000`. Example: `CFG hold_ms 1000`. The Pico ignores values outside 200 to 5000 ms, and values that are not below the 3000 ms `HOLD_LONG` time.

`CFG touch_holdover_ms <n>` sets the touch holdover in milliseconds. A gap shorter than this still counts as the same touch. This is the per-patient tap sensitivity (FR16). The bridge sends it when the Pico connects and at the start of each session, from the patient profile, in the same places it sends `CFG hold_ms`. Default `150`. Example: `CFG touch_holdover_ms 150`. The Pico ignores values outside 20 to 400 ms. This command does not change `hold_ms` or the 3000 ms `HOLD_LONG` time.

The Pico acknowledges nothing. The bridge re-sends the last command if the state has not changed for 5 seconds.

The three-colour LED module must show solid and blinking blue. If it cannot make blue, listening and phrase both change to a blink pattern on another colour. Agree that change before wiring, because it changes this table.

## 3. Keyboard input (fallback)

The bridge maps keys to the same events as the sensor. A keyboard event goes through the same state machine as a serial event, with no separate code path.

| Key | Event |
| --- | --- |
| Space | `TAP` |
| Enter, held for the hold time | `HOLD` |
| Enter, held for 3 seconds | `HOLD_LONG` |
| Shift+Enter | `SELECT` |
| Esc | Return to idle |

## 4. Button meaning by mode

This table is the single source for the state machine. The bridge and the Pico both follow it.

| Input | Idle | Category mode | Phrase mode |
| --- | --- | --- | --- |
| `TAP` | Ignored | Highlight the next category | Highlight the next phrase |
| `HOLD` (1 s) | Start a session (see the profile) | Open the phrases in the highlighted category | Choose the highlighted phrase |
| `HOLD_LONG` (3 s) | Send Call nurse directly (FR19) | Same as idle | Same as idle |
| `SELECT` | Ignored | Open the phrases, same as `HOLD` | Choose the highlighted phrase |

- After 8 seconds with no input, the bridge returns to idle.
- Choosing a phrase speaks it, logs it, sets `LED sent`, then returns to idle.
- A deliberate hold is needed to start a session, so touches from a blanket or bed rail do nothing (FR20).
- Holding 1 second in idle starts a session. Holding 3 seconds sends Call nurse. Do not change these times without the team.

## 5. Patient profile

Module: `bridge/profile.json`. One file for the bed the device is on. The nurse sets it at the bedside.

```json
{
  "profile_id": "bed-1",
  "input": "touch",
  "output": "both",
  "menu": "categories",
  "fixed_buttons": ["yes_yes", "pain_here", "person_nurse"],
  "language": "en",
  "hold_ms": 1000,
  "touch_holdover_ms": 150,
  "audio_on": true,
  "idle_alert_minutes": 10
}
```

Rules:

- `profile_id` is a label such as `bed-1`. It never holds a name, a date of birth, or a room number.
- `input` is `touch`, `key`, or `both`. `output` is `audio`, `screen`, or `both`.
- `menu` is `categories` or `fixed`. With `fixed`, `fixed_buttons` lists 2 to 4 phrase ids, and each tap selects one button.
- `language` picks the phrase file and audio clips (FR21).
- `hold_ms`, `touch_holdover_ms`, `audio_on`, and `idle_alert_minutes` are starting defaults. Agree them at the table before the demo.
- `touch_holdover_ms` is the tap sensitivity in milliseconds: how long a brief gap in the touch still counts as the same press. Default `150`. The profile accepts 20 to 400 only.
- Changes apply at the start of the next session.
- Every profile keeps the nurse call working (see section 10).

## 6. Phrase data and audio

Phrases live in `bridge/phrases.json`. Other languages use `bridge/phrases.<language>.json`. Each phrase has one id, one text, and one category. List order in the English file is the fixed fallback order.

The English catalog has these 16 phrases. Ids do not change. A later language file must keep the same ids.

| id | text | category |
| --- | --- | --- |
| `need_water` | I need water | `needs` |
| `need_bathroom` | I need the bathroom | `needs` |
| `need_suction` | I need suction | `needs` |
| `need_position` | Please change my position | `needs` |
| `pain_here` | I am in pain | `pain_comfort` |
| `pain_medicine` | I need pain medicine | `pain_comfort` |
| `comfort_hot` | I am too hot | `pain_comfort` |
| `comfort_cold` | I am too cold | `pain_comfort` |
| `person_nurse` | Call nurse | `people` |
| `person_family` | Please call my family | `people` |
| `person_doctor` | I want to see the doctor | `people` |
| `person_thanks` | Thank you | `people` |
| `yes_yes` | Yes | `yes_no` |
| `yes_no` | No | `yes_no` |
| `yes_not_sure` | I am not sure | `yes_no` |
| `yes_repeat` | Please say that again | `yes_no` |

Rules:

- `id` is lowercase snake_case and never changes once shipped. The request log uses it.
- Exactly 4 categories and 16 phrases. Four phrases in each category.
- `person_nurse` must exist with the text `Call nurse` in the English file. The alert path depends on this id.
- The category id `yes_no` and the phrase id `yes_no` ("No") are different fields. Do not rename either one.
- Audio clips live in `bridge/audio/`. Each phrase has `<phrase id>.wav`, and each category has `cat_<category>.wav` for the highlight name.
- Clips are generated from phrase text only, before the demo. No patient text is ever turned into a clip.
- Commit audio clips only if the team agrees.

## 7. Bridge to web UI

Transport: WebSocket from the bridge at `ws://localhost:8765`. JSON messages.

The bridge also serves the local patient page at `http://localhost:8765/`
and the dashboard at `/dashboard.html`. HTTP and WebSocket share port 8765.
On each WebSocket connection, the bridge sends an initial `state` snapshot
(`mode: idle`, `highlight_index: 0`, `category: null`, `phrases: []`).
The current connection demo displays receipt of this snapshot; it does not
handle selections or drive the menu yet.

State message, sent on every state change:

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
- `highlight_index` indexes categories in category mode, and phrases (or `fixed_buttons`) in phrase mode.
- `phrases` is empty in category mode. In phrase mode it holds the ranked list.

Alert message, sent when a nurse call or a no-activity alert is raised:

```json
{"type": "alert", "kind": "nurse_call", "phrase_id": "person_nurse", "timestamp": "2026-10-24T02:15:00Z"}
```

`kind` is `nurse_call` or `no_activity`. For `no_activity`, `phrase_id` is `null`.

UI to bridge, sent when a person presses Speak or clicks a phrase:

```json
{"type": "select", "phrase_id": "need_water", "source": "ui"}
```

The bridge treats a UI select the same as a `SELECT` event.

How the dashboard sends an acknowledgement is not defined in v1.1. Do not add that message without a contract revision.

## 8. Bridge to AI: phrase ranking (Claude)

Module: `ai/rank.py`, function `rank_phrases(context) -> list[str]`.

Input (`context`) holds only these fields:

```json
{
  "time_of_day": "evening",
  "category": "needs",
  "last_selections": ["need_water", "pain_here", "need_water"],
  "candidates": ["need_water", "need_bathroom", "need_suction", "need_position"]
}
```

- `time_of_day` is `morning`, `afternoon`, `evening`, or `night`.
- `last_selections` holds at most 5 phrase ids, oldest first.
- `candidates` must be ids from the phrase file, in catalog order.
- Never send names, IDs, room numbers, dated timestamps, profile contents, or free text from the patient.

Output: a list of phrase ids, ranked, containing exactly the candidate ids.

Failure rule: if the call errors, times out after 3 seconds, or returns an id not in `candidates`, return `candidates` unchanged. Cache a successful ranking for 60 seconds, keyed on the input.

The bridge calls `rank_phrases` when a category is highlighted. Phrase mode uses that ranking when it is already ready. Otherwise the screen shows catalog order, then replaces it only while the highlight is still the first phrase. A failure, a timeout, an invalid list, or a highlight the patient has already moved leaves catalog order in place. Ranking never blocks a phrase choice or a nurse call.

## 9. Bridge to AI: speech (Cartesia)

Module: `ai/speak.py`, function `speak(phrase_id, text) -> None`.

- If `audio_on` is true and `bridge/audio/<phrase id>.wav` exists, play the clip.
- Otherwise, if the output is `audio` or `both`, call Cartesia with `text` and play the result. Use the clip cache where it exists.
- Failure rule: if Cartesia fails, return without raising, and the bridge shows the text on screen. Never block the state machine on audio.
- Highlight names are spoken with `cat_<category>.wav` when the highlighted category changes. A missing clip, `audio_on` false, or screen-only output stays silent. A highlight is never spoken from a live call during the menu, because that would add network delay to every tap.

Phrase speech plays a local clip when one exists, and otherwise calls Cartesia. A failure returns without raising, and the phrase text stays on screen.

## 10. Nurse alerts (bridge logic, no external service)

Implemented in bridge/main.py (publish and publish_no_activity). No external service.

`kind` is `nurse_call` or `no_activity`.

Payloads:

```json
{"type": "nurse_call", "phrase_id": "person_nurse", "timestamp": "2026-10-24T02:15:00Z"}
```

```json
{"type": "no_activity", "phrase_id": null, "timestamp": "2026-10-24T02:20:00Z"}
```

Sources:

- `nurse_call` comes from choosing `person_nurse` in a menu, from the 3-second direct hold in idle (FR19), or from a fixed button `person_nurse`.
- `no_activity` is sent once when the device has been idle for `idle_alert_minutes`. It is not sent again until the patient starts a new session.

Agent rules:

- Dedupe: a second alert of the same kind within 60 seconds is merged into the first and not sent again to the dashboard.
- Escalate: if no acknowledgement arrives within 2 minutes, mark the alert as escalated on the dashboard.
- The agent sends alerts only to the nurse dashboard in the web UI. It sends nothing to an outside party.
- The nurse call works in every profile, including fixed buttons, audio off, and screen-only output.

The current stub does not send an alert.

## 11. Request log (storage)

Module: `bridge/log.py`, SQLite file `bridge/taptotalk.db` (gitignored).

Table `selections`:

| Column | Type | Note |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | auto |
| `phrase_id` | TEXT | from `phrases.json` |
| `category` | TEXT | |
| `source` | TEXT | `tap`, `keyboard`, `ui`, or `fixed` |
| `selected_at` | TEXT | ISO 8601 UTC |

Table `alerts`:

| Column | Type | Note |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | auto |
| `kind` | TEXT | `nurse_call` or `no_activity` |
| `created_at` | TEXT | ISO 8601 UTC |
| `escalated` | INTEGER | 0 or 1 |
| `acknowledged` | INTEGER | 0 or 1 |

`save_selection(phrase_id, category, source)` writes one `selections` row. It does not write alert rows.

"Frequent asks" for the ranker come from `selections`, the last 30 days only, when that calculation is in scope. No table stores names or identifiers. `profile_id` is not stored in either table. The v1.1 ranker input contains only the last five selections. Do not add fields silently.

## 12. Versioning

- Any change to a message, field, id, command, or button rule bumps the minor version in the header, for example v1.1 to v1.2, and adds a changelog line.
- Breaking changes (a removed field, a renamed id, a changed button rule) need all three owners to approve before they merge.
