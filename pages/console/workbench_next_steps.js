/* Current facts -> useful next actions. No writes, polling, models or new state store. */
(function (root, factory) {
  'use strict';
  const exported = factory();
  if (typeof module === 'object' && module.exports) module.exports = exported;
  else root.TLSWorkbenchNextSteps = exported;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const FIELDS = ['platform', 'bot_id', 'user_id', 'character_id', 'session_id'];
  const PROFILE_LIMIT = 20;
  const VIEWS = new Set(['modules', 'config', 'tasks', 'memory', 'profile_candidates', 'phone', 'phone_service',
    'phone_flow', 'insight', 'pc_daily_native', 'proactive_native', 'native_ownership', 'agenda', 'memo_notes',
    'dates', 'special_occasions', 'maintenance', 'scoped_daily_plan', 'music_library']);
  const full = s => !!s && FIELDS.every(k => typeof s[k] === 'string' && s[k].trim());
  const detached = s => full(s) ? Object.fromEntries(FIELDS.map(k => [k, s[k]])) : null;
  const same = (a, b) => full(a) && full(b) && FIELDS.every(k => a[k] === b[k]);
  const text = value => typeof value === 'string' ? value.slice(0, 240) : '';
  const amount = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
  const card = (id, title, description, view, label, priority, group = 'admin', state = 'action') =>
    ({id, title, description, view: VIEWS.has(view) ? view : 'modules', label, priority, group, state});

  function project(overview, {scope = null, profile = null, occasions = null} = {}) {
    const cards = [], add = row => { if (!cards.some(r => r.id === row.id)) cards.push(row); };
    const valid = overview && typeof overview === 'object' && typeof overview.runtime_active === 'boolean'
      && (!full(overview.scope) || same(overview.scope, scope));
    const scoped = valid && same(overview.scope, scope);
    const rows = valid && Array.isArray(overview.capabilities) ? overview.capabilities.filter(r => r && typeof r === 'object') : [];
    if (!valid) {
      add(card('overview-unread', '运行状态尚未读取', '读取服务状态后，才能给出当前问题和处理入口。', 'modules', '查看运行状态', 100, 'admin', 'unknown'));
    } else if (overview.runtime_active === false) {
      add(card('runtime-inactive', '生活服务当前未运行', '请先查看原生服务与配置，页面不会自动开启执行权。', 'native_ownership', '查看原生服务', 100));
    }
    const lanes = valid && Array.isArray(overview.tasks?.lanes) ? overview.tasks.lanes : [];
    let unknown = 0, unknownKnown = false;
    for (const lane of lanes) {
      const counts = lane?.counts;
      let laneKnown = false;
      if (counts && typeof counts === 'object') {
        for (const key of ['unknown', 'quarantined']) {
          const count = amount(counts[key]);
          if (count !== null) { unknown += count; unknownKnown = laneKnown = true; }
        }
      }
      if (!laneKnown && Array.isArray(lane?.tasks)) {
        const count = lane.tasks.filter(t => ['unknown', 'quarantined'].includes(t?.state)).length;
        if (count) { unknown += count; unknownKnown = true; }
      }
    }
    if (unknownKnown && unknown > 0) {
      add(card('unknown-deliveries', unknown + '项发送结果需要核对',
        (scoped ? '当前会话' : '管理员可见的队列合计') + '存在结果未确认或需隔离检查的任务。先查看原任务记录，再决定处理。',
        'tasks', '核对原任务', 98, 'admin', 'review'));
    }
    if (profile?.state === 'available' && same(profile.scope, scope) && amount(profile.pending) > 0) {
      add(card('profile-review', (profile.limited ? '至少' : '') + profile.pending + '项画像资料待审核',
        '查看原文、来源和证据后再批准或拒绝；待审核资料不会提前作为已采用画像。',
        'profile_candidates', '打开画像审核', 90, 'admin', 'review'));
    } else if (profile?.state === 'unavailable' && same(profile.scope, scope)) {
      add(card('profile-unread', '画像候选暂未读取', '当前范围的候选读取未完成，不能按“没有待审核”处理。',
        'profile_candidates', '查看候选资料', 35, 'admin', 'unknown'));
    }
    if (occasions?.state === 'available' && same(occasions.scope, scope)) {
      const settings = occasions.settings, timetable = settings?.values?.course_timetable;
      if (timetable?.enabled === true && settings?.calendar?.anchor_confirmed === false) {
        const week = amount(settings.calendar.current_week);
        add(card('academic-week', '课表教学周尚未核对',
          (week !== null ? '当前按第' + week + '周排课。' : '当前教学周尚未确认。') + '核对周一锚点和周次后，再确认课前提醒日期。',
          'special_occasions', '核对课表周次', 85, 'admin', 'review'));
      }
      const selected = settings?.values?.holiday_messages;
      const unavailable = Array.isArray(settings?.holidays) && selected?.enabled === true && Array.isArray(selected.holidays)
        ? settings.holidays.filter(r => selected.holidays.includes(r?.id) && r.available === false).length : 0;
      if (unavailable) add(card('holiday-calendar', unavailable + '类所选节日暂不可计算',
        '节日目录实际报告日期来源不可用；可检查所选节日与日期组件。', 'special_occasions', '查看节日设置', 84));
    } else if (occasions?.state === 'unavailable' && same(occasions.scope, scope)) {
      add(card('occasions-unread', '课表与特殊日期暂未读取', '当前用户资料读取未完成；已有课表或生日不会被默认值替换。',
        'special_occasions', '查看原资料', 34, 'admin', 'unknown'));
    }
    for (const row of rows) {
      if (typeof row.id !== 'string' || row.id.startsWith('legacy.') || row.enabled === false) continue;
      if (row.status === 'source_unavailable' || (row.status === 'configuration_missing' && row.runtime_active !== false)) {
        add(card('source:' + row.id, (text(row.label) || '资料来源') + '需要补充配置',
          row.reader_state === 'missing' ? '已启用的来源当前找不到所配置资料。请核对路径或授权来源。' : '当前能力实际报告来源不可用，请打开对应配置核对。',
          row.entry, '打开对应配置', 80));
      } else if (['blocked', 'unavailable'].includes(row.status) && !['tls.media.catalog'].includes(row.id)) {
        add(card('service:' + row.id, (text(row.label) || '功能') + '当前需要处理',
          text(row.detail) || text(row.purpose) || '当前能力状态报告未挂载或存在阻塞，请查看对应页面。',
          row.entry, '查看与处理', 65));
      }
    }
    const awaiting = scoped ? rows.filter(r => r.status === 'awaiting_scope' && r.administration?.available !== true &&
      !r.id?.startsWith('legacy.') && r.enabled !== false) : [];
    if (awaiting.length) {
      const names = [...new Set(awaiting.map(r => text(r.label)).filter(Boolean))].slice(0, 3);
      add(card('scope-authorization', '自动执行仍等待真实会话授权',
        names.join('、') + '等能力当前等待真实来源登记。管理员可维护资料；自动执行仍按原授权检查。',
        'native_ownership', '查看会话与执行权', 75, 'authorization', 'awaiting_scope'));
    } else if (valid && !scoped) {
      add(card('scope-selection', '选择会话查看专属事项', '上方选定已有用户与角色后，可读取该会话的画像、课表和自动执行状态。',
        'modules', '选择会话', 25, 'authorization', 'selection'));
    }
    return {available: !!valid, scopeSelected: scoped, sampledAt: valid && typeof overview.sampled_at === 'number' ? overview.sampled_at : null,
      admin: cards.filter(r => r.group === 'admin').sort((a, b) => b.priority - a.priority).slice(0, 6),
      authorization: cards.filter(r => r.group === 'authorization'),
      limitations: '依据当前运行快照和有界资料读取；管理员维护不等于自动执行授权。'};
  }

  function mount(container, {api, getScope = () => null, onNavigate = () => {}, onQuickCreate = () => {},
    canCreate = () => false, onRefresh = null, onSelectScope = () => {}, timeoutMs = 15000} = {}) {
    if (!container || typeof api !== 'function') throw Error('Authenticated workbench API required');
    const document = container.ownerDocument;
    const el = (tag, content, className) => { const n = document.createElement(tag); if (content !== undefined) n.textContent = content; if (className) n.className = className; return n; };
    let overview = null, profile = null, occasions = null, signature = '', epoch = 0, disposed = false, busy = false, loaded = false;
    const timers = new Set();
    container.replaceChildren(); container.classList.add('tls-next-steps');
    const heading = el('div', undefined, 'next-heading'), title = el('h2', '待处理与下一步'), refresh = el('button', '刷新事项'); refresh.type = 'button';
    refresh.dataset.nextAction = 'refresh'; heading.append(title, refresh);
    const status = el('p', '按当前实际状态整理可处理事项。', 'hint'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const quick = el('div', undefined, 'next-quick'), admin = el('div', undefined, 'next-admin'), auth = el('div', undefined, 'next-authorization');
    const description = el('p', '资料维护和自动执行授权分别显示。', 'hint');
    container.append(heading, status, quick, admin, auth, description);
    const quickButtons = [];
    for (const [type, name] of [['agenda', '安排一个提醒'], ['memo_notes', '记一条便签']]) {
      const button = el('button', name); button.type = 'button'; button.dataset.nextCreate = type;
      button.addEventListener('click', () => { if (!disposed && canCreate(type) === true) onQuickCreate(type); });
      quick.append(button); quickButtons.push([type, button]);
    }
    const scopeNow = () => detached(getScope());
    function alignScope() {
      const next = JSON.stringify(scopeNow());
      if (signature !== next) { signature = next; epoch++; busy = false; loaded = false; profile = occasions = null; }
    }
    function render() {
      if (disposed) return;
      alignScope();
      const value = project(overview, {scope: scopeNow(), profile, occasions});
      refresh.disabled = busy;
      for (const [type, button] of quickButtons) {
        button.disabled = canCreate(type) !== true;
        button.title = button.disabled ? '先选择当前范围，并确认对应原生服务可用。' : '打开原有表单，填写后再保存。';
      }
      admin.replaceChildren(el('h3', '管理员可维护'));
      auth.replaceChildren(el('h3', '自动执行与会话授权'));
      function append(target, row) {
        const item = el('article', undefined, 'next-item'); item.dataset.nextId = row.id; item.dataset.nextState = row.state;
        const content = el('div', undefined, 'next-content'); content.append(el('strong', row.title), el('p', row.description, 'hint'));
        const button = el('button', row.label); button.type = 'button';
        button.addEventListener('click', () => { if (disposed) return; if (row.state === 'selection') onSelectScope(); else onNavigate(row.view); });
        item.append(content, button); target.append(item);
      }
      value.admin.forEach(row => append(admin, row)); value.authorization.forEach(row => append(auth, row));
      if (!value.admin.length) admin.append(el('p', loaded ? '本次读取没有发现需要立即处理的资料事项。' : '运行快照已读取；专属资料将在打开工作台或刷新时补充。', 'hint'));
      if (!value.authorization.length) auth.append(el('p', value.scopeSelected ? '当前快照没有报告等待会话授权的能力。' : '会话执行状态尚未读取。', 'hint'));
      description.textContent = value.limitations;
    }
    async function read(path, params) {
      let timer;
      try {
        return await Promise.race([Promise.resolve().then(() => api('GET', path, params)), new Promise((_, reject) => {
          timer = setTimeout(() => reject(Error('Read deadline')), timeoutMs); timers.add(timer);
        })]);
      } finally { clearTimeout(timer); timers.delete(timer); }
    }
    async function activate(force = false) {
      if (disposed) return false;
      alignScope();
      const scope = scopeNow();
      if (!scope || busy || loaded && !force) { render(); return false; }
      const token = ++epoch, captured = JSON.stringify(scope); busy = true;
      status.textContent = '正在读取当前会话的待审核资料和课表状态…'; render();
      const results = await Promise.allSettled([
        read('page/profile-candidates/list', {...scope, status: 'pending', limit: PROFILE_LIMIT}),
        read('page/special-occasions/settings', scope)
      ]);
      if (disposed || token !== epoch || captured !== JSON.stringify(scopeNow())) return false;
      const p = results[0], o = results[1];
      profile = p.status === 'fulfilled' && p.value?.ok === true && same(p.value.scope, scope) && Array.isArray(p.value.records)
        && p.value.records.length <= PROFILE_LIMIT && p.value.records.every(r => r?.status === 'pending')
        ? {state: 'available', scope, pending: p.value.records.length, limited: p.value.records.length === PROFILE_LIMIT}
        : {state: 'unavailable', scope};
      occasions = o.status === 'fulfilled' && o.value?.ok === true && same(o.value.scope, scope) && o.value.settings?.values
        ? {state: 'available', scope, settings: o.value.settings} : {state: 'unavailable', scope};
      busy = false; loaded = true;
      status.textContent = '已读取当前事项 · ' + new Date().toLocaleTimeString() +
        (profile.state !== 'available' || occasions.state !== 'available' ? ' · 部分资料待读取' : '');
      render(); return true;
    }
    refresh.addEventListener('click', async () => {
      if (disposed || busy) return;
      if (typeof onRefresh === 'function') { try { await onRefresh(); } catch { status.textContent = '运行快照刷新未完成，已有资料入口仍可使用。'; } }
      await activate(true);
    });
    render();
    return {activate, updateOverview(value) { overview = value; render(); },
      invalidate() { epoch++; loaded = false; busy = false; profile = occasions = null; render(); },
      destroy() { disposed = true; epoch++; for (const timer of timers) clearTimeout(timer); timers.clear(); container.replaceChildren(); }};
  }
  return Object.freeze({project, mount, PROFILE_LIMIT});
});
