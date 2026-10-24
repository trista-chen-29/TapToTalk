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

This is the Friday-night scaffold, aligned with contract v1.1:

- `.env` is gitignored. Copy [`.env.example`](.env.example) before any API call.
- [`bridge/phrases.json`](bridge/phrases.json) has the 16 English phrase ids. Those ids do not change. Other languages, when added, use `phrases.<language>.json` and keep the same ids.
- [`bridge/profile.json`](bridge/profile.json) is the bedside profile for `bed-1`. It holds settings only, never a name.
- Each module has a hello entry point and a stub of its contract function.
- Ranking returns the candidate ids unchanged. `speak(phrase_id, text)` and `send_alert(kind, phrase_id, timestamp)` return without calling out.

The serial state machine, WebSocket server, audio clips, Claude, Cartesia, and Fetch.ai are the next work for the module owners. Requirement IDs FR12 through FR21 are recorded in the contract and are not built yet.

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

Person 1 owns `firmware/`, `bridge/`, and `bridge/audio/`. Person 2 owns `web/` and storage behavior. Person 3 owns `ai/`. Names and the Devpost account are still TBD. Merge to `main` through a pull request that someone else approves.
