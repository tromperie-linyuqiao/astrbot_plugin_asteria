/* Native role personal goals and daily progression. Uses the console SDK/auth
   and one explicit complete private scope; never sends or schedules anything. */
(function (global) {
  'use strict';
  const SCOPE = ['platform', 'bot_id', 'user_id', 'character_id', 'session_id'];
  const FIELDS = ['title', 'category', 'auto_step', 'stall_days', 'share_cooldown_hours',
    'next_step', 'note', 'keywords'];
  const STATUSES = ['active', 'paused', 'completed', 'abandoned'];
  const STATUS_LABEL = { active: '进行中', paused: '已暂停', completed: '已完成', abandoned: '已放弃' };
  const LOG_LABEL = {
    imported: '迁移导入', manual_progress: '手动推进', activity_progress: '活动推进',
    manual_adjust: '下调进度', completed: '完成', reopened: '重新打开', paused: '暂停',
    resumed: '恢复', abandoned: '放弃', archived: '归档', restored: '恢复归档'
  };
  const EVIDENCE_LABEL = {
    real_observation: '真实外部观测', user_reported: '用户明确维护', roleplay_event: '虚构角色经历',
    action_result: '行动结果', model_inference: '模型推断（不可推进）'
  };
  const SHARE_LABEL = { progress: '进度分享', milestone: '里程碑分享', completed: '完成分享', stalled: '停滞关心' };
  const CREATIVE = ['创作', '写作', '绘画创作', '作品'];
  const PAGE = 20;
  const MAX_GOALS = 200;
  const clone = value => JSON.parse(JSON.stringify(value));
  const ordered = value => Array.isArray(value) ? value.map(ordered)
    : value && typeof value === 'object'
      ? Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])])) : value;
  const same = (a, b) => JSON.stringify(ordered(a)) === JSON.stringify(ordered(b));
  const scoped = (a, b) => !!a && !!b && SCOPE.every(key => typeof a[key] === 'string' && a[key] && a[key] === b[key]);
  const normalized = text => text.trim().replace(/\s+/g, ' ');
  const length = text => [...text].length;
  const finite = value => typeof value === 'number' && Number.isFinite(value) && value > 0;

  function newId(prefix) {
    const uuid = global.TLSBrowserCompat && typeof global.TLSBrowserCompat.uuid === 'function'
      ? global.TLSBrowserCompat.uuid()
      : global.crypto && typeof global.crypto.randomUUID === 'function'
        ? global.crypto.randomUUID()
        : String(Date.now()) + '-' + Math.random().toString(16).slice(2);
    return prefix + uuid;
  }

  function parseKeywords(value) {
    const raw = Array.isArray(value) ? value : String(value == null ? '' : value).split(/[,，、;；\n]+/);
    const out = [];
    for (const item of raw) {
      if (typeof item !== 'string') throw Error('匹配词必须是文字。');
      const term = normalized(item);
      if (!term) continue;
      if (length(term) > 32) throw Error('每个匹配词不能超过 32 个字符。');
      if (!out.includes(term)) out.push(term);
    }
    if (out.length > 16) throw Error('匹配词最多 16 个。');
    return out;
  }

  function goalFields(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)
      || Object.keys(value).length !== FIELDS.length || FIELDS.some(key => !Object.hasOwn(value, key))) {
      throw Error('目标字段不完整。');
    }
    const out = { ...value };
    for (const [key, max, empty] of [['title', 60, false], ['category', 24, false],
      ['next_step', 100, true], ['note', 160, true]]) {
      if (typeof out[key] !== 'string' || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(out[key])) {
        throw Error('请填写有效的目标文字。');
      }
      out[key] = normalized(out[key]);
      if ((!empty && !out[key]) || length(out[key]) > max) throw Error('请检查目标名称、类别、下一步或备注的长度。');
    }
    if (CREATIVE.some(marker => out.category.includes(marker))) {
      throw Error('创作型目标请继续使用创作项目，这里只管理非创作型个人目标。');
    }
    for (const [key, low, high] of [['auto_step', 1, 50], ['stall_days', 1, 30], ['share_cooldown_hours', 1, 168]]) {
      if (!Number.isFinite(out[key]) || out[key] < low || out[key] > high) {
        throw Error('自动步长须为 1～50、停滞天数 1～30、分享冷却 1～168 小时。');
      }
    }
    if (!Number.isSafeInteger(out.auto_step) || !Number.isSafeInteger(out.stall_days)) {
      throw Error('自动步长和停滞天数必须是整数。');
    }
    out.keywords = parseKeywords(out.keywords);
    return out;
  }

  function logEntry(entry) {
    if (!entry || typeof entry !== 'object' || !finite(entry.ts) || !Number.isFinite(entry.progress)
      || !Number.isSafeInteger(entry.progress) || entry.progress < 0 || entry.progress > 100
      || !LOG_LABEL[entry.kind] || !EVIDENCE_LABEL[entry.evidence_kind]
      || typeof entry.evidence !== 'string' || length(entry.evidence) > 160) {
      throw Error('推进记录不完整。');
    }
    return clone(entry);
  }

  function pendingShare(value) {
    if (value === null || value === undefined) return null;
    if (typeof value !== 'object' || !SHARE_LABEL[value.kind] || !Number.isSafeInteger(value.milestone)
      || value.milestone < 0 || value.milestone > 100 || typeof value.evidence !== 'string'
      || !EVIDENCE_LABEL[value.evidence_kind] || !finite(value.at)) {
      throw Error('待分享标记不完整。');
    }
    return clone(value);
  }

  function record(row, scope) {
    if (!row || !/^goal\.[a-f0-9]{64}$/.test(row.id) || !Number.isSafeInteger(row.revision) || row.revision < 1
      || !scoped(row.scope, scope) || typeof row.archived !== 'boolean' || !STATUSES.includes(row.status)
      || !Number.isSafeInteger(row.progress) || row.progress < 0 || row.progress > 100
      || !finite(row.created_at) || !finite(row.last_activity_at) || !finite(row.last_progress_at)) {
      throw Error('后台目标记录不完整或范围不一致，未用于编辑。');
    }
    if (!same(goalFields(row.fields), row.fields)) throw Error('后台目标字段格式不一致。');
    if (!Array.isArray(row.logs) || row.logs.length > 24) throw Error('推进记录超出边界。');
    row.logs.forEach(logEntry);
    pendingShare(row.pending_share);
    if (!row.provenance || !['user_explicit', 'legacy_import'].includes(row.provenance.kind)) {
      throw Error('目标来源标记无效。');
    }
    return clone(row);
  }

  function formOf(row) {
    const fields = row.fields;
    return { fields: { ...fields, keywords: [...fields.keywords] }, progress: row.progress };
  }

  function describeFields(f) {
    return '类别：' + f.category + '\n下一步：' + (f.next_step || '尚未指定')
      + '\n备注：' + (f.note || '无') + '\n匹配词：' + (f.keywords.length ? f.keywords.join('、') : '（无）')
      + '\n自动步长：' + f.auto_step + ' · 停滞天数：' + f.stall_days + ' · 分享冷却：' + f.share_cooldown_hours + ' 小时';
  }

  function message(error) {
    return ({
      400: '输入未通过检查，请核对字段或迁移文件。',
      401: '后台登录已过期，请重新登录后核查原操作。',
      403: '当前完整范围或确认项未获准，请核对所选用户、角色和会话。',
      404: '记录已不存在，请刷新列表。',
      409: '记录或预览已有变化；草稿已保留，请读取当前版本后再决定。',
      503: '目标服务正在重载或存储结果尚未确认。'
    })[Number(error && (error.status || error.statusCode))] || '连接或响应未确认，请核查当前记录。';
  }

  function mount(root, { api, deadlineMs = 20000 }) {
    if (root.__personalGoals) return root.__personalGoals;
    const style = document.getElementById('personal-goals-styles');
    if (style) style.media = 'all';
    root.innerHTML = `<div class="goals-workspace">
<section class="panel">
<div class="panel-head"><h2>个人目标与日常推进</h2><button type="button" data-goal-action="new" class="primary">新建目标</button></div>
<p data-goal-scope class="hint"></p>
<p class="hint goals-boundary">管理选定会话中角色自己的非创作型目标（生活、学习、习惯）。这里维护定义、迁移资料与手动进度；自动推进和分享请查看日常计划的实际运行状态。保存目标不代表活动已执行或消息已发送。</p>
<div class="goals-toolbar">
<input type="search" data-goal-search placeholder="查找标题、类别、下一步或匹配词" aria-label="查找个人目标">
<select data-goal-status aria-label="按状态筛选"><option value="">全部状态</option><option value="active">进行中</option><option value="paused">已暂停</option><option value="completed">已完成</option><option value="abandoned">已放弃</option></select>
<button type="button" data-goal-action="refresh">刷新</button>
<button type="button" data-goal-action="export">导出目标</button>
</div>
<label class="switch-label"><input type="checkbox" data-goal-archived>包含归档</label>
<p data-goal-status-line class="goals-status" role="status" aria-live="polite"></p>
<div data-goal-list class="goals-list"></div>
<div class="goals-pager"><button type="button" data-goal-action="prev">上一页</button><span data-goal-range></span><button type="button" data-goal-action="next">下一页</button></div>
</section>
<section class="panel" data-goal-editor>
<div class="panel-head"><h2 data-goal-heading>目标详情</h2><span data-goal-badge class="tag">尚未选择</span></div>
<p data-goal-editor-scope class="hint"></p>
<p data-goal-source class="goals-source"></p>
<form data-goal-form>
<fieldset class="goals-fields" disabled>
<label class="full">目标名称<input data-goal-field="title" maxlength="60" required></label>
<label>类别<input data-goal-field="category" maxlength="24" required placeholder="生活 / 学习 / 习惯"></label>
<label>当前进度（%）<input data-goal-progress type="number" min="0" max="100" step="1"></label>
<label>自动步长<input data-goal-field="auto_step" type="number" min="1" max="50" step="1" required></label>
<label>停滞天数<input data-goal-field="stall_days" type="number" min="1" max="30" step="1" required></label>
<label>分享冷却（小时）<input data-goal-field="share_cooldown_hours" type="number" min="1" max="168" step="0.5" required></label>
<label class="full">下一步<input data-goal-field="next_step" maxlength="100"></label>
<label class="full">备注<textarea data-goal-field="note" maxlength="160"></textarea></label>
<label class="full">匹配词（逗号或换行分隔，最多 16 个）<textarea data-goal-field="keywords" maxlength="900"></textarea></label>
</fieldset>
<div class="goals-buttons">
<button type="button" data-goal-action="edit" hidden>编辑</button>
<button type="button" data-goal-action="save" class="primary" hidden>保存</button>
<button type="button" data-goal-action="cancel" hidden>取消</button>
<button type="button" data-goal-action="check" hidden>核查原请求</button>
<button type="button" data-goal-action="retry" hidden>按原请求重试</button>
<button type="button" data-goal-action="pause" hidden>暂停</button>
<button type="button" data-goal-action="resume" hidden>恢复</button>
<button type="button" data-goal-action="complete" hidden>标记完成</button>
<button type="button" data-goal-action="abandon" hidden>放弃</button>
<button type="button" data-goal-action="archive" hidden>归档</button>
<button type="button" data-goal-action="restore" hidden>恢复归档</button>
</div>
<div data-goal-confirm class="goals-confirm" hidden><span data-goal-confirm-text></span><button type="button" data-goal-action="confirm-state" class="primary">确认</button><button type="button" data-goal-action="cancel-state">取消</button></div>
<p data-goal-editor-line class="goals-status" role="status" aria-live="polite"></p>
<p data-goal-comparison class="goals-comparison" hidden></p>
<h3>推进记录</h3>
<div data-goal-history class="goals-history"></div>
<p data-goal-share class="hint"></p>
</form>
<details class="goals-import"><summary>旧 PC 个人目标迁移预览（只读）</summary>
<p class="hint">预览不写入。只有全部记录都明确归属且可映射时才能确认迁移；歧义、缺归属、冲突与不可安全迁移的记录必须人工处理。</p>
<input type="file" data-goal-file accept="application/json,.json">
<p data-goal-import-meta class="hint"></p>
<button type="button" data-goal-action="preview">只读预览</button>
<div data-goal-import-items class="goals-import-items"></div>
<div data-goal-import-preview class="goals-import-items"></div>
<label class="switch-label"><input type="checkbox" data-goal-owner>我确认这些记录属于当前用户、角色和会话，并明确授权迁移</label>
<button type="button" data-goal-action="import">确认迁移</button>
<button type="button" data-goal-action="clear-import">清空</button>
<p data-goal-import-line class="goals-status" role="status" aria-live="polite"></p>
</details>
</section></div>`;
    const $ = selector => root.querySelector(selector);
    const action = name => $('[data-goal-action="' + name + '"]');
    const field = name => $('[data-goal-field="' + name + '"]');
    const states = new Map();
    let scope = null, current = null, epoch = 0;
    const newState = () => ({
      rows: [], loaded: false, loading: false, loadToken: 0, query: '', status: '', archived: false,
      page: 0, editorToken: 0, e: null,
      t: { payload: null, preview: null, pending: null, busy: false }
    });
    const node = (tag, text, cls) => {
      const element = document.createElement(tag);
      if (text !== undefined) element.textContent = String(text);
      if (cls) element.className = cls;
      return element;
    };
    const scopeText = () => scope
      ? '用户 ' + scope.user_id + ' · 角色 ' + scope.character_id + ' · 会话 ' + scope.session_id + ' · ' + scope.platform + ' / ' + scope.bot_id
      : '请从上方选择完整用户、角色和会话范围。';
    const status = (selector, text, error = false) => {
      const element = $(selector);
      element.textContent = text;
      element.dataset.error = String(error);
    };
    const alive = (state, token) => state === current && token === epoch;
    async function call(method, path, payload) {
      let timer;
      try {
        return await Promise.race([
          Promise.resolve().then(() => api(method, 'page/personal-goals/' + path, payload)),
          new Promise((_, reject) => { timer = setTimeout(() => reject(Error('deadline')), deadlineMs); })
        ]);
      } finally { clearTimeout(timer); }
    }
    function setForm(value) {
      for (const key of FIELDS) {
        const element = field(key);
        if (key === 'keywords') element.value = Array.isArray(value.fields.keywords) ? value.fields.keywords.join('\n') : value.fields.keywords;
        else element.value = String(value.fields[key]);
      }
      $('[data-goal-progress]').value = String(value.progress);
    }
    // Keep the actual editable strings, including temporarily invalid numbers,
    // with their own scope. Validation belongs to Save, not scope switching.
    function captureDraft() {
      return {fields: Object.fromEntries(FIELDS.map(key => [key, field(key).value])),
        progress: $('[data-goal-progress]').value};
    }
    function readForm() {
      const fields = {};
      for (const key of FIELDS) {
        const element = field(key);
        fields[key] = ['auto_step', 'stall_days', 'share_cooldown_hours'].includes(key)
          ? (element.value.trim() === '' ? NaN : Number(element.value))
          : element.value;
      }
      const progress = $('[data-goal-progress]').value.trim() === ''
        ? 0 : Number($('[data-goal-progress]').value);
      if (!Number.isSafeInteger(progress) || progress < 0 || progress > 100) {
        throw Error('当前进度必须是 0～100 的整数。');
      }
      return { fields: goalFields(fields), progress };
    }
    function changed(e) { try { return !e.base || !same(readForm(), formOf(e.base)); } catch { return true; } }
    function source(row) {
      const p = row.provenance;
      return (p.kind === 'user_explicit' ? '来源：人工建立' : '来源：PC 迁移 · 人工确认归属')
        + '\n来源引用：' + (p.source_ref || '未提供')
        + (p.source_id ? '\n原记录：' + p.source_id : '')
        + (p.source_sha256 ? '\n来源文件 SHA256：' + p.source_sha256 : '')
        + '\n建立时间：' + new Date(row.created_at * 1000).toLocaleString()
        + ' · 最近读取版本：v' + row.revision;
    }
    function drawHistory(row) {
      const area = $('[data-goal-history]');
      area.replaceChildren();
      $('[data-goal-share]').textContent = row && row.pending_share
        ? '待分享候选：' + SHARE_LABEL[row.pending_share.kind] + '（进度 ' + row.pending_share.milestone
          + '%）。这只是留存的候选标记；本批未接自动消费或发送，也不证明已经送达。'
        : '当前没有待释放的分享理由。';
      if (!row) return;
      if (!row.logs.length) { area.append(node('p', '尚无推进记录。', 'empty')); return; }
      for (const entry of [...row.logs].reverse()) {
        const card = node('article', undefined, 'goals-history-item');
        card.append(node('h4', (LOG_LABEL[entry.kind] || entry.kind) + ' · ' + entry.progress + '%'),
          node('p', new Date(entry.ts * 1000).toLocaleString() + ' · ' + (EVIDENCE_LABEL[entry.evidence_kind] || '来源不明'), 'hint'),
          node('p', entry.evidence || '（无说明）'));
        area.append(card);
      }
    }
    function editor() {
      const e = current && current.e;
      root.dataset.goalPhase = !scope ? 'no-scope' : e && e.busy ? 'saving'
        : e && e.pending ? 'uncertain' : e && e.conflict ? 'conflict' : (e && e.mode) || 'ready';
      $('fieldset').disabled = !e || e.mode === 'view' || e.busy || !!e.pending || !!e.conflict;
      $('[data-goal-heading]').textContent = e ? (e.base ? '目标详情' : '新建目标') : '目标详情';
      $('[data-goal-badge]').textContent = e && e.base
        ? (e.base.archived ? '已归档 · ' : '') + (STATUS_LABEL[e.base.status] || e.base.status) + ' · v' + e.base.revision
        : '尚未保存';
      $('[data-goal-editor-scope]').textContent = scopeText();
      $('[data-goal-source]').textContent = e && e.base ? source(e.base) : '人工建立或迁移后保留原始创建时间与来源。';
      for (const name of ['edit', 'save', 'cancel', 'check', 'retry', 'pause', 'resume', 'complete',
        'abandon', 'archive', 'restore']) action(name).hidden = true;
      const base = e && e.base;
      if (e) {
        const locked = e.busy || !!e.pending || !!e.conflict;
        action('edit').hidden = e.mode !== 'view' || !base || base.archived;
        action('save').hidden = e.mode === 'view';
        action('cancel').hidden = e.mode === 'view';
        action('save').disabled = locked;
        action('cancel').disabled = e.busy || !!e.pending;
        action('check').hidden = !base && !(e.pending && e.pending.kind === 'create');
        action('check').textContent = e.pending && e.pending.kind === 'create' ? '核对原新建请求' : '核查原请求';
        action('check').disabled = e.busy;
        action('retry').hidden = !e.pending || !base;
        action('retry').disabled = e.busy;
        action('retry').textContent = e.pending && e.pending.kind === 'create'
          ? '用原请求核查新建' : '按原版本重试并核对';
        if (e.mode === 'view' && !e.pending && base) {
          if (base.archived) {
            action('restore').hidden = false;
          } else {
            action('archive').hidden = false;
            if (base.status === 'active') action('pause').hidden = false;
            if (['paused', 'abandoned', 'completed'].includes(base.status)) action('resume').hidden = false;
            if (base.status !== 'completed') action('complete').hidden = false;
            if (base.status !== 'abandoned') action('abandon').hidden = false;
          }
          for (const name of ['pause', 'resume', 'complete', 'abandon', 'archive', 'restore']) {
            if (!action(name).hidden) action(name).disabled = locked;
          }
        }
      }
      action('new').disabled = !scope || !current || current.loading || !!(e && (e.busy || e.pending));
      action('export').disabled = !scope || (current && current.loading);
      action('refresh').disabled = !scope || (current && current.loading);
      $('[data-goal-confirm]').hidden = !(e && e.confirm);
      action('confirm-state').disabled = !!(e && e.busy);
      action('cancel-state').disabled = !!(e && e.busy);
      if (e && e.confirm) {
        $('[data-goal-confirm-text]').textContent = '即将' + e.confirm.label + '：'
          + (base ? base.fields.title : '目标') + '。';
      }
      transferControls();
    }
    function drawList() {
      const state = current, list = $('[data-goal-list]');
      list.replaceChildren();
      if (!state) { list.append(node('p', '尚未选择范围。', 'empty')); return; }
      const q = state.query.toLocaleLowerCase();
      const all = state.rows.filter(row => (state.archived || !row.archived)
        && (!state.status || row.status === state.status)
        && (!q || [row.fields.title, row.fields.category, row.fields.next_step, row.fields.note,
          row.fields.keywords.join(' ')].join(' ').toLocaleLowerCase().includes(q)));
      state.page = Math.min(state.page, Math.max(0, Math.ceil(all.length / PAGE) - 1));
      const rows = all.slice(state.page * PAGE, state.page * PAGE + PAGE);
      for (const row of rows) {
        const card = node('article', undefined, 'goal-card');
        card.dataset.goalId = row.id;
        card.append(node('h3', row.fields.title));
        card.append(node('p', (STATUS_LABEL[row.status] || row.status) + ' · ' + row.fields.category
          + (row.archived ? ' · 已归档' : '') + ' · 来源 ' + (row.provenance.kind === 'legacy_import' ? 'PC 迁移' : '人工建立'), 'hint'));
        const bar = node('div', undefined, 'goal-progress');
        const fill = node('span', undefined, 'goal-progress-fill');
        fill.style.width = row.progress + '%';
        bar.append(fill, node('strong', row.progress + '%'));
        card.append(bar);
        card.append(node('p', '下一步：' + (row.fields.next_step || '尚未指定')));
        if (row.fields.note) card.append(node('p', row.fields.note, 'hint'));
        card.append(node('p', '匹配词：' + (row.fields.keywords.length ? row.fields.keywords.join('、') : '（无）')
          + ' · 最近活动：' + new Date(row.last_activity_at * 1000).toLocaleString(), 'hint'));
        if (row.pending_share) {
          card.append(node('p', '待分享候选：' + SHARE_LABEL[row.pending_share.kind] + '（不会自动发送）', 'hint'));
        }
        const open = node('button', '查看 / 编辑');
        open.type = 'button';
        open.addEventListener('click', () => select(row.id));
        const actions = node('div', undefined, 'actions');
        actions.append(open);
        card.append(actions);
        list.append(card);
      }
      if (!rows.length) list.append(node('p', state.loaded ? '当前没有匹配的个人目标。' : '尚未读取个人目标。', 'empty'));
      $('[data-goal-range]').textContent = all.length
        ? '匹配 ' + all.length + ' 条 · 第 ' + (state.page + 1) + ' / ' + Math.ceil(all.length / PAGE) + ' 页'
        : '无匹配记录';
      action('prev').disabled = !state.page;
      action('next').disabled = (state.page + 1) * PAGE >= all.length;
    }
    async function load() {
      if (!scope || !current) return;
      const state = current, token = epoch, at = { ...scope }, loadToken = ++state.loadToken;
      state.loading = true;
      editor();
      status('[data-goal-status-line]', '正在读取本范围全部目标…');
      try {
        const rows = [];
        let total = null;
        for (let offset = 0; offset < MAX_GOALS; offset += 100) {
          const response = await call('GET', 'list', { ...at, include_archived: true, limit: 100, offset });
          if (!alive(state, token) || loadToken !== state.loadToken) return;
          if (!scoped(response.scope, at) || !Array.isArray(response.records)
            || !Number.isSafeInteger(response.total) || response.total < 0 || response.total > MAX_GOALS
            || response.limit !== 100 || response.offset !== offset || response.records.length > 100
            || (total !== null && response.total !== total)) throw Error('list');
          total = response.total;
          rows.push(...response.records.map(row => record(row, at)));
          if (rows.length >= total) break;
          if (response.records.length !== 100) throw Error('list truncated');
        }
        if (rows.length !== total || new Set(rows.map(row => row.id)).size !== rows.length) throw Error('list inconsistent');
        state.rows = rows;
        state.loaded = true;
        drawList();
        status('[data-goal-status-line]', '已读取本范围 ' + rows.length + ' 条（含归档）；搜索与状态筛选覆盖全部已读目标。');
      } catch (error) {
        if (alive(state, token) && loadToken === state.loadToken) {
          status('[data-goal-status-line]', message(error) + ' 原有列表保留为上次读取结果。', true);
        }
      } finally {
        if (loadToken === state.loadToken) state.loading = false;
        if (alive(state, token) && loadToken === state.loadToken) editor();
      }
    }
    function mayLeave() {
      const e = current && current.e;
      if (e && (e.busy || e.pending || (e.mode !== 'view' && changed(e)))) {
        status('[data-goal-editor-line]', '当前草稿或原请求已保留，请先保存、取消编辑或核查原请求，再选择另一条目标。', true);
        return false;
      }
      return true;
    }
    async function select(id) {
      if (!scope || !mayLeave()) return;
      const state = current, token = epoch, at = { ...scope }, editorToken = ++state.editorToken;
      status('[data-goal-editor-line]', '正在按记录读取…');
      try {
        const row = record((await call('GET', 'detail', { ...at, id })).record, at);
        if (row.id !== id) throw Error('detail identity');
        if (!alive(state, token) || state.editorToken !== editorToken) return;
        state.e = { base: row, mode: 'view', busy: false };
        setForm(formOf(row));
        drawHistory(row);
        $('[data-goal-comparison]').hidden = true;
        status('[data-goal-editor-line]', '已读取当前记录；编辑和状态变更都会校验版本。');
        editor();
      } catch (error) {
        if (alive(state, token) && state.editorToken === editorToken) {
          status('[data-goal-editor-line]', message(error), true);
        }
      }
    }
    function newGoal() {
      if (!scope || !mayLeave()) return;
      current.editorToken++;
      current.e = { base: null, mode: 'new', busy: false };
      setForm({
        fields: {
          title: '', category: '生活', auto_step: 10, stall_days: 3, share_cooldown_hours: 12,
          next_step: '', note: '', keywords: []
        },
        progress: 0
      });
      drawHistory(null);
      $('[data-goal-comparison]').hidden = true;
      status('[data-goal-editor-line]', '填写目标定义；保存会校验版本并在之后独立回读。');
      editor();
      field('title').focus();
    }
    async function verify(saved, at) {
      const read = record((await call('GET', 'detail', { ...at, id: saved.id })).record, at);
      if (read.id !== saved.id || read.revision !== saved.revision || read.archived !== saved.archived
        || read.status !== saved.status || read.progress !== saved.progress
        || !same(read.fields, saved.fields)) throw Error('readback mismatch');
      return read;
    }
    async function write(pending) {
      const state = current, e = state.e, token = epoch, at = { ...scope };
      e.busy = true;
      pending = clone(pending);
      e.pending = pending;
      e.confirm = null;
      editor();
      status('[data-goal-editor-line]', '正在保存，随后独立读取当前记录…');
      let accepted = false;
      try {
        const response = await call('POST', pending.kind, pending.body);
        accepted = true;
        const saved = record(response.record, at);
        if (pending.body.id && saved.id !== pending.body.id) throw Error('write identity');
        if (pending.body.fields && !same(saved.fields, pending.body.fields)) throw Error('write mismatch');
        if (Number.isInteger(pending.body.progress) && saved.progress !== pending.body.progress) throw Error('write progress');
        if (pending.target && saved.status !== pending.target) throw Error('write status');
        if (typeof pending.expectArchived === 'boolean' && saved.archived !== pending.expectArchived) {
          throw Error('write archive');
        }
        const row = await verify(saved, at);
        if (!alive(state, token) || state.e !== e) return;
        e.base = row;
        e.mode = 'view';
        e.pending = null;
        e.conflict = false;
        setForm(formOf(row));
        drawHistory(row);
        $('[data-goal-comparison]').hidden = true;
        status('[data-goal-editor-line]', '已保存，并独立回读确认当前记录。目标不会因此获得发送权限。');
        await load();
      } catch (error) {
        if (!alive(state, token) || state.e !== e) return;
        const code = Number(error && (error.status || error.statusCode));
        if (!accepted && [400, 401, 403, 404, 409].includes(code)) {
          e.pending = null;
          e.conflict = code === 409;
          status('[data-goal-editor-line]', message(error) + ' 输入仍保留。', true);
        } else {
          status('[data-goal-editor-line]', '保存结果未知或回读未确认；输入和原请求已保留。请核查原请求，不要重复新建。 ' + message(error), true);
        }
      } finally {
        e.busy = false;
        if (alive(state, token) && state.e === e) editor();
      }
    }
    async function save() {
      const e = current && current.e;
      if (!e || e.busy || e.pending || e.conflict || e.mode === 'view') return;
      try {
        const draft = readForm();
        // Match the service create contract before freezing the original body.
        if (!e.base && draft.fields.keywords.length === 0) draft.fields.keywords = [draft.fields.title];
        setForm(draft);
        const body = e.base
          ? { scope: { ...scope }, id: e.base.id, expected_revision: e.base.revision, fields: draft.fields, progress: draft.progress }
          : { scope: { ...scope }, request_id: newId('goal.'), fields: draft.fields, progress: draft.progress };
        await write({ kind: e.base ? 'update' : 'create', body, id: e.base ? e.base.id : undefined });
      } catch (error) {
        status('[data-goal-editor-line]', error.message, true);
      }
    }
    async function changeStatus(kind) {
      const e = current && current.e;
      if (!e || !e.base || e.busy || e.pending) return;
      const target = { pause: 'paused', resume: 'active', complete: 'completed', abandon: 'abandoned' }[kind];
      await write({
        kind, target,
        body: { scope: { ...scope }, id: e.base.id, expected_revision: e.base.revision }
      });
    }
    async function changeArchive(kind) {
      const e = current && current.e;
      if (!e || !e.base || e.busy || e.pending) return;
      await write({
        kind, expectArchived: kind === 'archive',
        body: { scope: { ...scope }, id: e.base.id, expected_revision: e.base.revision }
      });
    }
    async function checkCreate() {
      const state = current, e = state && state.e, pending = e && e.pending;
      if (!scope || !e || e.base || e.busy || !pending || pending.kind !== 'create') return;
      const token = epoch, at = { ...scope }, requestId = pending.body.request_id;
      e.busy = true;
      editor();
      try {
        const response = await call('GET', 'export', { ...at, include_archived: true });
        const value = response.export;
        if (!value || value.schema !== 'tls.native.personal_goals.export.v1' || !scoped(value.scope, at)
          || value.definitions_only !== true || value.creates_send_permission !== false
          || !Array.isArray(value.records) || value.records.length !== value.total
          || value.records.length > MAX_GOALS) throw Error('request readback');
        const rows = value.records.map(row => record(row, at));
        const matched = rows.filter(row => row.provenance.kind === 'user_explicit'
          && row.provenance.source_ref === requestId);
        if (!alive(state, token) || state.e !== e || e.pending !== pending) return;
        if (!matched.length) {
          status('[data-goal-editor-line]', '尚未找到原新建请求的目标；旧请求仍可能完成。原参数保留，只继续只读核对，不另建一条。', true);
          return;
        }
        if (matched.length !== 1) throw Error('ambiguous request source');
        const row = await verify(matched[0], at);
        if (!alive(state, token) || state.e !== e || e.pending !== pending) return;
        e.base = row;
        e.pending = null;
        e.conflict = false;
        e.mode = 'view';
        setForm(formOf(row));
        drawHistory(row);
        status('[data-goal-editor-line]', '已按原新建请求核对当前目标，没有重新提交；如有后续编辑，以当前记录为准。');
        await load();
      } catch (error) {
        if (alive(state, token) && state.e === e) status('[data-goal-editor-line]', message(error) + ' 原新建请求与草稿保留，没有重发。', true);
      } finally {
        e.busy = false;
        if (alive(state, token) && state.e === e) editor();
      }
    }
    async function check() {
      const state = current, e = state && state.e;
      if (!e || e.busy) return;
      if (!e.base && e.pending && e.pending.kind === 'create') return checkCreate();
      if (!e.base) return;
      const token = epoch, at = { ...scope };
      e.busy = true;
      editor();
      try {
        const row = record((await call('GET', 'detail', { ...at, id: e.base.id })).record, at);
        if (row.id !== e.base.id) throw Error('detail identity');
        if (!alive(state, token) || state.e !== e) return;
        const pending = e.pending;
        const sameFields = pending && pending.body.fields && same(row.fields, pending.body.fields);
        const sameProgress = pending && Number.isInteger(pending.body.progress)
          && row.progress === pending.body.progress && row.revision > pending.body.expected_revision;
        const sameStatus = pending && pending.target && row.status === pending.target
          && row.revision >= pending.body.expected_revision;
        const sameArchive = pending && typeof pending.expectArchived === 'boolean'
          && row.archived === pending.expectArchived
          && row.revision > pending.body.expected_revision;
        if (pending && (sameFields && row.revision > pending.body.expected_revision
          || sameProgress || sameStatus || sameArchive)) {
          e.base = row;
          e.pending = null;
          e.conflict = false;
          e.mode = 'view';
          setForm(formOf(row));
          drawHistory(row);
          status('[data-goal-editor-line]', '已核对当前记录与目标一致，没有重复提交。');
        } else if (pending && row.revision === pending.body.expected_revision) {
          status('[data-goal-editor-line]', '当前记录尚未出现目标变化；旧请求仍可能稍后完成。原请求继续保留，请稍后再次核查。', true);
        } else {
          e.base = row;
          e.pending = null;
          e.conflict = false;
          e.mode = 'view';
          setForm(formOf(row));
          drawHistory(row);
          $('[data-goal-comparison]').hidden = false;
          $('[data-goal-comparison]').textContent = '后台当前值：v' + row.revision + ' · '
            + (STATUS_LABEL[row.status] || row.status) + ' · ' + row.progress + '%\n' + describeFields(row.fields);
          status('[data-goal-editor-line]', '已读取后台当前版本；草稿已按当前版本回填，请比较后再决定。', true);
        }
        editor();
      } catch (error) {
        if (alive(state, token)) status('[data-goal-editor-line]', message(error) + ' 未丢弃草稿或原请求。', true);
      } finally {
        e.busy = false;
        if (alive(state, token) && state.e === e) editor();
      }
    }
    function transferControls() {
      const t = current && current.t;
      const deny = !scope || !t || t.busy || !!t.pending;
      for (const element of root.querySelectorAll('[data-goal-file],[data-goal-owner]')) element.disabled = deny;
      action('preview').disabled = deny || !(t && t.payload);
      action('clear-import').disabled = deny;
      action('import').disabled = !scope || !t || t.busy || !t.preview
        || !$('[data-goal-owner]').checked || !t.preview.records.length
        || t.preview.records.some(row => !['ready', 'existing'].includes(row.status));
      action('import').textContent = t && t.pending ? '用原请求核查迁移' : '确认迁移';
    }
    const IMPORT_LABEL = {
      ready: '可迁移', existing: '已存在（不覆盖）', unassigned: '缺归属', foreign_scope: '属于其他范围',
      unsafe_domain: '创作型，不可迁移', ambiguous: '歧义，需人工决定', invalid: '内容无效',
      conflict: '来源已有冲突', duplicate_source_id: '原记录重复'
    };
    function drawImportRows(area, records, withOwner) {
      area.replaceChildren();
      for (const row of records) {
        const title = withOwner
          ? ((row.record && row.record.title) || row.source_id)
          : ((row.fields && row.fields.title) || row.source_id || '无效项');
        const card = node('article', undefined, 'goals-import-item');
        card.append(node('h3', title + ' · ' + (withOwner ? '待只读预览' : (IMPORT_LABEL[row.status] || row.status))));
        card.append(node('p', withOwner
          ? '原记录 ' + row.source_id
          : (row.fields ? row.fields.category + ' · ' + row.progress + '%' : '未映射')
            + (row.archived ? ' · 已归档，迁移不会恢复' : ''), 'hint'));
        if (row.issues && row.issues.length) card.append(node('p', row.issues.join('；'), 'hint'));
        if (withOwner) {
          const label = node('label', undefined, 'switch-label');
          const box = node('input');
          box.type = 'checkbox';
          box.checked = scoped(row.target_scope, scope);
          label.append(box, document.createTextNode('明确归属本会话'));
          box.addEventListener('change', () => {
            row.target_scope = box.checked ? { ...scope } : null;
            invalidatePreview();
          });
          card.append(label);
        }
        area.append(card);
      }
    }
    function drawImport() {
      const t = current && current.t;
      $('[data-goal-owner]').checked = !!(t && t.pending);
      $('[data-goal-file]').value = '';
      if (!t || !t.payload) {
        $('[data-goal-import-meta]').textContent = '尚未选择迁移文件。';
        $('[data-goal-import-items]').replaceChildren();
        $('[data-goal-import-preview]').replaceChildren();
        transferControls();
        return;
      }
      const payload = t.payload;
      $('[data-goal-import-meta]').textContent = '来源：' + payload.source_ref + ' · ' + payload.records.length
        + ' 项\n来源文件 SHA256：' + payload.source_sha256;
      drawImportRows($('[data-goal-import-items]'), payload.records, true);
      drawImportRows($('[data-goal-import-preview]'), t.preview ? t.preview.records : [], false);
      transferControls();
    }
    function invalidatePreview() {
      const t = current.t;
      if (t.pending) return;
      t.preview = null;
      $('[data-goal-import-preview]').replaceChildren();
      $('[data-goal-owner]').checked = false;
      status('[data-goal-import-line]', '内容或归属已变化，请重新只读预览。');
      transferControls();
    }
    async function fileChanged() {
      if (!scope || current.t.pending || current.t.busy) return;
      const state = current, token = epoch, file = $('[data-goal-file]').files[0];
      if (!file) return;
      try {
        if (file.size > 288 * 1024) throw Error('文件不能超过 288 KiB。');
        const payload = JSON.parse(await file.text());
        if (!alive(state, token)) return;
        const keys = ['schema', 'source_plugin', 'source_ref', 'source_sha256',
          'source_default_stall_days', 'source_default_share_cooldown_hours', 'records'];
        if (!payload || Object.keys(payload).length !== keys.length || keys.some(key => !Object.hasOwn(payload, key))
          || payload.schema !== 1 || payload.source_plugin !== 'private_companion'
          || typeof payload.source_ref !== 'string' || !payload.source_ref
          || !/^[a-f0-9]{64}$/.test(payload.source_sha256)
          || !Number.isSafeInteger(payload.source_default_stall_days)
          || !Number.isSafeInteger(payload.source_default_share_cooldown_hours)
          || !Array.isArray(payload.records) || payload.records.length < 1 || payload.records.length > 100
          || payload.records.some(item => !item || typeof item.source_id !== 'string'
            || !item.record || typeof item.record !== 'object')) {
          throw Error('请选择带来源标识的 PC 个人目标迁移文件；TLS 导出文件不适用。');
        }
        state.t = { payload: clone(payload), preview: null, pending: null, busy: false };
        drawImport();
        status('[data-goal-import-line]', '文件已读入本页，尚未上传或写入。逐项核对归属后预览。');
      } catch (error) {
        if (alive(state, token)) {
          status('[data-goal-import-line]', error.message || '文件无法读取。', true);
          $('[data-goal-file]').value = '';
        }
      }
    }
    async function preview() {
      const state = current, t = state && state.t;
      if (!scope || !t || !t.payload || t.busy || t.pending) return;
      const token = epoch, at = { ...scope };
      t.busy = true;
      t.preview = null;
      transferControls();
      status('[data-goal-import-line]', '正在只读预览，不会写入…');
      try {
        const result = await call('POST', 'import/preview', { scope: at, payload: t.payload });
        if (!alive(state, token) || state.t !== t) return;
        const value = result.preview;
        if (!value || !scoped(value.scope, at) || !/^[a-f0-9]{64}$/.test(value.preview_sha256)
          || !Array.isArray(value.records) || value.records.length !== t.payload.records.length
          || value.writes !== 0 || value.creates_send_permission !== false) throw Error('preview');
        t.preview = value;
        drawImportRows($('[data-goal-import-preview]'), value.records, false);
        const ready = value.records.filter(row => row.status === 'ready').length;
        const blocked = value.records.length - ready - value.records.filter(row => row.status === 'existing').length;
        status('[data-goal-import-line]', '只读预览完成，尚未写入。' + ready + ' 项可迁移，'
          + (blocked ? blocked + ' 项需人工处理。' : '全部记录可映射。'));
      } catch (error) {
        if (alive(state, token)) status('[data-goal-import-line]', message(error), true);
      } finally {
        t.busy = false;
        if (alive(state, token) && state.t === t) transferControls();
      }
    }
    async function confirmImport() {
      const state = current, t = state && state.t;
      if (!scope || !t || !t.preview || t.busy || !$('[data-goal-owner]').checked
        || t.preview.records.some(row => !['ready', 'existing'].includes(row.status))) return;
      const token = epoch, at = { ...scope };
      if (!t.pending) {
        t.pending = {
          scope: at, payload: clone(t.payload), preview_sha256: t.preview.preview_sha256,
          request_id: newId('goals-import.'), owner_confirmed: true
        };
      }
      t.busy = true;
      transferControls();
      status('[data-goal-import-line]', '正在核对原预览并迁移，随后逐项回读…');
      let accepted = false;
      try {
        const response = await call('POST', 'import/confirm', t.pending);
        accepted = true;
        const result = response.import;
        if (!result || !Array.isArray(result.created_ids) || !Array.isArray(result.existing_ids)
          || !Array.isArray(response.records)) throw Error('import');
        const ids = [...result.created_ids, ...result.existing_ids];
        const expected = t.preview.records.map(row => row.id);
        if (ids.length !== expected.length || new Set(ids).size !== ids.length
          || ids.some(id => !expected.includes(id)) || response.records.length !== ids.length) throw Error('import ids');
        for (const raw of response.records) {
          const row = record(raw, at);
          if (!ids.includes(row.id)) throw Error('foreign record');
          await verify(row, at);
        }
        if (!alive(state, token) || state.t !== t) return;
        t.pending = null;
        t.preview = null;
        drawImport();
        status('[data-goal-import-line]', '已迁移 ' + result.created_ids.length + ' 项，原有 '
          + result.existing_ids.length + ' 项，并独立逐项回读。旧 PC 数据保持原样；未安排发送。');
        await load();
      } catch (error) {
        if (!alive(state, token) || state.t !== t) return;
        const code = Number(error && (error.status || error.statusCode));
        if (!accepted && [400, 401, 403, 404, 409].includes(code)) {
          t.pending = null;
          t.preview = null;
          $('[data-goal-owner]').checked = false;
          $('[data-goal-import-preview]').replaceChildren();
          status('[data-goal-import-line]', message(error) + ' 来源内容保留，请重新预览。', true);
        } else {
          status('[data-goal-import-line]', '迁移结果未知或回读未确认；原内容、预览和请求已保留。再次确认只核查同一请求。 ' + message(error), true);
        }
      } finally {
        t.busy = false;
        if (alive(state, token) && state.t === t) transferControls();
      }
    }
    async function exportGoals() {
      if (!scope) return;
      const state = current, token = epoch, at = { ...scope };
      action('export').disabled = true;
      try {
        const response = await call('GET', 'export', { ...at, include_archived: true });
        if (!alive(state, token)) return;
        const value = response.export;
        if (!value || value.schema !== 'tls.native.personal_goals.export.v1' || !scoped(value.scope, at)
          || value.definitions_only !== true || value.creates_send_permission !== false
          || !Array.isArray(value.records) || value.records.length !== value.total) throw Error('export');
        value.records.forEach(row => record(row, at));
        const blob = new Blob([JSON.stringify(value, null, 2) + '\n'], { type: 'application/json;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = node('a');
        link.href = url;
        link.download = 'TLS-personal-goals.json';
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        status('[data-goal-status-line]', '已生成 ' + value.total + ' 条目标的本地 JSON 留存文件（含归档、推进记录与来源）。此文件不是 PC 迁移格式。');
      } catch (error) {
        if (alive(state, token)) status('[data-goal-status-line]', message(error) + ' 未生成下载。', true);
      } finally {
        if (alive(state, token)) editor();
      }
    }
    $('[data-goal-form]').addEventListener('submit', event => { event.preventDefault(); save(); });
    action('new').addEventListener('click', newGoal);
    action('refresh').addEventListener('click', load);
    action('export').addEventListener('click', exportGoals);
    action('edit').addEventListener('click', () => {
      const state = current;
      if (state && state.e && state.e.base && !state.e.base.archived) {
        state.editorToken++;
        state.e.mode = 'edit';
        editor();
        status('[data-goal-editor-line]', '编辑当前目标；取消会恢复上次读取值。');
      }
    });
    action('cancel').addEventListener('click', () => {
      const state = current, e = state && state.e;
      if (!e || e.busy || e.pending) return;
      if (e.base) {
        setForm(formOf(e.base));
        state.e = { base: e.base, mode: 'view', busy: false };
        drawHistory(e.base);
      } else {
        state.e = null;
        drawHistory(null);
      }
      $('[data-goal-comparison]').hidden = true;
      status('[data-goal-editor-line]', '已取消编辑，未提交草稿。');
      editor();
    });
    action('save').addEventListener('click', save);
    action('check').addEventListener('click', check);
    action('retry').addEventListener('click', () => {
      const e = current && current.e;
      if (e && e.pending && !e.busy) write(e.pending);
    });
    action('pause').addEventListener('click', () => changeStatus('pause'));
    action('resume').addEventListener('click', () => changeStatus('resume'));
    action('complete').addEventListener('click', () => changeStatus('complete'));
    for (const [name, label] of [['abandon', '放弃'], ['archive', '归档'], ['restore', '恢复归档']]) {
      action(name).addEventListener('click', () => {
        const e = current && current.e;
        if (!e || !e.base || e.busy || e.pending) return;
        e.confirm = { kind: name, label };
        editor();
      });
    }
    action('confirm-state').addEventListener('click', () => {
      const e = current && current.e;
      if (!e || !e.confirm || e.busy) return;
      const kind = e.confirm.kind;
      e.confirm = null;
      if (kind === 'abandon') changeStatus('abandon');
      else changeArchive(kind);
    });
    action('cancel-state').addEventListener('click', () => {
      if (current && current.e) { current.e.confirm = null; editor(); }
    });
    action('preview').addEventListener('click', preview);
    action('import').addEventListener('click', confirmImport);
    action('clear-import').addEventListener('click', () => {
      if (current && !current.t.busy && !current.t.pending) {
        current.t = { payload: null, preview: null, pending: null, busy: false };
        drawImport();
        status('[data-goal-import-line]', '已清空迁移内容，未写入。');
      }
    });
    $('[data-goal-file]').addEventListener('change', fileChanged);
    $('[data-goal-owner]').addEventListener('change', transferControls);
    $('[data-goal-search]').addEventListener('input', event => {
      if (current) { current.query = event.target.value; current.page = 0; drawList(); }
    });
    $('[data-goal-status]').addEventListener('change', event => {
      if (current) { current.status = event.target.value; current.page = 0; drawList(); }
    });
    $('[data-goal-archived]').addEventListener('change', event => {
      if (current) { current.archived = event.target.checked; current.page = 0; drawList(); }
    });
    for (const [name, step] of [['prev', -1], ['next', 1]]) {
      action(name).addEventListener('click', () => { current.page += step; drawList(); });
    }
    $('[data-goal-form]').addEventListener('input', () => {
      if (current && current.e) current.e.draft = captureDraft();
    });
    function setScope(value) {
      if (scoped(scope, value)) return;
      if (current && current.e && current.e.mode !== 'view') current.e.draft = captureDraft();
      scope = value && SCOPE.every(key => typeof value[key] === 'string' && value[key])
        ? Object.fromEntries(SCOPE.map(key => [key, value[key]])) : null;
      epoch++;
      current = scope ? (states.get(JSON.stringify(scope)) || newState()) : null;
      if (scope) states.set(JSON.stringify(scope), current);
      $('[data-goal-scope]').textContent = scopeText();
      $('[data-goal-search]').value = current ? current.query : '';
      $('[data-goal-status]').value = current ? current.status : '';
      $('[data-goal-archived]').checked = current ? current.archived : false;
      const e = current && current.e;
      if (e && e.mode !== 'view' && e.draft && typeof e.draft === 'object') setForm(e.draft);
      else if (e && e.base) setForm(formOf(e.base)); else setForm({
        fields: {
          title: '', category: '生活', auto_step: 10, stall_days: 3, share_cooldown_hours: 12,
          next_step: '', note: '', keywords: []
        },
        progress: 0
      });
      drawHistory(e && e.base ? e.base : null);
      $('[data-goal-comparison]').hidden = true;
      status('[data-goal-editor-line]', e && e.pending ? '已保留此范围的原请求，请先核查。'
        : e && e.base ? '已恢复此范围的记录或草稿。' : '选择记录或新建目标。');
      status('[data-goal-status-line]', current && current.loaded ? '已显示上次读取的本范围列表。' : '尚未读取。');
      status('[data-goal-import-line]', current && current.t.pending ? '已保留此范围的迁移原请求，请先核查。' : '');
      drawList();
      drawImport();
      editor();
    }
    function unmount() {
      epoch++;
      current = null;
      scope = null;
      root.replaceChildren();
      delete root.__personalGoals;
      delete root.dataset.goalPhase;
      return true;
    }
    const controller = { setScope, activate() { if (scope) load(); }, newGoal, unmount };
    root.__personalGoals = controller;
    setScope(null);
    editor();
    drawList();
    drawImport();
    return controller;
  }

  function unmount(root) {
    const controller = root && root.__personalGoals;
    return controller ? controller.unmount() : false;
  }

  global.TLSPersonalGoals = Object.freeze({
    mount, unmount, fields: goalFields, keywords: parseKeywords, record,
    labels: Object.freeze({
      status: STATUS_LABEL, log: LOG_LABEL, evidence: EVIDENCE_LABEL, share: SHARE_LABEL
    })
  });
})(window);
