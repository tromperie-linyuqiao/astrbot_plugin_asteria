/* One fictional-life ledger shared with Chat. Reading never generates a story. */
(function(global){
'use strict';
const root=document.getElementById('autonomous-life-mount');if(!root)return;
const FIELDS=['platform','bot_id','user_id','character_id','session_id'];
const key=value=>JSON.stringify(FIELDS.map(name=>value?.[name]));
const getScope=()=>typeof state==='object'&&state.scope&&FIELDS.every(name=>state.scope[name])?{...state.scope}:null;
const node=(tag,text,cls)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=String(text);if(cls)value.className=cls;return value;};
const uuid=()=>{const value=global.TLSBrowserCompat?.uuid?.()||global.crypto?.randomUUID?.();if(!value)throw Error('当前浏览器无法生成请求标识，请刷新后操作。');return 'life-ui-'+value;};
const labels={event:'经历',character:'人物',thread:'开放事项'};
const plurals={event:'events',character:'characters',thread:'threads'};
const states={ongoing:'进行中',completed:'已结束',cancelled:'已取消',open:'未结束',resolved:'已解决',canonical:'正典人物',recurring:'常驻人物',temporary:'临时人物'};
const runtimeStates={disabled:'未开启',ready:'允许尝试评估',waiting:'等待下一次评估',quiet:'最近是平静日',needs_review:'需要复核',failed:'最近评估未完成',paused_budget:'预算暂停',budget_exhausted:'今日预算已用完',model_unavailable:'后台模型未配置',advanced:'已产生新经历',created:'已产生新经历',blocked:'暂不可推进',unavailable:'暂不可用',running:'正在评估',idle:'待评估',not_registered:'等待真实会话登记',deferred:'等待推进条件',busy:'已有评估正在进行'};
const errorLabels={provider_restricted:'模型服务限制了这次请求',provider_access_denied:'模型服务拒绝访问',provider_authentication:'模型服务认证失败',provider_rate_limited:'模型服务限流',provider_timeout:'模型服务响应超时',provider_connection:'无法连接模型服务',provider_unavailable:'模型服务暂不可用',invalid_model_output:'模型返回内容无法解析',invalid_life_record:'生成的生活资料需要复核',runtime_permission:'当前来源或权限已变化',unknown_result:'请求结束状态尚未确认',unknown_error:'发生未分类错误'};
const stamp=value=>typeof value==='number'&&Number.isFinite(value)?new Date(value*1000).toLocaleString():'尚无记录';
let queuedOpen=null;
let scope=null,section='event',selected=null,records=[],total=0,offset=0,serial=0,busy=false;
let settings=null,overview=null,people=[],events=[],draftKind=null,draftRecord=null;
const pending=new Map();
root.innerHTML=`<section class="panel autonomous-life"><div class="panel-head"><div><h2>生活档案</h2><p class="hint">角色在虚构世界中的经历、熟人与未完事项。它们与真实聊天、手机感知分别保存。</p></div><button type="button" data-life-refresh>刷新与核对</button></div><p data-life-status role="status" aria-live="polite"></p><div data-life-runtime class="life-runtime"></div><div class="life-tabs" role="tablist"><button data-life-tab="event" role="tab">近期经历</button><button data-life-tab="character" role="tab">人物</button><button data-life-tab="thread" role="tab">开放事项</button><button data-life-tab="shares" role="tab">分享记录</button><button data-life-tab="settings" role="tab">推进设置</button></div><div data-life-records><form data-life-search class="life-toolbar"><label>查找<input data-life-query maxlength="200" placeholder="标题、人物或经历关键词"></label><button type="submit">搜索</button><label class="life-check"><input data-life-archived type="checkbox">含归档</label><label class="life-check"><input data-life-invalid type="checkbox">含待复核</label><button type="button" data-life-new>新增</button></form><div class="life-columns"><div><div data-life-list></div><div class="actions"><button data-life-prev type="button">上一页</button><span data-life-range></span><button data-life-next type="button">下一页</button></div></div><section data-life-detail><p class="empty">选择一项查看关联与修正历史。</p></section></div></div><section data-life-settings hidden><form data-life-policy><div data-life-policy-fields class="life-policy-grid"></div><div class="actions"><button type="submit" class="primary">保存推进设置</button><button data-life-models type="button">设置后台模型</button><button data-life-advance type="button">现在评估一次生活推进</button></div><p class="hint">后台推进独立于即时聊天；预算与静默日判断由服务器执行。分享只是候选，发送仍遵守原有主动陪伴权限、频率与可打扰时段。</p><p class="hint">“现在评估”可能使用已经配置的后台模型，且需要真实会话授权；不会重放停机期间的日记。</p></form></section><div class="actions"><button data-life-release type="button" hidden>已核对，结束本次等待</button></div></section><section class="panel autonomous-life" data-life-editor hidden><div class="panel-head"><h2 data-life-editor-title></h2><button data-life-cancel type="button">取消编辑</button></div><form data-life-form><div data-life-fields class="life-edit-grid"></div><label>维护原因<input data-life-reason maxlength="400" required></label><div class="actions"><button class="primary" type="submit">保存并回读</button></div></form><p class="hint">修正会保留原版本。依赖旧版本的记录需要复核后才能重新进入普通检索，不会改写真实聊天。</p></section>`;
const $=name=>root.querySelector('[data-life-'+name+']');
const same=target=>key(target)===key(scope)&&key(target)===key(getScope());
const message=(text,error=false)=>{$('status').textContent=text;$('status').dataset.error=String(error);};
const advanceHint=node('p',undefined,'hint life-advance-hint');advanceHint.dataset.lifeAdvanceHint='true';$('advance').parentElement.after(advanceHint);
function advanceBlock(){
 if(!overview?.runtime)return '读取当前推进状态后才能评估。';
 const policy=settings?.settings;
 if(policy?.max_model_calls_per_day===0)return '模型调用预算为 0，当前不会发起模型请求；预算不会自动恢复。';
 if(policy?.max_events_per_day===0)return '新经历预算为 0，当前不会发起生活评估。';
 const runtime=overview.runtime;
 if(runtime.can_advance===false)return runtime.advance_block_label||runtime.reason_label||'当前不满足推进条件，请查看上方状态。';
 return '';
}
function controls(){
 const blocked=busy||!scope||pending.has(key(scope));
 for(const input of root.querySelectorAll('input,select,textarea'))input.disabled=busy||pending.has(key(scope));
 for(const button of root.querySelectorAll('button'))button.disabled=blocked;
 $('refresh').disabled=busy;for(const tab of root.querySelectorAll('[data-life-tab]'))tab.disabled=busy;
 for(const read of root.querySelectorAll('[data-life-read]'))read.disabled=busy||!scope;
 $('release').hidden=!pending.has(key(scope));$('release').disabled=busy||!pending.get(key(scope))?.checked;
 $('cancel').disabled=busy||pending.has(key(scope));
 $('prev').disabled=busy||section==='shares'||offset===0;$('next').disabled=busy||section==='shares'||offset+records.length>=total;
 $('models').disabled=busy;$('new').hidden=!labels[section];
 const reason=advanceBlock();$('advance').disabled=blocked||!!reason;$('advance').title=reason;
 advanceHint.textContent=reason||'可以手动评估一次；仍受日预算与最短间隔约束，路由存在不代表上游可用。';
}
async function call(method,path,body,target=scope){
 if(!target||typeof api!=='function')throw Error('先在上方选择完整的用户、角色与会话。');
 const value=await api(method,'page/autonomous-life/'+path,body);
 if(value?.ok!==true||value.backend!=='autonomous_life'||key(value.scope)!==key(target))throw Error('生活档案返回范围或格式不匹配。');
 return value;
}
function button(label,action,parent){const b=node('button',label);b.type='button';b.addEventListener('click',action);parent.append(b);return b;}
function drawRuntime(){
 const target=$('runtime');target.replaceChildren();
 if(!overview)return;
 const counts=overview.result?.counts||{};
 target.append(node('p','当前档案：'+Object.entries(counts).filter(([,v])=>typeof v==='number').map(([k,v])=>({events:'经历',characters:'人物',threads:'开放事项',shares:'分享'}[k]||k)+' '+v).join(' · '),'hint'));
 const runtime=overview.runtime;
 if(runtime){
  const banner=node('div',undefined,'life-runtime-banner');banner.dataset.state=runtime.state||'unavailable';banner.dataset.lifeRuntimeBanner='true';
  banner.append(node('strong',runtimeStates[runtime.state]||'推进状态待核对'),node('p',runtime.reason_label||'请查看当前预算与最近评估结果。'));
  const oldFailure=['failed','unknown'].includes(runtime.last_result?.state);
  const error=runtime.last_error||(oldFailure?{error_category:'unknown_error',error_type:runtime.last_result?.reason}:null);
  if(error){const parts=[errorLabels[error.error_category]||'发生未分类错误'];if(/^[A-Za-z_][A-Za-z0-9_]{0,95}$/.test(error.error_type||''))parts.push(error.error_type);if(Number.isInteger(error.http_status))parts.push('HTTP '+error.http_status);if(Number.isInteger(error.upstream_code))parts.push('服务代码 '+error.upstream_code);const text=node('p','最近错误：'+parts.join(' · '),'life-runtime-error');text.dataset.lifeRuntimeError='true';banner.append(text);}
  const budget=runtime.budget;
  const calls=budget?.model_calls,eventsBudget=budget?.events;
  const callsLimit=calls?.limit??settings?.settings?.max_model_calls_per_day;
  const eventsLimit=eventsBudget?.limit??settings?.settings?.max_events_per_day;
  const budgetText=node('p',`今日预算：模型 ${calls?.used??runtime.model_calls_today??0} / ${callsLimit??'未读取'} 次 · 新经历 ${eventsBudget?.used??runtime.events_today??0} / ${eventsLimit??'未读取'} 条`,'life-budget');budgetText.dataset.lifeBudget='true';banner.append(budgetText);
  const ids=Array.isArray(runtime.model?.provider_ids)?runtime.model.provider_ids.filter(value=>typeof value==='string'):[];
  banner.append(node('p','后台模型：'+(runtime.model?.configured===true?'渊站 · '+(ids.join(' → ')||'已配置任务路由'):'尚未配置可用的渊站模型'),'life-model'));
  banner.append(node('small',runtime.model?.availability_label||'已配置仅表示路由存在，不代表上游当前可以生成。'));
  target.append(banner);
  const details=node('details'),summary=node('summary','时间与最近评估详情');details.append(summary);
  for(const [name,label]of [['last_attempt_at','最近评估'],['next_check_at','下次检查']])if(runtime[name])details.append(node('p',label+'：'+stamp(runtime[name]),'hint'));
  if(runtime.wait_reason==='minimum_interval'&&runtime.next_eligible_at)details.append(node('p','最早可手动评估：'+stamp(runtime.next_eligible_at),'hint'));
  if(settings?.timezone)details.append(node('p','日预算时区：'+settings.timezone,'hint'));
  if(runtime.last_result?.reason&&!error)details.append(node('p','最近结果：'+String(runtime.last_result.reason).slice(0,400),'hint'));
  if(runtime.review){const review=node('details');review.append(node('summary','查看待复核提议（尚未成为经历）'),node('pre',JSON.stringify(runtime.review,null,2),'life-content'));details.append(review);}
  target.append(details);}
}
function title(record){return record.fields?.title||record.fields?.name||record.id;}
function drawList(){
 const target=$('list');target.replaceChildren();
 for(const record of records){const b=node('button',undefined,'life-card');b.type='button';b.dataset.lifeRead='true';b.dataset.selected=String(selected?.id===record.id);
  if(section==='shares'){
   b.append(node('strong','经历 '+record.event_id),node('small','投递状态：'+({candidate:'候选，尚未发送',queued:'已入队',sent:'发送器已执行',confirmed:'已有投递确认',failed:'发送失败',unknown:'结果待核对'}[record.state]||record.state)+' · '+stamp(record.at)));
   b.addEventListener('click',()=>{switchTab('event',false);detail('event',record.event_id);});
  }else{
   const f=record.fields||{};b.append(node('strong',title(record)),node('small',(states[f.status||f.kind]||'虚构资料')+(record.archived?' · 已归档':'')+(record.valid===false?' · 关联待复核':'')),node('small',stamp(f.occurred_at||record.updated_at)));
   b.addEventListener('click',()=>detail(section,record.id));
  }target.append(b);
 }
 if(!records.length)target.append(node('p',scope?'当前筛选下还没有记录。平静的一天也可以不产生新事件。':'先选择完整会话。','empty'));
 $('range').textContent=total?(section==='shares'?`最近 ${records.length} 项 / 共 ${total} 项`:`${offset+1}–${offset+records.length} / ${total}`):'0 项';controls();
}
function references(parent,label,ids,kind){if(!ids?.length)return;const box=node('div',undefined,'life-references');box.append(node('strong',label));for(const id of ids){const row=(kind==='event'?events:people).find(item=>item.id===id);button(row?title(row):id,()=>{switchTab(kind,false);detail(kind,id);},box).dataset.lifeRead='true';}parent.append(box);}
function drawDetail(history){
 const target=$('detail');target.replaceChildren();if(!selected){target.append(node('p','选择一项查看关联与修正历史。','empty'));return;}
 const record=selected,f=record.fields||{};
 target.append(node('h3',title(record)),node('p','虚构角色生活 · 修订 '+record.revision+' · '+stamp(record.updated_at),'hint'));
 if(record.valid===false)target.append(node('p','关联来源已经变化，这条记录暂不进入普通检索。请核对人物和前序经历后保存修正。','life-warning'));
 for(const field of ['content','description','relationship','detail'])if(f[field])target.append(node('p',f[field],'life-content'));
 if(f.occurred_at)target.append(node('p','发生时间：'+stamp(f.occurred_at),'hint'));
 references(target,'相关人物',f.character_ids,'character');references(target,'前序经历',f.previous_event_ids,'event');references(target,'来源经历',f.event_ids,'event');
 if(record.source){const d=node('details');d.append(node('summary','来源与记录身份'),node('p','来源类型：'+(record.source.kind||'未标明'),'hint'),node('code',record.id));target.append(d);}
 const actions=node('div',undefined,'actions');button('修正'+labels[section],()=>editor(section,record),actions);
 button(record.archived?'恢复归档':'归档',()=>mutate(section+'/'+(record.archived?'restore':'archive'),{id:record.id,expected_revision:record.revision,reason:'管理员'+(record.archived?'恢复归档':'归档')}),actions);target.append(actions);
 const h=node('details');h.append(node('summary','修正历史'));
 const rows=Array.isArray(history)?history:history?.records||history?.history||[];
  for(const row of rows){const entry=node('details');entry.append(node('summary','版本 '+(row.version??row.revision??'')+' · '+stamp(row.replaced_at||row.at||row.updated_at)),node('p',row.reason||'维护记录','hint'));const old=row.snapshot?.fields;if(old)for(const [field,text]of Object.entries(old)){if(typeof text==='string'&&text)entry.append(node('p',({title:'标题',content:'内容',name:'姓名',description:'人物说明',relationship:'关系说明',detail:'事项说明',status:'状态',kind:'类别'}[field]||field)+'：'+(states[text]||text),'life-content'));}h.append(entry);}
 if(!rows.length)h.append(node('p','尚无可显示的修正记录。','hint'));target.append(h);controls();
}
async function detail(kind,id){
 if(busy||!scope)return;const target={...scope},token=++serial;busy=true;controls();
 try{const [value,history]=await Promise.all([call('GET',kind,{...target,id},target),call('GET','history',{...target,kind,id,limit:20},target)]);
  if(token!==serial||!same(target))return;selected=value.result;section=kind;drawDetail(history.result);drawList();
 }catch(error){if(token===serial&&same(target))message(error.publicMessage||error.message,true);}finally{if(token===serial&&same(target)){busy=false;controls();}}
}
const policyFields=[['enabled','开启后台生活推进','check'],['share_enabled','允许形成主动分享候选','check'],['quiet_day_allowed','允许没有新经历的平静日','check'],['interval_minutes','正常评估间隔（分钟）','number'],['min_interval_minutes','最短评估间隔（分钟）','number'],['max_model_calls_per_day','每日模型调用上限','number'],['max_events_per_day','每日新经历上限','number'],['max_shares_per_day','每日分享上限','number']];
function drawPolicy(){const target=$('policy-fields');target.replaceChildren();for(const [name,label,type]of policyFields){const wrap=node('label',label,type==='check'?'life-check':''),input=node('input');input.dataset.policy=name;input.type=type==='check'?'checkbox':type;if(type==='check')input.checked=settings?.settings?.[name]===true;else{input.min=name.includes('interval')?'60':'0';input.max=name.includes('interval')?'10080':name==='max_shares_per_day'?'8':'24';input.step='1';input.value=settings?.settings?.[name]??'';input.required=true;}wrap.append(input);target.append(wrap);}const topics=node('label','不主动分享的话题（每行一项，最多 16 项，每项 60 字）'),text=node('textarea');text.dataset.policy='muted_topics';text.value=(settings?.settings?.muted_topics||[]).join('\n');text.maxLength=975;topics.append(text);target.append(topics);controls();}
async function load(){
 if(busy)return;scope=getScope();if(!scope){records=[];total=0;drawList();message('先在上方选择完整会话。');return;}
 const target={...scope},token=++serial;busy=true;controls();
 try{
  const query={...target,query:$('query').value.trim(),include_archived:$('archived').checked,include_invalid:$('invalid').checked,offset,limit:30};
  const path=section==='settings'?'settings':section==='shares'?'shares':plurals[section];
  const policyRead=call('GET','settings',target,target);
  const selectedId=selected?.id;
  const [current,summary,policy,refsP,refsE,detailRead]=await Promise.all([
   section==='settings'?policyRead:call('GET',path,section==='shares'?{...target,limit:100}:query,target),
   call('GET','overview',target,target),policyRead,
   call('GET','characters',{...target,limit:100},target),call('GET','events',{...target,limit:100},target),
   selectedId&&labels[section]?call('GET',section,{...target,id:selectedId},target):null]);
  if(token!==serial||!same(target))return;
  overview=summary;settings=policy.result;people=refsP.result.records||[];events=refsE.result.records||[];
  if(section!=='settings'){records=current.result.records||[];total=current.result.total??records.length;}
  if(detailRead){selected=detailRead.result;drawDetail(selected.history);}
  if(pending.has(key(target)))pending.get(key(target)).checked=true;
  drawRuntime();drawPolicy();drawList();
  message(pending.has(key(target))?'已读取服务器当前记录，请核对原操作是否生效；不会自动重发。':'已读取当前有效资料；读取没有调用模型。');
 }catch(error){if(token===serial&&same(target))message(error.publicMessage||error.message,true);}finally{if(token===serial&&same(target)){busy=false;controls();if(queuedOpen){const request=queuedOpen;queuedOpen=null;if(request.scope===key(getScope()))openLinkedRecord(request.kind,request.id);}}}
}
function input(name,label,type,value,options){
 const wrap=node('label',label),element=node(type==='textarea'?'textarea':type==='select'||type==='multiple'?'select':'input');element.dataset.field=name;
 if(element.tagName==='INPUT')element.type=type;
 if(type==='select'||type==='multiple'){element.multiple=type==='multiple';if(element.multiple)element.size=4;for(const option of options||[]){const o=node('option',option.label);o.value=option.value;o.selected=element.multiple?(value||[]).includes(option.value):value===option.value;element.append(o);}}
 else if(type==='checkbox')element.checked=value===true;
 else element.value=value??'';
 if(['title','name','content'].includes(name))element.required=true;
 const limits={title:120,name:80,content:2400,description:1200,relationship:400,detail:1200};if(limits[name])element.maxLength=limits[name];
 wrap.append(element);$('fields').append(wrap);return element;
}
function refOptions(list,selectedIds=[]){const values=list.map(row=>({value:row.id,label:title(row)}));for(const id of selectedIds)if(!values.some(v=>v.value===id))values.push({value:id,label:id+'（当前列表外）'});return values;}
function editor(kind,record=null){
 if(busy||pending.has(key(scope)))return;draftKind=kind;draftRecord=record;const f=record?.fields||{};
 $('fields').replaceChildren();$('editor-title').textContent=(record?'修正':'新增')+labels[kind];$('reason').value='';$('reason').required=!!record;$('reason').parentElement.hidden=!record;
 if(kind==='event'){
  input('title','经历标题','text',f.title);input('content','发生了什么（虚构经历）','textarea',f.content);
  const at=new Date((f.occurred_at||Date.now()/1000)*1000);at.setMinutes(at.getMinutes()-at.getTimezoneOffset());input('occurred_at','发生时间（当前设备时区）','datetime-local',at.toISOString().slice(0,16));
  input('status','状态','select',f.status||'completed',['ongoing','completed','cancelled'].map(value=>({value,label:states[value]})));
  input('character_ids','涉及人物','multiple',f.character_ids,refOptions(people,f.character_ids));
  input('previous_event_ids','前序经历','multiple',f.previous_event_ids,refOptions(events.filter(e=>e.id!==record?.id),f.previous_event_ids));
  input('share_worthy','可以成为分享候选','checkbox',f.share_worthy);
 }else if(kind==='character'){
  input('name','姓名','text',f.name);input('kind','人物类别','select',f.kind||'temporary',['canonical','recurring','temporary'].map(value=>({value,label:states[value]})));
  input('description','人物说明','textarea',f.description);input('relationship','关系说明（须有来源经历）','textarea',f.relationship);
  input('event_ids','来源经历','multiple',f.event_ids,refOptions(events,f.event_ids));
 }else{
  input('title','事项标题','text',f.title);input('detail','后续线索','textarea',f.detail);
  input('status','状态','select',f.status||'open',['open','resolved','cancelled'].map(value=>({value,label:states[value]})));
  input('event_ids','来源经历','multiple',f.event_ids,refOptions(events,f.event_ids));input('character_ids','相关人物','multiple',f.character_ids,refOptions(people,f.character_ids));
 }
 $('editor').hidden=false;$('editor').scrollIntoView({block:'nearest'});controls();
}
async function mutate(path,body){
 if(busy||!scope||pending.has(key(scope)))return;if(path==='advance'&&advanceBlock()){message(advanceBlock());return;}const target={...scope},token=++serial;
 busy=true;pending.set(key(target),{path,body,checked:false});controls();
 let failure='',outcome='';
 try{const value=await call('POST',path,{scope:target,...body},target);if(token!==serial||!same(target))return;
  pending.delete(key(target));$('editor').hidden=true;selected=null;draftRecord=null;
  if(path==='advance')outcome='评估已返回：'+(errorLabels[value.result?.error_category]||value.result?.reason||runtimeStates[value.result?.state]||'请查看服务器记录')+'。';
 }catch(error){if(token===serial&&same(target)){failure=error.publicMessage||error.message;
   if(!error.outcomeUnknown&&[400,401,403,404,409,413].includes(Number(error.status)))pending.delete(key(target));}}
 finally{if(token===serial&&same(target)){busy=false;controls();await load();if(failure)message(failure+(pending.has(key(target))?' 请刷新核对原操作，不会自动重发。':''),true);else if(outcome)message(outcome);}}
}
function switchTab(value,fetch=true){
 if(busy)return;section=value;offset=0;selected=null;draftRecord=null;records=[];total=0;$('editor').hidden=true;
 $('records').hidden=value==='settings';$('settings').hidden=value!=='settings';$('search').hidden=value==='shares';
 for(const tab of root.querySelectorAll('[data-life-tab]'))tab.setAttribute('aria-selected',String(tab.dataset.lifeTab===value));
 drawList();drawDetail();if(fetch)load();
}
for(const tab of root.querySelectorAll('[data-life-tab]'))tab.addEventListener('click',()=>switchTab(tab.dataset.lifeTab));
$('refresh').addEventListener('click',load);$('search').addEventListener('submit',event=>{event.preventDefault();offset=0;load();});
for(const name of ['archived','invalid'])$(name).addEventListener('change',()=>{offset=0;load();});
$('prev').addEventListener('click',()=>{offset=Math.max(0,offset-30);load();});$('next').addEventListener('click',()=>{offset+=30;load();});
$('new').addEventListener('click',()=>editor(section));$('cancel').addEventListener('click',()=>{$('editor').hidden=true;draftRecord=null;});
$('models').addEventListener('click',()=>setView('config'));
$('advance').addEventListener('click',()=>mutate('advance',{}));
$('release').addEventListener('click',()=>{if(pending.get(key(scope))?.checked){pending.delete(key(scope));controls();message('已结束等待；原操作仍可能稍后完成，重新修改前请核对最新记录。');}});
$('form').addEventListener('submit',event=>{event.preventDefault();try{
 const fields={};for(const element of $('fields').querySelectorAll('[data-field]'))fields[element.dataset.field]=element.multiple?[...element.selectedOptions].map(o=>o.value):element.type==='checkbox'?element.checked:element.type==='datetime-local'?Date.parse(element.value)/1000:element.value.trim();
 const reason=$('reason').value.trim();if(draftRecord&&!reason)throw Error('请说明维护原因。');
 if(draftRecord)mutate(draftKind+'/'+(draftKind==='event'?'correct':'update'),{id:draftRecord.id,expected_revision:draftRecord.revision,changes:fields,reason});
 else mutate(draftKind+'/create',{request_id:uuid(),fields});
 }catch(error){message(error.message,true);}});
$('policy').addEventListener('submit',event=>{event.preventDefault();if(!settings)return;const changes={};for(const element of root.querySelectorAll('[data-policy]'))changes[element.dataset.policy]=element.dataset.policy==='muted_topics'?element.value.split('\n').map(v=>v.trim()).filter(Boolean):element.type==='checkbox'?element.checked:Number(element.value);if(changes.muted_topics.length>16||changes.muted_topics.some(v=>v.length>60)){message('不主动分享的话题最多 16 项，每项最多 60 字。',true);return;}mutate('settings/save',{expected_revision:settings.revision,changes});});
function scopeChanged(){queuedOpen=null;scope=getScope();serial++;busy=false;selected=null;draftRecord=null;records=[];total=0;offset=0;settings=null;overview=null;people=[];events=[];$('editor').hidden=true;drawRuntime();drawPolicy();drawList();drawDetail();message(scope?'请选择分类或刷新读取当前生活档案。':'先选择完整会话。');}
function openLinkedRecord(kind,id){
 if(!labels[kind]||typeof id!=='string'||!getScope())return;
 if(busy){queuedOpen={kind,id,scope:key(getScope())};return;}
 switchTab(kind,false);void detail(kind,id);
}
global.TLSAutonomousLifePanel={activate:load,scopeChanged,openRecord:openLinkedRecord};scopeChanged();switchTab('event',false);
})(window);
