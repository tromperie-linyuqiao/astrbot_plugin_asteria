'use strict';
/* Move the original buttons, retaining their handlers and authoritative state. */
window.ChatSettingsHub=(()=>{
  const keep=new Set(['角色与剧情','搜索服务器历史','聊天外观']);
  let dialog,menu,groups,queued=false;
  function close(){if(dialog?.open)dialog.close();}
  function destination(button){
    const text=button.textContent.trim();
    if(/连接|账户|手机|QQ|权限|感知/.test(text))return groups.connection;
    if(/日程|消息|记录|导出|收藏/.test(text))return groups.materials;
    return groups.expression;
  }
  function organize(){
    queued=false;
    for(const button of [...menu.children]){
      if(button.tagName!=='BUTTON'||button.id==='settings-hub-open'||keep.has(button.textContent.trim())||button.id==='rename-button')continue;
      destination(button).append(button);
      button.addEventListener('click',close,true);
    }
    for(const node of menu.querySelectorAll(':scope > .menu-separator'))node.remove();
    for(const node of menu.querySelectorAll(':scope > .menu-context'))document.getElementById('hub-role-context').append(node);
    for(const section of dialog.querySelectorAll('[data-hub-group]'))section.hidden=!section.querySelector('button:not([hidden])');
  }
  function init(){
    menu=document.getElementById('more-menu');if(!menu)return;
    dialog=document.createElement('dialog');dialog.id='settings-hub-dialog';dialog.className='settings-dialog settings-hub-dialog';
    dialog.innerHTML='<div class="settings-form"><div class="dialog-heading"><h2>聊天设置</h2><button id="settings-hub-close" class="icon-button" type="button" aria-label="关闭设置">×</button></div><p class="appearance-help">原有功能按用途收在这里，聊天内容和配置不会因入口移动而改变。</p><section data-hub-group><h3>角色与表达</h3><div id="hub-expression" class="hub-buttons"></div></section><section data-hub-group><h3>资料与日程</h3><div id="hub-materials" class="hub-buttons"></div></section><section data-hub-group><h3>连接与设备</h3><div id="hub-connection" class="hub-buttons"></div></section></div>';
    document.body.append(dialog);groups={expression:document.getElementById('hub-expression'),materials:document.getElementById('hub-materials'),connection:document.getElementById('hub-connection')};
    const role=document.createElement('div');role.id='hub-role-context';dialog.querySelector('.settings-form').append(role);
    document.getElementById('settings-hub-close').onclick=close;
    const open=document.createElement('button');open.id='settings-hub-open';open.className='menu-item';open.type='button';open.textContent='全部设置';
    open.onclick=()=>{hideMoreMenu();organize();if(!dialog.open)dialog.showModal();};menu.append(open);
    new MutationObserver(()=>{if(!queued){queued=true;queueMicrotask(organize);}}).observe(menu,{childList:true});
    organize();
  }
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return{close};
})();
