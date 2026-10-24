# Task 3: Speak button

Speak is visible below the phrase grid. It is enabled only when a valid
phrase-mode state has supplied a highlighted phrase, the socket has opened,
and no submission is pending. It sends the existing contract selection message
with the highlighted phrase ID and source `ui`. It does not alter highlighting,
advance the menu, play audio, or claim that speech happened.

Speak and direct phrase buttons share a synchronous submission guard. The first
activation displays `Sending…` and disables further submissions. Repeated copies
of the same state and unrelated alert messages do not unlock the guard. A changed
valid bridge state unlocks it, while explicitly stating that speech remains
unconfirmed. This is a UI guard, not server-side deduplication or acknowledgement.

If send throws, show an error and allow a deliberate retry. Disconnection clears
stale selection and reports an unknown outcome when a submission was pending.
Reconnection never automatically resends; a fresh phrase-mode state is required
before another deliberate activation.

## Verification

- `node --test web/bridge.test.cjs`: 17 tests, including 8 Speak/submission tests
  using a mock WebSocket and DOM.
- `node --check web/bridge.js`: syntax check.
- `.venv/bin/python -m unittest discover -s tests -v`: 15 existing tests.
- `.venv/bin/ruff check ai bridge tests` and
  `.venv/bin/ruff format --check ai bridge tests`: existing Python checks.
- `git diff --check`: whitespace check. This repo has no configured JavaScript,
  HTML, or CSS formatter/linter; no new tooling is introduced for this task.

## Remaining integration blockers

The production bridge still sends only idle state and ignores selections, so
Speak stays disabled in the current live demo. Catalog delivery, real phrase-mode
states, keyboard menu navigation, and selection processing are still bridge work.
The contract defines no selection or speech acknowledgement. Therefore the UI
never announces successful speech, and Sending remains pending if the bridge
keeps returning the same state. A team-agreed acknowledgement/result interface
is needed to confirm delivery, failure, or completed speech reliably.

Only web/ files change in this task. No bridge, contract, profile, nurse-call, or
firmware behavior is implemented or changed.
