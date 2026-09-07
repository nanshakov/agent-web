import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const elements = new Map();
const scrollIntoViewCalls = [];
const confirmations = [];
const switchRequests = [];
const documentEvents = new Map();
const windowEvents = new Map();
const element = (name) => ({
  hidden: false,
  innerHTML: '',
  textContent: '',
  value: '',
  attributes: new Map(),
  scrollHeight: 240,
  scrollTop: 0,
  scrollIntoView: (options) => scrollIntoViewCalls.push({name, options}),
  insertAdjacentHTML: (_position, markup) => { elements.get(name).innerHTML += markup; },
  querySelector: () => ({disabled: false}),
  setAttribute(attribute, value) { this.attributes.set(attribute, value); },
  getAttribute(attribute) { return this.attributes.get(attribute); },
  focus() {},
});
for (const name of ['#project-form', '#turn-form', '#messages', '#session-title', '#chat', '#chat-settings', '#limits', '#voice-record', '#voice-status', '#turn-form [name="prompt"]']) {
  elements.set(name, element(name));
}

const intervals = [];
const recognizers = [];
class SpeechRecognitionMock {
  constructor() { recognizers.push(this); }
  start() { this.onstart(); }
  stop() { this.onend(); }
}
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
    visibilityState: 'visible',
    addEventListener: (name, callback) => documentEvents.set(name, callback),
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
  SpeechRecognition: SpeechRecognitionMock,
  addEventListener: (name, callback) => windowEvents.set(name, callback),
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

test('chat script does not schedule polling', () => {
  assert.doesNotMatch(source, /waitForTurn|\/turns\//);
});

test('agent messages stream while the submitted turn is still marked running', () => {
  const streamed = element('streamed');
  elements.set('[data-stream-turn="live"]', streamed);
  vm.runInContext("turnRunning=true;handleTurnEvent({type:'turn.delta',turn_id:'live',content:'Live reply'})", context);

  assert.equal(streamed.textContent, 'Live reply');
  vm.runInContext('turnRunning=false', context);
});

test('returning to the page or network resynchronizes history and the session stream', async () => {
  context.recoveryCalls = [];
  vm.runInContext(`
    activeSession='chat-1';
    refreshMessages=async()=>recoveryCalls.push('history');
    connectSessionStream=id=>recoveryCalls.push('stream:'+id);
  `, context);

  await documentEvents.get('visibilitychange')();
  await windowEvents.get('pageshow')();
  await windowEvents.get('online')();

  assert.deepEqual(context.recoveryCalls, [
    'history', 'stream:chat-1',
    'history', 'stream:chat-1',
    'history', 'stream:chat-1',
  ]);
});

test('messages render their timestamp when the API provides one', () => {
  const markup = vm.runInContext(
    "messageMarkup({role:'user',content:'Timed',created_at:'2026-09-06T12:34:00Z'})",
    context,
  );
  assert.match(markup, /class=\"timestamp\"/);
  assert.match(markup, /datetime=\"2026-09-06T12:34:00Z\"/);
});

test('voice dictation appends a final transcript to the message draft', () => {
  const voiceButton = elements.get('#voice-record');
  voiceButton.onclick();
  recognizers[0].onresult({
    resultIndex: 0,
    results: [{isFinal: true, 0: {transcript: 'Review the deployment logs'}}],
  });

  assert.equal(elements.get('#turn-form [name="prompt"]').value, 'Review the deployment logs');
  assert.equal(elements.get('#voice-status').textContent, 'Listening…');
  assert.equal(voiceButton.getAttribute('aria-pressed'), 'true');
});

test('project list periodically refreshes discovered chats', async () => {
  vm.runInContext(`
    projectRefreshes=0;
    request=async(path)=>path==='/projects'?[{id:'project-2'}]:[];
    renderProjects=projects=>{projectRefreshes=projects.length};
  `, context);

  await intervals[0]();
  assert.equal(vm.runInContext('projectRefreshes', context), 1);
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

test('turn start errors remain visible after history refresh', async () => {
  const form = elements.get('#turn-form');
  const submitButton = {disabled: false};
  form.prompt = {value: 'Trigger agent'};
  form.querySelector = () => submitButton;
  form.reset = () => {};
  vm.runInContext(`
    activeSession='chat-1';
    applyChatSettings=async()=>{};
    fileInput.files=[];
    request=async()=>{throw new Error('Agent failed to start')};
  `, context);

  await form.onsubmit({preventDefault() {}, target: form});
  assert.match(messages.innerHTML, /Agent failed to start/);

  assert.match(messages.innerHTML, /Agent failed to start/);
});
