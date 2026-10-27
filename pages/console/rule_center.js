(function (root) {
  'use strict';
  const FIELDS = ['platform', 'bot_id', 'user_id', 'character_id', 'session_id'];
  const LABELS = {pending: '待审核', approved: '已批准，等待生效', rejected: '已拒绝', applied: '已生效'};
  function mount(options) {
    const container = typeof options.container === 'string' ? document.getElementById(options.container) : options.container;
    if (!container || typeof options.api !== 'function' || typeof options.getScope !== 'function'
        || typeof options.uuid !== 'function') throw Error('Rule center requires the existing authenticated page bridge and scope.');
    const api = options.api, notify = options.notify || function () {};
    let sequence = 0, busy = false, snapshot = null, draftId = null, scopeKey = '';
    const actions = new Map();
    const node = (tag, text, css) => {
      const element = document.createElement(tag);
      if (text !== undefined) element.textContent = String(text);
      if (css) element.className = css;
      return element;
    };
    const scope = () => {
      const value = options.getScope();
      if (!value || FIELDS.some(key => typeof value[key] !== 'string' || !value[key].trim())) return null;
      return Object.fromEntries(FIELDS.map(key => [key, value[key]]));
    };
    const key = value => JSON.stringify(value);
    const current = (value, token) => token === sequence && key(scope()) === key(value);
    const panel = node('section', undefined, 'rule-center');
    const heading = node('h2', '话语与行为规则中心');
    const boundary = node('p', '这里管理明确的用词、长短和追问偏好，不修改人格或事实。候选需人工审核；批准后复用原有表达规则入口。App 行为规则仍使用现有执行与发送检查。', 'rule-center-hint');
    const status = node('p', '请选择完整的用户、角色和会话范围。', 'rule-center-status');
    status.setAttribute('role', 'status');
    const reload = node('button', '刷新规则');
    reload.type = 'button';
    const behavior = node('button', '管理 App 行为规则');
    behavior.type = 'button';
    behavior.addEventListener('click', () => {
      if (typeof options.onNavigate === 'function') options.onNavigate('phone');
      else root.location.hash = '#view-phone';
    });
    const toolbar = node('div', undefined, 'rule-center-actions');
    toolbar.append(reload, behavior);
    const form = node('form');
    const label = node('label', '添加明确纠正');
    const input = node('textarea');
    input.maxLength = 500; input.rows = 3;
    input.placeholder = '例如：别再说“亲亲”，改成“你”；以后回复简短一点；以后少追问';
    input.setAttribute('aria-label', '明确的措辞纠正');
    const help = node('p', '只接受明确纠正，不从玩笑、引用、角色扮演或模糊评价猜测规则。此处只新建待审核候选。', 'rule-center-hint');
    const submit = node('button', '加入待审核'); submit.type = 'submit';
    label.append(input); form.append(label, help, submit);
    const candidates = node('div', undefined, 'rule-center-records');
    const rules = node('div', undefined, 'rule-center-records');
    panel.append(heading, boundary, toolbar, status, form, node('h3', '纠正候选'), candidates,
                 node('h3', '已登记的表达规则'), rules);
    container.replaceChildren(panel);
    function availability() {
      submit.disabled = busy || !scope(); reload.disabled = busy;
      input.disabled = busy;
      for (const button of panel.querySelectorAll('[data-rule-action]')) button.disabled = busy;
    }
    function operationId(kind, row) {
      const identity = kind + ':' + row.id + ':' + row.revision;
      if (!actions.has(identity)) actions.set(identity, 'rule-center.' + options.uuid());
      return actions.get(identity);
    }
    function description(row) {
      if (row.kind === 'replace') return '“' + row.pattern + '” → “' + row.replacement + '”';
      if (row.kind === 'avoid') return '避免用词：“' + row.pattern + '”';
      return ({natural_direct: '语气自然、直接', short: '优先简短回复', normal: '按内容需要恢复正常表达',
               detailed: '需要时详细解释', less: '减少不必要的' + (row.pattern === 'questions' ? '追问' : '长列表')})[row.preference] || row.pattern;
    }
    function button(label, action) {
      const element = node('button', label); element.type = 'button';
      element.setAttribute('data-rule-action', 'true'); element.addEventListener('click', action);
      return element;
    }
    function draw(data) {
      candidates.replaceChildren(); rules.replaceChildren();
      for (const row of data.candidates || []) {
        const card = node('article', undefined, 'rule-center-card');
        card.append(node('strong', LABELS[row.state] || '未知状态'), node('p', row.feedback));
        const details = node('details'); details.append(node('summary', '来源与版本'),
          node('p', '纠正来源：' + row.source_message_id), node('p', '候选版本：' + row.revision));
        if (row.approval) details.append(node('p', '审核人：' + row.approval.reviewer_id));
        card.append(details);
        const controls = node('div', undefined, 'rule-center-actions');
        if (row.state === 'pending' || row.state === 'approved') controls.append(button(
          row.state === 'pending' ? '批准并生效' : '重试生效', () => review(row, 'approve_apply')));
        if (row.state === 'pending') controls.append(button('拒绝', () => review(row, 'reject')));
        card.append(controls); candidates.append(card);
      }
      if (!candidates.children.length) candidates.append(node('p', '当前范围还没有待审核的纠正。', 'rule-center-hint'));
      for (const row of data.rules || []) {
        const card = node('article', undefined, 'rule-center-card');
        card.append(node('strong', row.active ? '已启用' : '已停用'), node('p', description(row)));
        const details = node('details'); details.append(node('summary', '来源与版本'),
          node('p', '原始登记来源：' + row.created_source_message_id), node('p', '规则版本：' + row.revision));
        card.append(details);
        if (row.active) card.append(button('停用', () => disable(row)));
        rules.append(card);
      }
      if (!rules.children.length) rules.append(node('p', '尚无生效规则。待审候选不会改变回复。', 'rule-center-hint'));
      availability();
    }
    async function refresh() {
      const selected = scope(), token = ++sequence;
      const nextKey = key(selected);
      if (scopeKey && scopeKey !== nextKey) {input.value = ''; draftId = null; actions.clear();}
      scopeKey = nextKey; snapshot = null; candidates.replaceChildren(); rules.replaceChildren();
      if (!selected) {status.textContent = '请选择完整的用户、角色和会话范围。'; availability(); return false;}
      status.textContent = '正在读取当前范围的纠正与规则…';
      try {
        const result = await api('GET', 'page/rule-center/state', selected);
        if (!current(selected, token)) return false;
        snapshot = result; draw(result); status.textContent = '已从后台读取。批准并生效是一个动作；不产生发送任务。';
        return true;
      } catch (_) {
        if (current(selected, token)) status.textContent = '暂时无法读取规则，请刷新；草稿会保留。';
        return false;
      } finally {if (current(selected, token)) availability();}
    }
    async function mutate(path, body, success) {
      if (busy || !scope()) return false;
      const selected = scope(), token = sequence;
      let expectedSequence = token;
      busy = true; availability(); status.textContent = '正在保存并回读…';
      try {
        const result = await api('POST', 'page/rule-center/' + path, {scope: selected, ...body});
        if (!current(selected, token)) return false;
        if (result.candidate && result.candidate.state === 'unrecognized') throw Error('unrecognized');
        expectedSequence = sequence + 1;
        const confirmed = await refresh();
        if (sequence !== expectedSequence || key(scope()) !== key(selected)) return false;
        if (!confirmed) throw Error('readback-unavailable');
        status.textContent = success; notify(success); return true;
      } catch (error) {
        if (sequence === expectedSequence && key(scope()) === key(selected)) status.textContent = error && error.message === 'unrecognized'
          ? '尚未识别为明确纠正，请使用示例句式。草稿已保留。'
          : '尚未确认保存结果。草稿及操作编号已保留；请刷新确认后重试。';
        return false;
      } finally {busy = false; availability();}
    }
    async function review(row, decision) {
      await mutate('review', {id: row.id, expected_revision: row.revision, decision,
        request_id: operationId(decision, row), note: ''}, decision === 'reject' ? '已拒绝，不改变表达规则。' : '已批准并从后台回读，表达规则已生效。');
    }
    async function disable(row) {
      await mutate('disable', {id: row.id, expected_revision: row.revision,
        source_message_id: operationId('disable', row)}, '已停用，并从后台重新读取确认。');
    }
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (busy || !scope() || !input.value.trim()) return;
      const feedback = input.value.trim();
      if (!draftId) draftId = 'rule-center.correction.' + options.uuid();
      if (await mutate('propose', {feedback, source_message_id: draftId}, '已加入待审核，尚未影响回复。')) {
        input.value = ''; draftId = null;
      }
    });
    input.addEventListener('input', () => {draftId = null;});
    reload.addEventListener('click', refresh); availability();
    return {refresh, reset() {sequence++; snapshot = null; candidates.replaceChildren(); rules.replaceChildren();
      status.textContent = '会话范围已变更，请刷新规则。'; availability();}, destroy() {sequence++; container.replaceChildren();}};
  }
  const api = Object.freeze({mount});
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TLSRuleCenter = api;
})(typeof globalThis === 'object' ? globalThis : this);
