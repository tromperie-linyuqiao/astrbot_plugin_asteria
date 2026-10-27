/* Calendar recurrence extends the existing agenda form and API only. */
(() => {
  'use strict';
  if (typeof state === 'undefined' || !$('agenda-create-form')) return;
  const labels = {none:'单次',daily:'每天',weekly:'每周',monthly:'每月',yearly:'每年'};
  const form = $('agenda-create-form');
  const controls = node('div', undefined, 'two-columns');
  const repeatLabel = node('label', '重复方式');
  const repeat = document.createElement('select'); repeat.id = 'agenda-repeat';
  for (const [value, title] of Object.entries(labels)) {
    const option = node('option', title); option.value = value; repeat.append(option);
  }
  repeatLabel.append(repeat);
  const zoneLabel = node('label', '周期采用的时区');
  const zone = document.createElement('input'); zone.id = 'agenda-repeat-zone';
  zone.maxLength = 80; zone.placeholder = '例如 Asia/Shanghai 或 UTC+08:00';
  const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  zone.value = browserZone(); zoneLabel.append(zone); controls.append(repeatLabel, zoneLabel);
  const hint = node('p', '首个时间使用上方显示的本地时间。周期按此时区保留当地钟点；月底不足时取当月最后一天，之后恢复原日期。投递确认或已过期后安排下一次，未知或失败不自动重发。', 'hint');
  controls.style.marginTop = '12px'; form.insertBefore(controls, form.querySelector('.actions'));
  controls.after(hint);
  const heading = document.querySelector('#view-agenda > .panel h2');
  if (heading) heading.textContent = 'TLS 日程表';
  const intro = document.querySelector('#view-agenda > .panel .hint');
  if (intro) intro.textContent = '创建单次或周期日程，使用同一提醒队列和发送权限。取消会停止当前及后续周期；恢复须明确选择新的未来时间。';
  document.querySelectorAll('[data-view="agenda"],[data-open-entry="agenda"]').forEach(button => {
    if (button.textContent.includes('一次性日程')) button.textContent = '日程表';
  });
  const pendingRequests = new Map();
  const scopeKey = scope => JSON.stringify(['platform','bot_id','user_id','character_id','session_id'].map(key=>scope[key]));
  const current = generation => generation === state.generation;
  const errorCode = error => Number(error && (error.status || error.statusCode));
  const ruleOf = row => row?.metadata?.recurrence || null;
  const describe = row => {
    const rule = ruleOf(row);
    return rule ? `${labels[rule.repeat] || rule.repeat} · ${rule.timezone} · 第 ${(row.metadata.sequence || 0)+1} 次` : '单次日程';
  };
  const canRestore = row => ['cancelled','expired','failed'].includes(row.status)
    || row.metadata?.recurrence_state === 'needs_review';
  function setRule(row) {
    const rule = ruleOf(row); repeat.value = rule?.repeat || 'none'; zone.value = rule?.timezone || browserZone();
    zone.disabled = repeat.value === 'none';
  }
  repeat.addEventListener('change', () => { zone.disabled = repeat.value === 'none'; });
  const resetOriginal = resetAgendaEditor;
  resetAgendaEditor = function() { resetOriginal(); setRule(null); $('agenda-form-title').textContent='创建日程'; };
  const editOriginal = beginAgendaEdit;
  beginAgendaEdit = async function(id, scope, generation) {
    await editOriginal(id, scope, generation);
    if (current(generation) && state.agendaEditing?.row.id === id) {
      setRule(state.agendaEditing.row); $('agenda-form-title').textContent = '编辑日程';
    }
  };
  const dialogOriginal = openAgendaDialog;
  openAgendaDialog = async function(id, cancel, scope, generation) {
    await dialogOriginal(id, cancel, scope, generation);
    if (!current(generation) || state.agendaDialog?.row.id !== id) return;
    const row = state.agendaDialog.row;
    $('agenda-dialog-meta').textContent += '\n重复：' + describe(row);
    if (ruleOf(row) && cancel) $('agenda-dialog-confirm').textContent = '确认停止此项及后续周期';
    else $('agenda-dialog-confirm').textContent = '确认取消此项日程';
    if (row.metadata?.last_occurrence) $('agenda-dialog-meta').textContent +=
      '\n上次：' + phoneTime(row.metadata.last_occurrence.due_at*1000) + ' · ' + row.metadata.last_occurrence.status;
  };
  async function beginRestore(id, scope, generation) {
    if (state.agendaCreating) return;
    try {
      const response = await api('GET','page/agenda/detail',{...scope,id});
      if (!current(generation)) return;
      const row = response.record;
      if (!canRestore(row)) throw inputError('该日程当前不能恢复；未知发送结果须先对账。');
      const due = new Date(row.due_at).getTime() > Date.now() ? row.due_at : new Date(Date.now()+3600000).toISOString();
      state.agendaEditing = {row,scope:{...scope},generation,originalLocal:localInput(due),restore:true};
      state.agendaDraft = null; $('agenda-due').value = localInput(due); $('agenda-content').value = row.content;
      setRule(row); $('agenda-form-title').textContent = '恢复日程'; $('agenda-create').textContent = '保存并恢复';
      $('agenda-edit-cancel').hidden = false; $('agenda-create-status').textContent = '';
      $('agenda-edit-context').textContent = '请选择新的未来时间；原执行记录保留，恢复只建立新版本。';
      updateZone('agenda-zone',$('agenda-due').value);
      openCommonEditor('agenda-create-form','恢复日程',currentScopeText()+' · 保存后重新进入同一提醒队列。');
    } catch (error) { notify(scopeOperationError(error,'agenda'),true); }
  }
  async function requestIdentity(scope, requestId) {
    const s = {bot_id:scope.bot_id,character_id:scope.character_id,platform:scope.platform,
      private:true,session_id:scope.session_id,user_id:scope.user_id};
    const digest = await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(['tls.agenda.request.v1',s,requestId])));
    return 'tls.agenda.' + Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2,'0')).join('');
  }
  const normalizedContent = value => value.trim().startsWith('【日程】') ? value.trim() : '【日程】'+value.trim();
  const sameSaved = (row,payload) => row && row.content === normalizedContent(payload.content)
    && (new Date(row.due_at).getTime() === new Date(payload.due_at).getTime()
      || row.metadata?.last_occurrence?.due_at*1000 === new Date(payload.due_at).getTime())
    && (ruleOf(row)?.repeat || 'none') === (payload.repeat || 'none')
    && (!ruleOf(row) || ruleOf(row).timezone === payload.timezone);
  async function reconcilePending(scope, generation) {
    const key = scopeKey(scope), pending = pendingRequests.get(key);
    if (!pending) return;
    try {
      const result = await api('GET','page/agenda/detail',{...scope,id:pending.id});
      if (current(generation) && pendingRequests.get(key)===pending && result.record?.id===pending.id && sameSaved(result.record,pending.payload)) {
        pendingRequests.delete(key); $('agenda-create-status').textContent = '之前的保存已从后台回读确认。';
      }
    } catch (_) { /* Read-only reconciliation never replays a save. */ }
  }
  loadAgenda = async function() {
    const generation = state.generation, request = ++state.agendaRequest;
    if (!state.scope) { empty($('agenda-records'),'先选择完整会话。'); return; }
    const scope = scopeParams(); $('agenda-status').textContent = '正在读取日程表…';
    $('agenda-prev').disabled = true; $('agenda-next').disabled = true;
    try {
      const result = await api('GET','page/agenda/list',{...scope,limit:25,offset:state.agendaOffset});
      if (!current(generation) || request !== state.agendaRequest) return;
      $('agenda-records').replaceChildren();
      for (const row of result.records) {
        const card = node('article',undefined,'record');
        card.append(node('p',row.content,'record-content'),node('p',
          (agendaStates[row.status] || row.status)+' · '+phoneTime(row.due_at),'hint'),
          node('p',describe(row)+' · 版本 '+row.revision+' · 队列 '+(row.task_state || '未入队'),'hint'));
        if (row.metadata?.recurrence_state === 'needs_review') card.append(node('p','周期超出可自动推进范围，请重新选择未来时间恢复。','error-text'));
        const actions = node('div',undefined,'actions');
        const add = (label, handler) => { const b = node('button',label); b.type='button';b.addEventListener('click',handler);actions.append(b); };
        if (agendaCancelable(row)) add('编辑时间与内容',()=>beginAgendaEdit(row.id,scope,generation));
        add('查看详情',()=>openAgendaDialog(row.id,false,scope,generation));
        if (agendaCancelable(row)) add(ruleOf(row)?'停止周期':'取消日程',()=>openAgendaDialog(row.id,true,scope,generation));
        if (canRestore(row)) add('恢复日程',()=>beginRestore(row.id,scope,generation));
        card.append(actions); $('agenda-records').append(card);
      }
      if (!result.records.length) empty($('agenda-records'),'当前范围还没有日程。');
      $('agenda-range').textContent = result.records.length ? '第 '+(state.agendaOffset+1)+'–'+(state.agendaOffset+result.records.length)+' 条' : '暂无结果';
      $('agenda-prev').disabled = state.agendaOffset===0; $('agenda-next').disabled=result.records.length<25;
      $('agenda-status').textContent = '单次及周期日程 · 使用同一提醒服务，保留历史执行记录';
      await reconcilePending(scope,generation);
    } catch (error) {
      if (current(generation) && request===state.agendaRequest) $('agenda-status').textContent=scopeOperationError(error,'agenda');
    }
  };
  $('agenda-refresh').addEventListener('click',event=>{event.stopImmediatePropagation();loadAgenda();},true);
  form.addEventListener('submit', async event => {
    const editing = state.agendaEditing;
    // One capture handler owns all agenda writes. The original bubble handler
    // remains installed but cannot issue a second POST for this submission.
    event.preventDefault(); event.stopImmediatePropagation();
    if (!state.scope || state.agendaCreating) return;
    const generation=state.generation, scope=scopeParams(), key=scopeKey(scope), local=$('agenda-due').value, content=$('agenda-content').value;
    state.agendaCreating=true; $('agenda-create').disabled=true;$('agenda-edit-cancel').disabled=true;$('agenda-new').disabled=true;
    try {
      if (pendingRequests.has(key)) throw inputError('前一次保存结果待确认，请先刷新日程核对；不会重复提交。');
      if (editing && (editing.generation!==generation || !sameScope(editing.scope,scope))) throw inputError('会话已改变，请重新读取。');
      const due=editing && local===editing.originalLocal ? editing.row.due_at : absoluteLocal(local);
      const recurrence={repeat:repeat.value,...(repeat.value==='none'?{}:{timezone:zone.value.trim()})};
      const signature=JSON.stringify([scope,due,content,recurrence]); let payload,path,id;
      if (editing) {
        id=editing.row.id;payload={scope,id,expected_revision:editing.row.revision,due_at:due,content,...recurrence};
        path='page/agenda/'+(editing.restore?'restore':'update');
      } else {
        if (!state.agendaDraft || state.agendaDraft.signature!==signature) state.agendaDraft={signature,
          payload:{scope,request_id:'webui.agenda.'+tlsUuid().replaceAll('-',''),due_at:due,content,...recurrence}};
        payload=state.agendaDraft.payload;path='page/agenda/create'; id=await requestIdentity(scope,payload.request_id);
      }
      if (!current(generation)) return;
      $('agenda-create-status').textContent='正在保存日程并重新读取…';
      pendingRequests.set(key,{id,scope,payload});
      let saved;
      try { saved=await api('POST',path,payload); }
      catch (error) { if ([400,401,403,404,409].includes(errorCode(error))) pendingRequests.delete(key); throw error; }
      if (!current(generation)) return;
      const verified=await api('GET','page/agenda/detail',{...scope,id});
      if (!current(generation)) return;
      if (verified.record?.id!==id || !sameSaved(verified.record,payload) || verified.record.revision<saved.record?.revision) throw inputError('保存后回读未能确认，请刷新日程核对。');
      pendingRequests.delete(key); state.agendaDraft=null;
      if (editing) {
        state.agendaEditing={...editing,row:verified.record,restore:false,originalLocal:localInput(verified.record.due_at)};
        $('agenda-form-title').textContent='编辑日程';$('agenda-create').textContent='保存修改';$('agenda-edit-context').textContent='已从后台回读确认 · 版本 '+verified.record.revision;
        markEditorSaved('agenda-create-form');
      } else resetAgendaEditor();
      state.agendaOffset=0; await loadAgenda();
      if (!current(generation)) return;
      $('agenda-create-status').textContent=editing?.restore?'日程已恢复，并从后台重新读取确认。':editing?'日程已修改，并从后台重新读取确认。':payload.repeat==='none'?'单次日程已创建，并从后台重新读取确认。':'周期日程已创建，并从后台重新读取确认。';
      notify('日程已保存；实际投递仍由原生提醒服务核验。');
    } catch (error) {
      if (current(generation)) $('agenda-create-status').textContent=scopeOperationError(error,'agenda')+(pendingRequests.has(key)?' 保存结果待确认，请刷新列表核对。':'');
    } finally {
      state.agendaCreating=false;$('agenda-create').disabled=!state.scope || state.busy>0;
      $('agenda-edit-cancel').disabled=false;$('agenda-new').disabled=false;
    }
  },true);
  setRule(null);
  if (!state.agendaEditing) $('agenda-form-title').textContent='创建日程';
})();
