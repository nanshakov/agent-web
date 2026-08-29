import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const elements = new Map();
const scrollIntoViewCalls = [];
const confirmations = [];
const switchRequests = [];
const element = (name) => ({
  hidden: false,
  innerHTML: '',
  textContent: '',
  scrollHeight: 240,
  scrollTop: 0,
  scrollIntoView: (options) => scrollIntoViewCalls.push({name, options}),
  insertAdjacentHTML: (_position, markup) => { elements.get(name).innerHTML += markup; },
  querySelector: () => ({disabled: false}),
});
for (const name of ['#project-form', '#turn-form', '#messages', '#session-title', '#chat', '#chat-settings', '#limits']) {
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
  FormData,
  confirm: (message) => { confirmations.push(message); return false; },
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

test('opening a chat reveals and scrolls to the chat workspace', () => {
  assert.equal(elements.get('#chat').hidden, false);
  const scroll = scrollIntoViewCalls.find((call) => call.name === '#chat');
  assert.equal(scroll.name, '#chat');
  assert.equal(scroll.options.behavior, 'smooth');
  assert.equal(scroll.options.block, 'start');
});

test('opening chat history scrolls the viewport to the latest message', () => {
  const scroll = scrollIntoViewCalls.at(-1);
  assert.equal(scroll.name, '#messages');
  assert.equal(scroll.options.behavior, 'smooth');
  assert.equal(scroll.options.block, 'end');
});

test('later consecutive agent messages appear', async () => {
  assert.ok(intervals.length > 0, 'an open chat must schedule history refreshes');
  await intervals.at(-1)();
  assert.match(messages.innerHTML, /First[\s\S]*Second/);
});

test('context consent is requested only when changing agents', async () => {
  context.switchRequests = switchRequests;
  vm.runInContext(`
    activeSession='chat-1';
    agents={codex:{models:[]},opencode:{models:[]}};
    request=async(path,options)=>{const body=JSON.parse(options.body);switchRequests.push(body);return {agent:body.agent,model:body.model}};
    chatSettings={agent:'codex',model:'test-model',reasoning:'low',sandbox:'workspace_write'};
    selectedChatSettings=()=>({agent:'codex',model:'other-model',reasoning:'low',sandbox:'workspace_write'});
  `, context);
  await vm.runInContext('applyChatSettings()', context);
  assert.equal(confirmations.length, 0);
  assert.equal(switchRequests.at(-1).transfer_context, null);

  vm.runInContext(`selectedChatSettings=()=>({agent:'opencode',model:null,reasoning:null,sandbox:'workspace_write'})`, context);
  await vm.runInContext('applyChatSettings()', context);
  assert.equal(confirmations.length, 1);
  assert.match(confirmations[0], /Передать историю чата/);
  assert.equal(switchRequests.at(-1).transfer_context, false);
});

test('agent usage readout follows the selected agent', () => {
  vm.runInContext(`agents={codex:{usage:{available:true,plan_type:'chatgpt_plus',primary:{remaining_percent:72,window_duration_mins:300},credits:{balance:'12.5'}}},opencode:{usage:{available:true,local:true}}}`, context);
  vm.runInContext("renderAgentUsage('codex')", context);
  assert.match(elements.get('#limits').textContent, /Codex · Plus · 5h: 72% left · Credits: 12.5/);
  vm.runInContext("renderAgentUsage('opencode')", context);
  assert.equal(elements.get('#limits').textContent, 'OpenCode · Local LM Studio · no cloud limit');
});
