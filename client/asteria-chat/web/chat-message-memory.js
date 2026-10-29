'use strict';

/* Every association and edit comes from the owned saved-message APIs. */
window.ChatMessageMemory = (() => {
  let dialog, list, status, consent, consentLabel, propose, reject, save, refresh, heading, searchBox, searchText, searchFiction, searchStatus, searchList, searchButton,
    owner='', session='', messageId='', epoch=0, busy=false, searching=false, snapshot=null, searchEpoch=0;
  const pending=new Map();
  const correctionDrafts=new Map();
  const scope=()=>JSON.stringify([state.server,state.username,state.activeId]);
  const node=(tag,text)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;return value;};
  const button=(text,fn)=>{const value=node('button',text);value.type='button';value.className='text-button';value.addEventListener('click',fn);return value;};
  const ticket=()=>({epoch,owner,session,messageId});
  const current=t=>dialog?.open&&state.authenticated&&t.epoch===epoch&&t.owner===owner&&owner===scope();
  const pendingKey=t=>JSON.stringify([t.owner,t.messageId]);
  const route=t=>'/chat/message-memory?session_id='+encodeURIComponent(t.session)+'&message_id='+encodeURIComponent(t.messageId);
  function say(value){status.textContent=value;}
  function controls(){
    const candidate=snapshot?.pending_candidate,waiting=pending.has(pendingKey(ticket())),confirmable=candidate?.status==='pending'&&!snapshot?.important_saved;
    save.hidden=consentLabel.hidden=reject.hidden=!confirmable;propose.hidden=refresh.hidden=!messageId;
    save.disabled=busy||waiting||!confirmable||!consent.checked;consent.disabled=busy||waiting;reject.disabled=busy||waiting;
    propose.disabled=busy||waiting||!snapshot||snapshot.important_saved||candidate?.status==='pending'||candidate?.status==='confirmed';
    propose.textContent=candidate?.status==='rejected'?'重新加入记忆候选':'加入记忆候选';refresh.disabled=busy;
    if(searchButton){searchButton.disabled=searching||busy;searchText.disabled=searchFiction.disabled=searching||busy;}
  }
  function close(){epoch++;searchEpoch++;owner='';snapshot=null;busy=searching=false;if(dialog?.open)dialog.close();list?.replaceChildren();searchList?.replaceChildren();if(searchBox)searchBox.hidden=false;if(searchText)searchText.value='';if(searchFiction)searchFiction.checked=false;if(searchStatus)searchStatus.textContent='';if(consent)consent.checked=false;}
  function setup(){
    if(dialog)return;
    dialog=node('dialog');dialog.id='message-memory-dialog';dialog.className='settings-dialog message-memory-dialog';dialog.setAttribute('aria-labelledby','message-memory-title');
    const header=node('div');header.className='dialog-heading';heading=node('h2','这条消息的记忆');heading.id='message-memory-title';header.append(heading,button('关闭',close));
    list=node('div');list.id='message-memory-records';status=node('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    consent=node('input');consent.type='checkbox';consent.id='message-memory-confirm';consentLabel=node('label');consentLabel.append(consent,node('span','我已核对候选原文，确认保存为长期记忆；保留其原始来源与虚构/推断性质'));
    propose=button('加入记忆候选',()=>write('propose'));propose.id='message-memory-propose';
    save=button('确认保存长期记忆',()=>write('confirm'));save.id='message-memory-save';save.className='primary-button';reject=button('不保存这个候选',()=>write('reject'));refresh=button('重新读取',read);
    consent.addEventListener('change',controls);dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
    searchBox=node('details');searchBox.id='message-memory-search';searchBox.append(node('summary','检索相关记忆'));
    searchText=node('input');searchText.id='message-memory-query';searchText.type='search';searchText.maxLength=200;searchText.placeholder='搜索经历、约定或偏好';searchText.setAttribute('aria-label','相关记忆关键词');
    searchFiction=node('input');searchFiction.id='message-memory-include-roleplay';searchFiction.type='checkbox';const fictionLabel=node('label');fictionLabel.append(searchFiction,node('span','同时查看 RP 虚构记录（单独标注）'));
    searchButton=button('搜索记忆',searchRelated);searchButton.id='message-memory-search-button';
    searchText.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();void searchRelated();}});
    searchStatus=node('p');searchStatus.id='message-memory-search-status';searchStatus.setAttribute('role','status');searchList=node('div');searchList.id='message-memory-search-results';
    searchBox.append(node('p','只查当前已授权的记忆；已确认共享的另一端资料单独展示。相关不等于这条消息的原始来源，也不会因搜索写入记忆。'),searchText,fictionLabel,searchButton,searchStatus,searchList);
    const body=node('div');body.className='settings-form';body.append(header,node('p','收藏用于回看。加入候选后可核对原文；明确确认后才会写入长期记忆。'),list,propose,consentLabel,save,reject,refresh,status,searchBox);dialog.append(body);document.body.append(dialog);
  }
  const kind=value=>({user_reported:'用户原话/陈述',model_inference:'助手生成/推断',roleplay_event:'虚构互动',real_observation:'真实来源观察',action_result:'动作结果'}[value]||value||'未标注');
  function recordState(record){
    if(record.lifecycle==='deleted')return '已移除，保留来源与修订历史，不进入回复记忆。';
    if(record.retrieval_lane==='roleplay')return 'RP 虚构记录，与现实经历分开保存。';
    if(record.retrieval_lane==='inference')return '助手生成的表述，不自动当作用户事实。';
    if(record.real_recall_eligible===true)return '当前版本可参与现实记忆检索；是否使用仍取决于回复语境与预算。';
    if(record.real_recall_eligible===false)return '已经保存，但当前不进入现实记忆检索。';
    return '';
  }
  function memoryCard(record){
    const row=node('article');row.append(node('p',record.content),node('small',kind(record.evidence_kind)+' · '+record.memory_type+' · '+record.review_status+' · '+record.lifecycle));
    row.append(node('p','来源：'+record.source_id+' · 修订 '+record.revision));
    if(record.retention==='conversation_utterance')row.append(node('small','会话原话记录，不等于已经确认的长期偏好或事实。'));
    else if(record.retention==='explicit_long_term')row.append(node('small','由你明确确认保存的长期记录，保留原始证据性质。'));
    const detail=recordState(record);if(detail)row.append(node('p',detail));
    if(record.corrected)row.append(node('small','显示已纠正的当前版本；旧内容仅保留在来源历史中。'));
    if(record.original_text&&record.original_text!==record.content){const original=node('details');original.append(node('summary','保存时原文'),node('p',record.original_text));row.append(original);}
    if(record.editable)row.append(button('查看原文与纠错',()=>edit(record)));return row;
  }
  async function searchRelated(){
    const t=ticket();if(!current(t)||searching||busy)return;
    const query=searchText.value.trim();if(!query||query.length>200){searchStatus.textContent='请输入1至200字的关键词。';return;}
    const request=++searchEpoch;searching=true;controls();searchList.replaceChildren();searchStatus.textContent='正在检索已授权的记忆…';
    try{
      const data=await apiClient.json('GET','/chat/memory-search?session_id='+encodeURIComponent(t.session)+'&query='+encodeURIComponent(query)+'&include_roleplay='+String(searchFiction.checked));
      if(!current(t)||request!==searchEpoch)return;
      if(!Array.isArray(data.records)||data.query!==query)throw Error('服务器未返回可核对的检索结果。');
      for(const record of data.records)searchList.append(memoryCard(record));
      const shared=data.shared;
      if(shared?.sections?.length){const group=node('section');group.append(node('h3','已确认共享的另一端记忆（只读）'));for(const row of shared.sections)group.append(node('p',row.text),node('small',kind(row.evidence_kind)+' · '+(row.source||'原有来源')));searchList.append(group);}
      const sharedLabels={ready:'已读取已确认共享资料',not_bound:'没有已确认共享的另一端',sharing_disabled:'长期记忆共享已关闭',waiting_for_qq_persona:'另一端角色来源尚未恢复',waiting_for_real_source_message:'等待真实来源消息',material_changed:'资料有更新，请重新搜索',unavailable:'共享来源暂不可用'};
      searchStatus.textContent=(data.records.length?'找到 '+data.records.length+' 项相关记忆。':'没有匹配的当前记忆。')+(data.limited?' 已显示本次上限，缩小关键词可继续查找。':'')+(shared?' '+(sharedLabels[shared.state]||'共享资料状态：'+shared.state)+'。':'')+' 搜索不会更改记忆。';
    }catch(error){if(current(t)&&request===searchEpoch)searchStatus.textContent=errorText(error);}
    finally{if(current(t)&&request===searchEpoch){searching=false;controls();}}
  }
  function returnToRecords(){
    searchBox.hidden=false;if(messageId)return read();list.replaceChildren();say('');return searchRelated();
  }
  function render(){
    searchBox.hidden=false;list.replaceChildren();const data=snapshot;
    heading.textContent=(data.message.role==='user'?'你的消息':'伙伴的回复')+' · 记忆';
    const candidate=data.pending_candidate;
    if(candidate){const row=node('article');row.append(node('h3','这条消息的记忆候选'),node('p',candidate.original_text),node('small',kind(candidate.evidence_kind)+' · 修订 '+candidate.revision),
      node('p',candidate.status==='pending'?(data.important_saved?'候选状态仍待核对；下方已经存在真实长期记忆。':'待你确认，候选本身不会进入记忆检索或回复上下文。'):candidate.status==='confirmed'?'已明确确认长期保存。':'已放弃这个候选。'));list.append(row);}
    if(!data.records.length&&!data.candidates.length)list.append(node('p','没有找到与这条消息编号或已登记来源编号精确关联的记忆。'));
    for(const record of data.records)list.append(memoryCard(record));
    for(const row of data.candidates){const item=node('article');item.append(node('p',row.content),node('small','画像候选 · '+row.status+' · 审核 '+row.review_status),node('p',(row.source_texts||[]).join('\n')));list.append(item);}
    consent.checked=false;
    say(data.important_saved?'已存在重要记忆，当前状态：'+data.important_state+'。'
      :pending.has(pendingKey(ticket()))?'上次保存结果待核对。已回读当前记录；不会自动重复提交。'
      :candidate?.status==='pending'?'候选已保存，尚未写入长期记忆。核对原文后可明确确认。'
      :'已读取真实关联。加入候选不会自动写入长期记忆。');
    if(data.limited)list.append(node('p','本次关联达到显示上限；原始资料保留，可通过关键词进一步查找。'));controls();
  }
  async function read(){
    const t=ticket();if(!current(t)||busy)return;busy=true;controls();say('正在读取这条消息的真实记忆…');
    try{const data=await apiClient.json('GET',route(t));if(!current(t))return;
      if(String(data?.message?.message_id)!==t.messageId||!Array.isArray(data.records)||!Array.isArray(data.candidates))throw Error('服务器未返回可核对的消息关联。');
      snapshot=data;const operation=pending.get(pendingKey(t));
      if(operation&&(data.pending_candidate?.last_operation?.request_id===operation.request_id||operation.action==='confirm'&&data.important_saved||operation.action==='propose'&&['pending','confirmed'].includes(data.pending_candidate?.status)))pending.delete(pendingKey(t));render();
    }catch(error){if(current(t))say(errorText(error));}
    finally{if(current(t)){busy=false;controls();}}
  }
  async function write(action){
    const t=ticket();if(!current(t)||busy||!snapshot||pending.has(pendingKey(t))||action==='confirm'&&!consent.checked)return;
    const request_id='memory-'+(window.crypto?.randomUUID?window.crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));
    const body={session_id:t.session,message_id:t.messageId,action,request_id,expected_revision:snapshot.pending_candidate?.revision||0,...(action==='confirm'?{confirm:true}:{})};
    pending.set(pendingKey(t),{request_id,action});busy=true;controls();say(action==='propose'?'正在加入记忆候选…':action==='confirm'?'正在明确保存长期记忆…':'正在放弃这个候选…');
    try{const data=await apiClient.json('POST','/chat/message-memory',body);
      if(!data?.pending_candidate||action==='propose'&&data.pending_candidate.status!=='pending'||action==='reject'&&data.pending_candidate.status!=='rejected'||action==='confirm'&&(!data.saved_record?.id||data.important_saved!==true))throw Error('操作结果尚未确认，请重新读取。');pending.delete(pendingKey(t));
      if(current(t)){snapshot=data;render();say(action==='propose'?'已加入候选，尚未写入长期记忆。':action==='confirm'?'长期记忆已明确保存，可查看原文与纠错。':'已放弃候选，没有因此改写长期记忆。');}
    }catch(error){if([400,403,404,409].includes(error.status))pending.delete(pendingKey(t));if(current(t))say(errorText(error)+' 请重新读取核对。');}
    finally{if(current(t)){busy=false;consent.checked=false;controls();}}
  }
  async function edit(record){
    const t=ticket();if(!current(t)||busy)return;busy=true;controls();say('正在读取原生记忆的当前版本…');
    try{
      const data=await apiClient.json('GET','/chat/memory-detail?session_id='+encodeURIComponent(t.session)+'&id='+encodeURIComponent(record.id));
      if(!current(t))return;const saved=data.record;if(!saved?.editable||saved.id!==record.id||!Number.isInteger(saved.revision))throw Error('这项资料目前不能编辑。');
      searchBox.hidden=true;list.replaceChildren();list.append(node('h3','原文与纠错'),node('p',saved.content),node('small',kind(saved.evidence_kind)+' · 来源 '+saved.source_id+' · 修订 '+saved.revision));
      const history=node('details');history.append(node('summary','修订历史（'+data.history_total+'）'));
      for(const row of data.history||[])history.append(node('p','修订 '+row.revision+' · '+row.operation+'\n'+row.record.content));list.append(history);
      const draftKey=JSON.stringify([t.owner,saved.id]);
      const draft=node('textarea');draft.value=correctionDrafts.get(draftKey)??saved.content;draft.maxLength=6000;draft.rows=7;draft.setAttribute('aria-label','修正后的记忆内容');
      const check=node('input');check.type='checkbox';const label=node('label');label.append(check,node('span','我确认修正这项已保存的原生记忆'));
      const submit=button('保存纠错',async()=>{
        if(!current(t)||busy||!check.checked)return;const content=draft.value.trim();if(!content||content.length>6000){say('请填写1至6000字的内容。');return;}
        if(content===saved.content){say('内容未变化。');return;}correctionDrafts.set(draftKey,draft.value);busy=true;submit.disabled=true;controls();say('正在保存纠错…');
        try{const result=await apiClient.json('POST','/chat/memory-correct',{session_id:t.session,id:saved.id,content,expected_revision:saved.revision});
          if(!result?.record||result.record.content!==content||!(result.record.revision>saved.revision))throw Error('纠错结果待回读核对。');
          correctionDrafts.delete(draftKey);if(current(t)){busy=false;await returnToRecords();}
        }catch(error){if(current(t)){say(errorText(error)+' 编辑内容保留，请重新读取原文后比较。');submit.disabled=true;}}
        finally{if(current(t)){busy=false;controls();}}
      });submit.disabled=true;check.addEventListener('change',()=>{submit.disabled=!check.checked||busy;});
      draft.addEventListener('input',()=>{correctionDrafts.set(draftKey,draft.value);check.checked=false;submit.disabled=true;});
      list.append(draft,label,submit,button(messageId?'返回关联记忆':'返回检索结果',returnToRecords));say('原文和修订来自现有记忆库，纠错沿用版本检查。');
    }catch(error){if(current(t))say(errorText(error));}
    finally{if(current(t)){busy=false;controls();}}
  }
  function open(savedMessage){
    if(!state.authenticated||!state.activeId)return;
    const identity=savedMessage?.serverId??savedMessage?.message_id;
    if(!/^[1-9]\d*$/.test(String(identity||''))){showNotice('请先同步，消息保存后才能查看它的真实记忆。');return;}
    setup();close();owner=scope();session=state.activeId;messageId=String(identity);epoch++;heading.textContent='这条消息的记忆';searchBox.open=false;dialog.showModal();snapshot=null;controls();void read();
  }
  function openSearch(){
    if(!state.authenticated||!state.activeId)return;setup();close();owner=scope();session=state.activeId;messageId='';epoch++;heading.textContent='检索记忆与共同经历';searchBox.open=true;dialog.showModal();controls();say('输入关键词，查看当前可检索的记忆与已确认共享资料。');
  }
  return{open,openSearch,openMessageMemory:open,closeActive:()=>{if(!dialog?.open)return false;close();return true;},scopeChanged:()=>{if(owner&&(!state.authenticated||owner!==scope()))close();}};
})();
window.openMessageMemory=savedMessage=>window.ChatMessageMemory.open(savedMessage);
