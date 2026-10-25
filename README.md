# TapToTalk

A communication aid prototype. Someone who cannot speak taps once to move through a fixed set of phrases. The laptop speaks the chosen phrase. "Call nurse" shows on a simulated nurse-request dashboard.

This is not a medical device. It has not been tested with patients. The dashboard is not a hospital nurse-call system.

## Layout

| Path | Role |
| --- | --- |
| [`firmware/`](firmware/) | MicroPython on a Pico. Prints `TAP`, `HOLD`, and `SELECT`. |
| [`bridge/`](bridge/) | Laptop process. State machine, bedside profile, phrase catalog, SQLite log. |
| [`bridge/audio/`](bridge/audio/) | Pre-generated phrase and category clips. Empty until the team agrees to commit them. |
| [`web/`](web/) | Patient screen and simulated nurse dashboard. |
| [`ai/`](ai/) | Phrase ranking, speech, and nurse alerts. |
| [`CONTRACT.md`](CONTRACT.md) | Message shapes, v1.1. If code and this file disagree, the file wins. |
| [`AGENTS.md`](AGENTS.md) | Working rules for people and coding agents. |

The board is a Raspberry Pi Pico, chosen 2026-10-23. Touch is GP14, the key switch is GP15, and the three-colour LED is GP16 red, GP17 green, and GP18 blue. The ESP32 is a backup only if the Pico touch module fails.

## What is here

The current prototype includes:

- `.env` is gitignored. Copy [`.env.example`](.env.example) before any API call.
- [`bridge/phrases.json`](bridge/phrases.json) has the 16 English phrase ids. Those ids do not change. Other languages, when added, use `phrases.<language>.json` and keep the same ids.
- [`bridge/profile.json`](bridge/profile.json) is the bedside profile for `bed-1`. It holds settings only, never a name.
- The bridge connects Pico input, keyboard navigation, phrase confirmation,
  local speech clips, selection logging, and simulated nurse alerts.
- `speak(phrase_id, text)` plays a catalog clip, then tries Cartesia if needed.

The bridge serves the local pages and sends current state over WebSocket.
Claude ranking and fixed-button navigation are not connected to the bridge yet.
Use the default categories profile for this demo.

## Run the local bridge

From the repo root, with Python 3.11+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,pico]'
python -m bridge.main
```

Open http://localhost:8765/ in a browser. It should show **Connected to bridge**
and **Test message received: bridge state (idle).** The page receives that state
over `ws://localhost:8765`, not from an HTTP response. Reloading opens a new
connection; if the server stops, the page shows a disconnected status and retries.
The dashboard is at http://localhost:8765/dashboard.html.

Run from the same checkout you are editing. On this laptop that is
`/Users/trista/Documents/ChatGPT/TapToTalk`; an older copy may exist at
`/Users/trista/TapToTalk`. Stop any bridge running from the other copy first.
Only one bridge should run, and only one program should use the Pico USB port.
Close Thonny and serial monitors before starting the bridge.

Stop the server with Ctrl+C. Both services bind only to localhost. Only the
public web files are served. English WAV clips are included; no API key is
required to play them. AI ranking is not needed to navigate or call the nurse.

## Test from the keyboard first (no Pico needed)

Keep both browser pages open. Use the keyboard with focus away from browser
buttons; the global keyboard listener also sees keys used on page controls.

1. Hold Enter for about 1 second, then release. Expect Needs highlighted.
2. Press Space to move to the next category. Shift+Enter opens that category.
3. Press Space to move between phrases. Shift+Enter, or the enabled Speak
   button, confirms the highlighted phrase. Expect speech and a return to idle.
4. Start again and wait 8 seconds without input. Expect a return to idle.
   Esc also cancels a menu. Short touches/Space in idle do nothing.
5. Hold Enter for at least 3 seconds from idle, then release. Expect a Call
   nurse card on the dashboard. Repeated calls within 60 seconds share a card.
6. Test a menu-selected call: hold Enter 1 second, release, press Space twice
   for People, then Shift+Enter twice. Expect Call nurse speech and an alert
   (wait over 60 seconds after the preceding alert to expect a new card).

If keys do nothing on macOS, check System Settings → Privacy & Security →
Accessibility and Input Monitoring for the application running the bridge,
then restart that application/bridge. A connected page alone does not prove
that the keyboard listener has permission.

## Test the Pico

The firmware runs on the Pico, not in laptop Python. With the bridge stopped
and Thonny disconnected, list the ports:

```bash
.venv/bin/python -m serial.tools.list_ports -v
```

Use the Pico port shown above in the commands below; `/dev/cu.usbmodem11201`
was the port on this laptop. If firmware is already installed, back it up
before replacing it:

```bash
.venv/bin/mpremote connect /dev/cu.usbmodem11201 fs cp :main.py /tmp/taptotalk-main-backup.py
.venv/bin/mpremote connect /dev/cu.usbmodem11201 fs cp firmware/main.py :main.py
```

Unplug/replug USB without holding BOOTSEL so the saved `main.py` starts again.
Repeat this after using `mpremote` or Thonny: closing a diagnostic connection
can leave the Pico stopped at its Python prompt.

The connected Pico 2 W's pulsing metal sensor was tested with 1 ms polling,
150 ms touch smoothing, and 30 ms debounce. The old 5 ms polling / 20 ms
smoothing could miss narrow pulses before debounce accepted them. The hold
thresholds remain 1000 ms and 3000 ms. These settings are for this sensor;
a steady-output TTP223 should use the separate setting noted in the firmware.

Start the bridge and watch the patient screen:

1. Hold the touch sensor for about 1 second, then release fully. Expect a
   solid blue LED and category mode. The LED is off while idle by design.
2. Short touches move the highlight. Another 1-second hold, or the key
   switch, opens the highlighted category: the LED blinks blue.
3. Short touches move between phrases; a hold/key press confirms one.
   Expect speech, one logged selection, and green briefly before the LED is off.
4. Hold for at least 3 seconds from idle. Expect a red LED and a nurse card.
   Keep the dashboard open before calling, and account for the 60-second dedupe.
5. Unplug the Pico. The pages stay available and the keyboard still works.
   Reconnect it and repeat a hold.

If touch does nothing but the sensor's own light changes, check that its
**digital output DO/OUT** is wired to **GP14 (physical pin 19)**, not AO or
physical pin 14. The key signal is GP15 (physical pin 20). RGB R/G/B connect
to GP16/17/18 (physical pins 21/22/24); physical pin 23 is GND. Compare the
module labels and [CONTRACT.md](CONTRACT.md) before moving wires, with USB
unplugged. Power the sensor from 3.3V and connect its ground to Pico ground.

Hardware checks must be observed on the actual board. Automated tests below
cover synthetic input and local sockets; they do not certify touch detection,
visible LED colors, or audible speaker output.

## Automated checks

To count real FR1/FR2 inputs separately from the application, stop the bridge
and close Thonny, then run one of these from this checkout:

```bash
.venv/bin/python -m bridge.input_check --source serial --seconds 60
.venv/bin/python -m bridge.input_check --source keyboard --seconds 60
```

The checker prints each event and totals. It does not speak, save selections,
or send nurse alerts. For FR1, try 10 deliberate short touches, 3 key presses,
one 1.5-second touch, then one 4-second touch. Expected totals are `TAP=10`,
`SELECT=3`, `HOLD=2`, `HOLD_LONG=1`. Each long touch emits HOLD first, with no
extra TAP on release. If the check ends before all actions, run the remaining
actions in a fresh check. A release before a threshold must not become a hold
just because software smoothing keeps the input temporarily active.

From the repo root, with Python 3.11+:

```bash
.venv/bin/python -m pytest tests ai/test_rank.py -q
node --test web/*.test.cjs
.venv/bin/ruff check ai bridge tests
.venv/bin/ruff format --check ai bridge tests
```

Use the local bridge URLs above rather than opening the HTML files directly.

Run `python -m ai.hello` separately for the AI hello entry point. Do not run
`firmware/main.py` with laptop Python; it requires MicroPython's `machine` module.

## Secrets

API keys live only in `.env`. Never commit a key, print a key, or hard-code one.

## Team

Person 1 owns `firmware/`, `bridge/`, and `bridge/audio/`. Person 2 owns `web/` and storage behavior. Person 3 owns `ai/`. Names and the Devpost account are still TBD. Merge to `main` through a pull request that someone else approves.
