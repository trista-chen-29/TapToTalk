# Task 5: nurse dashboard (FR7; paired with FR6 request-log tests)

The dashboard connects to the existing WebSocket root on port 8765 and renders
only valid contract v1.1 `alert` messages. It displays Call nurse and No activity,
the raised UTC timestamp, a received count, and connection status. Alerts are
listed newest-received first. Exact kind/timestamp replays are suppressed in this
tab; distinct events are retained. The agent still owns 60-second deduplication.

Records stay only in tab memory. Reconnect preserves them; reload clears them.
There is no localStorage, telemetry, API write, acknowledgement, or browser-side
escalation timer. No arbitrary payload text or identifying extra fields are
rendered. Malformed messages do not remove existing alerts. Disconnection warns
that new alerts may be missed; reconnect does not imply history recovery.

The script is inline in dashboard.html because the bridge only routes existing
public files. This keeps implementation in web/ without a new bridge asset route.
Dashboard CSS is scoped to .nurse-dashboard to preserve the patient interface.

## Verification

- `node --test web/*.test.cjs`: 24 frontend tests pass (17 patient, 7 dashboard).
- `.venv/bin/python -m unittest discover -s tests -v`: 23 tests pass, including
  Task 4's eight synthetic SQLite tests. Those files are preserved unchanged.
- Ruff lint/format checks, JavaScript syntax checks, and diff whitespace checks
  pass. No JavaScript/HTML/CSS formatter or linter is configured in this repo.
- A temporary Python WebSocket server on localhost:8766 sent synthetic nurse-call
  and no-activity messages to the actual dashboard. Browser verification confirmed
  both cards, timestamps, count, and the explicit simulation label. It did not
  exercise hardware, Fetch.ai, or production alert delivery.

## Remaining integration blockers

The current bridge emits only idle state; ai/alert.py is a stub. Live alerts need
bridge/agent wiring. The contract does not define acknowledgement messages,
escalation updates, event IDs, or history/replay transport. The UI therefore does
not offer acknowledgement or claim escalation state. Alert persistence and state
updates need team agreement and integration; the dashboard cannot read SQLite.

Task 4 verifies one stored row per logger call. Exactly-once handling across
retried confirmed events still needs Person 1's coordination; see tests/TASK4.md.
No bridge, firmware, state machine, or contract files change in Tasks 4 and 5.
