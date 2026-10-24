# TapToTalk

A communication aid prototype. Someone who cannot speak taps once to move through a fixed set of phrases. The laptop speaks the chosen phrase. "Call nurse" shows on a simulated nurse-request dashboard.

This is not a medical device. It has not been tested with patients. The dashboard is not a hospital nurse-call system.

## Layout

| Path | Role |
| --- | --- |
| [`firmware/`](firmware/) | MicroPython on a Pico. Prints `TAP`, `HOLD`, and `SELECT`. |
| [`bridge/`](bridge/) | Laptop process. State machine, phrase catalog, SQLite log. |
| [`web/`](web/) | Patient screen and simulated nurse dashboard. |
| [`ai/`](ai/) | Phrase ranking, speech, and the nurse-alert call. |
| [`CONTRACT.md`](CONTRACT.md) | Message shapes. If code and this file disagree, the file wins. |
| [`AGENTS.md`](AGENTS.md) | Working rules for people and coding agents. |

The board default is a Raspberry Pi Pico or Pico W (Plan B): touch on GP14, key switch on GP15, LED on GP16. ESP32 (Plan A) is the alternate. Do not mix the two pinouts unless the whole team switches.

## What is here

This is the Friday-night scaffold:

- `.env` is gitignored. Copy [`.env.example`](.env.example) before any API call.
- [`bridge/phrases.json`](bridge/phrases.json) has the 16 phrase ids. Those ids do not change.
- Each module has a hello entry point and a stub of its contract function.
- Ranking returns the candidate ids unchanged. Speech and alerts do not call out.

Not built yet: the serial state machine, the WebSocket server, Claude, Cartesia, and Fetch.ai.

## Run the hellos

From the repo root, with Python 3.11+:

```bash
python firmware/main.py
python -m bridge.main
python -m ai.hello
python -m unittest discover -s tests -v
```

Open [`web/index.html`](web/index.html) and [`web/dashboard.html`](web/dashboard.html) in a browser. The patient page should show the word Hello. The highlight on that page is a placeholder until the bridge is connected.

Lint the Python modules with [Ruff](https://docs.astral.sh/ruff/):

```bash
ruff check ai bridge tests
ruff format --check ai bridge tests
```

## Secrets

API keys live only in `.env`. Never commit a key, print a key, or hard-code one.

## Team

Person 1 owns `firmware/` and `bridge/`. Person 2 owns `web/` and storage behavior. Person 3 owns `ai/`. Names and the Devpost account are still TBD. Merge to `main` through a pull request that someone else approves.
