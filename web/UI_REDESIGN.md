# UI redesign verification

Visual/UX changes only. Started on `main` with a clean working tree. No commits,
PRs, backend changes, protocol changes, or extra frontend navigation state.
Read `AGENTS.md`, `CONTRACT.md` v1.2 and every existing file in `web/` first.

## Preserved integration hooks

- Patient: `connection-status`, `current-mode`, `category-grid`, `phrase-grid`,
  `phrase-heading`, `speak-button`, `send-status`, `bridge-message`.
- Category list children remain `li.tile[data-category]` in contract order.
  Decorative inline SVGs are hidden from assistive technology. Categories remain
  non-interactive: the bridge owns navigation.
- Phrase list children remain `li > button.tile.phrase-button[data-phrase-id]`.
  `updateSpeak()` still accesses each list item's first child as its button.
  `highlight` and `aria-current` remain driven by `highlight_index`.
- Dashboard: `dashboard-connection`, `alert-summary`, `alerts-empty`, `alert-list`,
  `dashboard-message`; `.alert-card` still contains an h2, time and status p.
- WebSocket URL, validation, ordering, outgoing selection JSON, duplicate guard,
  reconnect behavior, and dynamic status strings are unchanged. The only
  script additions are decorative category SVGs and presentation-only
  `data-connection` attributes. Asset query versions refresh cached styling.
- Native buttons retain Tab/Enter/Space activation. Focus differs from bridge
  highlighting. No `aria-pressed`, invented acknowledgement, escalation, or
  speaking state is introduced. New alerts use a dedicated polite live region;
  the entire alert list is not live.

## Layout and visual system

Shared local CSS tokens supply light/dark palettes, spacing, radius, typography
and shadows. Patient text is at least 24px. Categories use icons plus labels;
selection has a thick border, background and marker. Keyboard outlines are 4px.
The dashboard retains its full simulated-system warning and integration notes.
Acknowledged-card styling is reserved and unused by application logic.

In tall viewports the patient page has separate scroll-content and action rows:
Speak stays visible without overlaying the phrase list. Short viewports use
normal document flow. Expanding Diagnostics also restores document flow so the
extra content cannot trap the scrolling region. No fixed-position overlay is
used. Diagnostics keep their original message hooks inside a native disclosure.

## Automated verification

- `node --test web/*.test.cjs`: **29 pass** (25 existing plus 4 presentation
  checks). Includes all 16 catalog phrases, all four categories, each highlight
  index, exact selection payload, duplicate suppression, malformed input,
  disconnect/reconnect and both synthetic alert kinds.
- `.venv/bin/python -m unittest discover -s tests -v`: **78 pass**. Local
  test-server sockets require running outside the restricted sandbox.
- `.venv/bin/python -m pytest tests ai/test_rank.py -q`: **86 pass**,
  including 8 ranking tests. Pico-only `firmware/*_test.py` scripts require
  MicroPython hardware and are excluded from host pytest collection.
- `.venv/bin/ruff check ai bridge tests`: passes.
- `.venv/bin/ruff format --check ai bridge tests`: passes (28 files).
- JavaScript syntax checks (including extracted dashboard inline script), Python
  AST syntax checks, HTML parse and diff whitespace checks pass.
- The repo has no configured HTML/CSS/JavaScript linter or formatter; none was
  installed. CSS uses expanded declarations consistent with the existing style.

The new palette tests calculate WCAG contrast from sRGB tokens. All defined
text/background combinations tested meet **4.5:1**, including disabled Speak,
warning, muted text and selected tiles. Focus, selection/control boundaries and
category icon accents meet **3:1** against their defined backgrounds in both
palettes. Focus uses a 4px offset, separating it from primary button fills.
This is a contrast check, not a claim of complete WCAG 2.2 AA conformance.
System forced-color substitutions and OS/browser-specific rendering have not
been contrast-verified.

## Browser verification (synthetic unless noted)

Used a disposable local Python preview outside the repo, serving the actual web
files and sending the existing contract state/alert messages. It introduced no
production endpoint or protocol. Preview ports 8766–8771 are not the real bridge.
Light palette inspection disabled the dark media query in preview responses only;
dark mode matched the browser's actual system preference. No production CSS was
changed for that inspection.

- [x] Real bridge at localhost:8765 connects and renders idle state.
- [x] All 16 real catalog phrases render across four synthetic category states.
- [x] Category index 2 highlights People; phrase index 1 follows each supplied
  category and phrase order. All indices also covered by existing unit tests.
- [x] Tab moves between phrase buttons with visible 4px focus outline.
- [x] Enter on Speak sends exactly
  `{"type":"select","phrase_id":"need_bathroom","source":"ui"}`.
- [x] Space activates a phrase button. Sending disables duplicate submissions
  and says speech is not confirmed. Preview records selection messages only.
- [x] Synthetic `nurse_call` and `no_activity` cards render with UTC timestamps,
  latest received first, no fabricated acknowledgement/escalation.
- [x] Patient layout checked at 1024x768, 768x1024, 390x844, 512x384 and 320x640;
  no horizontal overflow. Scroll-content bottom equals action-panel top.
- [x] Dashboard at 390x844 has both alert cards and no horizontal overflow.
- [x] 512x384 checks the CSS viewport equivalent of a 1024x768 window at 200%
  zoom. Speak switches to normal flow and does not overlap content.
- [x] Light and dark pages inspected visually. Both previews had no JavaScript
  console errors during the initial smoke checks.
- [ ] **True 200% browser zoom:** automation zoom shortcuts did not change zoom;
  verify via the browser's actual zoom menu before approval.
- [ ] **VoiceOver announcements:** verify each new alert is announced once and
  phrase changes are understandable. ARIA structure is tested, audible assistive
  technology output is not verified.
- [ ] **OS reduced motion / increased contrast:** rules are implemented and
  reviewed; actual preference switching remains manual. No animation/transition
  runs by default; reduced motion also removes the pressed-button transform.
- [ ] Hover/pressed appearance and keyboard focus across Safari/Chrome, including
  expanding Diagnostics and returning to phrases, should receive teammate QA.

Before/after screenshots were captured outside the repo in the Codex
visualizations folder for this chat. Synthetic screenshots show rendering only.

## Existing integration limits

`bridge/main.py` now runs the shared keyboard/serial state machine and broadcasts
nurse-call alerts after PR #16. It still ignores incoming browser selections.
The redesign does not connect browser Speak/phrase selection processing, speech
playback, SQLite selection writes, no-activity alerts, acknowledgement, or
2-minute escalation. Live hardware and keyboard-to-dashboard behavior need a
teammate integration run against the updated bridge. Synthetic UI checks do
not establish those end-to-end acceptance criteria. Nothing claims clinical
validation or real emergency notification.
