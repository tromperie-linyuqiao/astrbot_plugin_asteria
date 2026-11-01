'use strict';
/* Image follow-ups use the existing TLS image service and saved chat history.
   This view never creates an image message or retries an uncertain paid call. */
window.ChatImageJobs = (() => {
  const labels={pending:'等待生成',generating:'正在生成',submitting:'正在准备图片',dispatching:'正在保存到会话',queued:'等待原消息通道',stored:'服务器已保存',blocked:'当前暂不可生成',definite_failure:'本次生成未成功',unknown:'结果待核对',failed:'发送未完成'};
  const reasons={accepted:'已接收图片请求',provider_submission:'原图片服务正在处理',image_prepared:'图片已准备，等待保存',sdk_history_write_started:'正在保存到当前会话',sdk_history_saved:'图片已保存到服务器聊天记录',original_history_reconciled:'已从原聊天记录核实保存',image_backend_not_configured:'服务器尚未配置图片服务',image_scope_not_authorized:'当前会话尚未获图片权限',configured_image_budget_exhausted:'已达到当前图片预算',image_job_busy:'已有图片正在处理',original_share_authority_changed:'原生活分享权限已改变',provider_outcome_unknown:'图片服务结果不确定，不能重复生成',authorization_changed_after_generation:'生成后权限改变，需核对原结果',authorization_changed_before_storage:'保存前权限改变，需核对原结果',sdk_history_outcome_unknown:'聊天保存结果不确定，请先核对',job_interrupted:'处理曾中断，请核对原任务',image_followup_unconfirmed:'图片结果尚未确认',interrupted_original_requires_review:'原任务中断，需要人工核对',image_not_generated:'图片服务未生成图片'};
  const purposes={chat:'聊天配图',life:'虚构生活画面',roleplay:'RP 场景'};
  const activeStates=new Set(['pending','generating','submitting','dispatching','queued']);
  const AUTO_INTERVAL=5000,AUTO_LIMIT=30,AUTO_WINDOW=180000;
  let dialog,prompt,purpose,parent,list,status,submit,refreshButton,config,closeButton,launcher,launcherStatus;
  let owner='',ownerAuth=null,session='',epoch=0,readSerial=0,reading=false,writing=false,snapshot=null,error='',readAt=0,lastAuto=0;
  let selectedParent='',pending=null,disposed=false;
  let autoTimer=0,autoReads=0,autoErrors=0,autoStarted=0,autoBlocked='',nativeRead=null,queuedRead=null;
  let renderedParents='',renderedJobs='';
  const get=id=>document.getElementById(id);
  const scope=()=>state.authenticated&&state.server&&state.username&&state.activeId?JSON.stringify([state.server,state.username,state.activeId]):'';
  const auth=()=>typeof chatAuthEpoch==='number'?chatAuthEpoch:null;
  const online=()=>navigator.onLine!==false;
  const foreground=()=>!document.hidden&&(typeof recoveryForeground!=='function'||recoveryForeground());
  const current=t=>!disposed&&!!owner&&state.authenticated&&t.owner===scope()&&t.owner===owner&&t.auth===auth()&&t.auth===ownerAuth&&t.epoch===epoch;
  const ticket=()=>({owner,auth:ownerAuth,epoch,session});
  const node=(tag,text,cls='')=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;value.className=cls;return value;};
  const button=(text,fn,cls='text-button')=>{const value=node('button',text,cls);value.type='button';value.addEventListener('click',fn);return value;};
  const plain=(value,max=300)=>typeof value==='string'?value.replace(/[\u0000-\u001f]/g,' ').slice(0,max):'';
  const decimal=value=>typeof value==='string'&&/^\d{1,24}$/.test(value);
  const key=()=>pref('image-request.'+encodeURIComponent(owner));
  const draftKey=()=>pref('image-draft.'+encodeURIComponent(owner));
  const storedRows=()=>state.messages.filter(value=>value.delivery==='confirmed'&&decimal(String(value.serverId??'')));
  function savedParent(id){return storedRows().find(value=>String(value.serverId)===id);}
  function savePending(value){pending=value;try{value?localStorage.setItem(key(),JSON.stringify(value)):localStorage.removeItem(key());}catch(_){}controls();}
  function restorePending(){pending=null;try{const raw=localStorage.getItem(key())||'';if(raw.length>2048)return;const value=JSON.parse(raw||'null');if(value&&/^[A-Za-z0-9_.:-]{8,128}$/.test(value.request_id||''))pending=value;}catch(_){} }
  function saveImageDraft(){
    if(!owner||!prompt)return;
    try{prompt.value?localStorage.setItem(draftKey(),JSON.stringify({prompt:prompt.value.slice(0,1200),purpose:purpose.value,parent_message_id:selectedParent})):localStorage.removeItem(draftKey());}catch(_){}
  }
  function restoreImageDraft(){
    if(!prompt)return;prompt.value='';purpose.value='chat';
    try{const raw=localStorage.getItem(draftKey())||'';if(raw.length>8192)return;const value=JSON.parse(raw||'null');
      if(value&&typeof value.prompt==='string'){prompt.value=value.prompt.slice(0,1200);purpose.value=Object.hasOwn(purposes,value.purpose)?value.purpose:'chat';if(decimal(value.parent_message_id))selectedParent=value.parent_message_id;}}
    catch(_){}
  }
  function stopAuto(){clearTimeout(autoTimer);autoTimer=0;}
  function resetAuto(){stopAuto();autoReads=autoErrors=0;autoStarted=Date.now();autoBlocked='';}
  const visible=()=>!disposed&&dialog?.open&&!!owner&&scope()===owner&&ownerAuth===auth()&&foreground()&&online();
  const progressing=()=>!!pending||(snapshot?.jobs||[]).some(job=>activeStates.has(job.state)||(job.state==='stored'&&!job.message_id));
  function scheduleAuto(){
    if(!visible()||!progressing()||reading||writing||nativeRead||autoBlocked){stopAuto();return;}
    if(autoReads>=AUTO_LIMIT||Date.now()-autoStarted>=AUTO_WINDOW){stopAuto();autoBlocked='budget';render();return;}
    if(autoTimer)return;
    autoTimer=setTimeout(()=>{autoTimer=0;if(visible())void read();},Math.min(30000,AUTO_INTERVAL*2**autoErrors));
  }
  function releaseRead(io){
    if(nativeRead!==io)return;nativeRead=null;
    const queued=queuedRead;queuedRead=null;render();
    if(queued&&current(queued)&&visible())void read({manual:true});else scheduleAuto();
  }
  function cleanJob(value){
    if(!value||typeof value!=='object'||!/^[a-f0-9]{64}$/.test(value.id||'')||!Object.hasOwn(labels,value.state)||value.authority!=='server_job_state')return null;
    return {...value,parent_message_id:decimal(String(value.parent_message_id??''))?String(value.parent_message_id):'',message_id:decimal(String(value.message_id??''))?String(value.message_id):null};
  }
  function mount(){
    if(dialog)return;
    dialog=node('dialog',undefined,'settings-dialog image-jobs-dialog');dialog.id='image-jobs-dialog';dialog.setAttribute('aria-labelledby','image-jobs-title');
    const body=node('div',undefined,'settings-form'),heading=node('div',undefined,'dialog-heading');heading.append(node('h2','生成图片','image-jobs-title'));heading.firstChild.id='image-jobs-title';closeButton=button('×',close,'icon-button');closeButton.setAttribute('aria-label','关闭图片任务');heading.append(closeButton);body.append(heading);
    body.append(node('p','文字照常聊天。图片由 TLS 原图片服务单独处理，完成后出现在这段对话里。','image-jobs-intro'));
    const form=node('form',undefined,'image-request-form');form.id='image-request-form';
    prompt=node('textarea');prompt.id='image-request-prompt';prompt.rows=3;prompt.maxLength=1200;prompt.placeholder='描述想看的画面、神态或场景…';prompt.setAttribute('aria-label','想生成的图片');
    const purposeLabel=node('label','画面用途');purpose=node('select');purpose.id='image-request-purpose';for(const[value,label]of Object.entries(purposes)){const option=node('option',label);option.value=value;purpose.append(option);}purposeLabel.append(purpose);
    const parentLabel=node('label','接在哪条消息之后');parent=node('select');parent.id='image-request-parent';parentLabel.append(parent);parent.onchange=()=>{selectedParent=parent.value;saveImageDraft();controls();};
    config=node('p',undefined,'image-job-config');config.id='image-job-config';submit=node('button','提交图片请求','primary-button');submit.type='submit';submit.id='image-request-submit';
    form.append(prompt,purposeLabel,parentLabel,config,submit);form.addEventListener('submit',event=>{event.preventDefault();void create();});prompt.addEventListener('input',()=>{saveImageDraft();controls();});purpose.addEventListener('change',saveImageDraft);body.append(form);
    const section=node('section',undefined,'image-job-section'),toolbar=node('div',undefined,'image-job-toolbar');toolbar.append(node('h3','图片任务'));refreshButton=button('核对任务',()=>read({manual:true}));refreshButton.id='image-jobs-refresh';toolbar.append(refreshButton);section.append(toolbar);
    status=node('p',undefined,'image-jobs-status');status.id='image-jobs-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');list=node('div',undefined,'image-job-list');list.id='image-job-list';section.append(status,list);body.append(section);dialog.append(body);document.body.append(dialog);
    dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.addEventListener('close',()=>{if(dialog.open)return;stopAuto();queuedRead=null;saveImageDraft();});dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)close();});
    const pane=document.querySelector('[data-compose-pane="attachments"]');
    if(pane){const wrap=node('div',undefined,'image-job-entry');launcher=button('生成图片',()=>open(),'attachment-picker');launcher.id='compose-generate-image';launcher.append(node('small','描述画面，文字不用等图片'));launcherStatus=node('p',undefined,'compose-status');launcherStatus.id='compose-image-job-status';wrap.append(launcher,launcherStatus);pane.append(wrap);}
  }
  function renderParents(){
    if(!parent)return;
    const rows=storedRows().slice(-80).reverse();if(!rows.some(value=>String(value.serverId)===selectedParent))selectedParent=rows[0]?String(rows[0].serverId):'';
    const options=rows.map(message=>[String(message.serverId),(message.role==='user'?'你':'伙伴')+'：'+plain(message.text||message.parts?.map(p=>p.label||p.filename||p.type).join(' · ')||'媒体消息',46)]),signature=JSON.stringify(options);
    if(signature!==renderedParents){renderedParents=signature;parent.replaceChildren();for(const [id,text]of options){const option=node('option',text);option.value=id;parent.append(option);}
      if(!rows.length){const option=node('option','先发送或同步一条聊天记录');option.value='';parent.append(option);}}
    if(parent.value!==selectedParent)parent.value=selectedParent;
  }
  function controls(){
    if(!dialog)return;
    const valid=!!owner&&scope()===owner&&online()&&foreground()&&!disposed,locked=writing||!!pending;
    submit.disabled=!valid||locked||!savedParent(selectedParent)||!prompt.value.trim()||!snapshot||snapshot.status.available!==true||snapshot.status.authorized===false;
    submit.textContent=writing?'正在提交…':pending?'先核对上次图片请求':'提交图片请求';
    prompt.disabled=purpose.disabled=parent.disabled=writing;
    refreshButton.disabled=!valid||reading||writing||!!nativeRead;
    if(launcher)launcher.disabled=!owner;
  }
  function reason(job){const code=plain(job.reason,120);return reasons[code]||(code==='provider_rejected'?'图片服务明确拒绝了这次请求':/^native_delivery_/.test(code)?'沿用原消息通道：'+code.slice(16):code?'原图片服务：'+code:'等待服务器更新');}
  function render(){
    if(!dialog)return;renderParents();const info=snapshot?.status;
    config.textContent=!info?'打开后读取服务器图片配置。':info.available!==true?'服务器图片服务目前未接通。':(info.authorized===false?'当前会话尚未获得图片权限。 ':'')+'尺寸由服务器统一配置：'+(plain(info.size,40)||'当前未返回')+'；此处不另设尺寸。'+(info.reference_configured?' 已配置角色参考图。':'')+(Number.isInteger(info.configured_daily_limit)?' 原图片日额度：'+info.configured_daily_limit+'。':'');
    const jobs=snapshot?.jobs||[],signature=JSON.stringify([jobs,jobs.map(job=>[savedParent(job.parent_message_id)?.text||'',state.messages.some(value=>value.delivery==='confirmed'&&String(value.serverId)===job.message_id)]),!snapshot&&reading,writing,!!pending,online()]);
    if(signature!==renderedJobs){renderedJobs=signature;list.replaceChildren();
    for(const job of jobs){
      const card=node('article',undefined,'image-job-card');card.dataset.jobId=job.id;card.dataset.state=job.state;
      const top=node('div',undefined,'image-job-heading');top.append(node('strong',purposes[job.purpose]||'图片'),node('span',labels[job.state],'image-job-state'));card.append(top,node('p',reason(job),'image-job-reason'));
      if(job.updated_at){const date=new Date(Number(job.updated_at)*1000);if(Number.isFinite(date.getTime()))card.append(node('small','更新于 '+date.toLocaleString('zh-CN',{hour12:false})));}
      const parentMessage=savedParent(job.parent_message_id);if(parentMessage)card.append(node('p','接在'+(parentMessage.role==='user'?'你的':'伙伴的')+'消息之后：'+plain(parentMessage.text||'媒体消息',90),'image-job-parent'));
      else if(job.parent_message_id)card.append(node('p','关联原消息 #'+job.parent_message_id+'（当前未加载）','image-job-parent'));
      if(job.state==='stored'){
        const loaded=state.messages.some(value=>value.delivery==='confirmed'&&String(value.serverId)===job.message_id);
        if(job.message_id){card.append(node('p',loaded?'已同步到本机聊天记录，可沿原图片卡片预览或下载。':'服务器已保存；同步聊天后可预览或下载。','image-job-reason'));
          const open=button(loaded?'在聊天中查看':'同步并查看图片',()=>view(job));open.dataset.messageId=job.message_id;open.title='打开服务器已保存的消息 #'+job.message_id;card.append(open);}
        else card.append(node('p','服务器标记已保存，但未返回聊天消息编号。请先核对任务；这里不会创建替代图片或猜测消息位置。','image-job-warning'));
      }else if(job.state==='unknown')card.append(node('p','生成或保存结果尚未确认。只核对原任务，不会重新付费生成。','image-job-warning'));
      else if(job.can_retry===true&&['definite_failure','blocked'].includes(job.state)&&job.source==='user_request'){
        const retry=button('重新请求这张图片',()=>confirmRetry(job));retry.disabled=writing||!!pending||!online();card.append(retry);
      }
      list.append(card);
    }
    if(!jobs.length)list.append(node('p',reading?'正在读取…':snapshot?'当前读取范围内还没有图片任务。':'尚未读取图片任务。','image-job-empty'));
    }
    if(nativeRead?.unknown)status.textContent='上次核对等待超时，本机仍在等待原网络读取结束；不会叠加新请求。结束后请点“核对任务”。';
    else if(!online())status.textContent='当前离线，自动核对已暂停。图片任务仍由服务器处理，联网后继续读取原任务。';
    else if(autoBlocked==='timeout')status.textContent='上次核对超时，原网络读取已结束。请点“核对任务”继续；不会重新生成。';
    else if(autoBlocked==='errors')status.textContent='连续核对未成功，已暂停自动读取。请点“核对任务”重连；原图片请求不会重发。';
    else if(autoBlocked==='budget')status.textContent='本次自动核对已达到30次或3分钟发起预算。可点“核对任务”继续，原任务不会重新生成。';
    else if(pending)status.textContent='上次图片提交结果待核对；仅读取同一个原请求，不会重复生成。';
    else if(error)status.textContent=error;
    else status.textContent=reading&&!snapshot?'正在核对服务器任务…':progressing()?'正在跟进图片任务；面板打开时每5秒核对，离开或进入后台即暂停。':readAt?'已从服务器读取 '+jobs.length+' 项任务；保存、客户端下载与系统通知分别确认。':'图片生成不会阻塞当前聊天。';
    status.dataset.mode=autoBlocked||nativeRead?.unknown||error||!online()?'paused':progressing()?'tracking':'idle';
    const active=jobs.filter(job=>activeStates.has(job.state)).length,unknown=jobs.filter(job=>job.state==='unknown').length;
    if(launcherStatus)launcherStatus.textContent=pending?'上次请求待核对':active?active+' 张图片正在处理，文字可照常发送':unknown?unknown+' 项结果待核对':jobs[0]?.state==='stored'?'最近图片已保存到聊天记录':'';
    controls();
  }
  function scopeChanged(){
    const next=scope(),nextAuth=auth();if(next===owner&&nextAuth===ownerAuth){controls();return;}
    saveImageDraft();stopAuto();queuedRead=null;if(dialog?.open)dialog.close();
    epoch++;readSerial++;owner=next;ownerAuth=nextAuth;session=state.activeId||'';reading=writing=false;snapshot=null;error='';readAt=lastAuto=0;selectedParent='';pending=null;renderedParents=renderedJobs='';resetAuto();
    if(dialog){prompt.value='';purpose.value='chat';list.replaceChildren();}if(owner){restorePending();restoreImageDraft();}render();
  }
  async function read({manual=false}={}){
    scopeChanged();if(!visible()||reading||writing)return false;
    if(nativeRead){if(manual)queuedRead=ticket();render();return false;}
    if(manual)resetAuto();
    else if(autoBlocked||autoReads>=AUTO_LIMIT||Date.now()-autoStarted>=AUTO_WINDOW){if(!autoBlocked)autoBlocked='budget';render();return false;}
    if(!manual&&(!foreground()||Date.now()-lastAuto<3000)){scheduleAuto();return false;}
    stopAuto();const t=ticket(),serial=++readSerial,io={nativeDone:false,settled:false,unknown:false},base=new Map((snapshot?.jobs||[]).map(job=>[job.id,Number(job.revision)]));nativeRead=io;
    reading=true;if(!manual){lastAuto=Date.now();autoReads++;}error='';render();
    try{
      const value=await apiClient.json('GET','/chat/image-jobs?session_id='+encodeURIComponent(t.session)+(pending?'&request_id='+encodeURIComponent(pending.request_id):''),undefined,
        {accept:()=>current(t),onNativeComplete:()=>{io.nativeDone=true;if(io.settled)releaseRead(io);}});
      if(!current(t)||serial!==readSerial)return false;
      if(!value||!value.status||typeof value.status!=='object'||Array.isArray(value.status)||!Array.isArray(value.jobs))throw Error('图片任务格式暂不兼容，请更新服务器。');
      const fetched=value.jobs.map(cleanJob).filter(Boolean).slice(0,50),previous=new Map((snapshot?.jobs||[]).map(job=>[job.id,job])),ids=new Set(fetched.map(job=>job.id));
      snapshot={status:value.status,jobs:[...previous.values()].filter(job=>!ids.has(job.id)&&(!base.has(job.id)||Number(job.revision)>base.get(job.id)))};
      for(const job of fetched){const newer=previous.get(job.id);merge(newer&&Number(newer.revision)>Number(job.revision)?newer:job);}
      const lookup=value.request_lookup;
      if(pending&&lookup?.request_id===pending.request_id&&lookup.found===true){const job=cleanJob(lookup.job);const accepted=Number.isInteger(lookup.matched_attempt)&&lookup.matched_attempt>0&&Number.isInteger(job?.attempt)&&lookup.matched_attempt<=job.attempt;if(job&&(job.request_id===pending.request_id||accepted)){savePending(null);merge(job);}}
      readAt=Date.now();autoErrors=0;return true;
    }catch(failure){
      if(failure?.nativeCompletionUnknown===true)io.unknown=true;
      if(io.unknown&&t.owner===owner&&t.owner===scope()&&t.auth===auth()&&t.epoch===epoch)autoBlocked='timeout';
      if(current(t)&&serial===readSerial){error=errorText(failure)+' 仅核对原任务，不会自动提交。';autoErrors++;
        if(io.unknown)autoBlocked='timeout';else if(autoErrors>=3||[401,403].includes(failure?.status))autoBlocked='errors';}
      return false;
    }finally{io.settled=true;if(nativeRead===io)reading=false;if(current(t)&&serial===readSerial)render();
      if(!io.unknown||io.nativeDone)releaseRead(io);}
  }
  function merge(job){
    if(!snapshot)snapshot={status:{available:false},jobs:[]};const old=snapshot.jobs.find(value=>value.id===job.id);if(old&&Number(old.revision)>Number(job.revision))return;
    snapshot.jobs=[job,...snapshot.jobs.filter(value=>value.id!==job.id)].sort((a,b)=>Number(b.updated_at)-Number(a.updated_at)).slice(0,50);
  }
  async function post(body){
    const t=ticket();if(!current(t)||writing||pending||!online())return;
    resetAuto();saveImageDraft();
    const requestId='tc-image-'+(window.crypto?.randomUUID?window.crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));
    const marker={request_id:requestId,submitted_at:Date.now(),...(body.retry_job_id?{retry_job_id:body.retry_job_id}:{parent_message_id:body.parent_message_id})};
    savePending(marker);writing=true;error='';render();
    try{
      const value=await apiClient.json('POST','/chat/image-jobs',{session_id:t.session,request_id:requestId,...body});
      if(!current(t))return;const job=cleanJob(value);if(!job||job.request_id!==requestId)throw Error('服务器尚未确认这次图片请求，请核对原任务。');
      savePending(null);merge(job);error='';
      if(!body.retry_job_id){prompt.value='';saveImageDraft();}
    }catch(failure){
      if(!current(t))return;
      if([400,401,403,404,409,422].includes(failure?.status)){savePending(null);error=errorText(failure)+' 本次请求被拒绝。';}
      else error=errorText(failure)+' 提交结果不确定，请仅核对原请求。';
    }finally{if(current(t)){writing=false;render();scheduleAuto();}}
  }
  async function create(){
    if(submit.disabled)return;const text=prompt.value.trim();if(!text||[...text].length>1200||!savedParent(selectedParent))return;
    await post({prompt:text,purpose:purpose.value,parent_message_id:selectedParent});
  }
  function confirmRetry(job){
    if(writing||pending||!['definite_failure','blocked'].includes(job.state)||job.can_retry!==true||job.source!=='user_request')return;
    const card=list.querySelector('[data-job-id="'+job.id+'"]');if(!card||card.querySelector('.image-retry-confirm'))return;
    const box=node('div',undefined,'image-retry-confirm');box.append(node('p','再次请求可能产生新的图片费用。是否用原画面说明重试？'));
    box.append(button('取消',()=>box.remove()),button('确认重新生成',async()=>{box.remove();await post({retry_job_id:job.id,expected_revision:job.revision});},'primary-button'));card.append(box);
  }
  async function view(job){
    if(!job.message_id)return;const t=ticket();close();
    if(!current(t))return;const result=await window.ChatMessageNavigation?.open(job.message_id);
    if(!result?.opened&&current(t))showNotice(result?.reason||'请同步当前聊天记录，再打开原图片卡片。',null,true);
  }
  function close(){stopAuto();queuedRead=null;saveImageDraft();if(dialog?.open)dialog.close();}
  function open(parentId){
    mount();scopeChanged();if(!owner){showNotice('请先打开自己的聊天会话。');return;}
    hideMoreMenu();window.ChatComposer?.closePanel();if(decimal(String(parentId??''))&&savedParent(String(parentId)))selectedParent=String(parentId);
    render();if(!dialog.open)dialog.showModal();void read({manual:true});
  }
  function streamEvent(value){
    scopeChanged();if(!owner)return;const job=cleanJob(value);if(!job)return;merge(job);
    if(pending&&job.request_id===pending.request_id)savePending(null);render();scheduleAuto();
  }
  function historyReceived(id){
    scopeChanged();if(!owner||id!==session)return;render();
    scheduleAuto();
  }
  function foregroundChanged(){scopeChanged();stopAuto();if(!visible()){queuedRead=null;render();return;}void read();}
  function renderAssociation(value){
    const label=button('生成图片 · '+(purposes[value.purpose]||'聊天配图'),()=>open(value.parent_message_id),'image-message-association');
    label.title='查看这张图片的原任务与关联消息';return label;
  }
  document.addEventListener('DOMContentLoaded',()=>{mount();scopeChanged();},{once:true});
  window.addEventListener('online',foregroundChanged);window.addEventListener('offline',foregroundChanged);document.addEventListener('visibilitychange',foregroundChanged);
  window.addEventListener('pagehide',()=>{saveImageDraft();disposed=true;stopAuto();close();});window.addEventListener('pageshow',()=>{disposed=false;foregroundChanged();});
  return {open,read,historyReceived,streamEvent,foregroundChanged,scopeChanged,renderAssociation,closeActive:()=>{if(!dialog?.open)return false;close();return true;}};
})();
