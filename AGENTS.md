# AGENTS.md: TapToTalk working rules

Version: v1.1 (2026-10-23)

Read this before you write code, run an agent, or open a pull request. Humans and coding agents follow the same rules.

## What this repo is

TapToTalk is a communication aid for intubated ICU patients. A patient taps a sensor to pick a phrase. The laptop bridge narrows the phrases, Claude re-ranks them, Cartesia speaks the choice, and Fetch.ai alerts the nurse on "Call nurse."

This is a hackathon build. It is not a medical device, and it has not been tested on patients. Do not write copy, comments, or docs that claim clinical use or outcomes.

Board: Raspberry Pico (chosen 2026-10-23). The ESP32 is a backup only.

## Layout

| Path | What it is | Owner |
| --- | --- | --- |
| `firmware/` | MicroPython for the Pico (touch, key switch, 3-colour LED) | Person 1 |
| `bridge/` | Python laptop process: state machine, profile, request log | Person 1 |
| `bridge/audio/` | Pre-generated phrase and category clips (`.wav`) | Person 1 |
| `web/` | Browser UI and nurse dashboard | Person 2 |
| `ai/` | Claude ranking, Cartesia speech, Fetch.ai nurse alerts | Person 3 |
| `CONTRACT.md` | Interfaces between modules (source of truth), v1.1 | All three |
| `AGENTS.md` | This file | All three |

Edit only the folder you own, unless the change is agreed in `CONTRACT.md` first.

Requirement IDs (FR1 to FR21) and the not-supported list are in the PRD doc. Cite the ID in your pull request.

Names for Person 1, Person 2, and Person 3 are still TBD.

## Before you touch code

1. Read `CONTRACT.md`. If your change alters a message, field, command, or button rule, update the contract in the same pull request and tell the team in chat.
2. Confirm the keyboard path still works. The demo must run with no sensor.
3. Confirm the nurse call still works in every profile you touched.
4. Check that no secrets are staged: `git status` and `git diff --cached`.

## Rules for every agent and every person

### Privacy

- Never send names, IDs, dates of birth, room numbers, or any identifying detail to Claude or any other API. Phrase context means time of day, the last five selections, and the category, nothing else.
- `bridge/profile.json` holds settings only. Use a label such as `bed-1`. Never put a name, date of birth, or room number in it.
- Keep patient request history on the laptop (SQLite). Do not upload it.
- Audio clips are made from phrase text only. Never turn patient text into a clip.
- Do not add analytics, telemetry, or third-party logging.

### Secrets

- API keys go in `.env`. `.env` is in `.gitignore`. Never hard-code a key, never print a key in logs, never commit one.
- If a key is committed by accident, revoke it first, then remove it from history. Tell the team.

### Safety

- The fallback always works. If Claude fails or times out, use the fixed phrase order. If Cartesia fails, show the text on screen. If the sensor fails, the keyboard takes over.
- Never let an AI response be the only way to speak or alert. A patient must always be able to select a phrase and call a nurse.
- The nurse call works in every profile: categories, fixed buttons, audio on or off, and screen-only output. Test it in each one before the demo.
- Holding 1 second in idle starts a session. Holding 3 seconds sends Call nurse. Do not change these times without the team.
- A no-activity alert is sent once per idle period, never repeated.
- Label the product as a communication aid in any UI text, README, or pitch material.

### Scope

- Do not build for the not-supported list in the PRD: patients who cannot move any limb, eye-tracking input, patient groups a clinician has not reviewed, and languages without a phrase file.
- Do not claim a clinical scenario works unless a clinician has reviewed it. Until then, call it a design.
- Do not add features after Saturday night's freeze without asking the team.
- Do not add patient-facing text that makes medical claims.
- Do not add eye tracking, a custom trained model, hospital or EMR integration, accounts, extra phrases, extra categories, or a native mobile app.

### Code standards

- Python (`bridge/`, `ai/`): Python 3.11+. Format with `ruff format`. Lint with `ruff check`. Type hints on public functions.
- MicroPython (`firmware/`): keep the main loop non-blocking. Debounce every input, using the `hold_ms` that the bridge sends with `CFG hold_ms <n>`. No `time.sleep` longer than 50 ms in the input path.
- Web (`web/`): plain HTML, CSS, and JavaScript unless the team agrees on a framework. Minimum body text 24 px on the patient screen. High contrast.
- Serial and bridge commands must match `CONTRACT.md` exactly: `TAP`, `HOLD`, `SELECT`, `LED idle`, `LED listening`, `LED phrase`, `LED sent`, `LED alert`, and `CFG hold_ms <n>`.

## Git workflow

- `main` is protected in spirit: merge only through pull requests.
- Branch names: `firmware/<short-topic>`, `bridge/<short-topic>`, `web/<short-topic>`, `ai/<short-topic>`.
- Commit messages: one line in the imperative, for example `bridge: add 8-second idle timeout`.
- Each pull request needs one approval from a teammate who did not write it.
- Do not force-push to `main`. Do not rewrite history after a review has started.
- Do not commit generated files, `.venv/`, `__pycache__/`, `.env`, `bridge/taptotalk.db`, or large media. Audio clips go in only if the team agrees to commit them.

## Before every commit

- I read `CONTRACT.md` and my change matches it
- I changed only my own folder, or the team agreed to the change
- Keyboard path still works end to end
- Nurse call still works in every profile I touched
- No secrets, patient identifiers, profile names, or new telemetry
- `ruff check` passes (Python changes)
- I ran the module once locally and saw the expected output
- Commit message is one clear line, and the pull request cites the FR ID

## Definition of done

A feature is done when:

1. It works from the keyboard path.
2. It works from the real sensor, if the change touches input.
3. Its fallback is tested by turning the dependency off.
4. The nurse call still works in every profile.
5. The owner has demoed it to one teammate.
6. `CONTRACT.md` is up to date.

## When to stop and ask

Stop and tell the team before you:

- change a message format, command, or button rule in `CONTRACT.md`
- change a profile field, a hold time, or the 3-second nurse-call hold
- change the LED states or the blue and blink pattern
- add a new external service or API
- send any new data off the laptop
- change the fallback order or the "Call nurse" path
- commit to a branch another person owns

## Hackathon timeline

- Friday night: Pico chosen, `CONTRACT.md` v1.1 agreed, modules run alone with stubs
- Saturday noon: one phrase speaks end to end from the keyboard
- Saturday night: feature freeze, real sensor tested
- Sunday 8:30 AM: Devpost submitted, demo rehearsed twice
- Sunday 10:30 AM: whole team at the table for judging

The Sunday 8:30 AM submission target is an internal buffer. Verify the official deadline and timezone against the current organizer guide.
