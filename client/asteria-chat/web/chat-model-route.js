'use strict';

/* The server owns session model selection. This panel sends no chat requests. */
window.ChatModelRoute = (() => {
  let dialog, content, status, primary, fallback, saveButton, resetButton, refreshButton, quick;
  let owner = '', session = '', epoch = 0, busy = false, saved = null, quickScope = '';
  const scope = () => JSON.stringify([state.server, state.username, state.activeId]);
  const node = (tag, text, className = '') => { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; item.className = className; return item; };
  const action = (label, fn, className = 'text-button') => { const item = node('button', label, className); item.type = 'button'; item.addEventListener('click', fn); return item; };
  const ticket = () => ({ owner, session, epoch });
  const current = t => dialog?.open && state.authenticated && owner === scope() && t.owner === owner && t.epoch === epoch;
  const sourceLabels = { session_override: '本会话覆盖', session_fallback: '本会话可用备选', task_preferred: '任务首选', task_fallback: '任务备选', sdk_session_default: 'AstrBot 会话 / 全局默认', unavailable: '暂无可用模型' };
  function controls() { saveButton.disabled = resetButton.disabled = busy || !saved; refreshButton.disabled = busy; primary.disabled = fallback.disabled = busy || !saved; }
  function close() { epoch++; owner = ''; saved = null; busy = false; if (dialog?.open) dialog.close(); }
  function setup() {
    if (dialog) return;
    dialog = node('dialog'); dialog.id = 'model-route-dialog'; dialog.className = 'settings-dialog model-route-dialog'; dialog.setAttribute('aria-labelledby', 'model-route-title');
    const form = node('div', undefined, 'settings-form'), heading = node('div', undefined, 'dialog-heading'), title = node('h2', '本会话模型'); title.id = 'model-route-title';
    heading.append(title, action('关闭', close)); form.append(heading, node('p', '只调整当前对话的后续请求，不修改其他对话或全局模型配置。', 'appearance-help'));
    content = node('section', undefined, 'model-route-effective'); content.setAttribute('aria-live', 'polite'); form.append(content);
    const select = label => { const row = node('label'), field = node('select'); row.append(node('span', label), field); form.append(row); return field; };
    primary = select('会话首选'); primary.id = 'model-route-primary'; fallback = select('首选移除时的备选'); fallback.id = 'model-route-fallback';
    primary.addEventListener('change', () => { if (!primary.value) fallback.value = ''; });
    form.append(node('p', '列表来自服务器已注册的文本模型；存在于列表不代表提供商当前网络调用一定成功。运行中的重试与图片模型切换仍沿用 AstrBot 原规则。', 'appearance-help'));
    const buttons = node('div', undefined, 'model-route-actions'); saveButton = action('保存本会话选择', () => write(false), 'primary-button'); resetButton = action('恢复继承', () => write(true)); refreshButton = action('重新读取', read); buttons.append(saveButton, resetButton, refreshButton); form.append(buttons);
    status = node('p', '', 'model-route-note'); status.setAttribute('role', 'status'); form.append(status); dialog.append(form);
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); }); document.body.append(dialog);
  }
  function options(select, rows, selected, blankLabel) {
    select.replaceChildren(); const blank = node('option', blankLabel); blank.value = ''; select.append(blank);
    for (const row of rows) { const option = node('option', row.model ? row.model + ' · ' + row.id : row.id); option.value = row.id; select.append(option); }
    if (selected && !rows.some(row => row.id === selected)) { const missing = node('option', selected + '（当前不可用）'); missing.value = selected; select.append(missing); }
    select.value = selected || '';
  }
  function render() {
    content.replaceChildren(); if (!saved) return;
    const e = saved.effective;
    content.append(node('strong', e.model || e.provider_id || '暂无可用模型'), node('p', '当前解析来源：' + (sourceLabels[e.source] || '未确认')));
    if (e.model && e.provider_id) content.append(node('small', e.provider_id));
    if (e.fallback) content.append(node('p', '首选当前不可用，下一次请求将使用上方可用选择。', 'model-route-warning'));
    content.append(node('small', '此处是当前配置的实际解析，不是已完成生成的模型回执。'));
    options(primary, saved.providers, saved.override.model_provider_id, '继承任务 / 系统配置'); options(fallback, saved.providers, saved.override.model_fallback_provider_id, '沿用任务 / 系统回退');
    if (quick) { quickScope = scope(); quick.textContent = e.model ? String(e.model).slice(0, 20) : '模型'; quick.title = '本会话模型：' + (e.model || e.provider_id || '未确认'); }
  }
  async function read() {
    const t = ticket(); if (!current(t) || busy) return; busy = true; controls(); status.textContent = '正在读取本会话实际路由…';
    try { const value = await apiClient.json('GET', '/chat/model-route?session_id=' + encodeURIComponent(t.session)); if (!current(t)) return; saved = value; render(); status.textContent = '已从服务器读取。保存后的选择用于后续请求，不会重新生成已有消息。'; }
    catch (error) { if (current(t)) { saved = null; status.textContent = errorText(error); } }
    finally { if (current(t)) { busy = false; controls(); } }
  }
  async function write(reset) {
    const t = ticket(); if (!current(t) || busy || !saved) return;
    const choices = reset ? { model_provider_id: '', model_fallback_provider_id: '' } : { model_provider_id: primary.value, model_fallback_provider_id: fallback.value };
    if (!reset && choices.model_fallback_provider_id && (!choices.model_provider_id || choices.model_provider_id === choices.model_fallback_provider_id)) { status.textContent = '请选择不同的首选与备选，或将备选恢复继承。'; return; }
    const revision = saved.revision; busy = true; controls(); status.textContent = '正在保存当前会话选择…';
    try { const value = await apiClient.json('POST', '/chat/model-route', { session_id: t.session, expected_revision: revision, changes: choices }); if (!current(t)) return; saved = value; render(); status.textContent = reset ? '本会话已恢复继承，其他会话和全局设置保持原值。' : '已保存到当前会话，后续请求由服务器使用此选择。'; }
    catch (error) { if (current(t)) { saved = null; status.textContent = errorText(error) + ' 请重新读取核对实际保存结果；不会自动重试写入。'; } }
    finally { if (current(t)) { busy = false; controls(); } }
  }
  function open() {
    if (!state.authenticated || !state.activeId) { showNotice('请先打开自己的聊天会话。'); return; }
    setup(); close(); owner = scope(); session = state.activeId; epoch++; dialog.showModal(); controls(); void read();
  }
  document.addEventListener('DOMContentLoaded', () => {
    const row = document.querySelector('.conversation-title-row'); if (!row) return;
    quick = action('模型', open, 'model-route-shortcut'); quick.id = 'chat-model-route-open'; quick.setAttribute('aria-label', '查看和切换本会话模型'); row.append(quick);
  }, { once: true });
  return { open, closeActive: () => { if (!dialog?.open) return false; close(); return true; }, scopeChanged: () => { if (owner && (!state.authenticated || owner !== scope())) close(); const next = state.authenticated ? scope() : ''; if (quick && next !== quickScope) { quickScope = next; quick.textContent = '模型'; quick.title = '查看和切换本会话模型'; } } };
})();
