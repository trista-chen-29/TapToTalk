# Task 4: SQLite request logging verification

The existing bridge/log.py already creates the contract v1.1 selections and
alerts tables. save_selection validates a catalog phrase, matching category,
and allowed source, then inserts and commits one row with a UTC timestamp.
Records can be retrieved locally through connect() and parameterized SQLite
queries; tests reopen the file before reading to verify persistence.

No change to bridge/log.py is needed for this storage scope. It was read but
not edited, preserving Person 1's ownership. Firmware, state machine, contract,
and profile files are unchanged. No new storage API or message format is added.

## Synthetic checks

Run `.venv/bin/python -m unittest discover -s tests -p test_log.py -v`.
Eight tests verify exact table columns/types, primary keys, required fields,
one committed selection row, every catalog phrase and allowed source, generated
UTC times, invalid inputs leaving existing rows unchanged, schema reopening,
and alert insertion/retrieval with default lifecycle flags. Test databases live
in temporary directories and are deleted automatically. Only predefined phrases,
categories, sources, timestamps, and alert kinds are used; no identifying fields
or patient data are stored. Alert test inserts validate the existing schema only;
they do not introduce an alert-lifecycle API.

Full validation: 23 Python tests and 17 frontend tests pass. Ruff lint and format
checks and git diff whitespace checks pass.

## Bridge coordination still required

One save_selection invocation creates exactly one record. It must be called once
by the bridge's confirmed-selection handler, never on highlight changes, raw taps,
or unconfirmed UI sends. That integration is not implemented here because the
state machine must not be modified in Task 4.

The current contract has no stable selection-event identifier. Calling the logger
twice inserts two rows, even for identical phrase/source/timestamp values; those
values can also represent two legitimate confirmations. Do not deduplicate by
phrase or time. Retry-safe exactly-once logging across duplicate event delivery
needs agreement with Person 1 on confirmation ownership and, if required, a
team-approved event identity/schema change before editing bridge/log.py.
