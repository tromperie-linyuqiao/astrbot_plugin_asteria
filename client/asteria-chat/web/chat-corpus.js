'use strict';
/* User-maintained reference text and explicit preferences. No extra model call. */
window.ChatCorpus=(()=>{
  let dialog,list,form,note,refresh,save,closeButton,resolve,scope,snapshot=null,editing=null,busy=false,serial=0,persona='',expiryEdited=false;
  const controls={},unknown=new Map(),$=id=>document.getElementById(id);
  const el=(tag,value,cls='')=>{const n=document.createElement(tag);if(value!==undefined)n.textContent=value;n.className=cls;return n;};
  const button=(label,fn,cls='text-button')=>{const n=el('button',label,cls);n.type='button';n.onclick=fn;return n;};
  const owner=()=>JSON.stringify([scope.key(),persona]),current=t=>scope.current(t)&&persona===(state.sessionPersonaConfig?.configuredId||'');
  const requestId=()=>crypto.randomUUID?crypto.randomUUID():Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');
  const bodyLimit=()=>controls.kind.value==='preference'?1000:12000;
  const stamp=value=>typeof value==='number'&&Number.isFinite(value)?new Date(value*1000).toLocaleString('zh-CN',{hour12:false}):'未记录';
  function message(text){note.textContent=text;}
  function sync(){
    const limit=bodyLimit();controls.body.maxLength=limit;controls.body.parentElement.querySelector('span').textContent='正文（最多 '+limit+' 字符）';
    const blocked=unknown.get(owner());refresh.disabled=busy;resolve.hidden=!blocked?.read;resolve.disabled=busy;
    for(const n of form.querySelectorAll('input,textarea,select,button'))n.disabled=busy;
    for(const n of list.querySelectorAll('button'))n.disabled=busy;
    controls.kind.disabled=busy||!!editing;
    controls.lifetime.disabled=busy||controls.kind.value==='sample';controls.hours.disabled=busy||controls.lifetime.value!=='temporary';
    save.disabled=busy||!snapshot||!!blocked;save.textContent=editing?'保存修订':'保存新条目';
  }
  function clearEditor(){editing=null;expiryEdited=false;controls.title.value=controls.body.value=controls.tags.value=controls.source.value='';controls.kind.value='sample';controls.lifetime.value='persistent';controls.hours.value='24';controls.enabled.checked=true;sync();}
  function edit(item){editing=structuredClone(item);expiryEdited=false;for(const key of ['title','body','source'])controls[key].value=item[key]||'';controls.tags.value=(item.tags||[]).join('、');controls.kind.value=item.kind;controls.lifetime.value=item.lifetime;controls.enabled.checked=item.enabled!==false;controls.hours.value=String(Math.min(168,Math.max(1,Math.ceil(((item.expires_at||Date.now()/1000+86400)-Date.now()/1000)/3600))));sync();controls.body.focus();}
  function render(){
    list.replaceChildren();for(const item of snapshot?.items||[]){
      const row=el('article',undefined,'corpus-row');row.dataset.corpusId=item.id;
      row.append(el('strong',item.title||String(item.body||'').slice(0,36)),el('small',(item.kind==='preference'?'明确偏好':'参考语料')+' · '+({persistent:'长期',session:'当前会话',temporary:'临时'}[item.lifetime]||'范围待核对')+' · '+(item.enabled===false?'已停用':item.eligible===false?'当前不适用':'已启用')+' · 修订 '+item.revision));
      row.append(el('p',item.body,'corpus-preview'));if(item.expires_at)row.append(el('small','有效期至 '+stamp(item.expires_at)));if(item.source)row.append(el('small','来源：'+item.source));
      row.append(button('查看与修改',()=>edit(item)));
      if(Array.isArray(item.history)&&item.history.length){const history=el('details');history.append(el('summary','最近修订摘要（'+item.history.length+'）'));for(const old of item.history)history.append(el('p','修订 '+(old.revision??'未提供')+' · '+(old.body||old.title||'条目状态变更')));row.append(history);}list.append(row);
    }if(!list.children.length)list.append(el('p','当前角色还没有保存的语料或偏好。','corpus-empty'));sync();
  }
  function valid(data,t){if(!data||data.session_id!==t.session||typeof data.persona_id!=='string')throw Error('资料范围未确认，已保留输入。');if(persona&&data.persona_id!==persona)throw Error('角色范围已变化，请重新打开。');return data;}
  async function read(){
    const t=scope.ticket();if(!current(t)||busy)return;const id=++serial;busy=true;sync();message('正在读取当前角色的资料…');
    try{await scope.settlePrevious(t);if(!current(t)||id!==serial)return;const data=valid(await apiClient.json('GET','/chat/corpus?session_id='+encodeURIComponent(t.session)),t);if(!current(t)||id!==serial)return;
      if(!Array.isArray(data.items)||data.items.some(x=>!x||typeof x.id!=='string'||!Number.isInteger(x.revision)||typeof x.body!=='string'))throw Error('服务器没有返回完整的资料列表。');snapshot=data;render();const blocked=unknown.get(owner());if(blocked){if(blocked.draft&&!controls.body.value){edit(blocked.draft);if(!blocked.draft.id)editing=null;}blocked.read=true;message('已读取当前版本；这不证明上次保存成功。核对列表后可结束等待，原输入保留。');}else message('语料供正常回复参考；偏好按所选范围生效。查看不会调用模型。');
    }catch(error){if(current(t)&&id===serial)message(error.status===404?'此服务器尚未提供语料与偏好管理。':errorText(error));}
    finally{if(current(t)&&id===serial){busy=false;sync();}}
  }
  async function submit(event){
    event.preventDefault();const t=scope.ticket();if(!current(t)||busy||!snapshot||unknown.has(owner()))return;
    const body=controls.body.value.trim();if(!body||body.length>bodyLimit()){message('正文需要 1–'+bodyLimit()+' 个字符，当前输入保留。');return;}
    const record={kind:controls.kind.value,body,title:controls.title.value.trim(),source:controls.source.value.trim(),tags:controls.tags.value.split(/[,，、\n]/).map(s=>s.trim()).filter(Boolean),enabled:controls.enabled.checked,lifetime:controls.kind.value==='sample'?'persistent':controls.lifetime.value};
    if(record.tags.length>8||record.tags.some(tag=>tag.length>24)){message('标签最多 8 个，每个最多 24 字符；请整理后保存。');return;}
    if(record.lifetime==='temporary'){const hours=Number(controls.hours.value);if(!Number.isFinite(hours)||hours<1||hours>168){message('临时偏好请选择 1–168 小时。');return;}record.expires_at=editing?.lifetime==='temporary'&&!expiryEdited?editing.expires_at:Math.floor(Date.now()/1000+hours*3600);}else record.expires_at=null;
    const request={session_id:t.session,op:'save',id:editing?.id||null,expected_revision:editing?.revision||0,request_id:requestId(),record};
    const corpusOwner=owner(),id=++serial;busy=true;sync();message('正在保存…');const promise=apiClient.json('POST','/chat/corpus',request);scope.track(t,promise);
    try{const data=await promise;if(!current(t)||id!==serial)return;valid(data,t);const item=data.item;
      if(!item||typeof item.id!=='string'||request.id&&item.id!==request.id||!Number.isInteger(item.revision)||item.revision<=request.expected_revision||item.body!==record.body||item.kind!==record.kind||item.lifetime!==record.lifetime||item.enabled!==record.enabled)throw Error('服务器未确认本次修订。');
      snapshot.items=[item,...snapshot.items.filter(x=>x.id!==item.id)];editing=structuredClone(item);expiryEdited=false;render();message('已保存修订 '+item.revision+'。'+(record.enabled?'语料仍由回复模型按语境选用。':'此条目已停用，修订历史保留。'));
    }catch(error){const rejected=[400,401,403,409,422].includes(error.status);if(!rejected)unknown.set(corpusOwner,{request_id:request.request_id,read:false,draft:{...record,id:request.id,revision:request.expected_revision}});if(current(t)&&id===serial){message(rejected?errorText(error)+' 输入保留；请重新读取并选择当前版本后再修改。':'保存结果尚未确认，输入保留。请重新读取核对；不会自动再次提交。');}}
    finally{scope.release(t,promise);if(current(t)&&id===serial){busy=false;sync();}}
  }
  function close(){if(!dialog?.open)return;dialog.close();scope.invalidate();serial++;busy=false;snapshot=editing=null;list.replaceChildren();controls.body.value='';}
  function setup(){
    if(dialog)return;dialog=el('dialog',undefined,'settings-dialog corpus-dialog');dialog.id='corpus-dialog';dialog.setAttribute('aria-labelledby','corpus-title');
    const shell=el('div',undefined,'settings-form'),heading=el('div',undefined,'dialog-heading'),title=el('h2','语料与偏好');title.id='corpus-title';closeButton=button('关闭',close);heading.append(title,closeButton);
    shell.append(heading,el('p','提供少量合适的参考，让角色按当前语境自然表达。临时偏好到期后不再参与；参考文本不会变成用户事实。','appearance-help'));
    list=el('section',undefined,'corpus-list');list.id='corpus-list';form=el('form',undefined,'corpus-editor');form.id='corpus-form';
    function field(key,label,type='input'){const wrap=el('label'),n=el(type);n.id='corpus-'+key;controls[key]=n;wrap.append(el('span',label),n);form.append(wrap);return n;}
    function options(n,values){for(const [id,label]of values){const o=el('option',label);o.value=id;n.append(o);}}
    options(field('kind','内容类型','select'),[['sample','参考语料'],['preference','明确偏好']]);field('title','标题（可留空）').maxLength=80;
    field('body','正文','textarea').maxLength=12000;controls.body.rows=5;controls.body.required=true;
    const file=field('file','导入 TXT（先预览，再保存）');file.type='file';file.accept='.txt,text/plain';file.onchange=async()=>{const chosen=file.files?.[0],t=scope.ticket();if(!chosen||busy)return;try{if(chosen.size>64*1024)throw Error('请选择不超过 64 KiB 的文本文件。');const text=await chosen.text();if(!current(t))return;if(text.length>bodyLimit())throw Error('当前内容类型最多 '+bodyLimit()+' 字符，请先整理文本再导入。');controls.body.value=text;message('文本已加入编辑框，尚未保存。');}catch(error){if(current(t))message(error.message);}finally{file.value='';}};
    field('tags','场景标签（最多 8 个，每个 24 字符，用顿号分隔）').maxLength=240;field('source','来源说明（可留空）').maxLength=240;
    options(field('lifetime','适用时间','select'),[['persistent','长期'],['session','当前会话'],['temporary','临时有效']]);const hours=field('hours','临时有效小时数');hours.type='number';hours.min=1;hours.max=168;
    const enabled=field('enabled','启用这条资料');enabled.type='checkbox';
    controls.kind.onchange=()=>{controls.lifetime.value=controls.kind.value==='sample'?'persistent':'session';sync();};controls.lifetime.onchange=()=>{expiryEdited=true;sync();};controls.hours.oninput=()=>{expiryEdited=true;};
    const extra=el('details',undefined,'corpus-optional'),extraFields=el('div',undefined,'corpus-optional-fields');extra.append(el('summary','标题、标签与来源（可选）'),extraFields);for(const key of ['title','tags','source'])extraFields.append(controls[key].parentElement);form.insertBefore(extra,controls.lifetime.parentElement);
    const actions=el('div',undefined,'experience-actions');save=el('button','保存新条目','primary-button');save.type='submit';actions.append(save,button('新建条目',()=>{clearEditor();message('正在编辑新条目，尚未保存。');},'secondary-button'));form.append(actions);form.onsubmit=submit;
    refresh=button('重新读取',read);resolve=button('已核对，结束等待',()=>{if(!unknown.get(owner())?.read||busy)return;unknown.delete(owner());message('已结束等待；重新选择条目或新建后可保存。不据此判定上次操作结果。');snapshot=null;clearEditor();void read();});resolve.hidden=true;
    note=el('p','','corpus-note');note.setAttribute('role','status');note.setAttribute('aria-live','polite');shell.append(list,form,refresh,resolve,note);dialog.append(shell);document.body.append(dialog);
    scope=ChatSessionScope.create(()=>state,()=>dialog.open);dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.addEventListener('close',()=>{if(!dialog.open)scope.invalidate();});
  }
  async function open(){if(!state.authenticated||!state.activeId){showNotice('请先打开当前账号的聊天。');return;}setup();hideMoreMenu();window.ChatSettingsHub?.close();close();dialog.showModal();scope.enter();persona=state.sessionPersonaConfig?.configuredId||'';snapshot=null;clearEditor();const blocked=unknown.get(owner());if(blocked?.draft){edit(blocked.draft);if(!blocked.draft.id)editing=null;}await read();}
  function scopeChanged(){if(dialog?.open&&!current(scope.ticket()))close();}
  document.addEventListener('DOMContentLoaded',()=>{const entry=button('语料与偏好',open,'menu-item');entry.id='menu-corpus';$('more-menu')?.append(entry);const original=renderChrome;renderChrome=function(){const result=original.apply(this,arguments);scopeChanged();return result;};},{once:true});
  return {open,closeActive:close,scopeChanged};
})();
