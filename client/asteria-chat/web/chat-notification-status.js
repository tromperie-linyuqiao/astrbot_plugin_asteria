'use strict';
/* Inspect the existing Android channels and watch. Reading never starts it. */
window.ChatNotificationStatus=(()=>{
  const node=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n;};
  const get=id=>document.getElementById(id),visible=()=>get('settings-dialog')?.open&&get('notification-diagnostics')?.open;
  const yes=value=>value===true?'已允许':value===false?'未允许':'未提供';
  const importance={none:'已关闭',min:'最低',low:'低',default:'普通',high:'高',unspecified:'未指定'};
  const watchStates={starting:'正在核对会话',running:'运行中',reconnecting:'正在重连',stopped:'已停止'};
  const answer=method=>{const bridge=window.AsteriaChat;if(!bridge||typeof bridge[method]!=='function')return null;const value=bridge[method]();return typeof value==='string'?JSON.parse(value):value;};
  function note(value){get('notification-system-note').textContent=value;}
  function refresh(){
    if(!visible())return;
    const box=get('notification-system-state');box.replaceChildren();
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
      if(watch&&watch.ok!==false)line('当前后台检查',watchStates[watch.state]||(watch.running===true?'运行中':'尚未确认'));
      else line('当前后台检查','暂不可读取');
      line('横幅条件',data.heads_up_possible===true?'应用权限与回复渠道满足基础条件':data.heads_up_possible===false?'尚未满足全部基础条件':'未确认');
      box.append(node('p','系统勿扰、会话通知和手机厂商策略仍会影响横幅。读取状态不申请权限、不启动检查，也不保证每条消息弹出。'));
      get('notification-settings-open').disabled=data.settings_available!==true;
      get('notification-permission-request').disabled=typeof window.AsteriaChat?.requestNotificationPermission!=='function';
    }catch(error){box.append(node('p',errorText(error)));get('notification-settings-open').disabled=true;}
  }
  function openSettings(){
    try{const value=answer('openNotificationSettings');if(value?.ok===true&&value.settings_opening===true)note('已向系统提出打开通知设置；返回后会重新读取，是否显示由系统决定。');else note('当前不能打开系统设置：'+(value?.error||'请更新Android客户端。'));}
    catch(error){note(errorText(error));}
  }
  function permission(){
    try{const value=answer('requestNotificationPermission');note(value?.granted===true?'当前通知权限已允许。':'已提出本次通知权限请求，请查看系统提示。');refresh();}
    catch(error){note(errorText(error));}
  }
  function init(){
    get('notification-diagnostics').addEventListener('toggle',()=>{if(visible()){note('');refresh();}});
    get('notification-status-refresh').onclick=()=>{note('');refresh();};get('notification-settings-open').onclick=openSettings;get('notification-permission-request').onclick=permission;
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});window.addEventListener('focus',refresh);
    new MutationObserver(()=>refresh()).observe(get('settings-dialog'),{attributes:true,attributeFilter:['open']});
  }
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return{refresh};
})();
