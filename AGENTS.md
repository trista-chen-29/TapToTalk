# AGENTS.md: TapToTalk working rules

Read this before you write code, run an agent, or open a pull request. Humans and coding agents follow the same rules.

## What this repo is

TapToTalk is a communication aid for intubated ICU patients. A patient taps a sensor to pick a phrase. The laptop bridge narrows the phrases, Claude re-ranks them, Cartesia speaks the choice, and Fetch.ai alerts the nurse on "Call nurse."

This is a hackathon build. It is not a medical device, and it has not been tested on patients. Do not write copy, comments, or docs that claim clinical use or outcomes.

## Layout

| Path | What it is | Owner |
| --- | --- | --- |
| `firmware/` | MicroPython for the Pico (sensor, keys, LEDs) | Person 1 |
| `bridge/` | Python laptop process (state machine, log) | Person 1 |
| `web/` | Browser UI and nurse dashboard | Person 2 |
| `ai/` | Claude ranking, Cartesia TTS, Fetch.ai alerts | Person 3 |
| `CONTRACT.md` | Interfaces between modules (source of truth) | All three |
| `AGENTS.md` | This file | All three |

Edit only the folder you own, unless the change is agreed in `CONTRACT.md` first.

Names for Person 1, Person 2, and Person 3 are still TBD.

## Before you touch code

1. Read `CONTRACT.md`. If your change alters a message, field, or command, update the contract in the same pull request and tell the team in chat.
2. Confirm the keyboard path still works. The demo must run with no sensor.
3. Check that no secrets are staged: `git status` and `git diff --cached`.

## Rules for every agent and every person

### Privacy

- Never send names, IDs, dates of birth, room numbers, or any identifying detail to Claude or any other API. Phrase context means time of day, the last five selections, and the category, nothing else.
- Keep patient request history on the laptop (SQLite). Do not upload it.
- Do not add analytics, telemetry, or third-party logging.
- The exact boundary between "do not upload request history" and the last five phrase ids sent to Claude is an open decision in `CONTRACT.md`. Until that is resolved, send only the section 6 fields, and use synthetic history in the demo.

### Secrets

- API keys go in `.env`. `.env` is in `.gitignore`. Never hard-code a key, never print a key in logs, never commit one.
- If a key is committed by accident, revoke it first, then remove it from history. Tell the team.

### Safety

- The fallback always works. If Claude fails or times out, use the fixed phrase order. If Cartesia fails, show the text on screen. If the sensor fails, the keyboard takes over.
- Never let an AI response be the only way to speak or alert. A patient must always be able to select a phrase and call a nurse.
- Label the product as a communication aid in any UI text, README, or pitch material.

### Scope

- Do not add features after Saturday night's freeze without asking the team.
- Do not add patient-facing text that makes medical claims.
- Do not add eye tracking, camera input, a custom trained model, hospital or EMR integration, accounts, extra phrases, extra categories, or a native mobile app.

### Code standards

- Python (`bridge/`, `ai/`): Python 3.11+. Format with `ruff format`. Lint with `ruff check`. Type hints on public functions.
- MicroPython (`firmware/`): keep the main loop non-blocking. Debounce every input. No `time.sleep` longer than 50 ms in the input path.
- Web (`web/`): plain HTML, CSS, and JavaScript unless the team agrees on a framework. Minimum body text 24 px on the patient screen. High contrast.
- Name serial messages exactly as `CONTRACT.md` spells them: `TAP`, `HOLD`, `SELECT`, `LED idle`, `LED listening`, `LED sent`, `LED alert`.

## Git workflow

- `main` is protected in spirit: merge only through pull requests.
- Branch names for feature work: `firmware/`, `bridge/`, `web/`, `ai/`, plus a short description.
- Commit messages: one line in the imperative, for example `bridge: add 8-second idle timeout`.
- Each pull request needs one approval from a teammate who did not write it.
- Do not force-push to `main`. Do not rewrite history after a review has started.
- Do not commit generated files, `.venv/`, `__pycache__/`, `.env`, or large media.

## Before every commit

- I read `CONTRACT.md` and my change matches it
- I changed only my own folder, or the team agreed to the change
- Keyboard path still works end to end
- No secrets, patient identifiers, or new telemetry
- `ruff check` passes (Python changes)
- I ran the module once locally and saw the expected output
- Commit message is one clear line

## Definition of done

A feature is done when:

1. It works from the keyboard path.
2. It works from the real sensor, if the change touches input.
3. Its fallback is tested by turning the dependency off.
4. The owner has demoed it to one teammate.
5. `CONTRACT.md` is up to date.

## When to stop and ask

Stop and tell the team before you:

- change a message format in `CONTRACT.md`
- add a new external service or API
- send any new data off the laptop
- change the fallback order or the "Call nurse" path
- commit to a branch another person owns

## Hackathon timeline

- Friday night: contract written, modules run alone with stubs
- Saturday noon: one phrase speaks end to end from the keyboard
- Saturday night: feature freeze, real sensor tested
- Sunday 8:30 AM: Devpost submitted, demo rehearsed twice
- Sunday 10:30 AM: whole team at the table for judging

The Sunday 8:30 AM submission target is an internal buffer. Verify the official deadline and timezone against the current organizer guide.
