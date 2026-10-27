/* Three existing background settings, using the console's authenticated API. */
(function (root, factory) {
  'use strict';
  const exported = factory();
  if (typeof module === 'object' && module.exports) module.exports = exported;
  else root.TLSContextSettings = exported;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const fields = Object.freeze([
    {key: 'presence_context_enabled', label: '在对话中显示可用背景', type: 'checkbox',
      help: '使用现有权限允许的环境背景；关闭后仍保留记忆与其他功能的原有设置。'},
    {key: 'presence_context_max_chars', label: '背景文字上限（字）', type: 'number', min: 160, max: 1200,
      help: '160～1200 字。限制背景篇幅，不是整条回复的长度。'},
    {key: 'presence_repeat_seconds', label: '相同重要背景的自动重述间隔（秒）', type: 'number', min: 30, max: 3600,
      help: '30～3600 秒；300 秒为 5 分钟。减少相同重要背景的自动重述；用户主动问及或请求重试时仍可使用背景。不改变提醒或主动消息的冷却。'}
  ]);
  const keys = fields.map(field => field.key);
  const copy = value => JSON.parse(JSON.stringify(value));
  const equal = (a, b) => keys.every(key => a[key] === b[key]);
  function parsed(values) {
    const result = {}, errors = {};
    for (const field of fields) {
      const value = values[field.key];
      if (field.type === 'checkbox') {
        if (typeof value !== 'boolean') errors[field.key] = '请选择开启或关闭。';
        else result[field.key] = value;
      } else {
        const number = typeof value === 'number' ? value : /^\d+$/.test(value) ? Number(value) : NaN;
        if (!Number.isSafeInteger(number) || number < field.min || number > field.max)
          errors[field.key] = '请输入 ' + field.min + '～' + field.max + ' 的整数。';
        else result[field.key] = number;
      }
    }
    return {values: result, errors, valid: !Object.keys(errors).length};
  }
  function snapshot(value) {
    if (typeof value?.values?.presence_context_max_chars !== 'number'
        || typeof value?.values?.presence_repeat_seconds !== 'number') throw Error('Invalid settings numeric types');
    const validation = parsed(value?.values || {});
    if (!validation.valid || typeof value?.revision !== 'string' || !/^[0-9a-f]{64}$/.test(value.revision)
        || typeof value.writable !== 'boolean') throw Error('Invalid settings response');
    return {values: validation.values, revision: value.revision, writable: value.writable,
      presenceEnabled: typeof value.readonly?.presence_layer_enabled === 'boolean'
        ? value.readonly.presence_layer_enabled : null};
  }
  function message(error) {
    return ({400: '输入未通过检查，请核对范围。', 401: '登录已过期，请重新登录管理后台。',
      403: '后台拒绝了此操作，请核对管理员登录。', 409: '后台设置已被更新，输入已保留，请先读取当前设置。',
      503: '配置服务暂不可用。'})[Number(error?.status || error?.statusCode)] || '连接或读取未完成。';
  }
  function createController(api, changed = () => {}, {timeoutMs = 20000} = {}) {
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120000) throw Error('Invalid request deadline');
    let current = null, draft = {}, touched = new Set(), busy = false, editing = false;
    let phase = 'initial', status = '尚未读取设置。', pending = null, disposed = false;
    const emit = () => { if (!disposed) changed(view()); };
    function request(method, path, payload) {
      let timer;
      // A deadline cannot cancel an already dispatched write. Its late result
      // is ignored; save() keeps the original intent locked for a GET check.
      return Promise.race([Promise.resolve().then(() => api(method, path, payload)),
        new Promise((_, reject) => { timer = setTimeout(() => reject(Error('Request deadline')), timeoutMs); })])
        .finally(() => clearTimeout(timer));
    }
    function view() {
      const check = parsed(draft), dirty = !!current && (!check.valid || !equal(check.values, current.values));
      return {current: current && copy(current), draft: copy(draft), busy, editing, phase, status,
        dirty, errors: editing ? check.errors : {},
        canSave: !!current?.writable && editing && dirty && check.valid && !busy
          && !['uncertain', 'conflict'].includes(phase),
        needsCheck: ['uncertain', 'conflict'].includes(phase)};
    }
    function accept(value, text) {
      current = value; draft = {...value.values}; touched.clear(); pending = null;
      editing = false; phase = 'ready'; status = text;
    }
    async function load() {
      if (busy || disposed) return false;
      if (editing) { status = '编辑中的内容已保留。请先取消编辑，或使用“核对当前设置”。'; emit(); return false; }
      busy = true; status = '正在读取后台设置…'; emit();
      try {
        const result = snapshot(await request('GET', 'page/console/config'));
        if (disposed) return false;
        accept(result, result.writable ? '已读取后台当前值。' : '已读取；当前宿主暂不支持保存设置。');
        return true;
      } catch (error) { if (!disposed) { phase = 'read_error'; status = message(error) + ' 未显示为默认值。'; } return false; }
      finally { busy = false; emit(); }
    }
    function begin() {
      if (busy || editing || pending || !current?.writable || disposed) return false;
      editing = true; phase = 'editing'; status = '正在编辑，尚未保存。'; emit(); return true;
    }
    function update(key, value) {
      if (!editing || busy || !keys.includes(key) || disposed || ['uncertain', 'conflict'].includes(phase)) return false;
      draft[key] = value;
      const check = parsed(draft);
      if (check.values[key] === current.values[key]) touched.delete(key); else touched.add(key);
      status = view().dirty ? '有未保存的修改。' : '表单与最近读取的后台值一致，尚未提交。'; emit(); return true;
    }
    function cancel() {
      if (busy || disposed) return false;
      if (pending) { status = '保存结果尚未确认，请先核对当前设置，再结束编辑。'; emit(); return false; }
      if (!current) return false;
      accept(current, '已取消本次编辑，恢复为最近读取的后台值。'); emit(); return true;
    }
    async function save() {
      if (!view().canSave || disposed) return false;
      const values = parsed(draft).values;
      const changes = Object.fromEntries(keys.filter(key => values[key] !== current.values[key]).map(key => [key, values[key]]));
      pending = {changes, values: {...values}, revision: current.revision};
      busy = true; phase = 'saving'; status = '正在保存，随后重新读取后台当前值…'; emit();
      let postAccepted = false;
      try {
        const saved = snapshot(await request('POST', 'page/console/config/save',
          {changes, expected_revision: pending.revision}));
        postAccepted = true;
        if (disposed) return false;
        phase = 'checking'; status = '后台已返回，正在独立读取当前设置…'; emit();
        const confirmed = snapshot(await request('GET', 'page/console/config'));
        if (disposed) return false;
        if (confirmed.revision !== saved.revision || !equal(confirmed.values, saved.values)
            || Object.entries(changes).some(([key, value]) => confirmed.values[key] !== value))
          throw Error('Settings readback differs');
        accept(confirmed, '已保存，并重新读取后台当前值。实际背景仍取决于来源、权限和后续请求。');
        return true;
      } catch (error) {
        if (!disposed) {
          const code = Number(error?.status || error?.statusCode);
          phase = !postAccepted && [400, 401, 403, 409].includes(code)
            ? (code === 409 ? 'conflict' : 'editing') : 'uncertain';
          if (phase !== 'uncertain') pending = null;
          status = message(error) + (phase === 'uncertain'
            ? ' 保存或回读尚未确认；输入已保留，请先核对当前设置，不要重复提交。'
            : ' 输入已保留，本页面未自动重试。');
        }
        return false;
      } finally { busy = false; emit(); }
    }
    async function reconcile() {
      if (busy || disposed) return false;
      const previousDraft = {...draft}, changedKeys = new Set(touched), originalPending = pending;
      busy = true; status = '正在核对当前设置；本次只读取，不重复保存…'; emit();
      try {
        const latest = snapshot(await request('GET', 'page/console/config'));
        if (disposed) return false;
        if (originalPending && Object.entries(originalPending.changes).every(([key, value]) => latest.values[key] === value)) {
          accept(latest, '已核对当前后台值，与本次修改一致；没有重复提交。');
        } else if (originalPending && latest.revision === originalPending.revision) {
          current = latest; phase = 'uncertain'; editing = true;
          status = '当前仍是原版本；先前请求仍可能完成。输入和原请求保留，请稍后只读核对，不会重新保存。';
        } else {
          current = latest; draft = {...latest.values};
          for (const key of changedKeys) draft[key] = previousDraft[key];
          touched = changedKeys; pending = null; editing = true; phase = 'editing';
          status = originalPending
            ? '当前值与本次修改不同，先前请求仍可能完成。草稿已保留，请核对后再保存，或取消编辑。'
            : '已读取当前后台值。你的修改保留在表单中，请核对差异后再保存，或取消编辑。';
        }
        return true;
      } catch (error) { if (!disposed) status = message(error) + ' 核对未完成，输入仍保留。'; return false; }
      finally { busy = false; emit(); }
    }
    return {view, load, begin, update, cancel, save, reconcile,
      destroy() { disposed = true; }};
  }
  function mountInheritance(target, {api, getScope}) {
    const document = target.ownerDocument, inputs = new Map(), switches = new Map(), actual = new Map();
    let current = null, currentScope = null, currentSignature = '', busy = false, disposed = false, epoch = 0;
    const pending = new Map();
    const full = value => value && ['platform', 'bot_id', 'user_id', 'character_id', 'session_id'].every(k => typeof value[k] === 'string' && value[k]);
    const scopeSignature = () => JSON.stringify(getScope?.() || null);
    const selectionKey = (at = currentScope, selectedLevel = level.value) => selectedLevel + ':' + (selectedLevel === 'global' ? '' : JSON.stringify(at));
    const alive = (turn, signature, local) => !disposed && turn === epoch && (!local || signature === scopeSignature());
    const el = (tag, text, className) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
    const wrapper = el('details', undefined, 'panel'), title = el('summary', '配置继承与局部覆盖');
    wrapper.dataset.contextInheritance = 'panel';
    const intro = el('p', '背景显示按默认 → 全局 → 平台与机器人 → 角色 → 当前会话继承。局部保存仅影响所选层级，不改动全局，也不授予新的资料或发送权限。', 'hint');
    const scopeInfo = el('p', '', 'hint'), levelLabel = el('label', '编辑层级 '), level = el('select');
    level.dataset.inheritanceLevel = 'select';
    for (const [value, name] of [['global', '全局'], ['platform', '当前平台与机器人'], ['role', '当前平台角色'], ['session', '当前私聊会话']]) {
      const option = el('option', name); option.value = value; level.append(option);
    }
    levelLabel.append(level);
    const status = el('p', '展开后读取当前配置。', 'context-settings-status'); status.setAttribute('role', 'status');
    const form = el('form'), grid = el('div', undefined, 'context-settings-fields');
    for (const field of fields) {
      const box = el('div', undefined, 'context-settings-field'), label = el('label', field.label + ' ');
      const input = el('input'); input.type = field.type; input.dataset.inheritanceField = field.key;
      if (field.type === 'number') { input.min = field.min; input.max = field.max; input.step = '1'; }
      const toggleLabel = el('label', undefined, 'context-settings-switch'), toggle = el('input'); toggle.type = 'checkbox';
      toggle.dataset.inheritanceOverride = field.key; toggleLabel.append(toggle, el('span', '本级覆盖'));
      const detail = el('p', '', 'hint');
      label.append(input); box.append(label, toggleLabel, detail); grid.append(box);
      inputs.set(field.key, input); switches.set(field.key, toggle); actual.set(field.key, detail);
      toggle.addEventListener('change', () => { input.disabled = busy || !toggle.checked; });
    }
    const actions = el('div', undefined, 'context-settings-actions');
    const save = el('button', '保存并回读', 'primary'), reload = el('button', '读取所选层级'), cancel = el('button', '取消编辑'), restore = el('button', '恢复本级继承');
    save.type = 'submit'; reload.type = cancel.type = restore.type = 'button';
    save.dataset.inheritanceAction = 'save'; reload.dataset.inheritanceAction = 'reload'; restore.dataset.inheritanceAction = 'restore';
    actions.append(save, cancel, restore, reload); form.append(grid, actions); wrapper.append(title, intro, scopeInfo, levelLabel, status, form); target.append(wrapper);
    const show = value => typeof value === 'boolean' ? (value ? '开启' : '关闭') : String(value);
    function paint(preserveDraft = false) {
      const uncertain = pending.get(selectionKey()), locked = busy || !!uncertain;
      level.disabled = busy; reload.disabled = busy; save.disabled = locked || !current?.writable;
      cancel.disabled = restore.disabled = locked || !current;
      scopeInfo.textContent = level.value === 'global' ? '全局设置；恢复继承将回到系统默认值。'
        : currentScope ? '当前平台 ' + currentScope.platform + ' · 角色 ' + currentScope.character_id + ' · 会话 ' + currentScope.session_id : '请先在上方选择完整真实会话，再读取局部设置。';
      for (const field of fields) {
        const input = inputs.get(field.key), toggle = switches.get(field.key), row = current?.fields?.find(r => r.key === field.key);
        if (!preserveDraft) toggle.checked = row?.overridden === true;
        toggle.disabled = locked || !current?.writable;
        input.disabled = locked || !current?.writable || !toggle.checked;
        const value = row?.override ?? row?.value;
        if (!preserveDraft) { if (field.type === 'checkbox') input.checked = value === true; else input.value = value ?? ''; }
        actual.get(field.key).textContent = row ? '默认：' + show(row.default) + ' · 来源：' + row.source_label + ' · 最终生效：' + show(row.value) : '尚未读取当前值。';
        if (uncertain && !preserveDraft) {
          const chosen = uncertain.draft[field.key]; toggle.checked = chosen.override;
          if (field.type === 'checkbox') input.checked = chosen.value; else input.value = chosen.value;
        }
      }
    }
    function validateSnapshot(value, selectedLevel) {
      if (!value || value.ok !== true || value.level !== selectedLevel || !Array.isArray(value.fields)
          || typeof value.revision !== 'string' || !/^[0-9a-f]{64}$/.test(value.revision)
          || typeof value.writable !== 'boolean' || !value.overrides || fields.some(f => !value.fields.some(r => r.key === f.key))) throw Error('Invalid inherited settings');
      return value;
    }
    function matches(value, intent) {
      return Object.entries(intent.body.changes).every(([key,wanted])=>Object.hasOwn(value.overrides,key)&&value.overrides[key]===wanted)
        && intent.body.restore.every(key=>!Object.hasOwn(value.overrides,key));
    }
    async function load() {
      if (busy || disposed) return false;
      const scope = getScope?.() || null, signature = scopeSignature(), selectedLevel = level.value, local = selectedLevel !== 'global';
      if (local && !full(scope)) { current = null; currentScope = null; status.textContent = '请选择上方完整会话；不会由配置创建会话或授权。'; paint(); return false; }
      const turn = ++epoch; currentScope = local ? {...scope} : null; currentSignature = signature;
      const ownKey = selectionKey(currentScope, selectedLevel); busy = true; status.textContent = '正在读取当前层级和上级配置…'; paint(true);
      try {
        const result = validateSnapshot(await api('GET', 'page/console/config/inheritance', {...(local ? scope : {}), level: selectedLevel}), selectedLevel);
        if (!alive(turn,signature,local)) return false;
        current = result;
        const intent = pending.get(ownKey);
        if (intent && matches(result,intent) && result.revision !== intent.body.expected_revision) pending.delete(ownKey);
        status.textContent = pending.has(ownKey) ? '已读取当前状态，但原保存尚未确认。草稿和原请求保留，只能继续读取，页面不会重发。' : '已读取当前来源和最终值；取消本级覆盖后保存可恢复继承。';
        return true;
      } catch (error) { if (alive(turn,signature,local)) { current = null; status.textContent = message(error); } return false; }
      finally { if (alive(turn,signature,local)) { busy = false; paint(); } }
    }
    async function persist(event) {
      event.preventDefault();
      const ownKey = selectionKey();
      if (busy || disposed || !current?.writable || pending.has(ownKey)) return;
      if (current.level !== 'global' && currentSignature !== scopeSignature()) { status.textContent = '上方会话已变化，请先读取新范围。'; return; }
      const changes = {}, restoreKeys = [], draft = {};
      for (const field of fields) {
        const input = inputs.get(field.key), value = field.type === 'checkbox' ? input.checked : Number(input.value);
        draft[field.key] = {override:switches.get(field.key).checked,value};
        if (!draft[field.key].override) { if (Object.hasOwn(current.overrides, field.key)) restoreKeys.push(field.key); continue; }
        if (field.type === 'number' && (!/^[0-9]+$/.test(input.value) || !Number.isSafeInteger(value) || value < field.min || value > field.max)) { status.textContent = field.label + '需要填写 ' + field.min + '–' + field.max + ' 的整数。'; return; }
        if (!Object.hasOwn(current.overrides, field.key) || current.overrides[field.key] !== value) changes[field.key] = value;
      }
      if (!Object.keys(changes).length && !restoreKeys.length) { status.textContent = '当前没有需要保存的修改。'; return; }
      const selectedLevel = current.level, capturedScope = currentScope && {...currentScope}, signature = currentSignature, turn = ++epoch;
      const intent = {body:{level:selectedLevel,...(capturedScope ? {scope:capturedScope} : {}),changes,restore:restoreKeys,expected_revision:current.revision},draft};
      pending.set(ownKey,intent); busy = true; paint(true); status.textContent = '正在保存本级修改并读取实际生效值…';
      let accepted = false;
      try {
        const saved = validateSnapshot(await api('POST','page/console/config/inheritance/save',intent.body),selectedLevel); accepted = true;
        const confirmed = validateSnapshot(await api('GET','page/console/config/inheritance',{...(capturedScope || {}),level:selectedLevel}),selectedLevel);
        if (confirmed.revision !== saved.revision || !matches(confirmed,intent)) throw Error('Readback differs');
        if (pending.get(ownKey)===intent) pending.delete(ownKey);
        if (!alive(turn,signature,!!capturedScope)) return;
        current = confirmed; status.textContent = '已保存并回读。下一次真实对话按上述最终值读取。';
      } catch (error) {
        if (!accepted && [400,401,403,409].includes(Number(error?.status||error?.statusCode)) && pending.get(ownKey)===intent) pending.delete(ownKey);
        if (alive(turn,signature,!!capturedScope)) status.textContent = message(error) + (pending.has(ownKey) ? ' 原保存结果未确认；保留草稿，请只读取核对，不会重发。' : ' 草稿已保留，请读取当前来源后再修改。');
      } finally { if (alive(turn,signature,!!capturedScope)) { busy = false; paint(!accepted || pending.has(ownKey)); } }
    }
    function scopeChanged() {
      if (level.value === 'global') return;
      epoch++; busy = false; current = null; currentScope = null; currentSignature = '';
      status.textContent = '会话范围已变化，旧结果不会应用到新范围。'; paint();
      if (wrapper.open) load();
    }
    wrapper.addEventListener('toggle', () => { if (wrapper.open && !current) load(); });
    level.addEventListener('change', () => { epoch++; busy = false; current = null; currentScope = null; paint(); load(); });
    reload.addEventListener('click', load); cancel.addEventListener('click', () => { if (!busy && !pending.has(selectionKey())) { paint(); status.textContent = '已取消本次编辑。'; } });
    restore.addEventListener('click', () => { if (!busy && !pending.has(selectionKey())) { for (const [key, input] of inputs) { switches.get(key).checked = false; input.disabled = true; } status.textContent = '已选择恢复本级继承，请保存后生效。'; } });
    form.addEventListener('submit', persist); paint();
    return {scopeChanged, destroy() { disposed = true; epoch++; }};
  }
  function mount(target, {api, getScope = () => null} = {}) {
    if (!target || typeof api !== 'function') throw Error('Settings mount and authenticated API required');
    const document = target.ownerDocument, controls = new Map(), currentLabels = new Map();
    function element(tag, text, className) {
      const result = document.createElement(tag);
      if (text !== undefined) result.textContent = text;
      if (className) result.className = className;
      return result;
    }
    target.classList.add('tls-context-settings');
    const heading = element('div', undefined, 'context-settings-heading');
    const title = element('h2', '对话背景显示'), scope = element('p', '感知与上下文 · 本插件全局设置', 'hint');
    heading.append(title, scope);
    const summary = element('p', '尚未读取设置。', 'context-settings-summary');
    const boundary = element('p', '这里只调整现有背景显示。保存不会开启来源、记忆记录或主动发送。', 'hint');
    const notice = element('p', '', 'context-settings-status');
    notice.setAttribute('role', 'status'); notice.setAttribute('aria-live', 'polite');
    const actions = element('div', undefined, 'context-settings-actions');
    const edit = element('button', '编辑背景设置'), reload = element('button', '重新读取');
    edit.type = reload.type = 'button'; edit.dataset.contextAction = 'edit'; reload.dataset.contextAction = 'reload';
    actions.append(edit, reload);
    const form = element('form'); form.hidden = true; form.setAttribute('aria-label', '背景显示设置');
    const grid = element('div', undefined, 'context-settings-fields');
    for (const field of fields) {
      const block = element('div', undefined, 'context-settings-field');
      const label = element('label'), text = element('span', field.label), input = element('input');
      input.type = field.type; input.name = field.key; input.dataset.contextField = field.key;
      if (field.type === 'number') { input.min = field.min; input.max = field.max; input.step = 1; input.required = true; }
      label.append(input.type === 'checkbox' ? input : text, input.type === 'checkbox' ? text : input);
      if (input.type === 'checkbox') label.className = 'context-settings-switch';
      const help = element('p', field.help, 'hint'), actual = element('p', '', 'context-settings-current');
      const error = element('p', '', 'context-settings-field-error');
      const id = 'context-settings-' + field.key;
      input.id = id; help.id = id + '-help'; error.id = id + '-error';
      input.setAttribute('aria-describedby', help.id + ' ' + error.id);
      block.append(label, help, actual, error); grid.append(block);
      controls.set(field.key, input); currentLabels.set(field.key, {actual, error});
    }
    const editorActions = element('div', undefined, 'context-settings-actions');
    const save = element('button', '保存并回读', 'primary'), cancel = element('button', '取消本次编辑');
    const check = element('button', '核对当前设置');
    save.type = 'submit'; cancel.type = check.type = 'button';
    save.dataset.contextAction = 'save'; cancel.dataset.contextAction = 'cancel'; check.dataset.contextAction = 'check';
    editorActions.append(save, cancel, check); form.append(grid, editorActions);
    target.replaceChildren(heading, summary, boundary, notice, actions, form);
    const inherited = mountInheritance(target, {api, getScope});
    function format(key, value) {
      if (typeof value === 'boolean') return value ? '开启' : '关闭';
      return key === 'presence_repeat_seconds' && value % 60 === 0 ? value + ' 秒（' + value / 60 + ' 分钟）' : String(value);
    }
    function render(state) {
      target.setAttribute('aria-busy', String(state.busy)); target.dataset.settingsPhase = state.phase;
      const values = state.current?.values;
      summary.textContent = values
        ? (values.presence_context_enabled ? '背景显示开启' : '背景显示关闭') + ' · 最多 ' + values.presence_context_max_chars
          + ' 字 · 重要背景自动重述间隔 ' + format('presence_repeat_seconds', values.presence_repeat_seconds)
        : '尚未取得有效后台设置；不按默认值推断。';
      if (state.current?.presenceEnabled === false) summary.textContent += ' · 感知总开关配置关闭';
      notice.textContent = state.status; notice.classList.toggle('context-settings-warning', state.needsCheck || state.phase === 'read_error');
      form.hidden = !state.editing; actions.hidden = state.editing;
      edit.disabled = state.busy || !state.current?.writable; reload.disabled = state.busy;
      save.disabled = !state.canSave; cancel.disabled = state.busy;
      check.hidden = !state.needsCheck; check.disabled = state.busy;
      for (const field of fields) {
        const input = controls.get(field.key), value = state.draft[field.key];
        input.disabled = state.busy || !state.current?.writable || state.needsCheck;
        if (field.type === 'checkbox') input.checked = value === true;
        else if (input.value !== String(value ?? '')) input.value = value ?? '';
        input.setAttribute('aria-invalid', String(!!state.errors[field.key]));
        currentLabels.get(field.key).error.textContent = state.errors[field.key] || '';
        currentLabels.get(field.key).actual.textContent = values ? '最近读取的后台值：' + format(field.key, values[field.key]) : '';
      }
    }
    const controller = createController(api, render);
    for (const field of fields) controls.get(field.key).addEventListener('input', event =>
      controller.update(field.key, field.type === 'checkbox' ? event.target.checked : event.target.value));
    edit.addEventListener('click', controller.begin); reload.addEventListener('click', controller.load);
    cancel.addEventListener('click', controller.cancel); check.addEventListener('click', controller.reconcile);
    form.addEventListener('submit', event => { event.preventDefault(); controller.save(); });
    const beforeUnload = event => { const state = controller.view(); if (state.dirty || state.needsCheck || ['saving', 'checking'].includes(state.phase)) { event.preventDefault(); event.returnValue = ''; } };
    const window = document.defaultView;
    window?.addEventListener('beforeunload', beforeUnload);
    render(controller.view()); controller.load();
    return {controller, scopeChanged:inherited.scopeChanged, destroy() { window?.removeEventListener('beforeunload', beforeUnload); controller.destroy(); inherited.destroy(); }};
  }
  return Object.freeze({createController, mount, mountInheritance, fields});
});
