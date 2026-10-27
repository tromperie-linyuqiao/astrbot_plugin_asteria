(() => {
  'use strict';
  const mount = document.getElementById('proactive-chat-native-mount');
  if (!mount || typeof api !== 'function') return;
  const base = 'page/proactive-chat-native/';
  let state = null, busy = false, selected = null, editor = null, pending = null, serial = 0;
  const triggerPending = new Map();
  const copy = value => JSON.parse(JSON.stringify(value));
  const equal = (left, right) => JSON.stringify(left) === JSON.stringify(right);
  const merge = (left, right) => {
    const result = copy(left || {});
    for (const [key, value] of Object.entries(right)) result[key] = value && typeof value === 'object' && !Array.isArray(value)
      ? merge(result[key] || {}, value) : value;
    return result;
  };
  const requestId = () => {
    if (!window.TLSBrowserCompat) throw Error('请求编号助手尚未加载，请刷新后台。');
    return 'proactive.manual.' + window.TLSBrowserCompat.uuid();
  };
  mount.innerHTML = `<section class="panel proactive-chat-native"><div class="panel-head"><h2>独立主动消息</h2><button type="button" data-pcn-refresh>刷新状态</button></div><p class="hint">保留原会话的计划时间、未回复次数和会话覆盖。编辑资料不授予发送权限；生成与发送仍经过实际私聊授权、冷却和统一队列。</p><p data-pcn-notice role="status" aria-live="polite">等待读取。</p><div data-pcn-stats class="pcn-stats"></div><div class="actions"><button type="button" data-pcn-inspect>读取原状态与兼容条件</button><button type="button" data-pcn-activate>接管已兼容的原任务</button><button type="button" data-pcn-stop>停止新接纳</button></div><div data-pcn-blockers class="pcn-blockers"></div><div data-pcn-sessions class="pcn-sessions"></div><form data-pcn-editor hidden><h3 data-pcn-title></h3><p data-pcn-inheritance class="hint"></p><label>显示名称<input maxlength="80" data-pcn-name></label><label class="switch-label"><input type="checkbox" data-pcn-enabled>启用此会话</label><div class="form-grid"><label>最短间隔（分钟）<input type="number" min="1" max="525600" step="1" data-pcn-min></label><label>最长间隔（分钟）<input type="number" min="1" max="525600" step="1" data-pcn-max></label></div><label>独立主动安静时段<input type="text" maxlength="143" data-pcn-quiet-hours placeholder="例如：8-12,14-18" autocapitalize="none" spellcheck="false"></label><p class="hint">按本会话原时区执行；多个时段用英文逗号分隔，最多24段。例 8-12,14-18 表示08:00–12:00和14:00–18:00保持安静，其他时间仍须通过原发送规则。结束早于开始时延续到次日，起止相同的时段不生效。</p><p data-pcn-quiet-preview class="hint" role="status"></p><label>连续未回复上限（0表示沿原配置不限）<input type="number" min="0" max="100" step="1" data-pcn-unanswered></label><label>主动开场提示词<textarea rows="6" maxlength="16000" data-pcn-prompt></textarea></label><details><summary>默认值与当前覆盖</summary><div data-pcn-sources class="pcn-sources"></div></details><div class="actions"><button type="submit" class="primary" data-pcn-save>保存并回读</button><button type="button" data-pcn-check>只读核对当前值</button><button type="button" data-pcn-inherit>恢复本会话全部继承</button><button type="button" data-pcn-cancel>取消编辑</button></div><div data-pcn-reset-confirm hidden><p class="hint">将清除本会话的所有覆盖（包括已有TTS、上下文等覆盖），恢复全局默认。已有任务的时间不会重抽。</p><button type="button" data-pcn-reset-yes>确认恢复继承</button><button type="button" data-pcn-reset-no>保留当前覆盖</button></div><p class="hint">只保存改过的字段，未修改的会话设置与继承关系保持。保存结果必须由原文件回读确认；不会取消、重排或清理当前任务。</p></form></section>`;
  const $ = key => mount.querySelector('[data-pcn-' + key + ']');
  const node = (tag, value) => { const element = document.createElement(tag); if (value !== undefined) element.textContent = value; return element; };
  const quietWindows = value => typeof value === 'string' && value.length <= 143
    && /^(?:[01]?[0-9]|2[0-3])-(?:[01]?[0-9]|2[0-3])(?:,(?:[01]?[0-9]|2[0-3])-(?:[01]?[0-9]|2[0-3])){0,23}$/.test(value)
    ? value.split(',').map(part => part.split('-').map(Number)) : null;
  function quietPreview() {
    const windows = quietWindows($('quiet-hours').value.trim());
    const format = hour => String(hour).padStart(2, '0') + ':00';
    $('quiet-preview').textContent = windows ? windows.some(([start, end]) => start !== end)
      ? '安静、不主动打扰：' + windows.filter(([start, end]) => start !== end)
        .map(([start, end]) => format(start) + '–' + (end < start ? '次日' : '') + format(end)).join('、')
      : '当前所有时段起止相同，不设安静时段。'
      : '请输入0–23的起止小时；多段用英文逗号分隔。原有非标准值若未修改会保持。';
  }
  const labels = {enabled_tts_not_supported_by_unified_lane: '当前会话需要TTS，但统一通道暂不可用。', enabled_segmentation_not_supported_by_single_task_lane: '当前会话启用了尚不兼容的分段发送。', enabled_decorating_handlers_not_supported_by_unified_lane: '存在不能静默跳过的消息装饰器。', decorating_handler_inventory_unknown: '消息装饰器清单尚未确认。', group_scope_not_authorized_by_private_lane: '群聊需要独立明确授权，不能使用私聊许可。'};
  function notice(text, error = false) { $('notice').textContent = text; $('notice').classList.toggle('pcn-error', error); }
  async function request(method, suffix, body) {
    const result = await api(method, base + suffix, body);
    if (!result || result.status === 'error' || result.ok === false || result.success === false) throw Error(result?.message || '后台操作未确认');
    return result.data ?? result;
  }
  function controls() {
    for (const button of mount.querySelectorAll('button')) button.disabled = busy;
    $('activate').disabled = busy || !!state?.active || !state?.prepared || !!state?.migration_blockers?.length || !!state?.pending_operations;
    $('stop').disabled = busy || !state?.active && !state?.pending_operations;
    for (const control of $('editor').querySelectorAll('input,textarea,select')) control.disabled = busy || !!pending;
    $('save').disabled = busy || !!pending || editor?.persisted_verified !== true;
    $('inherit').disabled = busy || !!pending || !Object.keys(editor?.override || {}).length || editor?.persisted_verified !== true;
    $('cancel').disabled = busy || !!pending;
    for (const button of mount.querySelectorAll('[data-pcn-send]')) button.disabled = busy || !state?.active || button.dataset.blocked === 'true';
  }
  function drawEditor() {
    $('editor').hidden = !editor;
    if (!editor) return;
    $('title').textContent = '编辑会话 · ' + selected;
    $('inheritance').textContent = editor.persisted_verified === true ? '原会话覆盖已与磁盘文件核对；管理操作不会登记私聊授权。' : '运行值与原文件尚未一致，暂不可继续保存。';
    const config = editor.config || {};
    $('name').value = config.session_name || '';
    $('enabled').checked = config.enable === true;
    $('min').value = config.schedule_settings?.min_interval_minutes ?? 30;
    $('max').value = config.schedule_settings?.max_interval_minutes ?? 900;
    $('quiet-hours').value = config.schedule_settings?.quiet_hours ?? '1-7';
    quietPreview();
    $('unanswered').value = config.schedule_settings?.max_unanswered_times ?? 3;
    $('prompt').value = config.proactive_prompt || '';
    const target = $('sources'); target.replaceChildren();
    for (const [label, key, child] of [['启用', 'enable'], ['名称', 'session_name'], ['最短间隔', 'schedule_settings', 'min_interval_minutes'], ['最长间隔', 'schedule_settings', 'max_interval_minutes'], ['独立主动安静时段', 'schedule_settings', 'quiet_hours'], ['未回复上限', 'schedule_settings', 'max_unanswered_times'], ['开场提示词', 'proactive_prompt']]) {
      const source = child ? editor.override?.[key]?.[child] : editor.override?.[key];
      const initial = child ? editor.base?.[key]?.[child] : editor.base?.[key];
      target.append(node('p', label + '：' + (source !== undefined ? '本会话覆盖' : '继承全局') + ' · 默认：' + (initial === undefined ? '未配置' : String(initial))));
    }
    $('reset-confirm').hidden = true;
  }
  function render() {
    $('stats').replaceChildren(); $('blockers').replaceChildren(); $('sessions').replaceChildren();
    if (state) {
      for (const [label, value] of [['执行者', state.active ? 'TLS原生运行' : 'TLS未运行'], ['在途操作', state.pending_operations ?? '未知'], ['确认送达', state.counts?.confirmed ?? '未知'], ['待核对', state.counts?.unknown ?? '未知']]) {
        const card = node('div'); card.append(node('small', label), node('strong', String(value))); $('stats').append(card);
      }
      for (const blocker of state.migration_blockers || []) $('blockers').append(node('p', (blocker.session_id ? blocker.session_id + '：' : '') + (labels[blocker.reason] || blocker.reason)));
      for (const session of state.sessions || []) {
        const row = node('article'); row.className = 'pcn-session';
        row.append(node('strong', session.session_id), node('p', `未回复 ${session.unanswered_count ?? 0} 次 · ${session.execution_state === 'waiting_for_real_scope' ? '等待真实私聊，原任务保留' : session.scheduled ? '已有计划' : '当前未运行'}`));
        row.append(node('p', session.next_trigger_time ? '计划时间：' + new Date(session.next_trigger_time * 1000).toLocaleString() : '原记录没有下一次时间'));
        if (session.last_admission) {
          const check = session.last_admission;
          row.append(node('p', '最新准入：' + (check.reason || check.state || '待核对') + ' · '
            + (check.source === 'current_preflight_read' ? '当前只读检查，不代表旧请求原因' : '本次触发结果')
            + (Number.isFinite(check.checked_at) ? ' · ' + new Date(check.checked_at * 1000).toLocaleString() : '')
            + '；准入允许也不等于已经送达。'));
        }
        if (session.manual_review || triggerPending.has(session.session_id)) row.append(node('p', '原任务或手动请求结果待核对。请查看真实会话与发送记录；本页不会自动重发。'));
        const edit = node('button', '编辑会话设置'); edit.type = 'button'; edit.onclick = () => editSession(session.session_id); row.append(edit);
        const trigger = node('button', '现在生成并按统一规则发送'); trigger.type = 'button'; trigger.dataset.pcnSend = 'true'; trigger.dataset.blocked = String(!!session.manual_review || triggerPending.has(session.session_id));
        trigger.onclick = () => triggerSession(session.session_id); row.append(trigger); $('sessions').append(row);
      }
    }
    controls();
  }
  async function load(inspect = false, quiet = false) {
    if (busy) return false; busy = true; controls();
    try { state = await request('GET', inspect ? 'inspect' : 'status'); if (!quiet) notice(inspect ? '已读取真实原状态，未触发发送。' : '已读取当前运行状态。'); return true; }
    catch (error) { notice('刷新未确认，保留上次显示。' + (error.publicMessage || error.message || ''), true); return false; }
    finally { busy = false; render(); }
  }
  async function operate(path) {
    if (busy) return; busy = true; controls();
    try { await request('POST', path, {}); notice('管理操作已返回，正在读取实际状态。'); }
    catch (error) { notice('结果需核对，不会自动重试。' + (error.publicMessage || error.message || ''), true); }
    finally { busy = false; }
    await load(false, true);
  }
  async function triggerSession(session) {
    if (busy || triggerPending.has(session)) return;
    const identity = requestId(); triggerPending.set(session, identity); busy = true; controls();
    try { state = await request('POST', 'trigger', {session_id: session, request_id: identity}); triggerPending.delete(session);
      const attempt = state.attempt;
      notice(attempt?.confirmed === true ? '统一队列已返回发送确认；这不代表用户已阅读。'
        : '本次未确认送达：' + (attempt?.reason || attempt?.state || '请核对真实任务与历史') + '。不会自动重发。'); }
    catch (error) {
      if ([400, 401, 403, 404, 409].includes(Number(error?.status || error?.statusCode))) triggerPending.delete(session);
      notice('手动请求尚未确认；不会自动重发。' + (error.publicMessage || error.message || ''), true);
    } finally { busy = false; render(); }
  }
  async function editSession(session) {
    if (busy) return;
    if (pending) { notice('请先只读核对当前未确认的保存，原草稿保持。', true); return; }
    busy = true; controls(); const token = ++serial;
    try { const result = await request('GET', 'session', {session_id: session}); if (token !== serial) return; selected = result.session_id; editor = result; drawEditor(); notice('已读取默认值、当前覆盖与实际文件。'); }
    catch (error) { notice(error.publicMessage || error.message || '会话配置读取失败，草稿保持。', true); }
    finally { busy = false; controls(); }
  }
  async function reconcile() {
    if (busy || !selected) return false;
    busy = true; controls();
    try {
      const result = await request('GET', 'session', {session_id: selected});
      if (pending && (!result.persisted_verified || !equal(result.override, pending.targetOverride))) {
        notice('当前文件尚未确认原目标。保留草稿和原请求，仅可继续只读核对。', true); return false;
      }
      pending = null; editor = result; drawEditor(); notice('已从原文件确认当前设置；没有重复提交。'); return true;
    } catch (error) { notice('文件回读尚未确认，草稿保留。' + (error.publicMessage || error.message || ''), true); return false; }
    finally { busy = false; controls(); }
  }
  async function save(reset = false) {
    if (busy || pending || !editor || !selected || editor.persisted_verified !== true) return;
    const changes = {};
    if (!reset) {
      const minimum = Number($('min').value), maximum = Number($('max').value), count = Number($('unanswered').value);
      if (![minimum, maximum, count].every(Number.isInteger) || minimum < 1 || maximum < minimum || maximum > 525600 || count < 0 || count > 100) { notice('请填写有效整数间隔和未回复上限。', true); return; }
      const values = {enable: $('enabled').checked, session_name: $('name').value.trim(), proactive_prompt: $('prompt').value};
      for (const [key, value] of Object.entries(values)) if (value !== (editor.config?.[key] ?? (key === 'enable' ? false : ''))) changes[key] = value;
      const schedule = {min_interval_minutes: minimum, max_interval_minutes: maximum, max_unanswered_times: count};
      const originalQuiet = editor.config?.schedule_settings?.quiet_hours ?? '1-7';
      const nextQuiet = $('quiet-hours').value.trim();
      if (nextQuiet !== originalQuiet) {
        if (!quietWindows(nextQuiet)) { notice('请填写1至24个0–23的小时范围，多段用英文逗号分隔，如8-12,14-18。', true); return; }
        schedule.quiet_hours = nextQuiet;
      }
      for (const [key, value] of Object.entries(schedule)) if (value !== (editor.config?.schedule_settings?.[key] ?? ({min_interval_minutes:30,max_interval_minutes:900,max_unanswered_times:3,quiet_hours:'1-7'})[key])) {
        (changes.schedule_settings ||= {})[key] = value;
      }
      if (!Object.keys(changes).length) { notice('没有修改，继承关系保持。'); return; }
    }
    const body = {session_id: selected, expected_revision: editor.revision, ...(reset ? {reset: true} : {changes})};
    pending = {body, targetOverride: reset ? {} : merge(editor.override || {}, changes)};
    busy = true; controls();
    try { const result = await request('POST', 'session', body); if (result.persisted_verified && equal(result.override, pending.targetOverride)) { pending = null; editor = result; drawEditor(); notice('已保存并与原文件核对。原任务时间保持。'); } }
    catch (error) {
      if ([400,401,403,404,409].includes(Number(error?.status || error?.statusCode))) pending = null;
      notice('保存尚未确认，草稿保留。' + (error.publicMessage || error.message || ''), true);
    } finally { busy = false; controls(); }
    if (pending) await reconcile();
  }
  $('quiet-hours').addEventListener('input', quietPreview);
  $('editor').addEventListener('submit', event => { event.preventDefault(); save(); });
  $('cancel').onclick = () => { if (busy || pending) return; selected = editor = null; drawEditor(); controls(); };
  $('check').onclick = reconcile;
  $('inherit').onclick = () => { if (!busy && !pending) $('reset-confirm').hidden = false; };
  $('reset-no').onclick = () => { $('reset-confirm').hidden = true; };
  $('reset-yes').onclick = () => save(true);
  $('refresh').onclick = () => load(); $('inspect').onclick = () => load(true);
  $('activate').onclick = () => operate('activate'); $('stop').onclick = () => operate('stop');
  window.TLSIndependentProactivePanel = Object.freeze({activate() { const sheet = document.getElementById('proactive-chat-native-styles'); if (sheet) sheet.media = 'all'; return load(); }});
  render();
})();
