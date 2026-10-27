/* Authenticated scoped profile review. No observe, auto-proof or send API. */
(function (global) {
  'use strict';
  const FIELDS = ['platform', 'bot_id', 'user_id', 'character_id', 'session_id'];
  const LABELS = {pending: '待审核', active: '已采用', rejected: '已拒绝', superseded: '已被新资料替代'};
  const REVIEW = {pending: '等待确认', auto: '质量门槛自动通过', approved: '人工已批准', rejected: '人工已拒绝', superseded: '已替代'};
  const REASONS = {awaiting_qualified_evidence_or_review: '证据暂不足，等待更多合格证据或人工确认',
    direct_qualified_statement: '明确原话已满足质量门槛', independent_qualified_evidence: '已有相互独立的合格证据',
    administrator_approved: '已由后台管理员明确批准', administrator_rejected: '已由后台管理员明确拒绝'};
  const sameScope = (a, b) => !!a && !!b && FIELDS.every(k => a[k] === b[k]);
  const scopeKey = value => JSON.stringify(FIELDS.map(k => value[k]));
  const validScope = value => !!value && (value.private === undefined || value.private === true) && FIELDS.every(k => typeof value[k] === 'string' && value[k].trim() === value[k] && value[k] && !/[\x00-\x1f]/.test(value[k]));
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = String(text); if (cls) n.className = cls; return n; };
  const stamp = value => Number.isFinite(value) && value > 0 ? new Date(value * 1000).toLocaleString() : '尚无记录';
  function eventId() {
    if (global.TLSBrowserCompat && typeof global.TLSBrowserCompat.uuid === 'function') return 'profile-review-' + global.TLSBrowserCompat.uuid();
    if (global.crypto && typeof global.crypto.randomUUID === 'function') return 'profile-review-' + global.crypto.randomUUID();
    throw Error('本页无法生成审核动作ID，请刷新后再操作。');
  }
  function mount(root, options) {
    if (!root || !options || typeof options.api !== 'function') throw Error('需要当前后台API');
    root.innerHTML = `<section class="profile-candidates"><header><h2>画像候选审核</h2><p>先核原文和来源，再决定是否采用。候选不是已核实事实；此处不创建聊天授权。</p></header><p data-profile-scope></p><form data-profile-search><input data-profile-query type="search" maxlength="128" placeholder="搜索偏好、事实或原文"><select data-profile-filter><option value="">全部状态</option><option value="pending">待审核</option><option value="active">已采用</option><option value="rejected">已拒绝</option><option value="superseded">已替代</option></select><button>搜索</button><button type="button" data-profile-refresh>刷新</button></form><p data-profile-notice role="status" aria-live="polite"></p><div class="profile-columns"><div data-profile-list></div><section data-profile-detail aria-label="候选详情"><p>选择一条候选查看原文、证据与审核状态。</p></section></div></section>`;
    const $ = selector => root.querySelector(selector);
    const states = new Map(), pending = new Map();
    let scope = null, state = null, epoch = 0, serial = 0, destroyed = false;
    const alive = (oldScope, token) => !destroyed && epoch === token && sameScope(scope, oldScope);
    const notice = (text, error = false) => { $('[data-profile-notice]').textContent = text; $('[data-profile-notice]').dataset.error = String(error); };
    const requestKey = (targetScope, id) => scopeKey(targetScope) + ':' + id;
    async function call(method, path, payload, expectedScope) {
      let timer;
      try {
        const response = await Promise.race([options.api(method, 'page/profile-candidates/' + path, payload),
          new Promise((_, reject) => { timer = setTimeout(() => reject(Error('候选请求超时，请回读核对。')), 15000); })]);
        const value = response && response.ok === true ? response : response && response.data;
        if (!value || value.ok !== true || value.backend !== 'native_profile_candidates' || !sameScope(value.scope, expectedScope)) throw Error('候选回读范围或格式不匹配。');
        return value;
      } finally { clearTimeout(timer); }
    }
    function renderList() {
      const list = $('[data-profile-list]'); list.replaceChildren();
      if (!state || !state.rows.length) { list.append(node('p', scope ? '当前筛选下没有候选。' : '请先选择完整用户、角色和会话。')); return; }
      for (const item of state.rows) {
        const button = node('button', undefined, 'profile-candidate-card'); button.type = 'button';
        button.append(node('strong', item.value || item.content || '候选资料'), node('span', LABELS[item.status] || '状态待核对'),
          node('small', (item.dimension || item.memory_type || '画像资料') + ' · 合格证据 ' + (Number.isSafeInteger(item.evidence_count) ? item.evidence_count : '未知')));
        button.dataset.selected = String(state.selected && state.selected.id === item.id);
        button.addEventListener('click', () => detail(item.id)); list.append(button);
      }
      list.append(node('p', '每次最多显示100条；可按文字和状态继续筛选。', 'profile-hint'));
    }
    function renderDetail() {
      const panel = $('[data-profile-detail]'); panel.replaceChildren();
      const item = state && state.selected;
      if (!item) { panel.append(node('p', '选择一条候选查看详情。')); return; }
      panel.append(node('h3', item.value || '画像候选'), node('p', item.content || ''),
        node('p', (LABELS[item.status] || '状态待核对') + ' · ' + (REVIEW[item.review_status] || '审核状态待核对')),
        node('p', '资料维度：' + (item.dimension || item.memory_type || '未知') + '；修订：' + item.revision),
        node('p', '合格独立证据：' + (Number.isSafeInteger(item.evidence_count) ? item.evidence_count : '未知')));
      const reasons = Array.isArray(item.reasons) ? item.reasons.filter(x => typeof x === 'string').map(x => REASONS[x] || '其他待核原因，请核对原文和证据') : [];
      panel.append(node('h4', '待确认原因'), node('p', reasons.length ? reasons.join('；') : '没有额外待确认原因，请仍核对原文与当前归属。'));
      panel.append(node('h4', '原文与来源'));
      for (const source of (Array.isArray(item.sources) ? item.sources : []).slice(0, 20)) {
        const card = node('blockquote'); card.append(node('p', source.source_text || '原文不可用'),
          node('small', (source.source_id || '来源待核对') + ' · ' + (source.qualified === true ? '计入合格证据' : '未计入合格证据'))); panel.append(card);
      }
      panel.append(node('p', '建立：' + stamp(item.created_at) + '；更新：' + stamp(item.updated_at), 'profile-hint'));
      if (item.reviewer) panel.append(node('p', '审核人：' + item.reviewer + '；时间：' + stamp(item.reviewed_at), 'profile-hint'));
      const unresolved = pending.get(requestKey(scope, item.id));
      const controls = node('div', undefined, 'profile-actions');
      for (const [action, label] of [['approve', '批准采用'], ['reject', '拒绝候选']]) {
        const button = node('button', label); button.type = 'button'; button.disabled = !!unresolved || state.busy || item.status === 'superseded';
        button.addEventListener('click', () => review(action)); controls.append(button);
      }
      const check = node('button', '回读审核结果'); check.type = 'button'; check.addEventListener('click', () => detail(item.id)); controls.append(check); panel.append(controls);
      if (unresolved) panel.append(node('p', '该审核结果尚未确认，请回读核对；不会自动重复提交。', 'profile-warning'));
    }
    async function load() {
      if (!scope || destroyed) return;
      const target = {...scope}, token = epoch, ownSerial = ++serial, ownState = state;
      notice('正在读取候选…');
      try {
        const payload = Object.fromEntries(FIELDS.map(k => [k, target[k]])); payload.limit = 100;
        if ($('[data-profile-query]').value.trim()) payload.q = $('[data-profile-query]').value.trim();
        if ($('[data-profile-filter]').value) payload.status = $('[data-profile-filter]').value;
        const value = await call('GET', 'list', payload, target);
        if (!alive(target, token) || ownSerial !== serial || state !== ownState) return;
        if (!Array.isArray(value.records)) throw Error('候选列表格式不完整。');
        state.rows = value.records; renderList(); notice('已读取 ' + value.records.length + ' 条候选。');
      } catch (error) { if (alive(target, token) && ownSerial === serial) notice(error.message || '候选读取失败，请稍后重试。', true); }
    }
    async function detail(id) {
      if (!scope || destroyed) return;
      const target = {...scope}, token = epoch, ownSerial = ++serial;
      try {
        const value = await call('GET', 'detail', {...Object.fromEntries(FIELDS.map(k => [k, target[k]])), id}, target);
        if (!alive(target, token) || ownSerial !== serial) return;
        if (!value.record || value.record.id !== id) throw Error('候选详情不匹配。');
        state.selected = value.record;
        const key = requestKey(target, id), intent = pending.get(key);
        if (intent && value.record.review_event_id === intent.event_id) {
          pending.delete(key); notice('审核已回读确认。');
        } else if (intent) notice('尚不能确认原审核结果；保留原动作ID，只读核对，不自动重发。', true);
        renderList(); renderDetail();
      } catch (error) { if (alive(target, token) && ownSerial === serial) notice(error.message || '详情读取失败。', true); }
    }
    async function review(action) {
      if (!scope || !state || !state.selected || state.busy) return;
      const target = {...scope}, token = epoch, ownState = state, item = state.selected;
      const key = requestKey(target, item.id);
      if (pending.has(key)) { notice('此候选有尚未确认的审核，请先回读。', true); return; }
      let intent;
      try { intent = {scope: target, id: item.id, expected_revision: item.revision, event_id: eventId()}; }
      catch (error) { notice(error.message, true); return; }
      pending.set(key, intent); ownState.busy = true; renderDetail(); notice('正在提交本次明确审核…');
      let accepted = false;
      try {
        const result = await call('POST', action, intent, target);
        if (!result.record || result.record.id !== item.id || result.record.review_event_id !== intent.event_id) throw Error('审核回执尚未确认。');
        accepted = true;
        pending.delete(key);
        ownState.selected = result.record;
        if (!alive(target, token)) return;
        await detail(item.id);
      } catch (error) {
        // Unknown completion retains this exact intent. Only GET reconciles it.
        const code = Number(error && (error.status || error.statusCode));
        if (!accepted && [400, 401, 403, 404, 409].includes(code)) {
          pending.delete(key);
          if (alive(target, token)) {
            ownState.selected = null;
            notice('本次审核已被拒绝，未采用此请求。请重新读取候选与最新修订后再决定。', true);
          }
        } else if (alive(target, token)) notice(accepted ? '审核回执已确认；最新详情暂不可读取，请刷新核对。' : '审核结果尚未确认。请回读核对，不要重复提交。', true);
      } finally { ownState.busy = false; if (alive(target, token) && state === ownState) renderDetail(); }
    }
    const onSearch = event => { event.preventDefault(); load(); };
    $('[data-profile-search]').addEventListener('submit', onSearch);
    $('[data-profile-refresh]').addEventListener('click', load);
    return Object.freeze({
      setScope(value) {
        ++epoch; ++serial;
        scope = validScope(value) ? {...Object.fromEntries(FIELDS.map(k => [k, value[k]])), private: true} : null;
        state = scope ? states.get(scopeKey(scope)) : null;
        if (scope && !state) { state = {rows: [], selected: null, busy: false}; states.set(scopeKey(scope), state); }
        $('[data-profile-scope]').textContent = scope ? '当前用户 ' + scope.user_id + ' · 角色 ' + scope.character_id + ' · 会话 ' + scope.session_id : '尚未选择完整资料范围。';
        renderList(); renderDetail(); notice('');
      },
      activate: load,
      unmount() { destroyed = true; ++epoch; ++serial; root.replaceChildren(); }
    });
  }
  global.TLSProfileCandidates = Object.freeze({mount});
})(window);
