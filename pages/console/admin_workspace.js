/* Asteria administration: one existing view state, grouped entry points. */
(function () {
  'use strict';
  const group = (title, entries) => ({title, entries});
  const areas = [
    {id:'workbench',name:'系统工作台',home:'overview',summary:'查看当前运行情况、今天的安排与需要处理的事项。',icon:'M3 10 12 3l9 7v10H3z M9 20v-7h6v7',groups:[group('今天',['overview','brief'])]},
    {id:'role',name:'角色与生活',home:'area-role',summary:'从当前角色状态进入生活档案与剧情，让经历、人物和互动各归其位。',icon:'M8 8a4 4 0 1 0 8 0 4 4 0 1 0-8 0 M4 21v-2a8 8 0 0 1 16 0v2',groups:[group('角色与状态',['pc-native','body','mood','space']),group('生活与故事',['autonomous_life','personal_space','pc_daily_native','narrative','preferences'])]},
    {id:'memory',name:'记忆中心',home:'area-memory',summary:'先找到资料类型，再检索、核对来源或修正记录；候选审核与已生效记忆分别管理。',icon:'M5 3h12l3 3v15H5z M9 8h7 M9 12h7 M9 16h4',groups:[group('检索与维护',['memory','personal','timeline','memory-classic']),group('候选与画像',['profile_candidates','memory-native']),group('摘要与历史',['memory_strategy','mc_summary','history'])]},
    {id:'perception',name:'感知中心',home:'area-perception',summary:'查看设备上报、连接时间与已授权来源。进入数据源后维护连接、规则或查询记录。',icon:'M12 10a2 2 0 1 0 0 4 2 2 0 1 0 0-4 M7 7a7 7 0 0 0 0 10 M17 7a7 7 0 0 1 0 10 M3 3a13 13 0 0 0 0 18 M21 3a13 13 0 0 1 0 18',groups:[group('来源与上报',['phone_service','weather']),group('规则与观察',['phone','insight'])]},
    {id:'companion',name:'陪伴与消息',home:'area-companion',summary:'先管理主动交流和表达规则，再查看实际投递结果；启用规则与成功送达是不同状态。',icon:'M3 4h18v13H8l-5 4z M7 8h10 M7 12h7',groups:[group('决策与节奏',['proactive_native','phone_flow']),group('表达与反馈',['expression','rules','policy']),group('实际执行',['tasks'])]},
    {id:'resources',name:'资料中心',home:'area-resources',summary:'图片、音乐、文案与场景使用各自适合的编辑器，共享已有资料与来源记录。',icon:'M3 6h7l2 2h9v12H3z M3 6V3h6l2 3',groups:[group('素材库',['assets','music_library','materials']),group('文字与场景',['data','phone','narrative']),group('维护与整理',['maintenance'])]},
    {id:'automation',name:'任务与自动化',home:'area-automation',summary:'日程、便签、目标与活动分开维护，通过执行记录核对真实结果。',icon:'M5 4h14v18H5z M9 2v4 M15 2v4 M8 10h8 M8 14h8 M8 18h5',groups:[group('时间与提醒',['agenda','dates','special_occasions','memo_notes']),group('目标与活动',['personal_goals','scoped_daily_plan']),group('执行与历史',['tasks','pc_daily_native'])]},
    {id:'models',name:'模型与路由',home:'area-models',summary:'为现有任务选择已配置的模型，查看实际调用与回退信息。凭据继续由 AstrBot 统一管理。',icon:'M12 3v5 M4 16v5 M20 16v5 M4 16V8h16v8 M8 12h8 M12 8v8',groups:[group('选择与调用',['model_routes']),group('预算与查询',['insight','memory_strategy'])]},
    {id:'integrations',name:'插件与集成',home:'area-integrations',summary:'核对每项能力的实际执行者、依赖与运行状态；保留尚需协作的管理入口。',icon:'M8 3v5 M16 3v5 M5 8h14v4a7 7 0 0 1-14 0z M12 19v3',groups:[group('运行与归属',['native_ownership','modules']),group('连接管理',['phone_service']),group('原生业务详情',['memory-native','pc-native'])]},
    {id:'settings',name:'系统设置',home:'area-settings',summary:'管理全局记录、上下文展示和工作台外观，业务资料仍在各自中心维护。',icon:'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',groups:[group('系统与权限',['config','context_display']),group('外观与维护',['workspace_appearance','maintenance'])]}
  ];
  const descriptions = {
    overview:['运行总览','真实运行状态、关注事项与固定快捷入口'],
    brief:['今日简报','集中查看今天的安排、提醒和待处理事项'],
    body:['虚拟身体','查看身体指标、部位与当前互动状态'],
    mood:['心绪','查看当前心绪、变化规则与相关记录'],
    space:['庄园与空间','查看角色所处空间及已有生活环境'],
    personal_space:['私人空间与兴趣','维护有来源的虚构空间、物品、收藏与探索'],
    autonomous_life:['生活档案','检索虚构经历、人物、未完事项和分享记录'],
    pc_daily_native:['角色日常','查看日计划、活动、日记与穿搭资料'],
    narrative:['剧情与偏好','维护虚构场景、剧情线索和互动偏好'],
    preferences:['互动偏好','维护相处方式与明确的互动选择'],
    memory:['当前会话记忆','检索、补充、纠正、软删除或恢复记忆'],
    personal:['长期约定','维护约定、边界和偏好，支持归档与导入导出'],
    timeline:['共同经历','记录有来源的共同经历，查看与修订时间线'],
    profile_candidates:['画像候选审核','核对原话证据，批准或拒绝候选资料'],
    history:['历史档案','按来源与分类审阅保留的历史资料'],
    phone_service:['手机感知','管理 PPB 连接，查看设备与音乐上报'],
    phone:['应用与话语','维护 App 触发规则、提示文案与音乐提示'],
    insight:['数据洞察','查询使用情况、模型用量与原生索引状态'],
    phone_flow:['聊天节奏','设置连续消息、会话偏好与手动免打扰'],
    proactive_native:['主动陪伴','查看会话计划，调整主动交流与发送策略'],
    expression:['回复风格','维护措辞纠正，查看生效范围与撤回反馈'],
    rules:['话语与行为规则','编辑表达与行为规则，保留来源和撤回入口'],
    policy:['表情策略','调整表情选择、使用频率与重复冷却'],
    data:['资料分类目录','按资料类型找到对应的查看、新建与维护入口'],
    assets:['表情图片库','上传图片、填写语义标签与管理启用状态'],
    music_library:['音乐资料库','搜索曲目、编辑标签，导入归档并预览匹配'],
    agenda:['一次性日程','安排带时间的提醒，查看状态或取消待办'],
    dates:['重要日期','维护生日、纪念日与重复日期规则'],
    special_occasions:['节日与课程','维护节日资料、学期课表及对应提醒设置'],
    memo_notes:['便签与待办','记录待办，完成、恢复、归档或导入已有资料'],
    personal_goals:['个人目标','维护角色目标与手动进度，查看自动推进状态'],
    scoped_daily_plan:['目标日计划','维护明确归属的计划与有来源的活动记录'],
    native_ownership:['原生接管状态','查看实际执行者、依赖、阻塞与恢复信息'],
    modules:['能力与模块','查看已登记功能、当前运行状态和管理入口'],
    model_routes:['任务模型路由','当前任务选择、备用模型、实际调用与用量'],
    memory_strategy:['记忆分流与摘要策略','临时记忆时效、低价值过滤与摘要去重'],
    context_display:['上下文与展示权限','统一上下文、资料显示开关及范围继承'],
    workspace_appearance:['工作台外观','主题、快捷入口和首页布局'],
    'memory-native':['完整记忆与画像','TLS 原生 MC 资料、画像、关系及摘要管理'],
    'memory-classic':['记忆记录维护','独立页面中的补充、纠正、删除与恢复'],
    'pc-native':['完整角色与陪伴','TLS 原生 PC 的角色资料、日常和策略'],
    weather:['存在层总览','查看已有空间、身体与天气来源'],
    materials:['材质工坊','维护虚拟身体使用的触觉材质与对应属性'],
    config:['全局记录设置','私聊原话记录与已有配置读取'],
    mc_summary:['摘要管线状态','实际摘要算法、来源及管线运行状态'],
    tasks:['提醒与投递记录','查看调度、待处理、失败与实际执行结果'],
    maintenance:['资料维护','来源核对、批量维护与资料体检']
  };
  const aliases = {'domain-interaction':'area-companion','domain-memory':'area-memory','domain-perception':'area-perception','domain-role':'area-role','domain-actions':'area-automation','domain-system':'area-integrations'};
  const owners = {personal_space:'role',overview:'workbench',brief:'workbench',autonomous_life:'role',pc_daily_native:'role',narrative:'role',preferences:'role',memory:'memory',personal:'memory',timeline:'memory',profile_candidates:'memory',mc_summary:'memory',memory_strategy:'memory',history:'memory',phone_service:'perception',phone:'perception',insight:'perception',phone_flow:'companion',proactive_native:'companion',expression:'companion',rules:'companion',policy:'companion',data:'resources',assets:'resources',music_library:'resources',maintenance:'resources',agenda:'automation',dates:'automation',special_occasions:'automation',memo_notes:'automation',personal_goals:'automation',scoped_daily_plan:'automation',tasks:'automation',model_routes:'models',native_ownership:'integrations',modules:'integrations',config:'settings',context_display:'settings',workspace_appearance:'settings'};
  const info = id => descriptions[id] || ENTRY_INFO[id] || [TITLES[id] || id,''];
  const svg = path => {const s=document.createElementNS('http://www.w3.org/2000/svg','svg');s.setAttribute('viewBox','0 0 24 24');s.setAttribute('class','nav-icon');s.setAttribute('aria-hidden','true');const p=document.createElementNS(s.namespaceURI,'path');p.setAttribute('d',path);s.append(p);return s;};
  const button = (label, callback, className='') => {const b=node('button',label,className);b.type='button';b.addEventListener('click',callback);return b;};
  function start() {
    Object.assign(ENTRY_INFO,descriptions);
    Object.assign(ENTRY_PAGES,{'memory-classic':'memory'});
    MODULE_ENTRY.context='context_display';
    Object.assign(VIEW_SECTIONS,owners);
    Object.assign(TITLES,{model_routes:'任务模型路由',memory_strategy:'记忆分流与摘要策略',context_display:'上下文与展示权限',workspace_appearance:'工作台外观',profile_candidates:'画像候选审核'});
    const views=document.querySelector('.views'),navigation=$('main-navigation');
    // These existing views were nested in the overview; hiding its ancestor hid them too.
    for(const id of ['view-mc_summary','view-profile_candidates']){const view=$(id);if(view&&view.parentElement!==views)views.append(view);}
    const living=$('view-overview').querySelector(':scope > .panel'),shortcuts=$('workbench-shortcuts');
    if(living&&shortcuts&&living.querySelector('[data-view="timeline"]')){
      living.classList.remove('panel');living.classList.add('aw-living-shortcuts');
      const title=living.querySelector('h2');if(title)title.replaceWith(node('h3',title.textContent));
      shortcuts.before(living);
    }
    navigation.replaceChildren();navigation.classList.add('aw-main-nav');
    document.querySelectorAll('.secondary-nav').forEach(n=>n.remove());
    for (const area of areas) {
      SECTION_NAMES[area.id]=area.name;SECTION_DEFAULTS[area.id]=area.home;
      const nav=button('',()=>setView(area.home),'aw-nav-item');nav.dataset.section=area.id;nav.append(svg(area.icon),node('span',area.name));navigation.append(nav);
      if(area.home!=='overview') {
        TITLES[area.home]=area.name;VIEW_SECTIONS[area.home]=area.id;
        const section=node('section',undefined,'view aw-domain-view');section.id='view-'+area.home;section.hidden=true;
        const head=node('div',undefined,'aw-domain-header');head.append(node('p',area.summary,'aw-domain-description'));
        const scope=node('p','','aw-domain-scope hint');head.append(scope);section.append(head);
        const groups=node('div',undefined,'aw-domain-groups');
        for(const group of area.groups) {
          const part=node('section',undefined,'aw-domain-group');part.append(node('h3',group.title));const grid=node('div',undefined,'aw-domain-grid');
          for(const id of group.entries) {
            const [title,description]=info(id),card=button('',()=>openEntry(id),'aw-domain-card');card.dataset.awEntry=id;
            card.append(node('span',title,'aw-card-title'),node('span',description,'aw-card-description'),node('span',ENTRY_PAGES[id]?'打开完整管理页 ↗':'进入管理 →','aw-card-meta'));grid.append(card);
          }
          part.append(grid);groups.append(part);
        }
        section.append(groups);views.append(section);
      }
      const sub=node('nav',undefined,'secondary-nav aw-view-nav');sub.dataset.subsection=area.id;sub.setAttribute('aria-label',area.name+'页面');sub.hidden=true;
      const home=button(area.id==='workbench'?'运行总览':'分区概览',()=>setView(area.home));home.dataset.view=area.home;sub.append(home);
      for(const id of new Set(area.groups.flatMap(g=>g.entries))) {
        if(ENTRY_PAGES[id]||id===area.home||owners[id]!==area.id)continue;
        const b=button(info(id)[0],()=>setView(id));b.dataset.view=id;sub.append(b);
      }
      views.before(sub);
    }
    const brand=document.querySelector('.brand');brand.replaceChildren();const mark=node('span',undefined,'brand-mark');mark.append(svg('M12 2l2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5z'));brand.append(mark,node('span','星栖 Asteria'),node('small','TLS · ADMINISTRATION'));
    document.querySelector('.eyebrow').textContent='ASTERIA / ADMINISTRATION';
    document.querySelector('.sidebar-note').textContent='在同一个工作台，照看每一份连接。';
    const top=node('div',undefined,'aw-toolbar'),crumb=node('nav',undefined,'aw-breadcrumb');crumb.id='aw-breadcrumb';crumb.setAttribute('aria-label','当前位置');
    const search=node('div',undefined,'aw-search-wrap'),field=node('input');field.id='aw-search';field.type='search';field.placeholder='查找功能、设置与资料入口';field.setAttribute('aria-label','查找管理功能');field.autocomplete='off';
    const results=node('div',undefined,'aw-search-results');results.id='aw-search-results';results.hidden=true;results.setAttribute('aria-label','功能搜索结果');search.append(field,results);top.append(crumb,search);document.querySelector('.header').after(top);
    const searchable=Array.from(new Set(areas.flatMap(a=>a.groups.flatMap(g=>g.entries))));
    function closeSearch(){results.hidden=true;field.setAttribute('aria-expanded','false');}
    function searchFeatures(){
      results.replaceChildren();const query=field.value.trim().toLocaleLowerCase();if(!query){closeSearch();return;}
      const matches=searchable.filter(id=>info(id).join(' ').toLocaleLowerCase().includes(query));
      for(const id of matches){const [title,description]=info(id),b=button('',()=>{closeSearch();field.value='';openEntry(id);},'aw-search-result');b.append(node('strong',title),node('small',description));results.append(b);}
      if(!matches.length)results.append(node('p','没有匹配的功能，试试“记忆”“手机”或“日程”。','empty'));
      results.hidden=false;field.setAttribute('aria-expanded','true');
    }
    field.setAttribute('aria-controls',results.id);field.setAttribute('aria-expanded','false');field.addEventListener('input',searchFeatures);field.addEventListener('focus',()=>{if(field.value)searchFeatures();});
    field.addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();results.querySelector('button')?.focus();}if(event.key==='Enter'){const first=results.querySelector('button');if(first){event.preventDefault();first.click();}}if(event.key==='Escape')closeSearch();});
    results.addEventListener('keydown',event=>{const buttons=Array.from(results.querySelectorAll('button')),index=buttons.indexOf(document.activeElement);if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();buttons[(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();}if(event.key==='Escape'){closeSearch();field.focus();}});
    document.addEventListener('click',event=>{if(!search.contains(event.target))closeSearch();});
    document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();field.focus();}});

    const relatedAreas={
      personal_space:['autonomous_life','music_library','assets','personal_goals'],autonomous_life:['personal_space','pc_daily_native','proactive_native','tasks'],
      music_library:['personal_space','phone_service','phone','insight'],assets:['personal_space','policy','expression'],
      phone_service:['phone','phone_flow','music_library','proactive_native'],phone:['phone_service','phone_flow','expression'],
      proactive_native:['phone_flow','tasks','autonomous_life','special_occasions'],tasks:['proactive_native','agenda','memo_notes'],
      memory:['profile_candidates','mc_summary','personal','history'],profile_candidates:['memory','memory_strategy','history'],
      model_routes:['insight','memory_strategy','autonomous_life'],special_occasions:['agenda','dates','proactive_native'],
      personal_goals:['scoped_daily_plan','memo_notes','autonomous_life'],scoped_daily_plan:['personal_goals','tasks']
    };
    const cooperate=node('details',undefined,'aw-cooperate'),cooperateTitle=node('summary','关联区域'),cooperateList=node('div',undefined,'aw-cooperate-links');
    cooperate.append(cooperateTitle,cooperateList);top.after(cooperate);
    const recentKey='asteria.admin.recent-views.v1';
    let recentViews=[];try{const saved=JSON.parse(localStorage.getItem(recentKey)||'[]');if(Array.isArray(saved))recentViews=saved.filter(id=>typeof id==='string'&&descriptions[id]&&!ENTRY_PAGES[id]).slice(0,5);}catch(_){}
    const recentBox=node('details',undefined,'aw-recent'),recentTitle=node('summary','最近打开'),recentList=node('div');recentBox.append(recentTitle,recentList);navigation.after(recentBox);
    function paintRelations(view,remember=false){
      if(remember&&descriptions[view]&&!ENTRY_PAGES[view]&&view!=='overview'){recentViews=[view,...recentViews.filter(id=>id!==view)].slice(0,5);try{localStorage.setItem(recentKey,JSON.stringify(recentViews));}catch(_){}}
      cooperateList.replaceChildren();for(const id of relatedAreas[view]||[])cooperateList.append(button(info(id)[0],()=>openEntry(id),'aw-related-link'));
      cooperate.hidden=!cooperateList.children.length;
      recentList.replaceChildren();for(const id of recentViews)recentList.append(button(info(id)[0],()=>setView(id),'aw-recent-link'));recentBox.hidden=!recentViews.length;
    }

    function paint(view) {
      const area=areas.find(a=>a.id===VIEW_SECTIONS[view])||areas[0];
      crumb.replaceChildren(button(area.name,()=>setView(area.home)));
      if(view!==area.home)crumb.append(node('span','/','aw-crumb-separator'),node('span',info(view)[0],'aw-crumb-current'));
      $('page-title').textContent=view===area.home?area.name:info(view)[0];
      document.querySelectorAll('.aw-domain-scope').forEach(n=>n.textContent=state.scope?'资料操作将使用上方选定的用户、角色和会话。':'可浏览功能入口；管理会话资料前，请在上方选择会话。');
      $('current-scope-bar').hidden=['history','model_routes','config','memory_strategy','workspace_appearance','area-models','area-integrations','area-settings','native_ownership','modules'].includes(view);
      document.body.dataset.awArea=area.id;document.body.dataset.awView=view;paintRelations(view);
    }
    // Material ownership remains the stored five-field scope. The administrator
    // can discover a cold library without assigning its data to the open Chat.
    const libraries={assets:{path:'page/assets/admin-scopes',noun:'图片',unit:'张',inactive:'deleted',inactiveLabel:'已删除'},music_library:{path:'page/music-library/scopes',noun:'音乐',unit:'首',inactive:'archived',inactiveLabel:'已归档'},special_occasions:{noun:'课程与节日',unit:'份设置',explicitOnly:true},memo_notes:{noun:'便签（含归档）',unit:'条',explicitOnly:true}};
    const sourceViews=new Map();
    const sameLibraryScope=(a,b)=>!!a&&!!b&&FIELDS.every(key=>a[key]===b[key]);
    const sourceName=scope=>/webchat/i.test(scope.platform)?'Chat 资料库':/qq|aiocq|onebot/i.test(scope.platform)?'QQ 资料库':scope.platform+' 资料库';
    const scopeSelect=$('scope-select');
    let catalogReady=!!state.scope||scopeSelect.options[0]?.textContent!=='正在读取会话…',catalogSelection=state.scope&&{...state.scope},catalogObserver=null;
    function hasLibraryDraft(view){
      const phase=$('music_library-mount')?.dataset.musicPhase;
      return !!state.editor||!!state.assetsBusy||!!state.assetsUploadDraft||!!$('assets-file')?.files?.length||
        !!$('assets-caption')?.value.trim()||!!$('assets-tags')?.value.trim()||!!$('assets-enabled')?.checked||
        (view==='music_library'&&(['new','edit','saving','uncertain','conflict'].includes(phase)||!!$('view-music_library').querySelector('[data-music-file]')?.files?.length));
    }
    function mergeLibraryCatalog(){
      if(!catalogReady)return;
      catalogObserver?.disconnect();
      try{
        for(const entry of sourceViews.values())for(const row of entry.sources||[]){
          if(state.scopes.some(item=>sameLibraryScope(item,row.scope)))continue;
          const index=state.scopes.length;state.scopes.push({...row.scope});
          if(index===0)scopeSelect.replaceChildren();
          const option=node('option',row.scope.user_id+' / '+row.scope.character_id+' / '+row.scope.session_id);option.value=String(index);scopeSelect.append(option);
        }
        scopeSelect.disabled=!state.scopes.length;
        if(catalogSelection&&state.scopes.some(item=>sameLibraryScope(item,catalogSelection))&&!sameLibraryScope(state.scope,catalogSelection))chooseScope(catalogSelection);
        const index=state.scopes.findIndex(item=>sameLibraryScope(item,state.scope));if(index>=0)scopeSelect.value=String(index);
      }finally{catalogObserver?.observe(scopeSelect,{childList:true});}
    }
    function selectLibrarySource(scope,automatic=false){
      if(!automatic)for(const entry of sourceViews.values())entry.defaultPending=false;
      let index=state.scopes.findIndex(item=>sameLibraryScope(item,scope));
      if(index<0){index=state.scopes.length;state.scopes.push({...scope});const option=node('option',scope.user_id+' / '+scope.character_id+' / '+scope.session_id);option.value=String(index);$('scope-select').append(option);}
      chooseScope(scope);
      if(sameLibraryScope(state.scope,scope)){catalogSelection={...state.scope};$('scope-select').value=String(index);}
    }
    function defaultLibrarySource(view){
      const entry=sourceViews.get(view);if(!catalogReady||!entry?.sources||!entry.defaultPending||state.view!==view)return;
      entry.defaultPending=false;
      if(hasLibraryDraft(view))return;
      const populated=entry.sources.filter(row=>row.total>0),current=entry.sources.find(row=>sameLibraryScope(row.scope,state.scope));
      if(!(current?.total)&&populated.length===1)selectLibrarySource(populated[0].scope,true);
    }
    function drawLibrarySources(view){
      const entry=sourceViews.get(view),def=libraries[view];if(!entry?.sources)return;
      entry.list.replaceChildren();
      const current=entry.sources.find(row=>sameLibraryScope(row.scope,state.scope));
      const total=entry.sources.reduce((sum,row)=>sum+row.total,0);
      entry.status.textContent=(entry.partial?'已确认来源中保存 ':'已保存 ')+total+' '+def.unit+' · 当前来源 '+(current?.total||0)+' '+def.unit+'。选择来源后查看和维护原记录。'+(entry.partial?' 另有 '+entry.failedCount+' 个来源未确认，请刷新后核对。':'');
      if(!entry.sources.length)entry.list.append(node('p',entry.partial?'尚无已确认的资料来源，仍有来源未读取成功，请刷新后核对。':'尚未找到已保存的'+def.noun+'资料。','empty'));
      for(const row of entry.sources){
        const selected=sameLibraryScope(row.scope,state.scope),b=button(sourceName(row.scope)+' · '+row.total+' '+def.unit,()=>selectLibrarySource(row.scope),selected?'current':'');
        b.setAttribute('aria-pressed',String(selected));b.title='用户 '+row.scope.user_id+' / 角色 '+row.scope.character_id+' / 会话 '+row.scope.session_id;
        entry.list.append(b);if(row.details)entry.list.append(node('span',row.details,'hint'));if(row[def.inactive])entry.list.append(node('span',row[def.inactive]+' '+def.unit+def.inactiveLabel,'hint'));
      }
    }
    async function readScopedLibrarySources(view){
      const sources=[],failures=[];
      await Promise.all(state.scopes.map(async scope=>{try{
        const query=Object.fromEntries(FIELDS.map(key=>[key,scope[key]]));
        if(view==='memo_notes'){
          const result=await api('GET','page/memo-notes/list',{...query,status:'all',include_archived:true,limit:1,offset:0});
          if(!sameLibraryScope(result.scope,scope)||!Number.isSafeInteger(result.total)||result.total<0)throw Error('便签范围或数量未确认');
          if(result.total)sources.push({scope:{...scope},total:result.total,details:'含归档；切换来源不会恢复便签，使用原列表的全部状态及归档入口查看。'});
          return;
        }
        const result=await api('GET','page/special-occasions/settings',query),values=result.settings?.values;
        if(!sameLibraryScope(result.scope,scope)||!values)throw Error('资料范围或内容未确认');
        const courses=values.course_timetable?.courses?.length||0,birthday=values.birthday_profile,hasBirthday=Number.isInteger(birthday?.month)&&birthday.month>=1&&birthday.month<=12&&Number.isInteger(birthday?.day)&&birthday.day>=1&&birthday.day<=31;
        const holidays=values.holiday_messages?.enabled===true&&Array.isArray(values.holiday_messages.holidays)?values.holiday_messages.holidays.length:0;
        if(courses||hasBirthday||holidays)sources.push({scope:{...scope},total:1,details:[courses?courses+' 门课程':'',hasBirthday?'已保存生日':'',holidays?holidays+' 项节日设置':''].filter(Boolean).join(' · ')});
      }catch{failures.push(scope);}}));
      return {sources,partial:failures.length>0,failedCount:failures.length};
    }
    function paintDataLibrarySources(){
      if(state.view!=='data')return;
      for(const view of ['assets','music_library']){
        const entry=sourceViews.get(view),def=libraries[view],card=$('data-categories').querySelector('[data-data-type="'+view+'"]');if(!card)continue;
        card.querySelector('[data-library-source-summary]')?.remove();
        const box=node('div',undefined,'aw-library-source-summary');box.dataset.librarySourceSummary=view;
        if(!entry?.sources){box.append(node('p',entry?.error?'资料来源尚未确认，请进入资料库刷新来源。':'正在读取其他已保存来源…','hint'));}
        else{
          const total=entry.sources.reduce((sum,row)=>sum+row.total,0),loaded=state.dataResults.get(view),rows=loaded?.result?.records;
          box.append(node('p','已读取来源合计 '+total+' '+def.unit+'；'+(Array.isArray(rows)?'当前范围本次读取 '+rows.length+' 条。':'当前范围的读取结果尚未确认。')+(entry.error?' 来源为上次读取，请刷新核对。':''),'hint'));
          const actions=node('div',undefined,'actions');
          for(const row of entry.sources.filter(row=>row.total>0))actions.append(button('查看'+sourceName(row.scope)+' · '+row.total+' '+def.unit,()=>{selectLibrarySource(row.scope);openEntry(view);}));
          box.append(actions);
        }
        card.append(box);
      }
    }
    async function loadLibrarySources(view){
      const def=libraries[view];if(!def)return;let entry=sourceViews.get(view);
      if(!entry){
        const panel=node('section',undefined,'panel aw-library-sources'),header=node('div',undefined,'panel-head');header.append(node('h2','资料来源'));
        const refresh=button('刷新来源',()=>loadLibrarySources(view));header.append(refresh);
        const status=node('p','正在查找已保存的资料来源…','hint'),list=node('div',undefined,'actions');list.setAttribute('aria-label',def.noun+'资料来源');
        panel.append(header,status,list,node('p','这里切换的是管理员查看范围。资料保留在原来源，不会复制或改写聊天身份。','hint'));
        $('view-'+view).prepend(panel);entry={panel,status,list,refresh,request:0,defaultPending:!def.explicitOnly};sourceViews.set(view,entry);
      }
      if(def.explicitOnly&&!catalogReady){entry.status.textContent='正在读取可管理的资料范围…';return;}
      const request=++entry.request;entry.refresh.disabled=true;entry.loading=true;
      try{
        const result=def.explicitOnly?await readScopedLibrarySources(view):await api('GET',def.path,{limit:100});if(request!==entry.request)return;
        if(!Array.isArray(result.sources)||result.sources.some(row=>!row.scope||FIELDS.some(key=>typeof row.scope[key]!=='string'||!row.scope[key])||!Number.isSafeInteger(row.total)||row.total<0))throw Error('资料来源响应不完整，请刷新核对。');
        entry.sources=result.sources;entry.error=false;entry.partial=result.partial===true;entry.failedCount=result.failedCount||0;
        mergeLibraryCatalog();defaultLibrarySource(view);
        drawLibrarySources(view);
      }catch(error){if(request===entry.request){entry.error=true;entry.status.textContent='资料来源暂时无法读取。当前列表仍按上方选定范围查询，请刷新来源重试。';}}
      finally{if(request===entry.request){entry.loading=false;entry.refresh.disabled=false;paintDataLibrarySources();}}
    }
    let restoring=false;
    const original=setView;
    setView=function(requested){
      const view=aliases[requested]||requested;if(!TITLES[view])return;
      original(view);paintRelations(view,true);
      if(view==='context_display')ensureContextSettings();
      paint(view);
      loadLibrarySources(view);
      if(view==='data')for(const id of ['assets','music_library'])loadLibrarySources(id);
      if(!restoring&&location.hash!=='#'+view)history.pushState(null,'','#'+view);
      window.dispatchEvent(new CustomEvent('tls-admin-viewchange',{detail:{view}}));
    };
    const originalChoose=chooseScope;
    chooseScope=function(scope){const value=originalChoose(scope);if(catalogReady)catalogSelection=state.scope&&{...state.scope};paint(state.view);if(libraries[state.view]){defaultLibrarySource(state.view);drawLibrarySources(state.view);}return value;};
    // The original startup request can already be in flight when this script
    // starts. Observe its option replacement, including a genuinely empty
    // memory catalog, before selecting a stored material source.
    catalogObserver=new MutationObserver(()=>{catalogReady=true;mergeLibraryCatalog();defaultLibrarySource(state.view);if(libraries[state.view])drawLibrarySources(state.view);const entry=sourceViews.get(state.view);if(libraries[state.view]?.explicitOnly&&entry&&!entry.sources&&!entry.loading)loadLibrarySources(state.view);});
    catalogObserver.observe(scopeSelect,{childList:true});
    scopeSelect.addEventListener('change',()=>{for(const entry of sourceViews.values())entry.defaultPending=false;},true);
    const originalLoadScopes=loadScopes;
    loadScopes=async function(){
      if(libraries[state.view]&&hasLibraryDraft(state.view)){notify('当前资料草稿或请求仍保留，请先保存、取消或核查后再刷新来源。',true);return;}
      catalogSelection=state.scope&&{...state.scope};catalogReady=false;
      try{return await originalLoadScopes();}finally{catalogReady=true;mergeLibraryCatalog();defaultLibrarySource(state.view);if(libraries[state.view])drawLibrarySources(state.view);}
    };
    $('refresh-scopes').removeEventListener('click',originalLoadScopes);
    $('refresh-scopes').addEventListener('click',()=>loadScopes());
    const originalDrawDataCenter=drawDataCenter;
    drawDataCenter=function(){const value=originalDrawDataCenter();paintDataLibrarySources();return value;};
    window.addEventListener('pagehide',()=>catalogObserver?.disconnect(),{once:true});
    window.addEventListener('popstate',()=>{const view=aliases[location.hash.slice(1)]||location.hash.slice(1)||'overview';if(TITLES[view]){restoring=true;setView(view);restoring=false;}});
    window.addEventListener('hashchange',()=>{const view=aliases[location.hash.slice(1)]||location.hash.slice(1);if(TITLES[view]&&state.view!==view){restoring=true;setView(view);restoring=false;}});
    $('aw-appearance-edit')?.addEventListener('click',openLayoutEditor);
    $('refresh').addEventListener('click',()=>{if(['model_routes','memory_strategy'].includes(state.view))setView(state.view);});
    const target=aliases[location.hash.slice(1)]||location.hash.slice(1)||state.view;
    restoring=true;setView(TITLES[target]?target:'overview');restoring=false;
    if(location.hash!=='#'+state.view)history.replaceState(null,'','#'+state.view);
    window.TLSAdminWorkspace=Object.freeze({areas:areas.map(a=>({id:a.id,name:a.name,home:a.home,entries:Array.from(new Set(a.groups.flatMap(g=>g.entries)))})),navigate:view=>setView(view),refresh:()=>paint(state.view)});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
