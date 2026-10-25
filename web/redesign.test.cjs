const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, name), 'utf8');
const css = read('styles.css');

function tokens(block) {
  return Object.fromEntries([...block.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/g)].map(m => [m[1], m[2]]));
}
function luminance(hex) {
  const linear = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return linear.reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
}
function contrast(a, b) {
  const [low, high] = [luminance(a), luminance(b)].sort((a, b) => a - b);
  return (high + 0.05) / (low + 0.05);
}
for (const [theme, block] of [
  ['light', css.split(':root {')[1].split('}')[0]],
  ['dark', css.split('@media (prefers-color-scheme: dark)')[1].split(':root {')[1].split('}')[0]],
]) {
  test(`${theme} palette meets AA text and control-boundary contrast`, () => {
    const t = tokens(block);
    const textPairs = [
      ['ink', 'bg'], ['ink', 'surface'], ['ink', 'selected'],
      ['muted', 'bg'], ['muted', 'surface'], ['muted', 'selected'], ['muted', 'disabled'],
      ['primary', 'bg'], ['primary', 'surface'], ['primary', 'selected'],
      ['on-primary', 'primary'], ['warning-ink', 'warning-bg'], ['warning-ink', 'surface'],
    ];
    for (const [a, b] of textPairs) {
      assert.ok(contrast(t[a], t[b]) >= 4.5, `${a}/${b}: ${contrast(t[a], t[b])}`);
    }
    for (const a of ['line', 'primary', 'focus']) {
      for (const b of ['bg', 'surface', 'selected']) {
        assert.ok(contrast(t[a], t[b]) >= 3, `${a}/${b}: ${contrast(t[a], t[b])}`);
      }
    }
    for (const a of ['danger', 'people', 'success']) {
      for (const b of ['surface', 'selected']) {
        assert.ok(contrast(t[a], t[b]) >= 3, `${a}/${b}`);
      }
    }
  });
}

test('dashboard announcements use a dedicated region and retain the simulation warning', () => {
  const html = read('dashboard.html');
  const list = html.match(/<ol[^>]*id="alert-list"[^>]*>/)[0];
  assert.doesNotMatch(list, /aria-live|role="alert"/);
  assert.match(html, /id="dashboard-message"[^>]*role="status"[^>]*aria-live="polite"[^>]*aria-atomic="true"/);
  assert.match(html, /Simulated channel\. This is not a hospital nurse-call system or an emergency service\./);
});

test('patient keeps existing hooks and local decorative category icons without new controls', () => {
  const html = read('index.html');
  for (const id of ['connection-status', 'current-mode', 'category-grid', 'phrase-grid', 'phrase-heading', 'speak-button', 'send-status', 'bridge-message']) {
    assert.equal([...html.matchAll(new RegExp(`id="${id}"`, 'g'))].length, 1, id);
  }
  for (const category of ['needs', 'pain_comfort', 'people', 'yes_no']) {
    assert.match(html, new RegExp(`<symbol id="icon-${category}"`));
  }
  assert.match(html, /<details class="diagnostics">/);
  assert.match(html, /id="speak-button"[^>]*disabled[^>]*aria-describedby="send-status"/);
  assert.doesNotMatch(html, /https?:\/\/(?!www\.w3\.org)/);
});
