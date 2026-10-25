# Confirmed Call nurse integration (FR6, FR7)

A normal confirmed `person_nurse` selection now uses the same nurse-call
broadcast helper as `HOLD_LONG`. The helper retains the existing 60-second
suppression window and WebSocket alert fields. It sends the alert before
selection logging or audio playback, so speech failure cannot prevent delivery.
Each deliberate selection still writes one SQLite selection row and invokes
speech once. Other phrase selections do not emit nurse-call alerts.

This change does not include the separate WebSocket diagnostic logging work or
browser selection implementation. Person 1's PR #25 handles browser Speak;
its behavior and tests belong to that PR. No acknowledgement/escalation protocol,
firmware, keyboard controls, dashboard styles, or shared contract are changed.

## Automated checks

Run from the repository root:

```sh
.venv/bin/python -m pytest tests ai/test_rank.py -q
.venv/bin/python -m unittest discover -s tests -q
node --test web/*.test.cjs
.venv/bin/ruff check ai bridge tests
.venv/bin/ruff format --check ai bridge tests
```

`tests/test_nurse_selection.py` uses synthetic keyboard/Pico-source events,
real local test WebSockets, actual temporary SQLite databases, and mocked audio.
It verifies a single normal confirmation sends a nurse alert, writes one row,
and invokes speech; verifies alerts are delivered before audio finishes and
survive audio failure; checks non-nurse phrases and shared deduplication across
normal confirmations and direct holds. Existing tests cover keyboard controls,
serial input parsing, state transitions, and the direct hold path.
These tests do not establish physical sensor operation or actual speaker output.
Pico-only `firmware/*_test.py` scripts require MicroPython and are not host tests.

## Person 1 manual verification

- Restart the updated bridge and keep the simulated nurse dashboard open.
- Hold Enter about 1 second, release, tap Space twice to highlight People,
  use Shift+Enter to open it, then Shift+Enter again to confirm Call nurse.
  Expect one dashboard card, one selection row, and the phrase spoken once.
- Repeat on the Pico using touch and the key switch. Confirm no bounce-induced
  duplicate selection and unchanged LED behavior.
- Repeat with audio off and screen-only output: the alert and selection row must
  still be produced. Restore test profile settings afterward.
- Confirm another People phrase: speech/logging work with no nurse-call alert.
- Repeat a nurse call within 60 seconds: no extra card; after the suppression
  window a new call produces a new card. Each deliberate normal selection
  still has its own selection row.
- Verify the 3-second direct hold still works. Test Enter with page controls
  focused as well as away from them, because the keyboard listener is global.
- With PR #25 applied, repeat using browser Speak. Browser validation and stale
  queued-selection behavior must be reviewed separately in that PR.

## Remaining work

The 120-second escalation requirement is not implemented or claimed by these
checks. Stable alert identity, acknowledgement transport, escalation updates,
and lifecycle persistence need team agreement and a separate implementation.
Dashboard reload/reconnect still does not recover missed alerts. Real hardware,
all profile combinations, and real audio need teammate verification before the
demo; the local tests use synthetic events and mock playback.
