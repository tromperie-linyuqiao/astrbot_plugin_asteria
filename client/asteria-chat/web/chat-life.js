'use strict';
/* An on-demand view of the TLS life ledger. No local event cache, model,
   scheduler, message writer or automatic follow-up sender lives here. */
window.ChatLife = (() => {
  let dialog, body, note, refresh, back, tabs, heading, searchForm, searchInput, searchGo;
  let owner = '', session = '', ownerAuth = null, epoch = 0, serial = 0, busy = false;
  let overview = null, detail = null, view = 'today', selection = null, editor = null;
  let searchData = null, listStale = false, restorePosition = null;
  let catalogKind,catalogShared,catalogFrom,catalogTo;
  const positions = new Map(), trail = [];
  let worldline = null, linking = null;
  const linkPending = new Map();
  const pending = new Map(); // Only unfinished user corrections, never ledger data.
  const statuses = { ongoing: '进行中', completed: '已结束', cancelled: '已取消', open: '仍在继续', resolved: '已解决' };
  const kinds = { canonical: '正典人物', recurring: '原创常驻人物', temporary: '临时人物' };
  const sharing = { unshared: '尚未分享', queued: '已进入分享队列', confirmed: '原发送端已确认分享', failed: '分享失败', unknown: '分享结果待核对', dismissed: '已放下这个分享话题' };
  const scope = () => JSON.stringify([state.server, state.username, state.activeId, state.sessionPersonaConfig?.configuredId || '']);
  const auth = () => typeof chatAuthEpoch === 'number' ? chatAuthEpoch : null;
  const ticket = () => ({ owner, session, epoch, auth: auth(), serial: ++serial });
  const sameOwner = t => dialog?.open && state.authenticated && owner === scope() && t.owner === owner && t.session === session && t.epoch === epoch && t.auth === auth();
  const current = t => sameOwner(t) && t.serial === serial;
  const make = (tag, value, className = '') => { const n = document.createElement(tag); if (value !== undefined) n.textContent = value; n.className = className; return n; };
  const button = (label, fn, className = 'text-button') => { const n = make('button', label, className); n.type = 'button'; n.addEventListener('click', fn); return n; };
  const fields = record => record?.fields || {};
  const validId = value => typeof value === 'string' && value.length > 0 && value.length <= 160 && !/[\u0000-\u001f]/.test(value);
  const key = id => owner + '|' + id;
  const time = value => { if (value == null || value === '') return '时间未记录'; const d = new Date(typeof value === 'number' ? value * 1000 : value); return Number.isFinite(d.getTime()) ? d.toLocaleString('zh-CN', { hour12: false }) : '时间未记录'; };
  const eventName = record => fields(record).title || '未命名经历';
  const recordName = (kind, record) => kind === 'character' ? fields(record).name || '未命名人物' : eventName(record);
  const selectedRecord = () => detail?.[{ event: 'event', character: 'person', thread: 'thread' }[selection?.kind]];
  const parameter = kind => ({ event: 'event_id', character: 'person_id', thread: 'thread_id' })[kind];
  const listKey = () => searchData ? 'search:' + JSON.stringify([searchData.query,searchData.kind,searchData.date_from,searchData.date_to,searchData.shared]) : view;
  const catalogFilter=()=>({kind:catalogKind.value,date_from:catalogFrom.value,date_to:catalogTo.value,shared:catalogShared.value});
  const say = value => { note.textContent = value; };
  function controls() {
    refresh.disabled = back.disabled = busy;
    searchInput.disabled = searchGo.disabled = busy;
    for(const control of [catalogKind,catalogShared,catalogFrom,catalogTo])if(control)control.disabled=busy;
    for (const n of body.querySelectorAll('button,input,textarea,select')) n.disabled = busy || n.dataset.unavailable === 'true';
    if(linking?.save)linking.save.disabled=busy||linking.save.dataset.unavailable==='true'||linkPending.has(linkKey());
    if (editor?.save) editor.save.disabled = busy || !editor.confirm.checked || editor.stale || pending.has(key(editor.record.id));
    for (const n of tabs.querySelectorAll('button')) n.disabled = busy;
  }
  function invalidate() {
    worldline = linking = null;
    epoch++; serial++; owner = session = ''; ownerAuth = null; busy = false; overview = detail = selection = editor = searchData = restorePosition = null; listStale = false; positions.clear(); trail.length = 0;
    body?.replaceChildren(); if (body) delete body.dataset.listKey; if (note) note.textContent = '';
  }
  function closeActive() { if (!dialog?.open) return false; dialog.close(); invalidate(); return true; }
  function scopeChanged() { if (owner && (!state.authenticated || owner !== scope() || ownerAuth !== auth())) closeActive(); }
  function setup() {
    if (dialog) return;
    dialog = make('dialog', undefined, 'settings-dialog life-dialog'); dialog.id = 'life-dialog'; dialog.setAttribute('aria-labelledby', 'life-title');
    const form = make('div', undefined, 'settings-form');
    const top = make('div', undefined, 'dialog-heading'); back = button('‹', () => returnToList(), 'icon-button'); back.id = 'life-back'; back.setAttribute('aria-label', '返回生活档案列表');
    heading = make('h2', '生活档案'); heading.id = 'life-title'; const close = button('×', closeActive, 'icon-button'); close.id = 'life-close'; close.setAttribute('aria-label', '关闭生活档案'); top.append(back, heading, close);
    const intro = make('p', '她的近况、熟悉的人和未完的故事', 'life-intro'); intro.append(make('small', '角色虚构生活档案', 'life-origin')); intro.append(button('私人空间与兴趣',()=>window.ChatPersonalSpace?.open(),'text-button')); form.append(top, intro);
    tabs = make('nav', undefined, 'life-tabs'); tabs.setAttribute('aria-label', '生活档案分类');
    for (const [id, label] of [['today', '今日'], ['recent', '近期'], ['ongoing', '进行中'], ['people', '人物']]) { const n = button(label, () => { rememberList(); view = id; searchData = selection = editor = null; searchInput.value = ''; if (overview && !listStale) renderOverview(); else void read(); }, 'life-tab'); n.dataset.lifeTab = id; tabs.append(n); }
    searchForm = make('form', undefined, 'life-search'); searchForm.setAttribute('role', 'search');
    searchInput = make('input'); searchInput.id = 'life-search'; searchInput.type = 'search'; searchInput.maxLength = 120; searchInput.placeholder = '搜索经历、人物、兴趣或收藏'; searchInput.setAttribute('aria-label', '搜索生活档案');
    searchGo = make('button', '搜索', 'text-button'); searchGo.type = 'submit';
    searchForm.append(searchInput, searchGo); searchForm.addEventListener('submit', event => { event.preventDefault(); if (!busy) void searchRecords(searchInput.value.trim()); });
    const filter=make('details',undefined,'life-catalog-filter');filter.append(make('summary','分类、日期与分享筛选'));
    const grid=make('div',undefined,'life-catalog-fields');
    const choice=(label,id,options)=>{const row=make('label'),select=make('select');select.id=id;select.setAttribute('aria-label',label);for(const [key,text]of options){const option=make('option',text);option.value=key;select.append(option);}row.append(make('span',label),select);grid.append(row);return select;};
    catalogKind=choice('资料类型','life-catalog-kind',[['all','全部档案'],['event','经历'],['character','人物'],['thread','待续事项'],['interest','兴趣'],['exploration','探索'],['collection','收藏'],['space','空间'],['item','物件']]);
    catalogShared=choice('分享记录','life-catalog-shared',[['','不限'],['true','已确认分享'],['false','尚未确认分享']]);
    const date=(label,id)=>{const row=make('label'),input=make('input');input.type='date';input.id=id;input.setAttribute('aria-label',label);row.append(make('span',label),input);grid.append(row);return input;};
    catalogFrom=date('起始日期','life-catalog-from');catalogTo=date('结束日期','life-catalog-to');
    filter.append(grid,make('p','按角色时区筛选：经历用发生日期，其他资料用更新日期；分享筛选覆盖全部记录。','life-muted'));searchForm.append(filter);
    tabs.append(button('全部档案',()=>{if(!busy){selection=null;catalogKind.value='all';void searchRecords(searchInput.value.trim());}},'life-tab'));
    body = make('section', undefined, 'life-body'); body.id = 'life-body';
    const actions = make('div', undefined, 'life-toolbar'); refresh = button('重新读取', () => read()); refresh.id = 'life-refresh'; actions.append(refresh);
    note = make('p', '', 'life-note'); note.id = 'life-note'; note.setAttribute('role', 'status'); note.setAttribute('aria-live', 'polite');
    form.append(searchForm, tabs, body, actions, note); dialog.append(form); document.body.append(dialog);
    dialog.addEventListener('cancel', event => { event.preventDefault(); closeActive(); }); dialog.addEventListener('close', () => { if (!dialog.open) invalidate(); });
  }
  function card(title, className = '') { const n = make('article', undefined, 'life-card ' + className); if (title) n.append(make('h3', title)); return n; }
  function recordNote(record) {
    if (record?.archived) return '已归档 · 保留历史';
    if (record?.valid === false) return '关联资料已变化 · 待复核';
    return '';
  }
  function shareLabel(receipt, version) {
    const value = fields(receipt), state = receipt?.state || value.state;
    let label = sharing[state] || '分享状态待核对';
    const sharedVersion = receipt?.event_version ?? value.event_version;
    if (state === 'confirmed' && (receipt?.is_current_version === false || sharedVersion != null && version != null && sharedVersion !== version)) label += '（旧版本）';
    return label;
  }
  function eventCard(record) {
    const f = fields(record), row = card();
    row.dataset.lifeRecord = 'event:' + record.id;
    row.append(button(eventName(record), () => openEvent(record.id), 'life-event-title'), make('small', time(f.occurred_at) + ' · ' + (statuses[f.status] || '状态未提供')));
    row.append(make('p', String(f.content || '').slice(0, 220), 'life-preview'));
    const sharingState = record.sharing;
    const metadata = [recordNote(record), sharingState ? shareLabel(sharingState, record.version) : ''].filter(Boolean).join(' · ');
    if (metadata) row.append(make('small', metadata));
    return row;
  }
  function rememberList() { if (!selection && body?.dataset.listKey === listKey()) positions.set(listKey(), readingPosition()); }
  function readingPosition() {
    if (body.scrollTop <= 1) return { scrollTop: 0, key: null, offset: 0 };
    const top = body.getBoundingClientRect().top;
    const row = [...body.querySelectorAll('[data-life-record]')].find(node => node.getBoundingClientRect().bottom > top + 1);
    return { scrollTop: body.scrollTop, key: row?.dataset.lifeRecord, offset: row ? row.getBoundingClientRect().top - top : 0 };
  }
  function restoreReading(position) {
    if (!position) { body.scrollTop = 0; return; }
    body.scrollTop = position.scrollTop;
    const row = [...body.querySelectorAll('[data-life-record]')].find(node => node.dataset.lifeRecord === position.key);
    if (row) body.scrollTop += row.getBoundingClientRect().top - body.getBoundingClientRect().top - position.offset;
  }
  function timeline(rows, destination = body) {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const tomorrow = new Date(today); tomorrow.setDate(today.getDate() + 1);
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
    const groups = new Map([['今天', []], ['昨天', []], ['更早', []], ['时间未记录', []]]);
    for (const row of [...rows].sort((a, b) => (Number(fields(b).occurred_at) || 0) - (Number(fields(a).occurred_at) || 0))) {
      const value = fields(row).occurred_at, at = typeof value === 'number' && Number.isFinite(value) ? value * 1000 : NaN;
      const name = !Number.isFinite(at) ? '时间未记录' : at >= today.getTime() && at < tomorrow.getTime() ? '今天' : at >= yesterday.getTime() && at < today.getTime() ? '昨天' : '更早';
      groups.get(name).push(row);
    }
    for (const [name, records] of groups) if (records.length) { const group = make('section', undefined, 'life-timeline-group'); group.append(make('h3', name, 'life-day')); for (const row of records) group.append(eventCard(row)); destination.append(group); }
  }
  function links(title, rows) {
    const box = card(title);
    for (const row of rows || []) if (validId(row?.id)) { box.append(button(eventName(row), () => openEvent(row.id), 'life-link')); if (row.valid === false || row.archived) box.append(make('small', recordNote(row))); }
    if (!box.querySelector('button')) box.append(make('p', '目前没有关联记录。', 'life-muted'));
    return box;
  }
  function stateCard() {
    const card = make('div', undefined, 'life-state'), status = overview.status || {}, policy = fields(overview.policy).enabled === undefined ? overview.policy || {} : fields(overview.policy);
    const enabled = policy.enabled, budget = status.budget || {};
    const paused = ['paused_budget', 'budget_exhausted'].includes(status.state) || [budget.model_calls, budget.events].some(value => value?.limit === 0);
    card.classList.toggle('is-paused', paused);
    card.append(make('strong', paused ? '后台生成已暂停，生活档案仍可查阅' : enabled === true ? '自动生活推进已启用' : enabled === false ? '自动生活推进未启用' : '推进配置尚未提供'));
    const names = { disabled: '当前关闭', ready: '当前可用，等待原调度评估', not_registered: '等待正常聊天建立执行来源', running: '当前生活作业正在执行', deferred: '本次评估已延后', waiting: '等待下次生活评估', paused_budget: '后台生成已暂停，生活档案仍可查阅', budget_exhausted: '本期预算已用完，生活档案仍可查阅', model_unavailable: '后台模型暂不可用，生活档案仍可查阅', failed: '最近推进未完成，已有经历保留', needs_review: '本次内容需要核对，尚未成为正式经历', quiet: '这一段时间很平静，没有新增经历' };
    if (status.state) card.append(make('p', status.reason_label || names[status.state] || '执行状态待核对'));
    if (typeof status.model?.configured === 'boolean') card.append(make('small', status.model.configured ? status.model.availability_label || (status.model.availability === 'not_verified' ? '后台模型已配置，上游可用性尚未验证。' : '后台模型已配置；这不代表已经推进或生成了事件。') : '后台模型尚未配置，已有生活记录仍可查阅。'));
    for (const [name, label, unit] of [['model_calls', '后台调用', '次'], ['events', '新经历', '条']]) {
      const value = budget[name];
      if (Number.isFinite(value?.used) && Number.isFinite(value?.limit)) card.append(make('small', label + '：' + value.used + ' / ' + value.limit + ' ' + unit + (Number.isFinite(value.remaining) ? ' · 剩余 ' + value.remaining + ' ' + unit : ''), 'life-budget'));
    }
    if (status.can_advance === false && status.advance_block_label && status.advance_block_label !== status.reason_label) card.append(make('small', status.advance_block_label));
    if (status.next_automatic_at) card.append(make('small', '下次自动评估：' + time(status.next_automatic_at)));
    else if (status.next_eligible_at) card.append(make('small', '最早可再评估：' + time(status.next_eligible_at)));
    if (status.last_error) {
      const error = status.last_error, codes = [];
      if (Number.isInteger(error.http_status)) codes.push('HTTP ' + error.http_status);
      if (typeof error.upstream_code === 'number' || typeof error.upstream_code === 'string' && /^[A-Za-z0-9_:-]{1,40}$/.test(error.upstream_code)) codes.push('上游 ' + error.upstream_code);
      card.append(make('small', (error.error_label || '最近后台请求未完成') + (codes.length ? '（' + codes.join(' · ') + '）' : ''), 'life-last-error'));
    }
    if (status.last_attempt_at) card.append(make('small', '最近评估：' + time(status.last_attempt_at)));
    if (status.last_result) { const result = status.last_result; card.append(make('p', typeof result === 'string' ? names[result] || '已记录一次评估结果' : result.reason_label || result.summary || names[result.state] || (result.state === 'recorded' ? '最近已保存一段新经历' : '已记录一次评估结果'))); }
    const currentState = overview.current_state || {};
    if (currentState.summary) card.append(make('p', currentState.summary));
    if (validId(currentState.latest_event_id)) { const latest = overview.events.find(row => row.id === currentState.latest_event_id); card.append(button('最近一段经历：' + (latest ? eventName(latest) : '查看当前关联'), () => openEvent(currentState.latest_event_id), 'life-link')); }
    if (typeof status.share_enabled === 'boolean') card.append(make('small', status.share_enabled ? '分享候选可交给现有主动陪伴评估，启用不代表已发送。' : '自动分享当前关闭，已有经历仍可查看与追问。'));
    if (Array.isArray(policy.muted_topics) && policy.muted_topics.length) card.append(make('small', '减少分享的话题：' + policy.muted_topics.join('、')));
    return card;
  }
  function dailyOverview() {
    const schedule=overview.schedule;let zone=typeof schedule?.timezone==='string'?schedule.timezone:'',offset=null;
    const fixed=/^UTC([+-])(\d{2}):(\d{2})$/.exec(zone);
    if(fixed&&Number(fixed[2])<=14&&Number(fixed[3])<60&&(Number(fixed[2])<14||Number(fixed[3])===0))offset=(Number(fixed[2])*60+Number(fixed[3]))*(fixed[1]==='-'?-1:1);
    else if(zone){try{new Intl.DateTimeFormat('zh-CN',{timeZone:zone}).format();}catch(_){zone='';}}
    const scheduleTime=value=>{if(value==null||value===0)return '未记录';const date=new Date(typeof value==='number'?value*1000:value);if(!Number.isFinite(date.getTime()))return '时间未记录';return offset!==null?new Date(date.getTime()+offset*60000).toLocaleString('zh-CN',{hour12:false,timeZone:'UTC'}):date.toLocaleString('zh-CN',{hour12:false,...(zone?{timeZone:zone}:{})});};
    const brief=overview.daily_brief||{},saved=overview.current_state||{},box=card('近况快读','life-brief');
    box.append(make('p',brief.summary||saved.summary||(brief.current||brief.next?'尚无近况摘要，下面显示已有记录。':'还没有可用的近况记录。')));
    const stamp=brief.as_of||saved.updated_at;
    box.append(make('small','记录更新：'+scheduleTime(stamp)));
    const labels=[['current','目前记录'],['next','接下来安排']];
    for(const [key,label]of labels){const value=brief[key];if(value){const text=typeof value==='string'?value:value.title||value.summary;if(text)box.append(make('p',label+'：'+text,'life-brief-line'));}}
    if(validId(saved.latest_event_id))box.append(button('查看最近关联经历',()=>openEvent(saved.latest_event_id),'life-link'));
    body.append(box);
    const section=make('section',undefined,'life-schedule');section.setAttribute('aria-label','角色日程');
    section.append(make('h3',schedule?.date?'日程 · '+schedule.date:'角色日程'));
    if(!schedule||!Array.isArray(schedule.items)){section.append(make('p','此服务器尚未提供角色日程投影；已有生活档案仍可查阅。','life-empty'));body.append(section);return;}
    section.append(make('small',zone?'日程时区：'+zone:'日程时间按设备时区显示','life-muted'));
    section.append(make('small','日程记录更新：'+scheduleTime(schedule.updated_at),'life-muted'));
    const states={planned:'计划中',ongoing:'进行中',completed:'已完成',cancelled:'已取消'};
    const rows=[...schedule.items].filter(row=>row&&typeof row.title==='string').sort((a,b)=>(Number(a.start_at)||0)-(Number(b.start_at)||0));
    if(!rows.length)section.append(make('p',schedule.reason||(schedule.available===false?'当前日程服务尚不可用。':'当前没有已记录的日程安排。'),'life-empty'));
    for(const value of rows){const row=make('article',undefined,'life-schedule-row');row.dataset.scheduleId=String(value.id||'');row.dataset.status=Object.hasOwn(states,value.status)?value.status:'unknown';
      const when=make('div',undefined,'life-schedule-time');when.append(make('span',scheduleTime(value.start_at)),make('small',states[value.status]||'状态未提供','life-schedule-status'));row.append(when);
      const detail=make('div',undefined,'life-schedule-detail');detail.append(make('strong',value.title));if(value.end_at)detail.append(make('small','计划结束：'+scheduleTime(value.end_at)));if(value.detail)detail.append(make('p',value.detail));
      if(validId(value.event_id))detail.append(button('查看关联经历',()=>openEvent(value.event_id),'life-link'));
      detail.append(button('问问这件事',()=>{
        const input=document.getElementById('draft');if(input.disabled||busy)return;const question='想问问你日程里“'+value.title+'”这件事。',text=input.value?input.value+'\n\n'+question:question;
        if(text.length>(input.maxLength>0?input.maxLength:16000)){say('草稿过长，请先整理当前输入。');return;}input.value=text;saveDraft();input.dispatchEvent(new Event('input',{bubbles:true}));closeActive();input.focus();showNotice('问题已加入草稿，可编辑后再发送。');
      },'life-link'));row.append(detail);section.append(row);
    }
    section.append(make('p','状态按服务器记录显示；到达计划时间不会自动标记完成。','life-muted'));body.append(section);
  }
  function renderOverview() {
    detail = selection = editor = null; heading.textContent = '生活档案'; tabs.hidden = searchForm.hidden = false; back.hidden = true; body.replaceChildren(); body.dataset.listKey = view;
    for (const n of tabs.querySelectorAll('button')) n.setAttribute('aria-pressed', String(n.dataset.lifeTab === view));
    if (!overview) { body.append(make('p', '重新读取服务器生活档案。', 'life-muted')); controls(); return; }
    if(view==='today')dailyOverview();
    const runtime=make('details',undefined,'life-runtime');runtime.append(make('summary','生活推进与记录状态'),stateCard());body.append(runtime);
    if (view === 'today') { /* Current record and schedule are above. */
    } else if (view === 'recent') {
      const rows = overview.events.filter(row => validId(row?.id));
      timeline(rows);
      if (!rows.length) body.append(make('p', '近期没有新的生活事件。平静的日常也可以不产生新故事。', 'life-empty'));
    } else if (view === 'ongoing') {
      const rows = overview.ongoing.filter(row => validId(row?.id));
      for (const record of rows) body.append(threadCard(record));
      if (!rows.length) body.append(make('p', '目前没有仍在继续的事项。', 'life-empty'));
    } else {
      const rows = overview.people.filter(row => validId(row?.id));
      for (const person of rows) body.append(personCard(person, true));
      if (!rows.length) body.append(make('p', '还没有相关人物档案。偶遇的人不必立即成为常驻人物。', 'life-empty'));
    }
    if(linking){heading.textContent='关联这条聊天';body.prepend(make('p','选择一段经历，再确认关联方式。原聊天内容不会改写。','life-link-intro'));}
    restoreReading(positions.get(view)); say('已从 TLS 读取。查看档案不会推进生活或发送消息。'); controls();
  }
  function personCard(person, expanded = false) {
    const f = fields(person), row = card(); row.dataset.lifeRecord = 'character:' + person.id;
    row.append(button(f.name || '未命名人物', () => openRecord('character', person.id), 'life-record-title'), make('small', [kinds[f.kind] || '人物类型未提供', recordNote(person)].filter(Boolean).join(' · ')));
    if (f.description) row.append(make('p', f.description)); if (f.relationship) row.append(make('p', '当前关系：' + f.relationship));
    if (expanded) { const more = make('details'); more.append(make('summary', '相关经历（' + (f.event_ids || []).length + '）'));
      for (const id of f.event_ids || []) { const event = overview?.events.find(value => value.id === id); more.append(button(event ? eventName(event) : '查看相关经历', () => openEvent(id), 'life-link')); } row.append(more); }
    return row;
  }
  function threadCard(record) {
    const f = fields(record), row = card(); row.dataset.lifeRecord = 'thread:' + record.id;
    row.append(button(f.title || '未完成的事情', () => openRecord('thread', record.id), 'life-record-title'), make('small', [statuses[f.status] || '状态未提供', recordNote(record)].filter(Boolean).join(' · ')), make('p', f.detail || '尚无补充说明'));
    return row;
  }
  function renderDetail() {
    editor = null; tabs.hidden = searchForm.hidden = true; back.hidden = false; back.setAttribute('aria-label', trail.length ? '返回上一条档案' : '返回生活档案列表'); heading.textContent = { event: '这段经历', character: '相关人物', thread: '相关事项' }[selection?.kind] || '生活档案'; body.replaceChildren(); delete body.dataset.listKey; body.scrollTop = 0;
    if (selection?.kind !== 'event') { renderRelatedDetail(); return; }
    const record = detail.event, f = fields(record), main = card(eventName(record));
    main.append(make('small', [time(f.occurred_at), statuses[f.status] || '状态未提供', recordNote(record)].filter(Boolean).join(' · ')), make('p', f.content || '暂无正文', 'life-content'));
    const actions = make('div', undefined, 'life-event-actions'), ask = button('追问这段经历', followUp, 'primary-button'), correct = button('纠正内容', () => editEvent());
    ask.dataset.unavailable = String(record.valid === false || record.archived === true); correct.dataset.unavailable = String(record.archived === true); actions.append(ask, correct, button('查看世界线',()=>openWorldline(record.id))); main.append(actions); body.append(main);
    for (const person of detail.related?.people || []) body.append(personCard(person));
    body.append(links('前面的经历', detail.related?.previous), links('后来的经历', detail.related?.following));
    const threads = card('关联事项'); for (const item of detail.threads || []) threads.append(threadCard(item));
    if (!(detail.threads || []).length) threads.append(make('p', '没有关联的未完事项。', 'life-muted')); body.append(threads);
    const shares = card('分享记录'); for (const receipt of detail.shares || []) shares.append(make('p', shareLabel(receipt, record.version) + ' · ' + time(receipt.at ?? fields(receipt).at)));
    if (!(detail.shares || []).length) shares.append(make('p', '尚无分享回执。值得分享不等于已经发送。', 'life-muted')); body.append(shares);
    const history = make('details', undefined, 'life-history'); history.append(make('summary', '修正历史（' + (detail.history || []).length + '）'));
    for (const old of detail.history || []) { const version = old.snapshot || old.record || old, value = fields(version); history.append(make('p', '版本 ' + (version.version ?? old.version ?? '未提供') + ' · ' + (value.title || eventName(record))), make('p', value.content || '原内容未提供', 'life-preview')); } body.append(history);
    renderChatLinks(detail.chat_links || []);
    if(linking) renderLinkForm(record);
    const operation = pending.get(key(record.id)); if (operation?.phase === 'unknown') { if (operation.read) body.append(button('已核对当前版本，结束等待', () => { pending.delete(key(record.id)); renderDetail(); say('已结束上次操作的等待；如需继续纠正，请重新比较当前版本。'); }, 'life-link')); say(operation.read ? '上次保存结果待核对。当前显示服务器版本，应用不会重新提交。' : '上次保存结果待核对。请重新读取当前版本，应用不会重新提交。'); }
    else say(record.archived ? '此记录已归档，仅供查阅。' : record.valid === false ? '这条经历待复核；可纠正内容，核对前不能追问。' : '虚构经历来自当前有效档案；追问会先加入可编辑输入框。'); controls();
  }
  function renderRelatedDetail() {
    const record = selectedRecord(), f = fields(record), person = selection.kind === 'character';
    const main = card(recordName(selection.kind, record));
    main.append(make('small', [person ? kinds[f.kind] || '人物类型未提供' : statuses[f.status] || '状态未提供', recordNote(record)].filter(Boolean).join(' · ')));
    main.append(make('p', person ? f.description || '尚无人物补充说明。' : f.detail || '尚无事项补充说明。', 'life-content'));
    if (person && f.relationship) main.append(make('p', '当前关系：' + f.relationship));
    const ask = button(person ? '聊聊这个人' : '接着聊这件事', followUp, 'primary-button'); ask.dataset.unavailable = String(record.valid === false || record.archived === true); main.append(ask); body.append(main);
    if (!person) for (const value of detail.people || []) body.append(personCard(value));
    body.append(make('h3', person ? '一起经历过的事' : '相关经历', 'life-day'));
    timeline((detail.events || []).filter(row => validId(row?.id)));
    if (!(detail.events || []).length) body.append(make('p', '目前没有可查看的关联经历。', 'life-empty'));
    say(record.archived ? '此记录已归档，仅供查阅。' : record.valid === false ? '这条资料的关联来源已变化，核对前不能追问。' : '追问会加入当前聊天草稿，可继续编辑后发送。'); controls();
  }
  function validate(data, expectedSession = session) {
    if (!data || data.session_id !== expectedSession) throw Error('生活档案会话不匹配，请重新读取。');
    return data;
  }
  async function read() {
    if (busy || !dialog?.open) return; if(worldline)return openWorldline(worldline.event_id); if (!selection && searchData) return searchRecords(searchData.query);
    rememberList(); const t = ticket(); busy = true; controls(); say('正在读取生活档案…');
    const chosen = selection, editing = editor ? { title: editor.title.value, content: editor.content.value, status: editor.status.value } : null;
    try {
      const operation = chosen?.kind === 'event' && pending.get(key(chosen.id)); if (operation?.promise) { try { await operation.promise; } catch (_) {} if (!current(t)) return; }
      const data = validate(await apiClient.json('GET', '/chat/life?session_id=' + encodeURIComponent(t.session) + (chosen ? '&' + parameter(chosen.kind) + '=' + encodeURIComponent(chosen.id) : '')), t.session); if (!current(t)) return;
      if (chosen) { const record = data[{ event: 'event', character: 'person', thread: 'thread' }[chosen.kind]]; if (record?.id !== chosen.id || !Number.isInteger(record.revision)) throw Error('服务器未返回当前档案版本。'); if (operation?.phase === 'unknown') operation.read = true; detail = data; renderDetail(); if (restorePosition) { restoreReading(restorePosition); restorePosition = null; } if (editing) { editEvent(editing); say('已读取服务器当前版本，未提交的编辑已保留，请比较后再确认。'); } }
      else { if (![data.events, data.ongoing, data.people].every(Array.isArray)) throw Error('服务器未返回可读取的生活列表。'); overview = data; listStale = false; renderOverview(); }
      return true;
    } catch (error) { if (current(t)) { say(error.status === 404 ? chosen ? '这条档案已不可用，请返回列表重新读取。' : '当前服务器尚未提供生活档案，请更新服务端后再读取。' : errorText(error)); } return false; }
    finally { if (current(t)) { busy = false; controls(); } }
  }

  const worldKinds={event:'经历',character:'人物',thread:'待续事项',interest:'兴趣',exploration:'探索',collection:'收藏',space:'空间',item:'物件'};
  const worldValue=value=>Array.isArray(value)?value.join('；'):({steady:'持续关注',growing:'兴趣渐浓',fading:'兴趣渐淡',active:'进行中',paused:'暂时搁置',completed:'已完成',planned:'待探索',cancelled:'已取消'}[value]||value||'未记录');
  const worldRelations={continues:'延续为',involves:'参与',grounds:'成为来源',explores:'继续探索',collects:'相关收藏',contains:'包含'};
  function worldOpen(row){
    worldline=null;
    if(parameter(row.kind)) { if(selection?.kind===row.kind&&selection.id===row.id)renderDetail();else openRecord(row.kind,row.id); }
    else window.ChatPersonalSpace?.openRecord(row.kind,row.id);
  }
  async function openWorldline(id){
    if(busy||!dialog?.open)return;const t=ticket();busy=true;controls();say('正在读取关联世界线…');
    try{
      const data=validate(await apiClient.json('GET','/chat/life?session_id='+encodeURIComponent(t.session)+'&view=worldline&event_id='+encodeURIComponent(id)),t.session);if(!current(t))return;
      const graph=data.worldline;if(graph?.event_id!==id||!Array.isArray(graph.nodes)||!Array.isArray(graph.edges))throw Error('服务器未返回这段经历的世界线。');
      worldline=graph;heading.textContent='这段经历的世界线';body.replaceChildren();tabs.hidden=searchForm.hidden=true;back.hidden=false;
      const nodes=new Map(graph.nodes.map(n=>[n.id,n])),root=nodes.get(graph.root_id||id);
      body.append(card(root?.title||'世界线','life-world-root'),make('p','只连接已有资料中明确记录的关系；相邻时间不代表发生因果。','life-muted'));
      const sections=new Map();
      for(const row of graph.nodes){if(row.id===(graph.root_id||id))continue;const name=row.kind==='event'?'前后经历':row.kind==='character'?'相关人物':row.kind==='thread'?'仍在继续':'兴趣与私人档案';if(!sections.has(name))sections.set(name,[]);sections.get(name).push(row);}
      for(const [title,rows]of sections){const box=card(title);for(const row of rows){
        const item=make('section',undefined,'life-world-node');item.append(button((worldKinds[row.kind]||'资料')+' · '+row.title,()=>worldOpen(row),'life-link'));
        if(row.summary)item.append(make('p',row.summary));
        if(row.valid===false||row.archived)item.append(make('small','来源已变化或归档 · 待复核，不作为有效前情','life-warning'));
        for(const edge of graph.edges.filter(e=>e.from===row.id||e.to===row.id)){const from=nodes.get(edge.from),to=nodes.get(edge.to);if(from&&to)item.append(make('small',from.title+' → '+(worldRelations[edge.relation]||'关联')+' → '+to.title+(edge.valid===false?'（待复核）':''),'life-world-edge'));}
        box.append(item);
      }body.append(box);}
      if(!sections.size)body.append(make('p','尚无明确关联，不会自动补写故事。','life-empty'));
      const growth=card('有来源的变化');
      for(const row of graph.growth||[]){const item=make('section',undefined,'life-world-node');item.append(make('strong',row.title),make('p',({relationship:'人物关系',attention:'关注变化',status:'状态',findings:'探索发现',next_direction:'下一方向'}[row.field]||row.field)+'：'+worldValue(row.before)+' → '+worldValue(row.after)));
        for(const sourceId of row.source_event_ids||[]){const source=nodes.get(sourceId);item.append(button('来源：'+(source?.title||'相关经历'),()=>{worldline=null;openRecord('event',sourceId);},'life-link'));}
        if(row.valid===false)item.append(make('small','关联来源待复核','life-warning'));growth.append(item);}
      if(!(graph.growth||[]).length)growth.append(make('p','没有可展示的有来源变化；普通经历不会自动改写核心人格。','life-muted'));body.append(growth);
      if(graph.coverage?.truncated)body.append(make('p','关联较多，这里仅显示有限的附近关系；可打开具体资料继续查看。','life-muted'));
      say('按当前档案读取，未调用模型或改写任何经历。');
    }catch(error){if(current(t))say(errorText(error));}
    finally{if(current(t)){busy=false;controls();}}
  }
  const linkTypes={asked_about:'询问过这段经历',interested:'明确对它感兴趣',recommended:'推荐了相关内容',correction:'这条聊天提出纠正',discussed:'一起讨论过'};
  const linkKey=()=>owner+'|'+(selection?.id||'')+'|'+(linking?.messageId||'');
  function renderChatLinks(rows){
    const box=card('我们聊过');for(const [k,operation]of linkPending)if(k.startsWith(owner+'|remove|')&&operation.event_id===selection?.id&&!rows.some(r=>r.id===operation.id))linkPending.delete(k);
    for(const row of rows){const entry=make('section',undefined,'life-world-node');
      entry.append(make('strong',linkTypes[row.relation]||'明确关联'),make('p',row.note||'由你明确关联的一条真实聊天。'));
      entry.append(make('small',row.valid===false?'经历来源已变化 · 待复核':'真实聊天关联，不代表用户现实经历'));
      if(Number.isInteger(row.revision)&&row.id){const remove=button('移除这个关联',()=>{remove.hidden=true;const confirm=button('确认移除关联',()=>forgetChatLink(row),'text-button');entry.append(make('p','只移除这项关联，原聊天与生活经历保留。','life-muted'),confirm);},'life-link');remove.dataset.unavailable=String(linkPending.has(owner+'|remove|'+row.id));entry.append(remove);
        if(linkPending.has(owner+'|remove|'+row.id))entry.append(make('p','移除结果待核对，请重新读取；不会重发。','life-warning'));}
      box.append(entry);
    }if(!rows.length)box.append(make('p','还没有明确关联的聊天，可从消息的“···”中选择“关联生活经历”。','life-muted'));body.append(box);
  }
  async function forgetChatLink(row){
    const eventId=selection?.id,pendingKey=owner+'|remove|'+row.id;if(busy||!eventId||linkPending.has(pendingKey))return;
    const t=ticket(),operation={event_id:eventId,id:row.id,request_id:'life-forget-'+(crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2))};linkPending.set(pendingKey,operation);busy=true;controls();say('正在移除这项关联…');
    try{
      const data=validate(await apiClient.json('POST','/chat/life',{session_id:t.session,action:'forget_link',event_id:eventId,link_id:row.id,expected_revision:row.revision,request_id:operation.request_id}),t.session);
      if(data.link?.id!==row.id||data.link.active!==false||data.link.state!=='removed')throw Error('移除结果尚未确认，请重新读取核对。');
      linkPending.delete(pendingKey);if(!current(t))return;busy=false;await read();if(sameOwner(t))say('已移除关联，原聊天与生活经历保留。');
    }catch(error){if([400,403,404,409].includes(error.status))linkPending.delete(pendingKey);if(current(t))say(errorText(error)+' 结果待核对时请重新读取，不会自动重试。');}
    finally{if(current(t)){busy=false;controls();}}
  }
  function renderLinkForm(record){
    const box=card('将选中的聊天关联到这里'),choose=make('select'),noteInput=make('textarea');choose.setAttribute('aria-label','聊天关联方式');noteInput.setAttribute('aria-label','关联补充说明');noteInput.rows=2;noteInput.maxLength=240;noteInput.placeholder='可选：补充关联原因，不必复制聊天';noteInput.value=linking.note;
    for(const [value,label]of Object.entries(linkTypes)){const o=make('option',label);o.value=value;choose.append(o);}choose.value=linking.relation;
    choose.onchange=()=>linking.relation=choose.value;noteInput.oninput=()=>linking.note=noteInput.value;
    const save=button('确认关联这条聊天',()=>saveChatLink(record),'primary-button');save.dataset.unavailable=String(record.valid===false||record.archived===true);linking.save=save;
    box.append(choose,noteInput,make('p','仅记录你明确确认的关联；不会把虚构经历写成你的现实生活。纠正内容仍需使用“纠正内容”。','life-muted'),save);body.prepend(box);
    const pendingKey=linkKey(),operation=linkPending.get(pendingKey);
    if(operation){const found=(detail.chat_links||[]).some(row=>String(row.message_id)===linking.messageId&&row.relation===operation.relation);
      if(found){linkPending.delete(pendingKey);box.append(make('p','已从服务器核对到这条关联。','life-muted'));save.dataset.unavailable='true';}
      else{box.append(make('p','上次保存结果待核对。可重新读取，应用不会再次提交。','life-warning'));save.dataset.unavailable='true';}}
  }
  async function saveChatLink(record){
    if(busy||!linking||record.valid===false||record.archived||linkPending.has(linkKey()))return;
    const t=ticket(),messageId=linking.messageId,relation=linking.relation,noteText=linking.note.trim(),pendingKey=linkKey();
    const operation={relation,request_id:'life-link-'+(crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2))};linkPending.set(pendingKey,operation);busy=true;controls();say('正在保存明确关联…');
    try{
      const data=validate(await apiClient.json('POST','/chat/life',{session_id:t.session,action:'link_message',event_id:record.id,message_id:messageId,relation,note:noteText,expected_revision:record.revision,request_id:operation.request_id}),t.session);
      if(data.link?.event_id!==record.id||String(data.link?.message_id)!==messageId||data.link?.relation!==relation)throw Error('关联结果尚未确认，请重新读取核对。');
      linkPending.delete(pendingKey);if(!current(t))return;linking=null;busy=false;await read();if(sameOwner(t))say('已保存明确关联；原聊天和经历正文保持。');
    }catch(error){if([400,403,404,409].includes(error.status))linkPending.delete(pendingKey);if(current(t))say(errorText(error)+' 保存结果待核对时请重新读取，不会自动重试。');}
    finally{if(current(t)){busy=false;controls();}}
  }

  function openEvent(id) { openRecord('event', id); }
  function openRecord(kind, id) {
    if(!parameter(kind)&&Object.hasOwn(worldKinds,kind)){window.ChatPersonalSpace?.openRecord(kind,id);return;}
    if (!parameter(kind) || !validId(id) || busy || selection?.kind === kind && selection.id === id) return;
    if (selection) trail.push({ selection, position: readingPosition() }); else rememberList();
    worldline=null; selection = { kind, id }; detail = editor = restorePosition = null; tabs.hidden = searchForm.hidden = true; back.hidden = false; body.replaceChildren(make('p', '正在读取这条档案…')); void read();
  }
  function returnToList() {
    if (busy) return;
    if(worldline){worldline=null;renderDetail();return;}
    if (selection && trail.length) { const previous = trail.pop(); selection = previous.selection; restorePosition = previous.position; editor = null; void read(); return; }
    if (!selection && searchData) { rememberList(); searchData = null; searchInput.value = ''; if (overview && !listStale) renderOverview(); else void read(); return; }
    selection = editor = restorePosition = null;
    if (searchData) { if (listStale) void searchRecords(searchData.query); else renderSearch(); }
    else if (overview && !listStale) renderOverview(); else void read();
  }
  function renderSearch() {
    detail = selection = editor = null; heading.textContent = '找到的档案'; tabs.hidden = searchForm.hidden = false; back.hidden = false; back.setAttribute('aria-label', '返回生活档案列表'); body.replaceChildren(); body.dataset.listKey = listKey();
    for (const n of tabs.querySelectorAll('button')) n.setAttribute('aria-pressed', 'false');
    const data = searchData; body.append(make('p', (data.query?'“'+data.query+'”':'当前筛选') + ' · ' + data.total + ' 条记录', 'life-search-count'));
    body.append(make('p','经历按发生日期、其他资料按更新日期 · '+(data.timezone||'角色时区'),'life-muted'));
    for (const { kind, record } of data.records) { let row;if(kind==='event')row=eventCard(record);else if(kind==='character')row=personCard(record);else if(kind==='thread')row=threadCard(record);else{row=card(fields(record).name||'生活资料');row.append(make('p',(fields(record).description||'').slice(0,180),'life-preview'),button('查看详情',()=>window.ChatPersonalSpace?.openRecord(kind,record.id),'life-link'));}row.prepend(make('small',worldKinds[kind],'life-kind'));body.append(row);}
    if (!data.records.length) body.append(make('p', '暂时没有匹配的档案。可以换个人物名、地点或经历中的词再找找。', 'life-empty'));
    if (data.offset + data.limit < data.total) body.append(button('再看一些', () => searchRecords(data.query, true), 'life-more'));
    restoreReading(positions.get(listKey())); say('结果来自服务器当前有效档案，查看或搜索不会推进生活。'); controls();
  }
  async function searchRecords(query, append = false) {
    if (busy || !dialog?.open || selection) return false;
    const filters=catalogFilter();if(filters.date_from&&filters.date_to&&filters.date_from>filters.date_to){say('结束日期不能早于起始日期。');return false;}
    rememberList(); const t = ticket(), previous = searchData, compatible=previous?.query===query&&previous?.filterKey===JSON.stringify(filters),offset=append&&compatible?previous.offset+previous.limit:0;
    busy = true; controls(); say('正在搜索生活档案…');
    try {
      const params=new URLSearchParams({session_id:t.session,view:'catalog',query,kind:filters.kind,limit:'20',offset:String(offset)});for(const name of ['date_from','date_to','shared'])if(filters[name])params.set(name,filters[name]);
      const data = validate(await apiClient.json('GET', '/chat/life?' + params), t.session); if (!current(t)) return false;
      const result = data.catalog;
      if (!result || result.query !== query || result.kind !== filters.kind || !Array.isArray(result.records) || !Number.isInteger(result.total) || result.total < 0 || result.offset !== offset || !Number.isInteger(result.limit) || result.limit < 1 || result.records.some(row => !Object.hasOwn(worldKinds,row.kind) || !validId(row.record?.id))) throw Error('服务器未返回可读取的搜索结果。');
      const records = append && compatible ? [...previous.records] : [];
      for (const row of result.records) { const at = records.findIndex(value => value.kind === row.kind && value.record.id === row.record.id); if (at < 0) records.push(row); else records[at] = row; }
      searchData = { ...result, records,filterKey:JSON.stringify(filters) }; searchInput.value = query; listStale = false;
      if (!append) { positions.delete(listKey()); searchForm.querySelector('.life-catalog-filter').open=false; } renderSearch(); return true;
    } catch (error) { if (current(t)) say(errorText(error)); return false; }
    finally { if (current(t)) { busy = false; controls(); } }
  }
  async function followUp() {
    const record = selectedRecord(), chosen = selection; if (busy || !record || record.valid === false || record.archived) return; const t = ticket(); busy = true; controls(); say('正在准备追问草稿…');
    try {
      const data = validate(await apiClient.json('POST', '/chat/life', { session_id: t.session, action: 'follow_up', ...(chosen.kind==='event'?{event_id:record.id}:{record_kind:chosen.kind,record_id:record.id}) }), t.session); if (!current(t)) return;
      if ((chosen.kind==='event'?data.event_id:data.record_id) !== record.id || chosen.kind!=='event'&&data.record_kind!==chosen.kind || typeof data.draft !== 'string' || !data.draft.trim()) throw Error('服务器未返回这条档案的追问草稿。');
      const input = document.getElementById('draft'), text = data.draft.trim(), value = input.value ? input.value + '\n\n' + text : text;
      if (input.disabled) throw Error('当前聊天输入框只读，请回到正在使用的对话再追问。');
      if (value.length > (input.maxLength > 0 ? input.maxLength : 16000)) throw Error('当前聊天草稿过长，请先整理输入框，再加入追问；原草稿未改动。');
      if(!data.reference||(chosen.kind==='event'?data.reference.event_id!==record.id||data.reference.event_revision!==data.event_revision:data.reference.record_kind!==chosen.kind||data.reference.record_id!==record.id||data.reference.record_revision!==data.record_revision))throw Error('服务器未提供这份资料的精确引用，请重新读取后再追问。');window.ChatComposer.addLifeReference(data.reference);
      input.value = value; saveDraft(); input.dispatchEvent(new Event('input', { bubbles: true })); closeActive(); input.focus(); showNotice('追问已加入输入框，可继续编辑，确认后再发送。');
    } catch (error) { if (current(t)) say(errorText(error)); }
    finally { if (current(t)) { busy = false; controls(); } }
  }
  function editEvent(preserved = null) {
    if (busy && !preserved || !detail?.event || detail.event.archived) return;
    const record = detail.event, f = fields(record), operation = pending.get(key(record.id));
    heading.textContent = '纠正这段经历'; body.replaceChildren();
    const currentVersion = make('details'); currentVersion.append(make('summary', '服务器当前内容 · 版本 ' + record.version), make('p', f.content || '', 'life-content')); body.append(currentVersion);
    const field = (name, control) => { const row = make('label'); row.append(make('span', name), control); body.append(row); return control; };
    const title = field('标题', make('input')); title.id = 'life-correct-title'; title.maxLength = 120; title.value = preserved?.title ?? operation?.changes.title ?? f.title ?? '';
    const content = field('修正后的内容', make('textarea')); content.id = 'life-correct-content'; content.maxLength = 2400; content.rows = 7; content.value = preserved?.content ?? operation?.changes.content ?? f.content ?? '';
    const status = field('当前状态', make('select')); status.id = 'life-correct-status'; for (const value of ['ongoing', 'completed', 'cancelled']) { const option = make('option', statuses[value]); option.value = value; status.append(option); } status.value = preserved?.status ?? operation?.changes.status ?? f.status;
    const consent = make('label', undefined, 'life-consent'), confirm = make('input'); confirm.id = 'life-correct-confirm'; confirm.type = 'checkbox'; consent.append(confirm, make('span', '将这次修正保存到虚构生活档案，保留修正历史。')); body.append(consent);
    const save = button('保存修正', saveCorrection, 'primary-button'); save.id = 'life-correct-save'; body.append(make('p', '关联资料由 TLS 按事件依赖更新；真实聊天记录不在这里修改。', 'appearance-help'), save, button('返回经历', () => renderDetail()));
    editor = { record, title, content, status, confirm, save, stale: false };
    if (operation?.phase === 'unknown' && operation.read) body.append(button('已核对当前版本，结束等待', () => { pending.delete(key(record.id)); confirm.checked = false; say('已结束上次操作的等待，请比较当前版本后重新确认编辑。'); controls(); }, 'life-link'));
    for (const control of [title, content, status]) for (const event of ['input', 'change']) control.addEventListener(event, () => { confirm.checked = false; controls(); }); confirm.addEventListener('change', controls);
    say(operation?.phase === 'unknown' ? '上次保存结果尚未确认，请先重新读取当前版本并核对。' : '尚未保存。关闭面板会放弃未提交的编辑。'); controls();
  }
  async function saveCorrection() {
    if (!editor || busy || !editor.confirm.checked || editor.stale || pending.has(key(editor.record.id))) return;
    const editing = editor, record = editing.record, original = fields(record), changes = { title: editing.title.value.trim(), content: editing.content.value.trim(), status: editing.status.value };
    if (!changes.title || changes.title.length > 120 || !changes.content || changes.content.length > 2400 || !['ongoing', 'completed', 'cancelled'].includes(changes.status)) { say('请填写标题（1–120字）、内容（1–2400字）并选择有效状态。'); return; }
    if (Object.keys(changes).every(name => changes[name] === original[name])) { say('内容未变化，无需保存。'); return; }
    const t = ticket(), operation = { request_id: 'life-' + (window.crypto?.randomUUID ? window.crypto.randomUUID() : Date.now().toString(36) + '-' + Math.random().toString(36).slice(2)), changes, phase: 'inflight', read: false };
    const pendingKey = key(record.id); pending.set(pendingKey, operation); busy = true; controls(); say('正在保存修正…');
    try {
      operation.promise = apiClient.json('POST', '/chat/life', { session_id: t.session, action: 'correct', event_id: record.id, expected_revision: record.revision, request_id: operation.request_id, changes });
      const result = validate(await operation.promise, t.session), updated = result.event;
      if (updated?.id !== record.id || !(updated.revision > record.revision) || !Object.keys(changes).every(name => fields(updated)[name] === changes[name])) throw Error('修正结果尚未确认，请重新读取核对。');
      pending.delete(pendingKey); if (!current(t)) return; overview = null; listStale = true; detail = result; editor = null; busy = false;
      const refreshed = await read(); if (sameOwner(t)) say(refreshed ? '已保存并重新读取生活档案。' : note.textContent + ' 修正保存已确认，关联资料请稍后重新读取。');
    } catch (error) {
      if ([400, 403, 404, 409].includes(error.status)) pending.delete(pendingKey); else operation.phase = 'unknown';
      if (current(t)) { editing.stale = true; editing.confirm.checked = false; say(errorText(error) + ' 编辑内容保留，请重新读取比较；应用不会自动重新提交。'); }
    } finally { operation.promise = null; if (current(t)) { busy = false; controls(); } }
  }
  function open(targetKind, targetId, message = null) {
    if(!parameter(targetKind)&&Object.hasOwn(worldKinds,targetKind)&&validId(targetId)){window.ChatPersonalSpace?.openRecord(targetKind,targetId);return;}
    const linked = !!parameter(targetKind) && validId(targetId);
    if (!state.authenticated || !state.activeId) { showNotice('请先打开自己的聊天会话。'); return; }
    setup(); if (dialog.open && owner === scope() && ownerAuth === auth() && !linked) return;
    catalogKind.value='all';catalogShared.value=catalogFrom.value=catalogTo.value='';
    closeActive(); owner = scope(); session = state.activeId; ownerAuth = auth(); epoch++; serial++; view = 'today'; overview = detail = editor = selection = searchData = restorePosition = null; searchInput.value = ''; listStale = false; positions.clear(); trail.length = 0; busy = false;
    window.ChatPersonalSpace?.closeActive(); window.ChatSettingsHub?.close(); window.ChatExperience?.close(); dialog.showModal(); if(message)linking={messageId:String(message.serverId),role:message.role,note:'',relation:'discussed'}; if(linked){selection={kind:targetKind,id:targetId};tabs.hidden=searchForm.hidden=true;back.hidden=false;body.replaceChildren(make('p','正在读取来源档案…'));}else renderOverview(); void read();
  }
  function init() {
    const entry = button('生活档案', () => { hideMoreMenu(); open(); }, 'menu-item'); entry.id = 'menu-life'; document.getElementById('more-menu')?.append(entry);
    const space = button('私人空间与兴趣', () => { hideMoreMenu(); window.ChatPersonalSpace?.open(); }, 'menu-item'); space.id='menu-personal-space'; document.getElementById('more-menu')?.append(space);
    const context = document.querySelector('[data-experience-pane="context"]'); if (context) { const n = button('查看生活档案', open, 'text-button'); n.id = 'experience-life-open'; context.append(n); }
    const body = document.getElementById('body-state-refresh'); if (body) { const n = button('生活档案与近期经历', () => { window.ChatNight?.requestClose?.(document.getElementById('body-state-dialog')); open(); }, 'text-button'); n.id = 'body-life-open'; body.after(n); }
    if (window.ChatExperience) window.ChatExperience.openLife = open;
  }
  document.addEventListener('DOMContentLoaded', init, { once: true });
  return { open, closeActive, scopeChanged, openRecord:(kind,id)=>open(kind,id), linkMessage:message=>{if(message?.delivery==='confirmed'&&/^\d+$/.test(String(message.serverId))) {open(null,null,message);view='recent';if(overview)renderOverview();}} };
})();
