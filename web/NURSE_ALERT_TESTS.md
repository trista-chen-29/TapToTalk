# Saturday afternoon nurse-alert acceptance results

Scope: current checkout, CONTRACT.md v1.1. No physical input, live nurse-alert
handler, or new WebSocket message format is introduced.

| Acceptance criterion | Result | Evidence / blocker |
| --- | --- | --- |
| Selecting Call nurse produces a dashboard nurse_call card | Blocked end to end; simulated rendering passes | Existing patient tests verify selection payload output. Existing dashboard tests feed contract alert JSON through a mock WebSocket and verify the card. bridge/main.py ignores input, bridge/alert.py does not exist, and ai/alert.py is a stub, so these two tested pieces are not connected. |
| Unacknowledged alert becomes escalated after two minutes | Blocked | No bridge escalation timer or acknowledgement handler exists, and v1.1 defines no escalation-update message. The dashboard explicitly reports acknowledgement status unavailable. |

## Focused simulation

`node --test web/dashboard.test.cjs` exercises the actual inline dashboard script
with a mock DOM and WebSocket. Existing tests cover nurse-call/no-activity cards,
exact replay suppression, invalid messages, disconnection/reconnection, and no
outgoing messages. They are UI tests, not live bridge integration tests.

The added boundary check uses a controllable Date implementation and advances to
119,999 ms, 120,000 ms, and 120,001 ms after a synthetic nurse call, with no real
time delay. Replaying the existing alert message leaves one card and the explicit
unavailable acknowledgement status. No escalation timer is scheduled.
This passing negative check documents the integration gap: it does NOT mean that
escalation works, and it cannot infer whether a real alert was acknowledged.
No escalated field, acknowledgement message, or browser-only lifecycle is invented.

## Next steps requiring Person 1 / team agreement

- Process the existing UI select message, confirm person_nurse, and route/broadcast
  its contract nurse_call alert to connected dashboard clients.
- Implement the agreed alert lifecycle with an injectable clock; test before 120
  seconds, at the boundary, and after it without sleeping. Define whether the
  boundary is inclusive, then verify acknowledged alerts do not escalate.
- Agree stable alert identity, acknowledgement transport, escalation updates and
  state persistence/replay before changing the shared protocol or UI.
- Once implemented, test the actual patient action -> bridge -> WebSocket -> card
  path and backend escalation -> dashboard update path with controllable time.
- Keep these as blocked until those actual paths pass; synthetic card rendering
  alone does not meet either complete acceptance criterion.

## Validation

25 frontend tests pass (17 patient and 8 dashboard); 40 Python unittest tests and
8 ranking pytest tests pass. Ruff lint/format, JavaScript syntax (including the
inline dashboard script), and diff whitespace checks pass. Only dashboard test
code and this report change. No bridge, firmware, production UI, CONTRACT.md or
AGENTS.md changes.
