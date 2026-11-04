/* Account-owned reference libraries, through the authenticated page bridge. */
(function(global){
'use strict';
const root=document.getElementById('chat-corpus-mount');if(!root)return;
const node=(tag,text,cls='')=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;n.className=cls;return n;};
const button=(text,fn)=>{const n=node('button',text);n.type='button';n.onclick=fn;return n;};
const options=(n,values)=>{n.replaceChildren();for(const [value,text]of values){const o=node('option',text);o.value=value;n.append(o);}};
const fields={},libFields={},unknown=new Map(),page=global.AstrBotPluginPage;
let rows=[],selected=null,persona='',snapshot=null,editing=null,libraryEditing=null,currentLibrary='default',busy=false,epoch=0,expiryEdited=false,active=false,itemDirty=false,libraryDirty=false,fresh=false;
const owner=()=>JSON.stringify([selected?.creator,selected?.session_id,persona]),pending=kind=>unknown.get(owner()+':'+kind);
const ticket=()=>({epoch,creator:selected?.creator,session:selected?.session_id,persona});
const current=t=>active&&t.epoch===epoch&&t.creator===selected?.creator&&t.session===selected?.session_id;
const bodyLimit=()=>fields.kind.value==='preference'?1000:12000;
const message=text=>{note.textContent=text;};
const stamp=value=>Number.isFinite(value)?new Date(value*1000).toLocaleString('zh-CN',{hour12:false}):'未记录';
const libraryId=value=>value==='default'||typeof value==='string'&&/^library_[a-f0-9]{24}$/.test(value);
const defaultLibrary=()=>({id:'default',name:'原有语料',enabled:true,trigger:{mode:'relevance',match:'any',include:[],exclude:[]},revision:0,item_count:0});
async function request(method,path,payload){
 if(!page)throw Error('请从已登录的 AstrBot 后台打开工作台。');
 await bridgeDeadline(page.ready(),15000,'后台连接未建立，请重新进入本页。');
 const result=await bridgeDeadline(method==='GET'?page.apiGet(path,payload):page.apiPost(path,payload),method==='GET'?25000:45000,'请求未确认，请保留输入并重新读取；不要重复保存。');
 // Current SDK unwraps HTTP data; older bridges retain the success envelope.
 if(result&&typeof result==='object'&&!Array.isArray(result)&&Object.hasOwn(result,'status')){
  if(!['ok','success'].includes(result.status)||!Object.hasOwn(result,'data'))throw Error(result.message||'服务端回复不完整，请重新读取。');return result.data;
 }
 if(!result||typeof result!=='object')throw Error('服务端回复不完整，请重新读取。');return result;
}
function ownedSessions(value){
 if(!Array.isArray(value))throw Error('聊天目录未返回完整列表。');
 const owned=value.filter(r=>r&&r.platform_id==='webchat'&&r.is_group===0&&typeof r.creator==='string'&&r.creator&&typeof r.session_id==='string'&&r.session_id&&r.tls_state?.archived!==true),seen=new Set();
 for(const r of owned){const id=JSON.stringify([r.creator,r.session_id]);if(seen.has(id))throw Error('聊天目录存在重复范围，请先核对会话目录。');seen.add(id);}return owned;
}
function validScope(data,t){if(!data||data.session_id!==t.session||typeof data.persona_id!=='string'||!data.persona_id)throw Error('回复中的账号角色范围未确认。');return data;}
function validWrite(data,t){validScope(data,t);if(data.persona_id!==t.persona)throw Error('保存后角色范围发生变化，结果需核对。');return data;}
function validLibrary(x){return x&&libraryId(x.id)&&typeof x.name==='string'&&x.name&&typeof x.enabled==='boolean'&&Number.isInteger(x.revision)&&x.revision>=0&&x.trigger&&['relevance','keywords','always'].includes(x.trigger.mode)&&['any','all'].includes(x.trigger.match)&&['include','exclude'].every(k=>Array.isArray(x.trigger[k])&&x.trigger[k].length<=12&&x.trigger[k].every(v=>typeof v==='string'&&v.length>=2&&v.length<=40))&&(x.trigger.mode!=='keywords'||x.trigger.include.length>0);}
function validCorpus(data){
 if(!Array.isArray(data.items)||data.items.length>128||data.items.some(x=>!x||typeof x.id!=='string'||!x.id||!Number.isInteger(x.revision)||x.revision<1||typeof x.body!=='string'||!['sample','preference'].includes(x.kind)||typeof x.enabled!=='boolean'||!Array.isArray(x.tags)))throw Error('资料列表不完整，原输入已保留。');
 const items=data.items.map(x=>({...x,library_id:x.library_id||'default'})),libraries=data.libraries===undefined?[{...defaultLibrary(),item_count:items.length}]:data.libraries;
 if(!Array.isArray(libraries)||!libraries.length||libraries.length>16||libraries.some(x=>!validLibrary(x))||new Set(libraries.map(x=>x.id)).size!==libraries.length||!libraries.some(x=>x.id==='default')||items.some(x=>!libraries.some(l=>l.id===x.library_id)||x.kind==='preference'&&x.library_id!=='default')||new Set(items.map(x=>x.id)).size!==items.length)throw Error('资料库范围不完整，原输入已保留。');
 for(const name of ['total_items','visible_items'])if(data[name]!==undefined&&(!Number.isInteger(data[name])||data[name]<0||data[name]>128))throw Error('资料数量回复未确认。');
 if(data.visible_items!==undefined&&data.visible_items!==items.length||data.total_items!==undefined&&data.total_items<items.length)throw Error('资料数量与当前列表不一致。');
 return {...data,items,libraries};
}
function clearScope(){selected=null;persona='';snapshot=null;fresh=false;currentLibrary='default';rows=[];search.value='';filter.value='all';clearEditor();clearLibraryEditor();render();}
async function recheck(t){
 const owned=ownedSessions(await request('GET','page/chat/sessions',{}));if(!current(t))return false;
 if(!owned.some(r=>r.session_id===t.session&&r.creator===t.creator)){epoch++;clearScope();options(session,[['','请重新读取聊天列表']]);scope.textContent='当前登录身份或会话已变化。';message('旧资料已收起，请重新读取聊天列表。');busy=false;sync();return false;}return true;
}
function sync(){
 refresh.disabled=busy;session.disabled=busy||!rows.length;readButton.disabled=busy||!selected;
 for(const f of [form,libraryForm])for(const n of f.querySelectorAll('input,textarea,select,button'))n.disabled=busy||!snapshot||!fresh;
 for(const n of root.querySelectorAll('.corpus-library-list button,#console-corpus-list button'))n.disabled=busy||!snapshot||!fresh;
 filter.disabled=search.disabled=busy||!snapshot;newLibrary.disabled=busy||!snapshot||!fresh||!!pending('library')||snapshot.libraries.length>=16;
 fields.kind.disabled=busy||!snapshot||!fresh||!!editing;fields.library.disabled=busy||!snapshot||!fresh||fields.kind.value==='preference';
 fields.lifetime.disabled=busy||!snapshot||!fresh||fields.kind.value==='sample';fields.hours.disabled=busy||!snapshot||!fresh||fields.lifetime.value!=='temporary';
 fields.body.maxLength=bodyLimit();bodyLabel.textContent='正文（最多 '+bodyLimit()+' 字符）';
 save.disabled=busy||!snapshot||!fresh||!!pending('item');save.textContent=editing?'保存这个块的修订':'保存新块';
 librarySave.disabled=busy||!snapshot||!fresh||!!pending('library');librarySave.textContent=libraryEditing?'保存资料库设置':'创建资料库';
 itemResolved.hidden=!pending('item')?.read;libResolved.hidden=!pending('library')?.read;itemResolved.disabled=libResolved.disabled=busy;
 for(const [kind,notice]of [['item',itemNotice],['library',libraryNotice]]){const p=pending(kind);notice.textContent=p?(p.confirmed?'保存回执已确认，但随后范围读取失败。重新读取后请核对。':'上次保存结果尚未确认。输入保留，重新读取只显示现状，不证明原写入成功。'):'';}
}
function libraryOptions(value){options(fields.library,(snapshot?.libraries||[]).map(x=>[x.id,x.name+(x.enabled?'':'（参考块已停用）')]));fields.library.value=value||currentLibrary;}
function clearEditor(){editing=null;expiryEdited=false;itemDirty=false;for(const n of ['title','body','source','tags'])fields[n].value='';fields.kind.value='sample';fields.lifetime.value='persistent';fields.hours.value='24';fields.enabled.checked=true;libraryOptions(currentLibrary);}
function edit(item){editing=structuredClone(item);expiryEdited=false;itemDirty=false;for(const n of ['title','body','source'])fields[n].value=item[n]||'';fields.tags.value=(item.tags||[]).join('、');fields.kind.value=item.kind;fields.lifetime.value=item.lifetime;fields.enabled.checked=item.enabled;fields.hours.value=String(Math.min(168,Math.max(1,Math.ceil(((item.expires_at||Date.now()/1000+86400)-Date.now()/1000)/3600))));libraryOptions(item.library_id||'default');sync();}
function clearLibraryEditor(){libraryEditing=null;libraryDirty=false;libFields.name.value='';libFields.enabled.checked=true;libFields.mode.value='relevance';libFields.match.value='any';libFields.include.value=libFields.exclude.value='';}
function editLibrary(value){libraryEditing=structuredClone(value);libraryDirty=false;libFields.name.value=value.name;libFields.enabled.checked=value.enabled;libFields.mode.value=value.trigger.mode;libFields.match.value=value.trigger.match;libFields.include.value=value.trigger.include.join('\n');libFields.exclude.value=value.trigger.exclude.join('\n');sync();}
function selectLibrary(value){if(pending('library')||pending('item')){message('当前有待核对的保存结果，请先读取并核对，再切换资料库。');return;}currentLibrary=value;clearEditor();editLibrary(snapshot.libraries.find(x=>x.id===value));render();message('已打开资料库；修改后需要单独保存。');}
function render(){
 libraryList.replaceChildren();list.replaceChildren();
 for(const value of snapshot?.libraries||[]){const n=button('',()=>selectLibrary(value.id));n.className='corpus-library-card';n.dataset.libraryId=value.id;n.setAttribute('aria-pressed',String(value.id===currentLibrary));n.append(node('strong',value.name),node('span',(value.enabled?'参考块启用':'参考块停用')+' · '+({relevance:'按语境',keywords:'关键词',always:'始终候选'}[value.trigger.mode])+' · '+(Number.isInteger(value.item_count)?value.item_count:'—')+' 块','hint'));libraryList.append(n);}
 const all=snapshot?.items||[],term=search.value.trim().toLocaleLowerCase(),items=all.filter(x=>x.library_id===currentLibrary&&(filter.value==='all'||x.kind===filter.value)&&(!term||[x.title,x.body,x.source,...x.tags].join('\n').toLocaleLowerCase().includes(term)));
 count.textContent=snapshot?('本聊天可见 '+all.length+' 项'+(Number.isInteger(snapshot.total_items)?' · 此账号与角色共 '+snapshot.total_items+' / 128 项':' · 全范围总数未返回')+' · 当前库筛选 '+items.length+' 项'):'请先读取当前账号的聊天资料。';
 for(const item of items){const row=node('article',undefined,'record corpus-item');row.dataset.corpusId=item.id;row.append(node('h3',item.title||item.body.slice(0,36)),node('p',(item.kind==='sample'?'参考文本块':'明确偏好')+' · '+({persistent:'长期',session:'当前会话',temporary:'临时'}[item.lifetime]||'未确认')+' · '+(!item.enabled?'已停用':item.eligible===false?'当前不适用':'已启用')+' · 修订 '+item.revision,'hint'),node('p',item.body,'corpus-preview'));
  if(item.tags.length)row.append(node('p',item.tags.join(' · '),'hint'));if(item.source)row.append(node('p','来源：'+item.source,'hint'));if(item.expires_at)row.append(node('p','有效期至 '+stamp(item.expires_at),'hint'));
  row.append(button('查看与修改',()=>{if(pending('item')){message('请先核对上次保存结果，原输入仍在编辑框。');return;}edit(item);message('已打开完整正文；保存只影响这个块。');}));
  if(item.history?.length){const detail=node('details');detail.append(node('summary','最近修订摘要（'+item.history.length+'）'));for(const old of item.history)detail.append(node('p','修订 '+old.revision+' · '+(old.body||old.title||'状态变更')));row.append(detail);}list.append(row);
 }
 if(!items.length)list.append(node('p',snapshot?(term?'当前筛选没有匹配的文本块。':'此资料库在当前聊天范围暂无文本块。可以在编辑框填写并保存。'):'先读取当前账号的聊天，再管理角色资料库。','empty'));sync();
}
function fillSessions(){options(session,[['',rows.length?'请选择聊天':'没有可用的 WebChat 会话'],...rows.map((r,i)=>[String(i),(r.display_name||r.session_id)+' · '+r.creator])]);if(selected)session.value=String(rows.findIndex(r=>r.creator===selected.creator&&r.session_id===selected.session_id));}
async function loadSessions(){
 if(busy||!active)return;const turn=++epoch,previous=selected;busy=true;fresh=false;sync();message('正在读取当前登录账号的聊天…');let shouldRead=false;
 try{const value=ownedSessions(await request('GET','page/chat/sessions',{}));if(turn!==epoch||!active)return;const kept=previous&&value.find(r=>r.creator===previous.creator&&r.session_id===previous.session_id);
  if(!kept){clearScope();rows=value;selected=rows.length===1?rows[0]:null;}else{rows=value;selected=kept;}fillSessions();shouldRead=!!selected;
  scope.textContent=selected?'正在确认所选聊天的角色资料…':rows.length?'请选择聊天；不会自动猜测角色或会话。':'当前账号没有可用的 WebChat 会话。请先在 Chat 建立聊天并选择角色；这里不会自动创建。';
 }catch(e){if(turn===epoch&&active)message(e.message+' 已有输入保留，范围确认前暂停保存。');}
 finally{if(turn===epoch&&active){busy=false;sync();}}
 if(shouldRead&&turn===epoch&&active)await read();
}
async function read(){
 if(busy||!selected||!active)return;const t=ticket();busy=true;fresh=false;sync();message('正在读取当前范围的资料库…');
 try{const data=validCorpus(validScope(await request('GET','page/chat/corpus',{session_id:t.session}),t));if(!current(t)||!await recheck(t))return;
  const changed=!!persona&&persona!==data.persona_id;if(changed){snapshot=null;currentLibrary='default';search.value='';filter.value='all';clearEditor();clearLibraryEditor();}
  persona=data.persona_id;snapshot=data;fresh=true;if(!data.libraries.some(x=>x.id===currentLibrary))currentLibrary='default';
  const ip=pending('item'),lp=pending('library');
  if(ip?.record&&!fields.body.value){edit(ip.record);if(!ip.record.id)editing=null;itemDirty=true;}
  if(lp?.record&&!libFields.name.value){editLibrary(lp.record);if(!lp.record.id)libraryEditing=null;libraryDirty=true;}
  if(!itemDirty&&!ip){const newer=editing&&data.items.find(x=>x.id===editing.id);if(newer)edit(newer);else clearEditor();}else libraryOptions(fields.library.value);
  if(!libraryDirty&&!lp)editLibrary(data.libraries.find(x=>x.id===currentLibrary));
  for(const p of [ip,lp])if(p)p.read=true;
  scope.textContent='账号：'+t.creator+' · 聊天：'+(selected.display_name||t.session)+' · 角色：'+persona+'（WebChat 资料范围）';
  message(changed?'角色已改变，旧角色的正文和编辑输入已收起。':ip||lp?'已读取服务器当前资料。原保存仍需人工核对，不会自动重发。':itemDirty||libraryDirty?'已刷新服务器列表；未保存的编辑输入和原修订号已保留。':'已读取资料库。文本由正常回复按语境选作参考，不保证每次采用。');render();
 }catch(e){if(current(t)){fresh=false;message(e.message+' 原输入保留，重新读取成功前暂停保存。');}}
 finally{if(current(t)){busy=false;sync();}}
}
function unknownResult(kind,ownerKey,record,confirmed,e){unknown.set(ownerKey+':'+kind,{read:false,confirmed,record});if(selected&&owner()===ownerKey)message((confirmed?'保存回执已确认，但随后账号范围读取失败。':'保存结果尚未确认：'+e.message)+' 输入保留，请读取核对；不会自动再次提交。');}
async function submit(event){
 event.preventDefault();if(busy||!selected||!snapshot||!fresh||pending('item'))return;const t=ticket(),body=fields.body.value;if(!body.trim()||body.length>bodyLimit()){message('正文需要 1–'+bodyLimit()+' 个字符。');return;}
 const record={kind:fields.kind.value,body,title:fields.title.value.trim(),source:fields.source.value.trim(),tags:fields.tags.value.split(/[,，、\n]/).map(x=>x.trim()).filter(Boolean),enabled:fields.enabled.checked,lifetime:fields.kind.value==='sample'?'persistent':fields.lifetime.value,expires_at:null,library_id:fields.kind.value==='preference'?'default':fields.library.value};
 if(record.tags.length>8||record.tags.some(x=>x.length>24)){message('标签最多 8 个，每个最多 24 字符。');return;}
 if(!snapshot.libraries.some(x=>x.id===record.library_id)){message('请先选择已读取的资料库。');return;}
 if(record.lifetime==='temporary'){const hours=Number(fields.hours.value);if(!Number.isFinite(hours)||hours<1||hours>168){message('临时偏好时长为 1–168 小时。');return;}record.expires_at=editing?.lifetime==='temporary'&&!expiryEdited?editing.expires_at:Math.floor(Date.now()/1000+hours*3600);}
 const payload={session_id:t.session,op:'save',id:editing?.id||null,expected_revision:editing?.revision||0,request_id:TLSBrowserCompat.uuid(),record},ownerKey=owner();let confirmed=false;busy=true;sync();message('正在保存这个文本块…');
 try{const data=validWrite(await request('POST','page/chat/corpus',payload),t);if(!current(t))return;const item=data.item;
  if(!item||typeof item.id!=='string'||payload.id&&item.id!==payload.id||!Number.isInteger(item.revision)||item.revision<=payload.expected_revision||['body','title','source','kind','lifetime','enabled','expires_at','library_id'].some(k=>(k==='library_id'?(item[k]||'default'):item[k])!==record[k])||JSON.stringify(item.tags)!==JSON.stringify([...new Set(record.tags)]))throw Error('保存回复未确认本次内容。');
  confirmed=true;if(!await recheck(t))return;const old=snapshot.items.find(x=>x.id===item.id);snapshot.items=[{...item,library_id:item.library_id||'default'},...snapshot.items.filter(x=>x.id!==item.id)];if(!old&&Number.isInteger(snapshot.total_items))snapshot.total_items++;snapshot.visible_items=snapshot.items.length;
  for(const l of snapshot.libraries)l.item_count=snapshot.items.filter(x=>x.library_id===l.id).length;
  const keepLibrary=currentLibrary!==record.library_id&&(libraryDirty||!!pending('library'));
  if(!keepLibrary)currentLibrary=record.library_id;if(!libraryDirty&&!pending('library'))editLibrary(snapshot.libraries.find(x=>x.id===currentLibrary));edit(snapshot.items[0]);render();
  message('文本块已保存，修订 '+item.revision+'。'+(keepLibrary?'文本块已存入“'+snapshot.libraries.find(x=>x.id===record.library_id).name+'”；当前资料库设置草稿和列表选择已保留。':item.kind==='preference'?'明确偏好沿自身有效期生效。':item.enabled?'是否采用仍由回复模型按语境判断。':'已停用，最近修订保留。'));
 }catch(e){unknownResult('item',ownerKey,{...record,id:payload.id,revision:payload.expected_revision},confirmed,e);}
 finally{if(current(t)){busy=false;sync();}}
}
const terms=value=>value.split(/[,，、\n]/).map(x=>x.trim()).filter(Boolean);
async function submitLibrary(event){
 event.preventDefault();if(busy||!selected||!snapshot||!fresh||pending('library'))return;const t=ticket(),record={name:libFields.name.value.trim(),enabled:libFields.enabled.checked,trigger:{mode:libFields.mode.value,match:libFields.match.value,include:terms(libFields.include.value),exclude:terms(libFields.exclude.value)}};
 if(!record.name||record.name.length>80){message('资料库名称需要 1–80 个字符。');return;}
 if(['include','exclude'].some(k=>record.trigger[k].length>12||record.trigger[k].some(x=>x.length<2||x.length>40))){message('触发词每组最多 12 个，每个 2–40 字符。');return;}
 if(record.trigger.mode==='keywords'&&!record.trigger.include.length){message('关键词触发至少需要一个包含词。');return;}
 const payload={session_id:t.session,op:'save_library',id:libraryEditing?.id||null,expected_revision:libraryEditing?.revision||0,request_id:TLSBrowserCompat.uuid(),record},ownerKey=owner();let confirmed=false;busy=true;sync();message('正在保存资料库设置…');
 try{const data=validWrite(await request('POST','page/chat/corpus',payload),t);if(!current(t))return;const value=data.library;
  if(!validLibrary(value)||payload.id&&value.id!==payload.id||value.revision<=payload.expected_revision||value.name!==record.name||value.enabled!==record.enabled||['mode','match'].some(k=>value.trigger[k]!==record.trigger[k])||['include','exclude'].some(k=>JSON.stringify(value.trigger[k])!==JSON.stringify([...new Set(record.trigger[k])])) )throw Error('保存回复未确认本次资料库设置。');
  confirmed=true;if(!await recheck(t))return;snapshot.libraries=[value,...snapshot.libraries.filter(x=>x.id!==value.id)];currentLibrary=value.id;editLibrary(value);
  if(!itemDirty&&!pending('item')){if(editing?.library_id===value.id)edit(editing);else clearEditor();}else libraryOptions(fields.library.value);
  render();message('资料库已保存，修订 '+value.revision+'。开关与触发条件仅影响参考文本块，明确偏好仍沿自身设置。');
 }catch(e){unknownResult('library',ownerKey,{...record,id:payload.id,revision:payload.expected_revision},confirmed,e);}
 finally{if(current(t)){busy=false;sync();}}
}
function resolve(kind){const p=pending(kind);if(busy||!p?.read||!fresh)return;unknown.delete(owner()+':'+kind);if(kind==='item')clearEditor();else editLibrary(snapshot.libraries.find(x=>x.id===currentLibrary));message('已由你结束这次等待；没有重发原请求。请先在列表核对现有资料，再开始新的编辑。');render();}
const header=node('section',undefined,'panel'),heading=node('div',undefined,'panel-head');heading.append(node('h2','语料资料库与聊天偏好'));const refresh=button('刷新当前范围',loadSessions);refresh.id='console-corpus-refresh';heading.append(refresh);header.append(heading,node('p','按资料库整理参考文本，每个文本块可以独立查看、修改和保存。角色沿所选聊天的已确认设置。','hint'));
const selector=node('label','当前账号的聊天'),session=node('select');session.id='console-corpus-session';selector.append(session);const readButton=button('读取这个聊天的资料',read),scope=node('p','','hint');readButton.id='console-corpus-read';scope.id='console-corpus-scope';header.append(selector,readButton,scope);
const note=node('p','','notice');note.id='console-corpus-status';note.setAttribute('role','status');note.setAttribute('aria-live','polite');header.append(note);
const librariesPanel=node('section',undefined,'panel'),librariesHead=node('div',undefined,'panel-head');librariesHead.append(node('h2','资料库'));const newLibrary=button('新建资料库',()=>{clearLibraryEditor();sync();message('填写新资料库的名称与触发设置，创建后再添加文本块。');});newLibrary.id='console-corpus-new-library';librariesHead.append(newLibrary);
const libraryList=node('div',undefined,'corpus-library-list');libraryList.id='console-corpus-libraries';const libraryForm=node('form');libraryForm.id='console-corpus-library-form';const libCols=node('div',undefined,'corpus-library-layout');libCols.append(libraryList,libraryForm);librariesPanel.append(librariesHead,libCols);
function field(target,store,key,label,type='input',prefix='console-corpus-'){const wrap=node('label'),n=node(type);n.id=prefix+key;store[key]=n;wrap.append(node('span',label),n);target.append(wrap);return n;}
field(libraryForm,libFields,'name','资料库名称','input','console-corpus-library-').maxLength=80;const libEnabled=field(libraryForm,libFields,'enabled','启用此库的参考文本块','input','console-corpus-library-');libEnabled.type='checkbox';libEnabled.parentElement.className='switch-label';
options(field(libraryForm,libFields,'mode','何时进入参考候选','select','console-corpus-library-'),[['relevance','按环境与语境匹配'],['keywords','包含指定关键词时'],['always','始终作为候选']]);
options(field(libraryForm,libFields,'match','包含词匹配方式','select','console-corpus-library-'),[['any','任意一个包含词'],['all','全部包含词']]);
for(const [key,text]of [['include','包含词'],['exclude','排除词（优先排除）']]){const n=field(libraryForm,libFields,key,text+'：每行一个，最多 12 个，每个 2–40 字符','textarea','console-corpus-library-');n.rows=2;n.maxLength=491;}
const libraryNotice=node('p','','notice'),libResolved=button('已核对资料库，结束等待',()=>resolve('library')),librarySave=node('button','创建资料库','primary');libraryNotice.id='console-corpus-library-pending';libResolved.id='console-corpus-library-resolve';librarySave.type='submit';librarySave.id='console-corpus-library-save';libraryForm.append(node('p','触发只决定参考块能否成为候选，不保证采用。停用原有语料库也不会关闭其中的明确偏好。','hint'),libraryNotice,libResolved,librarySave);libraryForm.onsubmit=submitLibrary;libraryForm.addEventListener('input',()=>{libraryDirty=true;});libraryForm.addEventListener('change',()=>{libraryDirty=true;});
const columns=node('div',undefined,'corpus-columns'),blocks=node('section',undefined,'panel'),blocksHead=node('div',undefined,'panel-head');blocksHead.append(node('h2','文本块'));
const filter=node('select');filter.id='console-corpus-filter';filter.setAttribute('aria-label','筛选资料类型');options(filter,[['all','全部资料'],['sample','参考文本块'],['preference','明确偏好']]);filter.onchange=render;blocksHead.append(filter);
const search=node('input');search.id='console-corpus-search';search.type='search';search.placeholder='搜索本库标题、正文或标签';search.setAttribute('aria-label','搜索本库文本块');search.oninput=render;
const count=node('p','','hint'),list=node('div',undefined,'records');count.id='console-corpus-count';list.id='console-corpus-list';blocks.append(blocksHead,search,count,list);
const editor=node('section',undefined,'panel'),form=node('form');form.id='console-corpus-form';editor.append(node('h2','查看与编辑文本块'),form);
const itemField=(key,label,type='input')=>field(form,fields,key,label,type);
options(itemField('kind','内容类型','select'),[['sample','参考文本块'],['preference','明确偏好']]);itemField('library','所属资料库','select');itemField('body','正文','textarea').required=true;fields.body.rows=9;const bodyLabel=fields.body.parentElement.querySelector('span');
const file=itemField('file','导入 TXT 到本块（只预览，单独保存后生效）');file.type='file';file.accept='.txt,text/plain';file.onchange=async()=>{const item=file.files?.[0],t=ticket();if(!item||busy)return;try{if(item.size>65536)throw Error('文本文件最多 64 KiB。');const text=await item.text();if(!current(t))return;if(text.length>bodyLimit())throw Error('此类型最多 '+bodyLimit()+' 字符。');fields.body.value=text;itemDirty=true;message('文本已放入编辑框，尚未保存。');}catch(e){if(current(t))message(e.message);}finally{file.value='';}};
const optional=node('details');optional.append(node('summary','标题、标签与来源（可选）'));for(const [name,label,max]of [['title','标题',80],['tags','标签（最多 8 个，每个 24 字符，用顿号分隔）',240],['source','来源说明',240]]){itemField(name,label).maxLength=max;optional.append(fields[name].parentElement);}form.append(optional);
options(itemField('lifetime','适用时间','select'),[['persistent','长期'],['session','当前会话'],['temporary','临时有效']]);const hours=itemField('hours','临时有效小时数');hours.type='number';hours.min=1;hours.max=168;const enabled=itemField('enabled','启用这条资料');enabled.type='checkbox';enabled.parentElement.className='switch-label';
fields.kind.onchange=()=>{fields.lifetime.value=fields.kind.value==='sample'?'persistent':'session';fields.library.value=fields.kind.value==='preference'?'default':currentLibrary;sync();};fields.lifetime.onchange=()=>{expiryEdited=true;sync();};fields.hours.oninput=()=>{expiryEdited=true;};
const actions=node('div',undefined,'actions'),save=node('button','保存新块','primary'),newItem=button('新建文本块',()=>{if(pending('item')){message('请先核对上次保存结果，原输入已保留。');return;}clearEditor();sync();message('新文本块尚未保存。');});save.type='submit';save.id='console-corpus-save';newItem.id='console-corpus-new-item';actions.append(save,newItem);
const itemNotice=node('p','','notice'),itemResolved=button('已核对文本块，结束等待',()=>resolve('item'));itemNotice.id='console-corpus-item-pending';itemResolved.id='console-corpus-item-resolve';form.append(itemNotice,itemResolved,actions,node('p','参考块最多选取 4 条，明确偏好最多 6 条，总参考预算 2400 字符；不会把资料写成角色经历。偏好只放在原有语料库，沿自身有效期和会话范围。离开本页会收起未保存正文。','hint'));form.onsubmit=submit;form.addEventListener('input',()=>{itemDirty=true;});form.addEventListener('change',()=>{itemDirty=true;});
columns.append(blocks,editor);root.append(header,librariesPanel,columns);
session.onchange=()=>{const value=session.value,next=value===''?null:rows[Number(value)];epoch++;selected=next||null;persona='';snapshot=null;fresh=false;currentLibrary='default';search.value='';filter.value='all';clearEditor();clearLibraryEditor();render();message('');scope.textContent=selected?'已选聊天：'+(selected.display_name||selected.session_id)+'，请读取以确认角色。':'请选择当前账号的聊天。';};
function leave(){active=false;epoch++;busy=false;clearScope();scope.textContent='请选择当前账号的聊天。';message('');}
function activate(){if(active)return;active=true;void loadSessions();}
global.addEventListener('tls-admin-viewchange',event=>{if(event.detail.view==='chat_corpus')activate();else if(active)leave();});global.addEventListener('pagehide',leave);global.TLSChatCorpusPanel={activate};clearEditor();clearLibraryEditor();render();if(!document.getElementById('view-chat_corpus').hidden)activate();
})(window);
