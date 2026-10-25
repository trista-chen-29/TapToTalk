const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, 'dashboard.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function setup() {
  const clock = { now: Date.parse('2026-10-24T02:15:00Z') };
  class TestDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clock.now])); }
    static now() { return clock.now; }
  }
  class Element {
    constructor() { this.children = []; this.attributes = {}; this.hidden = false; }
    append(...items) { this.children.push(...items); }
    prepend(item) { this.children.unshift(item); }
    replaceChildren(...items) { this.children = items; }
    setAttribute(key, value) { this.attributes[key] = value; }
  }
  const elements = Object.fromEntries(['dashboard-connection', 'alert-summary', 'alerts-empty', 'alert-list', 'request-summary', 'requests-empty', 'request-list', 'dashboard-message'].map(id => [id, new Element()]));
  const sockets = [];
  const timers = [];
  class Socket {
    constructor(url) { this.url = url; this.events = {}; this.sent = []; sockets.push(this); }
    addEventListener(name, fn) { this.events[name] = fn; }
    send(value) { this.sent.push(value); }
  }
  vm.runInNewContext(script, {
    document: { getElementById: id => elements[id], createElement: () => new Element() },
    WebSocket: Socket,
    Date: TestDate,
    window: { location: { host: 'localhost:8765' }, setTimeout: fn => timers.push(fn) },
  });
  const receive = data => sockets.at(-1).events.message({ data: JSON.stringify(data) });
  const alert = (kind = 'nurse_call', timestamp = '2026-10-24T02:15:00Z') => ({type: 'alert', kind, phrase_id: kind === 'nurse_call' ? 'person_nurse' : null, timestamp});
  return { elements, sockets, timers, receive, alert, clock };
}

test('connects to existing socket and ignores patient state', () => {
  const { elements, sockets, receive } = setup();
  assert.equal(sockets[0].url, 'ws://localhost:8765/?client=dashboard');
  sockets[0].events.open();
  assert.match(elements['dashboard-connection'].textContent, /Connected/);
  receive({type: 'state', mode: 'idle'});
  assert.equal(elements['alert-list'].children.length, 0);
  assert.equal(elements['alerts-empty'].hidden, false);
});

function localRaised(stamp) {
  const formatted = new Date(stamp).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
  return `Raised: ${formatted}`;
}

test('renders both contract alert kinds newest received first in local time', () => {
  const { elements, receive, alert } = setup();
  receive(alert());
  receive(alert('no_activity', '2026-10-24T02:20:00Z'));
  const rows = elements['alert-list'].children;
  assert.equal(rows.length, 2);
  assert.equal(rows[0].children[0].textContent, 'No activity');
  assert.equal(rows[1].children[0].textContent, 'Call nurse');
  assert.equal(rows[0].children[1].attributes.datetime, '2026-10-24T02:20:00Z');
  assert.equal(rows[0].children[1].textContent, localRaised('2026-10-24T02:20:00Z'));
  assert.equal(rows[1].children[1].textContent, localRaised('2026-10-24T02:15:00Z'));
  assert.doesNotMatch(rows[0].children[1].textContent, /\(UTC\)/);
  assert.match(rows[0].children[2].textContent, /status unavailable/);
  assert.equal(elements['alerts-empty'].hidden, true);
  assert.equal(elements['alert-summary'].textContent, '2 alerts.');
});

test('ignores exact replays, including equivalent timestamps, without merging distinct events', () => {
  const { elements, receive, alert } = setup();
  receive(alert());
  receive(alert());
  receive(alert('nurse_call', '2026-10-24T02:15:00.000Z'));
  assert.equal(elements['alert-list'].children.length, 1);
  receive(alert('nurse_call', '2026-10-24T02:15:01Z'));
  assert.equal(elements['alert-list'].children.length, 2);
});

test('invalid kinds, phrase IDs, missing fields, and timestamps cannot create alerts', () => {
  const { elements, receive, alert } = setup();
  receive(alert());
  for (const value of [
    {...alert(), kind: 'other'}, {...alert(), phrase_id: 'need_water'},
    {...alert('no_activity'), phrase_id: 'person_nurse'},
    {...alert(), timestamp: 'not a date'}, {...alert(), timestamp: '2026-02-30T02:15:00Z'},
    {...alert(), timestamp: '2026-10-24T02:15:00'}, {type: 'alert'},
    {...alert(), timestamp: '<img src=x>'},
  ]) receive(value);
  assert.equal(elements['alert-list'].children.length, 1);
  assert.match(elements['dashboard-message'].textContent, /invalid alert/);
});

test('malformed JSON preserves received alerts and later valid messages still work', () => {
  const { elements, sockets, receive, alert } = setup();
  receive(alert());
  sockets[0].events.message({data: '{'});
  assert.match(elements['dashboard-message'].textContent, /unreadable/);
  receive(alert('no_activity'));
  assert.equal(elements['alert-list'].children.length, 2);
});

test('disconnect preserves alerts, warns of missed messages and reconnects without sends', () => {
  const { elements, sockets, timers, receive, alert } = setup();
  receive(alert());
  sockets[0].events.error();
  assert.match(elements['dashboard-connection'].textContent, /may be missed/);
  sockets[0].events.close();
  assert.equal(elements['alert-list'].children.length, 1);
  assert.match(elements['dashboard-message'].textContent, /stay visible/);
  timers[0]();
  sockets[1].events.open();
  receive(alert());
  assert.equal(elements['alert-list'].children.length, 1);
  assert.equal(sockets[1].url, sockets[0].url);
  assert.ok(sockets.every(socket => socket.sent.length === 0));
});

test('never renders arbitrary payload text or identifying extra fields', () => {
  const { elements, receive, alert } = setup();
  receive({...alert(), text: '<script>unsafe</script>', patient_name: 'SYNTHETIC-IGNORED'});
  const row = elements['alert-list'].children[0];
  assert.equal(row.children[0].textContent, 'Call nurse');
  assert.ok(!JSON.stringify(row).includes('SYNTHETIC-IGNORED'));
  assert.ok(!JSON.stringify(row).includes('unsafe'));
});


test('two-minute boundary documents blocked escalation without fabricating status', () => {
  const { elements, receive, alert, clock, timers } = setup();
  receive(alert('nurse_call', '2026-10-24T02:15:00Z'));
  const raisedAt = clock.now;
  const card = elements['alert-list'].children[0];
  for (const elapsed of [119999, 120000, 120001]) {
    clock.now = raisedAt + elapsed;
    // Replaying the ONLY existing contract message is not an escalation update.
    // There is no bridge timer or acknowledgement/escalation protocol to invoke.
    receive(alert('nurse_call', '2026-10-24T02:15:00Z'));
    assert.equal(elements['alert-list'].children.length, 1);
    assert.equal(card.children[0].textContent, 'Call nurse');
    assert.equal(card.children[2].textContent, 'Acknowledgement status unavailable.');
    assert.equal(timers.length, 0);
  }
});

function localSelected(stamp) {
  const formatted = new Date(stamp).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
  return `Selected: ${formatted}`;
}

test('history restores alerts and requests in local time without extra fields', () => {
  const { elements, receive, alert } = setup();
  receive({
    type: 'history',
    alerts: [
      alert('no_activity', '2026-10-24T02:20:00Z'),
      alert('nurse_call', '2026-10-24T02:15:00Z'),
    ],
    selections: [
      {
        phrase_id: 'need_water', category: 'needs', source: 'keyboard',
        selected_at: '2026-10-24T02:16:00Z', text: '<script>unsafe</script>',
        patient_name: 'SYNTHETIC-IGNORED',
      },
      {
        phrase_id: 'need_bathroom', category: 'needs', source: 'tap',
        selected_at: '2026-10-24T02:10:00Z',
      },
    ],
  });
  const alerts = elements['alert-list'].children;
  assert.equal(alerts.length, 2);
  assert.equal(alerts[0].children[0].textContent, 'No activity');
  assert.equal(alerts[1].children[0].textContent, 'Call nurse');
  assert.equal(alerts[0].children[1].attributes.datetime, '2026-10-24T02:20:00Z');
  assert.equal(alerts[0].children[1].textContent, localRaised('2026-10-24T02:20:00Z'));
  assert.doesNotMatch(alerts[0].children[1].textContent, /\(UTC\)/);
  const requests = elements['request-list'].children;
  assert.equal(requests.length, 2);
  assert.equal(requests[0].children[0].textContent, 'need_water');
  assert.equal(requests[0].children[1].textContent, 'needs · keyboard');
  assert.equal(requests[0].children[2].attributes.datetime, '2026-10-24T02:16:00Z');
  assert.equal(requests[0].children[2].textContent, localSelected('2026-10-24T02:16:00Z'));
  assert.equal(requests[1].children[0].textContent, 'need_bathroom');
  const rendered = requests[0].children.map(child => child.textContent).join(" ");
  assert.equal(rendered.includes('SYNTHETIC-IGNORED'), false);
  assert.equal(rendered.includes('unsafe'), false);
  assert.equal(elements['alerts-empty'].hidden, true);
  assert.equal(elements['requests-empty'].hidden, true);
  assert.match(elements['dashboard-message'].textContent, /Showing 2 alerts and 2 requests/);
  assert.doesNotMatch(html, /<button/i);
});

test('a second history message does not duplicate alerts and replaces requests', () => {
  const { elements, receive, alert } = setup();
  const history = {
    type: 'history',
    alerts: [alert()],
    selections: [
      {phrase_id: 'need_water', category: 'needs', source: 'ui', selected_at: '2026-10-24T02:16:00Z'},
      {phrase_id: 'yes_yes', category: 'yes_no', source: 'fixed', selected_at: '2026-10-24T02:10:00Z'},
    ],
  };
  receive(history);
  receive(history);
  assert.equal(elements['alert-list'].children.length, 1);
  receive({
    type: 'history',
    alerts: [alert()],
    selections: [
      {phrase_id: 'pain_here', category: 'pain_comfort', source: 'tap', selected_at: '2026-10-24T02:18:00Z'},
    ],
  });
  assert.equal(elements['alert-list'].children.length, 1);
  assert.equal(elements['request-list'].children.length, 1);
  assert.equal(elements['request-list'].children[0].children[0].textContent, 'pain_here');
  assert.equal(elements['request-summary'].textContent, '1 recent request.');
});

test('invalid history and bad request rows leave stored cards unchanged', () => {
  const { elements, receive, alert } = setup();
  receive({
    type: 'history',
    alerts: [alert('nurse_call', '2026-10-24T02:15:00Z')],
    selections: [
      {phrase_id: 'need_water', category: 'needs', source: 'keyboard', selected_at: '2026-10-24T02:16:00Z'},
    ],
  });
  receive({type: 'history', alerts: 'nope'});
  assert.equal(elements['alert-list'].children.length, 1);
  assert.equal(elements['request-list'].children.length, 1);
  assert.match(elements['dashboard-message'].textContent, /invalid history/);
  receive({
    type: 'history',
    alerts: [{...alert(), kind: 'other'}, alert('no_activity', '2026-10-24T02:20:00Z')],
    selections: [
      {phrase_id: 'not a phrase', category: 'needs', source: 'keyboard', selected_at: '2026-10-24T02:16:00Z'},
      {phrase_id: 'need_water', category: 'people', source: 'keyboard', selected_at: '2026-10-24T02:16:00Z'},
      {phrase_id: 'need_water', category: 'needs', source: 'sensor', selected_at: '2026-10-24T02:16:00Z'},
      {phrase_id: 'yes_no', category: 'yes_no', source: 'ui', selected_at: '2026-10-24T02:17:00Z'},
    ],
  });
  assert.equal(elements['alert-list'].children[0].children[0].textContent, 'No activity');
  assert.equal(elements['request-list'].children.length, 1);
  assert.equal(elements['request-list'].children[0].children[0].textContent, 'yes_no');
});
