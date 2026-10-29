import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source = await fs.readFile(new URL('../web/chat-delivery-center.js', import.meta.url), 'utf8');
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.events = {}; this.attributes = {}; this.open = false; this.hidden = false; this.disabled = false; this.textContent = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this.textContent = ''; }
  get firstChild() { return this.children[0]; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, handler) { this.events[name] = handler; }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.(); }
  click() { if (!this.disabled) return this.events.click?.(); }
  get text() { return this.textContent + this.children.map(child => child.text).join(' '); }
}
const body = new Element('body');
const find = (id, item = body) => item.id === id ? item : item.children.map(child => find(id, child)).find(Boolean);
const document = { body, createElement: tag => new Element(tag), getElementById: id => find(id) };
const calls = [], exports = [], notices = [];
let historyClears = 0, attachmentClears = 0, localRefreshes = 0, syncs = 0, mode = 'ok', nextResolve;
let result = { schema: 1, supported: true, read_only: true, messages: [{ message_id: 'PRIVATE-MESSAGE-ID', kind: 'reply',
  stages: { created: { observed: true }, client_received: { observed: true, at: 1793000000 }, system_notification_posted: { observed: false }, user_opened: { observed: false } } }],
  server_queue: { state: 'available', counts: { queued: 3, failed: 1, unknown: 2 }, limited: true,
    items: [{ task_id: 'PRIVATE-TASK-ID', kind: 'proactive', destination: 'chat', state: 'unknown', reason: 'platform_timeout', available_at: 1793000000 }] },
  workspace: { values: { proactive_destination: 'chat_all' } }, PRIVATE: 'PRIVATE-SERVER-PAYLOAD' };
const state = { authenticated: true, server: 'https://PRIVATE-SERVER.invalid/path', username: 'PRIVATE-ACCOUNT', activeId: 'PRIVATE-SESSION',
  messages: [{ role: 'user', delivery: 'unknown', text: 'PRIVATE-BODY' }, { role: 'assistant', delivery: 'unknown' }, { role: 'user', delivery: 'pending' }],
  sending: false, loading: false, attaching: false, appearanceBusy: false, exportBusy: false, creating: false,
  cacheDisplay: { savedAt: 1793000000000 }, attachmentQueues: new Map([['PRIVATE-SESSION', [{ status: 'unknown' }, { status: 'send-unknown' }]]]) };
const pending = { 'PRIVATE-MESSAGE-ID': { client_received: true, user_opened: true }, $opened: 'PRIVATE-OPEN-ID' };
const cache = { sessions: 2, messages: 45, bytes: 1024, updatedAt: 1793000000000 };
const window = { AsteriaChat: {
  getConfig: () => JSON.stringify({ version: '1.4.0', username: 'PRIVATE-ACCOUNT', server: state.server, token: 'PRIVATE-TOKEN' }),
  getAttachmentCacheStatus: () => JSON.stringify({ ok: true, count: 4, bytes: 4096, max_count: 16, max_bytes: 67108864, ttl_hours: 24 }),
  clearRecoverableAttachmentCache() { throw Error('Use the original cache settings action'); },
  getNotificationStatus: () => JSON.stringify({ ok: true, runtime_permission_granted: false, app_notifications_enabled: true, reply_channel: { exists: true, blocked: false } }),
  exportConversation() { throw Error('Use original asynchronous request helper'); },
}, ChatCache: { history: () => ({ updatedAt: 1793000000000 }) },
  ChatCacheSettings: { refresh() { localRefreshes++; } }, ChatSettingsHub: { close() {} } };
for (const [id, handler] of [['chat-cache-history-clear', () => { historyClears++; find('chat-cache-note').textContent = '原记录缓存已清理'; }],
  ['chat-cache-attachment-clear', () => { attachmentClears++; find('chat-cache-note').textContent = '原附件缓存已清理'; }], ['chat-cache-note', () => {}]]) {
  const item = new Element('button'); item.id = id; item.addEventListener('click', handler); body.append(item);
}
const context = vm.createContext({ window, state, document, Date, JSON, Number, Object, Array, Map, Set, Promise,
  localStorage: { getItem(key) { assert.equal(key, 'asteria-chat.receipts.' + JSON.stringify([state.server, state.username, state.activeId])); return JSON.stringify(pending); },
    setItem() { throw Error('Delivery center must not write receipt metadata'); } },
  chatCacheStatus: () => cache, hideMoreMenu() {}, showNotice: value => notices.push(value), renderChrome() {},
  refreshCurrent: async () => { syncs++; return true; },
  exportUtf8Bytes: value => Buffer.byteLength(value, 'utf8'), responseData: value => value.data ?? value,
  nativeAsync: async (method, args) => { assert.equal(method, 'exportConversation'); assert.equal(state.exportBusy, true);
    exports.push(args); return { exported: true, filename: args[0], bytes: Buffer.byteLength(args[1], 'utf8') }; },
  apiClient: { async json(method, path, payload) {
    calls.push({ method, path, payload }); assert.equal(method, 'GET'); assert.equal(payload, undefined);
    if (mode === 'pending') return new Promise(resolve => { nextResolve = resolve; });
    if (mode === 'error') throw Object.assign(Error('PRIVATE-TOKEN PRIVATE-SERVER'), { status: 401 });
    return result;
  } }, setTimeout() { throw Error('No polling/timers permitted'); }, setInterval() { throw Error('No polling permitted'); } });
vm.runInContext(source, context, { filename: 'chat-delivery-center.js' });
const center = window.ChatDeliveryCenter;
assert.equal(calls.length, 0, 'Loading the module starts no network activity');
await center.openDelivery();
assert.equal(calls.length, 1); assert(calls[0].path.startsWith('/chat/delivery-center?session_id='));
assert(find('delivery-center-dialog').open);
await find('delivery-center-refresh').click();
assert.equal(calls.length, 2, 'The actual refresh button callback must perform one new GET');
assert.equal(calls[1].method, 'GET');
assert(calls[1].path.startsWith('/chat/delivery-center?session_id='));
let text = find('delivery-center-delivery').text;
assert(text.includes('PRIVATE-MESSAGE-ID'), 'Display the real saved server ID');
assert(!text.includes('PRIVATE-BODY')); assert(!text.includes('PRIVATE-TASK-ID'));
assert(text.includes('3 条') && text.includes('2 条'));
assert(text.includes('平台等待超时，发送结果未知'));
assert(text.includes('尚无独立记录'), 'Do not infer system notification/opened from receipt');
assert(text.includes('1 条消息 · 2 项确认'), 'Receipt metadata outbox remains distinct from server queue');
await center.openConnection();
text = find('delivery-center-connection').text;
assert(text.includes('TLS 已返回有效结果')); assert(text.includes('1.4.0')); assert(text.includes('未允许'));
assert(!text.includes('PRIVATE-SERVER')); assert(!text.includes('PRIVATE-ACCOUNT'));
const clearButtons = find('delivery-center-connection').children.flatMap(item => item.children).find(item => item.className === 'delivery-center-actions').children;
clearButtons[0].click(); clearButtons[1].click();
assert.equal(historyClears, 1); assert.equal(attachmentClears, 1); assert.equal(localRefreshes, 2);
await find('delivery-center-export').click();
assert.equal(exports.length, 1); assert.match(exports[0][0], /^AsteriaChat-diagnostics-[A-Za-z0-9-]+\.md$/);
assert(Buffer.byteLength(exports[0][1], 'utf8') <= 16384);
for (const secret of ['PRIVATE-', state.server, state.username, state.activeId, 'task_id', 'message_id']) assert(!exports[0][1].includes(secret), secret + ' must not appear in diagnostic export');
assert(exports[0][1].includes('"unknown_sends": 1'));
assert(exports[0][1].includes('"receipt_reports": 2'));
assert.equal(state.exportBusy, false);
await find('delivery-center-sync').click(); assert.equal(syncs, 1);
const beforeBusy = calls.length;
state.sending = true; await center.refresh(); // A read is safe while a send is busy, but export/clear/sync are blocked.
await find('delivery-center-export').click();
assert.equal(exports.length, 1);
state.sending = false;
mode = 'error'; await center.refresh();
assert(find('delivery-center-connection').text.includes('登录已失效'));
assert(!find('delivery-center-note').text.includes('PRIVATE-'));
assert(!find('delivery-center-delivery').text.includes('3 条'), 'A failed refresh cannot keep old queue counts');
assert.equal(calls.length, beforeBusy + 2);
mode = 'pending';
const delayed = center.refresh();
state.username = 'OTHER-ACCOUNT'; center.scopeChanged();
assert.equal(find('delivery-center-dialog').open, false);
nextResolve(result); await delayed;
assert.equal(find('delivery-center-delivery').children.length, 0, 'Discard late reads after account switch');
assert.equal(center.closeActive(), false);
state.authenticated = false; await center.openDelivery(); assert.equal(notices.length, 1);
assert(calls.every(call => call.method === 'GET'), 'The center never sends, reports receipts or clears a server queue');
console.log('delivery center: actual GET outcomes, saved IDs, separate stages/counts, original cache actions/sync, bounded private export and stale-scope fencing passed');
