'use strict';
/* Receipt metadata only. No message retry, extra poller or read-status guess. */
window.ChatReceipts = (() => {
  let busy = false, active = null, known = new Set(), receivedKey = '', lastState = null, lastError = '';
  let refreshSerial = 0;
  const phases = ['client_received', 'system_notification_posted', 'user_opened'];
  const pendingOpenLimit = 32;
  const validOpenId = id => typeof id === 'string' && id.length > 0 && id.length <= 160;
  function pendingOpenIds(value) {
    // Earlier versions stored a single ID under the same key.
    const ids = Array.isArray(value) ? value.slice(-pendingOpenLimit) : [value];
    return [...new Set(ids.filter(validOpenId))];
  }
  function context(id) {
    return state.authenticated && state.server && state.username && id
      ? { id, key: 'texas-chat.receipts.' + JSON.stringify([state.server, state.username, id]) } : null;
  }
  const current = selected => selected && context(state.activeId)?.key === selected.key;
  function clearOpenedNotification(selected, messageId) {
    if (!current(selected) || receivedKey !== selected.key || !known.has(messageId)
        || state.cacheDisplay || !recoveryForeground()) return;
    const bridge = window.AsteriaChat;
    if (typeof bridge?.clearMessageNotification !== 'function') return;
    try { bridge.clearMessageNotification(selected.id, messageId); }
    catch (_) { /* Local cancellation is independent of server receipt metadata. */ }
  }
  function read(selected) {
    try { const value = JSON.parse(localStorage.getItem(selected.key) || '{}');
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {}; }
    catch (_) { return {}; }
  }
  function write(selected, value) {
    try { localStorage.setItem(selected.key, JSON.stringify(value)); return true; }
    catch (_) { lastError = '本机无法保存收件确认；聊天记录仍在服务器。'; return false; }
  }
  function enqueue(selected, ids, phase, pending = read(selected)) {
    for (const id of ids) {
      const confirmed = lastState?.messages?.find(row => row.message_id === id);
      if (!confirmed?.[phase + '_at']) {
        pending[id] = { ...(pending[id] || {}), [phase]: true };
        // Only a newly observed saved row may reopen a previously unavailable ID.
        delete pending[id].unavailable;
      }
    }
    const keys = Object.keys(pending).filter(id => id !== '$opened');
    while (keys.length > 64) delete pending[keys.shift()];
    return write(selected, pending);
  }
  function unavailableIds(result, ids, phase) {
    const outcome = result?.receipt_result, remaining = new Set(ids), unavailable = new Set();
    if (outcome?.phase !== phase || !Array.isArray(outcome.accepted) || !Array.isArray(outcome.unavailable))
      throw Error('receipt_result_incomplete');
    for (const field of ['accepted', 'unavailable']) for (const id of outcome[field]) {
      if (typeof id !== 'string' || !remaining.delete(id)) throw Error('receipt_result_mismatch');
      if (field === 'unavailable') unavailable.add(id);
    }
    if (remaining.size) throw Error('receipt_result_incomplete');
    return unavailable;
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
        // These entries were queued only after actual saved rows were observed.
        // A later history window need not contain the old row again; the server
        // validates the ID against the same owned session before accepting it.
        const ids = Object.entries(read(selected)).filter(([id, value]) => /^[1-9][0-9]{0,18}$/.test(id) && value?.[phase] === true)
          .map(([id]) => id).slice(-32);
        if (!ids.length) break;
        const partial = active.partial === true;
        const body = { session_id: selected.id, phase, message_ids: ids };
        if (partial) body.allow_partial = true;
        const result = await apiClient.json('POST', '/chat/receipts', body);
        if (!current(selected)) break;
        const unavailable = partial ? unavailableIds(result, ids, phase) : new Set();
        // A confirmed report supersedes reads still waiting for their result.
        refreshSerial++;
        lastState = result; lastError = '';
        const pending = read(selected);
        for (const id of ids) {
          if (!pending[id]) continue;
          // Keep a bounded explanation in the same metadata, not a success
          // receipt. No other phase can be confirmed for an unavailable row.
          if (unavailable.has(id)) { pending[id] = { unavailable: true }; continue; }
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
    receivedKey = selected.key;
    known = new Set((Array.isArray(snapshot?.history) ? snapshot.history : [])
      .filter(row => row?.content?.type === 'bot' && row.id != null).map(row => String(row.id)));
    active = snapshot?.receipt_transport?.schema === 1 && snapshot.receipt_transport.supported === true
      ? { ...selected, partial: snapshot.receipt_transport.partial_reports === true } : null;
    reconcileNotificationOpens(selected);
    if (!active) { render(); return; }
    const ids = [...known].slice(-32);
    if (ids.length) enqueue(selected, ids, 'client_received');
    void flush(selected);
  }
  function reconcileNotificationOpens(selected) {
    if (state.cacheDisplay || !recoveryForeground()) return;
    const pending = read(selected);
    const opened = pendingOpenIds(pending.$opened);
    const matched = opened.filter(id => known.has(id));
    if (!matched.length) return;
    for (const id of matched) clearOpenedNotification(selected, id);
    const waiting = opened.filter(id => !known.has(id));
    if (waiting.length) pending.$opened = waiting;
    else delete pending.$opened;
    if (active) enqueue(selected, matched, 'user_opened', pending);
    else write(selected, pending);
  }
  function notificationOpened(sessionId, messageId) {
    const selected = context(sessionId);
    if (!selected || !validOpenId(messageId)) return;
    const pending = read(selected);
    const opened = pendingOpenIds(pending.$opened).filter(id => id !== messageId);
    pending.$opened = [...opened, messageId].slice(-pendingOpenLimit);
    write(selected, pending);
    // The notification click alone is insufficient: wait for the same saved
    // message to be received by loadHistory before reporting user_opened.
  }
  function messageOpened(sessionId, messageId) {
    const selected = context(sessionId);
    if (!current(selected) || receivedKey !== selected.key || !known.has(messageId)
        || state.cacheDisplay || !recoveryForeground()) return false;
    clearOpenedNotification(selected, messageId);
    if (active?.key === selected.key) {
      enqueue(selected, [messageId], 'user_opened');
      void flush(selected);
    }
    return true;
  }
  function render() {
    const box = document.getElementById('chat-server-receipts');
    if (!box) return;
    box.replaceChildren();
    const line = text => { const node = document.createElement('p'); node.textContent = text; box.append(node); };
    if (!current(active)) { line('同步当前对话后查看收件状态；旧服务器可能未提供此能力。'); return; }
    if (lastError) line(lastError);
    const unavailable = Object.values(read(active)).filter(row => row?.unavailable === true).length;
    if (unavailable) line(unavailable + ' 条原消息已不可用于确认；保留此记录，其他消息继续同步。');
    const item = lastState?.messages?.at(-1);
    if (!item) { line('尚未读取最近消息的收件记录。'); return; }
    line('服务器：消息已保存');
    for (const [field, label] of [['client_received', '客户端收取'], ['system_notification_posted', '已向系统发布通知'], ['user_opened', '客户端打开记录']])
      line(label + '：' + (item[field + '_at'] ? '客户端已报告' : '尚无报告'));
    line('打开记录可能来自通知点击或应用内跳转，包含仅进入会话的情况。回执无法确认是否定位到某条消息、是否已读或是否显示了横幅。发送状态单独记录。');
  }
  async function refresh() {
    const selected = context(state.activeId);
    if (!current(selected)) { render(); return; }
    const serial = ++refreshSerial;
    const fresh = () => serial === refreshSerial && current(selected);
    try {
      const result = await apiClient.json('GET', '/chat/receipts?session_id=' + encodeURIComponent(selected.id));
      if (!fresh()) return;
      if (result?.schema === 1) { active = { ...selected, partial: result.partial_reports === true }; lastState = result; lastError = ''; }
    } catch (_) {
      if (!fresh()) return;
      lastError = '服务器收件记录暂不可读取。';
    }
    render();
  }
  return { historyReceived, notificationOpened, messageOpened, refresh, render };
})();
