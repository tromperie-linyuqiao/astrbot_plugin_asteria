import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const html = await fs.readFile(new URL('../web/index.html', import.meta.url), 'utf8');
const source = await fs.readFile(new URL('../web/chat-cache-settings.js', import.meta.url), 'utf8');
const nodes = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], {
  textContent: '', disabled: false, hidden: false, open: false, handlers: {}, addEventListener(name, fn) { this.handlers[name] = fn; }
}]));
assert(nodes.has('notification-preferences'));
const scripts = [...html.matchAll(/<script\b[^>]*\bsrc="([^"]+)"/g)].map(match => match[1]);
assert(scripts.indexOf('chat-cache.js') < scripts.indexOf('app.js'));
assert(scripts.indexOf('chat-notification-preferences.js') > scripts.indexOf('chat-notification-status.js'));
for (const file of scripts) await fs.access(new URL('../web/' + file, import.meta.url));
let init, mutation, historyClears = 0, attachmentClears = 0, rendered = 0;
const calls = [];
const limits = { sessions: 20, messages: 250, accounts: 4, chars: 1500000, ttlMs: 30 * 86400000 };
let stats = { sessions: 2, messages: 42, bytes: 2048, updatedAt: 1793145600000, error: '', limits };
let attachmentStatus = { ok: true, count: 3, bytes: 4096, max_count: 16, max_bytes: 64 * 1048576, ttl_hours: 24 };
let clearResult = { ok: true, removed: 3, failed: 0 };
const state = { authenticated: true, server: 'https://fixture.invalid/tls-chat-api', username: 'fixture-account', sending: false, attaching: false,
  mediaCache: new Map([['saved-image', {}]]), previewElements: [{}] };
const window = { ChatCache: { limits }, AsteriaChat: {
  getAttachmentCacheStatus() { calls.push('status'); return JSON.stringify(attachmentStatus); },
  clearRecoverableAttachmentCache() { calls.push('clear'); attachmentClears++; return JSON.stringify(clearResult); }
}, addEventListener() {} };
const context = vm.createContext({ window, state, URL, Date, document: { hidden: false,
  getElementById(id) { assert(nodes.has(id), 'Missing actual index ID: ' + id); return nodes.get(id); },
  addEventListener(event, fn) { if (event === 'DOMContentLoaded') init = fn; } },
  MutationObserver: class { constructor(fn) { mutation = fn; } observe(target, options) { assert.equal(target, nodes.get('settings-dialog')); assert.deepEqual(Array.from(options.attributeFilter), ['open']); } },
  chatCacheStatus: () => stats, clearRecoverableChatCache: () => { historyClears++; stats = { ...stats, sessions: 0, messages: 0, bytes: 0, updatedAt: 0 }; return { ok: true }; },
  renderMessages: () => { rendered++; } });
vm.runInContext(source, context, { filename: 'chat-cache-settings.js' }); init();
assert.deepEqual(calls, ['status'], 'Loading settings only reads local cache status');
assert.equal(nodes.get('chat-cache-history-count').textContent, '2 段会话 · 42 条已保存消息');
assert(nodes.get('chat-cache-account').textContent.includes('fixture-account'));
assert(nodes.get('chat-cache-history-policy').textContent.includes('30 天'));
assert(nodes.get('chat-cache-history-time').textContent !== '尚无记录缓存');
nodes.get('chat-cache-history-clear').handlers.click();
assert.equal(historyClears, 1); assert.equal(attachmentClears, 0);
assert(nodes.get('chat-cache-note').textContent.includes('草稿、外观和服务器记录保留'));
nodes.get('chat-cache-attachment-clear').handlers.click();
assert.equal(historyClears, 1); assert.equal(attachmentClears, 1); assert.equal(rendered, 1);
assert.equal(state.mediaCache.size, 0); assert.equal(state.previewElements.length, 0);
state.sending = true;
nodes.get('chat-cache-history-clear').handlers.click(); nodes.get('chat-cache-attachment-clear').handlers.click();
assert.equal(historyClears, 1); assert.equal(attachmentClears, 1);
state.sending = false; state.authenticated = false; nodes.get('settings-dialog').open = true; mutation();
assert.equal(nodes.get('chat-cache-history-clear').disabled, true);
assert(nodes.get('chat-cache-account').textContent.includes('登录后'));
state.authenticated = true; stats.error = 'fixture cache error'; attachmentStatus = { ok: false };
nodes.get('chat-cache-refresh').handlers.click();
assert.equal(nodes.get('chat-cache-error').hidden, false); assert.equal(nodes.get('chat-cache-error').textContent, 'fixture cache error');
assert.equal(nodes.get('chat-cache-attachment-clear').disabled, true);
attachmentStatus = { ok: true, count: 1, bytes: 256, max_count: 16, max_bytes: 64 * 1048576, ttl_hours: 24 };
clearResult = { ok: false, removed: 1, failed: 1 }; window.ChatCacheSettings.refresh();
nodes.get('chat-cache-attachment-clear').handlers.click();
assert(nodes.get('chat-cache-note').textContent.includes('部分文件尚未清理'));
console.log('cache settings actual index wiring: script order/assets, read-only status, scoped clears, busy guards, account/error states and partial cleanup passed');
