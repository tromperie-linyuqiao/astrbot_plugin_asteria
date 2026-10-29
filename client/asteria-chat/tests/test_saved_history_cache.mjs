import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const cacheSource = await fs.readFile(new URL('../web/chat-cache.js', import.meta.url), 'utf8');
const appSource = await fs.readFile(new URL('../web/app.js', import.meta.url), 'utf8');
const revision = 'a'.repeat(64);
const row = (id, text = 'saved ' + id, type = 'bot') => ({ id, created_at: '2026-10-28T00:00:00Z', content: { type, message: [{ type: 'plain', text }] } });
const snapshot = (rows, extra = {}) => ({ history: rows, history_revision: revision, is_running: false, active_runs: [], ...extra });
const storage = new Map();
let now = Date.now(), quota = false;
class ClockDate extends Date { static now() { return now; } }
function environment() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { value: '', textContent: '', hidden: false, dataset: {}, classList: { add() {}, toggle() {} },
      querySelectorAll: () => [], addEventListener() {}, setAttribute() {}, close() {}, style: {} });
    return elements.get(id);
  };
  const context = vm.createContext({ window: { addEventListener() {}, AsteriaChat: { getConfig: () => JSON.stringify({ foreground: true }), clearAuth() {} } },
    document: { hidden: false, getElementById: element, addEventListener() {} }, navigator: { onLine: true },
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => { if (quota) throw Error('quota'); storage.set(key, value); }, removeItem: key => storage.delete(key) },
    Date: ClockDate, URL, Intl, setTimeout: () => 1, clearTimeout() {}, requestAnimationFrame: fn => fn(), console });
  vm.runInContext(cacheSource, context);
  return { context, cache: context.window.ChatCache, elements, element };
}
const json = value => JSON.parse(JSON.stringify(value));
let { cache } = environment();
const server = 'https://one.invalid', user = 'alice';
cache.sessions(server, user, [{ session_id: 's1', display_name: '伙伴', primary: true }, { session_id: 's2' }], 's1');
cache.save(server, user, 's1', snapshot([row(1, 'first'), row(2, 'second')]));
cache.save(server, user, 's2', snapshot([row(3)]));
cache = environment().cache; // A different renderer process, same persisted storage.
assert.equal(cache.restore(server, user).lastId, 's2');
assert.equal(cache.history(server, user, 's1').snapshot.history[1].content.message[0].text, 'second');
assert.equal(cache.history(server, 'bob', 's1'), null);
assert.equal(cache.history('https://two.invalid', user, 's1'), null);
assert.equal(cache.history(server, user, 's1').revision, revision);
cache.save(server, user, 's1', snapshot([row(2, 'edited'), row(2), row(4)]));
assert.deepEqual(json(cache.history(server, user, 's1').snapshot.history.map(value => value.id)), [2, 4]);
assert.equal(cache.history(server, user, 's1').revision, null, 'Deduped/incomplete response cannot authorize conditional reads');
cache.save(server, user, 's1', snapshot([row(4)], { is_running: true, active_runs: [{ content: { message: [{ type: 'plain', text: 'UNCONFIRMED SECRET' }] } }] }));
assert.equal(cache.history(server, user, 's1').revision, null);
assert(![...storage.values()].join('').includes('UNCONFIRMED SECRET'));
cache.save(server, user, 's1', snapshot(Array.from({ length: 300 }, (_, i) => row(i))));
assert.equal(cache.history(server, user, 's1').snapshot.history.length, 250);
assert.equal(cache.history(server, user, 's1').snapshot.history[0].id, 50);
assert.equal(cache.history(server, user, 's1').complete, false);
cache.sessions(server, user, [{ session_id: 's1' }], 's1');
assert.equal(cache.history(server, user, 's2'), null, 'Server list removal evicts the old session');
storage.set('asteria-chat.draft.owned', 'my unsent draft'); storage.set('asteria-chat.appearance.owned', 'avatar');
cache.clear(server, user);
assert.equal(cache.restore(server, user), null);
assert.equal(storage.get('asteria-chat.draft.owned'), 'my unsent draft');
assert.equal(storage.get('asteria-chat.appearance.owned'), 'avatar');
cache.sessions(server, user, [{ session_id: 's1' }], 's1'); cache.save(server, user, 's1', snapshot([row(1)]));
now += cache.limits.ttlMs + 1;
assert.equal(cache.restore(server, user), null);
assert(![...storage.values()].join('').includes('saved 1'));
cache.sessions(server, user, [{ session_id: 's1' }], 's1');
quota = true;
assert.equal(cache.save(server, user, 's1', snapshot([row(1)])), false);
assert.equal(storage.get('asteria-chat.draft.owned'), 'my unsent draft');
quota = false;
storage.set('asteria-chat.saved-history.v1', '{corrupt');
assert.equal(cache.restore(server, user), null);
for (let index = 0; index < 7; index++) {
  cache.sessions(server, 'account' + index, Array.from({ length: 25 }, (_, i) => ({ session_id: 's' + i })), 's24');
  cache.save(server, 'account' + index, 's24', snapshot([row(index, 'x'.repeat(400000))]));
  now++;
}
assert((storage.get('asteria-chat.saved-history.v1') || '').length <= cache.limits.chars);
assert(JSON.parse(storage.get('asteria-chat.saved-history.v1')).accounts.length <= cache.limits.accounts);
assert.equal(cache.restore(server, 'account6').sessions[0].session_id, 's24');

// Real app entry points: cache-first rendering, revision revalidation, removals,
// late account replies and unknown-send preservation without any POST path.
const env = environment();
vm.runInContext(appSource + `
  renderChrome = () => {}; renderMessages = () => {}; renderSessions = () => {};
  cancelAppearance = () => {}; cancelInteractions = () => {}; sidebar = () => {};
  saveDraft = () => {}; restoreDraft = () => {}; hideNotice = () => {};
  showNotice = () => {}; resizeDraft = () => {}; renderPendingActions = () => {};
  globalThis.test = { state, apiClient, loadHistory, loadSessions, selectSession, restoreCachedConversation,
    restoreCachedHistory, clearRecoverableChatCache, chatCacheStatus, receive,
    invalidateAuth: () => { chatAuthEpoch++; }, locateNotificationMessage };
`, env.context);
const api = env.context.test;
Object.assign(api.state, { authenticated: true, server, username: user, sessions: [{ session_id: 's1', primary: true }], activeId: 's1' });
env.cache.sessions(server, user, api.state.sessions, 's1'); env.cache.save(server, user, 's1', snapshot([row(1)]));
api.state.activeId = null; api.state.sessions = [];
assert.equal(api.restoreCachedConversation(), true);
assert.equal(api.state.activeId, 's1'); assert.equal(api.state.messages[0].serverId, 1);
let reads = [];
api.apiClient.history = async (id, options) => { reads.push({ id, options }); return { not_modified: true, history_revision: revision }; };
env.context.navigator.onLine = false;
await api.selectSession('s1');
assert.equal(reads.length, 0);
assert.equal(api.state.messages[0].delivery, 'confirmed');
assert(api.state.cacheDisplay);
env.context.navigator.onLine = true;
api.state.messages.push({ id: 'local', role: 'user', text: 'uncertain', delivery: 'unknown', clientMessageId: 'unconfirmed-id' });
await api.loadHistory('s1', { preserveUnconfirmed: true });
assert.equal(reads[0].options.knownRevision, revision);
assert.equal(api.state.cacheDisplay, null);
assert(api.state.messages.some(value => value.delivery === 'unknown'));
assert(!JSON.stringify(env.cache.history(server, user, 's1')).includes('uncertain'));
api.apiClient.history = async () => snapshot([row(2, 'server now removed 1')]);
await api.loadHistory('s1');
assert.deepEqual(json(api.state.messages.map(value => value.serverId)), [2]);
assert.deepEqual(json(env.cache.history(server, user, 's1').snapshot.history.map(value => value.id)), [2]);
let finish;
api.apiClient.history = () => new Promise(resolve => { finish = resolve; });
const late = api.loadHistory('s1');
api.state.username = 'bob'; finish(snapshot([row(99, 'alice private')])); await late;
assert(!api.state.messages.some(value => value.serverId === 99));
assert.equal(env.cache.history(server, 'bob', 's1'), null);
api.state.username = user;
api.apiClient.history = async () => { const error = new Error('gone'); error.status = 404; throw error; };
await assert.rejects(api.loadHistory('s1'), /gone/);
assert.equal(api.state.activeId, null);
assert.equal(env.cache.history(server, user, 's1'), null);
api.state.sessions = [{ session_id: 's1' }]; api.state.activeId = 's1';
env.cache.sessions(server, user, api.state.sessions, 's1'); env.cache.save(server, user, 's1', snapshot([row(1)]));
api.restoreCachedHistory('s1');
api.apiClient.sessions = async () => [];
await api.loadSessions({ select: false });
assert.equal(api.state.activeId, null);
assert.equal(env.cache.history(server, user, 's1'), null);
api.state.sessions = [{ session_id: 's1' }]; api.state.activeId = 's1';
env.cache.sessions(server, user, api.state.sessions, 's1'); env.cache.save(server, user, 's1', snapshot([row(1)]));
let round = 0;
api.apiClient.history = async () => ++round === 1 ? { not_modified: true, history_revision: 'b'.repeat(64) } : snapshot([row(8)]);
await api.loadHistory('s1'); assert.equal(round, 2); assert.equal(api.state.messages[0].serverId, 8);
api.restoreCachedHistory('s1'); api.clearRecoverableChatCache();
assert.equal(api.state.messages.length, 0); assert.equal(env.cache.history(server, user, 's1'), null);
let rejected = '';
api.state.requests.set('old-auth', { authEpoch: 0, reject: error => { rejected = error.message; }, resolve: () => { throw Error('stale response accepted'); } });
api.invalidateAuth(); api.receive('old-auth', { status: 401, body: {} });
assert(rejected.includes('账户已切换')); assert.equal(api.state.authenticated, true);
let scrolled = 0, receipt = null;
api.state.activeId = 's1'; api.state.messages = [{ id: '8|checkpoint', serverId: 8, role: 'assistant', delivery: 'confirmed' }];
env.element('messages').querySelectorAll = () => [{ dataset: { messageKey: '8|checkpoint' }, classList: { add() {} }, scrollIntoView() { scrolled++; } }];
env.context.window.ChatReceipts = { notificationOpened(id, messageId) { receipt = [id, messageId]; } };
env.context.window.AsteriaChatUI.openConversation('s1', '8', 'message'); api.locateNotificationMessage();
assert.equal(scrolled, 1); assert.deepEqual(receipt, ['s1', '8']);
env.context.window.AsteriaChatUI.openConversation('s1', '8', 'conversation'); api.locateNotificationMessage();
assert.equal(scrolled, 1, 'Conversation clicks do not jump to an individual message');
console.log('saved history cache: persistence, scope isolation, bounded storage, TTL, quota, cache-first, revision, removal and stale-response cases passed');
