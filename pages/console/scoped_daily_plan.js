/* New explicitly scoped role plans; no legacy plan import or proactive send. */
(function (global) {
  'use strict';
  const root = document.getElementById('scoped-daily-plan-mount');
  if (!root) return;
  const FIELDS = ['platform', 'bot_id', 'user_id', 'character_id', 'session_id'];
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const progressLabels = {not_started:'尚未完成',pending:'等待推进',waiting_for_scope:'等待真实会话授权',partial:'部分目标待恢复',applied:'已核对推进结果'};
  let scope = null, selected = null, records = [], goalOptions = [], metadata = null, busy = false, serial = 0;
  const pending = new Map();
  const key = value => JSON.stringify(FIELDS.map(k => value && value[k]));
  const same = value => key(value) === key(scope) && key(value) === key(getScope());
  const getScope = () => typeof state === 'object' && state.scope && FIELDS.every(k=>typeof state.scope[k]==='string'&&state.scope[k]) ? Object.fromEntries(FIELDS.map(k => [k, state.scope[k]])) : null;
  function requestId() {
    const uuid = global.TLSBrowserCompat && typeof global.TLSBrowserCompat.uuid === 'function' ? () => global.TLSBrowserCompat.uuid() : global.crypto && global.crypto.randomUUID && (() => global.crypto.randomUUID());
    if (!uuid) throw Error('当前页面无法建立稳定请求ID，请刷新后操作。');
    return 'plan-ui-' + uuid();
  }
  function offset(zone) {
    if (zone === 'UTC' || zone === 'UTC+00:00') return 0;
    const m = /^UTC([+-])(\d{2}):(\d{2})$/.exec(zone || '');
    return m ? (m[1] === '+' ? 1 : -1) * (+m[2] * 60 + +m[3]) : null;
  }
  function roleTime(at, zone) {
    const minutes = offset(zone);
    return minutes === null ? new Date(at * 1000).toLocaleString() + '（浏览器显示）' : new Date(at * 1000 + minutes * 60000).toISOString().slice(0, 16).replace('T', ' ') + ' ' + zone;
  }
  root.innerHTML = `<section class="panel scoped-plan"><div class="panel-head"><h2>目标专用日计划</h2><button data-plan-refresh type="button">刷新与核对</button></div><p class="hint">只管理新建、明确归属的虚构角色计划。旧PC全局日计划保留。提出计划不代表已经完成；这里不自动发消息、不领取分享。</p><p data-plan-status class="hint" role="status" aria-live="polite"></p><p data-plan-zone class="hint"></p><div class="scoped-plan-toolbar"><label>角色日期<input data-plan-day type="date" required></label><button data-plan-generate type="button">按已有目标整理计划</button><button data-plan-new type="button">新建空白计划</button><label class="scoped-plan-check"><input data-plan-archives type="checkbox">显示归档</label></div><div class="scoped-plan-columns"><div data-plan-list></div><section data-plan-detail><p class="empty">选择计划查看活动与进度。</p></section></div></section><section class="panel scoped-plan" data-plan-editor hidden><div class="panel-head"><h2 data-plan-editor-title>新建计划</h2><button data-plan-close type="button">取消编辑</button></div><form data-plan-form><label>计划名称<input data-plan-title maxlength="80" required></label><div data-plan-items></div><div class="actions"><button data-plan-add type="button">添加活动</button><button data-plan-save type="submit" class="primary">保存计划</button></div><p class="hint">新活动须安排在所选角色日期的未来时间；活动完成与目标推进会分开记录。</p></form></section>`;
  const $ = name => root.querySelector('[data-plan-' + name + ']');
  function notice(text, error) { $('status').textContent = text; $('status').classList.toggle('scoped-plan-error', !!error); }
  function controls() {
    const blocked = busy || !scope || pending.has(key(scope));
    for (const name of ['generate', 'new', 'add', 'save']) $(name).disabled = blocked;
    $('refresh').disabled = busy; $('archives').disabled = busy; $('close').disabled = busy || pending.has(key(scope)); $('day').disabled = busy || !!selected && !$('editor').hidden;
  }
  async function call(method, suffix, data, target = scope) {
    if (!target || typeof api !== 'function') throw Error('请先选择完整用户、角色和会话。');
    const result = await api(method, 'page/scoped-daily-plan/' + suffix, data);
    const value = result && result.ok === true ? result : result && result.data;
    if (!value || value.ok !== true || value.backend !== 'native_scoped_daily_plan' || key(value.scope) !== key(target)) throw Error('计划回读的范围或格式不匹配。');
    return value;
  }
  function drawList() {
    const target = $('list'); target.replaceChildren();
    for (const record of records) {
      const b = node('button', undefined, 'scoped-plan-card'); b.type = 'button'; b.dataset.selected = String(selected && selected.id === record.id);
      b.append(node('strong', record.title), node('small', record.date + ' · ' + record.items.filter(x => x.status === 'completed').length + '/' + record.items.length + ' 项完成' + (record.archived ? ' · 已归档' : record.status === 'cancelled' ? ' · 已取消' : '')));
      b.addEventListener('click', () => detail(record.id)); target.append(b);
    }
    if (!records.length) target.append(node('p', scope ? '当前日期没有计划。可从现有目标整理一份未来计划。' : '先选择完整会话。', 'empty'));
  }
  function action(label, operation, body, target) {
    const b = node('button', label); b.type = 'button'; b.disabled = busy || pending.has(key(scope));
    b.addEventListener('click', () => mutate(operation, body)); target.append(b); return b;
  }
  function drawDetail() {
    const target = $('detail'); target.replaceChildren();
    if (!selected) { target.append(node('p', '选择计划查看活动与进度。', 'empty')); return; }
    const record = selected;
    target.append(node('h3', record.title), node('p', record.date + ' · ' + record.timezone + ' · 修订 ' + record.revision, 'hint'), node('p', '来源：' + (record.provenance.origin === 'goal_definition_template' ? '已有目标定义整理，未调用模型' : '管理员维护的计划定义') + '；不代表已经执行。', 'hint'));
    for (const item of record.items) {
      const card = node('article', undefined, 'scoped-plan-item'); card.append(node('strong', item.title), node('p', item.description), node('small', roleTime(item.scheduled_at, record.timezone)), node('p', (item.status === 'pending' ? '待完成' : item.status === 'completed' ? '角色活动已明确完成' : '已取消') + ' · ' + (progressLabels[item.progress_state] || item.progress_state), 'hint'));
      const linked = item.goal_ids;
      card.append(node('p', linked === undefined ? '目标关联：旧记录仍按原文字匹配，可编辑指定目标。' : linked.length ? '关联目标：' + linked.map(id => goalOptions.find(goal => goal.id === id)?.title || '已保留的目标').join('、') : '仅记录活动，不推进目标。', 'hint'));
      if (item.progress_report) card.append(node('p', '匹配目标 ' + item.progress_report.matched + '；本次推进 ' + item.progress_report.advanced + '；既有收据 ' + item.progress_report.duplicate, 'hint'));
      const buttons = node('div', undefined, 'actions');
      if (!record.archived && record.status === 'active' && item.status === 'pending') {
        const base = {scope: {...scope}, id: record.id, item_id: item.id, expected_revision: record.revision};
        const complete = action('标记角色活动完成', 'item/complete', {...base, request_id: requestId()}, buttons);
        complete.title = '只表示虚构角色活动完成，不是手机观察或现实行动';
        action('取消这项活动', 'item/cancel', base, buttons);
      }
      card.append(buttons); target.append(card);
    }
    const buttons = node('div', undefined, 'actions'), base = {scope: {...scope}, id: record.id, expected_revision: record.revision};
    if (record.archived) action('恢复归档', 'restore', base, buttons);
    else {
      if (record.status === 'active') {
        const edit = node('button', '编辑计划'); edit.type = 'button'; edit.disabled = busy; edit.addEventListener('click', () => editor(record)); buttons.append(edit);
        action('取消未完成活动', 'cancel', base, buttons);
      }
      if (record.items.some(x => x.status === 'completed' && x.progress_state !== 'applied')) action('核对并继续目标推进', 'apply', {scope: {...scope}, id: record.id}, buttons);
      action('归档计划', 'archive', base, buttons);
    }
    target.append(buttons);
  }
  async function detail(id) {
    if (busy || !scope) return;
    const target = {...scope}, own = ++serial; busy = true; controls();
    try { const value = await call('GET', 'detail', {...target, id}, target); if (!same(target) || own !== serial) return; selected = value.record; drawList(); drawDetail(); }
    catch (error) { if (same(target) && own === serial) notice(error.message, true); }
    finally { if (same(target) && own === serial) { busy = false; controls(); } }
  }
  function itemEditor(item) {
    const row = node('fieldset', undefined, 'scoped-plan-edit-item'); if (item && item.id) row.dataset.id = item.id;
    const zone = selected && selected.timezone || metadata && metadata.timezone_name;
    const minutes = offset(zone);
    const text = (label, type, value, max) => { const wrap = node('label', label), input = document.createElement(type === 'textarea' ? 'textarea' : 'input'); if (type !== 'textarea') input.type = type; input.value = value || ''; if (max) input.maxLength = max; wrap.append(input); row.append(wrap); return input; };
    const title = text('活动名称', 'text', item && item.title, 100); title.dataset.itemTitle = ''; title.required = true;
    text('说明', 'textarea', item && item.description, 300).dataset.itemDescription = '';
    const at = text('角色时间', 'time', item && minutes !== null ? new Date(item.scheduled_at * 1000 + minutes * 60000).toISOString().slice(11, 16) : ''); at.dataset.itemTime = ''; at.required = true;
    const links = node('label', '关联目标（可多选；不选则只记录活动）', 'scoped-plan-goal-links');
    const picker = node('select'); picker.multiple = true; picker.size = Math.min(4, Math.max(2, goalOptions.length)); picker.dataset.itemGoals = '';
    const linked = item && item.goal_ids || [];
    for (const goal of goalOptions) {
      if ((goal.archived || goal.status !== 'active') && !linked.includes(goal.id)) continue;
      const option = node('option', goal.title + (goal.status === 'active' && !goal.archived ? '' : '（目前不推进）'));
      option.value = goal.id; option.selected = linked.includes(goal.id); picker.append(option);
    }
    links.append(picker); row.append(links);
    if (item && item.goal_ids === undefined) {
      const legacy = node('label', undefined, 'scoped-plan-check'), keep = node('input'); keep.type = 'checkbox'; keep.checked = true; keep.dataset.itemLegacyMatching = '';
      legacy.append(keep, node('span', '保留此旧活动的文字匹配规则')); row.append(legacy);
      picker.addEventListener('change', () => { keep.checked = false; });
    }
    if (item) { row.dataset.originalTime = at.value; row.dataset.originalDay = selected.date; row.dataset.scheduledAt = String(item.scheduled_at); }
    const fixed = item && item.status !== 'pending';
    if (fixed) { for (const control of row.querySelectorAll('input,textarea,select')) control.disabled = true; row.dataset.fixed = JSON.stringify({id:item.id,title:item.title,description:item.description,scheduled_at:item.scheduled_at,...(item.goal_ids === undefined ? {} : {goal_ids:item.goal_ids})}); row.append(node('p', '已完成或取消的活动保留历史，不能改写。', 'hint')); }
    else { const remove = node('button', '移除此活动'); remove.type = 'button'; remove.addEventListener('click', () => row.remove()); row.append(remove); }
    return row;
  }
  function editor(record) {
    if (busy || !scope || pending.has(key(scope))) return;
    if (offset(record && record.timezone || metadata && metadata.timezone_name) === null) { notice('当前时区不支持手工时刻换算；可先按已有目标整理计划。', true); return; }
    selected = record || null; $('editor').hidden = false; $('editor-title').textContent = record ? '编辑计划' : '新建计划'; $('title').value = record ? record.title : '角色目标日计划';
    if (record) $('day').value = record.date;
    $('items').replaceChildren(...(record ? record.items : [null]).map(itemEditor)); controls();
  }
  // Existence of an old plan is not evidence that a timed-out edit completed.
  // Only compare the actual operation's stable source, revision and result.
  function confirms(intent, record) {
    const b = intent.body || {}, op = intent.operation;
    if (op === 'create' || op === 'generate') return record.provenance?.request_id === intent.request_id;
    if (record.id !== intent.id) return false;
    if (op === 'apply') return record.items.some(x=>x.status==='completed') && record.items.filter(x=>x.status==='completed').every(x=>x.progress_state==='applied');
    if (!(record.revision > b.expected_revision)) return false;
    if (op === 'archive') return record.archived === true;
    if (op === 'restore') return record.archived === false;
    if (op === 'cancel') return record.status === 'cancelled';
    if (op === 'item/complete' || op === 'item/cancel') {
      const item = record.items.find(x=>x.id===b.item_id);
      return !!item && (op === 'item/cancel' ? item.status==='cancelled' : item.status==='completed' && item.completion_request===b.request_id);
    }
    if (op !== 'update' || b.title !== undefined && record.title !== b.title) return false;
    return b.items === undefined || b.items.length === record.items.length && b.items.every((item,index)=>{
      const actual=record.items[index];
      return (!item.id || item.id===actual.id) && ['title','description','scheduled_at'].every(k=>item[k]===actual[k]) && (item.goal_ids === undefined || JSON.stringify(item.goal_ids) === JSON.stringify(actual.goal_ids));
    });
  }
  async function load() {
    const live = getScope();
    if (key(live) !== key(scope)) scopeChanged();
    if (!scope) { drawList(); drawDetail(); notice('先在上方选择完整会话。'); controls(); return; }
    if (busy) return;
    const target = {...scope}, own = ++serial; busy = true; controls(); notice('正在读取明确范围的目标计划…');
    try {
      const status = await call('GET', 'status', target, target);
      if (!same(target) || own !== serial) return;
      metadata = status.status;
      const minutes = offset(metadata.timezone_name);
      if (!$('day').value) $('day').value = new Date(Date.now() + (minutes || 0) * 60000).toISOString().slice(0,10);
      $('zone').textContent = '角色日期与时间：' + (metadata.timezone_name || '待确认') + '；本面板不启动调度或分享；当前授权：' + (metadata.progress_authorized === true ? '可核对目标推进。' : '仅维护计划。') + ' 自动行为请查看“角色日常”的实际设置。';
      const list = await call('GET', 'list', {...target, day:$('day').value, include_archived:$('archives').checked, limit:64}, target);
      if (!same(target) || own !== serial) return;
      records = list.records || [];
      goalOptions = list.goal_options || [];
      if (selected) selected = records.find(x => x.id === selected.id) || null;
      const unknown = pending.get(key(target));
      if (unknown) {
        const candidate = unknown.id ? records.find(x => x.id === unknown.id) : records.find(x => x.provenance && x.provenance.request_id === unknown.request_id);
        if (candidate && confirms(unknown, candidate)) { selected = candidate; pending.delete(key(target)); $('editor').hidden = true; notice('已按原请求和目标修订核对当前结果，没有重复提交。'); }
        else notice('原写入结果仍待核对，当前范围已锁定新写入；不要重复创建。', true);
      } else notice('已读取 ' + records.length + ' 份计划。' + (metadata.progress_authorized ? '当前真实会话可核对目标推进。' : '目前可维护计划；活动推进等待真实会话授权。'));
      drawList(); drawDetail();
    } catch (error) { if (same(target) && own === serial) notice(error.message || '计划暂不可用。', true); }
    finally { if (same(target) && own === serial) { busy = false; controls(); drawDetail(); } }
  }
  async function mutate(operation, body) {
    if (busy || !scope || pending.has(key(scope))) return;
    const target = {...scope}, own = ++serial; let failure = null;
    const intent = {operation, id:body.id, request_id:body.request_id, body:JSON.parse(JSON.stringify(body))};
    pending.set(key(target), intent); busy = true; controls(); drawDetail(); notice('正在保存，请勿重复提交…');
    try {
      const result = await call('POST', operation, body, target);
      if (pending.get(key(target)) === intent) pending.delete(key(target));
      if (!same(target) || own !== serial) return;
      selected = result.record; $('editor').hidden = true;
      notice(operation === 'item/complete' ? '角色活动已保存；是否推进目标请以下方进度回读为准。' : '已保存，正在回读当前计划。');
    } catch (error) {
      if ([400,401,403,404,409].includes(Number(error.status || error.statusCode)) && pending.get(key(target)) === intent) pending.delete(key(target));
      if (same(target) && own === serial) {
        failure = (error.message || '请求未完成。') + (pending.has(key(target)) ? ' 请刷新核对原计划，不要重复创建。' : ' 请修正字段后再保存。');
        notice(failure, true);
      }
    }
    finally { if (same(target) && own === serial) { busy = false; controls(); await load(); if (failure && same(target)) notice(failure, true); } }
  }
  $('refresh').addEventListener('click', load);
  $('day').addEventListener('change', () => { selected = null; $('editor').hidden = true; load(); });
  $('archives').addEventListener('change', load);
  $('new').addEventListener('click', () => editor(null));
  $('close').addEventListener('click', () => { $('editor').hidden = true; controls(); });
  $('add').addEventListener('click', () => { if ($('items').children.length < 12) $('items').append(itemEditor(null)); });
  $('generate').addEventListener('click', () => { try { mutate('generate', {scope:{...scope},request_id:requestId(),day:$('day').value,limit:6}); } catch (error) { notice(error.message, true); } });
  $('form').addEventListener('submit', event => {
    event.preventDefault(); if (busy || !scope) return;
    try {
      const zone = selected && selected.timezone || metadata && metadata.timezone_name, minutes = offset(zone);
      if (minutes === null) throw Error('角色时区尚未确认。');
      const items = [...$('items').children].map(row => {
        if (row.dataset.fixed) return JSON.parse(row.dataset.fixed);
        const time = row.querySelector('[data-item-time]').value;
        const scheduled = row.dataset.scheduledAt && row.dataset.originalDay === $('day').value && row.dataset.originalTime === time ? Number(row.dataset.scheduledAt) : Date.parse($('day').value + 'T' + time + ':00Z') / 1000 - minutes * 60;
        if (!Number.isFinite(scheduled)) throw Error('请填写每项活动的角色时间。');
        const legacy = row.querySelector('[data-item-legacy-matching]');
        const links = legacy && legacy.checked ? {} : {goal_ids:[...row.querySelector('[data-item-goals]').selectedOptions].map(option => option.value)};
        return {...(row.dataset.id ? {id:row.dataset.id} : {}),title:row.querySelector('[data-item-title]').value.trim(),description:row.querySelector('[data-item-description]').value.trim(),scheduled_at:scheduled,...links};
      });
      if (!items.length) throw Error('至少保留一项活动。');
      const body = {scope:{...scope},title:$('title').value.trim(),items};
      if (selected) {
        const prior = selected.items.map(item => ({id:item.id,title:item.title,description:item.description,scheduled_at:item.scheduled_at,...(item.goal_ids === undefined ? {} : {goal_ids:item.goal_ids})}));
        if (JSON.stringify(items) === JSON.stringify(prior)) delete body.items;
        mutate('update', {...body,id:selected.id,expected_revision:selected.revision});
      }
      else mutate('create', {...body,request_id:requestId(),day:$('day').value});
    } catch (error) { notice(error.message, true); }
  });
  function scopeChanged() {
    scope = getScope(); selected = null; records = []; goalOptions = []; metadata = null; busy = false; serial++;
    $('editor').hidden = true; $('day').value = ''; $('zone').textContent = '';
    drawList(); drawDetail(); notice(scope ? '范围已变化，请刷新读取当前计划。' : '先选择完整会话。'); controls();
  }
  global.TLSScopedDailyPlanPanel = {activate:load,scopeChanged}; controls();
})(window);
