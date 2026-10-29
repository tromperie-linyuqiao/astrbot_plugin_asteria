'use strict';
/* Inspect the existing Android channels and watch. Reading never starts it. */
window.ChatNotificationStatus=(()=>{
  const node=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n;};
  const get=id=>document.getElementById(id),visible=()=>get('settings-dialog')?.open&&get('notification-diagnostics')?.open;
  const yes=value=>value===true?'已允许':value===false?'未允许':'未提供';
  const importance={none:'已关闭',min:'最低',low:'低',default:'普通',high:'高',unspecified:'未指定'};
  const watchStates={starting:'正在核对会话',running:'运行中',reconnecting:'正在重连',stopped:'已停止'};
  const watchReasons={system_time_limit:'Android 已达到后台同步时限；需要回到应用后自行开启',service_destroyed:'后台服务已结束；系统不保证重新启动',foreground_start_not_allowed:'系统暂不允许启动后台检查',watch_start_unavailable:'后台检查未能启动',notification_permission:'系统通知权限或渠道未开启',login_expired:'登录已失效',authentication_changed:'登录状态已改变',session_unavailable:'当前会话暂不可用',user_stopped:'已由你停止',notifications_disabled:'消息通知已关闭',cursor_unavailable_open_chat:'历史同步位置已不可用，请打开聊天核对，系统不会重弹旧消息',foreground_ui_owns_reads:'当前由聊天页面同步',network_or_history_unavailable:'网络或记录暂不可读取，将按退避节奏重试'};
  const syncStates={not_checked:'尚未读取',catching_up:'正在按服务器顺序补齐，每次最多32条',synced:'已补齐至本次服务器读取位置',baseline_saved:'初次位置已保存，不补弹旧消息',foreground_reconciled:'已由前台记录校准',cursor_unavailable:'旧同步位置已不可用，等待打开聊天核对',legacy_history_window:'服务器仅提供最近记录窗口',legacy_cursor_outside_window:'旧位置已超出服务器近期窗口，无法证明遗漏均已补齐'};
  const answer=method=>{const bridge=window.AsteriaChat;if(!bridge||typeof bridge[method]!=='function')return null;const value=bridge[method]();return typeof value==='string'?JSON.parse(value):value;};
  function note(value){get('notification-system-note').textContent=value;}
  function refresh(){
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
      for(const [field,label]of [['reply_channel','聊天回复渠道'],['watch_channel','后台检查常驻渠道']]){
        const channel=data[field];line(label,!channel?'未提供':channel.exists===false?'尚未建立':channel.blocked===true?'系统已关闭':importance[channel.importance_name]||'状态待确认');
      }
      const watch=answer('getReplyWatchStatus');
      if(watch&&watch.ok!==false){
        line('当前后台检查',watchStates[watch.state]||(watch.running===true?'运行中':'尚未确认'));
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
      line('横幅条件',data.heads_up_possible===true?'应用权限与回复渠道满足基础条件':data.heads_up_possible===false?'尚未满足全部基础条件':'未确认');
      box.append(node('p','系统勿扰、会话通知和手机厂商策略仍会影响横幅。读取状态不申请权限、不启动检查，也不保证每条消息弹出。'));
      box.append(node('p','当前仍是用户主动开启的每30秒后台检查，网络失败会降低检查频率。Android 15 的此类后台同步累计受6小时/24小时时限约束，不能保证整夜运行、进程被结束或强制停止后的送达。消息已接收、通知已发布和用户打开是不同状态；打开不代表已读证明。'));
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
    get('notification-diagnostics').addEventListener('toggle',()=>{if(visible()){note('');refresh();}});
    get('notification-status-refresh').onclick=()=>{note('');refresh();};get('notification-settings-open').onclick=openSystemSettings;get('notification-permission-request').onclick=permission;
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});window.addEventListener('focus',refresh);
    new MutationObserver(()=>refresh()).observe(get('settings-dialog'),{attributes:true,attributeFilter:['open']});
  }
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return{refresh,open:()=>open(false),openPreferences:()=>open(true)};
})();
