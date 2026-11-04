/* Asteria's own service status. Former migration controls are retired. */
(function (global) {
  'use strict';
  const mount = document.getElementById('native-ownership-mount');
  const roleMount = document.getElementById('pc-native-overview-mount');
  const proactiveMount = document.getElementById('proactive-native-mount');
  if (!mount && !roleMount && !proactiveMount) return;
  const types = {
    mc: {label:'完整记忆服务', key:'mc_full', description:'记忆捕获、画像、关系、摘要与资料维护', page:'memory-native'},
    pc: {label:'角色日常与陪伴', key:'pc_full', description:'角色状态、日记、穿搭、技能、创作和实际工具', page:'pc-native'},
    phone: {label:'设备感知', key:'phone', description:'授权设备连接、状态读取与交互节奏'},
    insight: {label:'洞察与统计', key:'insight', description:'使用记录、趋势与授权查询'},
    proactive: {label:'独立主动聊天', key:'proactive_full', description:'会话计划、配置覆盖和统一发送确认'}
  };
  const storageKey = 'tls.native.ownership.pending.v1';
  let overview = null, busy = false, pending = {}, proactiveState = null, fresh = false;
  try { pending = JSON.parse(sessionStorage.getItem(storageKey) || '{}') || {}; } catch (_) {}
  const node = (tag, content, cls) => { const value=document.createElement(tag); if(content!==undefined)value.textContent=content; if(cls)value.className=cls; return value; };
  const button = (text, callback, cls) => { const value=node('button',text,cls); value.type='button';value.addEventListener('click',callback);return value; };
  const phases = {inactive:'尚未启用',not_requested:'未启用',prepared:'已准备',preparing:'准备中',
    old_admission_closed:'旧接纳已关闭',draining_original:'等待旧执行者排空',turning_off_original:'正在退出旧插件',
    native:'服务运行中',active:'服务运行中',blocked:'存在阻塞',turnoff_unknown:'旧插件退出结果未知',
    draining:'停止接纳，等待在途完成',draining_native:'停止接纳，等待原生在途完成',native_stopped:'原生服务已停止',closed:'原生服务已关闭',
    legacy_restored:'已恢复旧实现',legacy_retained:'旧实现保持运行',
    drain_pending:'关闭尚未完成',waiting_native_predecessor:'等待前一记忆实例结束'};
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
    if(method!=='GET')throw Error('本面板只读取系统服务状态。');
    return unpack(await sdk.apiGet(path,data));
  }
  async function navigate(page){
    try{
      const result=await call('GET','page/nav',{to:page,theme:typeof resolvedTheme==='function'?resolvedTheme():'dark',format:'json'});
      const url=new URL(result.url,location.href);
      if(url.origin!==location.origin||url.pathname!=='/api/plugin/page/content/astrbot_plugin_asteria/'+page+'/'||!url.searchParams.get('asset_token'))throw Error('管理页入口校验未通过。');
      location.href=url.href;
    }catch(error){setNotice(error.message,true);}
  }
  function snapshot(kind){
    const value=overview&&overview[types[kind].key]||{};
    if(kind==='phone'||kind==='insight')return {...value,configured:value.enabled,active:value.native_active,original_plugin_active:value.legacy_active,phase:value.phase||(value.native_active?'native':'inactive')};
    return value;
  }
  function oldOff(value){return value.original_plugin_active===false||value.legacy_closed===true;}
  function label(value){
    if(!fresh)return overview?'上次记录，当前状态未确认':'等待读取服务状态';
    if(value.active===true&&value.original_plugin_active===true)return '检测到同时运行的执行者，请核对冲突';
    if(value.active===true&&oldOff(value))return 'Asteria 服务运行中';
    if(value.original_plugin_active===true)return '存在其他活动执行者';
    if(value.last_error)return '服务受阻，请查看详情';
    return phases[value.phase]||'当前状态待核对';
  }
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
      meta(stats,'执行者',value.active===true&&oldOff(value)?'Asteria':value.original_plugin_active===true?'存在冲突':'未运行或待核对');
      meta(stats,'实际阶段',phases[value.phase]||value.phase||'未观察');card.append(stats);
      if(pending[kind])card.append(node('p','上次“'+pending[kind].label+'”结果尚未确认。仅回读，不重复提交。','native-owner-error'));
      const actions=node('div',undefined,'actions');
      if(definition.page)actions.append(button('打开完整管理页',()=>navigate(definition.page)));
      card.append(actions);
      const detail=node('details');detail.append(node('summary','运行详情'));
      if(value.last_error)detail.append(node('p',String(value.last_error),'native-owner-error'));
      const drain=value.drain||{};
      for(const key of ['tasks','threads','queued','unknown'])if(drain[key]!==undefined)detail.append(node('p',({tasks:'在途任务',threads:'在途线程',queued:'排队操作',unknown:'未决状态'}[key])+'：'+(drain[key]===null?'未知':drain[key]),'hint'));
      detail.append(node('p','这里仅查看本插件服务。状态来自当前运行实例；配置开启不等于请求成功或消息送达。已有数据和未决任务保持。','hint'));
      card.append(detail);mount.querySelector('[data-native-cards]').append(card);
    }
  }
  function renderRole(){
    if(!roleMount)return;
    const target=roleMount.querySelector('[data-native-role]');target.replaceChildren();
    const value=snapshot('pc'),service=value.service||{};
    target.append(node('p',label(value),'native-owner-state'));
    target.append(node('p',value.real_scope_bound===true?'当前角色已取得真实私聊与人格来源登记。':'等待正常私聊建立当前来源；后台选择范围不会制造会话授权。','hint'));
    const stats=node('div',undefined,'native-owner-stats');
    meta(stats,'生命周期',service.initialized===true?'已初始化':'未观察');
    meta(stats,'额外调度器',service.independent_scheduler===false?'未启动':'待核对');
    meta(stats,'当前在途',typeof service.tasks==='number'?String(service.tasks):'未知');target.append(stats);
    target.append(node('p','新明确归属计划供原生日记、穿搭和角色状态读取。原全局计划保持独立历史，不按用户名或角色名补归属；旧候选、UNKNOWN与冷却均保留，不会自动领取旧池。','hint'));
  }
  function renderProactive(){
    if(!proactiveMount)return;
    const target=proactiveMount.querySelector('[data-native-sessions]');target.replaceChildren();
    const rows=proactiveState&&Array.isArray(proactiveState.sessions)?proactiveState.sessions:[];
    if(!rows.length)target.append(node('p','当前没有可显示的会话计划；请核对服务状态与会话配置。','hint'));
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
    try{overview=await call('GET','page/server-integration/status');fresh=true;
      if(proactiveMount){try{proactiveState=await call('GET','page/proactive-chat-native/status');}catch(_){proactiveState=overview.proactive_chat||null;}}
      render();setNotice(Object.keys(pending).length?'已读取状态。先前迁移操作的未决记录仍保留；本页不再执行接管或恢复。':'已回读当前运行状态；部署与实际消息送达分别记录。',Object.keys(pending).length>0);
    }catch(error){fresh=false;setNotice((error.message||'状态暂不可用。')+' 上次状态不作为当前操作依据，请先重新读取。',true);}finally{busy=false;render();}
  }
  if(mount){mount.innerHTML='<section class="panel native-owner-panel"><div class="panel-head"><h2>系统服务</h2><button type="button" data-native-refresh>刷新状态</button></div><p class="hint">Asteria 是独立插件，由自身服务处理记忆、陪伴、设备和消息。此处显示当前状态与管理入口；不再提供旧插件接管或恢复操作。</p><p data-native-notice role="status">等待回读。</p><div data-native-cards class="native-owner-grid"></div></section>';mount.querySelector('[data-native-refresh]').addEventListener('click',load);}
  if(roleMount){roleMount.innerHTML='<section class="panel native-owner-panel"><div class="panel-head"><h2>角色日常</h2><div class="actions"><button type="button" data-native-refresh>刷新状态</button><button type="button" data-native-open-pc>打开完整角色资料</button></div></div><p data-native-notice role="status">等待回读。</p><div data-native-role></div></section>';roleMount.querySelector('[data-native-refresh]').addEventListener('click',load);roleMount.querySelector('[data-native-open-pc]').addEventListener('click',()=>navigate('pc-native'));}
  if(proactiveMount){proactiveMount.innerHTML='<section class="panel native-owner-panel"><div class="panel-head"><h2>主动消息运行摘要</h2><button type="button" data-native-refresh>刷新摘要</button></div><p class="hint">实际生成、冷却、免打扰和发送确认由统一通道管理。未知结果不会重发；完整设置在下方维护。</p><p data-native-notice role="status">等待读取。</p><div data-native-sessions></div></section>';proactiveMount.querySelector('[data-native-refresh]').addEventListener('click',load);}
  global.TLSNativeOwnershipPanel={activate:load};
  global.TLSPCNativePanel={activate:load};
  global.TLSProactiveOwnershipSummary={activate:load};
  render();
})(window);
