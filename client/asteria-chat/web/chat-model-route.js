'use strict';

/* The server owns session model selection. This panel sends no chat requests. */
window.ChatModelRoute = (() => {
  let dialog, content, status, primary, fallback, draftNote, saveButton, resetButton, refreshButton, quick;
  let owner = '', session = '', epoch = 0, busy = false, saved = null, draft = null, quickScope = '';
  const pendingWrites = new Map();
  const scope = () => JSON.stringify([state.server, state.username, state.activeId]);
  const node = (tag, text, className = '') => { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; item.className = className; return item; };
  const action = (label, fn, className = 'text-button') => { const item = node('button', label, className); item.type = 'button'; item.addEventListener('click', fn); return item; };
  const ticket = () => ({ owner, session, epoch });
  const current = t => dialog?.open && state.authenticated && owner === scope() && t.owner === owner && t.session === session && t.session === state.activeId && t.epoch === epoch;
  const sourceLabels = { session_override: '本会话首选', session_fallback: '本会话备选', task_preferred: '任务首选', task_fallback: '任务备选', sdk_session_default: '会话 / 系统默认', unavailable: '暂无可用模型' };
  const choices = () => ({ model_provider_id: primary.value, model_fallback_provider_id: fallback.value });
  const same = (a, b) => a && b && a.model_provider_id === b.model_provider_id && a.model_fallback_provider_id === b.model_fallback_provider_id;
  const dirty = () => !!draft && (!saved || !same(draft, saved.override));
  const label = id => { const row = saved?.providers.find(value => value.id === id); return row ? (row.model ? row.model + ' · ' + row.id : row.id) : id + '（当前不可用）'; };
  function invalid(value) {
    if (!saved || !value) return '';
    if ([value.model_provider_id, value.model_fallback_provider_id].some(id => id && !saved.providers.some(row => row.id === id))) return '所选模型当前不在服务器列表中，请重新选择或恢复继承。';
    if (value.model_fallback_provider_id && (!value.model_provider_id || value.model_provider_id === value.model_fallback_provider_id)) return '请选择不同的首选与备选，或将备选恢复继承。';
    return '';
  }
  function controls() {
    saveButton.disabled = busy || !saved || !dirty() || !!invalid(draft);
    resetButton.disabled = busy || !saved || ![saved.override, draft].some(value => value && (value.model_provider_id || value.model_fallback_provider_id));
    refreshButton.disabled = busy;
    primary.disabled = busy || !saved; fallback.disabled = busy || !saved || !primary.value;
  }
  function shortcut(text, title) { if (quick) { quickScope = scope(); quick.textContent = text; quick.title = title; } }
  function close() {
    if (busy) shortcut('模型', '查看和切换本会话模型');
    epoch++; owner = ''; session = ''; saved = draft = null; busy = false;
    if (dialog) { content.replaceChildren(); primary.replaceChildren(); fallback.replaceChildren(); draftNote.textContent = ''; status.textContent = ''; if (dialog.open) dialog.close(); }
  }
  function setup() {
    if (dialog) return;
    dialog = node('dialog'); dialog.id = 'model-route-dialog'; dialog.className = 'settings-dialog model-route-dialog'; dialog.setAttribute('aria-labelledby', 'model-route-title');
    const form = node('div', undefined, 'settings-form'), heading = node('div', undefined, 'dialog-heading'), title = node('h2', '本会话模型'); title.id = 'model-route-title';
    heading.append(title, action('关闭', close)); form.append(heading, node('p', '本次修改用于后续发送；正在生成的回复不受影响。', 'appearance-help'));
    content = node('section', undefined, 'model-route-effective'); content.id = 'model-route-server'; content.setAttribute('aria-live', 'polite');
    form.append(node('h3', '当前编辑', 'model-route-edit-title'));
    const select = text => { const row = node('label'), field = node('select'); row.append(node('span', text), field); form.append(row); return field; };
    primary = select('会话首选'); primary.id = 'model-route-primary'; fallback = select('本会话失败备用'); fallback.id = 'model-route-fallback';
    const changed = () => { if (!primary.value) fallback.value = ''; draft = choices(); paintDraft(); controls(); };
    primary.addEventListener('change', changed); fallback.addEventListener('change', changed);
    draftNote = node('p', '', 'model-route-draft'); draftNote.id = 'model-route-draft'; draftNote.setAttribute('aria-live', 'polite'); form.append(draftNote);
    form.append(node('p', '选中后请点保存。列表来自服务器已注册的文本模型；能选中不代表调用成功。请求失败或图片能力引发的模型回退由服务器处理。', 'appearance-help'));
    const buttons = node('div', undefined, 'model-route-actions'); saveButton = action('保存本会话选择', () => write(false), 'primary-button'); resetButton = action('恢复继承', () => write(true)); refreshButton = action('重新读取', read); buttons.append(saveButton, resetButton, refreshButton); form.append(buttons);
    status = node('p', '', 'model-route-note'); status.id = 'model-route-status'; status.setAttribute('role', 'status'); form.append(status, content); dialog.append(form);
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); }); document.body.append(dialog);
  }
  function options(select, rows, selected, blankLabel, confirmed = true) {
    select.replaceChildren(); const blank = node('option', blankLabel); blank.value = ''; select.append(blank);
    for (const row of rows) { const option = node('option', row.model ? row.model + ' · ' + row.id : row.id); option.value = row.id; select.append(option); }
    if (selected && !rows.some(row => row.id === selected)) { const missing = node('option', selected + (confirmed ? '（当前不可用，请重选）' : '（待核对）')); missing.value = selected; missing.disabled = true; select.append(missing); }
    select.value = selected || '';
  }
  function paintDraft() {
    const warning = invalid(draft);
    draftNote.className = 'model-route-draft' + (warning ? ' model-route-warning' : '');
    draftNote.textContent = warning || (!saved ? (draft ? '当前编辑尚未确认保存，请先重新读取。' : '读取服务器设置后才能编辑。')
      : dirty() ? '有未保存的选择。重新读取会保留编辑；关闭或返回会放弃未保存的选择。' : '当前选择与已保存设置一致。');
  }
  function card(title) { const item = node('div', undefined, 'model-route-card'); item.append(node('h3', title)); content.append(item); return item; }
  function render() {
    content.replaceChildren();
    const rows = saved?.providers || [];
    options(primary, rows, draft?.model_provider_id, '继承任务 / 系统配置', !!saved); options(fallback, rows, draft?.model_fallback_provider_id, '沿用任务 / 系统回退', !!saved);
    if (!saved) {
      card('已保存设置待核对').append(node('p', '尚未读取到当前会话的设置，请重新读取。'));
      card('最近返回').append(node('p', '尚未观察到可核验的模型响应。'));
      paintDraft(); return;
    }
    const stored = card('已保存的会话选择');
    stored.append(node('p', '首选：' + (saved.override.model_provider_id ? label(saved.override.model_provider_id) : '继承任务 / 系统配置')),
      node('p', '失败备用：' + (saved.override.model_fallback_provider_id ? label(saved.override.model_fallback_provider_id) : '沿用任务 / 系统回退')));
    const e = saved.effective, resolved = card('下次请求');
    resolved.append(node('strong', e.available ? (e.model || e.provider_id) : '暂无可用模型'), node('p', '来源：' + (sourceLabels[e.source] || '未确认')));
    if (e.model && e.provider_id) resolved.append(node('small', e.provider_id));
    if (e.fallback) resolved.append(node('p', '当前配置采用备选路径，来源见上方。', 'model-route-warning'));
    resolved.append(node('small', '这是请求发出前的配置解析；实际调用仍可能回退。'));
    const runtime = saved.runtime || {}, backups = card('失败备用');
    if (Array.isArray(runtime.network_fallback_provider_ids) && runtime.network_fallback_provider_ids.every(id => typeof id === 'string' && id)) {
      const identities = [...new Set(runtime.network_fallback_provider_ids)];
      backups.append(node('p', identities.length ? identities.map(label).join(' → ') : '未设置失败备用'));
      const sources = { session: '本会话设置', task: '任务设置', astrbot: '系统设置' };
      backups.append(node('small', '来源：' + (sources[runtime.network_fallback_source] || '服务器未说明') + '；仅表示失败时的尝试顺序。'));
    } else backups.append(node('p', '服务器尚未提供失败备用信息。'));
    const actual = card('最近返回'), last = runtime.last_call;
    if (runtime.observed_outcome === true && last?.outcome === 'response_received' && last.source === 'sdk_response'
      && typeof last.provider_id === 'string' && last.provider_id && typeof last.model === 'string' && last.model) {
      actual.append(node('strong', last.model), node('p', last.provider_id));
      const when = typeof last.observed_at === 'number' && Number.isFinite(last.observed_at) ? new Date(last.observed_at * 1000)
        : typeof last.observed_at === 'string' && last.observed_at ? new Date(last.observed_at) : null;
      if (when && Number.isFinite(when.getTime())) actual.append(node('small', '观察时间：' + when.toLocaleString('zh-CN', { hour12: false })));
      actual.append(node('small', '服务器已收到该模型响应；这不代表回复已保存或送达本机。'));
    } else actual.append(node('p', '尚未观察到可核验的模型响应。'));
    const resolvedLabel = e.model && e.provider_id ? e.model + ' · ' + e.provider_id : e.provider_id;
    shortcut(e.available ? '下次 · ' + resolvedLabel : '模型 · 不可用', '下次请求的配置解析：' + (e.available ? resolvedLabel : '暂无可用模型') + '；最近实际返回请查看面板。');
    paintDraft();
  }
  function snapshot(value, t) {
    if (!value || value.session_id !== t.session || !Number.isInteger(value.revision) || value.revision < 0 || !Array.isArray(value.providers)
      || value.providers.some(row => !row || typeof row.id !== 'string' || !row.id || (row.model != null && typeof row.model !== 'string'))
      || !value.override || ['model_provider_id', 'model_fallback_provider_id'].some(key => typeof value.override[key] !== 'string')
      || !value.effective || typeof value.effective.available !== 'boolean' || (value.effective.model != null && typeof value.effective.model !== 'string')
      || (value.effective.available && !(typeof value.effective.provider_id === 'string' && value.effective.provider_id))) throw new Error('模型设置返回不完整或会话不匹配，请重新读取。');
    return value;
  }
  async function read() {
    const t = ticket(); if (!current(t) || busy) return;
    const editing = dirty() ? { ...draft } : null;
    busy = true; controls(); status.textContent = '正在读取本会话模型设置…'; shortcut('模型 · 读取中', '正在核对当前会话的已保存配置');
    try {
      const pending = pendingWrites.get(t.owner);
      if (pending) { status.textContent = '正在等待先前保存结束，再读取服务器设置…'; try { await pending; } catch (_) {} if (!current(t)) return; }
      const value = await apiClient.json('GET', '/chat/model-route?session_id=' + encodeURIComponent(t.session)); if (!current(t)) return;
      saved = snapshot(value, t); draft = editing || { ...saved.override }; render();
      status.textContent = dirty() ? '已读取服务器设置，未保存的选择已保留；保存前请核对。' : '已从服务器读取。此处配置解析不代表已成功生成回复。';
    } catch (error) { if (current(t)) { saved = null; draft = editing; render(); shortcut('模型 · 待核对', '未能确认本会话模型设置，请重新读取'); status.textContent = errorText(error); } }
    finally { if (current(t)) { busy = false; controls(); } }
  }
  async function write(reset) {
    const t = ticket(); if (!current(t) || busy || !saved) return;
    draft = reset ? { model_provider_id: '', model_fallback_provider_id: '' } : choices();
    const warning = invalid(draft); if (warning) { paintDraft(); controls(); status.textContent = warning; return; }
    if (same(draft, saved.override)) { render(); controls(); status.textContent = '当前选择已保存，无需重复写入。'; return; }
    const revision = saved.revision, submitted = { ...draft }; let request;
    busy = true; controls(); status.textContent = '正在保存当前会话选择…';
    try {
      request = apiClient.json('POST', '/chat/model-route', { session_id: t.session, expected_revision: revision, changes: submitted }); pendingWrites.set(t.owner, request);
      const value = await request; if (!current(t)) return;
      const confirmed = snapshot(value, t);
      if (confirmed.revision <= revision || !same(confirmed.override, submitted)) throw new Error('服务器返回未确认本次选择，请重新读取。');
      saved = confirmed; draft = { ...saved.override }; render();
      status.textContent = reset ? '本会话已恢复继承，后续请求沿用任务 / 系统配置。' : '已保存到当前会话。后续请求将重新解析配置；请以模型回执核对实际调用。';
    } catch (error) { if (current(t)) { saved = null; draft = submitted; render(); shortcut('模型 · 待核对', '保存结果尚未确认，请重新读取'); status.textContent = errorText(error) + ' 请重新读取核对实际保存结果；不会自动重试写入。'; } }
    finally { if (request && pendingWrites.get(t.owner) === request) pendingWrites.delete(t.owner); if (current(t)) { busy = false; controls(); } }
  }
  function open() {
    if (!state.authenticated || !state.activeId) { showNotice('请先打开自己的聊天会话。'); return; }
    if (dialog?.open && owner === scope()) return;
    setup(); close(); owner = scope(); session = state.activeId; epoch++; dialog.showModal(); render(); controls(); void read();
  }
  document.addEventListener('DOMContentLoaded', () => {
    const row = document.querySelector('.conversation-title-row'); if (!row) return;
    quick = action('模型', open, 'model-route-shortcut'); quick.id = 'chat-model-route-open'; quick.setAttribute('aria-label', '查看和切换本会话模型'); row.append(quick);
  }, { once: true });
  return { open, closeActive: () => { if (!dialog?.open) return false; close(); return true; }, scopeChanged: () => { if (owner && (!state.authenticated || owner !== scope())) close(); const next = state.authenticated ? scope() : ''; if (quick && next !== quickScope) { quickScope = next; quick.textContent = '模型'; quick.title = '查看和切换本会话模型'; } } };
})();
