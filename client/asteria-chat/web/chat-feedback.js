'use strict';
window.ChatFeedback=(()=>{
  const types=['表情不合适','动作对象错误','语音转写不对','语音播放异常','重复提醒','回复引用了错误记忆','其他'];
  const key=()=> 'texas-feedback-v1:'+JSON.stringify([state.server,state.username]);
  const clean=s=>String(s||'').replace(/\b(?:sk-|Bearer\s+)[A-Za-z0-9_\-.]{8,}/gi,'[凭据已遮蔽]').replace(/([?&](?:token|key|password)=)[^\s&]+/gi,'$1[已遮蔽]').slice(0,2000);
  function saved(){try{return JSON.parse(localStorage.getItem(key())||'[]');}catch(_){return [];}}
  function open(message,detailsOnly=false){
    const owner=JSON.stringify([state.server,state.username,state.activeId,chatAuthEpoch]);
    const current=()=>owner===JSON.stringify([state.server,state.username,state.activeId,chatAuthEpoch]);
    const dialog=document.createElement('dialog');dialog.className='settings-dialog';
    const form=document.createElement('div');form.className='settings-form';dialog.append(form);
    const title=document.createElement('h2');title.textContent=detailsOnly?'消息信息':'这条有问题';form.append(title);
    const info={server:state.server,account:state.username,bot_id:state.sessionPersonaConfig?.configuredId||state.sessionPersonaConfig?.configured_id||'',session_id:state.activeId,message_id:String(message.serverId||''),client_version:nativeConfig().version||'web',backend_version:window.ChatDevices?.backendVersion()||'服务器未返回',feature:'chat',occurred_at:new Date().toISOString()};
    const preview=document.createElement('textarea');preview.readOnly=true;preview.rows=8;preview.setAttribute('aria-label','报告内容预览');form.append(preview);
    const select=document.createElement('select');select.setAttribute('aria-label','问题类型');for(const t of types){const option=document.createElement('option');option.textContent=t;select.append(option);}
    const note=document.createElement('textarea');note.maxLength=2000;note.placeholder='补充说明（不会自动附带聊天、录音或图片）';note.setAttribute('aria-label','补充说明');
    const data=()=>({...info,type:select.value,note:clean(note.value)});
    function paint(){preview.value=JSON.stringify(detailsOnly?{...info,status:message.delivery,parts:messageParts(message).filter(p=>['action','sticker'].includes(p.type)).map(p=>({type:p.type,name:clean(p.name||p.label),asset_id:p.asset_id,action_id:p.action_id,native_result:p.native_result}))}:data(),null,2);}
    if(!detailsOnly){form.prepend(select,note);select.onchange=note.oninput=paint;}
    const status=document.createElement('p');status.setAttribute('role','status');form.append(status);
    const button=(label,fn)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=fn;form.append(b);};
    if(!detailsOnly)button('保存为待反馈',()=>{if(!current()){dialog.close();return;}try{const rows=saved();rows.push(data());localStorage.setItem(key(),JSON.stringify(rows.slice(-100)));status.textContent='已保存到本机。更多菜单可再次查看并导出。';}catch(_){status.textContent='本机保存未完成，请导出这份报告。';}});
    button('导出当前预览',async()=>{try{await nativeAsync('exportConversation',['Texas-反馈-'+Date.now()+'.md',preview.value],300000);status.textContent='已交给系统保存，请确认目标位置。';}catch(e){status.textContent=errorText(e);}});
    button('关闭',()=>dialog.close());dialog.addEventListener('close',()=>dialog.remove(),{once:true});document.body.append(dialog);paint();dialog.showModal();
  }
  function records(){const dialog=document.createElement('dialog');dialog.className='settings-dialog';const box=document.createElement('textarea');box.rows=18;box.readOnly=true;box.value=JSON.stringify(saved(),null,2);box.setAttribute('aria-label','本机待反馈报告');dialog.append(box);const exportButton=document.createElement('button');exportButton.textContent='导出这些报告';exportButton.onclick=()=>void nativeAsync('exportConversation',['Texas-待反馈-'+Date.now()+'.md',box.value],300000).catch(e=>showNotice(errorText(e)));const close=document.createElement('button');close.textContent='关闭';close.onclick=()=>dialog.close();dialog.append(exportButton,close);dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();}
  document.addEventListener('DOMContentLoaded',()=>{const b=document.createElement('button');b.className='menu-item';b.textContent='待反馈记录';b.onclick=()=>{hideMoreMenu();records();};$('more-menu').append(b);});
  return {open,records};
})();
