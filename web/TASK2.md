# Task 2: patient grid

The patient page renders the four contract categories and the phrase list in
received `state` messages. Category mode uses `highlight_index` for the category;
phrase mode uses `category` for the category and `highlight_index` for the phrase.
Idle, malformed state, and disconnection clear stale selection. The bridge alone
controls mode, ordering, and highlighting. Yellow fill, an arrow, and an inset
border identify the current item. Keyboard focus uses a separate dashed outline.
Patient-facing text is at least 24px.

Phrase buttons support native Tab, Enter, and Space. Activation sends only the
existing `{type: "select", phrase_id, source: "ui"}` message. It does not change
mode or highlight locally. It is not confirmation of speech or a nurse alert.

## Checks

Run from the repository root:

```sh
node --test web/bridge.test.cjs
node --check web/bridge.js
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check ai bridge tests
.venv/bin/ruff format --check ai bridge tests
```

The frontend tests read `bridge/phrases.json` directly as test data, covering all
16 actual phrases without duplicating IDs. They exercise category indexes,
reordered phrase lists, idle, malformed states, disconnection/reconnection, and
selection output using a simulated DOM and WebSocket. They are not browser tests.
Manual browser verification with a temporary Python simulated WebSocket server
confirmed People/category and phrase highlighting, Tab+Enter and Space activation
of Call nurse, and unchanged highlighting until another bridge state arrives.
The live bridge at localhost:8765 was separately verified to still connect and
render idle mode.

## Integration blockers requiring team agreement

- The existing bridge has no catalog endpoint. Its initial state contains no
  phrases, and it never sends phrase-mode states. Production currently displays
  categories and idle mode. The UI can render the entire catalog across incoming
  category phrase lists, but cannot load all 16 phrases from the existing server.
  No catalog is copied into web/, and no undocumented endpoint is assumed.
- The bridge ignores incoming selections. Button activation can send the agreed
  message, but does not yet result in selection, audio, logging, or an alert.
- The contract defines keyboard mappings but no browser-to-bridge navigation
  message. Space/held Enter/Shift+Enter/Escape menu navigation must be implemented
  in the shared Python state machine after the input transport is agreed. Native
  button keyboard activation is tested; full keyboard navigation is blocked.

No bridge or contract changes are made for Task 2. Existing modifications to those
files belong to the earlier local-server task. No clinical operation or complete
nurse-call flow is validated by this UI test.
