const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../bridge/phrases.json')));
const script = fs.readFileSync(path.join(__dirname, 'bridge.js'), 'utf8');

function setup() {
  class Element {
    constructor() {
      this.children = [];
      this.dataset = {};
      this.attributes = {};
      this.events = {};
      const classes = new Set();
      this.classList = { add: (s) => classes.add(s), remove: (s) => classes.delete(s), contains: (s) => classes.has(s) };
    }
    append(child) { this.children.push(child); }
    replaceChildren() { this.children = []; }
    setAttribute(k, v) { this.attributes[k] = v; }
    removeAttribute(k) { delete this.attributes[k]; }
    addEventListener(k, fn) { this.events[k] = fn; }
  }
  const elements = Object.fromEntries(['connection-status', 'bridge-message', 'current-mode', 'category-grid', 'phrase-grid', 'phrase-heading', 'speak-button', 'send-status'].map(id => [id, new Element()]));
  const sockets = [];
  const timers = [];
  class Socket {
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 1; this.events = {}; this.sent = []; sockets.push(this); }
    addEventListener(k, fn) { this.events[k] = fn; }
    send(s) { this.sent.push(JSON.parse(s)); }
  }
  vm.runInNewContext(script, {
    document: { getElementById: id => elements[id], createElement: () => new Element() },
    WebSocket: Socket,
    window: { location: { host: 'localhost:8765' }, setTimeout: fn => timers.push(fn) },
  });
  sockets[0].events.open();
  const receive = value => sockets.at(-1).events.message({ data: JSON.stringify(value) });
  const state = (mode, highlight_index = 0, category = null, phrases = []) => receive({ type: 'state', mode, highlight_index, category, phrases });
  return { elements, sockets, timers, receive, state };
}

test('preserves WebSocket address and all four category IDs in contract order', () => {
  const { elements, sockets } = setup();
  assert.equal(sockets[0].url, 'ws://localhost:8765/');
  assert.deepEqual(elements['category-grid'].children.map(e => e.dataset.category), catalog.categories);
});

test('category highlighting follows index, not a conflicting category field', () => {
  const { elements, state } = setup();
  for (let index = 0; index < 4; index++) {
    state('category', index, 'needs');
    assert.deepEqual(elements['category-grid'].children.map(e => e.classList.contains('highlight')), catalog.categories.map((_, i) => i === index));
    assert.equal(elements['phrase-grid'].children.length, 0);
  }
});

test('all 16 real phrases render and follow bridge ranking and highlight', () => {
  const { elements, state } = setup();
  for (const category of catalog.categories) {
    const phrases = catalog.phrases.filter(p => p.category === category).toReversed();
    for (let index = 0; index < phrases.length; index++) {
      state('phrase', index, category, phrases);
      const buttons = elements['phrase-grid'].children.map(e => e.children[0]);
      assert.deepEqual(buttons.map(b => b.dataset.phraseId), phrases.map(p => p.id));
      assert.deepEqual(buttons.map(b => b.textContent), phrases.map(p => p.text));
      assert.deepEqual(buttons.map(b => b.classList.contains('highlight')), phrases.map((_, i) => i === index));
      assert.equal(buttons[index].attributes['aria-current'], 'true');
    }
  }
});

test('idle clears previous phrase and category highlighting', () => {
  const { elements, state } = setup();
  state('phrase', 0, 'needs', catalog.phrases.slice(0, 4));
  state('idle');
  assert.equal(elements['phrase-grid'].children.length, 0);
  assert.ok(elements['category-grid'].children.every(e => !e.classList.contains('highlight')));
  assert.equal(elements['current-mode'].textContent, 'Mode: idle');
});

test('phrase activation sends only agreed select message without changing highlight', () => {
  const { elements, state, sockets } = setup();
  state('phrase', 0, 'needs', catalog.phrases.slice(0, 4));
  const buttons = elements['phrase-grid'].children.map(e => e.children[0]);
  buttons[2].events.click();
  assert.deepEqual(sockets[0].sent, [{ type: 'select', phrase_id: catalog.phrases[2].id, source: 'ui' }]);
  assert.ok(buttons[0].classList.contains('highlight'));
  assert.ok(!buttons[2].classList.contains('highlight'));
  sockets[0].readyState = 3;
  buttons[2].events.click();
  assert.equal(sockets[0].sent.length, 1);
});

test('bad index, malformed phrases and duplicate IDs clear stale selection', () => {
  const { elements, state } = setup();
  for (const [mode, index, category, phrases] of [
    ['category', 4, null, []], ['category', -1, null, []],
    ['phrase', 8, 'needs', catalog.phrases.slice(0, 4)],
    ['phrase', 0, 'unknown', catalog.phrases.slice(0, 4)],
    ['phrase', 0, 'needs', [null]],
    ['phrase', 0, 'needs', [catalog.phrases[0], catalog.phrases[0]]],
  ]) {
    state('category', 1);
    state(mode, index, category, phrases);
    assert.equal(elements['current-mode'].textContent, 'Mode: unavailable');
    assert.ok(elements['category-grid'].children.every(e => !e.classList.contains('highlight')));
  }
});

test('unrelated alerts do not change selection; invalid JSON clears it', () => {
  const { elements, state, receive, sockets } = setup();
  state('category', 1);
  receive({ type: 'alert', kind: 'nurse_call' });
  assert.ok(elements['category-grid'].children[1].classList.contains('highlight'));
  sockets[0].events.message({ data: '{' });
  assert.equal(elements['current-mode'].textContent, 'Mode: unavailable');
});

test('disconnect clears stale state and reconnect uses the same address', () => {
  const { elements, state, sockets, timers } = setup();
  state('category', 1);
  sockets[0].events.close();
  assert.equal(elements['current-mode'].textContent, 'Mode: unavailable');
  assert.ok(elements['category-grid'].children.every(e => !e.classList.contains('highlight')));
  timers[0]();
  assert.equal(sockets[1].url, sockets[0].url);
});

test('phrase text is assigned as plain text, never HTML', () => {
  const { elements, state } = setup();
  state('phrase', 0, 'needs', [{ id: catalog.phrases[0].id, text: '<b>water</b>' }]);
  assert.equal(elements['phrase-grid'].children[0].children[0].textContent, '<b>water</b>');
});

test('Speak is enabled only for a valid highlighted phrase on an open connection', () => {
  const { elements, state, sockets } = setup();
  const speak = elements['speak-button'];
  assert.equal(speak.disabled, true);
  state('idle');
  assert.equal(speak.disabled, true);
  state('category', 2);
  assert.equal(speak.disabled, true);
  state('phrase', 1, 'needs', catalog.phrases.slice(0, 4));
  assert.equal(speak.disabled, false);
  sockets[0].readyState = 3;
  speak.events.click();
  assert.equal(sockets[0].sent.length, 0);
  sockets[0].events.close();
  assert.equal(speak.disabled, true);
});

test('Speak uses highlighted phrase, blocks rapid and cross-button duplicates, preserves highlight', () => {
  const { elements, state, sockets } = setup();
  state('phrase', 2, 'needs', catalog.phrases.slice(0, 4));
  const speak = elements['speak-button'];
  const buttons = elements['phrase-grid'].children.map(item => item.children[0]);
  speak.events.click();
  speak.events.click();
  buttons[1].events.click();
  assert.deepEqual(sockets[0].sent, [{ type: 'select', phrase_id: catalog.phrases[2].id, source: 'ui' }]);
  assert.equal(speak.disabled, true);
  assert.equal(speak.textContent, 'Sending…');
  assert.equal(speak.attributes['aria-busy'], 'true');
  assert.ok(buttons[2].classList.contains('highlight'));
  assert.ok(buttons.every(button => button.disabled));
  assert.match(elements['send-status'].textContent, /Speech is not confirmed/);
});

test('repeated state and alerts cannot unlock a pending submission; changed state can', () => {
  const { elements, state, sockets, receive } = setup();
  const phrases = catalog.phrases.slice(0, 4);
  state('phrase', 0, 'needs', phrases);
  elements['speak-button'].events.click();
  state('phrase', 0, 'needs', phrases);
  receive({ type: 'alert', kind: 'nurse_call' });
  assert.equal(elements['speak-button'].disabled, true);
  elements['speak-button'].events.click();
  assert.equal(sockets[0].sent.length, 1);
  state('phrase', 1, 'needs', phrases);
  assert.equal(elements['speak-button'].disabled, false);
  assert.match(elements['send-status'].textContent, /Speech is not confirmed/);
  elements['speak-button'].events.click();
  assert.equal(sockets[0].sent[1].phrase_id, phrases[1].id);
});

test('invalid state disables Speak and cannot send a stale phrase', () => {
  const { elements, state, sockets } = setup();
  state('phrase', 0, 'needs', catalog.phrases.slice(0, 4));
  state('phrase', 8, 'needs', catalog.phrases.slice(0, 4));
  assert.equal(elements['speak-button'].disabled, true);
  elements['speak-button'].events.click();
  assert.equal(sockets[0].sent.length, 0);
});

test('send failure restores controls without claiming speech', () => {
  const { elements, state, sockets } = setup();
  state('phrase', 0, 'needs', catalog.phrases.slice(0, 4));
  sockets[0].send = () => { throw new Error('closed'); };
  elements['speak-button'].events.click();
  assert.equal(elements['speak-button'].disabled, false);
  assert.equal(elements['speak-button'].textContent, 'Speak');
  assert.equal(elements['speak-button'].attributes['aria-busy'], 'false');
  assert.match(elements['send-status'].textContent, /Could not send selection/);
});

test('disconnect during sending reports unknown outcome and never automatically replays', () => {
  const { elements, state, sockets, timers } = setup();
  state('phrase', 0, 'needs', catalog.phrases.slice(0, 4));
  elements['speak-button'].events.click();
  sockets[0].events.close();
  assert.equal(elements['speak-button'].disabled, true);
  assert.match(elements['send-status'].textContent, /outcome is unknown/);
  timers[0]();
  sockets[1].events.open();
  assert.equal(elements['speak-button'].disabled, true);
  assert.equal(sockets[1].sent.length, 0);
  state('phrase', 1, 'needs', catalog.phrases.slice(0, 4));
  assert.equal(elements['speak-button'].disabled, false);
  assert.equal(sockets[1].sent.length, 0);
});

test('direct phrase activation uses the same pending guard as Speak', () => {
  const { elements, state, sockets } = setup();
  state('phrase', 0, 'needs', catalog.phrases.slice(0, 4));
  const button = elements['phrase-grid'].children[1].children[0];
  button.events.click();
  button.events.click();
  elements['speak-button'].events.click();
  assert.equal(sockets[0].sent.length, 1);
  assert.equal(elements['speak-button'].disabled, true);
});

test('socket error disables Speak before the close event', () => {
  const { elements, state, sockets } = setup();
  state('phrase', 0, 'needs', catalog.phrases.slice(0, 4));
  sockets[0].events.error();
  assert.equal(elements['speak-button'].disabled, true);
  elements['speak-button'].events.click();
  assert.equal(sockets[0].sent.length, 0);
});
