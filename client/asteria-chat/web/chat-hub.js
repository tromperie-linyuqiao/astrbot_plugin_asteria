'use strict';
/* Keep each original button and its handlers. This is navigation, not a second
   configuration store: every field still belongs to its original module. */
window.ChatSettingsHub = (() => {
  const sections = [
    ['appearance', '外观与主题', '主题、头像与聊天背景'],
    ['role', '角色与会话', '当前角色、剧情与会话偏好'],
    ['life', '数字生活与档案', '空间、收藏、兴趣与生活经历'],
    ['interaction', '动作与互动', '动作类型、身体部位与常用组合'],
    ['voice', '声音与语音', '云端试听、朗读与语音输入'],
    ['agenda', '日程与重要日期', '课程、提醒、生日与纪念日'],
    ['perception', '手机感知与桌宠', '桌宠、手机状态与上报权限'],
    ['expression', '表情素材与偏好', '共享素材、双方偏好与表达方式'],
    ['models', '模型与路由', '本会话模型与继承来源'],
    ['notifications', '通知与安静时段', '消息中心、系统权限与提醒偏好'],
    ['connection', '连接与缓存', 'Bot 服务器、账户与离线记录'],
    ['advanced', '资料与维护', '重要消息、导出与高级选项']
  ];
  const keep = new Set(['角色与剧情', '搜索服务器历史', '聊天外观']);
  const map = {
    'menu-theme':'appearance', 'appearance-button':'appearance',
    'rename-button':'role', 'menu-session-preferences':'role', 'menu-life':'life', 'menu-personal-space':'life',
    'menu-voice':'voice', 'menu-interactions':'interaction', 'menu-model-route':'models',
    'menu-notification-center':'notifications', 'menu-delivery-center':'notifications',
    'menu-connection-center':'connection', 'menu-perception':'perception', 'menu-mobile-pet':'perception',
    'mobile-settings':'connection', 'refresh-chat':'connection',
    'menu-export':'advanced', 'menu-delete':'advanced'
  };
  let dialog, menu, home, detail, maintenance, search, results, searchStatus, active = '', queued = false, initialized = false;
  const normalize=value=>String(value||'').normalize('NFKC').toLocaleLowerCase().trim();
  const groups = {};
  const node = (tag, text, cls='') => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; n.className=cls; return n; };
  const button = (text, handler, cls='menu-item') => { const n=node('button',text,cls);n.type='button';n.onclick=handler;return n; };
  function close() { if(dialog?.open)dialog.close(); }
  function closeActive() { if(!dialog?.open)return false; if(active){showHome();return true;}close();return true; }
  function destination(button) {
    if(map[button.id])return map[button.id];
    const label=button.textContent.trim();
    if(/我的头像|聊天外观|主题|深色模式|纯黑/.test(label))return 'appearance';
    if(/语音|声音|朗读|电话/.test(label))return 'voice';
    if(/日程|课程|重要日期|生日|纪念日/.test(label))return 'agenda';
    if(/手机感知|感知上报|PPB/.test(label))return 'perception';
    if(/模型|路由/.test(label))return 'models';
    if(/通知|送达/.test(label))return 'notifications';
    if(/动作|互动/.test(label))return 'interaction';
    if(/表情|表达偏好|语料与偏好/.test(label))return 'expression';
    if(/生活档案|私人空间|兴趣|生活画卷/.test(label))return 'life';
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
      const card=home.querySelector('[data-hub-section="'+id+'"]');if(card)card.querySelector('small').textContent='›';
    }
  }
  function showHome() {
    if(search)search.value='';if(results)results.replaceChildren();if(searchStatus)searchStatus.textContent='';
    active='';home.hidden=false;detail.hidden=true;refreshBots();
    document.getElementById('settings-hub-title').textContent='设置';
    document.getElementById('settings-hub-back').hidden=true;
  }
  function refreshBots(){if(!home)return;for(const b of home.querySelectorAll('[data-hub-bot]')){const value=window.ChatConnections?.destinations?.().find(x=>x.name===b.dataset.hubBot);if(value)b.querySelector('small').textContent=value.current?'当前聊天':value.saved?'已保存登录':'已添加 · 待登录';}}
  function openSection(id) {
    if(!initialized)return;
    if(!Object.hasOwn(groups,id)){open();return;}
    hideMoreMenu();organize();search.value='';results.replaceChildren();searchStatus.textContent='';active=id;home.hidden=true;detail.hidden=false;
    for(const [key,group]of Object.entries(groups))group.hidden=key!==id;
    document.getElementById('settings-hub-title').textContent=sections.find(row=>row[0]===id)[1];
    document.getElementById('settings-hub-back').hidden=false;
    if(!dialog.open)dialog.showModal();detail.scrollTop=0;
  }
  function open() {
    if(!initialized)return;
    hideMoreMenu();organize();showHome();
    if(!dialog.open){maintenance.open=false;dialog.showModal();}
  }

  function aliases(title){
    const terms=[];
    for(const [pattern,words] of [[/外观|主题/,'黑色 黑底 浅色 深色 壁纸'],[/头像|背景/,'图片 裁剪 壁纸'],[/日程|重要日期|日历/,'生日 纪念日 课程 提醒'],[/动作|互动/,'摸头 戳 拥抱 牵手 自己 身体'],[/表情/,'贴纸 喜欢 隐藏 标签 收藏'],[/通知|送达/,'推送 消息 提醒 弹窗 未读'],[/连接|账户/,'服务器 Bot 登录 密码'],[/缓存/,'离线 删除缓存'],[/手机|感知/,'PPB 音乐'],[/语音|声音/,'试听 朗读 TTS ASR 云端'],[/导出/,'文件 备份'],[/生活|兴趣|私人空间/,'收藏 档案 画卷 空间 物品 探索 经历']])if(pattern.test(title))terms.push(words);
    return terms.join(' ');
  }
  function findSettings() {
    const query=normalize(search.value).slice(0,160),words=query.split(/\s+/).filter(Boolean);
    results.replaceChildren();if(!words.length){showHome();return;}
    active='search';home.hidden=true;detail.hidden=true;
    document.getElementById('settings-hub-title').textContent='查找设置';
    document.getElementById('settings-hub-back').hidden=false;
    let count=0;
    for(const [id,label,description]of sections){
      const candidates=[...groups[id].querySelectorAll('button')];
      for(const original of menu.children)if(original.tagName==='BUTTON'&&keep.has(original.textContent.trim())&&destination(original)===id)candidates.push(original);
      const seen=new Set();
      for(const original of candidates){
        const title=original.textContent.trim();if(original.hidden||!title||seen.has(title))continue;seen.add(title);
        const terms=normalize(title+' '+label+' '+aliases(title));
        if(!words.every(word=>terms.includes(word)))continue;
        const result=button('',()=>{close();original.click();},'hub-search-result');
        result.disabled=original.disabled;result.append(node('strong',title),node('small',label));results.append(result);count++;
      }
    }
    searchStatus.textContent=count?'找到 '+count+' 个入口':'没有找到，试试“生日”“图片”“模型”或“通知”。';
  }
  function init() {
    menu=document.getElementById('more-menu');if(!menu)return;
    dialog=node('dialog',undefined,'settings-dialog settings-hub-dialog');dialog.id='settings-hub-dialog';
    const form=node('div',undefined,'settings-form'),heading=node('div',undefined,'dialog-heading');
    const back=button('‹',showHome,'icon-button');back.id='settings-hub-back';back.hidden=true;back.setAttribute('aria-label','返回设置分类');
    const title=node('h2','设置');title.id='settings-hub-title';
    const dismiss=button('×',close,'icon-button');dismiss.id='settings-hub-close';dismiss.setAttribute('aria-label','关闭设置');
    heading.append(back,title,dismiss);form.append(heading);
    const searchBar=node('div',undefined,'hub-search-bar');search=node('input');search.type='search';search.id='settings-hub-search';search.maxLength=160;search.placeholder='查找功能，如生日、模型、头像';search.setAttribute('aria-label','查找设置与功能');search.autocomplete='off';search.addEventListener('input',findSettings);
    const clear=button('清除',()=>{showHome();search.focus();},'text-button');clear.id='settings-hub-clear';searchBar.append(search,clear);
    searchStatus=node('p','', 'hub-search-status');searchStatus.id='settings-hub-search-status';searchStatus.setAttribute('role','status');
    results=node('div',undefined,'hub-search-results');results.id='settings-hub-results';form.append(searchBar,searchStatus,results);
    home=node('nav',undefined,'hub-section-grid hub-organized');home.id='settings-hub-home';home.setAttribute('aria-label','设置分类');
    detail=node('div',undefined,'hub-section-detail');detail.id='settings-hub-detail';detail.hidden=true;
    const bots=node('section',undefined,'hub-bots');bots.setAttribute('aria-label','我的 Bot');bots.append(node('h3','我的 Bot'));
    for(const name of ['伙伴','苦艾']){const b=button('',()=>{close();window.ChatConnections?.openBot?.(name);},'hub-bot');b.dataset.hubBot=name;b.append(node('strong',name),node('small','已添加 · 待登录'));bots.append(b);}home.append(bots);
    const categories=[['聊天与表达',['appearance','voice','interaction','expression']],['角色与生活',['role','life','agenda']],['手机与通知',['notifications','perception']],['连接与管理',['connection','models','advanced']]];
    const categoryBoxes={};for(const [name,ids]of categories){const box=node('section',undefined,'hub-category');box.append(node('h3',name));for(const id of ids)categoryBoxes[id]=box;home.append(box);}
    for(const [id,label,description]of sections) {
      const card=button('',()=>openSection(id),'hub-section-card');card.dataset.hubSection=id;
      card.append(node('strong',label),node('span',description),node('small','›'));categoryBoxes[id].append(card);
      const group=node('section',undefined,'hub-buttons');group.id='hub-'+id;group.hidden=true;groups[id]=group;detail.append(group);
    }
    maintenance=node('details',undefined,'hub-maintenance');maintenance.id='settings-hub-maintenance';
    maintenance.append(node('summary','模型、导出与维护'));
    for(const id of ['models','advanced'])maintenance.append(categoryBoxes[id].querySelector('[data-hub-section="'+id+'"]'));
    categoryBoxes.connection.append(maintenance);
    const context=node('div');context.id='hub-role-context';groups.role.append(context);
    // The original appearance button is moved below; keep a single entry.
    groups.role.append(button('角色与剧情',()=>[...menu.children].find(value=>value.tagName==='BUTTON'&&value.textContent.trim()==='角色与剧情')?.click()));
    const interaction=document.getElementById('menu-interactions');if(interaction)interaction.textContent='动作与常用组合';
    groups.expression.append(button('共享表情与双方偏好',()=>window.ChatComposer?.setPanel('expressions')));
    groups.notifications.append(button('通知设置与系统权限',()=>window.ChatNotificationStatus?.openPreferences?.()),
      button('各 Bot 收件开关',()=>openSettings('bots')));
    groups.connection.append(button('我的 Bot 与最近消息',()=>openSettings('bots')),button('图片与离线缓存',()=>openSettings('cache')));
    groups.appearance.append(button('界面主题',()=>openSettings('appearance')));
    groups.role.append(button('服务器角色选择',()=>openSettings('role')));
    groups.advanced.append(button('本机资料与版本',()=>openSettings('advanced')));
    for(const group of Object.values(groups))group.addEventListener('click',event=>{if(event.target.closest('button'))close();},true);
    form.append(home,detail);dialog.append(form);document.body.append(dialog);
    dialog.addEventListener('cancel',event=>{if(active){event.preventDefault();showHome();}});
    dialog.addEventListener('close',showHome);
    const opener=button('全部设置',open);opener.id='settings-hub-open';menu.append(opener);
    new MutationObserver(()=>{if(!queued){queued=true;queueMicrotask(organize);}}).observe(menu,{childList:true});
    document.addEventListener('keydown',event=>{
      if((event.ctrlKey||event.metaKey)&&!event.altKey&&event.key.toLowerCase()==='k'){
        const opened=document.querySelector('dialog[open]');if(opened&&opened!==dialog)return;
        event.preventDefault();open();search.focus();
      }
    });
    initialized=true;organize();
  }
  document.addEventListener('DOMContentLoaded',init,{once:true});
  return {open,openSection,close,closeActive};
})();


/* One existing form, one authoritative copy of every control. The pane only
   changes which group is visible; original listeners and native bridges stay. */
window.ChatSettingsPages = (() => {
  const names={connection:'连接服务器',bots:'我的 Bot 与收件',notifications:'通知设置',cache:'图片与离线缓存',appearance:'界面主题',role:'服务器角色',advanced:'本机资料与版本'};
  const copy={connection:'首次连接时登录。正常打开对话后，登录由 Android 加密保管，之后无需每次输入密码。',bots:'各 Bot 独立收件，点击卡片即可恢复聊天。这里显示已读取的真实消息，不代表所有消息都已读。',notifications:'分类、预览与安静时段在这里设置；每个 Bot 的收件开关在“我的 Bot”。',cache:'已看过的表情和图片优先读取本机副本。清理缓存保留草稿、服务器记录与角色记忆。',appearance:'仅改变本机界面，立即生效。',role:'使用此服务器已配置的角色，不改变其他服务器。',advanced:'导出当前已加载的记录，或查看客户端版本。'};
  const panes={};let active='connection',form,dialog,intro,back;
  const get=id=>document.getElementById(id);
  function category(node){
    if(node.id==='reply-accounts')return 'bots';
    if(node.matches('.notify-settings,#notification-preferences'))return 'notifications';
    if(node.id==='chat-cache-settings')return 'cache';
    if(node.matches('.theme-settings,#appearance-settings-button'))return 'appearance';
    if(node.id==='persona-settings')return 'role';
    if(node.matches('#export-open,.about-app'))return 'advanced';
    return 'connection';
  }
  function organize(){
    if(!form)return;
    const accounts=get('reply-accounts');if(accounts&&accounts.parentElement!==panes.bots)panes.bots.append(accounts);
    for(const item of [...form.children]){
      if(item.matches('.dialog-heading,.settings-pane,.settings-page-intro'))continue;
      // The old general introduction is replaced by a page-specific explanation.
      if(item.matches('.settings-intro')){item.hidden=true;panes.connection.append(item);continue;}
      panes[category(item)].append(item);
    }
  }
  function show(page){
    active=Object.hasOwn(names,page)?page:'connection';if(!form)return;
    organize();for(const [id,pane]of Object.entries(panes))pane.hidden=id!==active;
    dialog.dataset.settingsPage=active;get('settings-title').textContent=names[active];intro.textContent=copy[active];
    const eyebrow=dialog.querySelector('.eyebrow');if(eyebrow)eyebrow.textContent='设置';
    // All controls remain in the same form. Hidden login constraints must not
    // interfere with Enter on a notification or cache page.
    for(const id of ['server','username','password'])get(id).required=active==='connection';
    form.scrollTop=0;window.ChatNotificationStatus?.refresh();
    if(active==='cache')window.ChatCacheSettings?.refresh();
    if(active==='notifications')window.ChatNotificationPreferences?.refresh();
  }
  function init(){
    form=get('settings-form');dialog=get('settings-dialog');if(!form||!dialog)return;
    const heading=form.querySelector('.dialog-heading');back=document.createElement('button');back.type='button';back.className='icon-button';back.id='settings-page-back';back.textContent='‹';back.setAttribute('aria-label','返回设置分类');
    back.onclick=()=>{dialog.close();window.ChatSettingsHub?.open();};heading.prepend(back);
    intro=document.createElement('p');intro.className='settings-page-intro';heading.after(intro);
    for(const [id,label]of Object.entries(names)){const pane=document.createElement('section');pane.className='settings-pane';pane.id='settings-pane-'+id;pane.setAttribute('aria-label',label);panes[id]=pane;form.append(pane);}
    if(typeof window.AsteriaChat?.startReplyWatchAccount==='function'){
      const legacy=form.querySelector('.notify-settings');
      for(const child of [...legacy.children])if(!['notification-diagnostics','reply-accounts'].includes(child.id))child.hidden=true;
      const link=document.createElement('button');link.type='button';link.className='secondary-button';link.textContent='管理各 Bot 收件';link.onclick=()=>show('bots');panes.notifications.prepend(link);
    }
    organize();show(active);
    // Supports modules registering a new control later without duplicating it.
    new MutationObserver(organize).observe(form,{childList:true});
    form.addEventListener('submit',event=>{if(active!=='connection'){event.preventDefault();event.stopImmediatePropagation();}},true);
  }
  document.addEventListener('DOMContentLoaded',()=>queueMicrotask(init),{once:true});
  return Object.freeze({show,current:()=>active});
})();
