'use strict';
/* One on-demand view over the original bridge, receipt outbox and caches.
   No timers, background services, receipt writes, queue changes or send retries. */
window.ChatDeliveryCenter = (() => {
  const LIMIT = 32;
  const phaseLabels = { created: '已生成', queued: '已进入原队列', sent: '原发送端已确认',
    client_received: '客户端已收取', system_notification_posted: '已向系统发布通知', user_opened: '通知点击后打开' };
  const stateLabels = { candidate: '待批准', approved: '待入队', queued: '待发送', claimed: '处理端已领取', sending: '发送中',
    retry_wait: '原队列等待', paused: '已暂停', confirmed: '原发送端已确认', failed: '发送失败', unknown: '发送结果未知',
    cancelled: '已取消', expired: '已过期', quarantined: '已隔离' };
  const reasonLabels = { awaiting_approval: '等待原系统批准', awaiting_queue: '等待原系统入队', awaiting_dispatch: '等待原发送端处理',
    worker_claimed: '原处理端已领取', dispatch_in_progress: '原发送端正在处理', original_queue_backoff: '按原队列节奏等待',
    original_queue_paused: '原队列已暂停', original_sender_confirmed: '原发送端已确认', original_sender_failed: '原发送端报告失败',
    dispatch_outcome_unknown: '发送结果未知，请先核对记录', original_queue_cancelled: '原队列已取消', delivery_expired: '已超过发送期限',
    original_queue_quarantined: '原队列已隔离，等待原系统处理',
    authorization_denied: '原发送权限不足', authorization_revoked: '原发送权限已收回', revoked_before_dispatch: '发送前权限已收回',
    adapter_unavailable: '原连接暂不可用', prepare_unavailable: '原消息或媒体暂不可准备', route_unavailable: '原发送位置不可用',
    platform_timeout: '平台等待超时，发送结果未知', ambiguous_receipt: '平台确认不明确，发送结果未知',
    dispatch_cancelled: '发送过程已中断，结果待核对', platform_exception: '平台处理异常，发送结果未知', sdk_confirmed: '原平台已确认',
    adapter_capacity: '原发送端繁忙，等待处理', frequency_gate: '等待原消息节奏限制解除', service_stopping: '原服务正在停止',
    waiting_for_real_scope: '等待原会话授权恢复', image_required: '原发送规则要求图片', attempts_exhausted: '原发送尝试已用尽',
    policy_deferred: '等待原免打扰时段或消息节奏限制解除' };
  const kindLabels = { reply: '聊天回复', proactive: '主动消息', reminder: '提醒' };
  const workspaceLabels = { qq: 'QQ 保持发送', chat_text: '纯文本主动消息发 Chat；图片与语音保留 QQ', chat_all: '文字、图片与语音均发 Chat' };
  let dialog, pane = 'delivery', owner = '', epoch = 0, readSerial = 0, reading = false;
  let snapshot = null, lastGet = null, saving = false;
  const get = id => document.getElementById(id);
  const key = () => JSON.stringify([state.server, state.username, state.activeId]);
  const ready = () => !!(state.authenticated && state.server && state.username && state.activeId);
  const ticket = () => ({ owner, epoch });
  const current = selected => ready() && selected.owner === key() && selected.owner === owner && selected.epoch === epoch && dialog?.open;
  const number = value => Number.isFinite(value) && value >= 0 ? Math.min(Math.floor(value), 100000000000000) : 0;
  const count = value => Math.min(number(value), 1000000);
  const time = value => value ? new Date(number(value) < 100000000000 ? number(value) * 1000 : number(value)).toLocaleString('zh-CN', { hour12: false }) : '尚无记录';
  const size = value => number(value) < 1024 ? number(value) + ' B' : number(value) < 1048576 ? (number(value) / 1024).toFixed(1) + ' KB' : (number(value) / 1048576).toFixed(1) + ' MB';
  const node = (tag, value, className = '') => { const item = document.createElement(tag); item.textContent = value; item.className = className; return item; };
  function action(label, handler, className = 'text-button') {
    const item = node('button', label, className); item.type = 'button'; item.addEventListener('click', handler); return item;
  }
  function note(value) { get('delivery-center-note').textContent = value; }
  function nativeRead(method) {
    try { const bridge = window.AsteriaChat; if (typeof bridge?.[method] !== 'function') return null;
      const value = bridge[method](); return typeof value === 'string' ? JSON.parse(value) : value; }
    catch (_) { return null; }
  }
  function receiptsPending() {
    if (!ready()) return { available: false, messages: 0, reports: 0, opened: false };
    try {
      const raw = localStorage.getItem('asteria-chat.receipts.' + key()) || '{}';
      if (raw.length > 65536) return { available: false, messages: 0, reports: 0, opened: false };
      const data = JSON.parse(raw); if (!data || typeof data !== 'object' || Array.isArray(data)) throw Error();
      let messages = 0, reports = 0;
      for (const [id, value] of Object.entries(data).slice(0, 65)) {
        if (id === '$opened' || !value || typeof value !== 'object') continue;
        const pending = ['client_received', 'system_notification_posted', 'user_opened'].filter(name => value[name] === true).length;
        if (pending) messages++; reports += pending;
      }
      return { available: true, messages, reports, opened: typeof data.$opened === 'string' && !!data.$opened };
    } catch (_) { return { available: false, messages: 0, reports: 0, opened: false }; }
  }
  function localStatus() {
    let cache = { error: true }, history = null;
    try { cache = ready() ? chatCacheStatus() : { error: true }; history = ready() ? window.ChatCache?.history(state.server, state.username, state.activeId) : null; } catch (_) { cache = { error: true }; }
    const attachments = nativeRead('getAttachmentCacheStatus'), notification = nativeRead('getNotificationStatus'), config = nativeRead('getConfig');
    const messages = Array.isArray(state.messages) ? state.messages : [];
    const queuedFiles = state.attachmentQueues?.get(state.activeId) || [];
    return { cache, history, attachments, notification, config, receipts: receiptsPending(),
      unknownSends: messages.filter(row => row.role === 'user' && row.delivery === 'unknown').length,
      pendingSends: messages.filter(row => row.role === 'user' && ['pending', 'unconfirmed'].includes(row.delivery)).length,
      unknownUploads: queuedFiles.filter(row => row.status === 'unknown').length,
      unknownAttachmentSends: queuedFiles.filter(row => row.status === 'send-unknown').length };
  }
  function mount() {
    if (dialog) return;
    dialog = document.createElement('dialog'); dialog.id = 'delivery-center-dialog'; dialog.className = 'settings-dialog delivery-center-dialog';
    dialog.setAttribute('aria-labelledby', 'delivery-center-title');
    const form = node('div', '', 'settings-form'), heading = node('div', '', 'dialog-heading');
    heading.append(node('h2', '消息与连接', 'delivery-center-title'));
    heading.firstChild.id = 'delivery-center-title';
    const close = action('×', () => closeActive(), 'icon-button'); close.setAttribute('aria-label', '关闭消息与连接'); heading.append(close); form.append(heading);
    const tabs = node('div', '', 'delivery-center-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', '消息与连接');
    for (const [name, label] of [['delivery', '消息送达'], ['connection', '连接与缓存']]) {
      const tab = action(label, () => select(name)); tab.id = 'delivery-center-tab-' + name; tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', 'delivery-center-' + name);
      tab.addEventListener('keydown', event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 'delivery' : event.key === 'End' ? 'connection' : name === 'delivery' ? 'connection' : 'delivery'; select(next); get('delivery-center-tab-' + next).focus(); } }); tabs.append(tab);
    }
    form.append(tabs);
    for (const name of ['delivery', 'connection']) {
      const section = node('section', '', 'delivery-center-pane'); section.id = 'delivery-center-' + name;
      section.setAttribute('role', 'tabpanel'); section.setAttribute('aria-labelledby', 'delivery-center-tab-' + name); form.append(section);
    }
    const tools = node('div', '', 'delivery-center-actions');
    const refreshButton = action('重新读取状态', () => refresh()); refreshButton.id = 'delivery-center-refresh';
    const sync = action('同步当前对话', manualSync); sync.id = 'delivery-center-sync';
    const exportButton = action('导出脱敏诊断', exportDiagnostics); exportButton.id = 'delivery-center-export';
    tools.append(refreshButton, sync, exportButton); form.append(tools);
    const status = node('p', '', 'appearance-help'); status.id = 'delivery-center-note'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); form.append(status);
    dialog.append(form); document.body.append(dialog);
    dialog.addEventListener('cancel', event => { event.preventDefault(); closeActive(); });
    dialog.addEventListener('close', () => { owner = ''; snapshot = null; lastGet = null; epoch++; });
  }
  function select(name) {
    pane = name === 'connection' ? 'connection' : 'delivery';
    for (const value of ['delivery', 'connection']) {
      get('delivery-center-' + value).hidden = pane !== value;
      const tab = get('delivery-center-tab-' + value); tab.setAttribute('aria-selected', String(pane === value)); tab.tabIndex = pane === value ? 0 : -1;
    }
    render();
  }
  function controls() {
    if (!dialog) return;
    const busy = state.sending || state.loading || state.attaching || state.appearanceBusy || state.exportBusy || state.creating;
    get('delivery-center-refresh').disabled = !ready() || reading || saving;
    get('delivery-center-sync').disabled = !ready() || busy || reading || saving;
    get('delivery-center-export').disabled = !ready() || busy || reading || saving || !lastGet || typeof window.AsteriaChat?.exportConversation !== 'function';
  }
  function line(box, label, value) { const row = node('div', '', 'delivery-center-line'); row.append(node('span', label), node('span', value)); box.append(row); }
  function block(box, label) { const section = node('section', '', 'delivery-center-card'); section.append(node('h3', label)); box.append(section); return section; }
  function renderDelivery() {
    const box = get('delivery-center-delivery'); box.replaceChildren();
    const local = localStatus(), localBox = block(box, '本机待核对');
    line(localBox, '发送结果未知', count(local.unknownSends) + ' 条');
    line(localBox, '正在提交或尚未确认', count(local.pendingSends) + ' 条');
    line(localBox, '收件确认待同步', local.receipts.available ? local.receipts.messages + ' 条消息 · ' + local.receipts.reports + ' 项确认' : '本机确认信息暂不可读取');
    if (local.receipts.opened) line(localBox, '通知打开目标', '等待同步原消息后确认');
    line(localBox, '附件待核对', local.unknownUploads + ' 个上传 · ' + local.unknownAttachmentSends + ' 个发送');
    localBox.append(node('p', '这些是本机提交和收件确认状态，与服务器发送队列分别计数。同步记录会沿用原有核对流程。', 'appearance-help'));
    const queueBox = block(box, '服务器原有发送队列');
    const queue = snapshot?.server_queue;
    if (!queue || queue.state !== 'available') queueBox.append(node('p', reading ? '正在读取…' : '当前尚不能读取原发送队列；不会将它显示为零条。', 'appearance-help'));
    else {
      const counts = queue.counts || {}, pending = Object.entries(counts).filter(([name]) => ['candidate', 'approved', 'queued', 'claimed', 'sending', 'retry_wait', 'paused'].includes(name)).reduce((sum, [, value]) => sum + count(value), 0);
      line(queueBox, '待处理', pending + ' 条'); line(queueBox, '失败', count(counts.failed) + ' 条'); line(queueBox, '结果未知', count(counts.unknown) + ' 条');
      for (const item of (Array.isArray(queue.items) ? queue.items : []).slice(0, LIMIT)) {
        const row = node('div', '', 'delivery-center-item');
        row.append(node('strong', (kindLabels[item.kind] || '消息') + ' · ' + (item.destination === 'qq' ? 'QQ' : 'Chat') + ' · ' + (stateLabels[item.state] || '待核对')));
        row.append(node('p', reasonLabels[item.reason] || '请在原系统核对这条消息', 'appearance-help'));
        if (item.available_at) row.append(node('small', '可处理时间：' + time(item.available_at)));
        queueBox.append(row);
      }
      queueBox.append(node('p', '仅查看当前授权范围内保留的原队列记录，最多 ' + LIMIT + ' 条' + (queue.limited ? '；还有未展示的记录。' : '。') + '归档记录不计入这里。', 'appearance-help'));
    }
    const saved = block(box, '已保存消息的送达记录');
    const messages = Array.isArray(snapshot?.messages) ? snapshot.messages : [];
    if (!messages.length) saved.append(node('p', reading ? '正在读取已保存消息…' : '当前读取范围内尚无助手消息记录。', 'appearance-help'));
    for (const item of messages.slice(-LIMIT).reverse()) {
      const row = node('article', '', 'delivery-center-item');
      const identity = typeof item.message_id === 'string' ? item.message_id.replace(/[\u0000-\u001f]/g, '').slice(0, 160) : '';
      row.append(node('strong', (kindLabels[item.kind] || '消息') + ' · 服务器已保存'));
      row.append(node('small', '消息编号：' + identity, 'delivery-center-message-id'));
      for (const [phase, label] of Object.entries(phaseLabels)) {
        const stage = item.stages?.[phase];
        line(row, label, stage?.observed === true ? (stage.at ? time(stage.at) : '有记录') : '尚无独立记录');
      }
      saved.append(row);
    }
    saved.append(node('p', '服务器保存、原队列发送确认、客户端收取、系统通知发布、通知点击后打开分别记录。客户端报告不证明用户已读，也不保证系统显示横幅。普通聊天回复可能没有独立队列阶段。', 'appearance-help'));
  }
  function renderConnection() {
    const box = get('delivery-center-connection'); box.replaceChildren(); const local = localStatus();
    const connection = block(box, '本次 TLS 查询');
    line(connection, '查询结果', reading ? '正在查询 TLS…' : !lastGet ? '尚未查询' : lastGet.ok ? 'TLS 已返回有效结果' : 'TLS 查询未完成或被拒绝');
    line(connection, '查询时间', time(lastGet?.at));
    if (lastGet && !lastGet.ok) line(connection, '错误类型', requestFailure(lastGet.status));
    line(connection, '当前记录来源', state.cacheDisplay ? '本机已保存副本' : '当前界面记录');
    line(connection, '当前对话缓存更新时间', time(local.history?.updatedAt || state.cacheDisplay?.savedAt));
    connection.append(node('p', '联网图标与登录状态不能证明本次 TLS 请求成功。这里显示真实查询结果；手动同步沿用当前对话的原有同步入口。', 'appearance-help'));
    const cache = block(box, '本机缓存');
    line(cache, '当前账户聊天缓存', count(local.cache.sessions) + ' 段 · ' + count(local.cache.messages) + ' 条 · 约 ' + size(local.cache.bytes));
    if (local.cache.error) line(cache, '聊天缓存读取', '暂不可读取');
    const attachments = local.attachments;
    line(cache, '附件下载副本', attachments?.ok === true ? count(attachments.count) + ' 个 · ' + size(attachments.bytes) : '当前客户端暂不能读取');
    if (attachments?.ok === true) line(cache, '附件保留范围', '最多 ' + count(attachments.max_count) + ' 个 · ' + size(attachments.max_bytes) + ' · ' + count(attachments.ttl_hours) + ' 小时');
    const actions = node('div', '', 'delivery-center-actions');
    const historyClear = action('清理聊天缓存', () => clearCache('history')), attachmentClear = action('清理附件副本', () => clearCache('attachment'));
    const blocked = !ready() || state.sending || state.attaching || saving || state.exportBusy;
    historyClear.disabled = blocked || !window.ChatCache; attachmentClear.disabled = blocked || typeof window.AsteriaChat?.clearRecoverableAttachmentCache !== 'function';
    actions.append(historyClear, attachmentClear); cache.append(actions);
    cache.append(node('p', '清理沿用原缓存工具。聊天草稿、服务器消息、原文件和收件确认保留。', 'appearance-help'));
    const permission = block(box, '应用与权限');
    const yn = value => value === true ? '已允许' : value === false ? '未允许' : '暂不可读取';
    line(permission, '客户端版本', safeVersion(local.config?.version) || '暂不可读取');
    line(permission, '系统通知权限', yn(local.notification?.runtime_permission_granted));
    line(permission, '应用通知开关', yn(local.notification?.app_notifications_enabled));
    line(permission, '回复通知渠道', local.notification?.reply_channel?.exists === false ? '尚未建立' : local.notification?.reply_channel?.blocked === true ? '已关闭' : local.notification?.reply_channel?.exists === true ? '已建立' : '暂不可读取');
    if (snapshot?.workspace?.values) line(permission, '主动消息位置', workspaceLabels[snapshot.workspace.values.proactive_destination] || '暂不可读取');
    permission.append(node('p', '导出仅含计数、阶段汇总、权限与版本、查询结果和时间；不含账户、地址、消息正文、消息编号或服务器内部编号。保存位置由系统窗口选择。', 'appearance-help'));
  }
  function render() { if (!dialog?.open || !ready() || owner !== key()) return; renderDelivery(); renderConnection(); controls(); }
  function requestFailure(status) {
    return status === 401 ? '登录已失效' : status === 403 ? '当前范围无权访问' : status === 404 ? '服务器尚未提供此接口或会话不存在' : status === 0 ? '网络或等待结果尚未确认' : status >= 500 ? '服务器暂不可用' : '响应格式或请求暂不兼容';
  }
  async function refresh() {
    const selected = ticket(); if (!current(selected) || reading || saving) return;
    const serial = ++readSerial; reading = true; snapshot = null; note('正在读取当前会话状态…'); render();
    try {
      const result = await apiClient.json('GET', '/chat/delivery-center?session_id=' + encodeURIComponent(state.activeId));
      if (!current(selected) || serial !== readSerial) return;
      if (result?.schema !== 1 || result.supported !== true || !Array.isArray(result.messages) || !result.server_queue) throw Object.assign(Error(), { status: -1 });
      snapshot = result; lastGet = { ok: true, at: Date.now(), status: 200 }; note('已读取当前会话的实际记录。');
    } catch (error) {
      if (!current(selected) || serial !== readSerial) return;
      lastGet = { ok: false, at: Date.now(), status: Number.isInteger(error?.status) && error.status >= 0 && error.status <= 599 ? error.status : -1 };
      note('状态读取未完成：' + requestFailure(lastGet.status) + '。可同步当前对话后再核对。');
    } finally { if (current(selected) && serial === readSerial) { reading = false; render(); } }
  }
  async function manualSync() {
    const selected = ticket(); if (!current(selected) || state.sending || state.loading || state.attaching || state.appearanceBusy || state.exportBusy || reading || saving) return;
    note('正在同步当前对话…');
    const ok = await refreshCurrent();
    if (!current(selected)) return;
    if (ok) await refresh(); else { note('本次对话同步尚未完成，请稍后核对。'); render(); }
  }
  function clearCache(kind) {
    if (!ready() || owner !== key() || state.sending || state.attaching || state.exportBusy || saving) return;
    window.ChatCacheSettings?.refresh();
    const original = get(kind === 'history' ? 'chat-cache-history-clear' : 'chat-cache-attachment-clear');
    if (!original || original.disabled) { note('当前暂不能清理该缓存。'); return; }
    original.click(); note(get('chat-cache-note')?.textContent || '已调用原缓存清理工具。'); render();
  }
  const safeVersion = value => typeof value === 'string' && /^[0-9]{1,3}(?:\.[0-9]{1,4}){1,3}(?:-[A-Za-z0-9.]{1,24})?$/.test(value) ? value : null;
  function diagnosticSnapshot() {
    const local = localStatus(), queue = snapshot?.server_queue;
    const counts = {};
    for (const name of Object.keys(stateLabels)) counts[name] = count(queue?.counts?.[name]);
    const phases = {};
    for (const name of Object.keys(phaseLabels)) phases[name] = (snapshot?.messages || []).slice(-LIMIT).filter(item => item.stages?.[name]?.observed === true).length;
    const bool = value => typeof value === 'boolean' ? value : null;
    return { schema: 1, exported_at: Date.now(), client_version: safeVersion(local.config?.version),
      tls_get: lastGet ? { ok: lastGet.ok === true, status: lastGet.status, at: number(lastGet.at) } : null,
      current_history_cache_updated_at: number(local.history?.updatedAt || state.cacheDisplay?.savedAt),
      display_uses_cache: !!state.cacheDisplay,
      local_pending: { unknown_sends: count(local.unknownSends), pending_sends: count(local.pendingSends), unknown_uploads: count(local.unknownUploads), unknown_attachment_sends: count(local.unknownAttachmentSends),
        receipts_available: local.receipts.available, receipt_messages: count(local.receipts.messages), receipt_reports: count(local.receipts.reports), opened_target_pending: local.receipts.opened },
      server_queue: { available: queue?.state === 'available', counts, limited: bool(queue?.limited), retained_live_rows_only: true },
      saved_message_window: { count: Math.min(count(snapshot?.messages?.length), LIMIT), stage_observations: phases, client_claims_only: true, user_read_proven: false },
      cache: { sessions: count(local.cache.sessions), messages: count(local.cache.messages), bytes: number(local.cache.bytes), available: !local.cache.error },
      attachments: { available: local.attachments?.ok === true, count: count(local.attachments?.count), bytes: number(local.attachments?.bytes), max_count: count(local.attachments?.max_count), max_bytes: number(local.attachments?.max_bytes), ttl_hours: count(local.attachments?.ttl_hours) },
      permissions: { notification_runtime: bool(local.notification?.runtime_permission_granted), app_notifications: bool(local.notification?.app_notifications_enabled), reply_channel_blocked: bool(local.notification?.reply_channel?.blocked) },
      server_push: false };
  }
  async function exportDiagnostics() {
    const selected = ticket();
    if (!current(selected) || !lastGet || reading || saving || state.exportBusy || state.sending || state.loading || state.attaching || state.appearanceBusy || state.creating || state.exportEditing || typeof window.AsteriaChat?.exportConversation !== 'function') return;
    const report = diagnosticSnapshot();
    const markdown = '# Asteria Chat 脱敏诊断\n\n仅供排查当前状态；客户端报告不证明已读。\n\n```json\n' + JSON.stringify(report, null, 2) + '\n```\n';
    const bytes = exportUtf8Bytes(markdown);
    if (bytes > 16384) { note('诊断内容超出上限，未导出。'); return; }
    const filename = 'AsteriaChat-diagnostics-' + new Date().toISOString().replace(/[-:]/g, '').slice(0, 15).replace('T', '-') + '.md';
    saving = true; state.exportBusy = true; controls(); renderChrome(); note('请选择系统保存位置；取消后可重新导出。');
    try {
      const data = responseData(await nativeAsync('exportConversation', [filename, markdown], 300000));
      if (!current(selected)) return;
      if (data?.cancelled === true && data.exported !== true) note('已取消诊断保存。');
      else if (data?.exported === true && data.filename === filename && data.bytes === bytes) note('脱敏诊断已保存。');
      else note('保存结果尚未确认，请先检查所选文件。');
    } catch (_) { if (current(selected)) note('诊断保存未完成或结果待确认，请先检查所选文件；不会自动重复保存。'); }
    finally { saving = false; state.exportBusy = false; renderChrome(); if (current(selected)) render(); }
  }
  async function open(name) {
    if (!ready()) { showNotice('请先登录并打开一段对话。'); return; }
    mount(); hideMoreMenu(); window.ChatSettingsHub?.close();
    if (owner !== key()) { snapshot = null; lastGet = null; readSerial++; reading = false; epoch++; }
    owner = key(); if (!dialog.open) dialog.showModal(); select(name); await refresh();
  }
  function closeActive(force = false) {
    if (!dialog?.open) return false;
    if (saving && !force) { note('请先在系统保存窗口完成或取消。'); return true; }
    epoch++; readSerial++; reading = false; owner = ''; snapshot = null; lastGet = null;
    dialog.close(); for (const name of ['delivery', 'connection']) get('delivery-center-' + name).replaceChildren(); note(''); return true;
  }
  function scopeChanged() { if (owner && (!ready() || owner !== key())) closeActive(true); }
  return Object.freeze({ openDelivery: () => open('delivery'), openConnection: () => open('connection'), refresh, scopeChanged, closeActive });
})();
