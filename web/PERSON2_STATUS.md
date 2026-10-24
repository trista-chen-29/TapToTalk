# Person 2 completion report

Checked against CONTRACT.md v1.1, AGENTS.md v1.1, and the Team Plan in
[Cal Hacks 13.0](https://docs.google.com/document/d/1bzE7dal8R1sOZqDUbULwX9HI_Bfp2aFU2xFTD1639Cg/edit).
This report describes the current checkout, not unmerged teammate branches.

## Frequent asks

`web/frequent_asks.sql` is an executable local SQLite query over `selections`.
Bind `:as_of` to a valid ISO 8601 UTC reference time. It returns only phrase_id
and request_count, sorted by descending count then phrase ID. The inclusive
window is [as_of minus 30 days, as_of]; future and unparseable stored timestamps
are excluded. UTC offsets and fractional timestamps are compared as instants.
This uses the existing schema and changes no module or network contract.

Example against an existing local database, from the repository root:

```python
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

query = Path("web/frequent_asks.sql").read_text()
uri = Path("bridge/taptotalk.db").resolve().as_uri() + "?mode=ro"
with closing(sqlite3.connect(uri, uri=True)) as connection:
    counts = connection.execute(
        query, {"as_of": datetime.now(UTC).isoformat()}
    ).fetchall()
```

No endpoint or production caller is added. The caller must validate the reference
time. A malformed reference produces no counts, rather than executing as SQL.
The query does not add frequent counts to Claude's v1.1 input; that input is still
limited to the contract's fields and at most five previous selections.

## Task-by-task status

| Task | Verified locally | Remaining acceptance gap |
| --- | --- | --- |
| 1: page/WebSocket | HTTP assets, WebSocket initial state, connection handling pass | Integrated demo/cold start still needs teammate verification |
| 2: grid/highlight (FR5) | All 16 canonical phrases render from simulated state lists; indexes and mode changes pass | Person 1: real phrase-state generation/catalog delivery and Space-driven bridge navigation |
| 3: Speak | One contract select message, duplicate guard, send failures and disconnect behavior pass with mock sockets | Person 1: process confirmed selections; Person 3: speech/clip playback; team: result acknowledgement contract |
| 4: SQLite (FR6) | Contract tables, one row per call, persistence, retrieval and validation tests pass | Person 1: invoke once per confirmed selection; retry idempotency/event identity requires agreement |
| 5: dashboard (FR7) | Both alert types, invalid/replayed events, disconnect/reconnect pass with synthetic messages | Person 1: live alert routing, dedupe/escalation integration; team: acknowledgement, escalation updates and request-history transport |
| Frequent asks | Correct 30-day counts on synthetic test set, no writes or new fields | Query is local-only; production use must be wired by storage/bridge owner without silently adding ranker fields |
| Log privacy audit | Exact schemas and synthetic field-value allowlists pass | No persistent local DB exists to audit; repeat audit on actual demo DB before submission |
| FR14: nurse audio toggle | Profile has audio_on, but no nurse setting UI is implemented | Team agreement on profile settings API; Person 1 session application and Person 3 output/clip behavior |
| Freeze/review/demo | Tests pass | Teammate approval/demo, keyboard-to-voice and all-profile nurse-call checks, cold-start rehearsals, and freeze status are not established by unit tests |

The Team Plan assigns alert dedupe/escalation to Person 1 while CONTRACT.md places
agent rules under the Fetch.ai alert section. Owners should coordinate integration;
this work does not change either document or assign a new protocol.

## Privacy audit scope and finding

- Tables contain only the contract fields; no patient name, room number,
  profile_id, free-text message, or other identity columns.
- All 16 synthetic selection rows use canonical phrase/category IDs, an allowed
  source, an integer row key, and a valid UTC timestamp. Synthetic alert rows use
  only the allowed kind, timestamp, row key, and 0/1 flags.
- Numeric SQLite primary keys and predefined phrase_id values are functional
  identifiers required by the contract, not patient identifiers.
- No .db/.sqlite/.sqlite3 file was found under bridge/. Tests create temporary
  databases and delete them; no patient database was uploaded or logged.
- Existing save_selection validates phrase/category/source but does not validate
  optional selected_at. A caller could store arbitrary text there. The new test
  documents that invalid timestamps are excluded from counts, but this is not
  input sanitization. Coordinate UTC timestamp validation with Person 1 before
  editing bridge/log.py. Direct SQL writers also need trusted input validation.
- This is an audit of current schemas and synthetic data, not a guarantee about
  future records, external databases, logs, API requests, or teammate branches.

## Validation

- 30 Python tests pass, including seven new query/privacy checks.
- 24 frontend tests pass, preserving Tasks 1–5 coverage.
- Ruff lint and formatting pass; patient/test JavaScript and dashboard inline
  JavaScript syntax checks pass; git diff whitespace checks pass.
- No JS/HTML/CSS formatter/linter is configured. SQL is executed against SQLite in
  the new tests. No additional formatting tool is introduced.

Changes: frequent_asks.sql, this report, and tests/test_frequent_asks.py only.
No bridge, AI, firmware, state-machine, schema, or shared-contract edits.
No commit or push is made for this work.
