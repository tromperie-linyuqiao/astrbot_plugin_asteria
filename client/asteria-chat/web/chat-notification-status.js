'use strict';
/* Inspect the existing Android channels and watch. Reading never starts it. */
window.ChatNotificationStatus=(()=>{
  const node=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n;};
  const get=id=>document.getElementById(id),settingsVisible=()=>get('settings-dialog')?.open,visible=()=>settingsVisible()&&get('notification-diagnostics')?.open;
  let operation='',accountList,accountNote,copying=false;
  const yes=value=>value===true?'已允许':value===false?'未允许':'未提供';
  const importance={none:'已关闭',min:'最低',low:'低',default:'普通',high:'高',unspecified:'未指定'};
  const watchStates={starting:'正在核对会话',running:'运行中',reconnecting:'正在重连',stopped:'已停止'};
  const watchReasons={notifications_not_enabled:'登录已保存，尚未开启此 Bot 的后台收件',service_not_running:'登录已保存，后台收件当前未运行',system_time_limit:'Android 已达到后台同步时限；需要回到应用后自行开启',service_destroyed:'后台服务已结束；系统不保证重新启动',foreground_start_not_allowed:'系统暂不允许启动后台检查',watch_start_unavailable:'后台检查未能启动',notification_permission:'系统通知权限或渠道未开启',notification_channel_blocked:'聊天回复渠道已关闭，请在系统设置中处理',login_expired:'登录已失效，请重新登录此服务器后开启收件',authentication_changed:'登录状态已改变',session_unavailable:'当前会话暂不可用',user_stopped:'已由你停止',notifications_disabled:'消息通知已关闭',cursor_unavailable_open_chat:'历史同步位置已不可用，请打开聊天核对，系统不会重弹旧消息',foreground_ui_owns_reads:'当前由聊天页面同步',network_or_history_unavailable:'网络或记录暂不可读取，将按退避节奏重试',local_delivery_state_unavailable:'本机通知或同步记录暂不可用，已暂停并退避',account_unavailable:'已保存的登录不可用，请重新登录此服务器',credential_unavailable:'已保存的登录不可用，请重新登录此服务器'};
  const syncStates={not_checked:'尚未读取',catching_up:'正在按服务器顺序补齐，每次最多32条',synced:'已补齐至本次服务器读取位置',baseline_saved:'初次位置已保存，不补弹旧消息',foreground_reconciled:'已由前台记录校准',cursor_unavailable:'旧同步位置已不可用，等待打开聊天核对',legacy_history_window:'服务器仅提供最近记录窗口',legacy_cursor_outside_window:'旧位置已超出服务器近期窗口，无法证明遗漏均已补齐'};
  const noticeOutcomes={posted:'已请求系统发布并保存本机记录，是否显示待手机核对',posting_unknown:'发布结果待核对；不会自动重发'};
  const diagnosticErrors={network_or_history_unavailable:watchReasons.network_or_history_unavailable,local_delivery_state_unavailable:watchReasons.local_delivery_state_unavailable};
  const stopReasons={unknown:'停止原因未提供',user_stopped:watchReasons.user_stopped,notifications_disabled:watchReasons.notifications_disabled,notification_permission:watchReasons.notification_permission,not_enabled:'尚未开启后台收件',notifications_not_enabled:watchReasons.notifications_not_enabled,system_time_limit:'达到 Android 后台同步时限',service_destroyed:watchReasons.service_destroyed,foreground_start_not_allowed:watchReasons.foreground_start_not_allowed,watch_start_unavailable:watchReasons.watch_start_unavailable,restart_registration_unavailable:'暂时无法恢复后台收件登记',watch_stopped:'后台收件服务已停止',session_unavailable:watchReasons.session_unavailable,authentication_changed:watchReasons.authentication_changed,logged_out:'已退出登录',server_changed:'已切换服务器',login_expired:watchReasons.login_expired,login_required:'需要重新登录'};
  const readReasons={foreground_ui_owns_reads:watchReasons.foreground_ui_owns_reads,cursor_unavailable_open_chat:watchReasons.cursor_unavailable_open_chat};
  const exitReasons={unknown:'未提供',exit_self:'应用自行退出',signaled:'进程收到系统信号',low_memory:'系统内存不足',crash:'应用崩溃',crash_native:'应用底层崩溃',anr:'应用无响应',initialization_failure:'应用初始化失败',permission_change:'系统权限发生变化',excessive_resource_usage:'系统报告资源使用过多',user_requested:'系统报告用户请求结束',user_stopped:'系统报告用户停止应用',dependency_died:'依赖进程结束',other:'其他系统原因',freezer:'系统冻结进程',package_state_change:'安装包状态变化',package_updated:'应用已更新'};
  const own=(value,key)=>value&&Object.prototype.hasOwnProperty.call(value,key);
  const code=(value,allowed)=>typeof value==='string'&&own(allowed,value)?value:'unknown';
  const stamp=value=>Number.isSafeInteger(value)&&value>0&&value<=8640000000000000?value:null;
  const timeText=value=>stamp(value)?new Date(value).toLocaleString('zh-CN',{hour12:false}):'尚无记录';
  const diagnosticTime=(data,key)=>own(data,key)?timeText(data[key]):'未提供';
  function accountSummary(row){
    if(row.reason==='cursor_unavailable_open_chat'||row.diagnosis?.read_reason==='cursor_unavailable_open_chat'||['cursor_unavailable','legacy_cursor_outside_window'].includes(row.message_sync))return '等打开聊天核对';
    if(row.state==='stopped'||row.running===false){
      return ['notifications_not_enabled','notifications_disabled','user_stopped','not_enabled'].includes(row.reason)||(row.registered===false&&!row.reason)?'未开启':'服务已停';
    }
    if(row.state==='reconnecting')return '正在重连';
    if(row.running===true&&stamp(row.last_sync_at)&&Date.now()-row.last_sync_at>=0&&Date.now()-row.last_sync_at<=300000)return '最近已同步';
    if(row.state==='starting'||row.running===true)return '等待下次读取';
    return '状态未提供';
  }
  function safeDiagnosis(value){
    if(!value||typeof value!=='object'||Array.isArray(value))return null;
    const result={};
    for(const key of ['last_attempt_at','last_success_at','last_notice_posted_at','stopped_at'])if(own(value,key))result[key]=stamp(value[key]);
    for(const [key,allowed]of [['last_notice_outcome',noticeOutcomes],['last_error',diagnosticErrors],['stop_reason',stopReasons],['read_reason',readReasons]])if(own(value,key))result[key]=value[key]===null||value[key]===''?null:code(value[key],allowed);
    return result;
  }
  const answer=method=>{const bridge=window.AsteriaChat;if(!bridge||typeof bridge[method]!=='function')return null;const value=bridge[method]();return typeof value==='string'?JSON.parse(value):value;};
  function accounts(watch=answer('getReplyWatchStatus')){
    if(!Array.isArray(watch?.accounts))return null;
    const seen=new Set();return watch.accounts.filter(row=>{
      if(!row||typeof row.account_id!=='string'||!row.account_id||row.account_id.length>256||seen.has(row.account_id)||typeof row.server!=='string'||typeof row.username!=='string'||!row.username||row.username.length>120)return false;
      try{const url=new URL(row.server);if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash)return false;}catch(_){return false;}
      seen.add(row.account_id);return true;
    }).map(row=>({account_id:row.account_id,server:row.server,username:row.username,title:typeof row.title==='string'?row.title.slice(0,80):'',session_id:typeof row.session_id==='string'?row.session_id:'',state:row.state,reason:row.reason,running:typeof row.running==='boolean'?row.running:null,can_activate:row.can_activate===true,registered:row.registered,enabled:typeof row.enabled==='boolean'?row.enabled:null,last_sync_at:row.last_sync_at,message_sync:row.message_sync,receipt_unavailable_count:row.receipt_unavailable_count,last_message_preview:typeof row.last_message_preview==='string'?row.last_message_preview.slice(0,360):'',last_message_id:row.last_message_id,last_message_observed_at:row.last_message_observed_at,diagnosis:safeDiagnosis(row.diagnosis)}));
  }
  function accountDetails(row){
    const details=node('details','');details.className='reply-account-diagnostics';details.append(node('summary','收件诊断明细'));
    const list=node('dl',''),add=(label,value)=>list.append(node('dt',label),node('dd',value)),data=row.diagnosis;
    const detailCode=(key,labels)=>!own(data,key)?'未提供':data[key]===null?'尚无记录':labels[data[key]]||'状态未提供';
    add('最近尝试读取',diagnosticTime(data,'last_attempt_at'));add('最近成功读取',own(data,'last_success_at')?diagnosticTime(data,'last_success_at'):stamp(row.last_sync_at)?timeText(row.last_sync_at)+'（既有记录）':'未提供');
    add('最近请求发布通知',diagnosticTime(data,'last_notice_posted_at'));add('最近发布结果',detailCode('last_notice_outcome',noticeOutcomes));
    add('读取说明',detailCode('read_reason',readReasons));add('最近读取错误',detailCode('last_error',diagnosticErrors));add('最近停止',diagnosticTime(data,'stopped_at'));add('停止原因',own(data,'stop_reason')?detailCode('stop_reason',stopReasons):stopReasons[row.reason]||watchReasons[row.reason]||'未提供');
    details.append(list,node('p','“最近已同步”仅指五分钟内已有读取。'+(data?'读取成功只表示核对过服务器记录；请求发布不证明横幅、响铃或屏幕显示成功。':'此客户端未提供新增诊断项；已有读取时间和状态仍可参考，不能据此认定后台收件正常。')));
    return details;
  }
  function diagnosticSnapshot(){
    // Never serialize bridge objects: they also contain credentials, identities and message previews.
    const read=method=>{try{return answer(method);}catch(_){return null;}},watch=read('getReplyWatchStatus'),system=read('getNotificationStatus'),config=read('getConfig');
    const bool=value=>typeof value==='boolean'?value:null,metadata=value=>typeof value==='string'?value.replace(/[\u0000-\u001f\u007f]/g,'').slice(0,80):null;
    const version=typeof config?.version==='string'&&/^\d{1,3}\.\d{1,3}\.\d{1,3}(?:[-+][A-Za-z0-9.-]{1,32})?$/.test(config.version)?config.version:null;
    const list=accounts(watch),exit=watch?.diagnosis?.last_exit;
    const channels={};for(const key of ['reply_channel','proactive_channel','reminder_channel','watch_channel']){
      const channel=system?.[key];channels[key]={exists:bool(channel?.exists),blocked:bool(channel?.blocked),importance:code(channel?.importance_name,importance),sound:bool(channel?.sound),vibration:bool(channel?.vibration)};
    }
    return {schema:1,app_version:version,device:{manufacturer:metadata(system?.device_manufacturer),model:metadata(system?.device_model),android:metadata(system?.android_release)},
      system:{available:system?.ok===true,permission:bool(system?.runtime_permission_granted),app_notifications_enabled:bool(system?.app_notifications_enabled),channels,battery_saver:bool(system?.battery_saver),battery_optimization_ignored:bool(system?.battery_optimization_ignored),background_restricted:bool(system?.background_restricted),background_data_restricted:bool(system?.background_data_restricted),heads_up_possible:bool(system?.heads_up_possible)},
      watch:{available:!!watch&&watch.ok!==false,state:code(watch?.state,watchStates),reason:code(watch?.reason,{...watchReasons,...stopReasons}),resume_on_foreground_required:bool(watch?.resume_on_foreground_required),diagnosis_provided:watch?.diagnosis?.schema===1,last_exit:exit?{reason:code(exit.reason,exitReasons),timestamp:stamp(exit.timestamp)}:null,targets_provided:list!==null,targets:list===null?[]:list.slice(0,64).map((row,index)=>({target:index+1,state:code(row.state,watchStates),summary:accountSummary(row),running:row.running,enabled:row.enabled,reason:code(row.reason,{...watchReasons,...stopReasons}),message_sync:code(row.message_sync,syncStates),last_sync_at:stamp(row.last_sync_at),diagnosis:row.diagnosis})),targets_truncated:list!==null&&list.length>64},
      limits:'本机匿名状态快照；未测试真实收件、横幅或声音；未接入系统推送。null或unknown表示未提供或未确认。'};
  }
  function renderDiagnosticOverview(){
    const box=get('reply-diagnostics-overview');if(!box)return;box.replaceChildren();
    try{
      const data=diagnosticSnapshot(),list=node('dl',''),add=(label,value)=>list.append(node('dt',label),node('dd',value)),flag=(value,on,off)=>value===true?on:value===false?off:'未提供';
      add('本机 App 版本',data.app_version||'未提供');add('手机与系统',[data.device.manufacturer,data.device.model,data.device.android?'Android '+data.device.android:''].filter(Boolean).join(' · ')||'未提供');
      add('系统通知权限',yes(data.system.permission));add('应用通知总开关',yes(data.system.app_notifications_enabled));
      const replies=data.system.channels.reply_channel;add('聊天回复渠道',replies.exists===false?'尚未建立':replies.blocked===true?'系统已关闭':importance[replies.importance]||'未提供');
      add('后台运行',flag(data.system.background_restricted,'系统已限制','系统未报告限制'));add('省电模式',flag(data.system.battery_saver,'已开启','未开启'));add('电池优化',flag(data.system.battery_optimization_ignored,'已豁免','仍受系统优化管理'));add('后台联网',flag(data.system.background_data_restricted,'省流量模式已限制','系统未报告省流量限制'));
      add('最近进程退出原因',data.watch.last_exit?exitReasons[data.watch.last_exit.reason]||'未提供':'未提供');add('最近进程退出时间',data.watch.last_exit?timeText(data.watch.last_exit.timestamp):'未提供');
      if(data.watch.resume_on_foreground_required===true)add('恢复条件','已达到系统后台时限；原收件开关保留，需回到应用前台恢复。');
      box.append(list,node('p','进程退出原因由 Android 提供，可能是先前一次退出；不说明当前仍在收件。系统权限和渠道满足基础条件也不保证横幅或响铃。'));
    }catch(_){box.append(node('p','本机诊断暂不可读取；不能据此认定后台收件正常。'));}
  }
  async function copyDiagnosis(){
    if(copying)return;copying=true;
    const button=get('reply-diagnostics-copy'),text=get('reply-diagnostics-text'),fallback=get('reply-diagnostics-export'),status=get('reply-diagnostics-note');button.disabled=true;
    try{
      const value=JSON.stringify(diagnosticSnapshot(),null,2);text.value=value;fallback.hidden=false;fallback.open=true;
      if(typeof navigator.clipboard?.writeText!=='function')throw Error('clipboard_unavailable');
      await navigator.clipboard.writeText(value);targetNote(status,'已复制匿名收件诊断。仅复制到本机剪贴板，没有发送消息或上传。');
    }catch(_){targetNote(status,'未能访问剪贴板。可在下方只读文本中长按或全选复制匿名诊断。');text.focus();text.select();}
    finally{button.disabled=false;copying=false;}
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
  function startAccount(row){
    if(operation)return;operation=row.account_id;renderAccounts();
    try{
      const permission=answer('requestNotificationPermission');
      if(permission?.granted!==true){targetNote(accountNote,'请允许系统通知后再次点击开启收件。未启动其他 Bot。');return;}
      const raw=window.AsteriaChat.startReplyWatchAccount(row.account_id),result=typeof raw==='string'?JSON.parse(raw):raw;
      if(result?.ok!==true){targetNote(accountNote,result?.error==='notifications_disabled'?'请先在通知设置中开启消息通知总开关。':'未能开启，请检查登录和通知权限后再试。');return;}
      targetNote(accountNote,'已提交开启请求，实际运行状态会在此更新。不会切换当前聊天。');
    }catch(_){targetNote(accountNote,'开启结果暂未确认，请刷新状态核对。');}
    finally{operation='';refresh();}
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
    if(!accountList)return;
    const expanded=new Set([...accountList.querySelectorAll('.reply-account-card')].filter(card=>card.querySelector('.reply-account-diagnostics')?.open).map(card=>card.dataset.accountId));
    accountList.replaceChildren();
    let list;try{list=accounts(watch);}catch(_){accountList.append(node('p','暂时无法读取后台收件列表，请刷新。'));return;}
    if(list===null){accountList.append(node('p','此 Android 版本尚未提供多 Bot 收件列表。请更新安装包；旧版本仍只检查当前对话。'));return;}
    if(!list.length){accountList.append(node('p','还没有已保存的 Bot。分别登录服务器并打开长期对话后，会自动出现在这里。'));return;}
    for(const row of list){
      const card=node('article','');card.className='reply-account-card';card.dataset.accountId=row.account_id;
      const heading=node('div','');heading.className='reply-account-heading';const title=node('strong',row.title||'聊天 Bot'),badge=node('span',accountSummary(row));badge.className='reply-account-state';badge.dataset.running=String(row.running);heading.append(title,badge);
      const address=node('p',new URL(row.server).host+' · '+row.username);address.className='reply-account-address';card.append(heading,address);
      if(row.last_message_preview){const preview=node('div','');preview.className='reply-account-preview';preview.append(node('small','最近收到的消息'),node('span',row.last_message_preview));card.append(preview);}
      if(row.reason)card.append(node('p',stopReasons[row.reason]||watchReasons[row.reason]||'状态已变化，可打开聊天或刷新核对。'));
      if(!row.can_activate)card.append(node('p','已保存的登录不可用，请在连接设置中选择此服务器并输入密码重新登录。'));
      if(Number.isFinite(row.last_sync_at)&&row.last_sync_at>0)card.append(node('p','最近读取：'+new Date(row.last_sync_at).toLocaleString('zh-CN',{hour12:false})));
      if(row.message_sync)card.append(node('p','消息同步：'+(syncStates[row.message_sync]||'等待核对')));
      if(Number.isInteger(row.receipt_unavailable_count)&&row.receipt_unavailable_count>0)card.append(node('p',row.receipt_unavailable_count+' 条原消息已不可用于确认；其他消息继续同步。'));
      if(row.receipt_unavailable_count===-1)card.append(node('p','本机收件确认记录暂不可读取。'));
      const diagnosticDetails=accountDetails(row);diagnosticDetails.open=expanded.has(row.account_id);card.append(diagnosticDetails);
      const actions=node('div','');actions.className='reply-account-actions';
      const activate=node('button',row.can_activate?'打开此 Bot':'需要重新登录');activate.type='button';activate.className='secondary-button';activate.dataset.accountAction='activate';activate.disabled=!!operation||!row.can_activate||typeof window.activateReplyAccount!=='function';activate.onclick=()=>activateAccount(row.account_id);
      const stop=node('button','停止此 Bot 收件');stop.type='button';stop.className='text-button';stop.dataset.accountAction='stop';stop.disabled=!!operation||row.registered===false||typeof window.AsteriaChat?.stopReplyWatchAccount!=='function';stop.onclick=()=>stopAccount(row);
      const start=node('button','开启此 Bot 收件');start.type='button';start.className='text-button';start.dataset.accountAction='start';start.hidden=row.running;start.disabled=!!operation||!row.can_activate||typeof window.AsteriaChat?.startReplyWatchAccount!=='function';start.onclick=()=>startAccount(row);
      stop.hidden=!row.running&&!row.enabled;
      actions.append(activate,start,stop);card.append(actions);accountList.append(card);
    }
  }
  function note(value){get('notification-system-note').textContent=value;}
  function refresh(){
    window.ChatConnections?.refreshContacts?.();
    if(!settingsVisible())return;
    renderAccounts();renderDiagnosticOverview();window.ChatConnections?.refreshSaved?.();
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
      if(data.runtime_permission_granted===false||data.app_notifications_enabled===false){const blocked=node('p','系统通知总权限尚未获准。请使用下方“打开系统通知设置”检查；应用不会重新创建渠道绕过你的静音选择。');blocked.className='notification-blocked-note';box.append(blocked);}
      for(const [field,label]of [['reply_channel','聊天回复渠道'],['proactive_channel','主动消息渠道'],['reminder_channel','日程提醒渠道'],['watch_channel','后台检查常驻渠道']]){
        const channel=data[field];line(label,!channel?'未提供':channel.exists===false?'尚未建立':channel.blocked===true?'系统已关闭':importance[channel.importance_name]||'状态待确认');
      }
      const categories=node('div','');categories.className='notification-category-controls';
      for(const [kind,label]of [['reply','聊天回复'],['proactive','主动消息'],['reminder','日程提醒']]){
        const channel=data[kind+'_channel'];if(!channel)continue;
        const card=node('section','');card.append(node('strong',label),node('p','声音：'+yes(channel.sound)+' · 振动：'+yes(channel.vibration)));
        const settings=node('button','设置声音、振动与横幅');settings.type='button';settings.dataset.notificationCategory=kind;
        settings.disabled=typeof window.AsteriaChat?.openNotificationCategorySettings!=='function';
        settings.onclick=()=>{try{const raw=AsteriaChat.openNotificationCategorySettings(kind),r=typeof raw==='string'?JSON.parse(raw):raw;note(r?.ok&&r.settings_opening?'已提出打开此类别的系统通知设置；返回后会重新读取。':'无法打开此类别，请在手机系统设置中查看 Asteria Chat。');}catch(_){note('设置入口暂不可用，请从手机设置中打开。');}};
        const test=node('button','检查这类通知能否显示');test.type='button';test.dataset.notificationTest=kind;
        test.disabled=typeof window.AsteriaChat?.testLocalNotification!=='function';
        test.onclick=()=>{test.disabled=true;try{const raw=AsteriaChat.testLocalNotification(kind),r=typeof raw==='string'?JSON.parse(raw):raw;
          const reasons={notification_permission:'系统通知权限未允许。',notification_channel_blocked:'此类别被系统关闭。',notification_preference_or_quiet:'此类消息被应用开关或免打扰时段拦下。'};
          note(r?.ok===true&&r.posted===true?'已提交一条本机显示检查；不代表已在屏幕上出现，请查看通知栏和横幅。没有联系 Bot 或发送消息。':reasons[r?.error]||'显示检查结果未确认，请查看通知栏；不会自动重复发布。');
        }catch(_){note('显示检查结果未确认，请查看通知栏。');}finally{setTimeout(()=>{test.disabled=false;},1500);}};
        card.append(settings,test);categories.append(card);
      }
      box.append(categories,node('p','三类消息可以分别设置系统提示方式；新类别首次沿用旧回复渠道设置。应用不会替你解除静音或修改系统勿扰。'));
      if(data.device_manufacturer||data.device_model)line('本机',String(data.device_manufacturer||'')+' '+String(data.device_model||'')+' · Android '+String(data.android_release||'未提供'));
      const flag=(value,on,off)=>value===true?on:value===false?off:'未提供';
      line('后台运行',flag(data.background_restricted,'系统已限制','系统未报告限制'));line('省电模式',flag(data.battery_saver,'已开启','未开启'));
      line('电池优化',flag(data.battery_optimization_ignored,'已豁免','仍受系统优化管理'));line('后台联网',flag(data.background_data_restricted,'省流量模式已限制','系统未报告省流量限制'));
      if(/vivo|iqoo/i.test(String(data.device_manufacturer)+' '+String(data.device_model))){
        const help=node('details','');help.className='notification-device-help';help.append(node('summary','vivo / iQOO 收不到消息时'));
        help.append(node('p','先用上面的本机显示检查：能在通知栏看到但没有横幅，检查悬浮通知、锁屏通知和系统勿扰；完全看不到，先检查应用通知权限与对应类别。'));
        help.append(node('p','只有切到后台后不再收到时，再检查 Asteria Chat 的自启动、后台耗电管理和后台联网许可，并可在最近任务中锁定应用。各系统版本名称可能不同；本页无法确认 vivo 的自启动许可。'));
        help.append(node('p','本机显示检查通过不证明后台收件运行。下方各 Bot 要显示已开启，且最近读取时间应持续更新；系统结束进程或强制停止后仍需重新打开应用。'));
        const link=node('a','vivo 官方消息提醒说明');link.href='https://kefu.vivo.com.cn/robot/imgmsgData/3dfcdb616d0542b4baa4e9ead6d75c5e/index_1.html';link.target='_blank';link.rel='noopener noreferrer';help.append(link);box.append(help);
      }
      const watch=answer('getReplyWatchStatus');
      if(watch&&watch.ok!==false){
        const targets=accounts(watch);line('后台收件',targets===null?(watchStates[watch.state]||(watch.running===true?'运行中':'尚未确认')):targets.length+'个目标 · '+targets.filter(row=>row.running).length+'个运行中');
        if(watch.reason)line('检查说明',stopReasons[watch.reason]||watchReasons[watch.reason]||'检查状态发生变化，可刷新或重新打开聊天核对。');
        if(watch.resume_on_foreground_required===true)line('恢复条件','达到系统后台时限；原收件开关保留，需要回到应用前台后恢复。未由你关闭的目标才会恢复。');
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
      if(/vivo|iqoo/i.test(String(data.device_manufacturer)))line('vivo 系统推送','尚未接入；后台设置不能替代厂商推送');
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
  function openWatchSettings(){
    const status=get('reply-watch-settings-note');
    try{
      const bridge=window.AsteriaChat;
      if(typeof bridge?.openNotificationCategorySettings!=='function'){
        targetNote(status,'请在 Android 客户端打开此设置。');return;
      }
      const raw=bridge.openNotificationCategorySettings('watch');
      const result=typeof raw==='string'?JSON.parse(raw):raw;
      if(result?.ok===true&&result.settings_opening===true)
        targetNote(status,'已请求打开「后台回复监控」。可按手机提供的选项收起或关闭常驻提示。');
      else if(result?.error==='watch_channel_not_created')
        targetNote(status,'此手机还没有建立后台收件渠道，首次开启收件后可在这里设置。');
      else targetNote(status,'手机未打开单独的渠道设置。可以在系统通知设置中查找「后台回复监控」。');
    }catch(_){targetNote(status,'暂时无法打开常驻提示设置。');}
  }
  function permission(){
    try{const value=answer('requestNotificationPermission');
      if(value?.ok!==true){note('当前不能申请通知权限，请从手机设置中查看 Asteria Chat 的通知权限。');return;}
      note(value.granted===true?'当前通知权限已允许。':'已提出本次通知权限请求；若系统不再显示提示，请打开系统通知设置。');refresh();}
    catch(error){note(errorText(error));}
  }
  function open(preferences=false){
    if(typeof openSettings!=='function')return false;
    window.ChatSettingsHub?.close();hideMoreMenu();openSettings('notifications');
    const target=get(preferences?'notification-preferences':'notification-diagnostics');
    if(!target)return false;
    if(preferences)window.ChatNotificationPreferences?.refresh();
    else{target.open=true;refresh();}
    if(typeof target.scrollIntoView==='function')target.scrollIntoView({block:'start',behavior:'auto'});
    return true;
  }
  function init(){
    const section=node('section','');section.id='reply-accounts';section.className='reply-accounts';section.setAttribute('aria-label','已保存的 Bot');
    const heading=node('div','');heading.className='reply-account-heading';heading.append(node('h3','已保存的 Bot'));const reload=node('button','刷新');reload.type='button';reload.className='text-button';reload.id='reply-accounts-refresh';reload.onclick=()=>{targetNote(accountNote,'');refresh();};heading.append(reload);
    const diagnostics=node('div','');diagnostics.className='reply-diagnostics-toolbar';const copy=node('button','复制收件诊断');copy.id='reply-diagnostics-copy';copy.type='button';copy.className='secondary-button';copy.onclick=copyDiagnosis;diagnostics.append(copy,node('p','只复制匿名状态、时间和本机系统信息，不含账号、服务器地址或消息内容。'));
    const copyNote=node('p','');copyNote.id='reply-diagnostics-note';copyNote.className='appearance-help';copyNote.setAttribute('role','status');
    const exported=node('details','');exported.id='reply-diagnostics-export';exported.hidden=true;exported.append(node('summary','查看可手动复制的匿名诊断'));
    const text=node('textarea','');text.id='reply-diagnostics-text';text.readOnly=true;text.rows=8;text.spellcheck=false;text.setAttribute('aria-label','可手动复制的匿名收件诊断');exported.append(text);
    const device=node('details','');device.className='reply-account-diagnostics';device.id='reply-diagnostics-device';device.append(node('summary','本机权限与后台状态'));const overview=node('div','');overview.id='reply-diagnostics-overview';device.append(overview);
    accountList=node('div','');accountList.id='reply-accounts-list';accountNote=node('p','');accountNote.id='reply-accounts-note';accountNote.className='appearance-help';accountNote.setAttribute('role','status');
    section.append(heading,node('p','正常登录并打开对话后即可保留登录。各 Bot 的收件开关独立；开启或停止一个目标不会切换聊天，也不影响其他目标。'),node('p','同步状态反映最近一次读取，不代表横幅或响铃成功。'),accountList,accountNote,device,diagnostics,copyNote,exported,node('p','后台收件需要 Android 保留服务运行；尚未接入系统推送。应用被强制停止后，重新打开可恢复同步。'));
    get('notification-diagnostics').before(section);
    get('notification-diagnostics').addEventListener('toggle',()=>{if(visible()){note('');refresh();}});
    get('notification-status-refresh').onclick=()=>{note('');refresh();};get('notification-settings-open').onclick=openSystemSettings;get('notification-permission-request').onclick=permission;
    get('reply-watch-settings').onclick=openWatchSettings;
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});window.addEventListener('focus',refresh);
    new MutationObserver(()=>refresh()).observe(get('settings-dialog'),{attributes:true,attributeFilter:['open']});
  }
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return{refresh,accounts,activateAccount,open:()=>open(false),openPreferences:()=>open(true)};
})();
