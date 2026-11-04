'use strict';
/* Saved destinations contain only server/account labels. Authentication remains
   in the original Native KeyStore and the original explicit login flow. */
window.ChatConnections=(()=>{
  const KEY='texas-chat.recent-connections.v1',MAX=6;
  let section,select,note,remove,activate,observer,savedAccount=null;
  const get=id=>document.getElementById(id);

  const PRESETS=[]; // Public builds have no preselected private servers.
  let presets;
  function usePreset(value,account=null){
    if(state.sending||state.attaching||get('login-button')?.disabled){note.textContent='请先等待本轮消息或文件处理结束。';return;}
    const saved=account?clean({server:value.server,username:account.username}):rows().find(row=>row.server===value.server);
    if(saved){get('server').value=saved.server;get('username').value=saved.username;get('password').value='';select.value=id(saved);remove.disabled=!select.value;refreshSaved();}
    else{get('server').value=value.server;get('username').value='';get('password').value='';select.value='';remove.disabled=true;refreshSaved();}
    note.textContent='已填入'+value.name+'的地址。'+(saved?'可使用已保存登录，或重新输入该服务器密码。':'请填写该服务器原有账号和密码。')+'登录后选择“'+value.name+'”；当前聊天、草稿和其他 Bot 收件保持不变。';
    get(saved?'password':'username')?.focus({preventScroll:true});
  }
  function destinations(){
    let accounts=[];try{accounts=window.ChatNotificationStatus?.accounts?.()||[];}catch(_){}
    return PRESETS.map(value=>({...value,current:state.authenticated&&state.server===value.server,saved:accounts.some(row=>row.server===value.server&&row.can_activate)}));
  }
  async function openBot(name){
    const value=PRESETS.find(row=>row.name===name);if(!value)return;
    if(state.authenticated&&state.server===value.server){window.ChatNavigation?.showChat?.();return;}
    let saved;try{saved=window.ChatNotificationStatus?.accounts?.()?.filter(row=>row.server===value.server&&row.can_activate);}catch(_){}
    if(saved?.length===1){const ok=await window.ChatNotificationStatus.activateAccount(saved[0].account_id);if(ok){window.ChatNavigation?.showChat?.();return;}}
    if(saved?.length>1){openContacts();return;}
    openSettings();usePreset(value);
  }

  // Project the original encrypted Android logins; no copied tokens, watch
  // startup, additional server polling or conversation merging.
  let contacts,contactList,contactNote,contactBusy=false;
  const el=(tag,text,className='')=>{const n=document.createElement(tag);n.textContent=text;n.className=className;return n;};
  const current=row=>state.authenticated&&state.server===row.server&&state.username===row.username;
  function closeContacts(){if(!contacts?.open)return false;contacts.close();return true;}
  function refreshContacts(){
    if(!contacts?.open)return;
    const focus=document.activeElement?.dataset.contactKey;
    contactList.replaceChildren();let saved=null;
    try{saved=window.ChatNotificationStatus?.accounts?.()??null;}catch(_){}
    for(const preset of PRESETS){
      const group=el('section','','contact-group');group.setAttribute('aria-label',preset.name);
      let entries=(saved||[]).filter(row=>row.server===preset.server);
      if(state.authenticated&&state.server===preset.server&&!entries.some(current))entries=[{server:preset.server,username:state.username},...entries];
      if(!entries.length)entries=[{server:preset.server,username:'',placeholder:true}];
      for(const row of entries){
        const button=el('button','','contact-card');button.type='button';button.disabled=contactBusy;
        button.dataset.contactKey=JSON.stringify([preset.server,row.username,row.account_id||'']);
        button.dataset.contactBot=preset.name;if(row.account_id)button.dataset.contactAccount=row.account_id;
        const isCurrent=current(row),ready=row.can_activate===true;
        button.dataset.current=String(isCurrent);
        const avatar=el('span',preset.name.slice(0,1),'contact-avatar');avatar.setAttribute('aria-hidden','true');
        const body=el('span','','contact-body'),heading=el('span','','contact-heading');
        heading.append(el('strong',preset.name),el('span',isCurrent?'当前聊天':ready?'已保存登录':row.placeholder?'首次登录':'需重新登录','contact-state'));
        body.append(heading,el('span',row.username||'使用这个 Bot 原有的账号登录','contact-account'));
        body.append(el('span',row.last_message_preview?'最近收到 · '+row.last_message_preview:isCurrent?'点击回到聊天':ready?'点击继续聊天，保留原会话和草稿':'登录后即可从这里打开聊天','contact-preview'));
        button.append(avatar,body,el('span',isCurrent||ready?'聊天 →':'登录 →','contact-open'));
        button.onclick=()=>openContact(preset,row);group.append(button);
      }
      contactList.append(group);
    }
    if(saved===null)contactList.append(el('p','暂时无法读取已保存的登录。当前聊天可继续，其他联系人可从连接设置登录。','contacts-help'));
    if(focus)Array.from(contactList.querySelectorAll('[data-contact-key]')).find(n=>n.dataset.contactKey===focus)?.focus({preventScroll:true});
  }
  async function openContact(preset,row){
    if(contactBusy)return;
    if(state.sending||state.attaching||state.creating||state.appearanceBusy||get('login-button')?.disabled){contactNote.textContent='请先等待当前消息或文件处理结束，再切换联系人。';return;}
    if(current(row)){closeContacts();window.ChatNavigation?.showChat?.();return;}
    if(!row.can_activate){closeContacts();openSettings('connection');usePreset(preset,row.username?row:null);return;}
    contactBusy=true;contactNote.textContent='正在打开'+preset.name+'…';refreshContacts();
    try{
      const ok=await window.ChatNotificationStatus?.activateAccount?.(row.account_id,contactNote);
      if(ok){closeContacts();window.ChatNavigation?.showChat?.();}
    }finally{contactBusy=false;refreshContacts();}
  }
  function openContacts(){
    if(!contacts)return;
    if(contacts.open){refreshContacts();return;}
    window.ChatNavigation?.showChat?.();contactNote.textContent='';contacts.showModal();refreshContacts();
  }
  function initContacts(){
    contacts=el('dialog','','settings-dialog contacts-dialog');contacts.id='contacts-dialog';contacts.setAttribute('aria-labelledby','contacts-title');
    const box=el('div','','settings-form'),header=el('div','','dialog-heading');
    const title=el('h2','联系人');title.id='contacts-title';const close=el('button','×','icon-button');close.type='button';close.setAttribute('aria-label','关闭联系人');close.onclick=closeContacts;header.append(title,close);
    contactList=el('div','','contact-list');contactList.id='contact-list';
    contactNote=el('p','','contacts-note');contactNote.id='contacts-note';contactNote.setAttribute('role','status');
    const help=el('p','分别登录一次，之后点联系人即可继续聊天。登录过期时需重新登录。','contacts-help');
    const manage=el('button','管理登录与后台收件','secondary-button contacts-manage');manage.type='button';manage.onclick=()=>{closeContacts();openSettings('bots');};
    box.append(header,help,contactList,contactNote,manage);contacts.append(box);document.body.append(contacts);
    contacts.addEventListener('click',event=>{if(event.target===contacts)closeContacts();});
  }
  function paintPresets(){
    if(!presets)return;
    for(const b of presets.querySelectorAll('[data-server-preset]')){
      const value=PRESETS[Number(b.dataset.serverPreset)],same=state.authenticated&&state.server===value.server;
      b.setAttribute('aria-pressed',String(same));b.querySelector('small').textContent=same?'当前连接':rows().some(row=>row.server===value.server)?'曾经登录 · 点击准备切换':'已添加 · 待登录';
    }
  }

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
    if(!select)return;paintPresets();const oldValue=select.value;select.replaceChildren();
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
  function refresh(){if(note)note.textContent='快捷列表只保存地址和账户。正常打开过对话的登录由 Android 加密保管，点击即可切换；首次连接和登录过期时才需密码。';render();}
  function init(){
    const server=get('server'),dialog=get('settings-dialog');if(!server||!dialog)return;
    section=document.createElement('section');section.className='connection-shortcuts';section.id='connection-shortcuts';
    const label=document.createElement('label');label.htmlFor='connection-choice';label.textContent='最近连接';select=document.createElement('select');select.id='connection-choice';select.onchange=choose;
    remove=document.createElement('button');remove.type='button';remove.className='text-button';remove.textContent='移除此快捷连接';remove.id='connection-forget';remove.onclick=forget;
    activate=document.createElement('button');activate.type='button';activate.className='secondary-button connection-saved-open';activate.textContent='用已保存登录打开';activate.id='connection-saved-open';activate.hidden=true;
    activate.onclick=async()=>{refreshSaved();const target=savedAccount;if(!target)return;activate.disabled=true;try{await window.ChatNotificationStatus?.activateAccount?.(target.account_id,note);}finally{refreshSaved();}};
    note=document.createElement('p');note.className='appearance-help';note.id='connection-shortcuts-note';note.setAttribute('role','status');section.append(label,select,activate,remove,note);
    const before=dialog.querySelector('label[for="server"]')||server;before.before(section);
    presets=document.createElement('section');presets.className='connection-presets';presets.id='connection-presets';presets.setAttribute('aria-label','Bot 服务器连接');
    const title=document.createElement('h3');title.textContent='选择要连接的 Bot';const grid=document.createElement('div');grid.className='connection-preset-grid';
    PRESETS.forEach((value,index)=>{const b=document.createElement('button');b.type='button';b.className='connection-preset';b.dataset.serverPreset=String(index);const name=document.createElement('strong'),description=document.createElement('span'),host=document.createElement('span'),status=document.createElement('small');name.textContent=value.name;description.textContent=value.description;host.textContent=new URL(value.server).host;host.className='connection-preset-host';b.append(name,description,host,status);b.onclick=()=>usePreset(value);grid.append(b);});
    const help=document.createElement('p');help.className='appearance-help';help.textContent='请先填写你有权使用的服务器地址并登录。此公版不预设私人服务器；已保存账户保留在本机。';presets.append(title,grid,help,note);section.before(presets);
    observer=new MutationObserver(()=>{if(dialog.open)refresh();});observer.observe(dialog,{attributes:true,attributeFilter:['open']});
    initContacts();remember();refresh();
    window.addEventListener('pagehide',()=>observer.disconnect());window.addEventListener('pageshow',()=>observer.observe(dialog,{attributes:true,attributeFilter:['open']}));
  }
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return {remember,refresh,refreshSaved,destinations,openBot,openContacts,closeContacts,refreshContacts};
})();
