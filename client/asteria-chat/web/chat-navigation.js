'use strict';
/* Four quiet entry points over the existing pages. No requests or state copy. */
window.ChatNavigation = (() => {
  let nav, buttons = {}, observer;
  function showChat() {
    window.ChatNotificationCenter?.closeActive?.();window.ChatSettingsHub?.close();
    window.ChatModelRoute?.closeActive?.();window.ChatNight?.requestClose?.(document.getElementById('body-state-dialog'));
    hideMoreMenu();sidebar(false);render();
  }
  function render() {
    if(!nav)return;
    const center=document.getElementById('notification-center-dialog');
    const active=center?.open?'notifications':document.getElementById('body-state-dialog')?.open?'role':document.getElementById('settings-hub-dialog')?.open?'settings':'chat';
    for(const [key,button]of Object.entries(buttons)){button.classList.toggle('selected',key===active);button.setAttribute('aria-current',key===active?'page':'false');}
  }
  function init() {
    const header=document.querySelector('.chat-header');if(!header)return;
    nav=document.createElement('nav');nav.id='chat-main-navigation';nav.className='chat-main-navigation';nav.setAttribute('aria-label','主要页面');
    for(const [id,label,open]of [
      ['chat','聊天',showChat],['notifications','通知',()=>window.ChatNotificationCenter?.open?.()],
      ['role','伙伴',()=>window.ChatNight?.openBody?.()],['settings','设置',()=>window.ChatSettingsHub?.open?.()]
    ]) {
      const n=document.createElement('button');n.type='button';n.id='main-nav-'+id;n.dataset.mainPage=id;n.textContent=label;
      n.onclick=()=>{hideMoreMenu();sidebar(false);open();render();};buttons[id]=n;nav.append(n);
    }
    header.after(nav);observer=new MutationObserver(render);
    observer.observe(document.body,{subtree:true,attributes:true,attributeFilter:['open'],childList:true});
    document.addEventListener('visibilitychange',render);render();
    window.addEventListener('pagehide',()=>observer?.disconnect());
    window.addEventListener('pageshow',()=>{observer?.observe(document.body,{subtree:true,attributes:true,attributeFilter:['open'],childList:true});render();});
  }
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return {showChat,scopeChanged:render};
})();
