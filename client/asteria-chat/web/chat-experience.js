'use strict';

/* Conversation UX over the existing authenticated bridge, not a second chat
   store or a second generation path. Unsent drafts remain on this device. */
window.ChatExperience = (() => {
  let panelScope = '', panelEpoch = 0, expressionSnapshot = null, contextSnapshot = null;
  const live = new Map();
  const memoryDrafts=new Map(),memoryPending=new Map();
  let memoryEditor=null,memoryEpoch=0,memoryReadSerial=0;
  let bookmarkScope='',bookmarkRows=[],readRestorePending='',readFrame=0;
  const readBoundaries=new Map();
  const key = () => JSON.stringify([state.server,state.username,state.activeId]);
  const route = name => '/chat/'+name+'?session_id='+encodeURIComponent(state.activeId||'');
  const call = (method,name,body) => apiClient.json(method,name,body);
  const text = (tag,value,className='') => {const node=document.createElement(tag);node.textContent=value;node.className=className;return node;};
  const button = (label,fn,className='text-button') => {const node=text('button',label,className);node.type='button';node.addEventListener('click',fn);return node;};
  const notice = error => showNotice(errorText(error)+' 修改结果未知时请先重新读取，不会自动重复提交。',null,true);
  const currentState = () => (state.sessions.find(item=>item.session_id===state.activeId)||{}).tls_state||{};
  function scopeReady() {if(!state.authenticated){openSettings();return false;}if(!state.activeId){showNotice('请先打开一个会话。');return false;}return true;}
  function status(value,error=false) {const node=$('experience-status');node.textContent=value;node.classList.toggle('error',error);}
  function selectOptions(node,options) {node.replaceChildren();for(const [value,label] of options){const option=text('option',label);option.value=value;node.append(option);}}
  function field(label,control) {const node=document.createElement('label');node.className='experience-field';node.append(text('span',label),control);return node;}
  function control(id,type='input') {const node=document.createElement(type);node.id=id;return node;}
  function section(name) {
    for(const node of document.querySelectorAll('[data-experience-pane]'))node.hidden=node.dataset.experiencePane!==name;
    for(const node of document.querySelectorAll('[data-experience-tab]'))node.classList.toggle('selected',node.dataset.experienceTab===name);
    status('');
  }
  const panelTicket=()=>({owner:panelScope,epoch:panelEpoch});
  const panelCurrent=ticket=>state.authenticated&&ticket.owner&&ticket.owner===key()
    &&ticket.owner===panelScope&&ticket.epoch===panelEpoch&&$('experience-dialog')?.open;
  function closeBookmarkReading(){
    const dialog=$('bookmark-reading-dialog');if(dialog?.open)dialog.close();
    for(const id of ['bookmark-reading-title','bookmark-reading-text','bookmark-reading-note'])if($(id))$(id).textContent='';
  }
  function close(){
    closeMemory();
    panelEpoch++;panelScope='';expressionSnapshot=null;contextSnapshot=null;
    const dialog=$('experience-dialog');if(dialog?.open)dialog.close();closeBookmarkReading();
    for(const id of ['experience-persona','experience-memory-note','experience-inheritance','experience-status'])if($(id))$(id).textContent='';
    for(const id of ['experience-memories','experience-narrative','experience-search-results','experience-bookmark-list'])if($(id))$(id).replaceChildren();
    for(const id of ['experience-scene','experience-search-input','experience-frequency','experience-cooldown','experience-fragments'])if($(id))$(id).value='';
    if($('experience-mode'))$('experience-mode').value='chat';
    if($('experience-setting-level'))$('experience-setting-level').value='session';
    if($('experience-per-unit'))$('experience-per-unit').checked=false;
    for(const mode of ['chat','roleplay','technical'])if($('experience-policy-'+mode))$('experience-policy-'+mode).value='';
    for(const id of ['experience-save-scene','experience-save-expression','experience-reset-expression'])if($(id))$(id).disabled=true;
  }
  function scopeChanged(){
    const valid=state.authenticated&&state.activeId;
    if(panelScope&&(!valid||panelScope!==key()))close();
    if(bookmarkScope&&(!valid||bookmarkScope!==key())){bookmarkScope='';bookmarkRows=[];closeBookmarkReading();}
  }
  async function open(name='context') {
    if(!scopeReady())return;
    hideMoreMenu();if(panelScope&&panelScope!==key())close();panelScope=key();panelEpoch++;section(name);
    if(!$('experience-dialog').open)$('experience-dialog').showModal();
    if(name==='context')await readContext();
    if(name==='expression')await readExpression();
    if(name==='bookmarks')await readBookmarks();
  }
  async function readContext() {
    const ticket=panelTicket();if(!panelCurrent(ticket))return;
    contextSnapshot=null;$('experience-save-scene').disabled=true;status('正在读取当前角色与会话…');
    try{
      const data=await call('GET',route('context'));
      if(!panelCurrent(ticket))return;
      contextSnapshot=data;
      $('experience-persona').textContent=data.persona&&data.persona.display_name||'角色配置暂不可用';
      $('experience-mode').value=data.mode||'chat';$('experience-scene').value=data.scene||'';
      $('experience-reply-format').value=data.tls_state?.reply_format||'auto';
      const box=$('experience-memories');box.replaceChildren();
      for(const value of data.memories||[]){
        const row=text('li',undefined,'experience-memory-row');row.append(text('p',value.content||''));
        row.append(text('small','来源：'+(value.source_id||value.source||'当前APP授权资料')+(Number.isInteger(value.revision)?' · 修订 '+value.revision:''),'experience-caption'));
        if(value.id)row.append(button(value.editable===true?'查看与修正':'查看来源',()=>openMemory(value)));
        if(value.editable===false&&value.readonly_reason)row.append(text('small','当前只读：'+value.readonly_reason,'experience-caption'));
        box.append(row);
      }
      for(const value of data.shared_memories||[]){const row=text('li',undefined,'experience-memory-row');row.append(text('p',value.text||value.content||''),text('small','来自已绑定QQ · 仅按查阅授权读取，不在APP改写','experience-caption'));box.append(row);}
      if(!box.children.length)box.append(text('li',data.memory_state==='waiting_for_real_message'?'当前会话尚未有可用的实时记忆范围；正常聊天后可重新读取。':'当前授权范围没有可显示的长期资料。'));
      $('experience-memory-note').textContent='按 TLS 现有角色和资料授权读取；不会根据后台登录合并 QQ 私密资料。';
      const narrative=$('experience-narrative');narrative.replaceChildren();
      if(data.narrative){const value=data.narrative;narrative.append(text('p',value.title||value.name||'当前 TLS 剧情'),text('p',value.summary||value.setting||value.description||'当前剧情已由 TLS 维护。'));}
      else narrative.append(text('p','没有额外的已授权 TLS 剧情。上方会话简介是你的明确设定，不会当作现实记忆。'));
      $('experience-save-scene').disabled=false;status('已读取服务器状态。');
    }catch(error){if(panelCurrent(ticket))status(errorText(error),true);}
  }
  async function saveContext(event) {
    event.preventDefault();const ticket=panelTicket();if(!panelCurrent(ticket)||!contextSnapshot||$('experience-save-scene').disabled)return;
    $('experience-save-scene').disabled=true;
    try{
      const value=await call('POST','/chat/session-state',{session_id:state.activeId,
        mode:$('experience-mode').value,scene:$('experience-scene').value,reply_format:$('experience-reply-format').value,
        expected_revision:contextSnapshot.tls_state.revision});
      if(!panelCurrent(ticket))return;
      contextSnapshot.tls_state=value;const item=state.sessions.find(row=>row.session_id===state.activeId);if(item)item.tls_state=value;
      await readContext();if(panelCurrent(ticket)){status('已保存并回读。后续聊天会使用当前模式和剧情简介。');renderChrome();}
    }catch(error){if(panelCurrent(ticket))status(errorText(error)+' 请重新读取核对结果。',true);}
    finally{if(panelCurrent(ticket))$('experience-save-scene').disabled=!contextSnapshot;}
  }
  const memoryKey=(owner,id)=>owner+'|'+id;
  const memoryTicket=()=>memoryEditor&&({owner:memoryEditor.owner,id:memoryEditor.id,epoch:memoryEpoch,sessionId:memoryEditor.sessionId});
  const memoryCurrent=ticket=>ticket&&memoryEditor&&state.authenticated&&key()===ticket.owner&&panelScope===ticket.owner
    &&memoryEditor.id===ticket.id&&memoryEpoch===ticket.epoch&&$('memory-detail-dialog')?.open;
  const memoryTime=value=>{if(value===null||value===undefined||value==='')return '未记录';const date=new Date(typeof value==='number'?value*1000:value);return Number.isFinite(date.getTime())?date.toLocaleString():'未记录';};
  function memoryMessage(value,error=false){$('memory-detail-status').textContent=value;$('memory-detail-status').classList.toggle('error',error);}
  function memoryHistory(data){
    const box=$('memory-history-list');box.replaceChildren();
    const supplied=Array.isArray(data.history),rows=supplied?data.history:[];
    const total=Number.isInteger(data.history_total)&&data.history_total>=0?data.history_total:rows.length;
    $('memory-history-summary').textContent='修订历史'+(supplied?'（'+rows.length+(data.history_limited===true?' / '+total:'')+'项）':'');
    $('memory-history-note').textContent=!supplied?'当前服务器未提供历史详情；当前资料仍可正常查看。':data.history_limited===true?'仅显示最近'+rows.length+'项，共'+total+'项；更早记录未在这里展开。':'按服务器原始顺序显示已返回的修订；不推断操作人身份。';
    const operations={create:'建立',correct:'修正',update:'更新',archive:'归档',restore:'恢复',supersede:'替代',delete:'删除'};
    for(const item of rows){
      if(!item||!item.record||typeof item.record.content!=='string')continue;
      const record=item.record,row=text('article',undefined,'experience-memory-row');
      row.append(text('strong','修订 '+(Number.isInteger(item.revision)?item.revision:'未提供')+' · '+(operations[item.operation]||item.operation||'操作未提供')),
        text('small',memoryTime(item.changed_at)+' · 来源：'+(record.source_id||record.source||'未提供'),'experience-caption'),text('p',record.content));box.append(row);
    }
    if(supplied&&!box.children.length)box.append(text('p','服务器尚未返回可显示的修订内容。','appearance-help'));
  }
  function memoryControls(){
    if(!memoryEditor)return;const pending=memoryPending.get(memoryKey(memoryEditor.owner,memoryEditor.id));
    const ready=memoryEditor.record?.editable===true&&!memoryEditor.busy&&!pending;
    $('memory-correction').disabled=!ready;$('memory-correct-confirm').disabled=!ready;
    $('memory-correct-save').disabled=!ready||!$('memory-correct-confirm').checked;
    $('memory-detail-refresh').disabled=memoryEditor.busy===true;
    $('memory-pending-clear').hidden=pending?.phase!=='unknown';$('memory-pending-clear').disabled=memoryEditor.busy===true||pending?.readChecked!==true;
  }
  function closeMemory(){
    if(memoryEditor&&$('memory-correction'))memoryDrafts.set(memoryKey(memoryEditor.owner,memoryEditor.id),$('memory-correction').value);
    memoryEpoch++;memoryReadSerial++;memoryEditor=null;const dialog=$('memory-detail-dialog');if(dialog?.open)dialog.close();
    for(const id of ['memory-detail-original','memory-detail-source','memory-detail-status'])if($(id))$(id).textContent='';
    if($('memory-correction'))$('memory-correction').value='';if($('memory-correct-confirm'))$('memory-correct-confirm').checked=false;
    if($('memory-history-list'))$('memory-history-list').replaceChildren();if($('memory-history'))$('memory-history').open=false;
  }
  function openMemory(value){
    if(!scopeReady()||!panelScope||panelScope!==key()||!value?.id)return;
    closeMemory();memoryEditor={owner:key(),sessionId:state.activeId,id:String(value.id),record:null,busy:false};
    $('memory-detail-original').textContent=value.content||'';$('memory-detail-source').textContent='正在读取同一APP资料的真实来源…';
    $('memory-correction').value=memoryDrafts.get(memoryKey(key(),String(value.id)))??value.content??'';
    $('memory-detail-dialog').showModal();memoryControls();readMemory();
  }
  async function readMemory(){
    const ticket=memoryTicket();if(!memoryCurrent(ticket)||memoryEditor.busy)return;
    const serial=++memoryReadSerial;memoryEditor.busy=true;memoryControls();memoryMessage('正在读取当前资料…');
    try{
      const data=await call('GET','/chat/memory-detail?session_id='+encodeURIComponent(ticket.sessionId)+'&id='+encodeURIComponent(ticket.id));
      if(!memoryCurrent(ticket)||serial!==memoryReadSerial)return;
      const record=data?.record;if(!record||String(record.id)!==ticket.id||!Number.isInteger(record.revision))throw Error('服务器未返回可核对的资料版本。');
      memoryEditor.record={...record,editable:data.editable===true&&record.editable===true};
      $('memory-detail-original').textContent=record.content||'';
      $('memory-detail-source').textContent='来源：'+(record.source_id||record.source||'APP原生记忆')+' · 证据：'+(record.evidence_kind||'未提供')+' · 修订 '+record.revision+'\n建立：'+memoryTime(record.created_at)+'\n最近更新：'+memoryTime(record.updated_at);
      memoryHistory(data);
      const id=memoryKey(ticket.owner,ticket.id),pending=memoryPending.get(id);let message=(memoryEditor.failure?memoryEditor.failure+' ':'')+'已读取当前保存值；这里只修正APP自身的原生资料，不改写QQ共享资料。';
      if(pending){
        pending.readChecked=true;
        if(record.revision>pending.body.expected_revision&&record.content===pending.body.content){memoryPending.delete(id);memoryDrafts.delete(id);$('memory-correction').value=record.content;message='服务器当前内容已与本次修正一致。不会重复提交。';}
        else message=(pending.failure?pending.failure+' ':'')+'已回读；上次提交仍待核对，不会自动重发。';
      }else if(!memoryDrafts.has(id))$('memory-correction').value=record.content||'';
      $('memory-correct-confirm').checked=false;memoryMessage(message);
    }catch(error){if(memoryCurrent(ticket))memoryMessage(errorText(error)+' 当前编辑草稿保留。',true);}
    finally{if(memoryCurrent(ticket)&&serial===memoryReadSerial){memoryEditor.busy=false;memoryControls();}}
  }
  async function correctMemory(event){
    event.preventDefault();const ticket=memoryTicket();if(!memoryCurrent(ticket)||memoryEditor.busy||!memoryEditor.record?.editable||!$('memory-correct-confirm').checked)return;
    const id=memoryKey(ticket.owner,ticket.id);if(memoryPending.has(id))return;
    const content=$('memory-correction').value.trim(),record=memoryEditor.record;memoryDrafts.set(id,$('memory-correction').value);
    if(!content||content.length>6000){memoryMessage('请填写1至6000字的修正内容；不会用空文字删除资料。',true);return;}
    if(content===record.content){memoryMessage('修正内容与当前保存值一致，无需提交。');return;}
    const pending={body:{session_id:ticket.sessionId,id:ticket.id,content,expected_revision:record.revision},phase:'inflight',readChecked:false};
    memoryPending.set(id,pending);memoryEditor.busy=true;memoryControls();memoryMessage('正在保存这项明确修正…');
    try{
      const data=await call('POST','/chat/memory-correct',pending.body);
      const saved=data?.record;if(!saved||String(saved.id)!==ticket.id||saved.content!==content||!(saved.revision>record.revision))throw Error('返回结果尚不能确认保存内容，请重新读取核对。');
      if(memoryPending.get(id)===pending)memoryPending.delete(id);memoryDrafts.delete(id);
      if(memoryCurrent(ticket)){$('memory-correction').value=content;memoryEditor.record=saved;memoryEditor.failure='';memoryMessage('已保存，正在回读当前版本…');}
    }catch(error){
      if(error.status===409){memoryPending.delete(id);if(memoryCurrent(ticket)){memoryEditor.failure='这项资料已被其他操作更新，编辑草稿已保留。请比较最新原文后再明确保存。';memoryMessage(memoryEditor.failure,true);}}
      else if([400,403,404].includes(error.status)){memoryPending.delete(id);if(memoryCurrent(ticket)){memoryEditor.failure=errorText(error)+' 编辑草稿已保留。';memoryMessage(memoryEditor.failure,true);}}
      else{pending.phase='unknown';pending.failure=errorText(error);if(memoryCurrent(ticket))memoryMessage(pending.failure+' 请读取核对，不会自动重发。',true);}
    }finally{if(memoryCurrent(ticket)){memoryEditor.busy=false;$('memory-correct-confirm').checked=false;memoryControls();}}
    if(memoryCurrent(ticket)&&!memoryPending.has(id)){await readMemory();if(memoryCurrent(ticket))await readContext();}
  }
  function renderExpression() {
    const snapshot=expressionSnapshot;if(!snapshot)return;
    const level=$('experience-setting-level').value;
    const value=level==='role'?{...snapshot.defaults,...snapshot.role}:snapshot.effective;
    $('experience-frequency').value=value.frequency;$('experience-per-unit').checked=value.per_unit;
    $('experience-cooldown').value=value.cooldown_seconds;$('experience-fragments').value=value.fragment_display;
    for(const mode of ['chat','roleplay','technical'])$('experience-policy-'+mode).value=value.mode_policies[mode];
    const labels={default:'系统默认',role:'角色默认',session:'本会话覆盖'};
    $('experience-inheritance').textContent=Object.entries(snapshot.sources).map(([name,source])=>({frequency:'频率',per_unit:'按语义配图',cooldown_seconds:'冷却',mode_policies:'模式策略',fragment_display:'展示'}[name]||name)+'：'+labels[source]).join(' · ');
  }
  async function readExpression() {
    const ticket=panelTicket();if(!panelCurrent(ticket))return;
    expressionSnapshot=null;$('experience-save-expression').disabled=true;$('experience-reset-expression').disabled=true;status('正在读取表达偏好…');
    try{const value=await call('GET',route('expression-settings'));if(!panelCurrent(ticket))return;expressionSnapshot=value;renderExpression();
      $('experience-save-expression').disabled=false;$('experience-reset-expression').disabled=false;status('偏好保存到 TLS，用户和角色的单张图片偏好仍分别维护。');}
    catch(error){if(panelCurrent(ticket))status(errorText(error),true);}
  }
  async function saveExpression(event,reset=false) {
    if(event)event.preventDefault();const ticket=panelTicket();if(!panelCurrent(ticket)||!expressionSnapshot||$('experience-save-expression').disabled)return;
    const level=$('experience-setting-level').value;
    const changes={frequency:$('experience-frequency').value,per_unit:$('experience-per-unit').checked,
      cooldown_seconds:Number($('experience-cooldown').value),fragment_display:$('experience-fragments').value,
      mode_policies:Object.fromEntries(['chat','roleplay','technical'].map(mode=>[mode,$('experience-policy-'+mode).value]))};
    $('experience-save-expression').disabled=true;$('experience-reset-expression').disabled=true;
    try{
      const value=await call('POST','/chat/expression-settings',{session_id:state.activeId,level,
        ...(reset?{reset:true}:{changes}),expected_revision:expressionSnapshot[level+'_revision']});
      if(!panelCurrent(ticket))return;
      expressionSnapshot=value;renderExpression();status(reset?'已恢复继承并回读生效值。':'已保存并回读。后续回复将使用新策略。');
    }catch(error){if(panelCurrent(ticket))status(errorText(error)+' 请重新读取核对结果。',true);}
    finally{if(panelCurrent(ticket)){$('experience-save-expression').disabled=!expressionSnapshot;$('experience-reset-expression').disabled=!expressionSnapshot;}}
  }
  async function archive(item) {
    if(item.session_id===primaryConnectionId()){showNotice('长期聊天保持连接；旧记录可以在侧栏查看。');return;}
    if(state.sending||state.attaching)return;
    try{await call('POST','/chat/session-state',{session_id:item.session_id,archived:!(item.tls_state&&item.tls_state.archived),
      ...(item.tls_state&&Number.isInteger(item.tls_state.revision)?{expected_revision:item.tls_state.revision}:{})});
      await loadSessions({select:false});showNotice(item.tls_state&&item.tls_state.archived?'会话已恢复。':'会话已归档，历史和剧情保留。');renderChrome();}
    catch(error){notice(error);}
  }
  async function search(event) {
    event.preventDefault();const ticket=panelTicket();if(!panelCurrent(ticket))return;
    const query=$('experience-search-input').value.trim();if(!query)return;
    const owner=panelScope;status('正在搜索服务器可读历史…');
    try{
      const result=await call('GET',route('search')+'&q='+encodeURIComponent(query));if(!panelCurrent(ticket))return;
      const list=$('experience-search-results');list.replaceChildren();
      for(const hit of result.items||[]){const row=button((hit.role==='assistant'?'伙伴':'你')+' · '+hit.excerpt,async()=>{
        if(!panelCurrent(ticket))return;const session=state.activeId;close();await loadHistory(session);
        if(!state.authenticated||owner!==key())return;
        const message=state.messages.find(value=>String(value.serverId)===String(hit.message_id));
        const node=message&&[...$('messages').querySelectorAll('.message-row')].find(value=>value.dataset.messageKey===String(message.id));
        if(node){node.scrollIntoView({block:'center'});node.classList.add('search-arrival');setTimeout(()=>node.classList.remove('search-arrival'),1400);}
      },'history-search-result');list.append(row);}
      status('找到 '+(result.items||[]).length+' 条 · 本次读取 '+result.scanned+' 条'+(result.limited?'，已达到可读窗口或命中上限。':'。')+' 不搜索隐藏推理或其他会话。');
    }catch(error){if(panelCurrent(ticket))status(errorText(error),true);}
  }
  async function regenerate(message) {
    if(primaryConnectionId()&&state.activeId!==primaryConnectionId()){showNotice('以前的记录保持只读，请回到伙伴继续聊天。');return;}
    if(state.sending||state.remoteRunning||state.attaching||!message.serverId)return;
    const owner=key(),id=state.activeId;state.sending=true;renderChrome();
    try{
      const raw=await bridgeRequest('POST','/chat/regenerate',{session_id:id,message_id:message.serverId,
        client_message_id:'tc-regen-'+(window.crypto&&crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)),enable_streaming:true},{streaming:true});
      if(owner!==key())return;
      const result=parseStream(raw);if(result.error)throw new Error(result.error);
      await loadHistory(id);showNotice(result.messageId?'已追加新的回答，原回复仍保留。':'正在核对回复保存状态，请同步记录。');
    }catch(error){if(owner===key())notice(error);}
    finally{state.sending=false;renderChrome();}
  }
  async function readBookmarks() {
    if(!state.authenticated||!state.activeId)return;
    const owner=key(),ticket=panelTicket();if(panelCurrent(ticket))status('正在读取重要消息…');
    try{
      const data=await call('GET',route('bookmarks'));if(!state.authenticated||owner!==key())return;
      bookmarkScope=owner;bookmarkRows=data.items||[];
      if(!panelCurrent(ticket)){decorateMessages();return;}
      const list=$('experience-bookmark-list');list.replaceChildren();
      for(const saved of bookmarkRows){
        const row=document.createElement('div');row.className='bookmark-item';
        const view=button((saved.role==='assistant'?'伙伴':'你')+' · '+(saved.excerpt||'图片、语音或附件'),async()=>{
          if(!panelCurrent(ticket))return;
          try{const detail=await call('GET',route('bookmarks')+'&message_id='+encodeURIComponent(saved.message_id));if(!panelCurrent(ticket))return;
            $('bookmark-reading-title').textContent=(detail.role==='assistant'?'伙伴':'你')+'的消息';
            $('bookmark-reading-text').textContent=detail.text||'这条消息以附件为主。';
            $('bookmark-reading-note').textContent=detail.media_in_original_history?'图片、语音和文件保留在原消息中，收藏不复制附件。':'';
            $('bookmark-reading-dialog').showModal();
          }catch(error){if(panelCurrent(ticket))notice(error);}
        },'bookmark-excerpt');view.disabled=saved.available===false;
        row.append(view,button('取消收藏',()=>toggleBookmark(saved.message_id,false)));list.append(row);
      }
      if(!bookmarkRows.length)list.append(text('p','把重要的约定、温柔的话或想回看的内容收在这里。点击消息下面的 ☆ 即可。','experience-caption'));
      status('收藏保存在 TLS，原消息和附件不另存一份。'+(data.limited?'当前最多显示 200 条。':''));decorateMessages();
    }catch(error){if(panelCurrent(ticket))status(errorText(error),true);}
  }
  async function toggleBookmark(messageId,enabled) {
    if(!state.authenticated||!state.activeId)return;const owner=key();
    try{
      const old=bookmarkScope===owner&&bookmarkRows.find(value=>String(value.message_id)===String(messageId));
      await call('POST','/chat/bookmarks',{session_id:state.activeId,message_id:messageId,enabled,
        ...(old?{expected_revision:old.revision}:{})});
      if(!state.authenticated||owner!==key())return;await readBookmarks();showNotice(enabled?'已收藏到重要消息。':'已取消收藏，原记录保留。');
    }catch(error){if(state.authenticated&&owner===key())notice(error);}
  }
  const cursorKey=()=>pref('read-cursor.'+encodeURIComponent(key()));
  function readCursor() {try{return JSON.parse(storage.get(cursorKey())||'null');}catch(_){return null;}}
  function afterCursor(cursor) {
    if(!cursor||cursor.message_id==null)return [];
    const records=state.messages.filter(value=>value.delivery==='confirmed'&&value.serverId!=null);
    const index=records.findIndex(value=>String(value.serverId)===String(cursor.message_id));
    return (index>=0?records.slice(index+1):records.filter(value=>Number(value.serverId)>Number(cursor.message_id))).filter(value=>value.role==='assistant');
  }
  function decorateUnread() {
    const banner=$('continue-reading');if(!banner)return;
    const unseen=afterCursor(readCursor());banner.hidden=!unseen.length;
    banner.textContent=unseen.length?'继续阅读 · 当前记录中 '+unseen.length+' 条新回复':'';
    for(const node of $('messages').querySelectorAll('.unread-divider'))node.remove();
    const boundary=readBoundaries.get(key());
    if(boundary){const row=[...$('messages').querySelectorAll('.message-row')].find(node=>{
      const message=state.messages.find(value=>String(value.id)===node.dataset.messageKey);return message&&String(message.serverId)===boundary;
    });if(row)row.before(text('div','上次读到这里','unread-divider'));}
  }
  function markVisibleRead() {
    if(!state.authenticated||!state.activeId||readRestorePending===key()||document.hidden||nativeConfig().foreground===false)return;
    const area=$('messages').getBoundingClientRect();let last=null;
    for(const row of $('messages').querySelectorAll('.message-row')){
      const box=row.getBoundingClientRect();if(box.bottom<=area.top||box.top>=area.bottom||box.bottom>area.bottom+4)continue;
      const message=state.messages.find(value=>String(value.id)===row.dataset.messageKey);
      if(message&&message.delivery==='confirmed'&&message.serverId!=null)last=message;
    }
    const cursor=readCursor();
    if(last&&(!cursor||Number(last.serverId)>Number(cursor.message_id))){storage.set(cursorKey(),JSON.stringify({message_id:String(last.serverId),seen_at:Date.now()}));decorateUnread();}
  }
  function queueRead() {if(readFrame)return;readFrame=requestAnimationFrame(()=>{readFrame=0;markVisibleRead();});}
  function continueReading() {
    const values=afterCursor(readCursor());if(!values.length)return;
    const row=[...$('messages').querySelectorAll('.message-row')].find(node=>node.dataset.messageKey===String(values[0].id));
    if(row)row.scrollIntoView({block:'start'});queueRead();
  }
  async function recordVoice() {
    if(!scopeReady()||state.sending||state.attaching||state.remoteRunning)return;
    if(primaryConnectionId()&&state.activeId!==primaryConnectionId()){showNotice('请先回到伙伴再发送语音。');return;}
    if(attachmentQueue().length>=4){showNotice('每条最多 4 个附件。');return;}
    const owner=key(),sessionId=state.activeId;let item;
    state.attaching=true;renderChrome();
    try{
      item={localId:'voice-'+Date.now(),session_id:sessionId,status:'choosing'};
      state.attachmentQueues.set(sessionId,[...attachmentQueue(sessionId),item]);renderAttachments();
      const body=await nativeAsync('recordVoice',[sessionId],300000);
      if(owner!==key())return;
      if(body&&body.cancelled===true){state.attachmentQueues.set(sessionId,attachmentQueue(sessionId).filter(value=>value!==item));return;}
      const data=responseData(body);
      if(!data||!data.attachment_id||data.session_id!==sessionId||!['record','file'].includes(data.type))throw new Error('服务器未确认语音附件。');
      Object.assign(item,data,{status:'ready'});showNotice('语音已加入待发送。可附带话语，确认后点发送。');
    }catch(error){
      const localFailure=['recorder_unavailable','voice_not_ready'].includes(error.code);
      if(item&&localFailure)state.attachmentQueues.set(sessionId,attachmentQueue(sessionId).filter(value=>value!==item));
      else if(item)item.status='unknown';
      if(localFailure)showNotice(errorText(error),null,true);else notice(error);
    }
    finally{state.attaching=false;renderAttachments();if(window.ChatComposer)window.ChatComposer.renderPreview();renderChrome();}
  }
  function decorateMessages() {
    for(const row of $('messages').querySelectorAll('.message-row')){
      const existingTools=row.querySelector('.message-tools');if(existingTools)existingTools.remove();
      const message=state.messages.find(value=>String(value.id)===row.dataset.messageKey);
      if(!message||message.delivery!=='confirmed'||message.serverId==null)continue;
      const bar=document.createElement('div');bar.className='message-tools';
      const actions=document.createElement('div');actions.className='message-action-menu';actions.hidden=true;actions.setAttribute('role','group');actions.setAttribute('aria-label','这条消息的操作');
      const toggle=button('···',()=>{
        const opening=actions.hidden;closeMessageTools();
        if(opening&&window.ChatComposer)window.ChatComposer.closePanel();
        actions.hidden=!opening;toggle.setAttribute('aria-expanded',String(opening));
        if(opening){const area=$('messages').getBoundingClientRect();actions.classList.toggle('below',bar.getBoundingClientRect().top-actions.getBoundingClientRect().height<area.top+8);}
      },'message-tools-toggle');
      toggle.setAttribute('aria-label','打开这条消息的操作');toggle.setAttribute('aria-expanded','false');
      const action=(label,fn)=>button(label,()=>{closeMessageTools();fn();});
      const historyOnly=primaryConnectionId()&&state.activeId!==primaryConnectionId();
      if(!historyOnly)actions.append(action('引用这条消息',()=>window.ChatComposer.addReference({message_id:message.serverId,text:message.text,role:message.role})));
      if(!historyOnly&&message.role==='assistant')actions.append(action('让伙伴再答一次',()=>regenerate(message)));
      const saved=bookmarkScope===key()&&bookmarkRows.some(value=>String(value.message_id)===String(message.serverId));
      const star=action(saved?'★ 取消收藏':'☆ 收藏到重要消息',()=>toggleBookmark(message.serverId,!saved));star.setAttribute('aria-label',saved?'取消收藏这条消息':'收藏这条消息');actions.append(star);
      if(saved){toggle.textContent='★ ···';toggle.setAttribute('aria-label','已收藏，打开这条消息的操作');}
      bar.append(toggle,actions);
      const bubble=row.querySelector('.message-bubble');
      if(bubble)bubble.ondblclick=event=>{if(historyOnly)return;if(event.target.closest('button,a,img,input'))return;event.preventDefault();const selection=window.getSelection();if(selection)selection.removeAllRanges();window.ChatComposer.addReference({message_id:message.serverId,text:message.text,role:message.role});};
      row.querySelector('.message-body').append(bar);
    }
  }
  function closeMessageTools() {
    for(const menu of document.querySelectorAll('.message-action-menu'))menu.hidden=true;
    for(const toggle of document.querySelectorAll('.message-tools-toggle'))toggle.setAttribute('aria-expanded','false');
  }
  function receiveStream(value) {
    if(!value||typeof value.id!=='string'||typeof value.chunk!=='string'||!state.requests.has(value.id))return;
    let entry=live.get(value.id);
    if(!entry){entry={owner:key(),raw:'',queued:false,message:null};live.set(value.id,entry);}
    if(entry.owner!==key())return;
    entry.raw+=value.chunk;
    if(entry.queued)return;entry.queued=true;
    requestAnimationFrame(()=>{
      entry.queued=false;if(entry.owner!==key()||!state.requests.has(value.id))return;
      let parsed;try{parsed=parseStream(entry.raw);}catch(_){return;}
      if(parsed.phase)state.replyPhase=parsed.phase;
      else if(parsed.parts.length)state.replyPhase='streaming';
      renderChrome();
      if(!parsed.parts.length)return;
      if(!entry.message){entry.message={id:'stream-'+value.id,role:'assistant',delivery:'unconfirmed',created_at:new Date().toISOString()};state.messages.push(entry.message);}
      entry.message.parts=parsed.parts;entry.message.text=parsed.text;renderMessages();
    });
  }
  function endStream(id,failed=false) {
    const entry=live.get(id);if(!entry)return;live.delete(id);
    if(entry.owner!==key()||!entry.message)return;
    if(!failed)state.messages=state.messages.filter(value=>value!==entry.message);
    else entry.message.delivery='unconfirmed';
  }
  const originalReceive=receive;
  receive=function(id,payload){let failed=false;try{const value=parse(payload);failed=!value||value.status<200||value.status>=300;}catch(_){failed=true;}endStream(String(id),failed);return originalReceive(id,payload);};
  // The native bridge calls this exported function rather than the old frozen
  // function reference. It keeps the original request and authentication logic.
  const originalRender=renderMessages;
  renderMessages=function(options){const result=originalRender(options);decorateMessages();decorateUnread();queueRead();return result;};
  const originalChrome=renderChrome;
  renderChrome=function(){
    originalChrome();
    const historyOnly=!!primaryConnectionId()&&state.activeId!==primaryConnectionId();
    const readOnly=historyOnly||!!currentState().archived;
    $('menu-delete').hidden=!!primaryConnectionId();
    if($('persona'))$('persona').disabled=!!primaryConnectionId();
    // Recompute both directions: reading an old record must not leave the
    // primary conversation's input disabled after returning to it.
    $('draft').disabled=readOnly;
    document.querySelector('.chat-main').classList.toggle('reading-history',readOnly);
    const hint=$('history-reading-hint');if(hint)hint.hidden=!readOnly;
    if(readOnly){$('send-button').disabled=true;$('attach-button').disabled=true;
      $('connection-status').textContent=historyOnly?'以前的记录 · 仅供回看':'已归档的记录 · 仅供回看';}
  };
  const originalSelect=selectSession;
  function saveReading() {if(!state.activeId||!state.messages.length)return;const position=captureMessagePosition($('messages'));storage.set(pref('reading.'+encodeURIComponent(key())),JSON.stringify(position));}
  selectSession=async function(id,options={}){
    saveReading();const target=JSON.stringify([state.server,state.username,id]);readRestorePending=target;
    const result=await originalSelect(id);
    if(state.activeId===id){
      let saved;try{saved=JSON.parse(storage.get(pref('reading.'+encodeURIComponent(key()))));}catch(_){}
      const unseen=afterCursor(readCursor());if(unseen.length)readBoundaries.set(key(),String(unseen[0].serverId));
      requestAnimationFrame(()=>{
        if(key()!==target)return;
        if(options.focusLatest===true)jumpToLatest();
        else if(saved&&!saved.follow){const row=[...$('messages').querySelectorAll('.message-row')].find(value=>value.dataset.messageKey===saved.key);setMessageScroll($('messages'),row?$('messages').scrollTop+row.getBoundingClientRect().top-$('messages').getBoundingClientRect().top-saved.offset:saved.top);}
        else if(unseen.length)continueReading();
        readRestorePending='';decorateUnread();queueRead();
      });
      if($('experience-bookmark-list'))readBookmarks();
    }else readRestorePending='';
    return result;
  };
  function init() {
    const dialog=document.createElement('dialog');dialog.id='experience-dialog';dialog.className='experience-dialog';
    dialog.innerHTML='<div class="experience-heading"><div><span class="eyebrow">ASTERIA CHAT</span><h2>会话与表达</h2></div><button id="experience-close" type="button" class="icon-button" aria-label="关闭">×</button></div><nav class="experience-tabs"><button data-experience-tab="context">角色与剧情</button><button data-experience-tab="expression">表达偏好</button><button data-experience-tab="search">历史搜索</button></nav><div class="experience-body"><section data-experience-pane="context"><div class="experience-role"><img src="logo.svg" alt=""><div><small>当前配置角色</small><strong id="experience-persona"></strong></div></div><form id="experience-context-form"><div id="experience-context-fields"></div><button id="experience-save-scene" class="primary-button">保存会话设置</button></form><details class="experience-details"><summary>相关记忆与 TLS 剧情</summary><p id="experience-memory-note"></p><ul id="experience-memories"></ul><div id="experience-narrative"></div></details><button id="experience-refresh-context" class="text-button">重新读取状态</button></section><section data-experience-pane="expression" hidden><form id="experience-expression-form"><div id="experience-expression-fields"></div><p id="experience-inheritance" class="experience-caption"></p><p class="experience-caption">图片文件只维护一份。没有合适素材时只发文字；全局冷却与单张图片冷却取较大值。</p><div class="experience-actions"><button id="experience-reset-expression" class="secondary-button" type="button">恢复继承</button><button id="experience-save-expression" class="primary-button">保存到 TLS</button></div></form><button id="experience-refresh-expression" class="text-button">重新读取偏好</button></section><section data-experience-pane="search" hidden><form id="experience-search-form" class="experience-search"><input id="experience-search-input" type="search" maxlength="200" placeholder="搜索这段对话的历史…"><button class="primary-button">搜索</button></form><p class="experience-caption">搜索当前会话服务器可读的最近 1000 条记录，最多显示 200 个命中。</p><div id="experience-search-results"></div></section><p id="experience-status" role="status"></p></div>';
    document.body.append(dialog);
    const memoryDialog=document.createElement('dialog');memoryDialog.id='memory-detail-dialog';memoryDialog.className='settings-dialog memory-detail-dialog';
    memoryDialog.innerHTML='<form id="memory-correct-form" class="settings-form"><div class="dialog-heading"><h2>资料来源与修正</h2><button id="memory-detail-close" class="icon-button" type="button" aria-label="关闭资料详情">×</button></div><p id="memory-detail-source" class="experience-caption"></p><h3>服务器当前保存的原文</h3><div id="memory-detail-original" class="memory-detail-original"></div><p class="appearance-help">显示这项资料的来源和版本，不代表已展开全部历史。QQ共享资料保留只读；修正不会删除历史或改写角色人格。</p><label class="experience-field">修正后的内容<textarea id="memory-correction" rows="5" maxlength="6000"></textarea></label><label class="switch-label"><input id="memory-correct-confirm" type="checkbox"> 已比较原文，确认保存这项修正</label><div class="appearance-actions"><button id="memory-detail-refresh" type="button" class="text-button">重新读取</button><button id="memory-correct-save" type="submit" class="primary-button">明确保存修正</button></div><p id="memory-detail-status" role="status" class="appearance-help"></p><button id="memory-pending-clear" type="button" class="text-button" hidden>已核对，结束等待</button></form>';
    document.body.append(memoryDialog);
    const history=document.createElement('details');history.id='memory-history';history.className='experience-details';
    const historySummary=text('summary','修订历史');historySummary.id='memory-history-summary';const historyNote=text('p','','appearance-help');historyNote.id='memory-history-note';const historyList=document.createElement('div');historyList.id='memory-history-list';
    history.append(historySummary,historyNote,historyList);$('memory-detail-original').after(history);
    $('memory-detail-close').onclick=closeMemory;memoryDialog.addEventListener('close',()=>{if(memoryEditor)closeMemory();});
    $('memory-detail-refresh').onclick=readMemory;$('memory-correct-confirm').onchange=memoryControls;$('memory-correct-form').onsubmit=correctMemory;
    $('memory-correction').oninput=()=>{if(memoryEditor)memoryDrafts.set(memoryKey(memoryEditor.owner,memoryEditor.id),$('memory-correction').value);$('memory-correct-confirm').checked=false;memoryControls();};
    $('memory-pending-clear').onclick=()=>{if(!memoryEditor||memoryEditor.busy)return;const id=memoryKey(memoryEditor.owner,memoryEditor.id),pending=memoryPending.get(id);if(pending?.phase==='unknown'&&pending.readChecked){memoryPending.delete(id);memoryMessage('已结束等待；原请求仍可能稍后完成。请比较当前原文后再决定是否修改。');memoryControls();}};
    const mode=control('experience-mode','select');selectOptions(mode,[['chat','日常聊天'],['roleplay','角色扮演'],['technical','讨论与解释']]);
    const scene=control('experience-scene','textarea');scene.rows=5;scene.maxLength=3000;scene.placeholder='这段对话的场景、剧情进度或讨论背景…';
    $('experience-context-fields').append(field('会话模式',mode),field('会话剧情 / 背景简介',scene));
    const replyFormat=control('experience-reply-format','select');selectOptions(replyFormat,[['auto','自动：RP使用动作与话语，其余保持流式文字'],['structured','动作与话语：整轮解析后显示'],['text','普通流式文字']]);$('experience-context-fields').append(field('伙伴的表达方式',replyFormat));
    const fields=$('experience-expression-fields');
    const level=control('experience-setting-level','select');selectOptions(level,[['session','仅当前会话'],['role','此账户下该角色的默认设置']]);fields.append(field('修改范围',level));
    const frequency=control('experience-frequency','select');selectOptions(frequency,[['expressive','丰富 · 尽量一语义单元一表情'],['balanced','适中'],['low','少量'],['off','关闭自动配图']]);fields.append(field('表情使用频率',frequency));
    const per=control('experience-per-unit');per.type='checkbox';fields.append(field('允许多个合适的语义单元分别配图',per));
    const cooldown=control('experience-cooldown');cooldown.type='number';cooldown.min=0;cooldown.max=86400;fields.append(field('最短重复冷却（秒）',cooldown));
    for(const [id,label]of [['chat','日常聊天配图'],['roleplay','RP 配图'],['technical','讨论配图']]){const select=control('experience-policy-'+id,'select');selectOptions(select,[['semantic','按完整语义'],['paragraph','按段落，保持叙事连贯'],['single','整轮最多一张'],['text_only','只用文字']]);fields.append(field(label,select));}
    const fragments=control('experience-fragments','select');selectOptions(fragments,[['semantic','按语义组织话语和表情'],['compact','紧凑，保持原段落']]);fields.append(field('默认片段展示',fragments));
    const menu=$('more-menu');menu.prepend(button('重要消息',()=>open('bookmarks')),button('角色与剧情',()=>open('context')),button('表达偏好',()=>open('expression')),button('搜索服务器历史',()=>open('search')));
    menu.prepend(button('查找当前文字',()=>{hideMoreMenu();openMessageSearch();},'menu-item'));
    $('touch-button').onclick=()=>window.ChatComposer.showActions();
    $('voice-button').onclick=recordVoice;
    const tabs=document.createElement('div');tabs.className='session-views';
    for(const [value,label]of [['active','正在聊'],['archived','已归档']]){const tab=button(label,()=>{state.sessionView=value;for(const child of tabs.children)child.classList.toggle('selected',child===tab);renderSessions();});if(value==='active')tab.classList.add('selected');tabs.append(tab);}
    $('conversation-list').before(tabs);
    for(const tab of dialog.querySelectorAll('[data-experience-tab]'))tab.addEventListener('click',()=>open(tab.dataset.experienceTab));
    const bookmarkTab=button('重要消息',()=>open('bookmarks'));bookmarkTab.dataset.experienceTab='bookmarks';dialog.querySelector('.experience-tabs').append(bookmarkTab);
    const bookmarkPane=document.createElement('section');bookmarkPane.dataset.experiencePane='bookmarks';bookmarkPane.hidden=true;bookmarkPane.innerHTML='<h3>留着慢慢回看</h3><div id="experience-bookmark-list"></div>';dialog.querySelector('.experience-body').prepend(bookmarkPane);
    const reading=document.createElement('dialog');reading.id='bookmark-reading-dialog';reading.className='settings-dialog';reading.innerHTML='<div class="settings-form"><div class="dialog-heading"><h2 id="bookmark-reading-title">重要消息</h2><button id="bookmark-reading-close" type="button" class="icon-button">×</button></div><div id="bookmark-reading-text" class="bookmark-reading-text"></div><p id="bookmark-reading-note" class="experience-caption"></p></div>';document.body.append(reading);$('bookmark-reading-close').onclick=()=>reading.close();
    const continuation=button('',continueReading,'continue-reading');continuation.id='continue-reading';continuation.hidden=true;document.querySelector('.chat-header').after(continuation);
    const historyHint=document.createElement('div');historyHint.id='history-reading-hint';historyHint.className='history-reading-hint';historyHint.hidden=true;
    historyHint.append(text('span','这里保留着以前的聊天。'),button('回到伙伴继续聊 →',returnToBot,'history-return'));
    document.querySelector('.composer-area').prepend(historyHint);
    const voice=button('录一段语音',recordVoice,'attachment-picker voice-picker');document.querySelector('[data-compose-pane="attachments"]').append(voice,text('p','调用手机现有录音应用，录完作为语音加入待发送；不在后台录音。','compose-status'));
    $('messages').addEventListener('scroll',queueRead,{passive:true});document.addEventListener('visibilitychange',()=>{if(!document.hidden)queueRead();});
    for(const name of ['wheel','touchstart'])$('messages').addEventListener(name,()=>{state.liveFollowScope='';},{passive:true});
    document.addEventListener('click',event=>{if(!event.target.closest('.message-tools'))closeMessageTools();});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'){const active=document.querySelector('.message-tools-toggle[aria-expanded="true"]');if(active){event.preventDefault();closeMessageTools();active.focus();}}});
    $('experience-close').onclick=close;$('experience-context-form').onsubmit=saveContext;
    dialog.addEventListener('close',()=>{if(panelScope)close();});
    reading.addEventListener('close',closeBookmarkReading);
    $('experience-expression-form').onsubmit=saveExpression;$('experience-reset-expression').onclick=()=>saveExpression(null,true);
    level.onchange=renderExpression;$('experience-refresh-context').onclick=readContext;$('experience-refresh-expression').onclick=readExpression;
    $('experience-search-form').onsubmit=search;
    window.addEventListener('pagehide',saveReading);
    // Limit reflow from IME/panel transitions to the same scroll owner already
    // used by the composer; native metrics remain the sole Android height.
    window.addEventListener('resize',()=>{if(window.ChatComposer)window.ChatComposer.withReading(()=>{resizeDraft();window.ChatComposer.panelHeight();});});
  }
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return {open,close,scopeChanged,archive,receiveStream,receive,endStream,recordVoice,readBookmarks};
})();
