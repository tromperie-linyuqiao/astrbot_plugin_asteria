'use strict';
/* Read-only TLS projection. This panel keeps no independent ledger, invokes no
   model or scheduler, and only appends a draft after an explicit user click. */
window.ChatPersonalSpace = (() => {
  const kinds = { all: '画卷', space: '私人空间', item: '物品', interest: '兴趣', exploration: '探索', collection: '收藏' };
  const states = { active: '进行中', paused: '已暂停', completed: '已完成', planned: '计划中', cancelled: '已取消' };
  const categories = { music: '音乐', book: '书籍', image: '图片', place: '地点', note: '笔记', event: '经历', topic: '话题' };
  const origins = { ordinary: '普通物品', selected: '自行挑选', user_gift: '用户赠予（管理端记录，未核验）', event: '经历获得' };
  const sourceKinds = { terra_canon: '泰拉资料（未核验）', public_reference: '公开资料（未核验）', original_fiction: '原创虚构', model_inference: '模型推断' };
  const resourceStates = { available: '原资源可用', changed: '原资源已更新 · 来源待复核', missing: '原资源已不存在', archived: '原资源已归档', denied: '原资源不可读取', unverified: '资源引用待核对' };
  const limit = 20;
  let dialog, body, note, back, title, tabs, searchForm, searchInput, searchGo, clearSearch, refresh;
  let owner = '', session = '', ownerAuth = null, epoch = 0, serial = 0, busy = false, serverScope = null;
  let kind = 'all', query = '', offset = 0, listing = null, selected = null, record = null, related = null, ready = false;
  let listPosition = 0, availability;
  const trail = [];
  const scope = () => JSON.stringify([state.server, state.username, state.activeId, state.sessionPersonaConfig?.configuredId || '']);
  const auth = () => typeof chatAuthEpoch === 'number' ? chatAuthEpoch : null;
  const active = () => dialog?.open && state.authenticated && owner === scope() && ownerAuth === auth();
  const ticket = () => ({ owner, session, epoch, auth: auth(), serial: ++serial });
  const current = t => active() && t.owner === owner && t.session === session && t.epoch === epoch && t.auth === auth() && t.serial === serial;
  const make = (tag, text, cls = '') => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; node.className = cls; return node; };
  const button = (label, fn, cls = 'text-button') => { const node = make('button', label, cls); node.type = 'button'; node.addEventListener('click', fn); return node; };
  const fields = value => value?.fields || {};
  const validId = value => typeof value === 'string' && value.length > 0 && value.length <= 160 && !/[\u0000-\u001f]/.test(value);
  const knownKind = value => value !== 'all' && Object.hasOwn(kinds, value);
  const validRecord = value => value && validId(value.id) && knownKind(value.kind) && value.fields && typeof value.fields === 'object' && !Array.isArray(value.fields);
  const name = value => typeof fields(value).name === 'string' && fields(value).name || '未命名资料';
  const textValue = value => typeof value === 'string' || typeof value === 'number' ? String(value) : '';
  const time = value => { if (value == null || value === '') return '未记录'; const date = new Date(typeof value === 'number' ? value * 1000 : value); return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { hour12: false }) : '未记录'; };
  const recordState = value => value.deleted || value.archived ? '已归档 · 仅供查阅' : value.valid === false ? '关联来源已变化 · 待复核' : '';
  function resourceInfo(value) {
    if (value?.kind !== 'collection') return null;
    const raw = value.resource, f = fields(value);
    if (raw == null && !f.resource_id && !f.resource_type) return null;
    const source = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
    let status = source.state || source.status || 'unverified';
    if (!Object.hasOwn(resourceStates, status) || !['music', 'image'].includes(source.type) || source.state && source.status && source.state !== source.status) status = 'unverified';
    if (['available', 'changed'].includes(status) && source.available === false) status = 'unverified';
    if (status === 'available' && Number.isInteger(source.revision) && Number.isInteger(source.expected_revision) && source.revision !== source.expected_revision) status = 'changed';
    return {source, state: status, readable: ['available', 'changed'].includes(status)};
  }
  const resourceBlocked = value => { const info = resourceInfo(value); return info && info.state !== 'available'; };
  const resourceChip = info => { const node = make('span', resourceStates[info.state], 'personal-resource-chip'); node.dataset.resourceState = info.state; return node; };
  // Resource metadata is deliberately a text-only allowlist. Never expose the
  // source scope, raw identifiers, URLs, filesystem paths or preview locations.
  function resourceText(value, max = 240) {
    if (typeof value !== 'string') return '';
    const text = value.trim();
    if (/(?:https?|file|content|data|javascript|blob):|[a-z]:[\\/]|\\\\|(?:^|\s)\/[a-z0-9_.-]+\//i.test(text)) return '';
    return text.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').slice(0, max);
  }
  function renderResource(destination, value) {
    const info = resourceInfo(value); if (!info) return;
    const panel = make('section', undefined, 'personal-resource'); panel.setAttribute('aria-label', '收藏的原资源资料'); panel.dataset.resourceState = info.state;
    panel.append(make('h4', info.source.type === 'music' ? '音乐资料' : info.source.type === 'image' ? '图片资料' : '资源引用'), resourceChip(info));
    if (info.readable) {
      if (info.state === 'changed') panel.append(make('p', '这里显示原资源当前资料；收藏引用的版本已变化。请前往 TLSWebUI 核对后再接着聊。', 'personal-resource-note'));
      const raw = info.source.metadata, metadata = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
      const title = resourceText(metadata.title) || resourceText(info.source.name);
      if (title) panel.append(make('p', title, 'personal-resource-title'));
      if (info.source.type === 'music') { fact(panel, '音乐人', resourceText(metadata.artist)); fact(panel, '专辑', resourceText(metadata.album)); }
      const caption = resourceText(metadata.caption, 600); if (caption) panel.append(make('p', caption, 'personal-content'));
      const tags = Array.isArray(metadata.tags) ? metadata.tags.map(value => resourceText(value, 60)).filter(Boolean).slice(0, 8) : []; if (tags.length) fact(panel, '标签', tags.join('、'));
      if (info.state === 'available') panel.append(make('p', '已读取原资源当前资料。', 'personal-resource-note'));
    } else {
      const reasons = { missing: '收藏条目仍保留，原资源已不存在，未显示旧资源资料。', archived: '收藏条目仍保留，原资源已归档，未显示旧资源资料。', denied: '当前会话无权读取原资源，未显示旧资源资料。', unverified: '此引用尚未核验，未作为真实资源展示。请前往 TLSWebUI 核对。' };
      panel.append(make('p', reasons[info.state], 'personal-resource-note'));
    }
    destination.append(panel);
  }
  const say = value => { note.textContent = value; };
  function controls() {
    back.hidden = !selected;
    back.disabled = refresh.disabled = searchInput.disabled = searchGo.disabled = clearSearch.disabled = busy;
    for (const node of tabs.querySelectorAll('button')) node.disabled = busy;
    for (const select of archiveFilters?.querySelectorAll('select') || []) select.disabled=busy;
    for (const node of body.querySelectorAll('button')) node.disabled = busy || node.dataset.unavailable === 'true' || !ready;
    body.setAttribute('aria-busy', String(busy));
  }
  function invalidate() {
    epoch++; serial++; owner = session = ''; ownerAuth = null; serverScope = null; busy = ready = false;
    listing = selected = record = related = null; trail.length = 0; listPosition = 0;
    body?.replaceChildren(); if (note) note.textContent = ''; if (searchInput) searchInput.value = '';
  }
  function closeActive() { if (!dialog?.open) return false; dialog.close(); invalidate(); return true; }
  function scopeChanged() { if (owner && !active()) closeActive(); }
  let archiveFilters;
  function setup() {
    if (dialog) return;
    dialog = make('dialog', undefined, 'settings-dialog personal-dialog'); dialog.id = 'personal-dialog'; dialog.setAttribute('aria-labelledby', 'personal-title');
    const form = make('div', undefined, 'settings-form'), heading = make('div', undefined, 'dialog-heading');
    availability=make('p','正在读取档案可用状态…','personal-availability');availability.setAttribute('role','status');
    back = button('‹', returnBack, 'icon-button'); back.id = 'personal-back'; back.setAttribute('aria-label', '返回私人空间列表');
    title = make('h2', '私人空间与兴趣'); title.id = 'personal-title';
    const close = button('×', closeActive, 'icon-button'); close.id = 'personal-close'; close.setAttribute('aria-label', '关闭私人空间与兴趣'); heading.append(back, title, close);
    const intro = make('p', '她的私人空间、收藏与还想继续的兴趣', 'personal-intro'); intro.append(make('small', '角色虚构生活资料 · 完整编辑请前往 TLSWebUI', 'personal-origin'));
    searchForm = make('form', undefined, 'personal-search'); searchForm.setAttribute('role', 'search');
    searchInput = make('input'); searchInput.id = 'personal-search'; searchInput.type = 'search'; searchInput.maxLength = 120; searchInput.placeholder = '搜索空间、物品、兴趣与收藏'; searchInput.setAttribute('aria-label', '搜索私人空间与兴趣');
    searchGo = make('button', '搜索', 'text-button'); searchGo.type = 'submit'; clearSearch = button('清除', () => { searchInput.value = ''; changeList(kind, ''); }); clearSearch.id = 'personal-search-clear';
    searchForm.append(searchInput, searchGo, clearSearch); searchForm.addEventListener('submit', event => { event.preventDefault(); changeList(kind, searchInput.value.trim()); });
    tabs = make('nav', undefined, 'personal-tabs'); tabs.setAttribute('aria-label', '私人空间资料分类');
    for (const [value, label] of Object.entries(kinds)) { const node = button(label, () => changeList(value, query), 'personal-tab'); node.dataset.personalKind = value; tabs.append(node); }
    archiveFilters = make('div', undefined, 'personal-archive-filters');
    for(const [id,label,values] of [['status','探索状态',[['','全部状态'],['planned','待探索'],['active','正在关注'],['completed','已完成'],['paused','暂时搁置'],['cancelled','已取消']]],['category','收藏类别',[['','全部类别'],...Object.entries(categories)]],['sort','排序',[['updated','最近更新'],['created','首次记录'],['name','名称']]]]) {
      const wrap=make('label',label), select=make('select');select.dataset.archiveFilter=id;
      for(const [value,text] of values){const option=make('option',text);option.value=value;select.append(option);}
      select.addEventListener('change',()=>changeList(kind,query));wrap.append(select);archiveFilters.append(wrap);
    }
    body = make('section', undefined, 'personal-body'); body.id = 'personal-body';
    const toolbar = make('div', undefined, 'personal-toolbar'); refresh = button('重新读取', () => read()); refresh.id = 'personal-refresh'; toolbar.append(refresh);
    note = make('p', '', 'personal-note'); note.id = 'personal-note'; note.setAttribute('role', 'status'); note.setAttribute('aria-live', 'polite');
    form.append(heading, intro, searchForm, tabs, archiveFilters, body, toolbar, note); dialog.append(form); document.body.append(dialog);
    dialog.addEventListener('cancel', event => { event.preventDefault(); closeActive(); }); dialog.addEventListener('close', () => { if (!dialog.open) invalidate(); });
  }
  const card = heading => { const node = make('article', undefined, 'personal-card'); if (heading) node.append(make('h3', heading)); return node; };
  function recordCard(value) {
    const f = fields(value), node = card(); node.dataset.personalRecord = value.kind + ':' + value.id;
    node.append(make('small', [kinds[value.kind], states[f.status], categories[f.category], recordState(value)].filter(Boolean).join(' · ')), button(name(value), () => openRecord(value.kind, value.id), 'personal-record-title'));
    const resource = resourceInfo(value); if (resource) node.append(resourceChip(resource));
    if (typeof f.description === 'string' && f.description) node.append(make('p', f.description.slice(0, 220), 'personal-preview'));
    return node;
  }
  function renderOverview(overview) {
    if (!overview || typeof overview !== 'object') return;
    const grid = make('section', undefined, 'personal-overview'); grid.setAttribute('aria-label', '生活资料概览');
    for (const [key, label, value, empty] of [['spaces', '私人空间', 'space', '还没有私人空间记录。'], ['recent_collections', '最近收藏', 'collection', '还没有收藏记录。'], ['active_interests', '正在关注的兴趣', 'interest', '目前没有进行中的兴趣。'], ['planned_explorations', '计划中的探索', 'exploration', '暂时没有计划中的探索。']]) {
      const node = card(label), rows = Array.isArray(overview[key]) ? overview[key].filter(validRecord).slice(0, 3) : [];
      for (const row of rows) { node.append(button(name(row), () => openRecord(row.kind, row.id), 'personal-link')); const resource = resourceInfo(row); if (resource && resource.state !== 'available') node.append(resourceChip(resource)); }
      if (!rows.length) node.append(make('p', empty, 'personal-muted'));
      node.append(button('查看' + kinds[value], () => changeList(value, ''), 'personal-link personal-see-all')); grid.append(node);
    }
    body.append(grid);
  }

  let visualSection='spaces', browsingAll=false;
  function renderVisual(data) {
    const top=card('私人数字档案');top.classList.add('personal-visual-hero');
    top.append(make('p',data.last_updated_at?'最近整理 · '+time(data.last_updated_at):'从一个空间、一件物品，慢慢留下生活的轮廓。','personal-muted'));
    const counts=listing.overview.display_counts||listing.overview.counts||{},stats=make('div',undefined,'personal-visual-stats');
    for(const [id,label]of [['space','空间'],['item','物品'],['interest','兴趣'],['collection','收藏']]){
      const b=button('',()=>changeList(id,''),'personal-visual-stat');b.append(make('strong',String(counts[id]??'—')),make('span',label));stats.append(b);
    }top.append(stats);body.append(top);
    const nav=make('nav',undefined,'personal-visual-tabs');nav.setAttribute('aria-label','生活画卷分区');
    for(const [id,label]of [['spaces','空间'],['interests','兴趣'],['explorations','探索'],['collections','收藏'],['recent','更新']]){const b=button(label,()=>{visualSection=id;listPosition=0;renderList();},'personal-tab');b.dataset.personalScene=id;b.setAttribute('aria-pressed',String(id===visualSection));nav.append(b);}body.append(nav);
    const grid=make('section',undefined,'personal-visual-grid');grid.dataset.personalSceneBody=visualSection;body.append(grid);
    const entry=(parent,row)=>{if(!validRecord(row))return;const b=button('',()=>openRecord(row.kind,row.id),'personal-visual-entry');b.append(make('strong',name(row)),make('small',[kinds[row.kind],recordState(row)].filter(Boolean).join(' · ')));parent.append(b);};
    const section=(label,copy)=>{const box=card(label);if(copy)box.append(make('p',copy,'personal-muted'));grid.append(box);return box;};
    if(visualSection==='spaces'){
      for(const group of data.spaces||[]){const box=section(group.record.fields?.area||'私人空间',group.item_count+' 件物品');entry(box,group.record);const branch=make('div',undefined,'personal-visual-branch');for(const row of group.items||[])entry(branch,row);if(!branch.children.length)branch.append(make('p','尚未放置物品','personal-muted'));box.append(branch);}
      if(data.unplaced_items?.count){const box=section('尚未归入空间',data.unplaced_items.count+' 件物品');for(const row of data.unplaced_items.records)entry(box,row);}
    }else if(visualSection==='interests'){
      for(const group of data.interests||[]){const box=section(states[group.record.fields?.status]||'兴趣',group.collection_count+' 项收藏 · '+group.exploration_count+' 段探索');entry(box,group.record);if(group.record.fields?.next_direction)box.append(make('p',group.record.fields.next_direction,'personal-preview'));const branch=make('div',undefined,'personal-visual-branch');for(const row of [...group.explorations||[],...group.collections||[]])entry(branch,row);if(branch.children.length)box.append(branch);}
    }else if(visualSection==='explorations'){
      for(const id of ['planned','active','paused','completed','cancelled']){const group=(data.exploration_states||[]).find(x=>x.value===id);if(id==='cancelled'&&!group)continue;const box=section((states[id]||id)+' · '+(group?.count||0));box.dataset.personalLane=id;for(const row of group?.records||[])entry(box,row);if(!group?.count)box.append(make('p','暂无记录','personal-muted'));const b=button('查看这个状态',()=>{archiveFilters.querySelector('[data-archive-filter="status"]').value=id;changeList('exploration','');},'personal-link');box.append(b);}
    }else if(visualSection==='collections'){
      for(const group of data.collection_categories||[]){const box=section(categories[group.value]||group.value,group.count+' 项收藏');for(const row of group.records||[])entry(box,row);box.append(button('查看这一类',()=>{archiveFilters.querySelector('[data-archive-filter="category"]').value=group.value;changeList('collection','');},'personal-link'));}
    }else{
      grid.classList.add('personal-visual-timeline');for(const row of data.recent_updates||[]){const box=section(time(row.updated_at));entry(box,row);}body.append(make('p','按档案更新时间排列，不代表生活事件发生时间。','personal-muted'));
    }
    if(!grid.children.length)grid.append(make('p',({spaces:'尚未记录私人空间。',interests:'目前没有持续兴趣，一次收藏不会自动形成兴趣。',collections:'个人收藏仍为空；服务器资料库不会自动成为个人收藏。',recent:'还没有档案更新。'})[visualSection]||'这里还没有记录。','personal-empty'));
    if(data.review_count)body.append(make('p',data.review_count+' 条资料来源待复核，可查看详情；完整修正请在 TLS 后台进行。','personal-resource-note'));
    body.append(button('浏览全部资料 · '+listing.total,()=>{browsingAll=true;listPosition=0;renderList();},'personal-browse-all'));
  }

  function renderList() {
    title.textContent = '私人空间与兴趣'; tabs.hidden = searchForm.hidden = archiveFilters.hidden = false;
    for(const element of archiveFilters.querySelectorAll('select')){element.closest('label').hidden=element.dataset.archiveFilter==='status'&&!['interest','exploration'].includes(kind)||element.dataset.archiveFilter==='category'&&kind!=='collection';} body.replaceChildren();
    for (const node of tabs.querySelectorAll('button')) node.setAttribute('aria-pressed', String(node.dataset.personalKind === kind));
    if (!listing) { body.append(make('p', '正在读取当前角色的私人空间资料…', 'personal-empty')); controls(); return; }
    if(kind==='all'&&!query&&listing.overview?.visual&&!browsingAll){tabs.hidden=archiveFilters.hidden=true;renderVisual(listing.overview.visual);say('同一份 TLS 档案 · 查看不会推进生活或调用模型。');controls();body.scrollTop=listPosition;return;}
    if (kind === 'all' && !query && !listing.overview?.visual) renderOverview(listing.overview);
    if(kind==='all'&&browsingAll)body.append(button('返回生活画卷',()=>{browsingAll=false;listPosition=0;renderList();},'personal-link'));
    body.append(make('p', (query ? '“' + query + '” · ' : kind === 'all' ? '全部资料 · ' : kinds[kind] + ' · ') + listing.total + ' 条记录', 'personal-count'));
    for (const value of listing.records) body.append(recordCard(value));
    if (!listing.records.length) body.append(make('p', offset ? '当前页已无资料，请返回上一页或重新读取。' : query ? '没有找到匹配资料，可以换个词再找找。' : '这里还没有资料；生活可以保留空白，不必补出故事。', 'personal-empty'));
    const pager = make('nav', undefined, 'personal-pager'); pager.setAttribute('aria-label', '资料分页');
    const previous = button('上一页', () => changePage(Math.max(0, offset - limit))), next = button('下一页', () => changePage(offset + limit));
    previous.dataset.unavailable = String(offset === 0); next.dataset.unavailable = String(offset + listing.records.length >= listing.total);
    pager.append(previous, make('span', listing.records.length ? (offset + 1) + '–' + (offset + listing.records.length) + ' / ' + listing.total : '0 / ' + listing.total), next); body.append(pager);
    say('已从 TLS 读取。查看资料不会推进生活；完整编辑请前往 TLSWebUI。'); controls(); body.scrollTop = listPosition;
  }
  function fact(destination, label, value) { const text = textValue(value); if (text) { const row = make('p', undefined, 'personal-fact'); row.append(make('strong', label + '：'), make('span', text)); destination.append(row); } }
  function lines(destination, label, values) { if (!Array.isArray(values) || !values.some(value => typeof value === 'string' && value)) return; destination.append(make('h4', label)); const list = make('ul'); for (const value of values) if (typeof value === 'string' && value) list.append(make('li', value)); destination.append(list); }
  function personalLink(destination, label, value, targetKind) { if (validId(value)) { const node = button(label + '：' + value, () => openRecord(targetKind, value), 'personal-link'); destination.append(node); } }
  function sourceLink(destination, targetKind, id) {
    if (!validId(id)) return;
    const values = related?.[targetKind === 'event' ? 'events' : 'people'], found = Array.isArray(values) ? values.find(value => value?.id === id) : null;
    const label = (targetKind === 'event' ? '来源经历：' : '关联人物：') + (fields(found)[targetKind === 'event' ? 'title' : 'name'] || id);
    destination.append(button(label, () => { if (!active() || busy || !ready) return; if (typeof window.ChatLife?.openRecord !== 'function') { say('当前版本暂不能跳转，请在生活档案中按来源编号查阅：' + id); return; } closeActive(); window.ChatLife.openRecord(targetKind, id); }, 'personal-link'));
  }
  function renderDetail() {
    title.textContent = kinds[selected.kind] + '详情'; tabs.hidden = searchForm.hidden = archiveFilters.hidden = true; body.replaceChildren(); body.scrollTop = 0;
    back.setAttribute('aria-label', trail.length ? '返回上一条私人资料' : '返回私人空间列表');
    if (!record) { body.append(make('p', '正在读取这条资料…', 'personal-empty')); controls(); return; }
    const f = fields(record), main = card(name(record)); main.append(make('small', [kinds[record.kind], states[f.status], recordState(record)].filter(Boolean).join(' · ')), make('p', textValue(f.description) || '暂无补充说明。', 'personal-content'));
    for (const [key, label] of [['environment', '环境'], ['area', '区域'], ['giver', '赠予者'], ['message_ref', '消息依据'], ['goal', '目标']]) fact(main, label, f[key]);
    if (f.origin) fact(main, '物品来源', origins[f.origin] || f.origin);
    if (f.gifted_at != null) fact(main, '赠予时间（未核验）', time(f.gifted_at));
    if (f.origin === 'user_gift' || record.attribution) main.append(make('p', '赠予信息来自管理端记录，尚未核验真实聊天依据。', 'personal-muted'));
    if (f.category) fact(main, '收藏类别', categories[f.category] || f.category);
    renderResource(main, record);
    if (f.source_kind) fact(main, '依据类型', sourceKinds[f.source_kind] || f.source_kind);
    fact(main,'兴趣缘由',f.origin_note);fact(main,'下一步方向',f.next_direction);if(f.attention) fact(main,'关注变化',({growing:'逐渐加深',steady:'持续关注',fading:'渐渐淡去'})[f.attention]);
    if (f.last_attended_at != null) fact(main, '上次关注', time(f.last_attended_at));
    if (typeof f.worth_continuing === 'boolean') fact(main, '是否值得继续', f.worth_continuing ? '是' : '暂时放下');
    lines(main, '待探索的问题', f.questions); lines(main, '已经探索的内容', f.explored); lines(main, '发现', f.findings);
    personalLink(main, '所在空间', f.space_id, 'space'); personalLink(main, '对应兴趣', f.interest_id, 'interest');
    const ask = button('接着聊', appendDraft, 'primary-button'); ask.id = 'personal-follow-up'; ask.dataset.unavailable = String(record.valid === false || record.archived === true || record.deleted === true || resourceBlocked(record)); main.append(ask); body.append(main);
    if(related?.links?.length) {const links=card('关联档案');for(const row of related.links.filter(validRecord)) links.append(button(kinds[row.kind]+' · '+name(row)+(row.valid===false?'（待复核）':''),()=>openRecord(row.kind,row.id),'personal-link'));body.append(links);}
    const sources = card('来源与关联');
    const eventIds = Array.isArray(f.event_ids) ? f.event_ids : [];
    for (const id of eventIds) sourceLink(sources, 'event', id);
    if (validId(f.shared_event_id) && !eventIds.includes(f.shared_event_id)) sourceLink(sources, 'event', f.shared_event_id);
    for (const id of Array.isArray(f.character_ids) ? f.character_ids : []) sourceLink(sources, 'character', id);
    if (Array.isArray(f.sources)) for (const source of f.sources) {
      if (!source || typeof source !== 'object') continue;
      const label = textValue(source.title) || '外部参考'; let url;
      try { url = new URL(source.url); } catch (_) { /* Keep invalid URLs as plain reference labels. */ }
      if (url && ['https:', 'http:'].includes(url.protocol)) { const link = make('a', label + '（外部参考，未核验）', 'personal-link'); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; sources.append(link); }
      else sources.append(make('p', label + '（参考信息未核验）', 'personal-muted'));
    }
    if (!sources.querySelector('button,a,p')) sources.append(make('p', '尚无关联经历、人物或参考资料。', 'personal-muted'));
    fact(sources, '资料来源', textValue(record.source)); fact(sources, '资料编号', record.id); if (Number.isInteger(record.revision)) fact(sources, '修订', record.revision);
    fact(sources, '建立时间', time(record.created_at)); fact(sources, '更新时间', time(record.updated_at)); body.append(sources);
    say(recordState(record) || (resourceBlocked(record) ? '资源来源待复核。完整收藏与核对请前往 TLSWebUI。' : '虚构生活资料。接着聊会加入可编辑草稿，确认后再发送。')); controls();
  }
  function validate(data, t) {
    if (!data || data.session_id !== t.session) throw Error('私人空间会话不匹配，请重新读取。');
    if (!data.personal || data.status === 'unsupported' || data.status?.state === 'unsupported') throw Object.assign(Error('unsupported'), { unsupported: true });
    if (data.evidence_kind !== 'roleplay_event') throw Error('服务器未标明虚构生活资料来源，请更新服务端后再读取。');
    const responseScope = data.scope == null ? null : JSON.stringify(data.scope);
    if (serverScope !== null && responseScope !== serverScope) { closeActive(); showNotice('当前角色资料范围已变化，请重新打开私人空间。'); return null; }
    serverScope = responseScope;
    if(availability){const status=data.status||{};availability.textContent=status.state==='paused_budget'
      ? '私人空间已接通，可浏览已有资料。自动生活推进暂停：当前模型预算为 0；浏览不调用模型。'
      : status.can_advance===false?'私人空间已接通，可浏览已有资料。自动生活推进当前未运行。'
      :'私人空间已接通，显示当前服务器保存的生活资料。';}
    return data.personal;
  }
  async function read(preservePosition = true) {
    if (!active() || busy) return false;
    if (!selected && listing && preservePosition) listPosition = body.scrollTop;
    if(availability){availability.textContent='正在读取档案状态…';if(!availability.isConnected)dialog.querySelector('.dialog-heading').after(availability);}
    const t = ticket(), chosen = selected && { ...selected }; busy = true; ready = false; controls(); say('正在读取私人空间资料…');
    const params = new URLSearchParams({ view: 'personal', session_id: t.session, kind: chosen?.kind || kind, query: chosen ? '' : query, limit: String(limit), offset: String(chosen ? 0 : offset) }); if (chosen) params.set('id', chosen.id);
    else for(const select of archiveFilters.querySelectorAll('select')) if(!select.closest('label').hidden && select.value && !(select.dataset.archiveFilter==='sort' && select.value==='updated')) params.set(select.dataset.archiveFilter,select.value);
    try {
      const response = await apiClient.json('GET', '/chat/life?' + params); if (!current(t)) return false;
      const data = validate(response, t); if (!data || !current(t)) return false;
      if (chosen) { if (!validRecord(data.record) || data.record.id !== chosen.id || data.record.kind !== chosen.kind) throw Error('服务器未返回这条私人资料。'); record = data.record; related = data; }
      else { if (!Array.isArray(data.records) || data.records.some(value => !validRecord(value)) || !Number.isInteger(data.total) || data.total < 0) throw Error('服务器未返回可读取的私人资料列表。'); listing = data; }
      ready = true; if (chosen) renderDetail(); else renderList(); return true;
    } catch (error) {
      if (current(t)) {
        const unsupported = error.unsupported || [404, 405, 501].includes(error.status) && !chosen;
        const message = unsupported ? '当前服务器尚未提供私人空间与兴趣。独立服务端需更新并连接支持此功能的 TLS 后再读取。' : chosen && error.status === 404 ? '这条资料已不可用，请返回列表重新读取。' : errorText(error);
        if (!listing && !record || unsupported) body.replaceChildren(make('p', message, 'personal-empty'));
        if(availability)availability.textContent='档案当前未能更新；不能据此判断自动推进状态。';
        say(message + (listing || record ? ' 当前保留的是上次读取的资料，请重新读取后再操作。' : ''));
      } return false;
    } finally { if (current(t)) { busy = false; controls(); } }
  }
  function changeList(nextKind, nextQuery) {
    if (!active() || busy || !Object.hasOwn(kinds, nextKind)) return;
    browsingAll=false;kind = nextKind; query = nextQuery.slice(0, 120); offset = 0; selected = record = related = listing = null; trail.length = 0; listPosition = 0; searchInput.value = query; ready = false; renderList(); void read();
  }
  function changePage(nextOffset) { if (!active() || busy) return; offset = nextOffset; listPosition = 0; void read(false); }
  function openRecord(nextKind, id) {
    if (!active() || busy || !knownKind(nextKind) || !validId(id)) return;
    if (selected) trail.push({ selected, record, related, position: body.scrollTop }); else listPosition = body.scrollTop;
    selected = { kind: nextKind, id }; record = related = null; ready = false; renderDetail(); void read();
  }
  function returnBack() {
    if (!active() || busy || !selected) return;
    const previous = trail.pop(); ready = true;
    if (previous) { ({ selected, record, related } = previous); renderDetail(); body.scrollTop = previous.position; }
    else { selected = record = related = null; renderList(); if (!listing) void read(); }
  }
  async function appendDraft() {
    if (!active() || busy || !ready || !record || record.valid === false || record.archived || record.deleted || resourceBlocked(record)) return;
    const input = document.getElementById('draft');
    if (!input || input.disabled || input.readOnly) { say('当前聊天输入框只读，请回到正在使用的对话再接着聊。'); return; }
    const t=ticket(),chosen={kind:record.kind,id:record.id};busy=true;controls();say('正在准备资料追问…');
    try{
      const data=await apiClient.json('POST','/chat/life',{session_id:t.session,action:'follow_up',record_kind:chosen.kind,record_id:chosen.id});if(!current(t))return;
      if(data?.session_id!==t.session||data.record_kind!==chosen.kind||data.record_id!==chosen.id||typeof data.draft!=='string'||!data.draft.trim()||!data.reference||data.reference.record_kind!==chosen.kind||data.reference.record_id!==chosen.id||data.reference.record_revision!==data.record_revision)throw Error('服务器未返回这份资料的精确追问，请更新服务端或重新读取。');
      const value=input.value?input.value+'\n\n'+data.draft.trim():data.draft.trim();
      if(input.disabled||input.readOnly||value.length>(input.maxLength>0?input.maxLength:16000))throw Error('当前草稿不可追加或已经过长；原草稿保留。');
      window.ChatComposer.addLifeReference(data.reference);input.value=value;saveDraft();input.dispatchEvent(new Event('input',{bubbles:true}));closeActive();input.focus();showNotice('资料追问已加入草稿，确认后再发送。');
    }catch(error){if(current(t))say(errorText(error));}finally{if(current(t)){busy=false;controls();}}
  }
  function open(targetKind,targetId) {
    if (!state.authenticated || !state.activeId) { showNotice('请先打开自己的聊天会话。'); return; }
    setup(); if (active()&&!targetId) return;visualSection='spaces';browsingAll=false;
    closeActive(); owner = scope(); session = state.activeId; ownerAuth = auth(); epoch++; serial++; serverScope = null; kind = 'all'; query = ''; offset = 0; listing = selected = record = related = null; trail.length = 0; busy = ready = false; listPosition = 0; searchInput.value = '';for(const select of archiveFilters.querySelectorAll('select'))select.selectedIndex=0;
    window.ChatSettingsHub?.close(); window.ChatExperience?.close(); window.ChatLife?.closeActive(); dialog.showModal(); if(targetKind&&validId(targetId)){kind=targetKind;selected={kind:targetKind,id:targetId};} renderList(); void read();
  }
  return { open, closeActive, scopeChanged, openRecord:(kind,id)=>open(kind,id) };
})();
