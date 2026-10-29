'use strict';
/* Display local status on demand. No sync request or background timer. */
window.ChatCacheSettings = (() => {
  const get = id => document.getElementById(id);
  const size = bytes => bytes < 1024 ? bytes + ' B' : bytes < 1048576 ? (bytes / 1024).toFixed(1) + ' KB' : (bytes / 1048576).toFixed(1) + ' MB';
  function nativeCache(method) {
    const bridge = window.AsteriaChat;
    if (!bridge || typeof bridge[method] !== 'function') return null;
    const result = bridge[method]();
    return typeof result === 'string' ? JSON.parse(result) : result;
  }
  function say(text) { get('chat-cache-note').textContent = text; }
  function refresh() {
    if (!get('chat-cache-settings')) return;
    const loggedIn = state.authenticated && !!state.server && !!state.username;
    const status = loggedIn ? chatCacheStatus() : { sessions: 0, messages: 0, bytes: 0, updatedAt: 0 };
    const limits = status.limits || window.ChatCache?.limits;
    let host = state.server;
    try { host = new URL(state.server).host; } catch (_) {}
    get('chat-cache-account').textContent = loggedIn ? '当前账户：' + state.username + ' · ' + host : '登录后查看当前账户的本机记录缓存。';
    get('chat-cache-history-count').textContent = status.sessions + ' 段会话 · ' + status.messages + ' 条已保存消息';
    get('chat-cache-history-time').textContent = status.updatedAt ? new Date(status.updatedAt).toLocaleString('zh-CN', { hour12: false }) : '尚无记录缓存';
    get('chat-cache-history-size').textContent = '约 ' + size(status.bytes || 0);
    get('chat-cache-history-policy').textContent = limits
      ? '每账户最多 ' + limits.sessions + ' 段会话，每段最近 ' + limits.messages + ' 条；' + Math.round(limits.ttlMs / 86400000) + ' 天后过期。最多保留 ' + limits.accounts + ' 个账户，记录缓存合计约 ' + size(limits.chars * 2) + ' 上限，超出时清理较旧副本。'
      : '当前界面尚未提供记录缓存。';
    get('chat-cache-history-clear').disabled = !loggedIn || !window.ChatCache || state.sending || state.attaching;
    let attachmentError = '';
    try {
      const attachments = nativeCache('getAttachmentCacheStatus');
      if (attachments?.ok !== true) {
        get('chat-cache-attachment-state').textContent = '当前客户端暂不能读取附件缓存信息。';
        get('chat-cache-attachment-clear').disabled = true;
      } else {
        get('chat-cache-attachment-state').textContent = attachments.count + ' 个下载副本 · ' + size(attachments.bytes || 0)
          + '；最多 ' + attachments.max_count + ' 个、' + size(attachments.max_bytes) + '，保留 ' + attachments.ttl_hours + ' 小时。';
        get('chat-cache-attachment-clear').disabled = typeof window.AsteriaChat?.clearRecoverableAttachmentCache !== 'function' || state.attaching || state.sending;
      }
    } catch (_) {
      attachmentError = '附件缓存信息暂不可读取。';
      get('chat-cache-attachment-state').textContent = attachmentError;
      get('chat-cache-attachment-clear').disabled = true;
    }
    const error = [status.error, attachmentError].filter(Boolean).join(' ');
    get('chat-cache-error').textContent = error; get('chat-cache-error').hidden = !error;
  }
  function clearHistory() {
    if (!state.authenticated || !state.server || !state.username || state.sending || state.attaching) return;
    const result = clearRecoverableChatCache();
    refresh();
    say(result.ok ? '当前账户的本机记录缓存已清理。草稿、外观和服务器记录保留。' : '缓存清理未完成，请查看上方提示后重试。');
  }
  function clearAttachments() {
    if (state.attaching || state.sending) return;
    try {
      const result = nativeCache('clearRecoverableAttachmentCache');
      if (!result) { say('当前客户端尚不支持清理附件缓存。'); return; }
      state.mediaCache.clear(); state.previewElements = []; renderMessages();
      refresh();
      say(result.ok === true ? '已清理 ' + (result.removed || 0) + ' 个本机下载副本。原文件保留。'
        : '已清理 ' + (result.removed || 0) + ' 个副本，部分文件尚未清理，请稍后重试。');
    } catch (_) { say('附件缓存清理未完成，请稍后重试。'); }
  }
  document.addEventListener('DOMContentLoaded', () => {
    get('chat-cache-refresh').addEventListener('click', () => { say(''); refresh(); });
    get('chat-cache-history-clear').addEventListener('click', clearHistory);
    get('chat-cache-attachment-clear').addEventListener('click', clearAttachments);
    refresh();
    const dialog = get('settings-dialog');
    if (typeof MutationObserver === 'function') new MutationObserver(() => { if (dialog.open) { say(''); refresh(); } }).observe(dialog, { attributes: true, attributeFilter: ['open'] });
    window.addEventListener('focus', () => { if (dialog.open) refresh(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden && dialog.open) refresh(); });
  }, { once: true });
  return Object.freeze({ refresh });
})();
