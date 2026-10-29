'use strict';
/* Receipt metadata only. No message retry, extra poller or read-status guess. */
window.ChatReceipts = (() => {
  let busy = false, active = null, known = new Set(), lastState = null, lastError = '';
  const phases = ['client_received', 'system_notification_posted', 'user_opened'];
  function context(id) {
    return state.authenticated && state.server && state.username && id
      ? { id, key: 'asteria-chat.receipts.' + JSON.stringify([state.server, state.username, id]) } : null;
  }
  const current = selected => selected && context(state.activeId)?.key === selected.key;
  function read(selected) {
    try { const value = JSON.parse(localStorage.getItem(selected.key) || '{}');
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {}; }
    catch (_) { return {}; }
  }
  function write(selected, value) {
    try { localStorage.setItem(selected.key, JSON.stringify(value)); return true; }
    catch (_) { lastError = '本机无法保存收件确认；聊天记录仍在服务器。'; return false; }
  }
  function enqueue(selected, ids, phase) {
    const pending = read(selected);
    for (const id of ids) {
      const confirmed = lastState?.messages?.find(row => row.message_id === id);
      if (!confirmed?.[phase + '_at']) pending[id] = { ...(pending[id] || {}), [phase]: true };
    }
    const keys = Object.keys(pending);
    while (keys.length > 64) delete pending[keys.shift()];
    return write(selected, pending);
  }
  async function flush(selected) {
    if (busy || !current(selected) || active?.key !== selected.key) return;
    busy = true;
    try {
      for (const phase of phases) {
        // The existing outbox holds at most64 IDs, the server accepts32.
        // Drain both bounded halves during this successful sync, rather than
        // starving the older half every time new replies arrive.
        for (let batch = 0; batch < 2; batch++) {
        if (!current(selected) || active?.key !== selected.key) break;
        const ids = Object.entries(read(selected)).filter(([id, value]) => known.has(id) && value?.[phase] === true)
          .map(([id]) => id).slice(-32);
        if (!ids.length) break;
        const result = await apiClient.json('POST', '/chat/receipts', { session_id: selected.id, phase, message_ids: ids });
        if (!current(selected)) break;
        lastState = result; lastError = '';
        const pending = read(selected);
        for (const id of ids) {
          if (!pending[id]) continue;
          delete pending[id][phase];
          if (!Object.keys(pending[id]).length) delete pending[id];
        }
        write(selected, pending);
        }
      }
    } catch (_) {
      // This endpoint is monotonic/idempotent receipt metadata. The next
      // successful history sync may report it again; user sends never do so.
      lastError = '收件确认尚未同步，下次读取记录时再核对；不会重复发送消息。';
    } finally {
      busy = false; render();
      if (active?.key !== selected.key && current(active)) void flush(active);
    }
  }
  function historyReceived(sessionId, snapshot) {
    const selected = context(sessionId);
    if (!current(selected)) return;
    if (active?.key !== selected.key) { lastState = null; lastError = ''; }
    active = snapshot?.receipt_transport?.schema === 1 && snapshot.receipt_transport.supported === true ? selected : null;
    if (!active) { known = new Set(); render(); return; }
    known = new Set(snapshot.history.filter(row => row?.content?.type === 'bot' && row.id != null).map(row => String(row.id)));
    const ids = [...known].slice(-32);
    if (ids.length) enqueue(selected, ids, 'client_received');
    const opened = read(selected).$opened;
    if (typeof opened === 'string' && known.has(opened) && recoveryForeground()) {
      enqueue(selected, [opened], 'user_opened');
      const pending = read(selected); delete pending.$opened; write(selected, pending);
    }
    void flush(selected);
  }
  function notificationOpened(sessionId, messageId) {
    const selected = context(sessionId);
    if (!selected || typeof messageId !== 'string' || !messageId || messageId.length > 160) return;
    const pending = read(selected); pending.$opened = messageId; write(selected, pending);
    // The notification click alone is insufficient: wait for the same saved
    // message to be received by loadHistory before reporting user_opened.
  }
  function messageOpened(sessionId, messageId) {
    const selected = context(sessionId);
    if (!current(selected) || active?.key !== selected.key || !known.has(messageId)
        || state.cacheDisplay || !recoveryForeground()) return false;
    enqueue(selected, [messageId], 'user_opened');
    void flush(selected);
    return true;
  }
  function render() {
    const box = document.getElementById('chat-server-receipts');
    if (!box) return;
    box.replaceChildren();
    const line = text => { const node = document.createElement('p'); node.textContent = text; box.append(node); };
    if (!current(active)) { line('同步当前对话后查看收件状态；旧服务器可能未提供此能力。'); return; }
    if (lastError) line(lastError);
    const item = lastState?.messages?.at(-1);
    if (!item) { line('尚未读取最近消息的收件记录。'); return; }
    line('服务器：消息已保存');
    for (const [field, label] of [['client_received', '客户端收取'], ['system_notification_posted', '已向系统发布通知'], ['user_opened', '客户端打开消息']])
      line(label + '：' + (item[field + '_at'] ? '客户端已报告' : '尚无报告'));
    line('这是已登录客户端上报，不证明人已读或系统显示了横幅；不改变发送状态。');
  }
  async function refresh() {
    const selected = context(state.activeId);
    if (!current(selected)) { render(); return; }
    try {
      const result = await apiClient.json('GET', '/chat/receipts?session_id=' + encodeURIComponent(selected.id));
      if (!current(selected)) return;
      if (result?.schema === 1) { active = selected; lastState = result; lastError = ''; }
    } catch (_) { if (current(selected)) lastError = '服务器收件记录暂不可读取。'; }
    render();
  }
  return { historyReceived, notificationOpened, messageOpened, refresh, render };
})();
