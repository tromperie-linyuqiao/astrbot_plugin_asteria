'use strict';
/* On-demand inbox over the original saved messages, delivery queue and receipts.
   No second inbox database, sender, receipt writer, timer or push service. */
window.ChatNotificationCenter = (() => {
  const LIMIT = 32;
  const kinds = { reply: '聊天回复', proactive: '主动消息', reminder: '日程提醒' };
  const states = { candidate: '待批准', approved: '待入队', queued: '待发送', claimed: '已领取', sending: '发送中', retry_wait: '等待重试', paused: '已暂停', confirmed: '原发送端已确认', failed: '发送失败', unknown: '结果未知', cancelled: '已取消', expired: '已过期', quarantined: '已隔离' };
  const reasons = { awaiting_approval: '等待原系统批准', awaiting_queue: '等待入队', awaiting_dispatch: '等待发送处理', worker_claimed: '发送端已领取', dispatch_in_progress: '原发送端正在处理', original_queue_backoff: '按原队列节奏等待', original_queue_paused: '原队列已暂停', original_sender_confirmed: '原发送端已确认', original_sender_failed: '原发送端报告失败', dispatch_outcome_unknown: '请先核对实际结果', original_queue_cancelled: '原任务已取消', delivery_expired: '已超过发送期限', original_queue_quarantined: '等待原系统处理', authorization_denied: '没有发送权限', authorization_revoked: '发送权限已收回', revoked_before_dispatch: '发送前权限已收回', adapter_unavailable: '原连接暂不可用', prepare_unavailable: '原消息或媒体暂不可准备', route_unavailable: '原发送位置不可用', platform_timeout: '平台超时，结果未知', ambiguous_receipt: '平台确认不明确', dispatch_cancelled: '发送中断，结果待核对', platform_exception: '平台异常，结果待核对', sdk_confirmed: '原平台已确认', adapter_capacity: '原发送端繁忙', frequency_gate: '等待原消息节奏限制解除', service_stopping: '原服务正在停止', waiting_for_real_scope: '等待原会话授权恢复', image_required: '原规则要求图片', attempts_exhausted: '原发送尝试已用尽', policy_deferred: '等待原免打扰或消息节奏限制解除' };
  let dialog, owner = '', epoch = 0, serial = 0, reading = false, snapshot = null, error = '';
  let filter = 'texas', onlyPending = false, collapsed = false, updatedAt = 0;
  const key = () => JSON.stringify([state.server, state.username, state.activeId]);
  const ready = () => !!(state.authenticated && state.server && state.username && state.activeId);
  const current = selected => ready() && owner === key() && owner === selected.owner && epoch === selected.epoch && dialog?.open;
  const get = id => document.getElementById(id);
  const text = (tag, value = '', className = '') => { const node = document.createElement(tag); node.textContent = value; node.className = className; return node; };
  const button = (label, handler, className = 'text-button') => { const node = text('button', label, className); node.type = 'button'; node.addEventListener('click', handler); return node; };
  const clean = (value, maximum = 220) => typeof value === 'string' ? value.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').slice(0, maximum) : '';
  const validId = value => typeof value === 'string' && value.length > 0 && value.length <= 160 && !/[\u0000-\u001f]/.test(value);
  function localMessages() { return (Array.isArray(state.messages) ? state.messages : []).filter(row => row?.delivery === 'confirmed' && row.serverId != null); }
  function savedMessage(id) { return localMessages().find(row => row.role === 'assistant' && String(row.serverId) === id); }
  function preview(row) {
    if (!row) return '同步记录后查看正文';
    if (Array.isArray(row.parts) && row.parts.length) {
      const values = row.parts.map(part => {
        if (part?.type === 'plain') return clean(part.text, 220);
        if (part?.type === 'action' && part.source === 'assistant_narrative') return clean(part.description || part.label, 220);
        return ['image', 'expression'].includes(part?.type) ? '[表情或图片]' : part?.type === 'file' ? '[文件]' : '';
      }).filter(Boolean);
      if (values.length) return clean(values.join(' '), 220);
      return '这条消息包含可在聊天中查看的内容';
    }
    return clean(row.text) || '打开聊天查看这条消息';
  }
  function viewed(item) {
    if (item.stages?.user_opened?.observed === true) return 'opened';
    // Reuse the existing visible-history cursor; never advance it here.
    let cursor;
    try { cursor = JSON.parse(storage.get(pref('read-cursor.' + encodeURIComponent(key()))) || 'null'); } catch (_) { return ''; }
    if (!cursor || cursor.message_id == null) return '';
    const rows = localMessages(), last = rows.findIndex(row => String(row.serverId) === String(cursor.message_id));
    const index = rows.findIndex(row => String(row.serverId) === item.message_id);
    return last >= 0 && index >= 0 && index <= last ? 'local' : '';
  }
  function savedRows() {
    const seen = new Set();
    return (Array.isArray(snapshot?.messages) ? snapshot.messages : []).slice(-LIMIT).filter(row => validId(row?.message_id) && !seen.has(row.message_id) && seen.add(row.message_id)).reverse();
  }
  function note(value) { get('notification-center-note').textContent = value; }
  function mount() {
    if (dialog) return;
    dialog = text('dialog', '', 'settings-dialog notification-center-dialog'); dialog.id = 'notification-center-dialog'; dialog.setAttribute('aria-labelledby', 'notification-center-title');
    const form = text('div', '', 'settings-form'), heading = text('div', '', 'dialog-heading'), title = text('h2', '通知中心'); title.id = 'notification-center-title';
    const close = button('×', closeActive, 'icon-button'); close.setAttribute('aria-label', '关闭通知中心'); heading.append(title, close); form.append(heading);
    form.append(text('p', '先看她说了什么，再按需查看提醒和同步状态。', 'notification-center-intro'));
    const tabs = text('div', '', 'notification-center-tabs'); tabs.setAttribute('role', 'group'); tabs.setAttribute('aria-label', '通知分类');
    for (const [name, label] of [['texas', '伙伴'], ['reminder', '提醒'], ['tasks', '待处理'], ['sync', '同步'], ['all', '全部消息']]) {
      const item = button(label, () => select(name), 'notification-center-filter'); item.id = 'notification-center-filter-' + name; tabs.append(item);
    }
    form.append(tabs);
    const controls = text('div', '', 'notification-center-toolbar'), label = text('label', '', 'notification-center-unread-toggle'), toggle = text('input'); toggle.type = 'checkbox'; toggle.id = 'notification-center-pending';
    toggle.addEventListener('change', () => { onlyPending = toggle.checked; render(); }); label.append(toggle, text('span', '仅看尚无查看记录')); controls.append(label);
    const collapse = button('收起已查看', () => { collapsed = !collapsed; render(); }); collapse.id = 'notification-center-collapse'; controls.append(collapse); form.append(controls);
    const list = text('section', '', 'notification-center-list'); list.id = 'notification-center-list'; list.setAttribute('aria-label', '当前会话通知'); form.append(list);
    const actions = text('div', '', 'notification-center-actions');
    const refresh = button('刷新通知', () => read()); refresh.id = 'notification-center-refresh';
    actions.append(refresh, button('查看送达阶段', () => { closeActive(); window.ChatDeliveryCenter?.openDelivery(); }), button('通知权限与设置', () => { closeActive(); window.ChatNotificationStatus?.open(); }));
    form.append(actions);
    const status = text('p', '', 'appearance-help'); status.id = 'notification-center-note'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); form.append(status);
    form.append(text('p', '“本机已浏览”来自原聊天阅读位置；“已有打开记录”来自客户端回执。两者均不证明人已读。收起只影响本次列表，不删除消息或完成服务器任务。', 'notification-center-footnote'));
    dialog.append(form); document.body.append(dialog);
    dialog.addEventListener('cancel', event => { event.preventDefault(); closeActive(); });
    dialog.addEventListener('close', invalidate);
  }
  function invalidate() { owner = ''; epoch++; serial++; reading = false; snapshot = null; error = ''; updatedAt = 0; }
  function select(name) { filter = name; collapsed = false; render(); }
  function stageLabel(item) {
    const stages = item.stages || {};
    if (stages.user_opened?.observed === true) return '已有打开记录';
    if (viewed(item) === 'local') return '本机已浏览';
    if (stages.system_notification_posted?.observed === true) return '系统通知已发布 · 尚无查看记录';
    if (stages.client_received?.observed === true) return '客户端已收取 · 尚无查看记录';
    return '服务器已保存 · 尚无查看记录';
  }
  async function navigate(item) {
    if (!ready() || owner !== key()) return;
    const selected = key(), messageId = item.message_id;
    if (typeof window.ChatMessageNavigation?.open !== 'function') { note('当前版本暂不能直接定位，请同步后在聊天记录中查看。'); return; }
    closeActive();
    try {
      const result = await window.ChatMessageNavigation.open(messageId);
      if (ready() && key() === selected && !(result === true || result?.opened === true)) showNotice('没有定位到这条已保存消息；请先同步记录后再查看。', null, true);
    } catch (_) { if (ready() && key() === selected) showNotice('消息定位未完成；原消息和服务器任务保持不变。', null, true); }
  }
  function messageCard(item) {
    const view = viewed(item), row = text('article', '', 'notification-center-card' + (view ? '' : ' notification-center-unseen'));
    row.setAttribute('data-notification-message', item.message_id);
    const heading = text('div', '', 'notification-center-card-heading'); heading.append(text('strong', item.kind === 'reminder' ? '日程提醒' : '伙伴'), text('span', kinds[item.kind] || '消息', 'notification-center-kind')); row.append(heading);
    row.append(text('p', preview(savedMessage(item.message_id)), 'notification-center-preview'));
    row.append(text('p', stageLabel(item), 'notification-center-stage'));
    const open = button('打开这条消息', () => navigate(item), 'notification-center-open'); open.setAttribute('aria-label', '打开' + (kinds[item.kind] || '消息')); row.append(open);
    return row;
  }
  function taskCards(box) {
    const queue = snapshot?.server_queue;
    if (queue?.state !== 'available') { box.append(text('p', '原发送队列暂不可读取，不会将其显示为空。', 'notification-center-empty')); return; }
    const items = (Array.isArray(queue.items) ? queue.items : []).slice(0, LIMIT).filter(item => !['confirmed', 'cancelled', 'expired'].includes(item?.state));
    if (!items.length) box.append(text('p', '当前保留窗口内没有待处理记录。', 'notification-center-empty'));
    for (const item of items) {
      const row = text('article', '', 'notification-center-card'); row.append(text('strong', (kinds[item.kind] || '消息') + ' · ' + (states[item.state] || '待核对')));
      row.append(text('p', reasons[item.reason] || '请在原系统核对处理结果。', 'notification-center-preview'));
      row.append(text('small', '原任务 · ' + (item.destination === 'qq' ? 'QQ' : 'Chat') + ' · 查看不会重试发送或完成任务', 'notification-center-stage')); box.append(row);
    }
    const action = button('打开原送达记录', () => { closeActive(); window.ChatDeliveryCenter?.openDelivery(); }); box.append(action);
  }
  function syncCards(box) {
    const rows = Array.isArray(state.messages) ? state.messages : [], files = state.attachmentQueues?.get(state.activeId) || [];
    const statuses = [
      ['发送结果待核对', rows.filter(row => row.role === 'user' && row.delivery === 'unknown').length],
      ['尚未确认的提交', rows.filter(row => row.role === 'user' && ['pending', 'unconfirmed'].includes(row.delivery)).length],
      ['附件上传结果待核对', files.filter(row => row.status === 'unknown').length],
      ['附件发送结果待核对', files.filter(row => row.status === 'send-unknown').length]
    ];
    const row = text('article', '', 'notification-center-card'); row.append(text('strong', '本机同步状态'));
    for (const [label, count] of statuses) row.append(text('p', label + '：' + count, 'notification-center-stage'));
    row.append(text('p', '结果未知时先同步核对，不会在这里自动重发。', 'appearance-help'));
    try {
      const raw = window.AsteriaChat?.getReplyWatchStatus?.(), watch = typeof raw === 'string' ? JSON.parse(raw) : raw;
      if (watch?.message_sync === 'cursor_unavailable') row.append(text('p', '后台旧同步位置已不可用，请打开聊天核对记录；不会把旧消息重新当成新通知。', 'appearance-help'));
      if (watch?.notification_outcome_unknown > 0) row.append(text('p', '有' + watch.notification_outcome_unknown + '条系统通知的发布结果待核对；原消息仍在聊天中，不会自动重弹。', 'appearance-help'));
    } catch (_) { /* The native diagnostics entry remains available. */ }
    row.append(button('查看连接与缓存', () => { closeActive(); window.ChatDeliveryCenter?.openConnection(); })); box.append(row);
  }
  function render() {
    if (!dialog?.open || !ready() || owner !== key()) return;
    const box = get('notification-center-list'); box.replaceChildren();
    for (const name of ['texas', 'reminder', 'tasks', 'sync', 'all']) get('notification-center-filter-' + name).setAttribute('aria-pressed', String(filter === name));
    const isMessages = ['texas', 'reminder', 'all'].includes(filter);
    get('notification-center-pending').disabled = !isMessages; get('notification-center-collapse').disabled = !isMessages;
    get('notification-center-collapse').textContent = collapsed ? '显示已查看' : '收起已查看';
    get('notification-center-refresh').disabled = reading;
    if (filter === 'tasks') taskCards(box);
    else if (filter === 'sync') syncCards(box);
    else {
      const all = savedRows().filter(row => filter === 'all' || filter === 'reminder' ? filter === 'all' || row.kind === 'reminder' : row.kind !== 'reminder');
      const rows = all.filter(item => !(onlyPending || collapsed) || !viewed(item));
      if (!rows.length) box.append(text('p', reading ? '正在读取…' : error ? '本次读取未完成，请刷新或检查连接。' : all.length ? '此筛选下没有尚无查看记录的消息。' : '当前保留窗口内没有这类消息。', 'notification-center-empty'));
      for (const item of rows) box.append(messageCard(item));
    }
    if (error) note(error);
    else if (reading) note('正在读取当前会话的真实记录…');
    else if (updatedAt) note('更新于 ' + new Date(updatedAt).toLocaleTimeString('zh-CN', { hour12: false }) + ' · 最近至多 ' + LIMIT + ' 条已保存助手消息；更多历史仍在聊天记录中。' + (state.cacheDisplay ? ' 正文预览来自本机缓存。' : ''));
    if (typeof window.CustomEvent === 'function' && typeof document.dispatchEvent === 'function') document.dispatchEvent(new window.CustomEvent('asteria-chat-notification-summary', { detail: summary() }));
  }
  async function read() {
    const selected = { owner, epoch }; if (!current(selected) || reading) return;
    const request = ++serial, sessionId = state.activeId; reading = true; snapshot = null; error = ''; render();
    try {
      const result = await apiClient.json('GET', '/chat/delivery-center?session_id=' + encodeURIComponent(sessionId));
      if (!current(selected) || request !== serial) return;
      if (result?.schema !== 1 || result.supported !== true || !Array.isArray(result.messages) || !result.server_queue) throw Error('invalid_projection');
      snapshot = result; updatedAt = Date.now();
    } catch (failure) {
      if (!current(selected) || request !== serial) return;
      updatedAt = 0; error = failure?.status === 401 ? '登录已失效，请到连接设置重新登录。' : failure?.status === 403 ? '当前会话没有通知查看权限。' : '通知读取未完成，可到连接与缓存查看状态；原消息没有删除。';
    } finally { if (current(selected) && request === serial) { reading = false; render(); } }
  }
  async function open() {
    if (!ready()) { showNotice('请先连接伙伴，再打开通知中心。'); return; }
    mount(); window.ChatSettingsHub?.close(); hideMoreMenu(); window.ChatDeliveryCenter?.closeActive();
    if (owner !== key()) { invalidate(); owner = key(); filter = 'texas'; onlyPending = false; collapsed = false; get('notification-center-pending').checked = false; }
    if (!dialog.open) dialog.showModal(); render(); await read();
  }
  function closeActive() {
    if (!dialog?.open) return false;
    invalidate(); dialog.close(); get('notification-center-list').replaceChildren(); note(''); return true;
  }
  function scopeChanged() { if (owner && (!ready() || owner !== key())) closeActive(); }
  function summary() {
    const messages = ready() && owner === key() ? savedRows() : [];
    return { available: !!snapshot && !error, window_count: messages.length, pending_count: messages.filter(item => !viewed(item)).length, updated_at: updatedAt, limited_window: true, human_read_proven: false };
  }
  return Object.freeze({ open, refresh: read, closeActive, scopeChanged, summary });
})();
