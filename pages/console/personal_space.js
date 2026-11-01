/* Scoped fictional possessions and interests. Reads and previews never advance life. */
(function (global) {
  'use strict';
  const root = document.getElementById('personal-space-mount');
  if (!root) return;
  const FIELDS = ['platform', 'bot_id', 'user_id', 'character_id', 'session_id'];
  const key = value => JSON.stringify(FIELDS.map(name => value?.[name]));
  const currentScope = () => typeof state === 'object' && state.scope && FIELDS.every(name => typeof state.scope[name] === 'string' && state.scope[name].trim()) ? {...state.scope} : null;
  const labels = {space:'私人空间', item:'私人物品', interest:'兴趣', exploration:'探索记录', collection:'个人收藏'};
  const countKeys = {space:'spaces', item:'items', interest:'interests', exploration:'explorations', collection:'collections'};
  const statusLabels = {active:'进行中', paused:'暂停', completed:'已完成', planned:'计划中', cancelled:'已取消'};
  const originLabels = {ordinary:'日常物品',selected:'主动挑选',user_gift:'用户赠礼',event:'源于生活经历'};
  const decisionLabels = {idle:'留出一段平静的时间',continue_thread:'接续未完的事情',continue_exploration:'继续一段探索',attend_interest:'照顾已有的兴趣',organize_collection:'整理个人收藏',revisit_person:'想起一位熟人',ordinary_life:'继续平常的生活'};
  const sourceLabels = {model_generated:'模型生成的虚构资料',scoped_plan:'范围日计划',pc_artifact:'角色日常资料',user_correction:'用户修正',operator:'管理员录入', life_event:'虚构生活经历', original_fiction:'原创虚构', terra_canon:'泰拉正典资料', public_reference:'现实公开资料', model_inference:'模型推测', model:'模型生成'};
  const categoryLabels = {music:'音乐', book:'书籍', image:'图片', place:'地点', note:'笔记', event:'经历', topic:'话题'};
  const fieldLabels = {origin_note:'兴趣缘由', attention:'关注变化', next_direction:'下一步方向', name:'名称', description:'说明', environment:'环境', area:'区域', origin:'来历', giver:'赠送者', gifted_at:'赠送时间', message_ref:'原消息引用', status:'状态', questions:'想弄清的问题', explored:'已经了解的内容', last_attended_at:'最近关注时间', worth_continuing:'仍值得继续', goal:'这次想了解什么', findings:'目前的发现', source_kind:'发现的依据', category:'收藏类型', resource_id:'资料编号', resource_type:'资料类型'};
  const node = (tag, text, className) => {const value = document.createElement(tag); if (text !== undefined) value.textContent = String(text); if (className) value.className = className; return value;};
  const stamp = value => typeof value === 'number' && Number.isFinite(value) ? new Date(value * 1000).toLocaleString() : '尚未记录';
  const title = record => record?.fields?.name || record?.fields?.title || record?.id || '未命名记录';
  const pending = new Map();
  let scope = null, kind = 'space', selected = null, records = [], total = 0, offset = 0, serial = 0, busy = false;
  let overview = null, draft = null, lifeReference = null, refs = {space:[], interest:[], event:[], character:[]};
  let review = null, reviewTotal = null, picker = {type:'music',sources:[],source:null,records:[],total:0,offset:0,selected:null};
  root.innerHTML = `<section class="panel personal-space"><div class="panel-head"><div><p class="ps-eyebrow">角色的生活一隅</p><h2>个人空间与兴趣</h2><p class="hint">整理她居住的地方、留下的物件，以及愿意继续了解的事。</p></div><button type="button" data-ps-refresh>刷新与核对</button></div><p class="ps-boundary">这里保存角色的虚构生活。泰拉正典、现实公开资料、原创虚构与模型推测分别标明来源；收藏不会证明真实听过、读过或到访。</p><p data-ps-status class="ps-status" role="status" aria-live="polite"></p><div data-ps-counts class="ps-counts"></div><section data-ps-decision class="ps-decision" aria-label="生活选择预览"></section><div class="ps-tabs" role="tablist" aria-label="个人生活资料">${Object.entries(labels).map(([id,label]) => `<button type="button" role="tab" id="ps-tab-${id}" aria-controls="ps-records" data-ps-tab="${id}" aria-selected="false">${label}</button>`).join('')}</div><section id="ps-records" role="tabpanel"><form data-ps-search class="ps-toolbar"><label>查找<input data-ps-query type="search" maxlength="200" placeholder="名称、说明或兴趣关键词"></label><button type="submit">搜索</button><button type="button" data-ps-new class="primary">新增私人空间</button><div class="ps-filters"><label><input type="checkbox" data-ps-archived>含归档与已删除</label><label><input type="checkbox" data-ps-invalid>含待复核</label></div></form><div class="ps-columns"><section class="ps-catalog" aria-label="资料列表"><div data-ps-list></div><div class="actions ps-pager"><button type="button" data-ps-prev>上一页</button><span data-ps-range></span><button type="button" data-ps-next>下一页</button></div></section><aside class="ps-side"><section data-ps-detail class="ps-detail" aria-label="资料详情"></section><section data-ps-reference class="ps-reference" hidden aria-label="关联生活资料"></section><section data-ps-editor class="ps-editor" hidden aria-label="独立资料编辑器"><div class="panel-head"><h3 data-ps-editor-title></h3><button data-ps-cancel type="button">取消编辑</button></div><p data-ps-editor-identity class="hint"></p><form data-ps-form><div data-ps-fields class="ps-edit-grid"></div><label data-ps-reason-wrap>维护原因<input data-ps-reason maxlength="400"></label><div class="actions"><button class="primary" type="submit">保存并回读</button></div></form><p class="hint ps-edit-note">保存会保留历史版本与来源。切换右侧详情不会改变当前编辑对象。</p></section></aside></div></section><div class="actions"><button data-ps-release type="button" hidden>已核对，结束本次等待</button></div></section>`;
  const $ = name => root.querySelector('[data-ps-' + name + ']');
  $('search').insertAdjacentHTML('beforeend','<label>状态<select data-ps-state><option value="">全部状态</option><option value="active">进行中</option><option value="planned">待探索</option><option value="completed">已完成</option><option value="paused">暂时搁置</option><option value="cancelled">已取消</option></select></label><label>收藏分类<select data-ps-category><option value="">全部分类</option>'+Object.entries(categoryLabels).map(([id,label])=>'<option value="'+id+'">'+label+'</option>').join('')+'</select></label><label>排序<select data-ps-sort><option value="updated">最近更新</option><option value="created">首次记录</option><option value="name">名称</option></select></label>');
  for (const name of ['state','category','sort']) $(name).addEventListener('change',()=>{offset=0;load();});
  root.querySelector('.ps-tabs').insertAdjacentHTML('beforeend','<button type="button" role="tab" id="ps-tab-review" aria-controls="ps-records" data-ps-tab="review" aria-selected="false">关联待复核 · —</button>');
  $('search').insertAdjacentHTML('beforeend','<button type="button" data-ps-pick hidden>从音乐／图片资料库收藏</button>');
  $('search').insertAdjacentHTML('afterend',`<section data-ps-picker class="ps-picker" hidden aria-label="选择已有资料收藏"><div class="panel-head"><div><h3>从已有资料中收藏</h3><p class="hint">先明确选择已授权的资料来源，再核对条目。收藏只保留引用，不代表听过、读过或发送过。</p></div><button type="button" data-ps-picker-close>收起</button></div><form data-ps-resource-search class="ps-resource-search"><label>资料类型<select data-ps-resource-type data-ps-resource-read><option value="music">音乐</option><option value="image">图片</option></select></label><label>资料来源<select data-ps-resource-source data-ps-resource-read><option value="">先读取资料来源</option></select></label><label>查找条目<input type="search" data-ps-resource-query data-ps-resource-read maxlength="200" placeholder="标题、作者或标签"></label><button type="submit" data-ps-resource-read>搜索资料</button></form><div class="ps-resource-columns"><div><div data-ps-resource-list></div><div class="actions ps-pager"><button type="button" data-ps-resource-prev data-ps-resource-read>上一页</button><span data-ps-resource-range></span><button type="button" data-ps-resource-next data-ps-resource-read>下一页</button></div></div><section data-ps-resource-preview class="ps-resource-preview" aria-label="收藏前预览"></section></div><form data-ps-collect-form hidden><div class="ps-edit-grid"><label>收藏名称（可选）<input data-ps-collect-name maxlength="120"></label><label>关联兴趣<select data-ps-collect-interest></select></label><label>收藏缘由（可选）<textarea data-ps-collect-description maxlength="1200"></textarea></label></div><div class="actions"><button type="submit" class="primary" data-ps-collect>收藏这项资料并回读</button></div></form></section>`);
  $('reference').insertAdjacentHTML('afterend',`<section data-ps-review class="ps-review" hidden aria-label="关联变化与人工复核"><div class="panel-head"><h3>关联来源发生了什么变化</h3><button type="button" data-ps-review-refresh data-ps-read>重新读取变化</button></div><p class="hint">对照记录当时使用的来源与当前来源。确认只表示你已人工核对，不表示模型已重写或证明内容属实。</p><div data-ps-review-changes></div><p data-ps-review-blocked class="ps-warning"></p><form data-ps-review-form><label class="ps-check"><input type="checkbox" data-ps-review-edit>同时保存下方编辑器中的修正（可选）</label><label class="ps-check"><input type="checkbox" data-ps-review-confirmed required>我已核对来源变化，并确认这条记录可继续使用</label><label>复核原因<input data-ps-review-reason maxlength="400" required></label><div class="actions"><button type="submit" class="primary" data-ps-review-submit>确认复核并回读</button></div></form></section>`);
  const message = (text, error = false) => {$('status').textContent = text; $('status').dataset.error = String(error);};
  const same = target => key(target) === key(scope) && key(target) === key(currentScope());
  const action = (parent, label, callback, className = '') => {const button = node('button', label, className); button.type = 'button'; button.addEventListener('click', callback); parent.append(button); return button;};
  function controls() {
    const uncertain = pending.has(key(scope)), blocked = busy || !scope || uncertain;
    for (const element of root.querySelectorAll('input,select,textarea,button')) element.disabled = blocked;
    $('refresh').disabled = busy || !scope;
    for (const element of root.querySelectorAll('[data-ps-tab],[data-ps-read],[data-ps-preview]')) element.disabled = busy || !scope;
    for (const element of [$('query'), $('archived'), $('invalid'), ...$('search').querySelectorAll('[type=submit]')]) element.disabled = busy || !scope;
    $('prev').disabled = busy || !scope || offset === 0;
    $('next').disabled = busy || !scope || offset + records.length >= total;
    $('release').hidden = !uncertain;
    $('release').disabled = busy || !pending.get(key(scope))?.checked;
    for (const element of root.querySelectorAll('[data-ps-immutable]')) element.disabled = true;
    for (const element of root.querySelectorAll('[data-ps-resource-read]')) element.disabled = busy || !scope;
    $('resource-prev').disabled = busy || !scope || !picker.source || picker.offset === 0;
    $('resource-next').disabled = busy || !scope || !picker.source || picker.offset + picker.records.length >= picker.total;
    $('collect').disabled = blocked || !picker.selected?.available;
    $('review-submit').disabled = blocked || review?.can_confirm !== true || !$('review-confirmed').checked;
    $('review-edit').disabled = blocked || review?.can_confirm !== true;
    $('review-confirmed').disabled = blocked || review?.can_confirm !== true;
    root.setAttribute('aria-busy', String(busy));
  }
  async function call(method, path, body, target = scope) {
    if (!target || typeof api !== 'function') throw Error('先在上方选择完整的用户、角色与会话。');
    const result = await api(method, 'page/autonomous-life/' + path, body);
    if (result?.ok !== true || result.backend !== 'autonomous_life' || key(result.scope) !== key(target)) {
      const error = Error('个人生活资料返回的范围或格式不匹配，请刷新核对。');
      if (method === 'POST') error.outcomeUnknown = true;
      throw error;
    }
    return result.result;
  }

  const decisionFold=node('details',undefined,'ps-decision-fold');decisionFold.append(node('summary','生活下一步 · 查看选择依据'));$('decision').before(decisionFold);decisionFold.append($('decision'));root.querySelector('.personal-space').append(decisionFold);
  let displayMode='visual', visualSection='spaces', summaryAt=0;
  $('counts').insertAdjacentHTML('afterend','<nav class="ps-modes" aria-label="档案显示方式"><button type="button" data-ps-mode="visual" data-ps-read>生活画卷</button><button type="button" data-ps-mode="catalog" data-ps-read>资料维护</button></nav><section data-ps-visual class="ps-visual" aria-label="私人数字档案可视图"></section>');
  function showMode(value) {
    displayMode=value;root.dataset.psMode=value;
    for(const b of root.querySelectorAll('[data-ps-mode]'))b.setAttribute('aria-pressed',String(b.dataset.psMode===value));
    $('visual').hidden=value!=='visual';root.querySelector('.ps-tabs').hidden=value==='visual';root.querySelector('#ps-records').hidden=value==='visual';
  }
  for(const b of root.querySelectorAll('[data-ps-mode]'))b.addEventListener('click',()=>{showMode(b.dataset.psMode);controls();});
  function visualRecord(parent,row,compact=false) {
    if(!row?.id||!labels[row.kind])return;
    const b=action(parent,'',()=>openRecord(row.kind,row.id),'ps-visual-record'+(compact?' ps-visual-compact':''));b.dataset.psRead='true';
    b.append(node('span',labels[row.kind]+(row.valid===false?' · 待复核':''),'ps-badge'),node('strong',title(row)));
    const copy=row.fields?.next_direction||row.fields?.goal||row.fields?.description;
    if(copy&&!compact)b.append(node('p',copy,'hint'));
    return b;
  }
  function drawVisual() {
    const parent=$('visual');parent.replaceChildren();const data=overview?.visual;
    if(!data){parent.append(node('p',scope?'读取资料后，空间、收藏与兴趣会在这里连起来。':'请先选择上方的角色与会话。','empty'));return;}
    const head=node('div',undefined,'ps-visual-heading');head.append(node('div','私人数字档案','ps-eyebrow'),node('h3','把生活中留下的东西，放在一起'));
    head.append(node('p',data.last_updated_at?'最近资料更新 · '+stamp(data.last_updated_at):'尚未建立私人资料，可以从一个空间或一项明确的收藏开始。','hint'));parent.append(head);
    const nav=node('nav',undefined,'ps-visual-nav');nav.setAttribute('aria-label','画卷分区');
    for(const [id,label]of [['spaces','空间与物品'],['interests','兴趣脉络'],['explorations','探索看板'],['collections','收藏书架'],['recent','最近更新']]){
      const b=action(nav,label,()=>{visualSection=id;drawVisual();controls();});b.dataset.psRead='true';b.dataset.psScene=id;b.setAttribute('aria-pressed',String(id===visualSection));
    }parent.append(nav);
    const area=node('div',undefined,'ps-visual-grid');area.dataset.psSceneBody=visualSection;parent.append(area);
    const section=(label,copy)=>{const box=node('article',undefined,'ps-visual-group');box.append(node('h4',label));if(copy)box.append(node('p',copy,'hint'));area.append(box);return box;};
    const empty=(label,copy,target)=>{const box=section(label,copy);action(box,'查看'+labels[target],()=>switchKind(target)).dataset.psRead='true';};
    if(visualSection==='spaces'){
      for(const group of data.spaces||[]){const box=section(group.record.fields?.area||'私人空间',group.item_count+' 件物品');visualRecord(box,group.record);const items=node('div',undefined,'ps-visual-branch');for(const row of group.items||[])visualRecord(items,row,true);if(!items.children.length)items.append(node('p','尚未放置物品','hint'));box.append(items);if(group.item_count>(group.items||[]).length)action(box,'查看这个空间的全部关联',()=>openRecord('space',group.record.id)).dataset.psRead='true';}
      if(data.unplaced_items?.count){const box=section('尚未归入空间',data.unplaced_items.count+' 件 · 原来源仍保留');for(const row of data.unplaced_items.records)visualRecord(box,row,true);}
      if(!area.children.length)empty('留一处自己的地方','空间来自实际维护记录，不自动填入虚构布置。','space');
    }else if(visualSection==='interests'){
      for(const group of data.interests||[]){const f=group.record.fields||{},box=section(statusLabels[f.status]||'兴趣',group.collection_count+' 项收藏 · '+group.exploration_count+' 段探索');visualRecord(box,group.record);const branch=node('div',undefined,'ps-visual-branch');for(const row of [...group.explorations||[],...group.collections||[]])visualRecord(branch,row,true);if(branch.children.length)box.append(branch);}
      if(!area.children.length)empty('还没有持续兴趣','一次收藏不会自动变成长期兴趣。可以维护来源、下一步方向与关注状态。','interest');
      if(data.interest_count>(data.interests||[]).length)action(area,'查看全部兴趣',()=>switchKind('interest')).dataset.psRead='true';
    }else if(visualSection==='explorations'){
      area.classList.add('ps-visual-board');for(const id of ['planned','active','paused','completed','cancelled']){const lane=(data.exploration_states||[]).find(x=>x.value===id);if(id==='cancelled'&&!lane)continue;const box=section(statusLabels[id]+' · '+(lane?.count||0));box.dataset.psLane=id;for(const row of lane?.records||[])visualRecord(box,row,true);if(!lane?.count)box.append(node('p','暂无记录','hint'));action(box,'查看此状态',()=>{$('state').value=id;switchKind('exploration');}).dataset.psRead='true';}
    }else if(visualSection==='collections'){
      for(const group of data.collection_categories||[]){const box=section(categoryLabels[group.value]||group.value,group.count+' 项个人收藏');for(const row of group.records||[])visualRecord(box,row,true);action(box,'查看这一类',()=>{$('category').value=group.value;switchKind('collection');}).dataset.psRead='true';}
      if(!area.children.length)empty('收藏书架还是空的','个人收藏与服务器素材库不同。从已有资料选择收藏，只保留原资源引用。','collection');
      const box=section('从资料库继续','音乐、图片与个人收藏沿用同一份原始资料。');for(const [id,label]of [['music_library','音乐资料库'],['assets','图片资料库']])action(box,label,()=>typeof setView==='function'&&setView(id)).dataset.psRead='true';
      action(box,'挑选音乐或图片收藏',()=>{showMode('catalog');kind='collection';selected=null;records=[];total=0;offset=0;paintTabs();drawList();drawDetail();openPicker();}).dataset.psRead='true';
    }else{
      area.classList.add('ps-visual-timeline');for(const row of data.recent_updates||[]){const box=section(stamp(row.updated_at));visualRecord(box,row);}
      if(!area.children.length)empty('还没有资料更新','这里排列档案保存时间，不冒充角色生活发生的时间。','space');
      parent.append(node('p','按档案更新时间排列。真实的虚构生活事件请进入“生活档案”。','hint'));
    }
    if(data.review_count){const warning=node('div',undefined,'ps-visual-review');warning.append(node('span',data.review_count+' 条档案的关联来源需要核对'));action(warning,'查看待复核',()=>switchKind('review')).dataset.psRead='true';parent.append(warning);}
    showMode(displayMode);
  }

  function drawCounts() {
    $('counts').replaceChildren();
    for (const [id, label] of Object.entries(labels)) {
      const card = action($('counts'), '', () => switchKind(id), 'ps-count'); card.dataset.psRead = 'true';
      card.append(node('span', label), node('strong', overview?.display_counts?.[id] ?? overview?.counts?.[countKeys[id]] ?? overview?.counts?.[id] ?? '—'));
    }
    const count = reviewTotal ?? overview?.counts?.review ?? overview?.review_count;
    const card = action($('counts'), '', () => switchKind('review'), 'ps-count'); card.dataset.psRead = 'true';
    card.append(node('span','关联待复核'),node('strong',count ?? '—'));
    root.querySelector('[data-ps-tab="review"]').textContent = '关联待复核 · ' + (count ?? '—');
  }
  function drawDecision(decision = overview?.decision) {
    const parent = $('decision'); parent.replaceChildren();
    const header = node('div', undefined, 'ps-decision-head'); header.append(node('h3', '下一步，想把时间留给什么'));
    action(header, '重新预览', preview).dataset.psPreview = 'true'; parent.append(header);
    parent.append(node('p', '只读取当前资料并按规则预览；不会调用模型、推进剧情、保存经历或发送消息。', 'hint'));
    if (!decision) {parent.append(node('p', scope ? '读取当前资料后显示生活选择。' : '选定会话后，查看她已有的兴趣与可做的事。', 'ps-decision-copy')); return;}
    const reason = decision.reason_label || decision.explanation || decision.reason || decision.message;
    const choice = decision.choice || decision.selected || decision.candidate;
    if (typeof reason === 'string') parent.append(node('p', reason, 'ps-decision-copy'));
    if (typeof choice === 'string') parent.append(node('p', choice, 'ps-decision-copy'));
    else if (choice && typeof choice === 'object') {
      const related = refs[choice.kind]?.find(row => row.id === choice.id);
      parent.append(node('strong', choice.name || choice.title || choice.label || (related ? title(related) : decisionLabels[choice.action || decision.action]) || '当前候选'));
      if (choice.reason || choice.description) parent.append(node('p', choice.reason || choice.description, 'ps-decision-copy'));
      const refKind = choice.kind || (choice.interest_id ? 'interest' : null), id = choice.id || choice.interest_id;
      if (id && (labels[refKind] || ['event','character','thread'].includes(refKind))) action(parent, '查看这项资料', () => labels[refKind] ? openRecord(refKind, id) : openLife(refKind, id)).dataset.psRead = 'true';
    }
    const candidates = decision.candidates || decision.options || [];
    if (Array.isArray(candidates) && candidates.length) {
      const list = node('div', undefined, 'ps-choice-list');
      for (const row of candidates.slice(0, 8)) {
        const item = node('div', undefined, 'ps-choice');
        const related = refs[row.kind]?.find(record => record.id === row.id);
        item.append(node('strong', row.name || row.title || row.label || (related ? title(related) : decisionLabels[row.action]) || labels[row.kind] || '可选活动'));
        if (row.reason_label || row.reason || row.description) item.append(node('small', row.reason_label || row.reason || row.description));
        if (row.id && (labels[row.kind] || ['event','character','thread'].includes(row.kind))) action(item, '查看', () => labels[row.kind] ? openRecord(row.kind, row.id) : openLife(row.kind, row.id)).dataset.psRead = 'true';
        list.append(item);
      }
      const more = node('details'); more.append(node('summary', '其他选择与依据'), list); parent.append(more);
    }
    if (!reason && !choice && !candidates.length) parent.append(node('p', '当前没有适合继续的候选，可以留出一段平静的时间。', 'ps-decision-copy'));
  }
  function drawList() {
    const parent = $('list'); parent.replaceChildren();
    for (const record of records) {
      const f = record.fields || {}, card = action(parent, '', () => kind === 'review' ? openReview(record.kind,record.id) : openRecord(kind, record.id), 'ps-card'); card.dataset.psRead = 'true';
      card.dataset.selected = String(selected?.id === record.id && selected?.kind === (kind==='review'?record.kind:kind));
      const badge = node('span', record.deleted ? '已删除' : record.archived ? '已归档' : record.valid === false ? '待复核' : statusLabels[f.status] || (kind === 'exploration' ? sourceLabels[f.source_kind] || '虚构探索' : '虚构生活'), 'ps-badge');
      card.append(badge, node('strong', title(record)));
      if (f.description || f.goal || f.findings) card.append(node('p', String(f.description || f.goal || f.findings).slice(0, 120), 'ps-card-copy'));
      card.append(node('small', kind === 'collection' ? (categoryLabels[f.category] || '收藏') + ' · ' + stamp(record.updated_at) : '更新于 ' + stamp(record.updated_at)));
    }
    if (!records.length) parent.append(node('p', scope ? kind === 'review' ? '当前筛选下没有待复核的关联。' : '还没有符合筛选条件的' + labels[kind] + '。可以从一条有来源的记录开始。' : '先在上方选择完整会话。', 'empty'));
    $('range').textContent = total ? `${offset + 1}–${offset + records.length} / ${total}` : '0 项'; controls();
  }
  function fact(parent, label, value) {
    if (value === undefined || value === null || value === '' || Array.isArray(value) && !value.length) return;
    const wrap = node('div', undefined, 'ps-fact'); wrap.append(node('dt', label), node('dd', Array.isArray(value) ? value.join('\n') : value)); parent.append(wrap);
  }
  function links(parent, label, ids, refKind) {
    if (!Array.isArray(ids) || !ids.length) return;
    const group = node('div', undefined, 'ps-links'); group.append(node('span', label, 'hint'));
    for (const id of ids) {
      const record = refs[refKind]?.find(row => row.id === id);
      action(group, record ? title(record) : id, () => labels[refKind] ? openRecord(refKind, id) : openLife(refKind, id)).dataset.psRead = 'true';
    }
    parent.append(group);
  }
  function safeURL(value) {try {const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null;} catch (_) {return null;}}
  const resourceScope = row => row?.source_scope ?? row?.scope;
  const sourceName = row => row?.label || (resourceScope(row) && FIELDS.map(name=>resourceScope(row)[name]).filter(value=>typeof value==='string').join(' / ')) || '来源未提供名称';
  const resourceTitle = row => row?.name || row?.metadata?.title || row?.metadata?.caption || row?.id || '未命名条目';
  const requestId = () => {const uuid = global.TLSBrowserCompat?.uuid?.() || global.crypto?.randomUUID?.(); if (!uuid) throw Error('当前浏览器无法生成请求标识，请刷新后操作。'); return 'personal-ui-' + uuid;};
  function resourceMetadata(parent, row) {
    const facts = node('dl',undefined,'ps-facts'), metadata = row?.metadata || {};
    for (const [name,label] of [['title','曲名'],['artist','作者／演出者'],['album','专辑'],['caption','图片说明'],['tags','标签'],['width','宽度'],['height','高度'],['format','格式']]) fact(facts,label,metadata[name]);
    if (row.description) fact(facts,'资料说明',row.description);
    fact(facts,'当前版本',row.revision); parent.append(facts);
  }
  function drawResourceList() {
    const parent = $('resource-list'); parent.replaceChildren();
    for (const row of picker.records) {
      const card = action(parent,'',()=>selectResource(row),'ps-card'); card.dataset.psResourceRead = 'true'; card.dataset.selected = String(picker.selected?.id === row.id);
      card.append(node('span',row.available === false ? '当前不可用' : '已有资料','ps-badge'),node('strong',resourceTitle(row)));
      if (row.metadata?.artist || row.description) card.append(node('p',row.metadata?.artist || row.description,'ps-card-copy'));
      card.append(node('small','版本 ' + row.revision));
    }
    if (!picker.records.length) parent.append(node('p',picker.source ? '此来源下没有符合条件的资料。' : '请明确选择一个资料来源。','empty'));
    $('resource-range').textContent = picker.total ? `${picker.offset+1}–${picker.offset+picker.records.length} / ${picker.total}` : '0 项'; controls();
  }
  function selectResource(row) {
    if (busy || !scope) return;
    if(row.type!==picker.type||key(row.source_scope)!==key(resourceScope(picker.source))){message('资料条目与所选来源不匹配，请重新读取。',true);return;}
    picker.selected = structuredClone(row); const parent = $('resource-preview'); parent.replaceChildren();
    parent.append(node('p',(row.type === 'image' ? '图片' : '音乐') + ' · 已有资料预览','ps-eyebrow'),node('h3',resourceTitle(row)));
    parent.append(node('p','来源：' + sourceName(picker.source),'hint')); resourceMetadata(parent,row);
    parent.append(node('p','这里只预览资料说明与元信息；没有播放音乐、发送图片或生成新素材。','hint'));
    if (row.available === false) parent.append(node('p','此条目当前不可收藏，请重新读取或选择可用资料。','ps-warning'));
    $('collect-name').value = ''; $('collect-description').value = '';
    $('collect-interest').replaceChildren(); for (const value of refOptions('interest',[],true)) {const option=node('option',value.label);option.value=value.value;$('collect-interest').append(option);}
    $('collect-form').hidden = row.available === false; drawResourceList(); controls();
  }
  async function loadResourceSources() {
    if (busy || !scope) return;
    const target = {...scope}, token = ++serial; busy = true; controls();
    picker.source = null; picker.selected = null; picker.records = []; picker.total = 0; picker.offset = 0;
    $('resource-source').replaceChildren(node('option','正在读取已授权来源…')); $('collect-form').hidden = true; $('resource-preview').replaceChildren(node('p','先选择来源，再选择资料查看收藏预览。','empty'));
    try {
      const result = await call('GET','personal/resource-sources',{...target,resource_type:picker.type},target);
      if (token !== serial || !same(target)) return;
      picker.sources = (result.sources || result.records || []).filter(row=>!Array.isArray(row.resource_types) || row.resource_types.includes(picker.type));
      $('resource-source').replaceChildren(); const empty = node('option',picker.sources.length ? '请选择资料来源' : '没有可读取的授权来源'); empty.value=''; $('resource-source').append(empty);
      picker.sources.forEach((row,index)=>{const option=node('option',sourceName(row)+' · '+(row.count ?? row.total ?? '数量未提供'));option.value=String(index);option.disabled=row.available===false;$('resource-source').append(option);});
    } catch (error) {if (token === serial && same(target)) {picker.sources=[];$('resource-source').replaceChildren(node('option','来源读取失败，请切换类型重试'));message(error.publicMessage || error.message,true);}}
    finally {if (token === serial && same(target)) {busy=false;drawResourceList();controls();}}
  }
  async function loadResources() {
    if (busy || !scope || !picker.source) return;
    const target={...scope},token=++serial;busy=true;controls();picker.selected=null;$('collect-form').hidden=true;$('resource-preview').replaceChildren(node('p','选择一项已有资料查看收藏前预览。','empty'));
    try {
      const source = resourceScope(picker.source);
      const result=await call('GET','personal/resources',{...target,resource_type:picker.type,source_scope:JSON.stringify(source),query:$('resource-query').value.trim(),limit:12,offset:picker.offset},target);
      if(token!==serial||!same(target))return;picker.records=result.records||[];picker.total=result.total??picker.records.length;drawResourceList();
    }catch(error){if(token===serial&&same(target)){picker.records=[];picker.total=0;drawResourceList();message(error.publicMessage||error.message,true);}}
    finally{if(token===serial&&same(target)){busy=false;controls();}}
  }
  function openPicker() {
    if(busy||!scope||pending.has(key(scope)))return;
    $('picker').hidden=false;picker.type=$('resource-type').value;$('resource-query').value='';loadResourceSources();$('picker').scrollIntoView({block:'nearest'});
  }
  const sourceStates={available:'来源可用',changed:'来源版本已变化',missing:'来源已不存在',archived:'来源已归档',denied:'当前无权读取',needs_review:'来源本身仍待复核'};
  function sourceSnapshot(parent,label,snapshot) {
    const side=node('section',undefined,'ps-source-snapshot');side.append(node('h4',label));
    if(!snapshot){side.append(node('p','当前无法读取此来源。','hint'));parent.append(side);return;}
    const facts=node('dl',undefined,'ps-facts');fact(facts,'版本',snapshot.version ?? snapshot.revision);
    const fields=snapshot.fields || snapshot.metadata || snapshot.snapshot?.fields || {};
    let shown=0;for(const [name,value]of Object.entries(fields)){if(typeof value==='string'||typeof value==='number'||typeof value==='boolean'||Array.isArray(value)&&value.every(item=>typeof item==='string')){fact(facts,fieldLabels[name]||({title:'标题',content:'正文',artist:'作者／演出者',album:'专辑',caption:'图片说明',tags:'标签'}[name])||name,typeof value==='boolean'?(value?'是':'否'):value);shown++;}}
    if(!shown)side.append(node('p','服务器保留了版本引用，未返回可展示的旧正文。','hint'));side.append(facts);parent.append(side);
  }
  function drawReview() {
    const parent=$('review-changes');parent.replaceChildren();$('review').hidden=!review;
    if(!review)return;
    for(const source of review.sources||[]){const block=node('section',undefined,'ps-source-change');block.append(node('h4',({event:'生活经历',character:'相关人物',thread:'开放事项',space:'私人空间',interest:'兴趣',resource:'收藏资料'}[source.kind]||labels[source.kind]||source.kind||'关联来源')+' · '+(sourceStates[source.status]||source.status||'等待核对')));const pair=node('div',undefined,'ps-source-compare');sourceSnapshot(pair,'记录当时使用的来源',source.previous);sourceSnapshot(pair,'当前来源',source.current);block.append(pair);parent.append(block);}
    if(!(review.sources||[]).length)parent.append(node('p','当前没有返回可对照的来源明细，请核对记录说明与服务器状态。','hint'));
    $('review-blocked').textContent=(review.blocked_reasons||[]).map(row=>typeof row==='string'?row:sourceStates[row.reason]||row.reason||'关联来源尚不可确认').join('；');
    $('review-form').hidden=review.can_confirm!==true;
    if(review.can_confirm!==true&&!$('review-blocked').textContent)$('review-blocked').textContent='当前关联仍不满足确认条件；先修复或恢复来源，再重新读取。';
    controls();
  }
  async function openReview(recordKind,id) {
    if(busy||!scope||!labels[recordKind])return;
    const target={...scope},token=++serial;busy=true;controls();
    try{const result=await call('GET','personal/review-preview',{...target,kind:recordKind,id},target);if(token!==serial||!same(target))return;
      review={...result,scope:target,kind:recordKind,id};selected={...result.record,kind:recordKind};if(draft?.reviewToken){draft.reviewToken=null;$('form').querySelector('[type=submit]').hidden=false;$('reason-wrap').hidden=false;}$('review-confirmed').checked=false;$('review-edit').checked=false;$('review-reason').value='';drawDetail();drawReview();
    }catch(error){if(token===serial&&same(target)){review=null;drawReview();message(error.publicMessage||error.message,true);}}
    finally{if(token===serial&&same(target)){busy=false;controls();}}
  }
  async function loadReviews() {
    if(busy||!scope)return;
    const target={...scope},token=++serial;busy=true;controls();
    try{const result=await call('GET','personal/review-list',{...target,query:$('query').value.trim(),limit:24,offset},target);if(token!==serial||!same(target))return;
      records=result.records||[];total=result.total??records.length;reviewTotal=total;if(overview)overview.review_count=total;if(pending.has(key(target)))pending.get(key(target)).checked=true;
      selected=null;review=null;drawCounts();drawList();drawDetail();drawReview();message(pending.has(key(target))?'已回读待复核资料，请先核对原操作是否生效。':'已读取需要人工核对的来源关联；没有自动确认或重写。');
    }catch(error){if(token===serial&&same(target))message(error.publicMessage||error.message,true);}
    finally{if(token===serial&&same(target)){busy=false;controls();}}
  }
  function sourceDetails(parent, record) {
    const section = node('section', undefined, 'ps-provenance');
    section.append(node('h4', '来源与资料边界'));
    section.append(node('p', '记录方式：' + (sourceLabels[record.source?.kind] || record.source?.kind || '未注明来源'), 'hint'));
    const f = record.fields || {};
    if (f.source_kind) section.append(node('p', '内容依据：' + (sourceLabels[f.source_kind] || f.source_kind), 'ps-source-kind'));
    if (f.source_kind === 'model_inference') section.append(node('p', '推测尚未被外部资料或经历证实，请勿作为正典或真实发生的事实。', 'ps-warning'));
    if (f.source_kind === 'original_fiction') section.append(node('p', '这段发现属于原创虚构，不代表泰拉正典或现实事实。', 'hint'));
    const sources = Array.isArray(f.sources) ? f.sources : [];
    for (const source of sources) {
      const row = node('div', undefined, 'ps-source');
      row.append(node('span', sourceLabels[source.kind] || source.kind || '未分类来源', 'ps-badge'));
      const url = safeURL(source.url);
      if (url) {const link = node('a', source.title || source.url); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(link);}
      else row.append(node('span', source.title || source.url || '未填写来源标题'));
      section.append(row);
    }
    const ref = record.source?.ref;
    if (typeof ref === 'string' && ref) section.append(node('p', '记录引用：' + ref, 'hint'));
    if (!sources.length && record.kind === 'exploration') section.append(node('p', '尚未附上外部资料；已标注的内容依据仍需按来源核对。', 'hint'));
    parent.append(section);
  }
  function drawDetail(history = []) {
    const parent = $('detail'); parent.replaceChildren();
    if (!selected) {parent.append(node('p', '选择一项，查看她的生活细节、关联和修正历史。', 'empty')); return;}
    const record = selected, f = record.fields || {}, recordKind = record.kind || kind;
    parent.append(node('p', labels[recordKind] + ' · 虚构角色生活', 'ps-eyebrow'), node('h3', title(record)), node('p', '修订 ' + record.revision + ' · ' + stamp(record.updated_at), 'hint'));
    if (record.deleted) parent.append(node('p', '此记录已软删除，保留版本历史。恢复后仍需核对关联来源。', 'ps-warning'));
    else if (record.archived) parent.append(node('p', '此记录已归档，不进入普通生活选择。', 'hint'));
    if (record.valid === false) parent.append(node('p', '关联待复核：' + (Array.isArray(record.invalid_reasons) ? record.invalid_reasons.join('；') : '来源或关联版本已变化。'), 'ps-warning'));
    const facts = node('dl', undefined, 'ps-facts');
    for (const name of ['description','origin_note','attention','next_direction','environment','area','origin','giver','status','goal','findings','questions','explored','gifted_at','last_attended_at','worth_continuing','message_ref','category','resource_id','resource_type']) {
      let value = f[name]; if(name === 'attention') value=({growing:'逐渐加深',steady:'持续关注',fading:'渐渐淡去'})[value] || value; if (name === 'origin') value = originLabels[value] || value; if (name === 'status') value = statusLabels[value] || value; if (name === 'category') value = categoryLabels[value] || value;
      if (['gifted_at','last_attended_at'].includes(name)) value = value ? stamp(value) : null;
      if (name === 'worth_continuing' && typeof value === 'boolean') value = value ? '值得继续关注' : '暂不继续';
      fact(facts, fieldLabels[name], value);
    }
    fact(facts,'首次记录',stamp(record.created_at)); parent.append(facts);
    if (record.archive_links?.length) {const related=node('section',undefined,'ps-links');related.append(node('h4','关联档案'));for(const link of record.archive_links){action(related,labels[link.kind]+' · '+title(link)+(link.valid===false?'（待复核）':''),()=>openRecord(link.kind,link.id)).dataset.psRead='true';}parent.append(related);}
    if (recordKind === 'item' && f.origin === 'user_gift') parent.append(node('p', '赠礼信息由管理员手动录入；原消息引用尚未自动核验，不代表系统已确认真实赠送。', 'ps-warning'));
    links(parent, '所在空间', f.space_id ? [f.space_id] : [], 'space'); links(parent, '关联兴趣', f.interest_id ? [f.interest_id] : [], 'interest');
    links(parent, '来源经历', f.event_ids, 'event'); links(parent, '相关人物', f.character_ids, 'character'); sourceDetails(parent, record);
    if (recordKind === 'collection' && ['music','image'].includes(f.category)) {
      if(record.resource){const status=node('section',undefined,'ps-provenance');status.append(node('h4','收藏资料当前状态'),node('p',record.resource.state||'未提供状态','hint'));if(record.resource.metadata)resourceMetadata(status,{...record.resource,revision:record.resource.revision||record.resource.current_revision});parent.append(status);}
      action(parent, '打开' + categoryLabels[f.category] + '资料库核对', () => typeof setView === 'function' && setView(f.category === 'music' ? 'music_library' : 'assets')).dataset.psRead = 'true';
    }
    const actions = node('div', undefined, 'actions');
    if (!record.deleted) action(actions, '编辑' + labels[recordKind], () => editor(recordKind, record));
    if (record.valid === false) action(actions,'查看关联变化与复核',()=>openReview(recordKind,record.id)).dataset.psRead='true';
    action(actions, record.deleted ? '恢复已删除记录' : record.archived ? '恢复归档' : '归档', () => maintenance(record.deleted || record.archived ? 'restore' : 'archive', record));
    if (!record.deleted) action(actions, '软删除', () => maintenance('delete', record), 'danger');
    parent.append(actions);
    const versions = node('details', undefined, 'ps-history'); versions.append(node('summary', '修正历史与记录编号'));
    versions.append(node('code', record.id));
    const rows = Array.isArray(history) ? history : history?.records || history?.history || [];
    for (const row of rows) {
      const item = node('details'); item.append(node('summary', '版本 ' + (row.version ?? row.revision ?? '') + ' · ' + stamp(row.at || row.replaced_at || row.updated_at)), node('p', row.reason || '资料维护', 'hint'));
      const old = row.snapshot?.fields || row.fields;
      if (old) {const values = node('dl', undefined, 'ps-facts'); for (const name of ['name','description','status','goal','findings','questions','explored']) fact(values, fieldLabels[name], statusLabels[old[name]] || old[name]); item.append(values);}
      versions.append(item);
    }
    if (!rows.length) versions.append(node('p', '尚无可显示的修正记录。', 'hint'));
    parent.append(versions); controls();
  }
  async function openLife(refKind, id) {
    if (busy || !scope) return;
    const target = {...scope}, token = ++serial; busy = true; controls();
    try {
      const record = await call('GET', refKind, {...target, id}, target);
      if (token !== serial || !same(target)) return;
      lifeReference = {kind:refKind, id}; const parent = $('reference'); parent.replaceChildren(); parent.hidden = false;
      const head = node('div', undefined, 'panel-head'); head.append(node('h3', '关联' + ({event:'经历',character:'人物',thread:'开放事项'}[refKind] || '资料') + ' · ' + title(record)));
      action(head, '收起', () => {parent.hidden = true; lifeReference = null;}).dataset.psRead = 'true'; parent.append(head);
      for (const name of ['content','description','relationship','detail']) if (record.fields?.[name]) parent.append(node('p', record.fields[name], 'ps-reference-copy'));
      parent.append(node('p', '虚构生活档案 · ' + record.id, 'hint'));
      if (typeof global.TLSAutonomousLifePanel?.openRecord === 'function') action(parent, '在生活档案中维护', () => {setView('autonomous_life'); global.TLSAutonomousLifePanel.openRecord(refKind, id);}).dataset.psRead = 'true';
    } catch (error) {if (token === serial && same(target)) message(error.publicMessage || error.message, true);}
    finally {if (token === serial && same(target)) {busy = false; controls();}}
  }
  async function openRecord(recordKind, id) {
    if (busy || !scope || !labels[recordKind]) return;
    showMode('catalog');
    if (kind !== recordKind) {kind = recordKind; offset = 0; paintTabs(); records = []; total = 0;}
    const target = {...scope}, token = ++serial; busy = true; controls();
    try {
      const [record, history, list] = await Promise.all([
        call('GET', 'personal/record', {...target, kind:recordKind, id}, target),
        call('GET', 'personal/history', {...target, kind:recordKind, id, limit:20}, target),
        call('GET', 'personal/records', listQuery(target), target)
      ]);
      if (token !== serial || !same(target)) return;
      selected = {...record, kind:recordKind}; records = list.records || []; total = list.total ?? records.length; drawList(); drawDetail(history);
    } catch (error) {if (token === serial && same(target)) message(error.publicMessage || error.message, true);}
    finally {if (token === serial && same(target)) {busy = false; controls();}}
  }
  const listQuery = target => ({...target, kind, status:['interest','exploration'].includes(kind)?$('state').value:'', category:kind==='collection'?$('category').value:'',sort:$('sort').value, query:$('query').value.trim(), include_archived:$('archived').checked, include_invalid:$('invalid').checked, limit:24, offset});
  async function load(refreshSummary = false) {
    if (busy) return;
    if (key(scope) !== key(currentScope())) scopeChanged();
    if (!scope) {controls(); return;}
    if(kind==='review'){await loadReviews();return;}
    const target = {...scope}, token = ++serial, selectedId = selected?.id;
    const fetchSummary=refreshSummary===true||!overview||Date.now()-summaryAt>60000; busy = true; controls();
    try {
      const [list, summary, spaces, interests, events, people, selectedRead, history] = await Promise.all([
        call('GET','personal/records',listQuery(target),target), fetchSummary?call('GET','personal/overview',target,target):overview,
        fetchSummary?call('GET','personal/records',{...target,kind:'space',limit:100,offset:0},target):{records:refs.space},
        fetchSummary?call('GET','personal/records',{...target,kind:'interest',limit:100,offset:0},target):{records:refs.interest},
        fetchSummary?call('GET','events',{...target,limit:100},target):{records:refs.event}, fetchSummary?call('GET','characters',{...target,limit:100},target):{records:refs.character},
        selectedId ? call('GET','personal/record',{...target,kind,id:selectedId},target) : null,
        selectedId ? call('GET','personal/history',{...target,kind,id:selectedId,limit:20},target) : null
      ]);
      if (token !== serial || !same(target)) return;
      records = list.records || []; total = list.total ?? records.length; overview = summary;if(fetchSummary)summaryAt=Date.now();
      refs = {space:spaces.records || [], interest:interests.records || [], event:events.records || [], character:people.records || []};
      if (selectedRead) selected = {...selectedRead, kind};
      if (pending.has(key(target))) pending.get(key(target)).checked = true;
      drawCounts(); drawDecision(); drawVisual(); drawList(); drawDetail(history || []);
      message(pending.has(key(target)) ? '已回读服务器资料。请核对原操作是否生效；不会自动重发。' : '已读取当前会话的个人生活资料。读取没有调用模型。');
    } catch (error) {if (token === serial && same(target)) message(error.publicMessage || error.message, true);}
    finally {if (token === serial && same(target)) {busy = false; controls();}}
  }
  async function preview() {
    if (busy || !scope) return;
    const target = {...scope}, token = ++serial; busy = true; controls();
    try {const result = await call('GET','personal/decision',target,target); if (token === serial && same(target)) {drawDecision(result); message('已预览当前生活选择；没有推进生活或发送消息。');}}
    catch (error) {if (token === serial && same(target)) message(error.publicMessage || error.message,true);}
    finally {if (token === serial && same(target)) {busy = false; controls();}}
  }
  function input(name, label, type, value, options = []) {
    const wrap = node('label', label, type === 'checkbox' ? 'ps-check' : ''), element = node(type === 'textarea' ? 'textarea' : ['select','multiple'].includes(type) ? 'select' : 'input');
    element.dataset.psField = name;
    if (element.tagName === 'INPUT') element.type = type === 'lines' ? 'text' : type;
    if (['select','multiple'].includes(type)) {
      element.multiple = type === 'multiple'; if (element.multiple) element.size = 4;
      for (const item of options) {const option = node('option', item.label); option.value = item.value; option.selected = element.multiple ? (value || []).includes(item.value) : value === item.value; element.append(option);}
    } else if (type === 'checkbox') element.checked = value === true;
    else if (type === 'datetime-local' && value) {const date = new Date(value * 1000); date.setMinutes(date.getMinutes() - date.getTimezoneOffset()); element.value = date.toISOString().slice(0,16);}
    else element.value = Array.isArray(value) ? value.join('\n') : value ?? '';
    element.required = name === 'name';
    if (element.tagName !== 'SELECT') element.maxLength = name === 'name' ? 120 : name === 'description' ? 1200 : ['environment','area'].includes(name) ? 400 : name === 'giver' ? 120 : ['message_ref','_source_ref'].includes(name) ? 256 : 2400;
    if (['questions','explored','findings'].includes(name)) {element.dataset.psLines = 'true'; element.placeholder = '每行一项';}
    wrap.append(element); $('fields').append(wrap); return element;
  }
  const options = values => values.map(value => ({value, label:statusLabels[value] || sourceLabels[value] || categoryLabels[value] || value}));
  function refOptions(refKind, selectedIds = [], empty = false) {
    const list = (refs[refKind] || []).map(record => ({value:record.id,label:title(record)}));
    for (const id of selectedIds.filter(Boolean)) if (!list.some(row => row.value === id)) list.push({value:id,label:id + '（当前列表外，需核对）'});
    if (empty) list.unshift({value:'',label:'暂不关联'}); return list;
  }
  function sourcesEditor(sources) {
    const box = node('section', undefined, 'ps-source-editor'); box.dataset.psSources = 'true'; box.append(node('h4','参考资料'),node('p','每条资料单独标明依据。外部链接仅作引用，不会自动导入。','hint'));
    const rows = node('div'); rows.dataset.psSourceRows = 'true'; box.append(rows);
    function add(source = {}) {
      const row = node('div',undefined,'ps-source-row'); row.dataset.psSourceRow = 'true';
      for (const [name,label] of [['title','资料标题'],['url','资料链接']]) {const wrap = node('label',label), element = node('input'); element.dataset.psSourceField = name; element.type = name === 'url' ? 'url' : 'text'; element.value = source[name] || ''; element.maxLength = name === 'url' ? 1000 : 200; wrap.append(element); row.append(wrap);}
      const wrap = node('label','资料类别'), element = node('select'); element.dataset.psSourceField = 'kind';
      for (const item of options(['terra_canon','public_reference','original_fiction','model_inference'])) {const option = node('option',item.label); option.value = item.value; option.selected = item.value === (source.kind || 'public_reference'); element.append(option);}
      wrap.append(element); row.append(wrap); action(row,'移除',()=>row.remove()); rows.append(row); controls();
    }
    for (const source of sources || []) add(source);
    action(box,'添加一条资料',()=>{if(rows.children.length >= 8) {message('参考资料最多 8 条。',true); return;} add();}); $('fields').append(box);
  }
  function editor(recordKind, record = null) {
    if (busy || !scope || pending.has(key(scope))) return;
    draft = {kind:recordKind, record:record ? structuredClone(record) : null, scope:{...scope}, operation:null}; const f = record?.fields || {};
    $('fields').replaceChildren(); $('form').querySelector('[type=submit]').hidden=false; $('editor-title').textContent = (record ? '编辑' : '新增') + labels[recordKind];
    $('editor-identity').textContent = record ? '正在编辑：' + title(record) + ' · 修订 ' + record.revision : '新增内容属于上方选定的角色与会话。';
    $('reason').value = ''; $('reason').required = !!record; $('reason-wrap').hidden = !record;
    input('name','名称','text',f.name); input('description','说明（角色的虚构生活）','textarea',f.description);
    if (recordKind === 'space') {input('environment','环境','textarea',f.environment); input('area','区域','text',f.area);}
    if (recordKind === 'item') {
      input('space_id','放在哪个空间','select',f.space_id || '',refOptions('space',[f.space_id],true)); input('origin','来历','select',f.origin || 'ordinary',Object.entries(originLabels).map(([value,label])=>({value,label})));
      input('giver','赠送者','text',f.giver); input('gifted_at','赠送时间（当前设备时区）','datetime-local',f.gifted_at); input('message_ref','原消息引用（已有编号）','text',f.message_ref);
      const hint = node('p','若选择“用户赠礼”，请填写真实来源引用；此处手动录入不会自动核验原消息。','hint ps-maintenance-copy'); $('fields').append(hint);
    }
    if (recordKind === 'interest') {
      input('origin_note','兴趣缘由（不以单次收藏推断）','textarea',f.origin_note || '');
      input('attention','关注变化','select',f.attention || 'steady',[{value:'growing',label:'逐渐加深'},{value:'steady',label:'持续关注'},{value:'fading',label:'渐渐淡去'}]);
      input('next_direction','下一步想了解什么','textarea',f.next_direction || '');
      input('status','状态','select',f.status || 'active',options(['active','paused','completed'])); input('worth_continuing','仍值得继续关注','checkbox',f.worth_continuing ?? true);
      input('questions','想弄清的问题（每行一项）','textarea',f.questions || []); input('explored','已经了解的内容（每行一项）','textarea',f.explored || []); input('last_attended_at','最近关注时间（当前设备时区）','datetime-local',f.last_attended_at);
    }
    if (recordKind === 'exploration') {
      input('interest_id','属于哪项兴趣','select',f.interest_id || '',refOptions('interest',[f.interest_id],true));
      input('status','状态','select',f.status || 'planned',options(['planned','active','completed','paused','cancelled']));
      input('goal','这次想了解什么','textarea',f.goal); input('findings','目前的发现（每行一项）','textarea',f.findings || []);
      input('source_kind','发现的依据','select',f.source_kind || 'original_fiction',options(['terra_canon','public_reference','original_fiction','model_inference'])); sourcesEditor(f.sources);
    }
    if (recordKind === 'collection') {
      const linked=!!f.resource_id,category=input('category','收藏类型','select',f.category || 'note',options(Object.keys(categoryLabels).filter(value=>linked||!['music','image'].includes(value))));
      if(linked){category.dataset.psImmutable='true';input('resource_type','已关联的资料类型','text',f.resource_type).readOnly=true;input('resource_id','已关联的资料编号','text',f.resource_id).readOnly=true;}
      else $('fields').append(node('p','音乐与图片请使用“从音乐／图片资料库收藏”，核对真实来源后选择已有条目。','hint ps-maintenance-copy'));
      input('interest_id','关联兴趣','select',f.interest_id || '',refOptions('interest',[f.interest_id],true));
    }
    input('event_ids','来源经历（可多选）','multiple',f.event_ids || [],refOptions('event',f.event_ids));
    input('character_ids','相关人物（可多选）','multiple',f.character_ids || [],refOptions('character',f.character_ids));
    if (!record) {input('_source_ref','录入依据或资料引用（可选）','text','');}
    $('editor').hidden = false; controls(); $('editor').scrollIntoView({block:'nearest'}); $('fields').querySelector('input')?.focus({preventScroll:true});
  }
  function maintenance(operation, record) {
    editor(record.kind || kind,record); if (!draft) return; draft.operation = operation;
    $('fields').replaceChildren(node('p',operation === 'delete' ? '软删除后，这条资料会退出普通检索与生活选择，历史仍保留。可在“含归档与已删除”中核对并恢复。' : operation === 'restore' ? '恢复后将重新核对关联与来源；失效资料仍需要维护。' : '归档后保留详情与历史，暂不参与普通生活选择。','ps-maintenance-copy'));
    $('editor-title').textContent = ({archive:'归档',restore:'恢复',delete:'软删除'}[operation]) + labels[draft.kind]; $('reason').focus();
  }
  function readFields() {
    const fields = {};
    for (const element of $('fields').querySelectorAll('[data-ps-field]')) {
      const name = element.dataset.psField;
      fields[name] = element.multiple ? [...element.selectedOptions].map(option => option.value) : element.type === 'checkbox' ? element.checked : element.type === 'datetime-local' ? element.value ? Date.parse(element.value) / 1000 : null : element.dataset.psLines ? element.value.split('\n').map(value => value.trim()).filter(Boolean) : element.value.trim();
    }
    if ($('fields').querySelector('[data-ps-sources]')) fields.sources = [...$('fields').querySelectorAll('[data-ps-source-row]')].map(row => Object.fromEntries([...row.querySelectorAll('[data-ps-source-field]')].map(element => [element.dataset.psSourceField,element.value.trim()]))).filter(source => source.title || source.url);
    for (const source of fields.sources || []) if (source.url && !safeURL(source.url)) throw Error('参考资料链接需要使用 http 或 https。');
    for (const name of ['event_ids','character_ids']) if (fields[name]?.length > 8) throw Error('关联经历或人物最多选择 8 项。');
    for (const name of ['questions','explored','findings']) if (fields[name]?.length > 12 || fields[name]?.some(value=>value.length > 400)) throw Error('问题与发现最多 12 项，每项最多 400 字。');
    if (fields.origin === 'user_gift' && (!fields.giver || !fields.gifted_at || !fields.message_ref)) throw Error('用户赠礼需要填写赠送者、赠送时间和原消息引用。');
    return fields;
  }
  async function mutate(path, body, edit) {
    if (busy || !scope || pending.has(key(scope)) || !same(edit.scope)) return;
    const target = {...scope}, token = ++serial; busy = true; pending.set(key(target),{checked:false}); controls(); let failure = '';
    try {
      await call('POST','personal/' + path,{scope:target,...body},target);
      if (token !== serial || !same(target)) return;
      pending.delete(key(target)); draft = null; $('editor').hidden = true;
      if(path==='collect'){$('picker').hidden=true;picker.selected=null;}
      if(path==='review-confirm'){review=null;$('review').hidden=true;$('review-confirmed').checked=false;}
    } catch (error) {
      if (token === serial && same(target)) {failure = error.publicMessage || error.message; if (!error.outcomeUnknown && [400,401,403,404,409,413].includes(Number(error.status))) pending.delete(key(target));
        if(!error.outcomeUnknown&&Number(error.status)===409){if(path==='review-confirm'&&review){review.can_confirm=false;$('review-confirmed').checked=false;review.blocked_reasons=['来源或记录版本已变化，请重新读取变化后再人工确认。'];drawReview();}if(path==='collect'){picker.selected=null;$('collect-form').hidden=true;$('resource-preview').replaceChildren(node('p','资料版本已变化，请重新搜索并选择当前条目。','ps-warning'));}}
      }
    } finally {
      if (token === serial && same(target)) {busy = false; controls(); await load(true); if (failure) message(failure + (pending.has(key(target)) ? ' 请先核对服务器资料，不会自动重发。' : ''),true);}
    }
  }
  function paintTabs() {
    for (const tab of root.querySelectorAll('[data-ps-tab]')) {tab.setAttribute('aria-selected',String(tab.dataset.psTab === kind)); tab.tabIndex = tab.dataset.psTab === kind ? 0 : -1;}
    root.querySelector('#ps-records').setAttribute('aria-labelledby','ps-tab-' + kind);
    $('new').textContent = '新增' + (labels[kind]||'资料');$('new').hidden=kind==='review';$('pick').hidden=kind!=='collection';root.querySelector('.ps-filters').hidden=kind==='review';
    $('state').closest('label').hidden=!['interest','exploration'].includes(kind);
    $('category').closest('label').hidden=kind!=='collection';
  }
  function switchKind(value) {
    if (busy || !labels[value]&&value!=='review') return;
    showMode('catalog');
    kind = value; selected = null; records = []; total = 0; offset = 0; lifeReference = null; $('reference').hidden = true;
    review=null;$('review').hidden=true;$('picker').hidden=true;
    if(draft?.reviewToken){draft.reviewToken=null;$('form').querySelector('[type=submit]').hidden=false;$('reason-wrap').hidden=false;}
    paintTabs(); drawList(); drawDetail(); load();
  }
  function scopeChanged() {
    serial++; busy = false; scope = currentScope(); selected = null; records = []; total = 0; offset = 0; overview = null; draft = null; lifeReference = null;review=null;reviewTotal=null;
    picker={type:'music',sources:[],source:null,records:[],total:0,offset:0,selected:null};$('picker').hidden=true;$('review').hidden=true;$('review-confirmed').checked=false;$('review-edit').checked=false;
    refs = {space:[],interest:[],event:[],character:[]}; $('editor').hidden = true; $('reference').hidden = true;
    $('query').value = ''; $('archived').checked = false; $('invalid').checked = false;
    $('state').value='';$('category').value='';$('sort').value='updated';
    summaryAt=0;drawCounts(); drawDecision(); drawVisual(); drawList(); drawDetail(); message(scope ? '范围已切换，刷新后读取当前角色的个人生活。' : '先在上方选择完整的用户、角色与会话。'); controls();
  }
  for (const tab of root.querySelectorAll('[data-ps-tab]')) {
    tab.addEventListener('click',()=>switchKind(tab.dataset.psTab));
    tab.addEventListener('keydown',event=>{if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key) || busy) return; event.preventDefault(); const tabs = [...root.querySelectorAll('[data-ps-tab]')], index = tabs.indexOf(tab), next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs.at(-1) : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]; next.focus(); switchKind(next.dataset.psTab);});
  }
  $('refresh').addEventListener('click',()=>load(true)); $('search').addEventListener('submit',event=>{event.preventDefault(); offset = 0; load();});
  for (const filter of ['archived','invalid']) $(filter).addEventListener('change',()=>{offset = 0; load();});
  $('prev').addEventListener('click',()=>{offset = Math.max(0,offset - 24); load();}); $('next').addEventListener('click',()=>{offset += 24; load();});
  $('new').addEventListener('click',()=>editor(kind)); $('cancel').addEventListener('click',()=>{if(draft?.reviewToken)$('review-edit').checked=false;draft = null; $('editor').hidden = true;});
  $('pick').addEventListener('click',openPicker);$('picker-close').addEventListener('click',()=>{$('picker').hidden=true;});
  $('resource-type').addEventListener('change',()=>{picker.type=$('resource-type').value;$('resource-query').value='';loadResourceSources();});
  $('resource-source').addEventListener('change',()=>{picker.source=$('resource-source').value===''?null:picker.sources[Number($('resource-source').value)];picker.offset=0;if(picker.source)loadResources();else{picker.records=[];picker.selected=null;picker.total=0;$('collect-form').hidden=true;$('resource-preview').replaceChildren();drawResourceList();}});
  $('resource-search').addEventListener('submit',event=>{event.preventDefault();picker.offset=0;loadResources();});
  $('resource-prev').addEventListener('click',()=>{picker.offset=Math.max(0,picker.offset-12);loadResources();});$('resource-next').addEventListener('click',()=>{picker.offset+=12;loadResources();});
  $('collect-form').addEventListener('submit',event=>{event.preventDefault();if(!picker.selected?.available||!picker.source)return;try{const row=picker.selected;mutate('collect',{request_id:requestId(),resource_type:row.type||picker.type,resource_id:row.id,source_scope:resourceScope(picker.source),expected_resource_revision:row.revision,...($('collect-name').value.trim()?{name:$('collect-name').value.trim()}:{}),...($('collect-description').value.trim()?{description:$('collect-description').value.trim()}:{}),...($('collect-interest').value?{interest_id:$('collect-interest').value}:{})},{scope:{...scope}});}catch(error){message(error.message,true);}});
  $('review-refresh').addEventListener('click',()=>{if(review)openReview(review.kind,review.id);});
  $('review-confirmed').addEventListener('change',controls);
  $('review-edit').addEventListener('change',()=>{if(!review)return;if($('review-edit').checked){editor(review.kind,review.record);draft.reviewToken=review.source_token;$('form').querySelector('[type=submit]').hidden=true;$('reason-wrap').hidden=true;}else if(draft?.reviewToken){draft=null;$('editor').hidden=true;}});
  $('review-form').addEventListener('submit',event=>{event.preventDefault();if(!review||review.can_confirm!==true||!$('review-confirmed').checked)return;try{const reason=$('review-reason').value.trim();if(!reason)throw Error('请说明人工复核的原因。');let changes={};if($('review-edit').checked){if(!draft||draft.kind!==review.kind||draft.record?.id!==review.id||draft.reviewToken!==review.source_token)throw Error('编辑对象已变化，请重新选择“同时保存修正”并核对。');changes=readFields();delete changes._source_ref;}mutate('review-confirm',{kind:review.kind,id:review.id,expected_revision:review.record.revision,source_token:review.source_token,reason,changes,confirmed:true},{scope:review.scope});}catch(error){message(error.message,true);}});
  $('release').addEventListener('click',()=>{if (pending.get(key(scope))?.checked) {pending.delete(key(scope)); controls(); message('已结束等待；原操作仍可能稍后完成，继续修改前请核对最新资料。');}});
  $('form').addEventListener('submit',event=>{
    event.preventDefault(); if (!draft || !same(draft.scope)) return;
    try {
      if(draft.reviewToken)throw Error('请在来源对照区勾选人工确认、填写复核原因，再提交复核。');
      const reason = $('reason').value.trim(); if (draft.record && !reason) throw Error('请说明维护原因。');
      if (draft.operation) {mutate(draft.operation,{kind:draft.kind,id:draft.record.id,expected_revision:draft.record.revision,reason},draft); return;}
      const fields = readFields(), sourceRef = fields._source_ref; delete fields._source_ref;
      if (draft.record) mutate('update',{kind:draft.kind,id:draft.record.id,expected_revision:draft.record.revision,changes:fields,reason},draft);
      else {const uuid = global.TLSBrowserCompat?.uuid?.() || global.crypto?.randomUUID?.(); if (!uuid) throw Error('当前浏览器无法生成请求标识，请刷新后再操作。'); mutate('create',{kind:draft.kind,request_id:'personal-ui-' + uuid,fields,source:{kind:'operator',ref:sourceRef || 'personal-space-console'}},draft);}
    } catch (error) {message(error.message,true);}
  });
  global.TLSPersonalSpacePanel = {activate:()=>load(true),scopeChanged,openRecord}; paintTabs(); scopeChanged();showMode('visual');
})(window);
