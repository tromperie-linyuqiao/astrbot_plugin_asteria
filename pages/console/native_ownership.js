/* Real native owners and original business views over the AstrBot page bridge. */
(function (global) {
  'use strict';
  const mount = document.getElementById('native-ownership-mount');
  const roleMount = document.getElementById('pc-native-overview-mount');
  const proactiveMount = document.getElementById('proactive-native-mount');
  if (!mount && !roleMount && !proactiveMount) return;
  const types = {
    mc: {label:'完整记忆服务', key:'mc_full', description:'记忆捕获、画像、关系、摘要与原历史管理', page:'memory-native'},
    pc: {label:'角色日常与陪伴', key:'pc_full', description:'角色状态、日记、穿搭、技能、创作和实际工具', page:'pc-native'},
    proactive: {label:'独立主动聊天', key:'proactive_full', description:'原会话计划、配置覆盖和统一发送确认'}
  };
  const storageKey = 'tls.native.ownership.pending.v1';
  let overview = null, busy = false, pending = {}, proactiveState = null, fresh = false;
  try { pending = JSON.parse(sessionStorage.getItem(storageKey) || '{}') || {}; } catch (_) {}
  const node = (tag, content, cls) => { const value=document.createElement(tag); if(content!==undefined)value.textContent=content; if(cls)value.className=cls; return value; };
  const button = (text, callback, cls) => { const value=node('button',text,cls); value.type='button';value.addEventListener('click',callback);return value; };
  const phases = {inactive:'尚未启用',not_requested:'尚未请求接管',prepared:'已准备',preparing:'准备中',
    old_admission_closed:'旧接纳已关闭',draining_original:'等待旧执行者排空',turning_off_original:'正在退出旧插件',
    native:'TLS原生运行',active:'TLS原生运行',blocked:'存在阻塞',turnoff_unknown:'旧插件退出结果未知',
    draining:'停止接纳，等待在途完成',draining_native:'停止接纳，等待原生在途完成',native_stopped:'原生服务已停止',closed:'原生服务已关闭',
    legacy_restored:'已恢复旧实现',legacy_retained:'旧实现保持运行'};
  function savePending(){try{sessionStorage.setItem(storageKey,JSON.stringify(pending));}catch(_){}}
  function unpack(value){
    for(let index=0;index<4;index++){
      if(!value||typeof value!=='object')throw Error('后台没有返回有效状态。');
      if(value.status==='error'||value.success===false||value.ok===false){const error=Error(value.message||value.error||'操作未完成');error.status=value.status_code||value.code;throw error;}
      const keys=Object.keys(value);
      if(value.data&&typeof value.data==='object'&&(value.status==='success'||value.success===true||keys.every(key=>['ok','data','message'].includes(key)))){value=value.data;continue;}
      return value;
    }
    throw Error('后台返回结构无法识别。');
  }
  async function call(method,path,data){
    const sdk=global.AstrBotPluginPage;
    if(!sdk)throw Error('请从 AstrBot 后台重新打开此页。');
    await sdk.ready();
    return unpack(method==='GET'?await sdk.apiGet(path,data):await sdk.apiPost(path,data));
  }
  async function navigate(page){
    try{
      const result=await call('GET','page/nav',{to:page,theme:typeof resolvedTheme==='function'?resolvedTheme():'dark',format:'json'});
      const url=new URL(result.url,location.href);
      if(url.origin!==location.origin||url.pathname!=='/api/plugin/page/content/astrbot_plugin_virtual_body/'+page+'/'||!url.searchParams.get('asset_token'))throw Error('管理页入口校验未通过。');
      location.href=url.href;
    }catch(error){setNotice(error.message,true);}
  }
  function snapshot(kind){return overview&&overview[types[kind].key]||{};}
  function oldOff(value){return value.original_plugin_active===false||value.legacy_closed===true||value.legacy_turnoff_confirmed===true||value.old_off_confirmed===true;}
  function label(value){
    if(!fresh)return overview?'上次状态仅供核对，当前执行权未确认':'当前执行权待读取';
    if(value.active===true&&value.original_plugin_active===true)return '执行权冲突，停止扩大运行';
    if(value.active===true&&oldOff(value))return 'TLS原生运行';
    if(value.original_plugin_active===true)return '旧插件仍运行';
    if(value.last_error)return '接管受阻，请核对当前状态';
    return phases[value.phase]||'当前状态待核对';
  }
  function finished(kind,action){
    const value=snapshot(kind);
    if(action==='activate')return value.active===true&&oldOff(value);
    if(action==='restore')return value.phase==='legacy_restored'&&value.active===false;
    const native=value.native||value.service||value;
    return value.active===false&&['native_stopped','closed','inactive'].includes(value.phase)
      &&!(native.pending_operations>0)&&!(native.tasks>0);
  }
  function reconcile(){for(const [kind,item] of Object.entries(pending)){if(types[kind]&&finished(kind,item.action))delete pending[kind];}savePending();}
  function setNotice(message,error){
    for(const root of [mount,roleMount,proactiveMount]){
      const target=root&&root.querySelector('[data-native-notice]');
      if(target){target.textContent=message;target.classList.toggle('native-owner-error',!!error);}
    }
  }
  function meta(parent,labelText,value){const line=node('div',undefined,'native-owner-stat');line.append(node('small',labelText),node('strong',value));parent.append(line);}
  function renderOwners(){
    if(!mount)return;
    mount.querySelector('[data-native-cards]').replaceChildren();
    for(const [kind,definition] of Object.entries(types)){
      const value=snapshot(kind),card=node('article',undefined,'native-owner-card');
      card.append(node('h3',definition.label),node('p',definition.description,'hint'),node('p',label(value),'native-owner-state'));
      const stats=node('div',undefined,'native-owner-stats');
      meta(stats,'配置',value.configured===true?'已开启':value.configured===false?'未开启':'未观察');
      meta(stats,'旧执行者',value.original_plugin_active===true?'仍活动':oldOff(value)?'已退出':'待核对');
      meta(stats,'实际阶段',phases[value.phase]||value.phase||'未观察');card.append(stats);
      if(pending[kind])card.append(node('p','上次“'+pending[kind].label+'”结果尚未确认。仅回读，不重复提交。','native-owner-error'));
      const actions=node('div',undefined,'actions');
      for(const [action,title] of [['activate','接管已准备职责'],['stop','停止原生接纳'],['restore','恢复旧执行者']]){
        const control=button(title,()=>operate(kind,action,title),action==='activate'?'primary':'');
        control.disabled=busy||!!pending[kind]||!overview||!fresh||(action==='activate'&&value.active===true)
          ||(action==='stop'&&value.active!==true&&!['blocked','draining','turnoff_unknown'].includes(value.phase));
        actions.append(control);
      }
      if(definition.page)actions.append(button('打开完整管理页',()=>navigate(definition.page)));
      card.append(actions);
      const detail=node('details');detail.append(node('summary','交接与阻塞说明'));
      if(value.last_error)detail.append(node('p',String(value.last_error),'native-owner-error'));
      const drain=value.drain||{};
      for(const key of ['tasks','threads','queued','unknown'])if(drain[key]!==undefined)detail.append(node('p',({tasks:'在途任务',threads:'在途线程',queued:'排队操作',unknown:'未决状态'}[key])+'：'+(drain[key]===null?'未知':drain[key]),'hint'));
      detail.append(node('p','按钮执行真实后台交接，不删除原库或队列。配置开关不等于运行成功；本轮未进行正式测试或新设备验收。','hint'));
      card.append(detail);mount.querySelector('[data-native-cards]').append(card);
    }
  }
  function renderRole(){
    if(!roleMount)return;
    const target=roleMount.querySelector('[data-native-role]');target.replaceChildren();
    const value=snapshot('pc'),service=value.service||{};
    target.append(node('p',label(value),'native-owner-state'));
    target.append(node('p',value.real_scope_bound===true?'当前原生角色已取得真实私聊与人格来源登记。':'等待正常私聊建立当前来源；后台选择范围不会制造会话授权。','hint'));
    const stats=node('div',undefined,'native-owner-stats');
    meta(stats,'生命周期',service.initialized===true?'已初始化':'未观察');
    meta(stats,'独立旧调度器',service.independent_scheduler===false?'未启动':'待核对');
    meta(stats,'当前在途',typeof service.tasks==='number'?String(service.tasks):'未知');target.append(stats);
    target.append(node('p','新明确归属计划供原生日记、穿搭和角色状态读取。原全局计划保持独立历史，不按用户名或角色名补归属；旧候选、UNKNOWN与冷却均保留，不会自动领取旧池。','hint'));
  }
  function renderProactive(){
    if(!proactiveMount)return;
    const target=proactiveMount.querySelector('[data-native-sessions]');target.replaceChildren();
    const rows=proactiveState&&Array.isArray(proactiveState.sessions)?proactiveState.sessions:[];
    if(!rows.length)target.append(node('p','当前没有可显示的原生会话计划；请先核对接管状态和原配置。','hint'));
    for(const row of rows){
      const item=node('article',undefined,'native-session-row');
      const heading=node('div');heading.append(node('strong',row.session_id),node('p',(row.enabled?'已启用':'已关闭')+' · '+(row.scheduled?'已安排':'未安排')+' · '+(row.execution_state||'状态未知'),'hint'));
      if(row.manual_review)heading.append(node('p','存在未决结果，等待回读核对，不会自动重发。','native-owner-error'));
      if(row.next_trigger_time!==undefined&&row.next_trigger_time!==null)heading.append(node('p','下一触发：'+String(row.next_trigger_time),'hint'));
      item.append(heading);target.append(item);
    }
    target.append(node('p','这里仅显示当前计划摘要。完整配置由下方独立主动消息面板维护，避免两套编辑器互相覆盖。','hint'));
    target.append(button('前往完整会话配置',()=>{const editor=document.getElementById('proactive-chat-native-mount');if(editor)editor.scrollIntoView({block:'start',behavior:'smooth'});else setNotice('完整面板尚未加载，请重新打开当前分区。',true);}));
  }
  function render(){renderOwners();renderRole();renderProactive();}
  async function load(){
    if(busy)return;busy=true;render();setNotice('正在回读真实服务状态…');
    try{overview=await call('GET','page/server-integration/status');fresh=true;reconcile();
      if(proactiveMount){try{proactiveState=await call('GET','page/proactive-chat-native/status');}catch(_){proactiveState=overview.proactive_chat||null;}}
      render();setNotice(Object.keys(pending).length?'已读取状态；仍有未决操作，只允许继续回读。':'已回读当前运行状态；部署与实际消息送达分别记录。',Object.keys(pending).length>0);
    }catch(error){fresh=false;setNotice((error.message||'状态暂不可用。')+' 上次状态不作为当前操作依据，请先重新读取。',true);}finally{busy=false;render();}
  }
  async function operate(kind,action,title){
    if(busy||pending[kind]||!fresh)return;
    if(!global.confirm(title+'：会进行真实执行权操作，保留原数据。现在继续？'))return;
    pending[kind]={action,label:title,at:Date.now()};savePending();busy=true;render();setNotice('正在执行，请勿重复提交…');
    try{overview=await call('POST','page/server-integration/'+kind+'/full/'+action,{});reconcile();}
    catch(error){setNotice((error.message||'结果未知。')+' 请回读，不会重复提交。',true);}
    finally{busy=false;render();}
    await load();
  }
  if(mount){mount.innerHTML='<section class="panel native-owner-panel"><div class="panel-head"><h2>原生接管中心</h2><button type="button" data-native-refresh>刷新状态</button></div><p class="hint">唯一执行者、在途排空与实际原生对象共同决定当前职责。开关为真不等于已运行；基础备份设施和原本禁用的插件不计作替代。</p><p data-native-notice role="status">等待回读。</p><div data-native-cards class="native-owner-grid"></div></section>';mount.querySelector('[data-native-refresh]').addEventListener('click',load);}
  if(roleMount){roleMount.innerHTML='<section class="panel native-owner-panel"><div class="panel-head"><h2>角色日常</h2><div class="actions"><button type="button" data-native-refresh>刷新状态</button><button type="button" data-native-open-pc>打开完整角色资料</button></div></div><p data-native-notice role="status">等待回读。</p><div data-native-role></div></section>';roleMount.querySelector('[data-native-refresh]').addEventListener('click',load);roleMount.querySelector('[data-native-open-pc]').addEventListener('click',()=>navigate('pc-native'));}
  if(proactiveMount){proactiveMount.innerHTML='<section class="panel native-owner-panel"><div class="panel-head"><h2>原生主动消息运行摘要</h2><button type="button" data-native-refresh>刷新摘要</button></div><p class="hint">实际生成、冷却、免打扰和发送确认由统一通道管理。未知结果不会重发；完整设置在下方维护。</p><p data-native-notice role="status">等待读取。</p><div data-native-sessions></div></section>';proactiveMount.querySelector('[data-native-refresh]').addEventListener('click',load);}
  global.TLSNativeOwnershipPanel={activate:load};
  global.TLSPCNativePanel={activate:load};
  global.TLSProactiveOwnershipSummary={activate:load};
  render();
})(window);
