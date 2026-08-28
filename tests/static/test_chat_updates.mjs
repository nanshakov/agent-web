import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const elements = new Map();
const element = (name) => ({
  hidden: false,
  innerHTML: '',
  textContent: '',
  scrollHeight: 240,
  scrollTop: 0,
  querySelector: () => ({disabled: false}),
});
for (const name of ['#project-form', '#turn-form', '#messages', '#session-title', '#chat', '#chat-settings']) {
  elements.set(name, element(name));
}

const intervals = [];
const histories = [
  [{role: 'assistant', content: 'First', rendered_content: '<p>First</p>'}],
  [
    {role: 'assistant', content: 'First', rendered_content: '<p>First</p>'},
    {role: 'assistant', content: 'Second', rendered_content: '<p>Second</p>'},
  ],
];
let historyRequest = 0;
const context = vm.createContext({
  console,
  crypto: {randomUUID: () => 'request-id'},
  document: {
    querySelector: (selector) => elements.get(selector) ?? element(selector),
    querySelectorAll: () => [],
  },
  fetch: async (url) => ({
    ok: true,
    json: async () => url.includes('/messages')
      ? histories[Math.min(historyRequest++, histories.length - 1)]
      : {},
  }),
  setInterval: (callback) => intervals.push(callback),
  setTimeout,
  URL,
  Blob,
});

let source = fs.readFileSync(new URL('../../src/agent_web/static/app.js', import.meta.url), 'utf8');
source = source.replace(/refresh\(\)\.catch\([^\n]+\);\s*$/, '');
vm.runInContext(source, context);
vm.runInContext('renderChatSettings=()=>{}', context);

await vm.runInContext("showHistory('chat-1','Chat','codex','project-1')", context);
const messages = elements.get('#messages');

test('opening a chat scrolls to the latest message', () => {
  assert.equal(messages.scrollTop, messages.scrollHeight);
});

test('later consecutive agent messages appear', async () => {
  assert.ok(intervals.length > 0, 'an open chat must schedule history refreshes');
  await intervals.at(-1)();
  assert.match(messages.innerHTML, /First[\s\S]*Second/);
});
