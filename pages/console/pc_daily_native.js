/* One view of the real native daily lifecycle; no local execution/ownership. */
(function (global) {
  'use strict';
  const root = document.getElementById('pc-daily-native-mount');
  if (!root) return;
  const fields = ['platform', 'bot_id', 'user_id', 'character_id', 'session_id'];
  const labels = {auto_generate:'自动准备未来目标计划',auto_progress:'到时记为虚构活动并推进目标',share_enabled:'使用现有陪伴通道分享有来源的目标进展',routine_enabled:'同时安排独立的虚构日常'};
  const pending = new Map();
  let scope=null,snapshot=null,busy=false,serial=0,lastOutcome='';
  const signature=value=>JSON.stringify(fields.map(key=>value&&value[key]));
  const currentScope=()=>typeof state==='object'&&state.scope&&fields.every(key=>typeof state.scope[key]==='string'&&state.scope[key])?Object.fromEntries(fields.map(key=>[key,state.scope[key]])):null;
  const current=(at,turn)=>turn===serial&&signature(at)===signature(scope)&&signature(at)===signature(currentScope());
  const text=(tag,content,className)=>{const result=document.createElement(tag);result.textContent=content;if(className)result.className=className;return result;};
  root.innerHTML='<section class="panel pc-daily-native"><div class="panel-head"><h2>角色日常与目标自动推进</h2><button type="button" data-pcd-refresh>刷新状态</button></div><p data-pcd-notice role="status">选择真实用户、角色和会话后查看。</p><div data-pcd-summary></div><form data-pcd-settings><div data-pcd-flags></div><button type="submit" class="primary" data-pcd-save>保存本范围设置</button></form><div class="pc-daily-native-actions"><label>角色日期<input type="date" data-pcd-day></label><button type="button" data-pcd-goals>准备目标计划</button><button type="button" data-pcd-routines>准备虚构日常</button><button type="button" data-pcd-tick>核对并推进一次</button></div><p class="hint">仅对有真实会话来源的新计划执行。旧无归属日计划保留，不按昵称猜归属；虚构活动不是现实观察。分享沿现有队列、冷却和发送确认，确认后才记录已分享。</p><div data-pcd-result></div></section>';
  const find=name=>root.querySelector('[data-pcd-'+name+']');
  find('day').parentElement.firstChild.textContent='角色日期（留空按服务器今天）';
  const plansButton=text('button','查看目标日计划');plansButton.type='button';plansButton.dataset.pcdPlans='true';
  plansButton.addEventListener('click',()=>{if(global.TLSAdminWorkspace)global.TLSAdminWorkspace.navigate('scoped_daily_plan');else if(typeof setView==='function')setView('scoped_daily_plan');});
  find('result').before(plansButton);
  for(const [key,label] of Object.entries(labels)){const line=text('label','','pc-daily-native-check'),input=document.createElement('input');input.type='checkbox';input.name=key;line.append(input,document.createTextNode(label));find('flags').append(line);}
  function notice(message,error){find('notice').textContent=message;find('notice').classList.toggle('pc-daily-native-error',!!error);}
  function controls(){
    const locked=busy||pending.has(signature(scope)),live=!!snapshot&&!!scope&&signature(scope)===signature(currentScope());
    find('save').disabled=locked||!live;
    for(const name of ['goals','routines','tick'])find(name).disabled=locked||!live||snapshot.genuine_scope_registered!==true||snapshot.effective_native_goal_owned!==true||snapshot.active!==true;
    find('refresh').disabled=busy;
    find('day').disabled=locked||!live;plansButton.disabled=!scope;
    for(const input of find('flags').querySelectorAll('input'))input.disabled=locked||!live;
  }
  async function call(method,path,payload,at){
    if(typeof api!=='function')throw Error('管理后台连接尚未就绪。');
    const response=await api(method,'page/pc-daily-native/'+path,payload),result=response&&response.ok===true?response:response&&response.data;
    if(!result||result.ok!==true||result.backend!=='native_pc_daily'||signature(result.scope)!==signature(at))throw Error('日常接口未返回同一范围的有效结果。');
    return result;
  }
  const problem=error=>error.publicMessage||error.message||'操作结果尚未确认。';
  function validIntent(value){return value&&typeof value==='object'&&Object.keys(value).sort().join(',')==='day,persona_id,plan_id,request_id,routines'&&/^\d{4}-\d{2}-\d{2}$/.test(value.day)&&typeof value.routines==='boolean'&&['persona_id','plan_id','request_id'].every(key=>typeof value[key]==='string'&&value[key].length>0);}
  function sameIntent(a,b){return validIntent(a)&&validIntent(b)&&['day','routines','persona_id','request_id','plan_id'].every(key=>a[key]===b[key]);}
  function validPlan(plan,intent,at){return plan&&plan.id===intent.plan_id&&plan.date===intent.day&&signature(plan.scope)===signature(at)&&plan.provenance?.request_id===intent.request_id;}
  function generation(value,expected){
    if(!value||!['ready','confirmed','blocked','pending','not_found','inconsistent'].includes(value.state)||typeof value.can_generate!=='boolean'||(expected&&!sameIntent(value.intent,expected)))throw Error('计划核对返回的生成意图不匹配；结果仍需核对。');
    if(['ready','confirmed'].includes(value.state)&&!validIntent(value.intent))throw Error('服务器未返回完整计划标识；不会提交。');
    return value;
  }
  function confirmedPlan(plan,intent,at){
    if(!validPlan(plan,intent,at))throw Error('计划回执未精确对应原日期、会话和生成标识；请只读核对，不要重发。');
    find('result').replaceChildren(text('p','对应计划：'+plan.title+' · '+intent.day+'。计划已存在，不代表其中的活动已经完成。'));
  }
  function pendingMessage(intent){
    const original=intent.error?'原请求提示：'+intent.error+' ':'';
    const why=intent.checkReason?'核对结果：'+intent.checkReason+' ':'';
    const identity=intent.identity?'原计划日期 '+intent.identity.day+' · '+(intent.identity.routines?'虚构日常':'目标计划')+'。':'原操作没有可精确核对的计划标识。';
    return original+why+identity+' 当前写入仍暂停，不会重发。可查看目标日计划；列表中存在相似计划不代表原操作已完成。';
  }
  function render(){
    find('summary').replaceChildren();if(!snapshot){controls();return;}
    const old=snapshot.old_goal_writer||{};
    find('summary').append(text('p','目标执行者：'+(snapshot.active===true&&snapshot.effective_native_goal_owned===true?'TLS 原生运行':'当前未运行；旧职责或围栏状态：'+(old.phase||'未知'))));
    find('summary').append(text('p',snapshot.genuine_scope_registered?'本会话已有真实入站来源登记。':'等待本会话真实私聊；后台仍可维护设置，不会创建实时授权。'));
    const shareLabels={blocked:'当时未获准分享',idle:'当前没有新分享候选',disabled:'本次未启用分享',deferred:'等待原通道',queued:'已排队',claimed:'已确认并记录',unknown:'结果未确认'};
    if(snapshot.last_tick?.share){const value=snapshot.last_tick.share;find('summary').append(text('p','最近一次推进核对：'+(shareLabels[value.state]||value.state||'状态未提供')+(Number.isFinite(snapshot.last_tick_at)?' · '+new Date(snapshot.last_tick_at*1000).toLocaleString():'')+(value.reason_label?' · '+value.reason_label:value.reason==='no_new_eligible_goal_share'?' · 没有新的符合条件内容，不是发送失败。':'')));}
    if(snapshot.share){const value=snapshot.share,at=value.updated_at??value.created_at;find('summary').append(text('p','上次分享记录：'+(shareLabels[value.phase]||value.phase)+(Number.isFinite(at)?' · '+new Date(at*1000).toLocaleString():' · 记录时间未提供')+(value.delivery_confirmed?'；已有发送确认。':'；未取得发送确认。')+(value.reason_label?' '+value.reason_label:'')));}
    for(const key of Object.keys(labels))find('flags').querySelector('[name="'+key+'"]').checked=snapshot.settings.flags[key]===true;
    const uncertain=pending.get(signature(scope));
    if(uncertain?.path==='settings')for(const key of Object.keys(labels))find('flags').querySelector('[name="'+key+'"]').checked=uncertain.payload.flags[key]===true;
    controls();
  }
  function scopeChanged(){serial++;busy=false;scope=currentScope();snapshot=null;lastOutcome='';find('summary').replaceChildren();find('result').replaceChildren();find('day').value='';notice(scope?'范围已切换，请刷新读取当前日常。':'先选择完整用户、角色与会话。');controls();}
  async function load(){
    const live=currentScope();if(signature(live)!==signature(scope))scopeChanged();
    if(busy)return;if(!scope){notice('先选择完整用户、角色与会话。');controls();return;}
    const at={...scope},turn=++serial;busy=true;controls();notice('正在读取当前范围日常…');
    try{
      const response=await call('GET','status',at,at);if(!current(at,turn))return;snapshot=response.result;
      const uncertain=pending.get(signature(at));
      if(uncertain?.path==='settings'&&snapshot.settings.revision>uncertain.payload.expected_revision&&Object.keys(labels).every(key=>snapshot.settings.flags[key]===uncertain.payload.flags[key]))pending.delete(signature(at));
      if(uncertain?.path==='generate'&&uncertain.identity){
        try{const read=await call('GET','generation',{...at,intent:JSON.stringify(uncertain.identity)},at);if(!current(at,turn))return;
          const value=generation(read.result,uncertain.identity);uncertain.checkReason=value.reason_label||'原意图尚无完成证明。';
          if(value.state==='confirmed'){confirmedPlan(value.plan,uncertain.identity,at);if(pending.get(signature(at))===uncertain)pending.delete(signature(at));lastOutcome='已精确核对原意图的计划确实存在；不代表本次新建，也未重复提交。';}
        }catch(error){if(!current(at,turn))return;uncertain.checkReason=problem(error);}
      }
      render();
      notice(pending.has(signature(at))?pendingMessage(pending.get(signature(at))):lastOutcome||'已回读真实运行状态。',pending.has(signature(at)));
    }catch(error){if(current(at,turn))notice(problem(error)+(pending.has(signature(at))?' '+pendingMessage(pending.get(signature(at))):''),true);}
    finally{if(current(at,turn)){busy=false;controls();}}
  }
  async function prepareGenerate(routines){
    if(busy||pending.has(signature(scope))||!snapshot||!scope||signature(scope)!==signature(currentScope()))return;
    const at={...scope},turn=++serial,day=find('day').value;busy=true;lastOutcome='';controls();notice('正在按服务器角色日历核对日期与计划；尚未提交。');
    let prepared=null;
    try{const response=await call('GET','generation',{...at,routines:String(routines),...(day?{day}:{})},at);if(!current(at,turn))return;
      const value=generation(response.result);if(validIntent(value.intent))find('day').value=value.intent.day;
      if(value.state==='confirmed'){confirmedPlan(value.plan,value.intent,at);lastOutcome='该日期与类型的计划已存在，未再次提交。';notice(lastOutcome);}
      else if(value.state==='ready'&&value.can_generate===true)prepared=value.intent;
      else notice((value.reason_label||'当前无法准备这份计划。')+(value.role_date?' 角色今天：'+value.role_date+(value.timezone?'（'+value.timezone+'）':'')+'。':'')+(value.suggested_day?' 可选择：'+value.suggested_day+'。':'')+' 尚未提交写入；请调整日期或查看现有计划。',true);
    }catch(error){if(current(at,turn))notice(problem(error)+' 尚未提交写入，可核对日期后重试。',true);}
    finally{if(current(at,turn)){busy=false;controls();}}
    if(prepared&&current(at,turn))await mutate('generate',{day:prepared.day,routines:prepared.routines,expected_generation:prepared},prepared);
  }
  async function mutate(path,payload,identity=null){
    if(busy||pending.has(signature(scope))||!snapshot||!scope||signature(scope)!==signature(currentScope()))return;
    const at={...scope},turn=++serial,intent={path,payload,identity};pending.set(signature(at),intent);busy=true;lastOutcome='';controls();notice('正在处理并等待后端结果…');
    try{
      const response=await call('POST',path,{scope:at,...payload},at);
      if(path==='generate'&&(!identity||!validPlan(response.result,identity,at)))throw Error('计划回执缺少原意图的精确证明，请刷新核对；不会重发。');
      // A completed response belongs to its original scope; do not keep a false
      // unknown lock merely because the user switched panels while it finished.
      if(pending.get(signature(at))===intent)pending.delete(signature(at));
      if(!current(at,turn))return;find('result').replaceChildren();
      if(path==='generate')confirmedPlan(response.result,identity,at);
      else if(path==='tick'){const value=response.result;find('result').append(text('p',value.state==='disabled'?'未执行：当前真实会话、人格或旧目标交接条件未满足。':'已核对：新增计划 '+value.generated+'；虚构活动完成 '+value.completed_items+'。'));}
      lastOutcome='操作已返回有效回执；已继续回读当前状态。';notice(lastOutcome);
    }catch(error){
      intent.error=problem(error);
      if(path!=='generate'&&!error.outcomeUnknown&&[400,401,403,404,409].includes(Number(error.status||error.statusCode))&&pending.get(signature(at))===intent)pending.delete(signature(at));
      if(current(at,turn))notice(intent.error+(pending.has(signature(at))?' 请刷新回读，不要重复提交。':' 原输入保留，请核对后再操作。'),true);
    }finally{if(current(at,turn)){busy=false;controls();}}
    if(current(at,turn))await load();
  }
  find('refresh').addEventListener('click',load);
  find('settings').addEventListener('submit',event=>{event.preventDefault();if(!snapshot)return;const flags=Object.fromEntries(Object.keys(labels).map(key=>[key,find('flags').querySelector('[name="'+key+'"]').checked]));if(Object.keys(labels).every(key=>flags[key]===snapshot.settings.flags[key])){notice('设置未变化，没有重复提交。');return;}mutate('settings',{expected_revision:snapshot.settings.revision,flags});});
  find('goals').addEventListener('click',()=>prepareGenerate(false));
  find('routines').addEventListener('click',()=>prepareGenerate(true));
  find('tick').addEventListener('click',()=>mutate('tick',{}));
  global.TLSPCDailyNativePanel={activate:load,scopeChanged};controls();
})(window);
