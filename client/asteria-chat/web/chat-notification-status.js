'use strict';
/* Inspect the existing Android channels and watch. Reading never starts it. */
window.ChatNotificationStatus=(()=>{
  const node=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n;};
  const get=id=>document.getElementById(id),settingsVisible=()=>get('settings-dialog')?.open,visible=()=>settingsVisible()&&get('notification-diagnostics')?.open;
  let operation='',accountList,accountNote;
  const yes=value=>value===true?'已允许':value===false?'未允许':'未提供';
  const importance={none:'已关闭',min:'最低',low:'低',default:'普通',high:'高',unspecified:'未指定'};
  const watchStates={starting:'正在核对会话',running:'运行中',reconnecting:'正在重连',stopped:'已停止'};
  const watchReasons={system_time_limit:'Android 已达到后台同步时限；需要回到应用后自行开启',service_destroyed:'后台服务已结束；系统不保证重新启动',foreground_start_not_allowed:'系统暂不允许启动后台检查',watch_start_unavailable:'后台检查未能启动',notification_permission:'系统通知权限或渠道未开启',notification_channel_blocked:'聊天回复渠道已关闭，请在系统设置中处理',login_expired:'登录已失效，请重新登录此服务器后开启收件',authentication_changed:'登录状态已改变',session_unavailable:'当前会话暂不可用',user_stopped:'已由你停止',notifications_disabled:'消息通知已关闭',cursor_unavailable_open_chat:'历史同步位置已不可用，请打开聊天核对，系统不会重弹旧消息',foreground_ui_owns_reads:'当前由聊天页面同步',network_or_history_unavailable:'网络或记录暂不可读取，将按退避节奏重试',local_delivery_state_unavailable:'本机通知或同步记录暂不可用，已暂停并退避',account_unavailable:'已保存的登录不可用，请重新登录此服务器',credential_unavailable:'已保存的登录不可用，请重新登录此服务器'};
  const syncStates={not_checked:'尚未读取',catching_up:'正在按服务器顺序补齐，每次最多32条',synced:'已补齐至本次服务器读取位置',baseline_saved:'初次位置已保存，不补弹旧消息',foreground_reconciled:'已由前台记录校准',cursor_unavailable:'旧同步位置已不可用，等待打开聊天核对',legacy_history_window:'服务器仅提供最近记录窗口',legacy_cursor_outside_window:'旧位置已超出服务器近期窗口，无法证明遗漏均已补齐'};
  const answer=method=>{const bridge=window.AsteriaChat;if(!bridge||typeof bridge[method]!=='function')return null;const value=bridge[method]();return typeof value==='string'?JSON.parse(value):value;};
  function accounts(watch=answer('getReplyWatchStatus')){
    if(!Array.isArray(watch?.accounts))return null;
    const seen=new Set();return watch.accounts.filter(row=>{
      if(!row||typeof row.account_id!=='string'||!row.account_id||row.account_id.length>256||seen.has(row.account_id)||typeof row.server!=='string'||typeof row.username!=='string'||!row.username||row.username.length>120)return false;
      try{const url=new URL(row.server);if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash)return false;}catch(_){return false;}
      seen.add(row.account_id);return true;
    }).map(row=>({account_id:row.account_id,server:row.server,username:row.username,title:typeof row.title==='string'?row.title.slice(0,80):'',session_id:typeof row.session_id==='string'?row.session_id:'',state:row.state,reason:row.reason,running:row.running===true,can_activate:row.can_activate===true,registered:row.registered,last_sync_at:row.last_sync_at,message_sync:row.message_sync}));
  }
  function targetNote(target,value){if(target)target.textContent=value;}
  async function activateAccount(accountId,target=accountNote){
    if(operation){targetNote(target,'正在处理一个收件操作，请稍候。');return false;}
    try{if(!accounts()?.some(row=>row.account_id===accountId&&row.can_activate)){targetNote(target,'此 Bot 的已保存登录不可用。请在连接设置中输入密码重新登录。');return false;}}catch(_){targetNote(target,'无法确认此 Bot 的已保存登录，请刷新或重新登录。');return false;}
    if(typeof window.activateReplyAccount!=='function'){targetNote(target,'当前客户端还不能切换已保存的登录，请填写密码重新登录。');return false;}
    operation=accountId;renderAccounts();
    try{
      const switched=await window.activateReplyAccount(accountId);
      targetNote(target,switched===true?'已选择这个 Bot，正在恢复聊天与草稿。':'尚未切换。请先结束当前发送或文件处理；登录失效时需填写密码重新登录。');
      return switched===true;
    }catch(_){targetNote(target,'无法打开此 Bot。请检查连接，或在登录区重新登录；没有自动发送消息。');return false;}
    finally{operation='';renderAccounts();}
  }
  function stopAccount(row){
    if(operation)return;operation=row.account_id;renderAccounts();
    try{
      const raw=window.AsteriaChat.stopReplyWatchAccount(row.account_id),result=typeof raw==='string'?JSON.parse(raw):raw;
      if(result?.ok!==true||result.account_id!==row.account_id||result.stopped!==true)throw Error('stop_unconfirmed');
      const current=accounts(),remaining=current?.find(item=>item.account_id===row.account_id);
      targetNote(accountNote,current&&(remaining===undefined||remaining.running===false)?'已停止此 Bot 的后台收件。其他收件目标与聊天记录保留。':'停止操作已提交；当前状态尚未确认，请刷新核对。');
    }catch(_){targetNote(accountNote,'停止结果暂未确认，请刷新状态核对；没有关闭其他 Bot 的收件。');}
    finally{operation='';refresh();}
  }
  function renderAccounts(watch){
    if(!accountList)return;accountList.replaceChildren();
    let list;try{list=accounts(watch);}catch(_){accountList.append(node('p','暂时无法读取后台收件列表，请刷新。'));return;}
    if(list===null){accountList.append(node('p','此 Android 版本尚未提供多 Bot 收件列表。请更新安装包；旧版本仍只检查当前对话。'));return;}
    if(!list.length){accountList.append(node('p','还没有后台收件目标。先登录第一个服务器并开启“新回复提醒”，再登录第二个服务器并各开启一次。'));return;}
    for(const row of list){
      const card=node('article','');card.className='reply-account-card';card.dataset.accountId=row.account_id;
      const heading=node('div','');heading.className='reply-account-heading';const title=node('strong',row.title||'聊天 Bot'),badge=node('span',watchStates[row.state]||(row.running?'运行中':'尚未运行'));badge.className='reply-account-state';badge.dataset.running=String(row.running);heading.append(title,badge);
      const address=node('p',new URL(row.server).host+' · '+row.username);address.className='reply-account-address';card.append(heading,address);
      if(row.reason)card.append(node('p',watchReasons[row.reason]||'状态已变化，可打开聊天或刷新核对。'));
      if(!row.can_activate)card.append(node('p','已保存的登录不可用，请在连接设置中选择此服务器并输入密码重新登录。'));
      if(Number.isFinite(row.last_sync_at)&&row.last_sync_at>0)card.append(node('p','最近读取：'+new Date(row.last_sync_at).toLocaleString('zh-CN',{hour12:false})));
      if(row.message_sync)card.append(node('p','消息同步：'+(syncStates[row.message_sync]||'等待核对')));
      const actions=node('div','');actions.className='reply-account-actions';
      const activate=node('button',row.can_activate?'打开此 Bot':'需要重新登录');activate.type='button';activate.className='secondary-button';activate.dataset.accountAction='activate';activate.disabled=!!operation||!row.can_activate||typeof window.activateReplyAccount!=='function';activate.onclick=()=>activateAccount(row.account_id);
      const stop=node('button','停止此 Bot 收件');stop.type='button';stop.className='text-button';stop.dataset.accountAction='stop';stop.disabled=!!operation||row.registered===false||typeof window.AsteriaChat?.stopReplyWatchAccount!=='function';stop.onclick=()=>stopAccount(row);
      actions.append(activate,stop);card.append(actions);accountList.append(card);
    }
  }
  function note(value){get('notification-system-note').textContent=value;}
  function refresh(){
    if(!settingsVisible())return;
    renderAccounts();window.ChatConnections?.refreshSaved?.();
    if(!visible())return;
    const box=get('notification-system-state');box.replaceChildren();
    const receipts=node('div','');receipts.id='chat-server-receipts';box.append(receipts);
    if(window.ChatReceipts)window.ChatReceipts.refresh();
    try{
      const data=answer('getNotificationStatus');
      if(!data){box.append(node('p','当前客户端尚不能读取系统通知渠道，请安装支持此功能的Android版本。'));get('notification-settings-open').disabled=true;return;}
      if(data.ok!==true)throw Error(data.error||'系统通知状态暂不可用');
      const line=(label,value)=>box.append(node('p',label+'：'+value));
      line('系统通知权限',yes(data.runtime_permission_granted));line('应用通知总开关',yes(data.app_notifications_enabled));
      if(data.runtime_permission_granted===false||data.app_notifications_enabled===false||data.reply_channel?.blocked===true){const blocked=node('p','系统通知尚未获准。请使用下方“打开系统通知设置”检查权限与聊天回复渠道；应用不会重新创建渠道绕过你的静音选择。');blocked.className='notification-blocked-note';box.append(blocked);}
      for(const [field,label]of [['reply_channel','聊天回复渠道'],['watch_channel','后台检查常驻渠道']]){
        const channel=data[field];line(label,!channel?'未提供':channel.exists===false?'尚未建立':channel.blocked===true?'系统已关闭':importance[channel.importance_name]||'状态待确认');
      }
      const watch=answer('getReplyWatchStatus');
      if(watch&&watch.ok!==false){
        const targets=accounts(watch);line('后台收件',targets===null?(watchStates[watch.state]||(watch.running===true?'运行中':'尚未确认')):targets.length+'个目标 · '+targets.filter(row=>row.running).length+'个运行中');
        if(watch.reason)line('检查说明',watchReasons[watch.reason]||'检查状态发生变化，可刷新或重新打开聊天核对。');
        if(watch.message_sync)line('历史补齐',syncStates[watch.message_sync]||'等待核对');
        if(Number.isFinite(watch.last_sync_at)&&watch.last_sync_at>0)line('最近成功读取',new Date(watch.last_sync_at).toLocaleString('zh-CN',{hour12:false}));
        if(Number.isFinite(watch.last_stopped_at)&&watch.last_stopped_at>0)line('最近停止',new Date(watch.last_stopped_at).toLocaleString('zh-CN',{hour12:false}));
        if(watch.notification_outcome_unknown>0)line('通知发布结果待核对',watch.notification_outcome_unknown+'条；为避免重复弹出，不会自动重发通知，可在聊天和通知中心查看原消息');
        if(watch.notification_outcome_unknown===-1)line('本机通知记录','暂不可读取；未将其视为没有通知');
      }
      else line('当前后台检查','暂不可读取');
      if(watch?.reason==='local_delivery_state_unavailable')line('本机投递状态','本机通知或同步记录暂不可用；为避免重复通知，已暂停本次处理并退避。');
      const preferences=answer('getNotificationPreferences');
      if(preferences?.ok===true)line('消息通知偏好',preferences.enabled?'已开启；按分类和免打扰时段处理':'已关闭');
      line('系统推送','尚未接入；进程被系统结束后无法保证收到消息');
      line('vivo 系统通道','尚未接入厂商 SDK 和应用凭据；打开后台设置不能替代系统推送');
      line('横幅条件',data.heads_up_possible===true?'应用权限与回复渠道满足基础条件':data.heads_up_possible===false?'尚未满足全部基础条件':'未确认');
      box.append(node('p','系统勿扰、会话通知和手机厂商策略仍会影响横幅。读取状态不申请权限、不启动检查，也不保证每条消息弹出。'));
      box.append(node('p','当前仍是你主动开启的后台检查，按目标轮流同步，网络失败会降低检查频率。Android 的后台运行限制仍然适用，不能保证整夜运行、进程被结束或强制停止后的送达。消息已接收、通知已发布和用户打开是不同状态；打开不代表已读证明。'));
      const background=node('button','打开后台运行设置');background.type='button';background.className='secondary-button';
      background.disabled=typeof window.AsteriaChat?.requestPhonePerceptionPermission!=='function'||typeof nativeAsync!=='function';
      background.onclick=async()=>{
        background.disabled=true;
        try{await nativeAsync('requestPhonePerceptionPermission',['battery']);if(visible())note('已提出打开系统后台运行设置；请自行检查 Asteria Chat 的后台限制。不会启用采集或改变通知开关，也不能保证进程结束后送达。');}
        catch(_){if(visible())note('无法打开后台设置，请从手机设置中查看 Asteria Chat 的后台运行限制。');}
        finally{background.disabled=false;}
      };box.append(background);
      get('notification-settings-open').disabled=data.settings_available!==true;
      get('notification-permission-request').disabled=typeof window.AsteriaChat?.requestNotificationPermission!=='function';
    }catch(error){box.append(node('p',errorText(error)));get('notification-settings-open').disabled=true;}
  }
  function openSystemSettings(){
    try{const value=answer('openNotificationSettings');if(value?.ok===true&&value.settings_opening===true)note('已向系统提出打开通知设置；返回后会重新读取，是否显示由系统决定。');else note('当前不能打开系统设置：'+(value?.error||'请更新Android客户端。'));}
    catch(error){note(errorText(error));}
  }
  function permission(){
    try{const value=answer('requestNotificationPermission');
      if(value?.ok!==true){note('当前不能申请通知权限，请从手机设置中查看 Asteria Chat 的通知权限。');return;}
      note(value.granted===true?'当前通知权限已允许。':'已提出本次通知权限请求；若系统不再显示提示，请打开系统通知设置。');refresh();}
    catch(error){note(errorText(error));}
  }
  function open(preferences=false){
    if(typeof openSettings!=='function')return false;
    window.ChatSettingsHub?.close();hideMoreMenu();openSettings();
    const target=get(preferences?'notification-preferences':'notification-diagnostics');
    if(!target)return false;
    if(preferences)window.ChatNotificationPreferences?.refresh();
    else{target.open=true;refresh();}
    if(typeof target.scrollIntoView==='function')target.scrollIntoView({block:'start',behavior:'auto'});
    return true;
  }
  function init(){
    const section=node('section','');section.id='reply-accounts';section.className='reply-accounts';section.setAttribute('aria-label','各 Bot 后台收件');
    const heading=node('div','');heading.className='reply-account-heading';heading.append(node('h3','各 Bot 后台收件'));const reload=node('button','刷新');reload.type='button';reload.className='text-button';reload.id='reply-accounts-refresh';reload.onclick=()=>{targetNote(accountNote,'');refresh();};heading.append(reload);
    accountList=node('div','');accountList.id='reply-accounts-list';accountNote=node('p','');accountNote.id='reply-accounts-note';accountNote.className='appearance-help';accountNote.setAttribute('role','status');
    section.append(heading,node('p','每个服务器都需先真实登录，并为该 Bot 开启一次“新回复提醒”。切换聊天不会发送消息；停止一个目标不关闭其他目标。'),accountList,accountNote,node('p','这是 Android 系统通知，不是手机短信。后台检查依赖服务仍在运行，不等于进程退出后也可靠的系统推送。'));
    get('notification-diagnostics').before(section);
    get('notification-diagnostics').addEventListener('toggle',()=>{if(visible()){note('');refresh();}});
    get('notification-status-refresh').onclick=()=>{note('');refresh();};get('notification-settings-open').onclick=openSystemSettings;get('notification-permission-request').onclick=permission;
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});window.addEventListener('focus',refresh);
    new MutationObserver(()=>refresh()).observe(get('settings-dialog'),{attributes:true,attributeFilter:['open']});
  }
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return{refresh,accounts,activateAccount,open:()=>open(false),openPreferences:()=>open(true)};
})();
