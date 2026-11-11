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
const runtimeStates={disabled:'未开启',ready:'允许尝试评估',waiting:'等待下一次评估',resting:'正在休息',quiet:'最近是平静日',needs_review:'需要复核',failed:'最近评估未完成',paused_budget:'预算暂停',budget_exhausted:'今日预算已用完',model_unavailable:'后台模型未配置',advanced:'已产生新经历',created:'已产生新经历',blocked:'暂不可推进',unavailable:'暂不可用',running:'正在评估',idle:'待评估',not_registered:'等待真实会话登记',deferred:'等待推进条件',busy:'已有评估正在进行'};
const errorLabels={provider_restricted:'模型服务限制了这次请求',provider_access_denied:'模型服务拒绝访问',provider_authentication:'模型服务认证失败',provider_rate_limited:'模型服务限流',provider_timeout:'模型服务响应超时',provider_connection:'无法连接模型服务',provider_unavailable:'模型服务暂不可用',invalid_model_output:'模型返回内容无法解析',invalid_life_record:'生成的生活资料需要复核',runtime_permission:'当前来源或权限已变化',unknown_result:'请求结束状态尚未确认',unknown_error:'发生未分类错误'};
const stamp=value=>typeof value==='number'&&Number.isFinite(value)?new Date(value*1000).toLocaleString():'尚无记录';
let queuedOpen=null,historyView=null;
let scope=null,section='event',selected=null,records=[],total=0,offset=0,serial=0,busy=false;
let settings=null,overview=null,people=[],events=[],draftKind=null,draftRecord=null,listState='unread';
const pending=new Map();
root.innerHTML=`<section class="panel autonomous-life"><div class="panel-head"><div><h2>生活档案</h2><p class="hint">角色在虚构世界中的经历、熟人与未完事项。它们与真实聊天、手机感知分别保存。</p></div><button type="button" data-life-refresh>刷新与核对</button></div><p data-life-status role="status" aria-live="polite"></p><div data-life-runtime class="life-runtime"></div><div class="life-tabs" role="tablist"><button data-life-tab="event" role="tab">近期经历</button><button data-life-tab="character" role="tab">人物</button><button data-life-tab="thread" role="tab">开放事项</button><button data-life-tab="shares" role="tab">分享记录</button><button data-life-tab="settings" role="tab">推进设置</button></div><div data-life-records><form data-life-search class="life-toolbar"><label>查找<input data-life-query maxlength="200" placeholder="标题、人物或经历关键词"></label><button type="submit">搜索</button><label class="life-check"><input data-life-archived type="checkbox">含归档</label><label class="life-check"><input data-life-invalid type="checkbox">含待复核</label><button type="button" data-life-new>新增</button></form><div class="life-columns"><div><div data-life-list></div><div class="actions"><button data-life-prev type="button">上一页</button><span data-life-range></span><button data-life-next type="button">下一页</button></div></div><section data-life-detail><p class="empty">选择一项查看关联与修正历史。</p></section></div></div><section data-life-settings hidden><form data-life-policy><div data-life-policy-fields class="life-policy-grid"></div><div class="actions"><button type="submit" class="primary">保存推进设置</button><button data-life-models type="button">设置后台模型</button><button data-life-advance type="button">现在评估一次生活推进</button></div><p class="hint">后台推进独立于即时聊天；预算与静默日判断由服务器执行。分享只是候选，发送仍遵守原有主动陪伴权限、频率与可打扰时段。</p><p class="hint">“现在评估”可能使用已经配置的后台模型，且需要真实会话授权；不会重放停机期间的日记。</p></form></section><div class="actions"><button data-life-release type="button" hidden>已核对，结束本次等待</button></div></section><section class="panel autonomous-life" data-life-editor hidden><div class="panel-head"><h2 data-life-editor-title></h2><button data-life-cancel type="button">取消编辑</button></div><form data-life-form><div data-life-fields class="life-edit-grid"></div><label>维护原因<input data-life-reason maxlength="400" required></label><div class="actions"><button class="primary" type="submit">保存并回读</button></div></form><p class="hint">修正会保留原版本。依赖旧版本的记录需要复核后才能重新进入普通检索，不会改写真实聊天。</p></section>`;
const $=name=>root.querySelector('[data-life-'+name+']');
$('models').textContent='全局后台任务配置';
const same=target=>key(target)===key(scope)&&key(target)===key(getScope());
const message=(text,error=false)=>{$('status').textContent=text;$('status').dataset.error=String(error);};
const advanceHint=node('p',undefined,'hint life-advance-hint');advanceHint.dataset.lifeAdvanceHint='true';$('advance').parentElement.after(advanceHint);
const impact=node('section',undefined,'life-correction-impact');impact.hidden=true;impact.dataset.lifeImpact='true';
const impactRead=node('button','查看这次修正会影响哪些资料');impactRead.type='button';impactRead.dataset.lifeRead='true';
const impactResult=node('div');impactResult.setAttribute('role','status');impact.append(impactRead,impactResult);$('editor').querySelector('form').before(impact);
impactRead.addEventListener('click',()=>readCorrectionImpact());
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
 for(const button of root.querySelectorAll('[data-history-read]'))button.disabled=busy||!scope||historyView?.loading===true;
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
const capacityNames={event:'经历',character:'人物',thread:'开放事项',space:'私人空间',item:'私人物品',interest:'兴趣',exploration:'探索记录',collection:'个人收藏'};
function drawCapacity(parent,capacity){
 const details=node('details',undefined,'life-capacity');details.dataset.lifeCapacity='true';
 details.append(node('summary','当前范围资料容量'));
 const fields=['total','active','archived','deleted','limit','remaining'];
 const rows=Object.keys(capacityNames).map(kind=>(Array.isArray(capacity?.kinds)?capacity.kinds:[]).find(row=>row.kind===kind));
 const available=capacity?.scope_only===true&&rows.every(row=>row&&fields.every(name=>Number.isSafeInteger(row[name])&&row[name]>=0));
 if(!available){details.append(node('p','当前服务尚未提供完整的范围容量，不能按零占用判断；已有档案仍可查看。','hint'));parent.append(details);return;}
 for(const row of rows){
  if(row.total===0||row.limit===0||row.total<row.limit*.8)continue;
  const full=row.remaining===0,warning=node('p',capacityNames[row.kind]+(full?'已达到保留上限':'接近保留上限')+'（'+row.total+' / '+row.limit+'，剩余 '+row.remaining+'）。'+(full?'新增该类记录会受限，其他功能仍按各自容量与原有规则运行。':'可在原分类中查看和维护资料；归档不会释放名额。'),'life-warning');
  warning.dataset.lifeCapacityWarning=row.kind;parent.append(warning);
 }
 const totals=capacity.totals;
 if(totals&&fields.every(name=>Number.isSafeInteger(totals[name])&&totals[name]>=0))details.append(node('p','八类资料合计：'+totals.total+' / '+totals.limit+'，剩余 '+totals.remaining+' 个实体名额。这是各类限额合计，名额不能跨类别调配。','hint'));
 if(typeof capacity.as_of==='number')details.append(node('p','读取时间：'+stamp(capacity.as_of),'hint'));
 const grid=node('div',undefined,'life-capacity-grid');
 for(const row of rows){const card=node('section',undefined,'life-capacity-card');card.dataset.lifeCapacityKind=row.kind;
  card.append(node('h4',capacityNames[row.kind]),node('strong',row.total+' / '+row.limit+' · 剩余 '+row.remaining),node('p','未归档 '+row.active+' · 已归档 '+row.archived+' · 软删除 '+row.deleted,'hint'));grid.append(card);}
 details.append(grid,node('p','“未归档”指未归档且未删除，不等于关联有效或事项仍在进行；三项互斥计数，软删除优先。','hint'),node('p','归档和软删除保留原记录与历史，不释放名额。这里只显示当前用户、角色和会话的实体容量；剩余名额不保证共享 Journal 仍有足够写入空间。','hint'));
 parent.append(details);
}
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
  const timing=runtime.timing,next=runtime.next_automatic_at;
  const timeText=!timing?'暂未提供预计时间；保存的检查时刻不代表会自动执行。':typeof next!=='number'?'暂不能估计，请查看当前阻碍。':next<=timing.as_of?'已到可评估时间，仍需满足会话、预算和模型条件。':(timing.next_automatic_at_local?.replace('T',' ')||stamp(next))+'；满足条件后才会评估。';
  const nextTime=node('p','最早可再评估：'+timeText,'hint');nextTime.dataset.lifeNextEvaluation='true';banner.append(nextTime);
  banner.append(node('small','这里只表示预算、休息与间隔允许的最早时间，不保证届时调用或模型成功。'));
  const ids=Array.isArray(runtime.model?.provider_ids)?runtime.model.provider_ids.filter(value=>typeof value==='string'):[];
  banner.append(node('p','后台模型：'+(runtime.model?.configured===true?(ids.join(' → ')||'已配置后台任务路由'):'尚未配置可用的后台模型'),'life-model'));
  if(runtime.model?.route_scope)banner.append(node('small',runtime.model.route_scope==='character'?'使用当前角色独立的后台模型配置。':'继承后台“自主生活”任务配置；不继承普通聊天模型。'));
  banner.append(node('small',runtime.model?.availability_label||'已配置仅表示路由存在，不代表上游当前可以生成。'));
  target.append(banner);
  const choice=runtime.action_controls;
  if(Number.isSafeInteger(choice?.revision)){
   const controlsBox=node('section',undefined,'life-choice-controls');controlsBox.dataset.lifeChoiceControls='true';
   controlsBox.append(node('h3','自主行动节奏'),node('p',choice.rest?.active?'正在休息，至 '+stamp(choice.rest.until)+'。':'当前没有手动休息安排。','hint'));
   const actions=node('div',undefined,'actions');
   button(choice.rest?.active?'结束休息，恢复原计划':'休息两小时',()=>changeAction(choice.rest?.active?'restart':'rest'),actions);
   controlsBox.append(actions,node('p','只调整当前角色的行动安排；不增加预算，不清除待核对结果，也不会立即调用模型或发送消息。','hint'));
   const recent=Array.isArray(choice.recent_actions)?choice.recent_actions.slice(0,5):[];
   if(recent.length){const history=node('details');history.append(node('summary','最近行动调整'));for(const row of recent)history.append(node('p',({rest:'休息',defer:'延后事项',restart:'恢复计划'}[row.action]||'行动调整')+' · '+stamp(row.at)+(row.reason?' · '+row.reason:''),'hint'));controlsBox.append(history);}
   target.append(controlsBox);
  }
  const details=node('details'),summary=node('summary','时间与最近评估详情');details.append(summary);
  for(const [name,label]of [['last_attempt_at','最近评估'],['next_check_at','上次保存的检查时间（历史调度值）']])if(runtime[name])details.append(node('p',label+'：'+stamp(runtime[name]),'hint'));
  if(runtime.manual_retry_available)details.append(node('p','上次模型服务明确返回不可用。处理通道后可以手动重试，仍计入今日额度；自动评估继续遵守原间隔。','hint'));
  else if(runtime.wait_reason==='minimum_interval'&&runtime.next_eligible_at&&(!runtime.advance_block_reason||runtime.advance_block_reason==='minimum_interval'))details.append(node('p','最早可手动评估：'+stamp(runtime.next_eligible_at),'hint'));
  if(runtime.timing?.timezone||settings?.timezone)details.append(node('p','日预算时区：'+(runtime.timing?.timezone||settings.timezone),'hint'));
  if(runtime.last_result?.reason&&!error)details.append(node('p','最近结果：'+String(runtime.last_result.reason).slice(0,400),'hint'));
  if(runtime.review){const review=node('details');review.append(node('summary','查看待复核提议（尚未成为经历）'),node('pre',JSON.stringify(runtime.review,null,2),'life-content'));details.append(review);}
  target.append(details);}
 drawCapacity(target,overview.result?.capacity);
}
function title(record){return record.fields?.title||record.fields?.name||record.id;}
function drawList(){
 const target=$('list');target.replaceChildren();
 if(listState==='error')target.append(node('p',records.length?'本次未能读取，以下是上次已读取的记录；当前状态尚未确认。':'未能读取当前资料，不能据此判断没有记录。请查看上方错误并手动刷新。','life-warning'));
 for(const record of records){const b=node('button',undefined,'life-card');b.type='button';b.dataset.lifeRead='true';b.dataset.selected=String(selected?.id===record.id);
  if(section==='shares'){
   b.append(node('strong','经历 '+record.event_id),node('small','投递状态：'+({candidate:'候选，尚未发送',queued:'已入队',sent:'发送器已执行',confirmed:'已有投递确认',failed:'发送失败',unknown:'结果待核对'}[record.state]||record.state)+' · '+stamp(record.at)));
   b.addEventListener('click',()=>{switchTab('event',false);detail('event',record.event_id);});
  }else{
   const f=record.fields||{};b.append(node('strong',title(record)),node('small',(states[f.status||f.kind]||'虚构资料')+(record.archived?' · 已归档':'')+(record.valid===false?' · 关联待复核':'')),node('small',stamp(f.occurred_at||record.updated_at)));
   b.addEventListener('click',()=>detail(section,record.id));
  }target.append(b);
 }
 if(!records.length&&listState!=='error')target.append(node('p',!scope?'先选择完整会话。':listState==='ready'?'当前筛选下还没有记录。私人空间、兴趣与聊天记忆分别保存，不会自动补成生活经历。':listState==='loading'?'正在读取当前资料…':'尚未读取当前资料，请选择分类或刷新。','empty'));
 $('range').textContent=listState!=='ready'?(listState==='error'?'本次未确认':'等待读取'):total?(section==='shares'?`最近 ${records.length} 项 / 共 ${total} 项`:`${offset+1}–${offset+records.length} / ${total}`):'0 项';controls();
}
function references(parent,label,ids,kind){if(!ids?.length)return;const box=node('div',undefined,'life-references');box.append(node('strong',label));for(const id of ids){const row=(kind==='event'?events:people).find(item=>item.id===id);button(row?title(row):id,()=>{switchTab(kind,false);detail(kind,id);},box).dataset.lifeRead='true';}parent.append(box);}
function startHistory(data,host,recordKind,record){
 const rows=Array.isArray(data)?data:data?.records||data?.history||[];
 const paged=Number.isSafeInteger(data?.current_revision)&&Number.isSafeInteger(data?.offset)&&Number.isSafeInteger(data?.limit)&&Number.isSafeInteger(data?.total);
 historyView={host,kind:recordKind,id:record.id,rows,paged,revision:data?.current_revision,total:data?.total??rows.length,next:paged?data.offset+data.limit:rows.length,loading:false,error:'',stale:paged&&data.current_revision!==record.revision};
 paintHistory(historyView);
}
function paintHistory(view){
 const host=view.host,opened=new Set([...host.querySelectorAll('[data-history-row][open]')].map(row=>row.dataset.historyRow));host.replaceChildren();
 host.append(node('p',view.paged?'已显示 '+view.rows.length+' / '+view.total+' 条旧版本 · 基于修订 '+view.revision:'已显示 '+view.rows.length+' 条旧版本；当前服务未提供分页信息，不能确认已读取全部历史。','hint'));
 for(const row of view.rows){
  const entry=node('details');entry.dataset.historyRow=String(row.revision??row.version);entry.open=opened.has(entry.dataset.historyRow);
  entry.append(node('summary','版本 '+(row.version??row.revision??'')+' · '+stamp(row.replaced_at||row.at||row.updated_at)),node('p',row.reason||'资料维护','hint'));
  const old=row.snapshot?.fields;if(old)for(const [field,text]of Object.entries(old)){if(typeof text==='string'&&text)entry.append(node('p',({title:'标题',content:'内容',name:'姓名',description:'人物说明',relationship:'关系说明',detail:'事项说明',status:'状态',kind:'类别'}[field]||field)+'：'+(states[text]||text),'life-content'));}
  host.append(entry);
 }
 if(!view.rows.length)host.append(node('p','尚无可显示的修正记录。','hint'));
 if(view.stale)host.append(node('p','资料已发生修正；已读历史保留，请从最新版本重新读取后继续。','life-warning'));
 if(view.error)host.append(node('p',view.error+' 已读历史和编辑草稿保留。','life-warning'));
 const actions=node('div',undefined,'actions');
 if(view.paged&&!view.stale&&view.next<view.total)button('查看更多旧版本',()=>loadHistory(false),actions);
 if(view.stale||view.error||!view.paged)button('从最新版本重新读取',()=>loadHistory(true),actions);
 for(const button of actions.querySelectorAll('button')){button.dataset.historyRead='true';button.disabled=view.loading||busy||!scope;}
 if(view.loading)actions.append(node('span','正在读取旧版本…','hint'));host.append(actions);
}
async function loadHistory(reset){
 const view=historyView;if(busy||!scope||!view||view.loading||!view.host.isConnected)return;
 const target={...scope},token=serial,requestedOffset=reset?0:view.next;
 const query={...target,kind:view.kind,id:view.id,limit:20,offset:requestedOffset};if(!reset)query.expected_revision=view.revision;
 view.loading=true;view.error='';paintHistory(view);
 const current=()=>historyView===view&&token===serial&&same(target)&&selected?.id===view.id&&view.host.isConnected;
 try{
  const result=(await call('GET','history',query,target)).result;if(!current())return;
  const paged=Number.isSafeInteger(result?.current_revision)&&Number.isSafeInteger(result?.offset)&&Number.isSafeInteger(result?.limit)&&Number.isSafeInteger(result?.total);
  if(!Array.isArray(result?.records)||!reset&&(!paged||result.offset!==requestedOffset||result.current_revision!==view.revision))throw Error('历史分页未对应当前记录，请重新读取。');
  if(paged&&(result.offset!==requestedOffset||result.limit!==20))throw Error('历史分页范围不匹配。');
  view.rows=reset?result.records:view.rows.concat(result.records);view.paged=paged;view.revision=result.current_revision;view.total=result.total??view.rows.length;view.next=paged?result.offset+result.limit:view.rows.length;view.stale=false;
 }catch(error){if(current()){view.stale=Number(error.status)===409;view.error=view.stale?'翻页期间资料发生了变化。':error.publicMessage||error.message;}}
 finally{if(current()){view.loading=false;paintHistory(view);}}
}

function drawDetail(history){
 const target=$('detail');target.replaceChildren();if(!selected){target.append(node('p','选择一项查看关联与修正历史。','empty'));return;}
 const record=selected,f=record.fields||{};
 target.append(node('h3',title(record)),node('p','虚构角色生活 · 修订 '+record.revision+' · '+stamp(record.updated_at),'hint'));
 if(record.valid===false)target.append(node('p','关联来源已经变化，这条记录暂不进入普通检索。请核对人物和前序经历后保存修正。','life-warning'));
 for(const field of ['content','description','relationship','detail'])if(f[field])target.append(node('p',f[field],'life-content'));
 if(f.occurred_at)target.append(node('p','发生时间：'+stamp(f.occurred_at),'hint'));
 references(target,'相关人物',f.character_ids,'character');references(target,'前序经历',f.previous_event_ids,'event');references(target,'来源经历',f.event_ids,'event');
 if(record.source){const d=node('details');d.append(node('summary','来源与记录身份'),node('p','来源类型：'+(record.source.kind||'未标明'),'hint'),node('code',record.id));target.append(d);}
 const actions=node('div',undefined,'actions');if(section==='event')button('查看世界线',()=>worldline(record.id),actions).dataset.lifeRead='true';button('修正'+labels[section],()=>editor(section,record),actions);
 button(record.archived?'恢复归档':'归档',()=>mutate(section+'/'+(record.archived?'restore':'archive'),{id:record.id,expected_revision:record.revision,reason:'管理员'+(record.archived?'恢复归档':'归档')}),actions);target.append(actions);
 if(section==='thread'&&record.valid!==false&&!record.archived&&f.status==='open'&&Number.isSafeInteger(overview?.runtime?.action_controls?.revision)){
  const deferred=(overview.runtime.action_controls.deferred||[]).find(row=>row.kind==='thread'&&row.id===record.id&&row.valid!==false&&!row.stale&&row.until>Date.now()/1000);
  if(deferred)target.append(node('p','这项事项暂缓至 '+stamp(deferred.until)+'；内容和来源仍保留。','hint'));
  button(deferred?'继续这件事':'这件事延后一天',()=>changeAction(deferred?'restart':'defer',record),actions);
 }
 const h=node('details');h.append(node('summary','修正历史'));
 const host=node('div');h.append(host);target.append(h);startHistory(history,host,section,record);controls();
}

const worldNames={event:'经历',character:'人物',thread:'事项',interest:'兴趣',exploration:'探索',collection:'收藏',space:'空间',item:'物件'};
const worldValue=value=>Array.isArray(value)?value.join('；'):({steady:'持续关注',growing:'兴趣渐浓',fading:'兴趣渐淡',active:'进行中',paused:'暂时搁置',completed:'已完成',planned:'待探索',cancelled:'已取消'}[value]||value||'未记录');
const worldEdges={continues:'延续为',involves:'参与',grounds:'成为来源',explores:'继续探索',collects:'相关收藏',contains:'包含'};
function worldOpen(row){if(labels[row.kind]){switchTab(row.kind,false);void detail(row.kind,row.id);}else if(global.TLSPersonalSpacePanel){setView('personal_space');global.TLSPersonalSpacePanel.openRecord(row.kind,row.id);}}
async function worldline(id){
 if(busy||!scope)return;const target={...scope},token=++serial;busy=true;controls();message('正在读取明确关联…');
 try{
  const value=await call('GET','worldline',{...target,event_id:id},target);if(token!==serial||!same(target))return;
  const graph=value.result;if(graph?.event_id!==id||!Array.isArray(graph.nodes)||!Array.isArray(graph.edges))throw Error('世界线数据未对应所选经历。');
  const box=$('detail');box.replaceChildren();box.append(node('h3','世界线与有来源的变化'),node('p','只连接已有资料中的明确关系，不因时间相近推断因果。','hint'));
  button('返回经历',()=>detail('event',id),box).dataset.lifeRead='true';
  const nodes=new Map(graph.nodes.map(row=>[row.id,row]));
  for(const row of graph.nodes){
   const item=node('section',undefined,'life-world-node');button((worldNames[row.kind]||'资料')+' · '+row.title,()=>worldOpen(row),item).dataset.lifeRead='true';
   if(row.summary)item.append(node('p',row.summary,'life-content'));
   if(row.valid===false||row.archived)item.append(node('p','来源已变化或归档 · 待复核，不作为有效前情','life-warning'));
   for(const edge of graph.edges.filter(e=>e.from===row.id)){const other=nodes.get(edge.to);if(other)item.append(node('p',(worldEdges[edge.relation]||'关联')+' → '+other.title+(edge.valid===false?'（待复核）':''),'hint'));}
   box.append(item);
  }
  const growth=node('section',undefined,'life-world-growth');growth.append(node('h4','有来源的变化'));
  for(const row of graph.growth||[]){const item=node('section',undefined,'life-world-node');item.append(node('strong',row.title),node('p',({relationship:'人物关系',attention:'关注变化',status:'状态',findings:'探索发现',next_direction:'下一方向'}[row.field]||row.field)+'：'+worldValue(row.before)+' → '+worldValue(row.after),'life-content'));
   for(const sourceId of row.source_event_ids||[])button('来源：'+(nodes.get(sourceId)?.title||'相关经历'),()=>detail('event',sourceId),item).dataset.lifeRead='true';
   if(row.valid===false)item.append(node('p','关联来源待复核','life-warning'));growth.append(item);}
  if(!(graph.growth||[]).length)growth.append(node('p','没有可展示的有来源变化；普通经历不会自动改写核心人格。','hint'));box.append(growth);
  if(graph.coverage?.truncated)box.append(node('p','关系较多，只显示有限的附近关系；可进入具体资料继续维护。','hint'));
  message('世界线来自同一份生活账本；本次读取没有调用模型。');
 }catch(error){if(token===serial&&same(target))message(error.publicMessage||error.message,true);}
 finally{if(token===serial&&same(target)){busy=false;controls();drainOpen();}}
}
async function detail(kind,id){
 if(busy||!scope)return;const target={...scope},token=++serial;busy=true;controls();
 try{const [value,history]=await Promise.all([call('GET',kind,{...target,id},target),call('GET','history',{...target,kind,id,limit:20},target)]);
  if(token!==serial||!same(target))return;selected=value.result;section=kind;drawDetail(history.result);drawList();
 }catch(error){if(token===serial&&same(target))message(error.publicMessage||error.message,true);}finally{if(token===serial&&same(target)){busy=false;controls();drainOpen();}}
}
const policyFields=[['enabled','开启后台生活推进','check'],['share_enabled','允许形成主动分享候选','check'],['quiet_day_allowed','允许没有新经历的平静日','check'],['interval_minutes','正常评估间隔（分钟）','number'],['min_interval_minutes','最短评估间隔（分钟）','number'],['max_model_calls_per_day','每日模型调用上限','number'],['max_events_per_day','每日新经历上限','number'],['max_shares_per_day','每日分享上限','number']];
function drawPolicy(){const target=$('policy-fields');target.replaceChildren();for(const [name,label,type]of policyFields){const wrap=node('label',label,type==='check'?'life-check':''),input=node('input');input.dataset.policy=name;input.type=type==='check'?'checkbox':type;if(type==='check')input.checked=settings?.settings?.[name]===true;else{input.min=name.includes('interval')?'60':'0';input.max=name.includes('interval')?'10080':name==='max_shares_per_day'?'8':'24';input.step='1';input.value=settings?.settings?.[name]??'';input.required=true;}wrap.append(input);target.append(wrap);}
 const providers=Array.isArray(overview?.runtime?.model?.providers)?overview.runtime.model.providers:[];
 for(const [name,label]of [['model_provider_id','当前角色的后台首选模型'],['model_fallback_provider_id','当前角色的后台备选模型（可选）']]){
  const wrap=node('label',label),select=node('select'),saved=settings?.settings?.[name]||'';select.dataset.policy=name;
  const inherit=node('option',name==='model_provider_id'?'继承后台“自主生活”任务配置':'留空');inherit.value='';select.append(inherit);
  const ids=new Set();for(const provider of providers){if(!provider||typeof provider.id!=='string'||!provider.id||ids.has(provider.id))continue;ids.add(provider.id);const option=node('option',provider.id+(provider.model&&provider.model!==provider.id?' · '+provider.model:''));option.value=provider.id;select.append(option);}
  if(saved&&!ids.has(saved)){const unavailable=node('option','已保存但当前不可用 · '+saved);unavailable.value=saved;unavailable.dataset.unavailable='true';select.append(unavailable);}
  select.value=saved;wrap.append(select);target.append(wrap);
 }
 const modelNote=node('p','首选留空时继承后台“自主生活”的显式任务配置；首选已选、备选留空时只尝试首选。这里不修改普通聊天模型，也不影响其他角色。','hint');modelNote.dataset.lifeModelPolicyNote='true';target.append(modelNote);
 const topics=node('label','不主动分享的话题（每行一项，最多 16 项，每项 60 字）'),text=node('textarea');text.dataset.policy='muted_topics';text.value=(settings?.settings?.muted_topics||[]).join('\n');text.maxLength=975;topics.append(text);target.append(topics);controls();}
async function load(){
 if(busy)return;scope=getScope();if(!scope){records=[];total=0;drawList();message('先在上方选择完整会话。');return;}
 const target={...scope},token=++serial;busy=true;listState='loading';drawList();controls();message('正在读取当前生活档案…');
 try{
  const query={...target,query:$('query').value.trim(),include_archived:$('archived').checked,include_invalid:$('invalid').checked,offset,limit:30};
  const path=section==='settings'?'settings':section==='shares'?'shares':plurals[section];
  const policyRead=call('GET','settings',target,target);
  const selectedId=selected?.id;
  const [current,summary,policy,refsP,refsE,detailRead,historyRead]=await Promise.all([
   section==='settings'?policyRead:call('GET',path,section==='shares'?{...target,limit:100}:query,target),
   call('GET','overview',target,target),policyRead,
   call('GET','characters',{...target,limit:100},target),call('GET','events',{...target,limit:100},target),
   selectedId&&labels[section]?call('GET',section,{...target,id:selectedId},target):null,
   selectedId&&labels[section]?call('GET','history',{...target,kind:section,id:selectedId,limit:20},target):null]);
  if(token!==serial||!same(target))return;
  listState='ready';overview=summary;settings=policy.result;people=refsP.result.records||[];events=refsE.result.records||[];
  if(section!=='settings'){records=current.result.records||[];total=current.result.total??records.length;}
  if(detailRead){selected=detailRead.result;drawDetail(historyRead.result);}
  if(pending.has(key(target)))pending.get(key(target)).checked=true;
  drawRuntime();drawPolicy();drawList();
  message(pending.has(key(target))?'已读取服务器当前记录，请核对原操作是否生效；不会自动重发。':'已读取当前有效资料；读取没有调用模型。');
 }catch(error){if(token===serial&&same(target)){listState='error';drawList();message(error.publicMessage||error.message,true);}}finally{if(token===serial&&same(target)){busy=false;controls();drainOpen();}}
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
function changeAction(action,record=null){
 const choice=overview?.runtime?.action_controls;
 if(!Number.isSafeInteger(choice?.revision)||busy||pending.has(key(scope)))return;
 const body={action,request_id:uuid(),expected_revision:choice.revision,reason:action==='rest'?'管理员安排短暂休息':action==='defer'?'管理员将当前事项延后一天':'管理员恢复原行动安排'};
 if(record)Object.assign(body,{target_kind:'thread',target_id:record.id,expected_target_revision:record.revision});
 if(action==='rest')body.minutes=120;if(action==='defer')body.minutes=1440;
 void mutate('actions/control',body);
}
function editor(kind,record=null){
 if(busy||pending.has(key(scope)))return;draftKind=kind;draftRecord=record;const f=record?.fields||{};
 impact.hidden=kind!=='event'||!record;impactResult.replaceChildren();
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
async function readCorrectionImpact(){
 if(busy||draftKind!=='event'||!draftRecord||!scope)return;
 const target={...scope},record=draftRecord,token=++serial;busy=true;controls();impactResult.replaceChildren(node('p','正在读取这条经历的来源依赖…','hint'));
 try{
  const result=(await call('GET','event/impact',{...target,event_id:record.id},target)).result;
  if(token!==serial||!same(target)||draftRecord!==record)return;
  if(result?.root_event_id!==record.id||result.root_revision!==record.revision||!Array.isArray(result.direct)||!Array.isArray(result.indirect))throw Error('经历版本或影响范围已变化，请保留当前输入，重新核对原记录后再决定修正。');
  impactResult.replaceChildren(node('p','直接关联 '+result.direct.length+' 项，继续依赖它们的资料 '+result.indirect.length+' 项。修正后需要按新来源复核。','hint'));
  for(const [label,rows] of [['直接关联',result.direct],['后续关联',result.indirect]]){
   if(!rows.length)continue;const list=node('ul');list.setAttribute('aria-label',label);
   for(const row of rows.slice(0,30))list.append(node('li',(worldNames[row.kind]||'资料')+' · '+(row.title||'未命名资料')+(row.valid===false?'（已经待复核）':'')));
   impactResult.append(node('h4',label),list);if(rows.length>30)impactResult.append(node('p','另有 '+(rows.length-30)+' 项；可在世界线与关联待复核中继续查看。','hint'));
  }
  impactResult.append(node('p','这里只查看当前留存记录的明确依赖；尚未保存修正，不改写聊天历史。','hint'));
 }catch(error){if(token===serial&&same(target))impactResult.replaceChildren(node('p',error.publicMessage||error.message,'life-warning'));}
 finally{if(token===serial&&same(target)){busy=false;controls();drainOpen();}}
}
function drainOpen(){
 const request=queuedOpen;queuedOpen=null;
 if(request&&request.scope===key(getScope())&&state.view==='autonomous_life'){if(request.section)openSection(request.section);else openLinkedRecord(request.kind,request.id);}
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
 if(busy)return;section=value;offset=0;selected=null;draftRecord=null;records=[];total=0;listState='unread';$('editor').hidden=true;
 $('records').hidden=value==='settings';$('settings').hidden=value!=='settings';$('search').hidden=value==='shares';
 for(const tab of root.querySelectorAll('[data-life-tab]'))tab.setAttribute('aria-selected',String(tab.dataset.lifeTab===value));
 drawList();drawDetail();global.dispatchEvent(new CustomEvent('tls-admin-sectionchange',{detail:{view:'autonomous_life',section:value}}));if(fetch)load();
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
$('policy').addEventListener('submit',event=>{event.preventDefault();if(!settings)return;const changes={};for(const element of root.querySelectorAll('[data-policy]'))changes[element.dataset.policy]=element.dataset.policy==='muted_topics'?element.value.split('\n').map(v=>v.trim()).filter(Boolean):element.tagName==='SELECT'?element.value:element.type==='checkbox'?element.checked:Number(element.value);if(changes.muted_topics.length>16||changes.muted_topics.some(v=>v.length>60)){message('不主动分享的话题最多 16 项，每项最多 60 字。',true);return;}if(changes.model_fallback_provider_id&&!changes.model_provider_id){message('选择独立的备选模型前，请先选择当前角色的首选模型；两项都留空才会继承后台任务配置。',true);return;}if(changes.model_provider_id&&changes.model_provider_id===changes.model_fallback_provider_id){message('首选和备选请选择不同模型，或将备选留空。',true);return;}mutate('settings/save',{expected_revision:settings.revision,changes});});
function scopeChanged(){listState='unread';queuedOpen=null;scope=getScope();serial++;busy=false;selected=null;draftRecord=null;records=[];total=0;offset=0;settings=null;overview=null;people=[];events=[];$('editor').hidden=true;drawRuntime();drawPolicy();drawList();drawDetail();message(scope?'请选择分类或刷新读取当前生活档案。':'先选择完整会话。');}
function openLinkedRecord(kind,id){
 if(!labels[kind]||typeof id!=='string'||!getScope())return;
 if(busy){queuedOpen={kind,id,scope:key(getScope())};return;}
 switchTab(kind,false);void detail(kind,id);
}
function openSection(value){
 if(!labels[value]&&!['shares','settings'].includes(value))return false;
 if(!$('editor').hidden&&value!==section){message('编辑内容仍保留。请先保存或取消当前编辑，再切换工作区域。',true);return false;}
 if(busy){queuedOpen={section:value,scope:key(getScope())};return true;}
 if(section===value){if(listState==='unread')void load();return true;}
 switchTab(value);return true;
}
global.TLSAutonomousLifePanel={activate:load,scopeChanged,openRecord:openLinkedRecord,openSection};scopeChanged();switchTab('event',false);
})(window);
