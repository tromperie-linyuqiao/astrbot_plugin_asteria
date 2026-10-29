'use strict';
/* Open only actual saved rows in the owned active conversation. Receipts remain
   authenticated client observations, not proof that somebody read the text. */
window.ChatMessageNavigation = (() => {
  let serial = 0, lastScope = '';
  const scope = () => state.authenticated && state.activeId
    ? JSON.stringify([state.server, state.username, state.activeId]) : '';
  const saved = id => state.messages.find(item => item.role === 'assistant'
    && item.delivery === 'confirmed' && String(item.serverId) === id);
  async function open(value) {
    const id = typeof value === 'string' ? value : '';
    const owner = scope(), sid = state.activeId, ticket = ++serial;
    lastScope = owner;
    const current = () => owner && owner === scope() && ticket === serial;
    if (!owner || !id || id.length > 160 || /[\u0000-\u001f]/.test(id))
      return { opened: false, reason: '消息编号或当前会话不可用。' };
    hideMoreMenu(); sidebar(false);
    if (!saved(id) || state.cacheDisplay) {
      if (!await refreshCurrent({ preserveUnconfirmed: true, preserveReading: true, accept: current }) || !current())
        return { opened: false, reason: '请等待当前同步完成，再打开消息。' };
    }
    if (!current() || !saved(id)) return { opened: false, reason: '当前已加载记录中没有这条消息。' };
    const message = saved(id);
    const row = [...document.getElementById('messages').querySelectorAll('.message-row')]
      .find(item => item.dataset.messageKey === String(message.id));
    if (!row) return { opened: false, reason: '消息暂未显示，请同步后重试。' };
    const target = { account: chatAccountKey(), sessionId: sid, messageId: id, clickTarget: 'message' };
    notificationTarget = target;
    await new Promise(resolve => requestAnimationFrame(resolve));
    if (!current() || !row.isConnected || !recoveryForeground())
      return { opened: false, reason: '页面或会话已变化。' };
    row.scrollIntoView({ block: 'center', behavior: 'auto' });
    row.classList.add('notification-target');
    if (notificationTarget === target) notificationTarget = null;
    window.ChatReceipts?.messageOpened?.(sid, id);
    return { opened: true };
  }
  function scopeChanged() { const next = scope(); if (next !== lastScope) { lastScope = next; serial++; } }
  return Object.freeze({ open, scopeChanged });
})();
