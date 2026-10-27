/* One view of the real native daily lifecycle; no local execution/ownership. */
(function (global) {
  'use strict';
  const root = document.getElementById('pc-daily-native-mount');
  if (!root) return;
  const fields = ['platform', 'bot_id', 'user_id', 'character_id', 'session_id'];
  const labels = {auto_generate:'自动准备未来目标计划',auto_progress:'到时记为虚构活动并推进目标',share_enabled:'使用现有陪伴通道分享有来源的目标进展',routine_enabled:'同时安排独立的虚构日常'};
  const pending = new Map();
  let scope=null,snapshot=null,busy=false,serial=0;
  const signature=value=>JSON.stringify(fields.map(key=>value&&value[key]));
  const currentScope=()=>typeof state==='object'&&state.scope&&fields.every(key=>typeof state.scope[key]==='string'&&state.scope[key])?Object.fromEntries(fields.map(key=>[key,state.scope[key]])):null;
  const current=(at,turn)=>turn===serial&&signature(at)===signature(scope)&&signature(at)===signature(currentScope());
  const text=(tag,content,className)=>{const result=document.createElement(tag);result.textContent=content;if(className)result.className=className;return result;};
  root.innerHTML='<section class="panel pc-daily-native"><div class="panel-head"><h2>角色日常与目标自动推进</h2><button type="button" data-pcd-refresh>刷新状态</button></div><p data-pcd-notice role="status">选择真实用户、角色和会话后查看。</p><div data-pcd-summary></div><form data-pcd-settings><div data-pcd-flags></div><button type="submit" class="primary" data-pcd-save>保存本范围设置</button></form><div class="pc-daily-native-actions"><label>角色日期<input type="date" data-pcd-day></label><button type="button" data-pcd-goals>准备目标计划</button><button type="button" data-pcd-routines>准备虚构日常</button><button type="button" data-pcd-tick>核对并推进一次</button></div><p class="hint">仅对有真实会话来源的新计划执行。旧无归属日计划保留，不按昵称猜归属；虚构活动不是现实观察。分享沿现有队列、冷却和发送确认，确认后才记录已分享。</p><div data-pcd-result></div></section>';
  const find=name=>root.querySelector('[data-pcd-'+name+']');
  for(const [key,label] of Object.entries(labels)){const line=text('label','','pc-daily-native-check'),input=document.createElement('input');input.type='checkbox';input.name=key;line.append(input,document.createTextNode(label));find('flags').append(line);}
  function notice(message,error){find('notice').textContent=message;find('notice').classList.toggle('pc-daily-native-error',!!error);}
  function controls(){
    const locked=busy||pending.has(signature(scope)),live=!!snapshot&&!!scope&&signature(scope)===signature(currentScope());
    find('save').disabled=locked||!live;
    for(const name of ['goals','routines','tick'])find(name).disabled=locked||!live||snapshot.genuine_scope_registered!==true||snapshot.effective_native_goal_owned!==true||snapshot.active!==true;
    find('refresh').disabled=busy;
    for(const input of find('flags').querySelectorAll('input'))input.disabled=locked||!live;
  }
  async function call(method,path,payload,at){
    if(typeof api!=='function')throw Error('管理后台连接尚未就绪。');
    const response=await api(method,'page/pc-daily-native/'+path,payload),result=response&&response.ok===true?response:response&&response.data;
    if(!result||result.ok!==true||result.backend!=='native_pc_daily'||signature(result.scope)!==signature(at))throw Error('日常接口未返回同一范围的有效结果。');
    return result;
  }
  function render(){
    find('summary').replaceChildren();if(!snapshot){controls();return;}
    const old=snapshot.old_goal_writer||{};
    find('summary').append(text('p','目标执行者：'+(snapshot.active===true&&snapshot.effective_native_goal_owned===true?'TLS 原生运行':'当前未运行；旧职责或围栏状态：'+(old.phase||'未知'))));
    find('summary').append(text('p',snapshot.genuine_scope_registered?'本会话已有真实入站来源登记。':'等待本会话真实私聊；后台仍可维护设置，不会创建实时授权。'));
    if(snapshot.share)find('summary').append(text('p','最近分享：'+snapshot.share.phase+(snapshot.share.delivery_confirmed?'；已取得真实发送确认。':'；不代表已经送达。')));
    for(const key of Object.keys(labels))find('flags').querySelector('[name="'+key+'"]').checked=snapshot.settings.flags[key]===true;
    const uncertain=pending.get(signature(scope));
    if(uncertain?.path==='settings')for(const key of Object.keys(labels))find('flags').querySelector('[name="'+key+'"]').checked=uncertain.payload.flags[key]===true;
    controls();
  }
  function scopeChanged(){serial++;busy=false;scope=currentScope();snapshot=null;find('summary').replaceChildren();find('result').replaceChildren();find('day').value='';notice(scope?'范围已切换，请刷新读取当前日常。':'先选择完整用户、角色与会话。');controls();}
  async function load(){
    const live=currentScope();if(signature(live)!==signature(scope))scopeChanged();
    if(busy)return;if(!scope){notice('先选择完整用户、角色与会话。');controls();return;}
    const at={...scope},turn=++serial;busy=true;controls();notice('正在读取当前范围日常…');
    try{
      const response=await call('GET','status',at,at);if(!current(at,turn))return;snapshot=response.result;
      const uncertain=pending.get(signature(at));
      if(uncertain?.path==='settings'&&snapshot.settings.revision>uncertain.payload.expected_revision&&Object.keys(labels).every(key=>snapshot.settings.flags[key]===uncertain.payload.flags[key]))pending.delete(signature(at));
      render();
      notice(pending.has(signature(at))?'已读取现状，但原操作尚无精确完成证明；本范围写入仍暂停，不会重发。可在目标日计划核对原计划与活动。':'已回读真实运行状态。',pending.has(signature(at)));
    }catch(error){if(current(at,turn))notice(error.message||'状态读取失败。',true);}
    finally{if(current(at,turn)){busy=false;controls();}}
  }
  async function mutate(path,payload){
    if(busy||pending.has(signature(scope))||!snapshot||!scope||signature(scope)!==signature(currentScope()))return;
    const at={...scope},turn=++serial,intent={path,payload};pending.set(signature(at),intent);busy=true;controls();notice('正在处理并等待后端结果…');
    try{
      const response=await call('POST',path,{scope:at,...payload},at);
      // A completed response belongs to its original scope; do not keep a false
      // unknown lock merely because the user switched panels while it finished.
      if(pending.get(signature(at))===intent)pending.delete(signature(at));
      if(!current(at,turn))return;find('result').replaceChildren();
      if(path==='generate')find('result').append(text('p','计划已准备：'+response.result.title+'。可在“目标日计划”查看、编辑和取消。'));
      else if(path==='tick'){const value=response.result;find('result').append(text('p',value.state==='disabled'?'未执行：当前真实会话、人格或旧目标交接条件未满足。':'已核对：新增计划 '+value.generated+'；虚构活动完成 '+value.completed_items+'。'));}
      notice('操作已返回；继续回读当前状态。');
    }catch(error){
      if([400,401,403,404,409].includes(Number(error.status||error.statusCode))&&pending.get(signature(at))===intent)pending.delete(signature(at));
      if(current(at,turn))notice((error.message||'操作结果未知。')+(pending.has(signature(at))?' 请刷新回读，不要重复提交。':' 原输入保留，请核对后再操作。'),true);
    }finally{if(current(at,turn)){busy=false;controls();}}
    if(current(at,turn))await load();
  }
  find('refresh').addEventListener('click',load);
  find('settings').addEventListener('submit',event=>{event.preventDefault();if(!snapshot)return;const flags=Object.fromEntries(Object.keys(labels).map(key=>[key,find('flags').querySelector('[name="'+key+'"]').checked]));if(Object.keys(labels).every(key=>flags[key]===snapshot.settings.flags[key])){notice('设置未变化，没有重复提交。');return;}mutate('settings',{expected_revision:snapshot.settings.revision,flags});});
  find('goals').addEventListener('click',()=>mutate('generate',{day:find('day').value||null,routines:false}));
  find('routines').addEventListener('click',()=>mutate('generate',{day:find('day').value||null,routines:true}));
  find('tick').addEventListener('click',()=>mutate('tick',{}));
  global.TLSPCDailyNativePanel={activate:load,scopeChanged};controls();
})(window);
