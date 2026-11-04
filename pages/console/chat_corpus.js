/* Existing account-owned Chat corpus, reached through the authenticated page bridge. */
(function(global){
 'use strict';
 const root=document.getElementById('chat-corpus-mount');if(!root)return;
 const node=(tag,text,cls='')=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;n.className=cls;return n;};
 const button=(text,fn)=>{const n=node('button',text);n.type='button';n.onclick=fn;return n;};
 const fields={},unknown=new Map();let rows=[],selected=null,persona='',snapshot=null,editing=null,busy=false,epoch=0,expiryEdited=false,active=false;
 const page=global.AstrBotPluginPage,key=()=>JSON.stringify([selected?.creator,selected?.session_id,persona]);
 const ticket=()=>({epoch,creator:selected?.creator,session:selected?.session_id,persona});
 const current=t=>active&&t.epoch===epoch&&t.creator===selected?.creator&&t.session===selected?.session_id;
 const visible=()=>!document.getElementById('view-chat_corpus').hidden;
 const bodyLimit=()=>fields.kind.value==='preference'?1000:12000;
 const message=text=>{note.textContent=text;};
 const stamp=value=>Number.isFinite(value)?new Date(value*1000).toLocaleString('zh-CN',{hour12:false}):'未记录';
 async function request(method,path,payload){
  if(!page)throw Error('请从已登录的 AstrBot 后台打开工作台。');
  await bridgeDeadline(page.ready(),15000,'后台连接未建立，请重新进入本页。');
  const result=await bridgeDeadline(method==='GET'?page.apiGet(path,payload):page.apiPost(path,payload),method==='GET'?25000:45000,'请求未确认，请保留输入并重新读取；不要重复保存。');
  if(!result||result.status!=='ok'||!Object.hasOwn(result,'data')){const e=Error(result?.message||'服务端回复不完整，请重新读取。');e.status=Number(result?.status_code||result?.code)||0;throw e;}return result.data;
 }
 function ownedSessions(value){
  if(!Array.isArray(value))throw Error('聊天目录未返回完整列表。');
  return value.filter(r=>r&&r.platform_id==='webchat'&&r.is_group===0&&typeof r.creator==='string'&&r.creator&&typeof r.session_id==='string'&&r.session_id&&r.tls_state?.archived!==true);
 }
 async function recheck(t){
  const owned=ownedSessions(await request('GET','page/chat/sessions',{}));
  if(!current(t))return false;
  if(!owned.some(r=>r.session_id===t.session&&r.creator===t.creator)){
   epoch++;selected=null;persona='';snapshot=editing=null;rows=[];list.replaceChildren();clearEditor();session.replaceChildren(node('option','请重新读取聊天列表'));scope.textContent='当前登录身份或会话已变化。';message('旧资料已收起，请重新读取聊天列表。');busy=false;sync();return false;
  }return true;
 }
 function sync(){
  const blocked=selected&&unknown.get(key());
  refresh.disabled=busy;session.disabled=busy||!rows.length;readButton.disabled=busy||!selected;
  for(const n of form.querySelectorAll('input,textarea,select,button'))n.disabled=busy||!snapshot;
  for(const n of list.querySelectorAll('button'))n.disabled=busy||!snapshot;
  fields.kind.disabled=busy||!snapshot||!!editing;
  fields.lifetime.disabled=busy||!snapshot||fields.kind.value==='sample';
  fields.hours.disabled=busy||!snapshot||fields.lifetime.value!=='temporary';
  fields.body.maxLength=bodyLimit();bodyLabel.textContent='正文（最多 '+bodyLimit()+' 字符）';
  save.disabled=busy||!snapshot||!!blocked;save.textContent=editing?'保存修订':'保存新条目';
  resolved.hidden=!blocked?.read;resolved.disabled=busy;
 }
 function clearEditor(){editing=null;expiryEdited=false;for(const n of ['title','body','source','tags'])fields[n].value='';fields.kind.value='sample';fields.lifetime.value='persistent';fields.hours.value='24';fields.enabled.checked=true;sync();}
 function edit(item){editing=structuredClone(item);expiryEdited=false;for(const n of ['title','body','source'])fields[n].value=item[n]||'';fields.tags.value=(item.tags||[]).join('、');fields.kind.value=item.kind;fields.lifetime.value=item.lifetime;fields.enabled.checked=item.enabled;fields.hours.value=String(Math.min(168,Math.max(1,Math.ceil(((item.expires_at||Date.now()/1000+86400)-Date.now()/1000)/3600))));sync();}
 function render(){
  list.replaceChildren();const kind=filter.value;
  const items=(snapshot?.items||[]).filter(item=>kind==='all'||item.kind===kind);
  count.textContent=(snapshot?.items.length||0)+' / 128 项 · 当前显示 '+items.length+' 项';
  for(const item of items){const row=node('article',undefined,'record corpus-item');row.dataset.corpusId=item.id;
   row.append(node('h3',item.title||item.body.slice(0,36)),node('p',(item.kind==='sample'?'参考语料':'明确偏好')+' · '+({persistent:'长期',session:'当前会话',temporary:'临时'}[item.lifetime]||'未确认')+' · '+(!item.enabled?'已停用':item.eligible===false?'当前不适用':'已启用')+' · 修订 '+item.revision,'hint'),node('p',item.body,'corpus-preview'));
   if(item.tags?.length)row.append(node('p',item.tags.join(' · '),'hint'));if(item.source)row.append(node('p','来源：'+item.source,'hint'));if(item.expires_at)row.append(node('p','有效期至 '+stamp(item.expires_at),'hint'));
   row.append(button('查看与修改',()=>edit(item)));
   if(item.history?.length){const detail=node('details');detail.append(node('summary','最近修订摘要（'+item.history.length+'）'));for(const old of item.history)detail.append(node('p','修订 '+old.revision+' · '+(old.body||old.title||'状态变更')));row.append(detail);}list.append(row);
  }
  if(!items.length)list.append(node('p',snapshot?'此范围暂无这类资料。可以在右侧填写或导入自己的文本。':'先选择当前账号的聊天，再读取角色资料。','empty'));sync();
 }
 function valid(data,t){
  if(!data||data.session_id!==t.session||typeof data.persona_id!=='string'||!data.persona_id||t.persona&&data.persona_id!==t.persona)throw Error('角色或会话已变化，请重新选择聊天后读取。');return data;
 }
 async function loadSessions(){
  if(busy||!active)return;const turn=++epoch;busy=true;selected=null;persona='';snapshot=null;rows=[];clearEditor();render();scope.textContent='正在读取当前登录账号的聊天…';message('');
  try{const value=ownedSessions(await request('GET','page/chat/sessions',{}));if(turn!==epoch||!active)return;rows=value;session.replaceChildren();const initial=node('option',rows.length?'请选择聊天':'没有可用的 WebChat 会话');initial.value='';session.append(initial);
   for(const [i,row]of rows.entries()){const option=node('option',(row.display_name||row.session_id)+' · '+row.creator);option.value=String(i);session.append(option);}scope.textContent=rows.length?'只显示当前后台登录账号的聊天；角色沿该聊天的已确认设置。':'请先用同一账号在 Chat 建立聊天并选择角色，再回来读取。这里不会自动建立会话或角色。';
  }catch(e){if(turn===epoch&&active){scope.textContent='聊天列表尚未确认。';message(e.message);}}
  finally{if(turn===epoch&&active){busy=false;sync();}}
 }
 async function read(){
  if(busy||!selected||!active)return;const t=ticket();busy=true;sync();message('正在读取所选聊天的角色资料…');
  try{const data=valid(await request('GET','page/chat/corpus',{session_id:t.session}),t);if(!current(t)||!await recheck(t))return;
   if(!Array.isArray(data.items)||data.items.some(x=>!x||typeof x.id!=='string'||!Number.isInteger(x.revision)||typeof x.body!=='string'))throw Error('资料列表不完整，输入已保留。');
   persona=data.persona_id;snapshot=data;scope.textContent='账号：'+t.creator+' · 聊天：'+(selected.display_name||t.session)+' · 角色：'+persona;
   const blocked=unknown.get(key());if(blocked){blocked.read=true;if(!fields.body.value&&blocked.draft){edit(blocked.draft);if(!blocked.draft.id)editing=null;}message(blocked.confirmed?'已重新读取当前资料；上次保存回执已确认。核对后可结束等待。':'已读取当前资料；这不证明上次保存成功。核对后可结束等待，原输入保留。');}else message('已读取。参考文本由正常回复按语境选用，不会写成事实或额外调用模型。');render();
  }catch(e){if(current(t)){snapshot=null;message(e.message+' 原输入保留，重新读取成功后可继续。');}}
  finally{if(current(t)){busy=false;sync();}}
 }
 async function submit(event){
  event.preventDefault();if(busy||!selected||!snapshot||unknown.has(key()))return;const t=ticket(),body=fields.body.value.trim();
  if(!body||body.length>bodyLimit()){message('正文需要 1–'+bodyLimit()+' 个字符。');return;}
  const record={kind:fields.kind.value,body,title:fields.title.value.trim(),source:fields.source.value.trim(),tags:fields.tags.value.split(/[,，、\n]/).map(x=>x.trim()).filter(Boolean),enabled:fields.enabled.checked,lifetime:fields.kind.value==='sample'?'persistent':fields.lifetime.value,expires_at:null};
  if(record.tags.length>8||record.tags.some(x=>x.length>24)){message('标签最多 8 个，每个最多 24 字符。');return;}
  if(record.lifetime==='temporary'){const hours=Number(fields.hours.value);if(!Number.isFinite(hours)||hours<1||hours>168){message('临时偏好时长为 1–168 小时。');return;}record.expires_at=editing?.lifetime==='temporary'&&!expiryEdited?editing.expires_at:Math.floor(Date.now()/1000+hours*3600);}
  const payload={session_id:t.session,op:'save',id:editing?.id||null,expected_revision:editing?.revision||0,request_id:TLSBrowserCompat.uuid(),record},owner=key();let confirmed=false;busy=true;sync();message('正在保存…');
  try{const data=valid(await request('POST','page/chat/corpus',payload),t);if(!current(t))return;const item=data.item;
   if(!item||typeof item.id!=='string'||payload.id&&item.id!==payload.id||!Number.isInteger(item.revision)||item.revision<=payload.expected_revision||['body','title','source','kind','lifetime','enabled','expires_at'].some(k=>item[k]!==record[k])||JSON.stringify(item.tags)!==JSON.stringify([...new Set(record.tags)]))throw Error('保存回复未确认本次内容。');
   confirmed=true;if(!await recheck(t))return;snapshot.items=[item,...snapshot.items.filter(x=>x.id!==item.id)];editing=structuredClone(item);expiryEdited=false;render();message('已保存修订 '+item.revision+'。'+(item.enabled?'是否采用仍由回复模型按语境判断。':'已停用，最近修订保留。'));
  }catch(e){const rejected=!confirmed&&[400,401,403,409,422].includes(e.status);if(!rejected)unknown.set(owner,{read:false,confirmed,draft:{...record,id:payload.id,revision:payload.expected_revision}});if(current(t)){if(rejected)snapshot=null;message(confirmed?'保存已确认，但随后账号范围读取失败。输入保留，请重新读取核对，不要重复保存。':rejected?e.message+' 输入保留，请重新读取当前版本。':'保存结果尚未确认，输入保留。请重新读取核对；不会自动再次提交。');}}
  finally{if(current(t)){busy=false;sync();}}
 }
 const header=node('section',undefined,'panel'),heading=node('div',undefined,'panel-head');heading.append(node('h2','语料与聊天偏好'));const refresh=button('重新读取聊天列表',loadSessions);heading.append(refresh);header.append(heading,node('p','管理自己提供的参考文本，以及明确的长期、当前会话或临时偏好。正文必填，角色从所选聊天继承。','hint'));
 const selector=node('label','当前账号的聊天'),session=node('select');session.id='console-corpus-session';selector.append(session);const readButton=button('读取这个聊天的资料',read),scope=node('p','','hint');scope.id='console-corpus-scope';header.append(selector,readButton,scope);
 const note=node('p','','notice');note.id='console-corpus-status';note.setAttribute('role','status');note.setAttribute('aria-live','polite');
 const resolved=button('已核对，结束等待',()=>{const blocked=unknown.get(key());if(!busy&&blocked?.read){unknown.delete(key());snapshot=null;clearEditor();void read();}});resolved.hidden=true;header.append(note,resolved);
 const columns=node('div',undefined,'corpus-columns'),library=node('section',undefined,'panel'),libraryHead=node('div',undefined,'panel-head');libraryHead.append(node('h2','已有资料'));
 const filter=node('select');filter.id='console-corpus-filter';filter.setAttribute('aria-label','筛选资料类型');for(const [value,text]of [['all','全部资料'],['sample','参考语料'],['preference','明确偏好']]){const o=node('option',text);o.value=value;filter.append(o);}filter.onchange=render;libraryHead.append(filter);const count=node('p','','hint'),list=node('div',undefined,'records');list.id='console-corpus-list';library.append(libraryHead,count,list);
 const editor=node('section',undefined,'panel'),form=node('form');form.id='console-corpus-form';editor.append(node('h2','新建或修改'),form);
 function field(key,label,type='input'){const wrap=node('label'),n=node(type);n.id='console-corpus-'+key;fields[key]=n;wrap.append(node('span',label),n);form.append(wrap);return n;}
 function options(n,values){for(const [value,text]of values){const o=node('option',text);o.value=value;n.append(o);}}
 options(field('kind','内容类型','select'),[['sample','参考语料'],['preference','明确偏好']]);field('body','正文','textarea').required=true;fields.body.rows=7;const bodyLabel=fields.body.parentElement.querySelector('span');
 const file=field('file','导入 TXT（只预览，保存后生效）');file.type='file';file.accept='.txt,text/plain';file.onchange=async()=>{const item=file.files?.[0],t=ticket();if(!item||busy)return;try{if(item.size>65536)throw Error('文本文件最多 64 KiB。');const text=await item.text();if(!current(t))return;if(text.length>bodyLimit())throw Error('此类型最多 '+bodyLimit()+' 字符。');fields.body.value=text;message('文本已放入编辑框，尚未保存。');}catch(e){if(current(t))message(e.message);}finally{file.value='';}};
 const optional=node('details');optional.append(node('summary','标题、标签与来源（可选）'));for(const [name,label,max]of [['title','标题',80],['tags','标签（最多 8 个，用顿号分隔）',240],['source','来源说明',240]]){field(name,label).maxLength=max;optional.append(fields[name].parentElement);}form.append(optional);
 options(field('lifetime','适用时间','select'),[['persistent','长期'],['session','当前会话'],['temporary','临时有效']]);const hours=field('hours','临时有效小时数');hours.type='number';hours.min=1;hours.max=168;const enabled=field('enabled','启用这条资料');enabled.type='checkbox';enabled.parentElement.className='switch-label';
 fields.kind.onchange=()=>{fields.lifetime.value=fields.kind.value==='sample'?'persistent':'session';sync();};fields.lifetime.onchange=()=>{expiryEdited=true;sync();};fields.hours.oninput=()=>{expiryEdited=true;};
 const actions=node('div',undefined,'actions'),save=node('button','保存新条目','primary');save.type='submit';actions.append(save,button('新建条目',()=>{clearEditor();message('新条目尚未保存。');}));form.append(actions,node('p','长期资料仅属于此账号与角色；当前会话和临时偏好不影响其他聊天。关闭或离开本页会收起未保存正文。','hint'));form.onsubmit=submit;
 columns.append(library,editor);root.append(header,columns);
 session.onchange=()=>{epoch++;selected=rows[Number(session.value)]||null;if(session.value==='')selected=null;persona='';snapshot=null;clearEditor();render();message('');if(selected)scope.textContent='已选聊天：'+(selected.display_name||selected.session_id)+'，请读取以确认角色。';};
 function leave(){active=false;epoch++;busy=false;selected=null;persona='';snapshot=editing=null;rows=[];clearEditor();render();scope.textContent='请选择当前账号的聊天。';message('');}
 function activate(){if(active)return;active=true;void loadSessions();}
 global.addEventListener('tls-admin-viewchange',event=>{if(event.detail.view==='chat_corpus')activate();else if(active)leave();});
 global.addEventListener('pagehide',leave);global.TLSChatCorpusPanel={activate};clearEditor();render();if(visible())activate();
})(window);
