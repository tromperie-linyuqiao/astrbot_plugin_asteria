'use strict';

/* One user-operated settings surface. Credentials and collection stay native/server side. */
window.AsteriaChatPerception = (() => {
  let installed = null;
  const SECTIONS = ['basic', 'app', 'music'];
  const unwrap = value => {
    const body = typeof value === 'string' ? JSON.parse(value) : value;
    return body && Object.hasOwn(body, 'data') ? body.data : body;
  };
  const sameSections = (a, b) => SECTIONS.every(key => a?.[key] === b?.[key]);
  const reasonText = value => ({
    binding_required: '先在“QQ与记忆共享”确认绑定。', linked_identity_required: '先在“QQ与记忆共享”确认绑定。',
    linked_perception_required: '请在“日程与权限”允许使用已绑定手机的感知与音乐。',
    perception_permission_required: '请在“日程与权限”允许使用已绑定手机的感知与音乐。',
    device_binding_required: '当前账户没有已分配的设备，请先在 TLS 手机感知中维护设备。',
    phone_service_unavailable: '服务器感知模块暂时不可用；仍可停止本机采集。',
    permission_required: '请在“日程与权限”允许使用已绑定手机的感知与音乐。',
    bridge_unavailable: '服务器暂时无法连接原手机感知桥。', device_required: '请选择你原来已经拥有的手机设备。',
    no_owned_devices: '当前账户没有可用的原手机设备，请先在 TLS 手机感知中维护设备。',
    notifications_permission_required: '请先允许常驻采集通知。', usage_permission_required: '应用感知需要你明确授予使用情况访问权限。',
    music_permission_required: '音乐感知需要你明确授予通知访问权限。', stopped: '采集已停止。', disabled: '尚未开启采集。',
    notification_permission: '常驻采集通知未获允许，采集已停止。', no_available_sections: '已选项目暂无权限或可用状态，本轮没有上报。',
    configuration_unavailable: '暂时无法核验服务器配置，等待网络恢复。', report_outcome_unknown: '本轮上报结果未知，未记为成功，不会重发原事件。',
    report_rejected: '感知桥未接受本轮上报，未记为成功。',
    none: '', ok: '', ready: '', configured: '', running: '', reported: ''
  })[value] ?? (/^[a-z0-9_.:-]{1,96}$/.test(String(value || '')) ? '状态：' + value : '');
  function runtimeText(value) {
    if (!value) return '本机状态不可用';
    const labels = {
      starting: '本机正在启动，尚未核验设备与采集范围', verifying: '本机正在核验设备与采集范围',
      waiting_for_permission: '本机等待已选项目的权限或可用状态', waiting_for_network: '本机等待网络恢复，当前尚未确认同步',
      syncing: '本机正在同步手机状态，结果待确认', report_unknown: '本轮上报结果未知，未记为成功',
      waiting_for_bridge: '感知桥未接受本轮上报，等待下次检查', running: '本机正在采集，按已选项目同步', stopped: '本机已停止'
    };
    return labels[value.state] || (value.enabled === false && value.running === false ? '本机已停止' : '本机采集状态待核对，请刷新查看');
  }
  function reportTimeText(value) {
    const parseDate = raw => typeof raw === 'number' && raw > 0 ? new Date(raw < 1e12 ? raw * 1000 : raw)
      : typeof raw === 'string' && raw ? new Date(raw) : null;
    const accepted = value?.accepted_report_at;
    const id = value?.accepted_event_id;
    const confirmed = value?.report_confirmation_schema === 1 && value?.last_report_confirmed === true
      && typeof id === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(id)
      && typeof accepted === 'number' && Number.isFinite(accepted) && accepted > 0 && accepted === value.last_report_at;
    const date = parseDate(confirmed ? accepted : value?.last_report_at);
    if (date && Number.isFinite(date.getTime())) return date.toLocaleString() + (confirmed ? '（感知桥已确认接收）' : '（旧记录，未核对）');
    return '本机尚无成功上报记录';
  }
  function install({ state, api, bridgeRequest, showNotice }) {
    if (installed) return installed;
    const $ = id => document.getElementById(id);
    const dialog = $('perception-dialog');
    if (!dialog) throw Error('手机感知设置入口尚未挂载。');
    let epoch = 0, owner = '', busy = false, stopping = false, stopEpoch = 0, server = null, nativeState = null, installationId = '';
    const pending = new Map();
    const scope = () => JSON.stringify([state.server, state.username, state.activeId]);
    const op = () => ({ epoch, owner, session: state.activeId, stopEpoch });
    const current = value => value.epoch === epoch && value.owner === owner && owner === scope()
      && state.authenticated && dialog.open;
    const say = text => { $('perception-status').textContent = text; };
    const errorText = error => String(error?.message || '操作暂时未完成。').replace(/[\u0000-\u001f<>]/g, '').slice(0, 220);
    const bridge = async (method, args = []) => {
      if (typeof bridgeRequest !== 'function') throw Error('请在支持手机感知的新版 Android 应用中打开。');
      return unwrap(await bridgeRequest(method, args));
    };
    const eligible = () => !!server && server.linked === true && server.permission_granted === true && server.bridge_available === true;
    const sections = () => Object.fromEntries(SECTIONS.map(key => [key, $('perception-' + key).checked === true]));
    const uncertain = () => pending.has(owner);
    function controls() {
      const block = busy || uncertain() || !server || !installationId;
      for (const id of ['perception-device', 'perception-enabled', 'perception-basic', 'perception-app', 'perception-music', 'perception-consent']) $(id).disabled = block;
      $('perception-save').disabled = block;
      $('perception-start').disabled = block || !eligible() || server.enabled !== true;
      $('perception-report').disabled = busy || uncertain() || !eligible() || server.enabled !== true || nativeState?.running !== true;
      $('perception-refresh').disabled = busy;
      // An uncertain server write must never prevent an immediate local stop.
      $('perception-stop').disabled = !installationId || stopping;
      for (const key of ['notifications', 'usage', 'music', 'battery']) $('perception-permission-' + key).disabled = busy || !installationId;
      $('perception-reconcile').hidden = pending.get(owner)?.checked !== true;
      $('perception-reconcile').disabled = busy;
    }
    function drawStatus() {
      $('perception-connection').textContent = server ? server.bridge_available === true ? '感知桥已配置' : '感知桥配置当前不可用' : '尚未读取服务器';
      $('perception-authority').textContent = server ? server.linked !== true ? 'QQ 身份尚未确认绑定'
        : server.permission_granted !== true ? '感知查阅权限尚未开启' : '已确认绑定与感知查阅权限' : '授权尚未读取';
      $('perception-runtime').textContent = runtimeText(nativeState);
      $('perception-server-state').textContent = server ? server.enabled === true ? '服务器配置：允许本机上报' : '服务器配置：关闭' : '';
      $('perception-last-report').textContent = reportTimeText(nativeState);
      const http = nativeState?.http_status;
      $('perception-reason').textContent = [reasonText(server?.reason), reasonText(nativeState?.error),
        Number.isInteger(http) && http > 0 ? '最近请求 HTTP ' + http + '（不代表已生成陪伴消息）' : ''].filter(Boolean).join(' ');
      for (const key of ['notifications', 'usage', 'music']) {
        const value = nativeState?.permissions?.[key];
        $('perception-permission-state-' + key).textContent = value === true ? '已允许' : value === false ? '未允许' : '尚未读取';
      }
      if (window.AsteriaChatPerceptionStatus?.render) window.AsteriaChatPerceptionStatus.render($('perception-unified-status'), server?.unified_status);
      controls();
    }
    function drawForm() {
      const select = $('perception-device'); select.replaceChildren();
      const option = document.createElement('option'); option.value = ''; option.textContent = '请选择原手机设备'; select.append(option);
      for (const row of server.devices || []) {
        if (!row || typeof row.id !== 'string' || !row.id) continue;
        const node = document.createElement('option'); node.value = row.id;
        node.textContent = typeof row.label === 'string' && row.label ? row.label : '已登记手机'; select.append(node);
      }
      select.value = [...select.options].some(value => value.value === server.device_id) ? server.device_id : '';
      $('perception-enabled').checked = server.enabled === true;
      for (const key of SECTIONS) $('perception-' + key).checked = server.sections?.[key] === true;
      $('perception-consent').checked = false;
    }
    function validateSnapshot(data) {
      if (!data || typeof data.enabled !== 'boolean' || !Array.isArray(data.devices) || !data.sections
          || SECTIONS.some(key => typeof data.sections[key] !== 'boolean') || data.revision === undefined
          || data.installation_id !== installationId || data.session_id !== state.activeId) throw Error('服务器未返回当前会话完整的手机感知配置。');
      return data;
    }
    function reconcile() {
      const value = pending.get(owner); if (!value) return false; value.checked = true;
      const body = value.body;
      if (server.revision !== body.expected_revision && server.enabled === body.enabled && server.device_id === body.device_id
          && sameSections(server.sections, body.sections)) { pending.delete(owner); return true; }
      return false;
    }
    async function refresh() {
      if (busy || !owner) return;
      const ticket = op(); busy = true; controls(); say('正在读取本机与服务器状态…');
      try {
        const local = await bridge('phonePerceptionStatus'); if (!current(ticket)) return;
        if (!local || typeof local.installation_id !== 'string' || !local.installation_id) throw Error('此环境未提供手机感知采集；请使用新版 Android 应用。');
        nativeState = local; installationId = local.installation_id;
        const data = await api.json('GET', '/chat/perception/config?session_id=' + encodeURIComponent(ticket.session)
          + '&installation_id=' + encodeURIComponent(installationId));
        if (!current(ticket)) return;
        server = validateSnapshot(unwrap(data)); const confirmed = reconcile(); drawForm(); drawStatus();
        say(confirmed ? '服务器当前值已与上次修改对应。采集不会因核对而自动重启，请明确点击继续采集。'
          : uncertain() ? '已读取当前配置；上次保存仍未确认，不会自动重发。' : '请按需选择采集项并明确授权；默认不采集。');
      } catch (error) { if (current(ticket)) { say(errorText(error)); drawStatus(); } }
      finally { if (current(ticket)) { busy = false; controls(); } }
    }
    function prepared(enabled) {
      if (!server || !installationId) throw Error('请先刷新当前配置。');
      const device = $('perception-device').value;
      if (enabled) {
        if (!eligible()) throw Error(reasonText(server.reason) || '请先在“日程与权限”确认绑定手机的感知查阅权限。');
        if (!(server.devices || []).some(row => row.id === device)) throw Error('请选择你已经拥有的手机设备；不会自动选择或创建设备。');
        if (!Object.values(sections()).some(Boolean)) throw Error('请至少选择一项你愿意提供的手机感知。');
        if (!$('perception-consent').checked) throw Error('请先确认采集范围，并停止原 PPB 上报端，避免同设备被同时更新。');
      }
      return { session_id: state.activeId, installation_id: installationId, device_id: device || server.device_id,
        enabled, sections: sections(), consent: true, expected_revision: server.revision };
    }
    async function start(ticket, saved) {
      if (!current(ticket) || ticket.stopEpoch !== stopEpoch) return;
      const local = await bridge('startPhonePerception', [ticket.session, JSON.stringify(saved.sections)]);
      // Native admission cancels starts queued before stop/scope change. A late
      // old reply must not issue a fresh stop against a newly selected session.
      if (ticket.stopEpoch !== stopEpoch || !current(ticket)) return;
      nativeState = local; drawStatus();
      say(local?.start_cancelled === true ? '本次启动已取消，请按当前本机状态操作。'
        : runtimeText(local) + '；只有已选择的资料会上报，是否产生陪伴由 TLS 原规则决定。');
    }
    async function save() {
      if (busy || uncertain() || owner !== scope()) return;
      let body; try { body = prepared($('perception-enabled').checked); } catch (error) { say(errorText(error)); return; }
      const ticket = op(); busy = true; const value = { body, checked: false }; pending.set(owner, value); controls();
      try {
        const result = await api.json('POST', '/chat/perception/config', body);
        // A completed authenticated CAS is required before any native start.
        if (!current(ticket)) { pending.delete(ticket.owner); return; }
        server = validateSnapshot(unwrap(result)); pending.delete(ticket.owner); drawForm();
        if (body.enabled) await start(ticket, server);
        else { nativeState = await bridge('stopPhonePerception'); if (current(ticket)) { drawStatus(); say('服务器已关闭，本机采集已请求停止。'); } }
      } catch (error) {
        if (pending.get(ticket.owner) === value && Number.isInteger(error?.status) && error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status)) pending.delete(ticket.owner);
        if (current(ticket)) say(errorText(error) + (pending.has(ticket.owner) ? ' 保存结果待核对，请刷新；不会自动重复提交。' : ' 配置未自动重试。请刷新当前状态后操作。'));
      } finally { if (current(ticket)) { busy = false; drawStatus(); } }
    }
    async function resume() {
      if (busy || uncertain() || owner !== scope() || server?.enabled !== true) return;
      let body; try { body = prepared(true); if (body.device_id !== server.device_id || !sameSections(body.sections, server.sections)) throw Error('你已修改设备或采集范围，请先保存设置。'); }
      catch (error) { say(errorText(error)); return; }
      const ticket = op(); busy = true; controls();
      try { await start(ticket, server); } catch (error) { if (current(ticket)) say(errorText(error)); }
      finally { if (current(ticket)) { busy = false; controls(); } }
    }
    async function stop() {
      if (!installationId || stopping || owner !== scope()) return;
      stopping = true; stopEpoch++;
      const ticket = op(), wasBusy = busy; busy = true; controls();
      // Local collection is stopped immediately even if a server write is unknown/in flight.
      const stopped = bridge('stopPhonePerception').then(value => {
        if (current(ticket)) nativeState = value; return { value };
      }, error => ({ error }));
      if (wasBusy || uncertain() || !server) {
        try { const result = await stopped; if (result.error) throw result.error;
          if (current(ticket)) say('已请求本机停止。服务器保存仍待核对，请刷新；不会重发未决配置。'); }
        catch (error) { if (current(ticket)) say(errorText(error)); }
        finally { stopping = false; if (current(ticket)) { busy = wasBusy; drawStatus(); } } return;
      }
      const body = { session_id: ticket.session, installation_id: installationId, device_id: server.device_id,
        enabled: false, sections: server.sections, consent: true, expected_revision: server.revision };
      const value = { body, checked: false }; pending.set(owner, value);
      try {
        const result = await api.json('POST', '/chat/perception/config', body);
        if (current(ticket)) { server = validateSnapshot(unwrap(result)); drawForm(); }
        pending.delete(ticket.owner);
      } catch (error) {
        if (pending.get(ticket.owner) === value && Number.isInteger(error?.status) && error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status)) pending.delete(ticket.owner);
        if (current(ticket)) say(errorText(error) + ' 本机已请求停止；服务器关闭结果请刷新核对。');
      } finally {
        try { const result = await stopped; if (result.error) throw result.error;
          if (current(ticket) && !pending.has(ticket.owner)) say('本机已停止，服务器已关闭本机上报。'); }
        catch (error) { if (current(ticket)) say(errorText(error) + ' 请按系统通知停止采集并刷新核对。'); }
        stopping = false; if (current(ticket)) { busy = false; drawStatus(); }
      }
    }
    async function nativeAction(method, args = []) {
      if (busy || !installationId || owner !== scope()) return;
      const ticket = op(); busy = true; controls();
      try {
        const result = await bridge(method, args); if (!current(ticket)) return;
        nativeState = await bridge('phonePerceptionStatus'); if (current(ticket)) { drawStatus(); say(method === 'reportPhonePerception'
          ? result?.report_queued === true ? '已请求上报已授权的采集项，请查看实际最近上报时间与请求状态。'
            : '本轮未能排队上报，请核对本机运行状态；不会自动启动采集。'
          : '系统授权页面已请求打开；返回后请刷新查看实际授权状态。'); }
      } catch (error) { if (current(ticket)) say(errorText(error)); }
      finally { if (current(ticket)) { busy = false; controls(); } }
    }
    function close() { epoch++; owner = ''; busy = false; if (dialog.open) dialog.close(); }
    function scopeChanged() { if (owner && (!state.authenticated || owner !== scope())) { stopEpoch++; close(); } }
    function open() {
      if (!state.authenticated || !state.activeId) { showNotice('先登录并连接伙伴。'); return; }
      $('more-menu').hidden = true; $('more-button').setAttribute('aria-expanded', 'false');
      epoch++; owner = scope(); busy = false; server = null; nativeState = null; installationId = '';
      $('perception-device').replaceChildren(); $('perception-enabled').checked = false; $('perception-consent').checked = false;
      for (const key of SECTIONS) $('perception-' + key).checked = false;
      if (!dialog.open) dialog.showModal(); drawStatus(); refresh();
    }
    $('menu-perception').onclick = open; $('perception-close').onclick = close;
    $('perception-refresh').onclick = refresh; $('perception-save').onclick = save;
    $('perception-start').onclick = resume; $('perception-stop').onclick = stop;
    $('perception-report').onclick = () => nativeAction('reportPhonePerception');
    for (const key of ['notifications', 'usage', 'music', 'battery']) $('perception-permission-' + key).onclick = () => nativeAction('requestPhonePerceptionPermission', [key]);
    $('perception-workspace').onclick = () => { close(); if (window.ChatWorkspace?.open) window.ChatWorkspace.open(); else showNotice('请先打开“日程与权限”管理感知查阅权限。'); };
    $('perception-reconcile').onclick = () => { const value = pending.get(owner); if (!busy && value?.checked) { pending.delete(owner); say('已结束本次等待；原请求仍可能稍后完成，请按当前服务器值操作。'); controls(); } };
    dialog.addEventListener('close', () => { if (!dialog.open && owner) { epoch++; owner = ''; busy = false; } });
    const foregroundChanged = () => { if (dialog.open && owner === scope() && state.authenticated && !busy) return refresh(); };
    installed = Object.freeze({ open, close, scopeChanged, refresh, foregroundChanged });
    return installed;
  }
  return Object.freeze({ install });
})();
