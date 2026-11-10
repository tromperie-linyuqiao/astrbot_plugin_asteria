'use strict';
window.ChatDevices=(()=>{
  const scope=()=>JSON.stringify([state.server,state.username,state.activeId,chatAuthEpoch]);
  let context=null,contextOwner='',lease=null,expiry=null,checking=false,visibleStamp='',claimGeneration=0;
  function device(){
    const nativeId=nativeConfig().deviceId;if(nativeId)return nativeId;
    let id=localStorage.getItem('texas-device-v1');if(!id){id='web-'+crypto.randomUUID();localStorage.setItem('texas-device-v1',id);}return id;
  }
  async function request(action,fields){const owner=scope();const result=await apiClient.json('POST','/chat/devices',{session_id:state.activeId,device_id:device(),action,...fields});if(owner!==scope())throw Error('会话已变化，原设备操作已丢弃。');return result;}
  function rememberLease(result,id){
    const voice=result.voice;if(!result.accepted||voice?.device_id!==device()||voice?.call_id!==id)throw Error('另一设备正在通话。可点“在此设备继续”，等待原设备结束后再开始。');
    const seconds=voice.expires_at-result.server_time-3;if(!(seconds>0&&seconds<=240))throw Error('当前语音设备确认已过期。');
    clearTimeout(expiry);lease={id,owner:scope()};
    expiry=setTimeout(()=>{lease=null;window.ChatCall?.end();showNotice('设备通话确认已过期，语音已结束；文字和草稿保留。');},seconds*1000);
  }
  async function acquire(id,takeover=false){const ticket=++claimGeneration;const result=await request(takeover?'voice_takeover':'voice_claim',{call_id:id});if(ticket!==claimGeneration)throw Error('旧通话确认已丢弃。');rememberLease(result,id);}
  async function check(id){const selected=lease;if(!selected||selected.owner!==scope()||selected.id!==id)throw Error('本机已不再持有这次语音通话，请重新开始。');const result=await request('voice_check',{call_id:id});if(!lease||lease.id!==id||lease.owner!==selected.owner)throw Error('旧通话确认已丢弃。');rememberLease(result,id);}
  function release(id){if(!lease||lease.id!==id)return;const owned=lease.owner===scope();lease=null;clearTimeout(expiry);if(owned)void request('voice_release',{call_id:id}).catch(()=>{});}
  function observe(value){
    context=value?.schema===1?value:null;contextOwner=scope();
    if(lease&&lease.owner===scope()&&!checking){checking=true;const selected=lease,id=lease.id;void check(id).catch(()=>{if(!lease||lease.id!==id||lease.owner!==selected.owner)return;window.ChatCall?.end();showNotice('当前设备通话确认失效，已停止声音；可以在所选设备重新开始。');}).finally(()=>{checking=false;});}
  }
  function visible(ids,cursor){
    if(!context||contextOwner!==scope()||document.hidden||nativeConfig().foreground===false||!ids.length)return;
    const stamp=scope()+'|'+cursor;if(stamp===visibleStamp)return;visibleStamp=stamp;
    void request('visible',{message_ids:ids.slice(-32),read_cursor:String(cursor)}).then(observe).catch(()=>{});
  }
  function continueReading(){
    if(!context||contextOwner!==scope()){showNotice('这个服务器尚未提供设备接续位置；本机草稿保持不变。');return;}
    const rows=[...$('messages').querySelectorAll('.message-row')];
    const row=rows.find(r=>String(r.messageRecord?.serverId)===context.read_cursor);
    if(row)row.scrollIntoView({block:'center'});else showNotice('另一端的位置不在当前缓存中，请先同步记录。');
  }
  document.addEventListener('DOMContentLoaded',()=>{const b=document.createElement('button');b.className='menu-item';b.textContent='接着另一端读';b.onclick=()=>{hideMoreMenu();continueReading();};$('more-menu').append(b);});
  return {acquire,check,release,observe,visible,continueReading,backendVersion:()=>contextOwner===scope()?context?.backend_version:''};
})();
