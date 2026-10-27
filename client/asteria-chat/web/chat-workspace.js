'use strict';

/* Existing TLS agenda and explicit permissions through one authenticated bridge. */
window.ChatWorkspace = (() => {
  let owner='',epoch=0,serial=0,busy=0,snapshot=null,calendar=null,edit=null,mode='create',requestId='',formTimezone='',editorOwner='',proactiveSerial=0;
  const pendingWrites=new Map(),REPEATS={none:'不重复',daily:'每天',weekly:'每周',monthly:'每月',yearly:'每年'};
  const DESTINATIONS={qq:'保留QQ',chat_text:'纯文本改发Chat',chat_all:'文字、图片与语音均发Chat'};
  const $id=id=>document.getElementById(id),scope=()=>JSON.stringify([state.server,state.username,state.activeId]);
  const current=op=>op.epoch===epoch&&op.owner===owner&&owner===scope()&&$id('workspace-dialog')?.open;
  const make=(tag,value,cls='')=>{const n=document.createElement(tag);if(value!==undefined)n.textContent=value;n.className=cls;return n;};
  const button=(label,fn)=>{const n=make('button',label,'text-button');n.type='button';n.onclick=fn;return n;};
  const say=text=>$id('workspace-status').textContent=text;
  const route=(name,id)=>'/chat/'+name+'?session_id='+encodeURIComponent(id);
  const readTime=value=>{if(value===null||value===undefined||value==='')return '未提供';const d=new Date(typeof value==='number'?value*1000:value);return Number.isFinite(d.getTime())?d.toLocaleString():'未提供';};
  function renderProactive(data){
    const box=$id('workspace-proactive-body');box.replaceChildren();
    const labels={waiting_for_real_scope:'等待真实聊天登记',waiting_for_real_app_message:'等待一条真实APP消息登记范围',waiting_for_authorized_app_source:'尚无已授权APP执行来源',confirmed_app_binding_required:'APP与QQ身份尚未确认绑定',chat_destination_not_selected:'主动消息发送位置尚未选择Chat',native_proactive_unavailable:'原生主动来源当前不可用',blocked:'当前暂不具备执行条件',ready:'当前条件可继续评估',active:'当前启用',disabled:'当前关闭',unavailable:'来源暂不可用',quiet_hours:'当前处于免打扰时段',recent_chat:'近期正在聊天',not_chat_destination:'主动消息当前未选择Chat',unlinked:'QQ身份尚未确认绑定'};
    const line=(name,value)=>{const row=make('p');row.append(make('span',name+'：'),make('strong',value,'workspace-state-value'));box.append(row);};
    line('配置开关',data.enabled===true?'开启':data.enabled===false?'关闭':'服务器未提供');
    line('实际状态',labels[data.state]||data.state||'待确认');
    line('执行来源',data.active===true?'当前接纳':data.active===false?'当前未接纳':'尚未确认');
    line('发送位置',DESTINATIONS[data.destination]||data.destination||'尚未提供');
    line('免打扰窗口',data.quiet_hours?(data.quiet_hours+'（安静时段）'):'未提供');
    if(data.timezone)line('规则时区',data.timezone);
    line('下次评估',data.next_evaluation_at?readTime(data.next_evaluation_at):'尚无已排定评估');
    line('读取时间',readTime(data.checked_at));
    const admission=data.admission,reason=admission?.reason||data.reason;
    if(reason)box.append(make('p','当前原因：'+(labels[reason]||reason),'workspace-state-reason'));
    if(admission)box.append(make('p','当前只读门槛：'+(admission.allowed===true?'允许继续评估':admission.allowed===false?'暂不允许':'未确认')+'；这次读取不领取或发送消息。','appearance-help'));
    const last=data.latest_admission;if(last?.reason)box.append(make('p','最近一次接纳记录：'+(labels[last.reason]||last.reason)+' · '+readTime(last.checked_at)+'；属于历史记录，不证明本次实际触发。','appearance-help'));
  }
  async function readProactive(){
    if(!owner||!$id('workspace-dialog')?.open)return;
    const op={owner,epoch,id:++proactiveSerial,sessionId:state.activeId};
    $id('workspace-proactive-refresh').disabled=true;$id('workspace-proactive-body').replaceChildren(make('p','正在读取服务器主动状态…'));
    try{const data=await apiClient.json('GET',route('proactive-state',op.sessionId));if(current(op)&&op.id===proactiveSerial)renderProactive(data);}
    catch(e){if(current(op)&&op.id===proactiveSerial)$id('workspace-proactive-body').replaceChildren(make('p',e.status===404?'当前服务器未提供主动状态；已有权限与日程仍可使用。':errorText(e),'workspace-state-reason'));}
    finally{if(current(op)&&op.id===proactiveSerial)$id('workspace-proactive-refresh').disabled=false;}
  }
  const localDate=value=>{const d=new Date(value);return Number.isFinite(d.getTime())?new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16):'';};
  function deviceTimezone(){
    try{
      const zone=Intl.DateTimeFormat().resolvedOptions().timeZone;
      if(typeof zone==='string'&&zone){
        const fixed=/^(?:UTC)?([+-])(\d{2}):(\d{2})$/.exec(zone);
        if(fixed){
          const hours=Number(fixed[2]),minutes=Number(fixed[3]);
          if(hours<=14&&minutes<=59&&(hours<14||minutes===0))return 'UTC'+fixed[1]+fixed[2]+':'+fixed[3];
        }else if(!/^(?:UTC)?[+-]/.test(zone))return zone;
      }
    }catch{}
    const offset=-new Date().getTimezoneOffset(),absolute=Math.abs(offset);
    if(!Number.isInteger(offset)||absolute>14*60)return 'UTC';
    return 'UTC'+(offset<0?'-':'+')+String(Math.floor(absolute/60)).padStart(2,'0')+':'+String(absolute%60).padStart(2,'0');
  }
  const supports=key=>snapshot&&(Array.isArray(snapshot.supported_settings)?snapshot.supported_settings:
    ['shared_memory','linked_calendar','proactive_destination']).includes(key)
    &&(key!=='linked_activity'||typeof snapshot.settings.values.linked_activity==='boolean');
  const linked=()=>snapshot?.identity?.linked===true;
  const locked=()=>busy!==0||pendingWrites.has(owner);
  const unsafe=row=>['unknown','quarantined','claimed','sending'].includes(row.task_state)||row.status==='unknown';
  function controls(){
    const blocked=locked(),pending=pendingWrites.get(owner),writable=calendar?.writable===true;
    $id('workspace-save').disabled=blocked||!snapshot;
    $id('workspace-refresh').disabled=busy!==0;
    $id('permission-memory').disabled=blocked||!supports('shared_memory');
    $id('permission-calendar').disabled=blocked||!supports('linked_calendar')||!linked();
    $id('permission-activity').disabled=blocked||!supports('linked_activity')||!linked();
    if($id('permission-perception'))$id('permission-perception').disabled=blocked||!supports('linked_perception')||!linked();
    $id('workspace-destination').disabled=blocked||!supports('proactive_destination')||!linked();
    for(const id of ['calendar-text','calendar-time','calendar-save'])$id(id).disabled=blocked||!writable;
    $id('calendar-repeat').disabled=blocked||!writable||calendar?.capabilities?.periodic!==true;
    $id('calendar-new').disabled=busy!==0||pending?.phase==='inflight';
    $id('workspace-clear-pending').hidden=pending?.phase!=='unknown';
    $id('workspace-clear-pending').disabled=busy!==0||pending?.readChecked!==true;
    for(const n of $id('calendar-list').querySelectorAll('button'))n.disabled=blocked;
  }
  function begin(){if(busy||!owner)return null;const op={owner,epoch,id:++serial,sessionId:state.activeId};busy=op.id;controls();return op;}
  function end(op){if(current(op)&&busy===op.id){busy=0;controls();}}
  function recurrenceControls(value){
    const select=$id('calendar-repeat'),previous=value??select.value??'none';select.replaceChildren();
    const enabled=calendar?.capabilities?.periodic===true,declared=calendar?.capabilities?.recurrence_choices;
    const choices=enabled?(Array.isArray(declared)?declared.filter(k=>Object.hasOwn(REPEATS,k)):Object.keys(REPEATS)):['none'];
    for(const key of choices.length?choices:['none']){const option=make('option',REPEATS[key]);option.value=key;select.append(option);}
    if(edit?.metadata?.recurrence?.repeat===previous&&!Array.from(select.options).some(o=>o.value===previous)){
      const option=make('option','保留原重复规则');option.value=previous;option.disabled=true;select.append(option);
    }
    select.value=Array.from(select.options).some(o=>o.value===previous)?previous:'none';
    $id('calendar-repeat-field').hidden=!enabled;
    $id('calendar-timezone').textContent='输入时间按手机本地时间显示'+(enabled?'；重复规则使用 '+formTimezone+'。':'。');
  }
  function form(row=null,action='create'){
    editorOwner=owner;edit=row;mode=row?action:'create';requestId='chat-calendar-'+Date.now()+'-'+Math.random().toString(16).slice(2);
    $id('calendar-text').value=row?String(row.content||'').replace(/^【日程】/,''):'';
    const due=row&&Date.parse(row.due_at)>Date.now()?row.due_at:Date.now()+3600000;
    $id('calendar-time').value=localDate(due);
    formTimezone=row?.metadata?.recurrence?.timezone||row?.timezone||deviceTimezone();
    recurrenceControls(row?.metadata?.recurrence?.repeat||'none');
    $id('calendar-form-title').textContent=mode==='restore'?'恢复已取消日程':row?'编辑日程':'安排提醒';
    $id('calendar-save').textContent=mode==='restore'?'恢复提醒':row?'保存修改':'添加日程';controls();
  }
  function settingsControls(){
    const values=snapshot.settings.values;
    $id('permission-memory').checked=values.shared_memory===true;
    $id('permission-calendar').checked=values.linked_calendar===true;
    $id('permission-activity').checked=values.linked_activity===true;
    $id('permission-activity-field').hidden=!supports('linked_activity');
    if($id('permission-perception'))$id('permission-perception').checked=values.linked_perception===true;
    if($id('permission-perception-field'))$id('permission-perception-field').hidden=!supports('linked_perception');
    const select=$id('workspace-destination');select.replaceChildren();
    const declared=snapshot.destinations,choices=Array.isArray(declared)?declared:declared&&typeof declared==='object'?Object.keys(declared):['qq','chat_text'];
    for(const key of Object.keys(DESTINATIONS).filter(k=>choices.includes(k))){
      const label=typeof declared?.[key]==='string'?declared[key]:DESTINATIONS[key],option=make('option',label);option.value=key;select.append(option);
    }
    if(!Array.from(select.options).some(o=>o.value===values.proactive_destination)){
      const option=make('option','当前服务器设置（未声明可修改）');option.value=values.proactive_destination;option.disabled=true;select.append(option);
    }
    select.value=values.proactive_destination;
    $id('workspace-binding').textContent=linked()?'已绑定QQ '+(snapshot.identity.qq_account_masked||'已确认账户'):'QQ尚未确认绑定；Chat自己的日程仍可使用。';
    $id('workspace-route-note').textContent='按服务器支持选择QQ、仅文字或全部媒体的主动消息目的地；同一消息沿原发送链处理。通知仍取决于APP后台和手机系统，存入Chat不等于已读。';
  }
  function draw(){
    const box=$id('calendar-list');box.replaceChildren();const day=$id('calendar-day').value;
    const rows=calendar.items.filter(row=>!day||localDate(row.due_at).slice(0,10)===day);
    for(const row of rows){
      const item=make('article','','workspace-card'),recurrence=row.metadata?.recurrence;
      item.append(make('strong',row.content),make('p',new Date(row.due_at).toLocaleString()+' · '+(row.source==='qq'?'QQ事项（只读）':'Chat提醒')));
      const labels={active:'等待提醒',cancelled:'已取消',completed:'已完成',confirmed:'已存入聊天',unknown:'结果待核对',sending:'正在发送',expired:'已过期'};
      item.append(make('small',(labels[row.status]||row.status)+' · '+(labels[row.task_state]||row.task_state||'尚未入队')));
      if(recurrence?.repeat)item.append(make('p',(REPEATS[recurrence.repeat]||'原有重复规则')+' · '+recurrence.timezone,'workspace-recurrence'));
      if(row.editable===true&&row.source!=='qq'&&!unsafe(row)){
        if(row.status==='active')item.append(button('编辑',()=>{if(locked())return;form(row,'update');$id('calendar-text').focus();}),button('取消提醒',()=>cancel(row)));
        if(row.status==='cancelled'&&calendar.capabilities?.restore===true)item.append(button('恢复提醒',()=>{if(locked())return;form(row,'restore');$id('calendar-time').focus();}));
      }
      box.append(item);
    }
    if(!rows.length)box.append(make('p',day?'这一天没有日程。':'暂无可读取的日程。'));
    const notes=$id('workspace-notes');notes.replaceChildren();
    for(const note of calendar.notes||[]){const f=note.fields||{};notes.append(make('li',(f.title||f.content||'便签')+(f.due_at?' · '+new Date(f.due_at*1000).toLocaleString():'')));}
    if(!notes.children.length)notes.append(make('li','暂无可读取的待办。'));
    $id('calendar-form').hidden=calendar.writable!==true;
    $id('workspace-source').textContent=calendar.writable?'日程保存在TLS，到期写入当前Chat。手机系统日历未读取。':'需一条真实APP消息登记当前会话后才能维护日程；已有资料仍可按授权查阅。';
    if((calendar.sources||[]).some(row=>row.state==='scope_unavailable'))$id('workspace-source').textContent+=' 部分来源当前授权不可用，未按空数据处理。';
    recurrenceControls();controls();
  }
  function reconcile(){
    const pending=pendingWrites.get(owner);if(!pending||pending.phase!=='unknown')return false;pending.readChecked=true;
    let matched=false;
    if(pending.kind==='settings')matched=Object.entries(pending.body.changes).every(([key,value])=>snapshot.settings.values[key]===value);
    else if(pending.body.id){
      const row=calendar.items.find(r=>r.id===pending.body.id),body=pending.body;
      if(body.action==='cancel')matched=row?.status==='cancelled';
      else matched=!!row&&row.status==='active'&&row.revision>body.expected_revision
        &&Date.parse(row.due_at)===Date.parse(body.due_at)&&String(row.content||'').replace(/^【日程】/,'')===body.text;
    }
    if(matched){pendingWrites.delete(owner);if(pending.kind==='calendar'&&pending.body.action!=='cancel')form();return true;}return false;
  }
  async function read(){
    const op=begin();if(!op)return;say('正在读取TLS…');readProactive();
    try{
      const [settings,data]=await Promise.all([apiClient.json('GET',route('workspace',op.sessionId)),apiClient.json('GET',route('calendar',op.sessionId))]);
      if(!current(op))return;
      if(!settings?.settings?.values||!Array.isArray(data?.items))throw Error('服务器未返回完整的日程与权限。');
      snapshot=settings;calendar=data;settingsControls();const confirmed=reconcile();draw();
      const pending=pendingWrites.get(owner);
      say(confirmed?'已回读，当前服务器值与上次修改一致。':pending?(pending.failure?pending.failure+' ':'')+'已回读。上次操作仍待核对，不会自动重发。':'已读取服务器当前配置与日程。');
    }catch(e){if(current(op))say(errorText(e));}finally{end(op);}
  }
  async function write(kind,body,success){
    if(locked())return;const op=begin();if(!op)return;
    const pending={kind,body,phase:'inflight',readChecked:false};pendingWrites.set(op.owner,pending);controls();
    try{
      await apiClient.json('POST',kind==='settings'?'/chat/workspace':'/chat/calendar',body);
      if(pendingWrites.get(op.owner)===pending)pendingWrites.delete(op.owner);
      if(current(op)){if(kind==='calendar'&&body.action!=='cancel')form();say(success);}
    }catch(e){pending.phase='unknown';pending.failure=errorText(e);if(current(op))say(pending.failure+' 请刷新核对；不会自动重试。');}
    finally{end(op);}if(current(op))await read();
  }
  async function saveSettings(){
    if(locked()||!snapshot||owner!==scope())return;
    const values=snapshot.settings.values,changes={};
    for(const [key,id]of [['shared_memory','permission-memory'],['linked_calendar','permission-calendar'],['linked_activity','permission-activity'],['linked_perception','permission-perception']]){
      if(!supports(key)||(key!=='shared_memory'&&!linked()))continue;
      if(values[key]!==$id(id).checked)changes[key]=$id(id).checked;
    }
    const select=$id('workspace-destination'),chosen=Array.from(select.options).find(o=>o.value===select.value);
    if(supports('proactive_destination')&&linked()&&chosen&&!chosen.disabled&&select.value!==values.proactive_destination)changes.proactive_destination=select.value;
    if(!Object.keys(changes).length){say('当前没有需要保存的修改。');return;}
    await write('settings',{session_id:state.activeId,expected_revision:snapshot.settings.revision,changes},'已保存，正在回读…');
  }
  async function saveCalendar(event){
    event.preventDefault();if(locked()||calendar?.writable!==true||owner!==scope())return;
    const text=$id('calendar-text').value.trim(),date=new Date($id('calendar-time').value);
    if(!text||!Number.isFinite(date.getTime())||date.getTime()<=Date.now()){say('请填写内容和未来的提醒时间。');return;}
    const body={session_id:state.activeId,action:edit?mode:'create',...(edit?{id:edit.id,expected_revision:edit.revision}:{request_id:requestId}),due_at:date.toISOString(),text};
    if(calendar.capabilities?.periodic===true){
      const repeat=$id('calendar-repeat').value,old=edit?.metadata?.recurrence?.repeat||'none';
      if(!edit||repeat!==old){body.repeat=repeat;body.timezone=formTimezone;}
    }
    await write('calendar',body,mode==='restore'?'日程已恢复。':'日程已保存。');
  }
  async function cancel(row){
    if(locked()||owner!==scope()||row.editable!==true||row.source==='qq'||unsafe(row))return;
    await write('calendar',{session_id:state.activeId,action:'cancel',id:row.id,expected_revision:row.revision},'日程已取消。');
  }
  function invalidate(){epoch++;proactiveSerial++;owner='';busy=0;snapshot=null;calendar=null;}
  function open(){
    if(!state.authenticated||!state.activeId){showNotice('先连接伙伴。');return;}
    hideMoreMenu();epoch++;owner=scope();busy=0;snapshot=null;calendar=null;
    $id('calendar-list').replaceChildren();$id('workspace-notes').replaceChildren();$id('workspace-binding').textContent='正在读取…';$id('calendar-form').hidden=true;
    for(const id of ['permission-memory','permission-calendar','permission-activity','permission-perception'])$id(id).checked=false;
    $id('permission-activity-field').hidden=true;$id('permission-perception-field').hidden=true;$id('workspace-destination').replaceChildren();
    if(editorOwner!==owner)form();else controls();
    if(!$id('workspace-dialog').open)$id('workspace-dialog').showModal();read();
  }
  function scopeChanged(){if(owner&&(!state.authenticated||owner!==scope())){invalidate();$id('workspace-dialog')?.close();}}
  document.addEventListener('DOMContentLoaded',()=>{
    const d=document.createElement('dialog');d.id='workspace-dialog';d.className='settings-dialog';
    d.innerHTML='<div class="settings-form"><div class="dialog-heading"><h2>日程与权限</h2><button id="workspace-close" class="icon-button" aria-label="关闭" type="button">×</button></div><p id="workspace-binding"></p><details><summary>查阅权限与主动消息</summary><p class="appearance-help">只控制已确认绑定双方的资料共享，不申请手机日历、定位或全盘访问。</p><label class="experience-field"><span><input type="checkbox" id="permission-memory"> 双向查阅长期记忆</span></label><label class="experience-field"><span><input type="checkbox" id="permission-calendar"> 在Chat查阅已绑定QQ的日程与待办</span></label><label class="experience-field" id="permission-activity-field" hidden><span><input type="checkbox" id="permission-activity"> 两端聊天互相免打扰</span><small class="appearance-help">任一端近期正在聊天时，减少另一端的主动打扰；不复制消息或授予发送权限。</small></label><label class="experience-field" id="permission-perception-field" hidden><span><input type="checkbox" id="permission-perception"> 在Chat使用已绑定手机的感知与音乐</span><small class="appearance-help">复用原PPB设备授权和原数据，用于当前角色上下文与应用陪伴；不新增采集权限，可随时关闭。</small></label><label class="experience-field">主动消息发送位置<select id="workspace-destination"></select></label><p id="workspace-route-note" class="appearance-help"></p><button id="workspace-save" class="secondary-button" type="button">保存权限与发送位置</button></details><div class="appearance-actions"><label>查看日期 <input id="calendar-day" type="date"></label><button id="calendar-all" type="button" class="text-button">全部日期</button><button id="workspace-refresh" type="button" class="text-button">刷新</button></div><p id="workspace-source" class="appearance-help"></p><div id="calendar-list"></div><form id="calendar-form"><h3 id="calendar-form-title">安排提醒</h3><label class="experience-field">内容<textarea id="calendar-text" maxlength="3000" rows="3" required></textarea></label><label class="experience-field">手机本地时间<input id="calendar-time" type="datetime-local" required></label><label class="experience-field" id="calendar-repeat-field" hidden>重复<select id="calendar-repeat"><option value="none">不重复</option></select></label><p id="calendar-timezone" class="appearance-help"></p><div class="appearance-actions"><button id="calendar-save" type="submit" class="primary-button">添加日程</button><button id="calendar-new" type="button" class="text-button">清空编辑</button></div></form><details><summary>已有待办</summary><ul id="workspace-notes"></ul></details><p id="workspace-status" role="status" class="appearance-help"></p><button id="workspace-clear-pending" type="button" class="text-button" hidden>已核对，继续编辑</button></div>';
    document.body.append(d);
    const proactive=make('section',undefined,'workspace-proactive');proactive.setAttribute('aria-label','当前主动消息状态');
    const proactiveHead=make('div',undefined,'workspace-state-heading'),proactiveRefresh=button('读取状态',readProactive);proactiveRefresh.id='workspace-proactive-refresh';
    proactiveHead.append(make('h3','现在会主动来找我吗？'),proactiveRefresh);const proactiveBody=make('div');proactiveBody.id='workspace-proactive-body';
    proactive.append(proactiveHead,proactiveBody,make('p','只读当前开关、节奏与来源状态；下次评估不是发送预约，也不保证横幅通知。打开或手动刷新时读取，不在此页持续轮询。','appearance-help'));
    $id('workspace-binding').after(proactive);
    $id('workspace-close').onclick=()=>d.close();$id('workspace-refresh').onclick=read;$id('workspace-save').onclick=saveSettings;
    $id('calendar-form').onsubmit=saveCalendar;$id('calendar-new').onclick=()=>{const p=pendingWrites.get(owner);if(p?.phase==='inflight')return;pendingWrites.delete(owner);form();say('已开始新的日程草稿；原操作未重发，请先核对列表避免重复。');};
    $id('workspace-clear-pending').onclick=()=>{const p=pendingWrites.get(owner);if(!busy&&p?.phase==='unknown'&&p.readChecked){pendingWrites.delete(owner);say('已结束本次等待；原请求仍可能稍后完成。请核对后再提交新修改。');controls();}};
    $id('calendar-day').onchange=()=>calendar&&draw();$id('calendar-all').onclick=()=>{$id('calendar-day').value='';if(calendar)draw();};
    d.addEventListener('close',()=>{if(!d.open)invalidate();});
    $id('more-menu').append(button('日程与权限',open));
  },{once:true});
  return {open,scopeChanged};
})();
