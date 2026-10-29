'use strict';

/* Incremental UI over the existing bridge. No credentials, new message store,
   background worker, or direct database access. */
window.ChatNight = (() => {
  const $n=id=>document.getElementById(id);
  let alive=true,noticeTimer=0,avatarOwner='',avatarLoaded=false,avatarLoadTask=null,avatarLoadOwner='',avatar=null,avatarSaving=false;
  let avatarPanelOwner='',avatarPanelScope='',avatarPanelEpoch=0,avatarLoading=false,avatarChoosing=false;
  let avatarSource=null,avatarSourceChanged=false,avatarImage=null,avatarImageSerial=0,bodyOwner='',bodyEpoch=0;
  const dialogs=[],openers=new WeakMap(),cleaning=new WeakSet(),canonicalClose=new WeakSet();
  const account=()=>typeof state==='object'&&state.authenticated?JSON.stringify([state.server,state.username]):'';
  const scope=()=>JSON.stringify([account(),state.activeId]);
  const text=(tag,value,style='')=>Object.assign(document.createElement(tag),{textContent:value,className:style});
  const button=(label,fn,style='text-button')=>{const node=text('button',label,style);node.type='button';node.onclick=fn;return node;};
  const fail=error=>showNotice(errorText(error)+' 请重新读取核对结果，应用不会自动重复提交。',null,true);

  function installNotices(){
    const show=showNotice,hide=hideNotice;
    hideNotice=function(){clearTimeout(noticeTimer);noticeTimer=0;return hide.apply(this,arguments);};
    showNotice=function(message,action=null,error=false){
      clearTimeout(noticeTimer);noticeTimer=0;const result=show.apply(this,arguments);
      if(alive&&!error&&!action&&!/未知|待确认|待核对|失败|错误|无法/.test(String(message)))noticeTimer=setTimeout(()=>{if(alive)hideNotice();},Math.min(8000,3800+String(message).length*30));
      return result;
    };
  }
  const closers={
    'appearance-dialog':'appearance-close','settings-dialog':'close-settings','interaction-dialog':'interaction-close',
    'rename-dialog':'rename-close','delete-dialog':'delete-close','export-dialog':'export-close',
    'compose-action-dialog':'compose-action-cancel','expression-pref-dialog':'expression-pref-cancel',
    'compose-text-dialog':'compose-text-cancel','experience-dialog':'experience-close',
    'bookmark-reading-dialog':'bookmark-reading-close','action-batch-dialog':'action-batch-close',
    'user-avatar-dialog':'user-avatar-close','body-state-dialog':'body-state-close'
  };
  function requestClose(dialog){
    if(!dialog||!dialog.open)return false;
    if(dialog.id==='settings-hub-dialog'&&window.ChatSettingsHub?.closeActive)
      return window.ChatSettingsHub.closeActive();
    const closer=$n(closers[dialog.id]);
    if(closer){if(!closer.disabled)closer.click();return true;}
    const close=dialog.querySelector('button[aria-label^="关闭"],button[aria-label^="取消"]');
    if(close){if(!close.disabled)close.click();return true;}
    dialog.close();return true;
  }
  function installDialogs(){
    const proto=HTMLDialogElement.prototype,show=proto.showModal,close=proto.close;
    proto.showModal=function(){
      if(this.open)return;canonicalClose.delete(this);openers.set(this,document.activeElement);show.apply(this,arguments);
      const index=dialogs.indexOf(this);if(index>=0)dialogs.splice(index,1);dialogs.push(this);
    };
    proto.close=function(){
      close.apply(this,arguments);const index=dialogs.indexOf(this);if(index>=0)dialogs.splice(index,1);
    };
    if(typeof cancelAppearance==='function'){const cancel=cancelAppearance;cancelAppearance=function(){const dialog=$n('appearance-dialog');if(dialog)canonicalClose.add(dialog);return cancel.apply(this,arguments);};}
    if(typeof cancelInteractions==='function'){const cancel=cancelInteractions;cancelInteractions=function(){const dialog=$n('interaction-dialog');if(dialog)canonicalClose.add(dialog);return cancel.apply(this,arguments);};}
    document.addEventListener('click',event=>{const closer=event.target.closest('button');const dialog=closer&&closer.closest('dialog');if(dialog&&(/^(?:close-)|-(?:close|cancel)$/.test(closer.id)))canonicalClose.add(dialog);},true);
    document.addEventListener('cancel',event=>{if(event.target instanceof HTMLDialogElement){event.preventDefault();event.stopImmediatePropagation();requestClose(event.target);} },true);
    document.addEventListener('pointerdown',event=>{
      const dialog=dialogs.filter(value=>value.open).at(-1)||[...document.querySelectorAll('dialog[open]')].at(-1);
      if(dialog&&event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)requestClose(dialog);}
      if(!event.target.closest('#more-menu,#more-button'))hideMoreMenu();
    },true);
    document.addEventListener('close',event=>{
      const dialog=event.target;if(!(dialog instanceof HTMLDialogElement)||dialog.open||cleaning.has(dialog))return;
      cleaning.add(dialog);
      try{
        if(!canonicalClose.has(dialog)&&dialog.id==='appearance-dialog'&&typeof cancelAppearance==='function')cancelAppearance();
        if(!canonicalClose.has(dialog)&&dialog.id==='interaction-dialog'&&typeof cancelInteractions==='function')cancelInteractions();
      }finally{cleaning.delete(dialog);canonicalClose.delete(dialog);}
      const opener=openers.get(dialog);openers.delete(dialog);
      if(!document.querySelector('dialog[open]')&&opener&&opener.isConnected&&!opener.disabled)opener.focus({preventScroll:true});
    },true);
    const oldBack=window.AsteriaChatUI&&window.AsteriaChatUI.back;
    if(window.AsteriaChatUI)window.AsteriaChatUI=Object.freeze({...window.AsteriaChatUI,back:()=>{
      const top=dialogs.filter(value=>value.open).at(-1)||[...document.querySelectorAll('dialog[open]')].at(-1);
      return top?requestClose(top):oldBack?oldBack():false;
    }});
  }
  function installTheme(){
    const key=()=>pref(typeof THEME_KEY==='string'?THEME_KEY:'theme');
    const preference=themePreference,effective=effectiveTheme,apply=applyTheme,menu=renderThemeMenu;
    if(typeof setThemePreference==='function'){const set=setThemePreference;setThemePreference=function(mode){if(mode!=='black')return set.apply(this,arguments);storage.set(key(),'black');applyTheme();return 'black';};}
    themePreference=function(){return storage.get(key())==='black'?'black':preference();};
    effectiveTheme=function(){return themePreference()==='black'?'black':effective();};
    renderThemeMenu=function(){menu();if(themePreference()==='black'){$n('menu-theme').textContent='外观：纯黑';$n('menu-theme').dataset.mode='black';$n('menu-theme').setAttribute('aria-label','当前主题：纯黑，点击切换');}};
    applyTheme=function(){const result=apply();const black=effectiveTheme()==='black';document.documentElement.style.colorScheme=black?'dark':'';
      if(black){document.documentElement.dataset.theme='black';const meta=document.querySelector('meta[name="theme-color"]');if(meta)meta.content='#000000';if(window.AsteriaChat&&window.AsteriaChat.setChromeTheme)window.AsteriaChat.setChromeTheme('black');}
      return result;
    };
    document.addEventListener('click',event=>{if(!event.target.closest('#menu-theme'))return;event.preventDefault();event.stopImmediatePropagation();
      const modes=['system','light','dark','black'],next=modes[(modes.indexOf(themePreference())+1)%modes.length];
      storage.set(key(),next==='system'?'':next);applyTheme();renderThemeMenu();
    },true);
    window.addEventListener('storage',event=>{if(event.key===key())applyTheme();});applyTheme();
  }
  function applyUserAvatar(){
    const image=avatar&&avatar.data_url;
    for(const node of document.querySelectorAll('.message-row.user .message-avatar,#account-avatar')){
      node.replaceChildren();if(image){const picture=document.createElement('img');picture.src=image;picture.alt='我的头像';node.append(picture);}else node.textContent='你';
    }
  }
  const avatarTicket=()=>({owner:avatarPanelOwner,scope:avatarPanelScope,epoch:avatarPanelEpoch});
  const avatarCurrent=ticket=>ticket.owner&&ticket.owner===account()&&ticket.owner===avatarPanelOwner
    &&ticket.scope===scope()&&ticket.scope===avatarPanelScope&&ticket.epoch===avatarPanelEpoch&&$n('user-avatar-dialog')?.open;
  function avatarControls(){
    const locked=avatarLoading||avatarChoosing||avatarSaving;
    for(const name of ['choose','save','default','reload','x','y','zoom']){
      const control=$n('user-avatar-'+name);if(control)control.disabled=locked;
    }
  }
  function closeAvatar(){
    avatarPanelEpoch++;avatarImageSerial++;avatarPanelOwner='';avatarPanelScope='';avatarLoading=false;avatarChoosing=false;
    avatarSource=null;avatarSourceChanged=false;avatarImage=null;
    const dialog=$n('user-avatar-dialog');if(dialog?.open)dialog.close();
    if($n('user-avatar-status'))$n('user-avatar-status').textContent='';
    for(const [name,value]of Object.entries({x:.5,y:.5,zoom:1}))if($n('user-avatar-'+name))$n('user-avatar-'+name).value=value;
    if($n('user-avatar-preview'))paintAvatar();avatarControls();
  }
  function closeBody(){
    bodyEpoch++;bodyOwner='';const dialog=$n('body-state-dialog');if(dialog?.open)dialog.close();
    if($n('body-state-values'))$n('body-state-values').replaceChildren();
    if($n('body-state-name'))$n('body-state-name').textContent='伙伴';
    if($n('body-state-status'))$n('body-state-status').textContent='';
  }
  function scopeChanged(){
    if(avatarPanelOwner&&(avatarPanelOwner!==account()||avatarPanelScope!==scope()))closeAvatar();
    if(bodyOwner&&(!account()||bodyOwner!==scope()))closeBody();
  }
  async function readUserAvatar(force=false,ticket=null){
    const owner=account();scopeChanged();
    if(!owner){avatarOwner='';avatarLoaded=false;avatar=null;applyUserAvatar();return null;}
    if(owner!==avatarOwner){avatarOwner=owner;avatarLoaded=false;avatar=null;}
    if(avatarLoadTask&&avatarLoadOwner===owner)return avatarLoadTask;
    if(avatarLoaded&&!force)return avatar;
    const task=(async()=>{try{const value=await apiClient.json('GET','/chat/user-avatar');if(account()!==owner)return null;avatar=value;avatarLoaded=true;applyUserAvatar();return value;}
      catch(error){if(account()===owner){avatarLoaded=true;if(force&&(!ticket||avatarCurrent(ticket)))fail(error);}return null;}})();
    avatarLoadTask=task;avatarLoadOwner=owner;
    try{return await task;}finally{if(avatarLoadTask===task){avatarLoadTask=null;avatarLoadOwner='';}}
  }
  function cropValues(){return Object.fromEntries(['x','y','zoom'].map(name=>[name,Number($n('user-avatar-'+name).value)]));}
  function paintAvatar(){
    const canvas=$n('user-avatar-preview'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,256,256);
    if(!avatarImage){ctx.fillStyle='#777';ctx.font='64px sans-serif';ctx.textAlign='center';ctx.fillText('你',128,155);return;}
    const c=cropValues(),side=Math.min(avatarImage.naturalWidth,avatarImage.naturalHeight)/c.zoom;
    ctx.drawImage(avatarImage,(avatarImage.naturalWidth-side)*c.x,(avatarImage.naturalHeight-side)*c.y,side,side,0,0,256,256);
  }
  async function setAvatarSource(source,ticket){
    const serial=++avatarImageSerial;avatarSource=source;avatarImage=null;
    if(source){const image=new Image();await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=reject;image.src=source;});if(serial!==avatarImageSerial||!avatarCurrent(ticket))return false;avatarImage=image;}
    if(!avatarCurrent(ticket))return false;paintAvatar();return true;
  }
  async function openUserAvatar(){
    if(!account()){openSettings();return;}
    if(avatarSaving){showNotice('头像保存仍在等待结果，请先等待或核对，应用不会重复上传。',null,true);return;}
    hideMoreMenu();avatarPanelOwner=account();avatarPanelScope=scope();avatarPanelEpoch++;
    const ticket=avatarTicket();avatarLoading=true;avatarSourceChanged=false;avatarImageSerial++;avatarImage=null;avatarSource=null;
    paintAvatar();avatarControls();$n('user-avatar-status').textContent='正在读取服务器头像…';$n('user-avatar-dialog').showModal();
    try{
      const value=await readUserAvatar(true,ticket);if(!avatarCurrent(ticket))return;
      if(!value){$n('user-avatar-status').textContent='头像读取未成功，请点重新读取。';return;}
      for(const [name,number]of Object.entries(value.crop||{x:.5,y:.5,zoom:1}))$n('user-avatar-'+name).value=number;
      if(!await setAvatarSource(value.source_data_url,ticket)||!avatarCurrent(ticket))return;
      $n('user-avatar-status').textContent='我的头像保存到当前账户；伙伴头像仍在原聊天外观中分别设置。';
    }catch(error){if(avatarCurrent(ticket))$n('user-avatar-status').textContent=errorText(error);}
    finally{if(avatarCurrent(ticket)){avatarLoading=false;avatarControls();}}
  }
  async function chooseUserAvatar(){
    if(avatarLoading||avatarChoosing||avatarSaving)return;
    const ticket=avatarTicket();if(!avatarCurrent(ticket))return;avatarChoosing=true;avatarControls();
    try{const value=await nativeAsync('chooseAppearanceImage',['background'],300000);
      if(!avatarCurrent(ticket)||value&&value.cancelled)return;
      let image=value;if(!image.data_url&&typeof responseData==='function')image=responseData(value);
      if(image.cancelled)return;if(typeof image.data_url!=='string'||!image.data_url.startsWith('data:image/jpeg;base64,'))throw Error('系统未返回可用头像图片');
      for(const [name,number]of Object.entries({x:.5,y:.5,zoom:1}))$n('user-avatar-'+name).value=number;
      if(!await setAvatarSource(image.data_url,ticket)||!avatarCurrent(ticket))return;
      avatarSourceChanged=true;$n('user-avatar-status').textContent='调整位置与缩放，点保存后上传。';
    }catch(error){if(avatarCurrent(ticket))$n('user-avatar-status').textContent=errorText(error);}
    finally{if(avatarCurrent(ticket)){avatarChoosing=false;avatarControls();}}
  }
  async function saveUserAvatar(reset=false){
    if(avatarSaving||avatarLoading||avatarChoosing)return;
    if(!avatar||avatarPanelOwner!==account()||!state.activeId){$n('user-avatar-status').textContent='请先连接伙伴，再保存当前账户头像。';return;}
    const ticket=avatarTicket();if(!avatarCurrent(ticket))return;
    avatarSaving=true;avatarControls();
    try{const value=await apiClient.json('POST','/chat/user-avatar',{session_id:state.activeId,expected_revision:avatar.revision,crop:cropValues(),reset,...(!reset&&avatarSourceChanged?{source_data_url:avatarSource}:{})});
      if(ticket.owner===account()){avatar=value;avatarLoaded=true;applyUserAvatar();}
      if(!avatarCurrent(ticket))return;closeAvatar();showNotice(reset?'已恢复默认用户头像。':'我的头像已保存并同步到当前账户。');
    }catch(error){if(avatarCurrent(ticket))$n('user-avatar-status').textContent=errorText(error)+' 请重新读取核对，未自动重复上传。';}
    finally{avatarSaving=false;avatarControls();}
  }
  function bodyTime(value){
    if(value==null||value===''||value===0)return {label:'未记录',raw:''};
    const raw=String(value).slice(0,120);
    const date=typeof value==='number'&&Number.isFinite(value)&&value>0?new Date(value<1e12?value*1000:value)
      :typeof value==='string'&&/^\d{4}-\d{2}-\d{2}[T ]/.test(value)?new Date(value):null;
    return {label:date&&Number.isFinite(date.getTime())?date.toLocaleString():'时间格式暂不可用',raw};
  }
  async function readBody(){
    if(!account()||!state.activeId||!$n('body-state-dialog')?.open)return;
    const owner=scope(),epoch=++bodyEpoch;bodyOwner=owner;
    const current=()=>account()&&owner===scope()&&owner===bodyOwner&&epoch===bodyEpoch&&$n('body-state-dialog').open;
    $n('body-state-status').textContent='正在读取TLS身体状态…';
    $n('body-state-values').replaceChildren();
    try{const value=await apiClient.json('GET','/chat/body-state?session_id='+encodeURIComponent(state.activeId));if(!current())return;
      const list=$n('body-state-values');list.replaceChildren();
      $n('body-state-name').textContent=value.name||'伙伴';
      const metric=(label,number,isTime=false)=>{const row=document.createElement('div'),value=isTime?bodyTime(number):null;
        const content=text('strong',value?value.label:number==null?'未提供':String(number));
        if(value)content.title=value.raw?'服务器原始时间：'+value.raw:'未记录';row.append(text('span',label),content);return row;};
      const rp=value.tls_state,modeNames={chat:'日常聊天',roleplay:'角色扮演（RP）',technical:'讨论'};
      if(rp&&['chat','roleplay','technical'].includes(rp.mode)){
        const section=document.createElement('section');section.className='body-state-rp';section.append(text('h3','会话与 RP 状态'));
        section.append(metric('当前模式',modeNames[rp.mode]||rp.mode),metric('剧情简介',rp.scene||'尚未设置'),metric('设置版本',rp.revision));
        if(rp.mode==='roleplay'&&rp.rp_intensity)section.append(metric('互动强度',{inherit:'继承角色设置',light:'轻量',balanced:'适中',immersive:'沉浸'}[rp.rp_intensity]||rp.rp_intensity));
        list.append(section);
      }else list.append(text('p','当前服务器未提供会话与 RP 状态。','appearance-help'));
      const source=value.source==='owned_webchat_virtual_body'?'当前APP会话 · TLS虚拟身体原始记录':value.source||'当前APP会话';
      list.append(text('p','来源：'+source+' · 读取于 '+bodyTime(value.read_at).label,'appearance-help'));
      if(!value.available){$n('body-state-status').textContent=value.reason||'虚拟身体尚未接入';return;}
      for(const [label,key]of [['当前阶段','phase'],['身体唤起','arousal'],['语言唤起','verbal_arousal'],['耐受','tolerance']])list.append(metric(label,value[key]));
      if(value.phase_until)list.append(metric('阶段有效至',value.phase_until,true));
      for(const part of value.parts||[]){const row=document.createElement('details');row.append(text('summary',part.label),metric('基础敏感度',part.sensitivity),metric('敏感增益',part.sensitivity_boost),metric('当前状态值',part.value),metric('最近触碰',part.last_event_at,true));list.append(row);}
      const updated=bodyTime(value.updated_at);$n('body-state-status').title=updated.raw?'服务器原始时间：'+updated.raw:'未记录';
      const until=typeof value.phase_until==='number'?new Date(value.phase_until<1e12?value.phase_until*1000:value.phase_until):new Date(value.phase_until);
      const expired=value.phase_until&&Number.isFinite(until.getTime())&&until.getTime()<=Date.now();
      $n('body-state-status').textContent=value.initialized?'保存的身体状态更新于 '+updated.label+(expired?'；阶段有效时间已过，当前显示原始快照。':'；显示已保存快照，刷新不会推进身体状态。'):'当前APP对话尚无身体状态；完成一次可识别互动后显示。以下敏感度来自原TLS角色配置。';
    }catch(error){if(current())$n('body-state-status').textContent=errorText(error);}
  }
  function openBody(){if(!account()){openSettings();return;}if(!state.activeId){showNotice('先连接当前对话再查看身体状态。');return;}hideMoreMenu();$n('body-state-dialog').showModal();readBody();}
  function decorateRoleAvatars(){
    for(const node of document.querySelectorAll('.message-row.assistant .message-avatar,.header-avatar')){
      node.removeAttribute('aria-hidden');node.setAttribute('role','button');node.tabIndex=0;node.setAttribute('aria-label','查看伙伴身体状态');node.onclick=openBody;
      node.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openBody();}};
    }
    applyUserAvatar();
  }
  function installPanels(){
    const heading=document.querySelector('.chat-heading'),portrait=document.querySelector('.header-avatar');
    if(heading&&portrait){heading.prepend(portrait);heading.classList.add('night-identity');}
    const avatarDialog=document.createElement('dialog');avatarDialog.id='user-avatar-dialog';avatarDialog.className='settings-dialog night-dialog';
    avatarDialog.innerHTML='<div class="settings-form"><div class="dialog-heading"><h2>我的头像</h2><button id="user-avatar-close" type="button" class="icon-button" aria-label="关闭我的头像">×</button></div><canvas id="user-avatar-preview" width="256" height="256"></canvas><button id="user-avatar-choose" type="button" class="secondary-button">从设备选择图片</button><label>左右位置<input id="user-avatar-x" type="range" min="0" max="1" step="0.01" value="0.5"></label><label>上下位置<input id="user-avatar-y" type="range" min="0" max="1" step="0.01" value="0.5"></label><label>缩放<input id="user-avatar-zoom" type="range" min="1" max="3" step="0.05" value="1"></label><p id="user-avatar-status" role="status"></p><div class="appearance-actions"><button id="user-avatar-default" type="button" class="text-button">恢复默认</button><button id="user-avatar-reload" type="button" class="secondary-button">重新读取</button><button id="user-avatar-save" type="button" class="primary-button">保存我的头像</button></div></div>';
    const bodyDialog=document.createElement('dialog');bodyDialog.id='body-state-dialog';bodyDialog.className='settings-dialog night-dialog body-state-dialog';
    bodyDialog.innerHTML='<div class="settings-form"><div class="dialog-heading"><h2 id="body-state-name">伙伴</h2><button id="body-state-close" type="button" class="icon-button" aria-label="关闭身体状态">×</button></div><p class="appearance-help">当前APP对话的真实虚拟身体数据；打开面板不推进状态、不调用模型。</p><p id="body-state-status" role="status"></p><div id="body-state-values"></div><button id="body-state-refresh" type="button" class="secondary-button">刷新身体状态</button></div>';
    document.body.append(avatarDialog,bodyDialog);$n('user-avatar-close').onclick=closeAvatar;$n('body-state-close').onclick=closeBody;$n('body-state-refresh').onclick=readBody;
    avatarDialog.addEventListener('close',()=>{if(avatarPanelOwner)closeAvatar();});
    bodyDialog.addEventListener('close',()=>{if(bodyOwner)closeBody();});
    $n('user-avatar-choose').onclick=chooseUserAvatar;$n('user-avatar-save').onclick=()=>saveUserAvatar();$n('user-avatar-default').onclick=()=>saveUserAvatar(true);$n('user-avatar-reload').onclick=openUserAvatar;
    for(const key of ['x','y','zoom'])$n('user-avatar-'+key).oninput=paintAvatar;
    $n('more-menu').prepend(button('我的头像',openUserAvatar,'menu-item'),button('伙伴身体状态',openBody,'menu-item'));
    const accountAvatar=button('你',openUserAvatar,'account-avatar');accountAvatar.id='account-avatar';accountAvatar.setAttribute('aria-label','我的头像设置');document.querySelector('.sidebar-footer').prepend(accountAvatar);
    const originalRender=renderMessages;renderMessages=function(){const value=originalRender.apply(this,arguments);decorateRoleAvatars();return value;};
    const originalChrome=renderChrome;renderChrome=function(){const value=originalChrome.apply(this,arguments);readUserAvatar();return value;};
    const send=apiClient.send;apiClient.send=async function(){const owner=scope();const result=await send.apply(this,arguments);if(!owner||owner!==scope())return result;if($n('body-state-dialog').open)readBody();
      for(const frame of typeof result==='string'?result.split('\n\n'):[]){const line=frame.split('\n').find(v=>v.startsWith('data: '));if(!line)continue;let event;try{event=JSON.parse(line.slice(6));}catch(_){continue;}if(event.type==='tls_action_result'&&event.data)showNotice(event.data.applied?'互动已由TLS身体系统处理。':'动作已交给角色回应；没有匹配的身体事件。');}
      return result;
    };
    const select=selectSession;selectSession=async function(){if(bodyDialog.open)closeBody();return select.apply(this,arguments);};
    decorateRoleAvatars();readUserAvatar();
  }
  function init(){if(typeof state!=='object'||typeof showNotice!=='function'||typeof apiClient!=='object')return;
    installNotices();installDialogs();installTheme();installPanels();
  }
  window.addEventListener('pagehide',()=>{if(noticeTimer&&typeof hideNotice==='function')hideNotice();alive=false;clearTimeout(noticeTimer);noticeTimer=0;if(typeof hideMoreMenu==='function')hideMoreMenu();});
  window.addEventListener('pageshow',()=>{alive=true;});
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return {openBody,openUserAvatar,readUserAvatar,requestClose,paintAvatar,scopeChanged};
})();
