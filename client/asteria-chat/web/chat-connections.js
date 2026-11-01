'use strict';
/* Saved destinations contain only server/account labels. Authentication remains
   in the original Native KeyStore and the original explicit login flow. */
window.ChatConnections=(()=>{
  const KEY='asteria-chat.recent-connections.v1',MAX=6;
  let section,select,note,remove,activate,observer,savedAccount=null;
  const get=id=>document.getElementById(id);
  function clean(value){
    if(!value||typeof value.server!=='string'||typeof value.username!=='string')return null;
    try{const url=new URL(value.server);if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash||value.username.length>120||!value.username.trim())return null;
      return {server:url.origin+url.pathname.replace(/\/+$/,''),username:value.username.trim()};
    }catch(_){return null;}
  }
  const id=value=>JSON.stringify([value.server,value.username]);
  function rows(){try{const parsed=JSON.parse(localStorage.getItem(KEY)||'[]');if(!Array.isArray(parsed))return [];const seen=new Set();return parsed.map(clean).filter(value=>value&&!seen.has(id(value))&&seen.add(id(value))).slice(0,MAX);}catch(_){return [];}}
  function save(values){try{localStorage.setItem(KEY,JSON.stringify(values.slice(0,MAX)));return true;}catch(_){if(note)note.textContent='本机暂时无法保存连接列表；仍可正常填写地址登录。';return false;}}
  function remember(){
    if(!state.authenticated)return;const value=clean(state);if(!value)return;
    const old=rows();if(old.length&&id(old[0])===id(value)){render();return;}
    save([value,...old.filter(row=>id(row)!==id(value))]);render();
  }
  function render(){
    if(!select)return;const oldValue=select.value;select.replaceChildren();
    const first=document.createElement('option');first.value='';first.textContent='选择以前登录过的服务器与账户';select.append(first);
    for(const row of rows()){const option=document.createElement('option');option.value=id(row);option.textContent=new URL(row.server).host+' · '+row.username;select.append(option);}
    if([...select.options].some(option=>option.value===oldValue))select.value=oldValue;
    section.hidden=rows().length===0;remove.disabled=!select.value;
    refreshSaved();
  }
  function refreshSaved(){
    if(!activate)return;savedAccount=null;const selected=rows().find(row=>id(row)===select.value);
    try{const accounts=window.ChatNotificationStatus?.accounts?.();if(selected&&Array.isArray(accounts))savedAccount=accounts.find(row=>row.server===selected.server&&row.username===selected.username&&row.can_activate)||null;}catch(_){}
    activate.hidden=!savedAccount;activate.disabled=!savedAccount||typeof window.activateReplyAccount!=='function';
  }
  function choose(){
    if(state.sending||state.attaching||get('login-button')?.disabled){note.textContent='请先等待本轮消息或文件处理结束。';select.value='';remove.disabled=true;return;}
    const selected=rows().find(row=>id(row)===select.value);remove.disabled=!selected;refreshSaved();if(!selected)return;
    get('server').value=selected.server;get('username').value=selected.username;get('password').value='';
    note.textContent=savedAccount?'地址与账户已填入，当前聊天和草稿尚未改变。可点击“用已保存登录打开”，或输入密码重新登录。':'地址与账户已填入。输入密码后点“登录并同步”才会切换；当前聊天和草稿尚未改变。';
  }
  function forget(){const selected=select.value;if(!selected)return;save(rows().filter(row=>id(row)!==selected));select.value='';render();note.textContent='已从快捷列表移除。登录状态、草稿与缓存保留。';}
  function refresh(){if(note)note.textContent='快捷列表只保存地址和账户。开启过后台收件的登录由 Android 加密保管，必须明确点击才会切换；其他连接仍需密码登录。';render();}
  function init(){
    const server=get('server'),dialog=get('settings-dialog');if(!server||!dialog)return;
    section=document.createElement('section');section.className='connection-shortcuts';section.id='connection-shortcuts';
    const label=document.createElement('label');label.htmlFor='connection-choice';label.textContent='最近连接';select=document.createElement('select');select.id='connection-choice';select.onchange=choose;
    remove=document.createElement('button');remove.type='button';remove.className='text-button';remove.textContent='移除此快捷连接';remove.id='connection-forget';remove.onclick=forget;
    activate=document.createElement('button');activate.type='button';activate.className='secondary-button connection-saved-open';activate.textContent='用已保存登录打开';activate.id='connection-saved-open';activate.hidden=true;
    activate.onclick=async()=>{refreshSaved();const target=savedAccount;if(!target)return;activate.disabled=true;try{await window.ChatNotificationStatus?.activateAccount?.(target.account_id,note);}finally{refreshSaved();}};
    note=document.createElement('p');note.className='appearance-help';note.id='connection-shortcuts-note';note.setAttribute('role','status');section.append(label,select,activate,remove,note);
    const before=dialog.querySelector('label[for="server"]')||server;before.before(section);
    observer=new MutationObserver(()=>{if(dialog.open)refresh();});observer.observe(dialog,{attributes:true,attributeFilter:['open']});
    remember();refresh();
    window.addEventListener('pagehide',()=>observer.disconnect());window.addEventListener('pageshow',()=>observer.observe(dialog,{attributes:true,attributeFilter:['open']}));
  }
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return {remember,refresh,refreshSaved};
})();
