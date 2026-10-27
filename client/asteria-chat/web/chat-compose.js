'use strict';

/* One composer over the existing chat/session/attachment transport. Assets and
   both preference sets live on TLS; only unsent composition stays on-device. */
window.ChatComposer = (() => {
  const model = { scope: '', serial: 0, loaded: false, loading: false, error: '',
    assets: [], actions: [], stickers: [], extras: [], order: [], panel: '', filter: 'all', query: '', touchCatalog:null, touchVerb:'', touchPart:'', touchUnknown:false,
    pickMode: 'attach', selected: null, actionEditing: null, batch: null, batchSerial: 0, busy: false,
    previews: new Map(), nativeViewport: null, watch: null, watchTarget: '', pendingWatch: '', notificationId: null };
  const node = id => document.getElementById(id);
  const scope = () => state.authenticated && state.activeId
    ? JSON.stringify([state.server, state.username, state.activeId,
      state.sessionPersonaConfig && state.sessionPersonaConfig.configuredId || '']) : '';
  const draftStore = () => pref('composition.' + encodeURIComponent(JSON.stringify([state.server, state.username, state.activeId || 'new'])));
  const endpoint = (name, extra = {}) => '/chat/' + name + '?' + new URLSearchParams({ session_id: state.activeId, ...extra });
  const call = (method, route, body) => apiClient.json(method, route, body);
  const assetId = item => String(item.id || item.asset_id || '');
  const actorPref = (asset, actor) => asset[actor === 'user' ? 'user_preference' : 'texas_preference'] || {};
  const setText = (id, text) => { if (node(id)) node(id).textContent = text; };
  function button(label, callback, className = '') {
    const result = document.createElement('button'); result.type = 'button'; result.textContent = label;
    result.className = className; result.addEventListener('click', callback); return result;
  }
  function persist() {
    try {
      localStorage.setItem(draftStore(), JSON.stringify({ version: 2, actions: state.pendingActions, stickers: model.stickers, extras: model.extras, order: model.order }));
    } catch (_) { showNotice('组合草稿未能保存到本机；当前输入仍保留。', null, true); }
  }
  function restore() {
    state.pendingActions = []; model.stickers = []; model.extras = []; model.order = [];
    try {
      const saved = JSON.parse(localStorage.getItem(draftStore()) || 'null');
      if (saved && [1, 2].includes(saved.version)) {
        model.extras = Array.isArray(saved.extras) ? saved.extras.filter(value => value && ['text','reference'].includes(value.type)).slice(0, 12) : [];
        model.order = Array.isArray(saved.order) ? saved.order.filter(value => typeof value === 'string').slice(0, 24) : [];
        state.pendingActions = (saved.actions || []).filter(value => value && typeof value.id === 'string'
          && typeof value.label === 'string' && typeof value.description === 'string').slice(0, 4);
        model.stickers = (saved.stickers || []).filter(value => value && typeof value.asset_id === 'string').slice(0, 4);
      }
    } catch (_) { showNotice('组合草稿无法读取，文字草稿仍保留。', null, true); }
    renderPreview();
  }
  function actionPart(value) {
    return { type: 'action', action_id: value.id || value.action_id, label: value.label,
      description: value.description || value.action, source: 'user_action' };
  }
  function identity(prefix = 'fragment') { return prefix + '-' + (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + '-' + Math.random().toString(36).slice(2)); }
  function parts(text) {
    const values = [...model.extras];
    if (text) values.push({type:'text',text,fragment_id:'current-draft'});
    for (const value of state.pendingActions) { if (!value.fragment_id) value.fragment_id = identity('action'); values.push({...actionPart(value),fragment_id:value.fragment_id}); }
    for (const value of model.stickers) { if (!value.fragment_id) value.fragment_id = identity('sticker'); values.push({type:'sticker',asset_id:value.asset_id,fragment_id:value.fragment_id,label:value.name}); }
    for (const value of readyAttachments()) values.push({type:['image','record','video'].includes(value.type)?value.type:'file',attachment_id:value.attachment_id,filename:value.filename||value.name||'附件',fragment_id:'file-'+value.attachment_id});
    const existing = new Set(values.map(value => value.fragment_id));
    model.order = model.order.filter(id => existing.has(id));
    for (const value of values) if (!model.order.includes(value.fragment_id)) model.order.push(value.fragment_id);
    return model.order.map((id,index)=>({...values.find(value=>value.fragment_id===id),order:index}));
  }
  function snapshot(text) {
    const structured = state.pendingActions.length || model.stickers.length || model.extras.length;
    if (structured && !model.loaded) throw new Error('组合表达服务尚未连接；已保留草稿，普通文字仍可发送。');
    return { parts: structured || model.loaded ? parts(text) : null,
      actions: state.pendingActions.map(value => ({...value})), stickers: model.stickers.map(value=>({...value})),
      extras: model.extras.map(value=>({...value})), order:[...model.order] };
  }
  function clear() { state.pendingActions=[];model.stickers=[];model.extras=[];model.order=[];persist();renderPreview(); }
  function recover(saved) {
    if (!state.pendingActions.length) state.pendingActions=saved.actions||[];
    if (!model.stickers.length) model.stickers=saved.stickers||[];
    if (!model.extras.length) model.extras=saved.extras||[];
    if (!model.order.length) model.order=saved.order||[];
    persist();renderPreview();
  }
  function hasContent() { return state.pendingActions.length>0 || model.stickers.length>0 || model.extras.length>0; }
  function removePart(value) {
    if(value.fragment_id==='current-draft') { node('draft').value='';saveDraft();resizeDraft(); }
    else if(value.type==='action') state.pendingActions=state.pendingActions.filter(v=>v.fragment_id!==value.fragment_id);
    else if(value.type==='sticker') model.stickers=model.stickers.filter(v=>v.fragment_id!==value.fragment_id);
    else if(['attachment','image','file','record','video'].includes(value.type)) state.attachmentQueues.set(state.activeId,attachmentQueue().filter(v=>v.attachment_id!==value.attachment_id));
    else model.extras=model.extras.filter(v=>v.fragment_id!==value.fragment_id);
    persist();renderPreview();renderChrome();renderAttachments();
  }
  function renderPreview() {
    const list=node('pending-actions');if(!list)return;
    list.replaceChildren();
    const values=parts(node('draft').value.trim());
    const expanded=hasContent() || values.some(v=>['attachment','image','file','record','video'].includes(v.type));
    list.hidden=!expanded;
    if(expanded) for(const [index,value] of values.entries()) {
      const row=document.createElement('div');row.className='composition-item';
      const names={text:'话语',action:'动作',sticker:'表情',attachment:'附件',image:'图片',file:'文件',record:'语音',video:'视频',reference:'引用'};
      const label=button((names[value.type]||'片段')+' · '+(value.label||value.text||value.filename||value.description||'消息').slice(0,70),()=>{
        if(value.type==='text') {
          const editor=node('compose-text-editor');model.editingText=value.fragment_id;editor.value=value.text;node('compose-text-dialog').showModal();
        } else if(value.type==='action') { const action=model.actions.find(v=>v.id===value.action_id);if(action)editAction(action); }
      },'composition-label');row.append(label);
      for(const [symbol,delta,title] of [['↑',-1,'向前移动'],['↓',1,'向后移动']]) {
        const control=button(symbol,()=>{const target=index+delta;if(target<0||target>=model.order.length)return;[model.order[index],model.order[target]]=[model.order[target],model.order[index]];persist();renderPreview();},'composition-control');
        control.disabled=index+delta<0||index+delta>=values.length;control.title=title;row.append(control);
      }
      const remove=button('×',()=>removePart(value),'composition-control');remove.title='移除片段';row.append(remove);list.append(row);
    }
    setText('compose-summary',expanded?'按上方顺序发送 · '+values.length+' 个片段':'');
    node('compose-summary').hidden=!expanded;syncComposerMetrics();
  }
  function addReference(value) {
    if(model.extras.filter(v=>v.type==='reference').length>=2) {showNotice('每条最多引用两条消息。');return;}
    model.extras.push({type:'reference',message_id:String(value.message_id),text:value.text||'消息附件',role:value.role,fragment_id:identity('quote')});
    persist();renderPreview();node('draft').focus();renderChrome();
  }
  function commitText() {
    const text=node('draft').value.trim();if(!text)return;
    model.extras.push({type:'text',text,fragment_id:identity('speech')});node('draft').value='';saveDraft();resizeDraft();persist();renderPreview();
  }
  let readingWork = null;
  function withReading(action) {
    const log = node('messages');
    const owner = scope(), reading = state.readingScope, render = state.messageRenderSerial;
    let work = readingWork;
    if (!work || work.log !== log || work.owner !== owner || work.reading !== reading || work.render !== render
        || (log && Math.abs(log.scrollTop - work.top) > 2)) {
      if (work && work.frame !== null) cancelAnimationFrame(work.frame);
      work = { log, owner, reading, render, position: log && captureMessagePosition(log),
        top: log ? log.scrollTop : 0, frame: null };
      readingWork = work;
    }
    action();
    // Several decoded images in one frame must share the original intent;
    // their own height changes are not the reader scrolling away from latest.
    if (work.frame !== null) return;
    work.frame = requestAnimationFrame(() => {
      if (readingWork !== work) return;
      readingWork = null;
      const position = work.position;
      if (!log || !position || owner !== scope() || reading !== state.readingScope || render !== state.messageRenderSerial) return;
      if (position.follow) setMessageScroll(log, log.scrollHeight);
      else {
        const row = [...log.querySelectorAll('.message-row')].find(value => value.dataset.messageKey === position.key);
        setMessageScroll(log, row ? log.scrollTop + row.getBoundingClientRect().top - log.getBoundingClientRect().top - position.offset : position.top);
      }
      updateJumpLatest();
    });
  }
  function panelHeight() {
    const drawer = node('composer-drawer'); if (!drawer || drawer.hidden) return;
    const height = model.nativeViewport && model.nativeViewport.height || window.visualViewport && window.visualViewport.height || innerHeight;
    const footer = document.querySelector('.composer-area');
    const fixed = footer.getBoundingClientRect().height - drawer.getBoundingClientRect().height;
    const header = document.querySelector('.chat-header').getBoundingClientRect().height;
    const budget = Math.min(280, height * .38, height - fixed - header - 70);
    const limit=Math.max(42,Math.round(budget))+'px';if(drawer.style.maxHeight!==limit)drawer.style.maxHeight=limit;
  }
  function setPanel(name = '') {
    withReading(() => {
      model.panel = model.panel === name && name ? '' : name;
      const drawer = node('composer-drawer'); drawer.hidden = !model.panel;
      for(const [id,pane] of [['sticker-button','expressions'],['touch-button','actions'],['attach-button','attachments']]){
        node(id).setAttribute('aria-expanded',String(model.panel===pane));
        node(id).classList.toggle('expanded',model.panel===pane);
      }
      for (const pane of document.querySelectorAll('[data-compose-pane]')) pane.hidden = pane.dataset.composePane !== model.panel;
      for (const tab of document.querySelectorAll('[data-compose-tab]')) tab.setAttribute('aria-selected', String(tab.dataset.composeTab === model.panel));
      if (model.panel) node('draft').blur();
      node('compose-add-text').hidden=!model.panel;panelHeight(); syncComposerMetrics();
    });
    if (name === 'expressions') { sync(); renderAssets(); }
    if (name === 'actions') { sync(); renderActions(); }
  }
  function closePanel() { if (!model.panel) return false; setPanel(''); return true; }
  function onViewport(value) {
    if (!value || value.source !== 'android' || !Number.isFinite(value.height) || value.height <= 0) return;
    if (model.nativeViewport && value.sequence < model.nativeViewport.sequence) return;
    if(model.nativeViewport&&value.height===model.nativeViewport.height&&value.width===model.nativeViewport.width&&value.imeVisible===model.nativeViewport.imeVisible){model.nativeViewport=value;return;}
    withReading(() => {
      model.nativeViewport = value;
      document.documentElement.style.setProperty('--app-height', Math.round(value.height) + 'px');
      document.documentElement.classList.toggle('ime-visible', !!value.imeVisible);
      resizeDraft();
    });
  }
  async function sync(force = false) {
    flushNotification(); updateWatchTarget();
    const current = scope();
    if (!current) { if (model.scope) { closeActive(); closeBatchActions(); model.serial++; model.scope = ''; model.assets = []; model.actions = []; model.loaded = false; restore(); } return; }
    if (model.scope !== current) {
      closeActive(); closeBatchActions(); model.selected = null; model.actionEditing = null;
      model.serial++; model.scope = current; model.loaded = false; model.loading = false;
      model.assets = []; model.actions = []; model.previews.clear(); model.error = ''; restore();
    }
    if (model.loading || !force && (model.loaded || model.error)) return;
    model.loading = true; const serial = ++model.serial;
    try {
      const [library, actions] = await Promise.all([call('GET', endpoint('expressions')),
        call('GET', endpoint('actions'))]);
      if (model.scope !== scope() || serial !== model.serial) return;
      model.assets = Array.isArray(library.items) ? library.items : [];
      model.actions = Array.isArray(actions.items) ? actions.items : [];
      model.touchCatalog=actions.native_touch||null;if(force)model.touchUnknown=false;
      model.loaded = true; model.error = '';
    } catch (error) {
      if (serial !== model.serial) return;
      model.error = error && error.status === 404 ? '服务器尚未启用共享表达接口，文字聊天可继续。' : errorText(error);
    } finally {
      if (serial === model.serial) { model.loading = false; renderAssets(); renderActions(); }
    }
  }
  function thumbnail(image, asset) {
    const id = assetId(asset), current = scope();
    if (!id || !current) return;
    let pending = model.previews.get(id);
    if (!pending) {
      pending = call('GET', endpoint('expression-preview', { asset_id: id })).then(value => {
        if (typeof value.data_url !== 'string' || !/^data:image\/(png|jpeg|gif|webp);base64,/.test(value.data_url)) throw new Error('表情图片暂不可用');
        return value.data_url;
      }); model.previews.set(id, pending);
      pending.catch(() => { if (model.previews.get(id) === pending) model.previews.delete(id); });
    }
    pending.then(url => { if (current === scope() && image.isConnected) { image.src = url; image.classList.add('loaded'); } })
      .catch(() => { if (current === scope() && image.isConnected) image.alt = asset.name || '图片暂不可用'; });
  }
  function filteredAssets() {
    const query = model.query.trim().toLowerCase();
    let values = model.filter === 'hidden' ? model.assets.filter(value => actorPref(value, 'user').hidden)
      : model.filter === 'disabled' ? model.assets.filter(value => value.enabled === false)
      : model.assets.filter(value => value.enabled !== false && !actorPref(value, 'user').hidden);
    if (model.filter === 'favorites') values = values.filter(value => actorPref(value, 'user').favorite);
    if (model.filter === 'recent') values = values.filter(value => actorPref(value, 'user').last_used)
      .sort((a, b) => String(actorPref(b, 'user').last_used).localeCompare(String(actorPref(a, 'user').last_used)));
    if (model.filter === 'frequent') values = values.filter(value => actorPref(value, 'user').use_count > 0)
      .sort((a, b) => actorPref(b, 'user').use_count - actorPref(a, 'user').use_count);
    if (model.filter === 'disliked') values = values.filter(value => actorPref(value, 'user').disliked);
    return query ? values.filter(value => [value.name, value.meaning, ...(value.tags || []), ...(Array.isArray(value.scenarios) ? value.scenarios : [value.scenarios])]
      .filter(Boolean).join(' ').toLowerCase().includes(query)) : values;
  }
  function renderAssets() {
    const grid = node('shared-expression-grid'); if (!grid) return;
    grid.replaceChildren();
    setText('expression-status', !scope() ? '先打开一个对话，再使用服务器共享素材。'
      : model.loading ? '正在读取共享素材…' : model.error || '与伙伴使用同一份素材与人工语义标注');
    for (const asset of filteredAssets()) {
      const card = document.createElement('div'); card.className = 'shared-expression';
      const pick = button('', () => model.pickMode === 'send' || actorPref(asset, 'user').quick_send
        ? sendNow([{ type: 'sticker', asset_id: assetId(asset) }]) : attachAsset(asset), 'expression-pick');
      pick.disabled = asset.enabled === false || actorPref(asset, 'user').hidden === true;
      pick.title = [asset.name, asset.meaning, (asset.tags || []).join('、')].filter(Boolean).join(' · ');
      const image = document.createElement('img'); image.alt = asset.name || '表情'; image.width = 84; image.height = 84; pick.append(image);
      const label = document.createElement('span'); label.textContent = asset.name || '表情'; pick.append(label);
      const controls = document.createElement('div'); controls.className = 'expression-controls';
      const star = button(actorPref(asset, 'user').favorite ? '★' : '☆', () => savePreference(assetId(asset), 'user', { favorite: !actorPref(asset, 'user').favorite }), 'expression-star');
      star.setAttribute('aria-label', '收藏 ' + (asset.name || '表情'));
      const detail = button('偏好', () => openPreference(asset), 'text-button'); controls.append(star, detail);
      card.append(pick, controls); grid.append(card); thumbnail(image, asset);
    }
    if (!grid.children.length && model.loaded) {
      const empty = document.createElement('p'); empty.className = 'compose-empty';
      empty.textContent = model.query ? '没有匹配的名称、标签或含义。' : '这里还没有符合条件的已启用素材。'; grid.append(empty);
    }
  }
  function attachAsset(asset) {
    if (interactionBusy()) return;
    if (model.stickers.length >= 4) { showNotice('一条消息最多附加 4 张表情。'); return; }
    model.stickers.push({ asset_id: assetId(asset), name: asset.name || '表情' });
    persist(); renderPreview(); renderChrome();
  }
  function attachAction(value) {
    if (value.enabled === false) {showNotice('这个动作已停用，可在编辑中重新启用。');return;}
    if (interactionBusy()) {showNotice('当前消息或文件仍在处理，请完成后再添加互动。');return;}
    if (state.pendingActions.length >= 4) { showNotice('一条消息最多附加 4 个动作。'); return; }
    state.pendingActions.push({ id: value.id, label: value.label, description: value.description });
    persist(); renderPreview(); renderChrome();
  }
  async function sendNow(parts) {
    if (!model.loaded) {showNotice(model.error||'动作库尚未连接，请刷新后再互动。',null,true);return;}
    if (interactionBusy()) {showNotice('上一轮消息或文件仍在处理，互动尚未发出。');return;}
    await sendMessage({ preventDefault() {} }, { kind: 'composition', parts, text: '', files: [],
      scope: { server: state.server, username: state.username, sessionId: state.activeId }, consume: false });
  }
  function renderActions() {
    const list = node('shared-action-list'); if (!list) return;
    list.replaceChildren();
    renderTouchBuilder();
    setText('action-status', model.loading ? '正在读取动作…' : model.error || '动作是明确的用户互动输入，不是已经发生的现实行为。');
    const values = [...model.actions].sort((a, b) => (b.quick === true) - (a.quick === true) || (a.order || 0) - (b.order || 0));
    const others = document.createElement('details'); others.className = 'other-actions';
    const summary = document.createElement('summary'); summary.textContent = '其他动作与停用项'; others.append(summary);
    for (const value of values) {
      const row = document.createElement('div'); row.className = 'compose-action-row';
      const attach = button(value.label, () => attachAction(value), 'action-attach'); attach.disabled = value.enabled === false;
      const description = document.createElement('span'); description.className = 'action-description'; description.textContent = value.description;
      const body = document.createElement('div'); body.append(attach, description);
      const actions = document.createElement('div'); actions.className = 'action-row-controls';
      const immediate = button('直接发', () => sendNow([actionPart(value)]), 'text-button'); immediate.disabled = value.enabled === false;
      actions.append(immediate, button('编辑', () => editAction(value), 'text-button')); row.append(body, actions);
      if (value.quick === false || value.enabled === false) others.append(row); else list.append(row);
    }
    if (others.children.length > 1) list.append(others);
    if (!values.length && model.loaded) setText('action-status', '还没有动作，可以创建或导入本机原有互动。');
  }
  function touchPartLabel(part){
    const labels=[part.label,...(part.aliases||[])];
    return labels.some(value=>['腹部','肚子','肚皮'].includes(value))?'肚皮':part.label;
  }
  function renderTouchBuilder(){
    const box=node('native-touch-picker');if(!box)return;box.replaceChildren();
    const catalog=model.touchCatalog;
    if(!catalog||!catalog.available){box.append(Object.assign(document.createElement('p'),{className:'compose-status',textContent:catalog&&catalog.reason||'正在连接TLS原生动作与部位…'}));return;}
    const heading=document.createElement('div');heading.className='touch-path';
    heading.append(button(model.touchVerb||'① 选择动作',()=>{model.touchVerb='';model.touchPart='';renderTouchBuilder();},'touch-breadcrumb'));
    heading.append(Object.assign(document.createElement('span'),{textContent:'›'}),Object.assign(document.createElement('strong'),{textContent:model.touchPart?touchPartLabel(catalog.parts.find(p=>p.id===model.touchPart)||{})||'部位':model.touchVerb?'② 选择部位':'再选部位'}));box.append(heading);
    const choices=document.createElement('div');choices.className='touch-choices';
    if(!model.touchVerb){
      const preferred=['戳','摸','轻拍','牵','抱','捏'];
      const sorted=[...catalog.verbs].sort((a,b)=>{const rank=w=>preferred.includes(w)?preferred.indexOf(w):100;return rank(a.word)-rank(b.word);});
      for(const value of sorted)choices.append(button(value.word,()=>{model.touchVerb=value.word;model.touchPart='';renderTouchBuilder();},'touch-choice'));
    }else{
      for(const part of catalog.parts){const choice=button(touchPartLabel(part),()=>{model.touchPart=part.id;renderTouchBuilder();},'touch-choice');choice.classList.toggle('selected',part.id===model.touchPart);choices.append(choice);}
    }
    box.append(choices);
    if(model.touchVerb&&model.touchPart){const controls=document.createElement('div');controls.className='touch-confirm';controls.append(button('加入当前消息',()=>useTouch(false),'secondary-button'),button('直接互动',()=>useTouch(true),'primary-button'));box.append(controls);}
  }
  async function useTouch(direct){
    if(model.busy||!model.loaded||!model.touchVerb||!model.touchPart)return;
    if(model.touchUnknown){showNotice('上次保存结果待核对，请先点面板右上角刷新。');return;}
    const catalog=model.touchCatalog,selected={character:catalog.character,verb:model.touchVerb,part:model.touchPart},owner=scope();
    const target=catalog.parts.find(p=>p.id===selected.part);if(!target)return;
    model.busy=true;
    try{
      let action=model.actions.find(value=>value.enabled!==false&&value.native_touch&&['character','verb','part'].every(key=>value.native_touch[key]===selected[key]));
      if(!action){
        const label=selected.verb+'·'+touchPartLabel(target);
        const record={id:identity('touch'),label,description:'用户发起角色触觉互动：'+selected.verb+target.label+'。',native_touch:selected,enabled:true,quick:true,order:model.actions.length};
        const result=await call('POST','/chat/actions',{session_id:state.activeId,op:'create',record,request_id:record.id});
        if(owner!==scope())return;model.actions=result.items||[];action=model.actions.find(v=>v.id===record.id);
      }
      if(!action)throw Error('服务器没有回读这个互动组合。');
      model.busy=false;
      if(direct)await sendNow([actionPart(action)]);else{attachAction(action);showNotice('互动已加入待发送，确认发送时由TLS触觉系统处理。');}
    }catch(error){model.touchUnknown=true;showNotice(errorText(error)+' 请刷新核对动作库，不会自动重复保存。',null,true);}
    finally{model.busy=false;}
  }
  const batchCurrent=batch=>!!batch&&batch===model.batch&&batch.owner===scope()
    &&batch.sessionId===state.activeId&&batch.epoch===model.batchSerial&&node('action-batch-dialog')?.open;
  function closeBatchActions(){
    model.batchSerial++;model.batch=null;
    const dialog=node('action-batch-dialog');if(dialog?.open)dialog.close();
    if(node('action-batch-source'))node('action-batch-source').value='';
    if(node('action-batch-preview'))node('action-batch-preview').textContent='';
    if(node('action-batch-save'))node('action-batch-save').disabled=true;
  }
  function openBatchActions(){
    if(!model.loaded||model.busy||!scope()){showNotice('请先连接当前角色动作库，并等待正在处理的操作。');return;}
    model.batch={owner:scope(),sessionId:state.activeId,epoch:++model.batchSerial,items:null};
    node('action-batch-source').value=JSON.stringify({items:model.actions},null,2);node('action-batch-preview').textContent='修改或粘贴动作组合。每批最多64项；相同ID会更新，其他动作保留。';node('action-batch-save').disabled=true;node('action-batch-dialog').showModal();
  }
  function previewBatchActions(){
    const batch=model.batch;if(!batchCurrent(batch)||model.busy)return;
    try{const parsed=JSON.parse(node('action-batch-source').value);const items=Array.isArray(parsed)?parsed:parsed.items;
      if(!Array.isArray(items)||!items.length||items.length>64)throw Error('每批需要1至64项。');
      const ids=new Set();for(const item of items){if(!item||typeof item.id!=='string'||!item.label||!item.description||ids.has(item.id))throw Error('请填写唯一ID、名称和动作说明。');ids.add(item.id);}
      model.batch={...batch,items};const existing=new Set(model.actions.map(v=>v.id));node('action-batch-preview').textContent=items.map(v=>(existing.has(v.id)?'更新':'新增')+' · '+v.label+(v.native_touch?' · TLS原生触觉':' · 角色语义动作')).join('\n');node('action-batch-save').disabled=false;
    }catch(error){model.batch={...batch,items:null};node('action-batch-save').disabled=true;node('action-batch-preview').textContent='未能预览：'+error.message;}
  }
  async function saveBatchActions(){
    const batch=model.batch;if(!batchCurrent(batch)||!batch.items||model.busy)return;
    const body={session_id:batch.sessionId,op:'import',record:{items:JSON.parse(JSON.stringify(batch.items))}},owner=batch.owner;
    model.busy=true;node('action-batch-save').disabled=true;
    try{await call('POST','/chat/actions',body);if(!batchCurrent(batch))return;closeBatchActions();await sync(true);if(owner===scope())showNotice('动作组合已批量保存并回读。');}
    catch(error){if(batchCurrent(batch)){node('action-batch-preview').textContent=errorText(error)+' 请关闭后刷新动作库核对；不会自动重复写入。';model.batch={...batch,items:null};}}
    finally{model.busy=false;}
  }
  async function savePreference(id, actor, changes) {
    if (model.busy) return;
    const current = scope(); model.busy = true;
    try {
      await call('POST', '/chat/expression-preference', { session_id: state.activeId, asset_id: id, actor, changes });
      if (current === scope()) { await sync(true); showNotice(actor === 'user' ? '你的表情偏好已保存。' : '伙伴的表情偏好已保存。'); }
      return true;
    } catch (error) { showNotice(errorText(error) + ' 请刷新偏好核对结果，不会自动重复提交。', null, true); return false; }
    finally { model.busy = false; }
  }
  function openPreference(asset) {
    model.selected = asset; setText('expression-pref-title', asset.name || '表情偏好');
    node('expression-pref-actor').value = 'user';
    node('expression-user-fields').hidden = false; node('expression-texas-fields').hidden = true; node('expression-metadata-fields').hidden = true;
    setText('expression-pref-meaning', [asset.meaning, (asset.tags || []).join('、'),
      Array.isArray(asset.scenarios) ? asset.scenarios.join('、') : asset.scenarios].filter(Boolean).join('\n'));
    const user = actorPref(asset, 'user'), texas = actorPref(asset, 'texas');
    for (const key of ['favorite', 'liked', 'disliked', 'hidden', 'quick_send']) node('expression-user-' + key).checked = !!user[key];
    node('expression-texas-weight').value = Number.isFinite(texas.weight) ? texas.weight : 1;
    node('expression-texas-cooldown').value = Number.isFinite(texas.cooldown_seconds) ? texas.cooldown_seconds : 120;
    node('expression-texas-contexts').value = Array.isArray(texas.contexts) ? texas.contexts.join('、') : texas.contexts || '';
    node('expression-meta-name').value = asset.name || '';
    node('expression-meta-meaning').value = asset.meaning || '';
    node('expression-meta-tags').value = (asset.tags || []).join('、');
    node('expression-meta-scenarios').value = Array.isArray(asset.scenarios) ? asset.scenarios.join('、') : asset.scenarios || '';
    node('expression-user-order').value = actorPref(asset,'user').quick_order || 0;
    node('expression-meta-pairing').value = asset.pairing || '';
    node('expression-meta-enabled').checked = asset.enabled !== false;
    setText('expression-pref-status', '用户与角色分别保存；收藏只参与加权，不覆盖角色倾向。');
    node('expression-pref-dialog').showModal();
  }
  async function submitPreference(event) {
    event.preventDefault(); if (!model.selected || model.busy) return;
    const actor = node('expression-pref-actor').value;
    if (actor === 'metadata') {
      const list = id => node(id).value.split(/[、,，\n]/).map(value => value.trim()).filter(Boolean);
      model.busy = true;
      try {
        await call('POST', '/chat/expression-metadata', { session_id: state.activeId, asset_id: assetId(model.selected),
          changes: { name: node('expression-meta-name').value.trim(), meaning: node('expression-meta-meaning').value.trim(),
            tags: list('expression-meta-tags'), scenarios: list('expression-meta-scenarios'), pairing: node('expression-meta-pairing').value.trim(), enabled: node('expression-meta-enabled').checked } });
        await sync(true); node('expression-pref-dialog').close(); showNotice('共享素材说明已保存，后续选图使用新标注。');
      } catch (error) { setText('expression-pref-status', errorText(error) + ' 请刷新核对结果，不会自动重复提交。'); }
      finally { model.busy = false; }
      return;
    }
    const changes = actor === 'user' ? Object.fromEntries(['favorite', 'liked', 'disliked', 'hidden', 'quick_send'].map(key => [key, node('expression-user-' + key).checked]))
      : { weight: Number(node('expression-texas-weight').value), cooldown_seconds: Number(node('expression-texas-cooldown').value),
        contexts: node('expression-texas-contexts').value.split(/[、,，\n]/).map(value => value.trim()).filter(Boolean) };
    if(actor==='user')changes.quick_order=Number(node('expression-user-order').value);
    if (await savePreference(assetId(model.selected), actor, changes)) node('expression-pref-dialog').close();
  }
  function editAction(value = null) {
    if (!model.loaded) { showNotice('先连接服务器动作库。'); return; }
    model.actionEditing = value ? { ...value } : null;
    model.actionRequestId = 'action-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
    setText('compose-action-title', value ? '编辑动作' : '新建动作');
    node('compose-action-label').value = value && value.label || '';
    node('compose-action-description').value = value && value.description || '';
    node('compose-action-quick').checked = !value || value.quick !== false;
    node('compose-action-enabled').checked = !value || value.enabled !== false;
    node('compose-action-order').value = value && value.order || 0;
    node('compose-action-delete').hidden = !value;
      const catalog=model.touchCatalog,verb=node('compose-action-native-verb'),part=node('compose-action-native-part');
      verb.replaceChildren();part.replaceChildren();
      const option=(select,value,label)=>{const node=document.createElement('option');node.value=value;node.textContent=label;select.append(node);};
      option(verb,'','按动作说明识别');option(part,'','选择部位');
      for(const item of catalog&&catalog.verbs||[])option(verb,item.word,item.word);
      for(const item of catalog&&catalog.parts||[])option(part,item.id,touchPartLabel(item));
      verb.disabled=part.disabled=!(catalog&&catalog.available);
      verb.value=value&&value.native_touch&&value.native_touch.verb||'';part.value=value&&value.native_touch&&value.native_touch.part||'';
    setText('compose-action-error', ''); node('compose-action-dialog').showModal();
  }
  async function saveAction(event) {
    event.preventDefault(); if (model.busy) return;
    const label = node('compose-action-label').value.trim(), description = node('compose-action-description').value.trim();
    if (!label || !description) { setText('compose-action-error', '请填写名称和动作语义。'); return; }
    if ([...label].length>32 || [...description].length>500) { setText('compose-action-error', '动作名称最多32字，动作语义最多500字。'); return; }
    const record = { ...(model.actionEditing ? { id: model.actionEditing.id } : {}), label, description,
      quick: node('compose-action-quick').checked, enabled: node('compose-action-enabled').checked,
      order: Number(node('compose-action-order').value) || 0 };
      if(model.touchCatalog&&model.touchCatalog.available){
        const verb=node('compose-action-native-verb').value,part=node('compose-action-native-part').value;
        if(verb&&!part){setText('compose-action-error','选择了原生动作后，还需要选择部位。');return;}
        record.native_touch=verb?{character:model.touchCatalog.character,verb,part}:null;
      }
    model.busy = true;
    try {
      await call('POST', '/chat/actions', { session_id: state.activeId, op: model.actionEditing ? 'update' : 'create', record, request_id: model.actionRequestId });
      node('compose-action-dialog').close(); await sync(true); showNotice('动作已保存到服务器。');
    } catch (error) { setText('compose-action-error', errorText(error) + ' 请先刷新动作库核对，不会自动重建。'); }
    finally { model.busy = false; }
  }
  async function deleteAction() {
    if (!model.actionEditing || model.busy) return;
    model.busy = true;
    try {
      await call('POST', '/chat/actions', { session_id: state.activeId, op: 'delete', record: { id: model.actionEditing.id } });
      node('compose-action-dialog').close(); await sync(true); showNotice('动作已移除，已发送的历史记录保留。');
    } catch (error) { setText('compose-action-error', errorText(error) + ' 请先刷新核对。'); }
    finally { model.busy = false; }
  }
  async function importLocalActions() {
    if (!model.loaded || model.busy) return;
    const local = currentInteractions(); model.busy = true;
    try {
      for (const [index, value] of local.slots.entries()) {
        if (model.actions.some(action => action.label === value.label && action.description === value.action)) continue;
        await call('POST', '/chat/actions', { session_id: state.activeId, op: 'create', record: { label: value.label,
          description: value.action, enabled: value.enabled, quick: true, order: index } });
      }
      await sync(true); showNotice('本机互动已复制到当前角色动作库，原记录保留。');
    } catch (error) { await sync(true); showNotice(errorText(error) + ' 已保存的项保留，请先核对，不会自动重复导入。', null, true); }
    finally { model.busy = false; }
  }
  function normalizeParts(values) {
    return Array.isArray(values) ? values.flatMap(part => {
      if (!part || typeof part !== 'object') return [];
      if (['text', 'speech', 'plain'].includes(part.type) && typeof part.text === 'string') return [{ type: 'plain', text: part.text }];
      if (part.type === 'reference') return [{...part,type:'reference'}];
      if (part.type === 'attachment') return [mediaPart({...part,type:part.media_type||'file',source:'upload'})];
      if (part.type === 'action') return [{ type: 'action', action_id: part.action_id, label: part.label || '互动', description: part.description || '', source: part.source || 'user_action' }];
      if (part.type === 'sticker' && typeof part.asset_id === 'string') return [{ type: 'sticker', asset_id: part.asset_id, name: part.name || part.label || '表情' }];
      if (['image', 'file', 'record', 'video'].includes(part.type)) return [mediaPart({ ...part, source: part.source || 'history' })];
      return [];
    }) : [];
  }
  function renderPart(part) {
    if(part.type==='reference') {const quote=document.createElement('blockquote');quote.className='typed-reference';quote.textContent=(part.role==='assistant'?'伙伴':'你')+' · '+(part.text||'引用的附件消息');return quote;}
    if (part.type === 'action') {
      const action = document.createElement('span'); action.className = 'typed-action';
      action.textContent = part.source === 'user_action' ? '你 · ' + part.label : part.label;
      action.title = part.description; return action;
    }
    const card = document.createElement('div'); card.className = 'typed-sticker';
    const image = document.createElement('img'); image.width = 128; image.height = 128;
    image.alt = part.name || '表情'; card.append(image); thumbnail(image, { id: part.asset_id, name: part.name }); return card;
  }
  function closeActive() {
    if(node('action-batch-dialog')?.open){closeBatchActions();return true;}
    for (const id of ['compose-action-dialog', 'expression-pref-dialog']) if (node(id).open) { node(id).close(); return true; }
    return closePanel();
  }
  const watchScope = () => state.authenticated && state.activeId && (!primaryConnectionId() || state.activeId===primaryConnectionId()) ? JSON.stringify([state.server, state.username, state.activeId]) : '';
  function lastAssistantId() {
    const row = [...state.messages].reverse().find(value => value.role === 'assistant' && value.delivery === 'confirmed' && value.serverId != null);
    return row ? String(row.serverId) : '';
  }
  function watchChanged(value) {
    if (!value || typeof value !== 'object') return;
    model.watch = value;
    const active = value.running === true || ['starting', 'running', 'reconnecting'].includes(value.state);
    if (!model.pendingWatch && node('notify-toggle')) node('notify-toggle').checked = active;
    storage.set(pref('notify'), active ? '1' : '');
    const labels = { starting: '后台服务正在连接当前会话。', running: value.verified_session ? '正在原生后台检查当前会话的新回复。' : '服务已启动，正在核对会话归属。',
      reconnecting: '网络暂不可用，后台服务正在退避重连。', stopped: '后台检查已停止；不会自动重新启动。' };
    setText('reply-watch-status', value.reason === 'foreground_ui_owns_reads' ? '前台由聊天页同步新消息；后台提醒保持开启。' : labels[value.state] || '后台服务状态：' + (value.state || '未知'));
  }
  function startWatch() {
    if (!model.pendingWatch || model.pendingWatch !== watchScope() || !node('notify-toggle').checked) { model.pendingWatch = ''; return; }
    model.pendingWatch = ''; model.watchTarget = watchScope();
    try {
      const value = parse(native().setReplyWatch(true, state.activeId, conversationTitle(), lastAssistantId()));
      watchChanged(value);
      if (!value || value.ok === false) { node('notify-toggle').checked = false; showNotice('后台回复检查未能启动，请在设置中查看状态。', null, true); }
    } catch (error) { node('notify-toggle').checked = false; showNotice(errorText(error), null, true); }
  }
  function permissionChanged(granted) {
    if (!model.pendingWatch) return;
    if (granted === true) startWatch();
    else { model.pendingWatch = ''; node('notify-toggle').checked = false; setText('reply-watch-status', '未获得通知权限，后台服务没有开启。'); }
  }
  function toggleWatch(enabled) {
    const bridge = native();
    if (typeof bridge.setReplyWatch !== 'function') { showNotice('当前版本没有原生后台回复服务，请安装新安装包。', null, true); node('notify-toggle').checked = false; return; }
    if (!enabled) { model.pendingWatch = ''; model.watchTarget = ''; watchChanged(parse(bridge.setReplyWatch(false, '', '', ''))); return; }
    if (!watchScope()) { node('notify-toggle').checked = false; showNotice('先登录并打开要接收提醒的对话。'); return; }
    model.pendingWatch = watchScope();
    const answer = parse(bridge.requestNotificationPermission());
    if (answer && answer.granted === true) startWatch();
    else setText('reply-watch-status', '请在系统窗口允许通知；只为本次明确开启操作接续启动。');
  }
  function updateWatchTarget() {
    if (!model.watch || !(model.watch.running === true || ['starting', 'running', 'reconnecting'].includes(model.watch.state))) return;
    const target = watchScope(); if (!target || target === model.watchTarget || state.loading || state.sending) return;
    model.watchTarget = target;
    try { watchChanged(parse(native().setReplyWatch(true, state.activeId, conversationTitle(), lastAssistantId()))); } catch (_) {}
  }
  function historyReceived(sessionId) {
    if (!recoveryForeground() || sessionId !== state.activeId || !model.watch || model.watch.running !== true
        || model.watch.session_id !== sessionId || !watchScope()) return;
    const seen = lastAssistantId();
    if (typeof native().ackReplyWatch !== 'function' || !seen || model.lastWatchAck === watchScope() + '|' + seen) return;
    try {
      // The acknowledgement bridge never starts a stopped watch or polls HTTP.
      const answer = parse(native().ackReplyWatch(sessionId, seen));
      if (answer && answer.ok === true) model.lastWatchAck = watchScope() + '|' + seen;
    } catch (_) { /* Next genuine history read may acknowledge it again. */ }
  }
  function openConversation(id) {
    if (typeof id !== 'string' || !id || id.length > 256 || /[\u0000-\u001f]/.test(id)) return;
    model.notificationId = id; flushNotification();
  }
  function flushNotification() {
    if (!model.notificationId || !state.authenticated || state.loading || state.sending || state.attaching || state.creating) return;
    const id = model.notificationId; model.notificationId = null;
    selectSession(id,{focusLatest:true}); // Ownership stays on the original history path.
  }
  function init() {
    node('attach-button').setAttribute('aria-label', '打开附件工具');
    node('attach-button').setAttribute('aria-controls', 'composer-drawer');
    for (const tab of document.querySelectorAll('[data-compose-tab]')) tab.addEventListener('click', () => setPanel(tab.dataset.composeTab));
    node('compose-close').addEventListener('click', closePanel);
    node('shared-expression-search').addEventListener('input', event => { model.query = event.target.value; renderAssets(); });
    for (const filter of document.querySelectorAll('[data-expression-filter]')) filter.addEventListener('click', () => {
      model.filter = filter.dataset.expressionFilter;
      for (const value of document.querySelectorAll('[data-expression-filter]')) value.classList.toggle('selected', value === filter);
      renderAssets();
    });
    node('expression-pick-mode').addEventListener('change', event => { model.pickMode = event.target.value; });
    node('compose-refresh').addEventListener('click', () => sync(true));
    node('compose-add-action').addEventListener('click', () => editAction());
    node('compose-import-actions').addEventListener('click', importLocalActions);
    const picker=document.createElement('section');picker.id='native-touch-picker';picker.className='native-touch-picker';document.querySelector('[data-compose-pane="actions"]').prepend(picker);
    document.querySelector('.compose-action-toolbar').append(button('批量组合',openBatchActions,'text-button'));
    const batch=document.createElement('dialog');batch.id='action-batch-dialog';batch.className='settings-dialog';batch.innerHTML='<div class="settings-form"><div class="dialog-heading"><h2>批量维护动作组合</h2><button id="action-batch-close" type="button" class="icon-button" aria-label="关闭批量维护">×</button></div><p class="appearance-help">给外部编辑器的批量入口。JSON只描述动作，不执行代码；原生触觉可填native_touch：character、verb、part，必须来自当前TLS词表和部位。</p><textarea id="action-batch-source" rows="12" spellcheck="false" aria-label="动作组合JSON"></textarea><pre id="action-batch-preview" class="action-batch-preview"></pre><div class="appearance-actions"><button id="action-batch-preview-button" type="button" class="secondary-button">检查并预览</button><button id="action-batch-save" type="button" class="primary-button" disabled>确认批量写入</button></div></div>';document.body.append(batch);
    node('action-batch-close').onclick=closeBatchActions;node('action-batch-preview-button').onclick=previewBatchActions;node('action-batch-save').onclick=saveBatchActions;
    batch.addEventListener('close',()=>{if(model.batch)closeBatchActions();});
    node('action-batch-source').oninput=()=>{if(batchCurrent(model.batch))model.batch={...model.batch,epoch:++model.batchSerial,items:null};node('action-batch-save').disabled=true;};
    node('compose-choose-file').addEventListener('click', chooseAttachment);
    node('compose-action-form').addEventListener('submit', saveAction);
    const binding=document.createElement('details');binding.className='other-actions';binding.innerHTML='<summary>关联原生触觉（可选）</summary><p class="compose-status">可以固定动作和部位；未绑定时按动作说明识别，无法识别的动作由角色剧情回应。</p><label>动作<select id="compose-action-native-verb"></select></label><label>部位<select id="compose-action-native-part"></select></label>';node('compose-action-error').before(binding);
    node('compose-action-delete').addEventListener('click', deleteAction);
    node('compose-action-cancel').addEventListener('click', () => node('compose-action-dialog').close());
    node('expression-pref-form').addEventListener('submit', submitPreference);
    node('expression-pref-cancel').addEventListener('click', () => node('expression-pref-dialog').close());
    node('expression-pref-actor').addEventListener('change', () => {
      node('expression-user-fields').hidden = node('expression-pref-actor').value !== 'user';
      node('expression-texas-fields').hidden = node('expression-pref-actor').value !== 'texas';
      node('expression-metadata-fields').hidden = node('expression-pref-actor').value !== 'metadata';
    });
    node('draft').addEventListener('focus', closePanel);
    node('draft').addEventListener('input',()=>{parts(node('draft').value.trim());persist();renderPreview();});
    node('compose-add-text').addEventListener('click',commitText);
    node('compose-text-form').addEventListener('submit',event=>{event.preventDefault();const text=node('compose-text-editor').value;if(model.editingText==='current-draft'){node('draft').value=text;saveDraft();resizeDraft();}else{const item=model.extras.find(v=>v.fragment_id===model.editingText);if(item)item.text=text;}persist();renderPreview();node('compose-text-dialog').close();});
    node('compose-text-cancel').addEventListener('click',()=>node('compose-text-dialog').close());
    try { if (window.AsteriaChat && window.AsteriaChat.getViewportMetrics) onViewport(JSON.parse(window.AsteriaChat.getViewportMetrics())); } catch (_) {}
    try { if (window.AsteriaChat && window.AsteriaChat.getReplyWatchStatus) watchChanged(parse(window.AsteriaChat.getReplyWatchStatus())); } catch (_) {}
    restore(); sync();
  }
  return { init, sync, snapshot, clear, recover, restore, persist, hasContent, renderPreview,
    toggle: () => setPanel(model.panel ? '' : 'expressions'), setPanel, closeActive, closePanel,
    viewportChanged: onViewport, viewport: () => model.nativeViewport, withReading, panelHeight,
    normalizeParts, renderPart, addReference, commitText, showActions: () => setPanel('actions'),
    toggleWatch, watchChanged, permissionChanged, historyReceived, openConversation };
})();
