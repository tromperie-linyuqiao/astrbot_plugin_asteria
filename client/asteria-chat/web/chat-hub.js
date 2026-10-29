'use strict';
/* Keep each original button and its handlers. This is navigation, not a second
   configuration store: every field still belongs to its original module. */
window.ChatSettingsHub = (() => {
  const sections = [
    ['appearance', '外观与主题', '主题、头像与聊天背景'],
    ['role', '角色与会话', '当前角色、剧情与会话偏好'],
    ['interaction', '动作与互动', '动作类型、身体部位与常用组合'],
    ['expression', '表情素材与偏好', '共享素材、双方偏好与表达方式'],
    ['models', '模型与路由', '本会话模型与继承来源'],
    ['notifications', '通知与安静时段', '消息中心、系统权限与提醒偏好'],
    ['connection', '连接与缓存', '账户、离线记录与手机感知'],
    ['advanced', '资料与高级设置', '日程、重要消息、导出与维护']
  ];
  const keep = new Set(['角色与剧情', '搜索服务器历史', '聊天外观']);
  const map = {
    'menu-theme':'appearance', 'appearance-button':'appearance',
    'rename-button':'role', 'menu-session-preferences':'role',
    'menu-interactions':'interaction', 'menu-model-route':'models',
    'menu-notification-center':'notifications', 'menu-delivery-center':'notifications',
    'menu-connection-center':'connection', 'menu-perception':'connection',
    'mobile-settings':'connection', 'refresh-chat':'connection',
    'menu-export':'advanced', 'menu-delete':'advanced'
  };
  let dialog, menu, home, detail, active = '', queued = false, initialized = false;
  const groups = {};
  const node = (tag, text, cls='') => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; n.className=cls; return n; };
  const button = (text, handler, cls='menu-item') => { const n=node('button',text,cls);n.type='button';n.onclick=handler;return n; };
  function close() { if(dialog?.open)dialog.close(); }
  function closeActive() { if(!dialog?.open)return false; if(active){showHome();return true;}close();return true; }
  function destination(button) {
    if(map[button.id])return map[button.id];
    const label=button.textContent.trim();
    if(/我的头像|聊天外观|主题|深色模式|纯黑/.test(label))return 'appearance';
    if(/模型|路由/.test(label))return 'models';
    if(/通知|送达/.test(label))return 'notifications';
    if(/动作|互动/.test(label))return 'interaction';
    if(/表情|表达偏好/.test(label))return 'expression';
    if(/角色|身体|剧情|会话偏好|会话标题/.test(label))return 'role';
    if(/连接|账户|手机|QQ|权限|感知|同步|缓存/.test(label))return 'connection';
    return 'advanced';
  }
  function organize() {
    queued=false;if(!menu||!dialog)return;
    for(const original of [...menu.children]) {
      if(original.tagName!=='BUTTON'||original.id==='settings-hub-open'||keep.has(original.textContent.trim()))continue;
      groups[destination(original)].append(original);
      if(!original.dataset.hubOwned){original.dataset.hubOwned='true';original.addEventListener('click',close,true);}
    }
    for(const separator of menu.querySelectorAll(':scope > .menu-separator'))separator.remove();
    for(const context of menu.querySelectorAll(':scope > .menu-context'))document.getElementById('hub-role-context').append(context);
    for(const [id] of sections) {
      const count=groups[id].querySelectorAll('button:not([hidden])').length;
      const card=home.querySelector('[data-hub-section="'+id+'"]');if(card)card.querySelector('small').textContent=count+' 个入口';
    }
  }
  function showHome() {
    active='';home.hidden=false;detail.hidden=true;
    document.getElementById('settings-hub-title').textContent='设置';
    document.getElementById('settings-hub-back').hidden=true;
  }
  function openSection(id) {
    if(!initialized)return;
    if(!Object.hasOwn(groups,id)){open();return;}
    hideMoreMenu();organize();active=id;home.hidden=true;detail.hidden=false;
    for(const [key,group]of Object.entries(groups))group.hidden=key!==id;
    document.getElementById('settings-hub-title').textContent=sections.find(row=>row[0]===id)[1];
    document.getElementById('settings-hub-back').hidden=false;
    if(!dialog.open)dialog.showModal();detail.scrollTop=0;
  }
  function open() {
    if(!initialized)return;hideMoreMenu();organize();showHome();if(!dialog.open)dialog.showModal();
  }
  function init() {
    menu=document.getElementById('more-menu');if(!menu)return;
    dialog=node('dialog',undefined,'settings-dialog settings-hub-dialog');dialog.id='settings-hub-dialog';
    const form=node('div',undefined,'settings-form'),heading=node('div',undefined,'dialog-heading');
    const back=button('‹',showHome,'icon-button');back.id='settings-hub-back';back.hidden=true;back.setAttribute('aria-label','返回设置分类');
    const title=node('h2','设置');title.id='settings-hub-title';
    const dismiss=button('×',close,'icon-button');dismiss.id='settings-hub-close';dismiss.setAttribute('aria-label','关闭设置');
    heading.append(back,title,dismiss);form.append(heading);
    home=node('nav',undefined,'hub-section-grid');home.id='settings-hub-home';home.setAttribute('aria-label','设置分类');
    detail=node('div',undefined,'hub-section-detail');detail.id='settings-hub-detail';detail.hidden=true;
    for(const [id,label,description]of sections) {
      const card=button('',()=>openSection(id),'hub-section-card');card.dataset.hubSection=id;
      card.append(node('strong',label),node('span',description),node('small',''));home.append(card);
      const group=node('section',undefined,'hub-buttons');group.id='hub-'+id;group.hidden=true;groups[id]=group;detail.append(group);
    }
    const context=node('div');context.id='hub-role-context';groups.role.append(context);
    groups.appearance.append(button('聊天头像与背景',()=>document.getElementById('appearance-button')?.click()));
    groups.role.append(button('角色与剧情',()=>[...menu.children].find(value=>value.tagName==='BUTTON'&&value.textContent.trim()==='角色与剧情')?.click()));
    const interaction=document.getElementById('menu-interactions');if(interaction)interaction.textContent='动作与常用组合';
    groups.expression.append(button('共享表情与双方偏好',()=>window.ChatComposer?.setPanel('expressions')));
    groups.notifications.append(button('Android 通知权限',()=>window.ChatNotificationStatus?.open?.()),
      button('通知类别与预览',()=>window.ChatNotificationStatus?.openPreferences?.()));
    for(const group of Object.values(groups))group.addEventListener('click',event=>{if(event.target.closest('button'))close();},true);
    form.append(home,detail);dialog.append(form);document.body.append(dialog);
    dialog.addEventListener('cancel',event=>{if(active){event.preventDefault();showHome();}});
    dialog.addEventListener('close',showHome);
    const opener=button('全部设置',open);opener.id='settings-hub-open';menu.append(opener);
    new MutationObserver(()=>{if(!queued){queued=true;queueMicrotask(organize);}}).observe(menu,{childList:true});
    initialized=true;organize();
  }
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return {open,openSection,close,closeActive};
})();
