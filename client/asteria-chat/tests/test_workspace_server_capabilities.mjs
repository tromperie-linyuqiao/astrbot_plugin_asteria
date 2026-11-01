/* Isolated DOM/bridge purposes. No browser, APK, production, model or send. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const source=await fs.readFile(new URL('../web/chat-workspace.js',import.meta.url),'utf8');
const clone=value=>JSON.parse(JSON.stringify(value));
const turn=()=>new Promise(resolve=>setImmediate(resolve));
const localTime=value=>{const d=new Date(value);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);};

class Element {
  constructor(tag='div',document){this.tagName=tag.toUpperCase();this.ownerDocument=document;this.children=[];this.handlers={};this.value='';this.textContent='';this.className='';this.hidden=false;this.disabled=false;this.checked=false;this.open=false;}
  set id(value){this._id=value;this.ownerDocument.elements.set(value,this);} get id(){return this._id||'';}
  set innerHTML(value){
    this.children=[];
    for(const match of value.matchAll(/<([a-z][a-z0-9-]*)([^>]*\bid="([^"]+)"[^>]*)>/gi)){
      const item=new Element(match[1],this.ownerDocument);item.id=match[3];item.hidden=/\bhidden\b/.test(match[2]);this.append(item);
    }
  }
  get options(){return this.children.filter(child=>child.tagName==='OPTION');}
  append(...items){for(const item of items){item.parent=this;this.children.push(item);if(this.tagName==='SELECT'&&!this.value)this.value=item.value;}}
  before(...items){for(const item of items)item.parent=this.parent;this.parent?.children.splice(this.parent.children.indexOf(this),0,...items);}
  after(...items){for(const item of items)item.parent=this.parent;this.parent?.children.splice(this.parent.children.indexOf(this)+1,0,...items);}
  setAttribute(name,value){this[name]=value;}
  replaceChildren(...items){this.children=[];if(this.tagName==='SELECT')this.value='';this.append(...items);}
  querySelectorAll(selector){return this.children.flatMap(child=>[...(child.tagName===selector.toUpperCase()?[child]:[]),...child.querySelectorAll(selector)]);}
  addEventListener(name,handler){(this.handlers[name]??=[]).push(handler);}
  showModal(){this.open=true;} close(){this.open=false;for(const handler of this.handlers.close||[])handler();}
  focus(){this.ownerDocument.focused=this.id;}
}

function setup({legacy=false,linked=true,calendarRows=[],deferReads=false,failCalendar=false,perception=false}={}){
  const document={elements:new Map(),handlers:{},getElementById(id){assert(this.elements.has(id),'missing element '+id);return this.elements.get(id);},
    createElement(tag){return new Element(tag,this);},addEventListener(name,handler){this.handlers[name]=handler;}};
  document.body=new Element('body',document);document.head=new Element('head',document);
  const more=new Element('div',document);more.id='more-menu';document.body.append(more);
  const state={server:'https://fixture.invalid/tls-chat-api',username:'fixture-user',activeId:'owned-1',authenticated:true,draft:'原聊天草稿'};
  let settings={identity:{linked,qq_account_masked:'***1234'},settings:{revision:1,values:{shared_memory:true,linked_calendar:false,proactive_destination:'qq',...(legacy?{}:{linked_activity:true})}}};
  if(!legacy){settings.destinations={qq:'保留QQ',chat_text:'仅文字发Chat',chat_all:'全部媒体发Chat'};settings.supported_settings=['shared_memory','linked_calendar','linked_activity','proactive_destination'];}
  if(perception&&!legacy){settings.settings.values.linked_perception=false;settings.supported_settings.push('linked_perception');}
  const calendar={items:clone(calendarRows),notes:[],sources:[],writable:true,...(legacy?{}:{capabilities:{periodic:true,restore:true,recurrence_choices:['none','daily','weekly','monthly','yearly']}})};
  const calls=[],deferred=[];let sequence=0,failNextCalendar=failCalendar;
  const apiClient={async json(method,path,body){
    calls.push({method,path,body:body?clone(body):undefined});
    if(method==='GET'){
      if(path.startsWith('/chat/proactive-state?'))return {available:false};
      if(path.startsWith('/chat/important-dates?'))return {records:[],sources:[],writable:true,capabilities:{}};
      const result=clone(path.startsWith('/chat/workspace?')?settings:calendar);
      if(deferReads)return await new Promise(resolve=>deferred.push(()=>resolve(result)));
      return result;
    }
    if(path==='/chat/workspace'){assert.equal(body.expected_revision,settings.settings.revision);Object.assign(settings.settings.values,clone(body.changes));settings.settings.revision++;return clone(settings.settings);}
    assert.equal(path,'/chat/calendar');
    if(failNextCalendar){failNextCalendar=false;throw Object.assign(Error('未知写入结果'),{status:0});}
    let row=calendar.items.find(item=>item.id===body.id);
    if(body.action==='create'){
      row={id:'created-'+(++sequence),revision:1,status:'active',task_state:'queued',source:'chat',editable:true,content:'【日程】'+body.text,due_at:body.due_at,metadata:{recurrence:null}};calendar.items.push(row);
    }else{
      assert.ok(row,'mutation needs an existing row');assert.equal(row.revision,body.expected_revision);
      row.revision++;row.status=body.action==='cancel'?'cancelled':'active';row.task_state=body.action==='cancel'?'cancelled':'queued';
      if(body.action!=='cancel'){assert.ok(body.text,'restore/update require text');row.content='【日程】'+body.text;row.due_at=body.due_at;}
    }
    if(Object.hasOwn(body,'repeat'))row.metadata.recurrence=body.repeat==='none'?null:{repeat:body.repeat,timezone:body.timezone};
    return clone(row);
  }};
  const context=vm.createContext({window:{},document,state,apiClient,Intl,Date,JSON,Map,Math,Number,Object,Array,Promise,
    encodeURIComponent,showNotice:()=>{},hideMoreMenu:()=>{},errorText:error=>error.message});
  vm.runInContext(source,context,{filename:'chat-workspace.js'});document.handlers.DOMContentLoaded();
  return {context,api:context.window.ChatWorkspace,document,state,calls,deferred,calendar,get settings(){return settings;},
    setSettings(value){settings=clone(value);},get:id=>document.getElementById(id)};
}

async function flush(){for(let i=0;i<6;i++)await turn();}
async function click(node){assert.equal(node.disabled,false,'button must be usable: '+node.id);await node.onclick?.();await flush();}
async function submit(env){await env.get('calendar-form').onsubmit({preventDefault(){}});await flush();}
const buttons=(env,label)=>env.get('calendar-list').querySelectorAll('button').filter(n=>n.textContent===label);
let purposes=0;

{
  const due=new Date(Date.now()+3600000).toISOString();
  const rows=[{id:'cancelled-periodic',revision:4,status:'cancelled',task_state:'cancelled',source:'chat',editable:true,content:'【日程】原有周期',due_at:due,
    metadata:{recurrence:{repeat:'monthly',timezone:'Asia/Tokyo'}}},
    {id:'uncertain',revision:1,status:'cancelled',task_state:'unknown',source:'chat',editable:true,content:'未知结果',due_at:due},
    {id:'qq-readonly',revision:1,status:'cancelled',task_state:'cancelled',source:'qq',editable:true,content:'QQ资料',due_at:due}];
  const env=setup({calendarRows:rows});env.api.open();await flush();
  assert.deepEqual(env.get('workspace-destination').options.map(o=>o.value),['qq','chat_text','chat_all']);
  assert.equal(env.get('permission-activity-field').hidden,false);assert.equal(env.get('permission-activity').disabled,false);
  env.get('permission-activity').checked=false;env.get('workspace-destination').value='chat_all';await click(env.get('workspace-save'));
  const settingPost=env.calls.find(c=>c.method==='POST'&&c.path==='/chat/workspace');
  assert.deepEqual(settingPost.body.changes,{linked_activity:false,proactive_destination:'chat_all'});
  assert.equal(env.get('calendar-repeat-field').hidden,false);assert.equal(env.get('calendar-repeat').options.length,5);
  env.get('calendar-text').value='每周检查';env.get('calendar-time').value=localTime(Date.now()+7200000);env.get('calendar-repeat').value='weekly';await submit(env);
  let last=env.calls.filter(c=>c.method==='POST'&&c.path==='/chat/calendar').at(-1).body;
  assert.equal(last.repeat,'weekly');assert.equal(last.timezone,Intl.DateTimeFormat().resolvedOptions().timeZone);assert.equal(last.action,'create');
  const edited=buttons(env,'编辑').find(n=>n.parent.children.some(child=>child.textContent==='【日程】每周检查'));assert.ok(edited);await click(edited);
  env.get('calendar-text').value='仅改正文';await submit(env);last=env.calls.filter(c=>c.method==='POST'&&c.path==='/chat/calendar').at(-1).body;
  assert.equal(last.action,'update');assert.equal(Object.hasOwn(last,'repeat'),false);assert.equal(Object.hasOwn(last,'timezone'),false);
  assert.equal(buttons(env,'恢复提醒').length,1,'readonly/UNKNOWN rows must not expose restore');
  await click(buttons(env,'恢复提醒')[0]);assert.equal(env.get('calendar-repeat').value,'monthly');assert.match(env.get('calendar-timezone').textContent,/Asia\/Tokyo/);
  env.get('calendar-time').value=localTime(Date.now()+86400000);await submit(env);last=env.calls.filter(c=>c.method==='POST'&&c.path==='/chat/calendar').at(-1).body;
  assert.equal(last.action,'restore');assert.equal(last.id,'cancelled-periodic');assert.equal(last.expected_revision,4);assert.equal(last.text,'原有周期');
  assert.equal(Object.hasOwn(last,'repeat'),false);assert.equal(Object.hasOwn(last,'timezone'),false);
  assert.equal(env.calendar.items.find(r=>r.id==='cancelled-periodic').metadata.recurrence.timezone,'Asia/Tokyo');
  assert.equal(env.state.draft,'原聊天草稿');purposes++;
}

{
  const old=setup({legacy:true});old.api.open();await flush();assert.equal(old.get('permission-activity-field').hidden,true);
  assert.deepEqual(old.get('workspace-destination').options.map(o=>o.value),['qq','chat_text']);assert.equal(old.get('calendar-repeat-field').hidden,true);
  old.get('permission-memory').checked=false;old.get('permission-activity').checked=false;await click(old.get('workspace-save'));
  assert.deepEqual(old.calls.find(c=>c.method==='POST').body.changes,{shared_memory:false});
  old.get('calendar-text').value='旧服务器单次';old.get('calendar-time').value=localTime(Date.now()+3600000);await submit(old);
  const create=old.calls.filter(c=>c.method==='POST'&&c.path==='/chat/calendar').at(-1).body;
  assert.equal(Object.hasOwn(create,'repeat'),false);assert.equal(Object.hasOwn(create,'timezone'),false);
  const unbound=setup({linked:false});unbound.api.open();await flush();assert.equal(unbound.get('permission-activity').disabled,true);
  unbound.get('permission-memory').checked=false;unbound.get('permission-activity').checked=false;await click(unbound.get('workspace-save'));
  assert.deepEqual(unbound.calls.find(c=>c.method==='POST').body.changes,{shared_memory:false});purposes++;
}

{
  const env=setup({deferReads:true});env.api.open();await turn();assert.equal(env.deferred.length,2);
  env.get('calendar-text').value='保留的日程草稿';env.get('workspace-dialog').close();
  const newer=clone(env.settings);newer.settings.values.proactive_destination='chat_all';newer.identity.qq_account_masked='***9999';env.setSettings(newer);
  env.api.open();await turn();assert.equal(env.deferred.length,4);
  for(const reply of env.deferred.slice(0,2))reply();await flush();
  assert.equal(env.get('workspace-binding').textContent,'正在读取…');
  assert.equal(env.get('workspace-refresh').disabled,true,'old finally must not release the new read lock');
  assert.equal(env.get('calendar-text').value,'保留的日程草稿');
  for(const reply of env.deferred.slice(2))reply();await flush();
  assert.equal(env.get('workspace-destination').value,'chat_all');assert.match(env.get('workspace-binding').textContent,/9999/);
  assert.equal(env.get('workspace-refresh').disabled,false);assert.equal(env.get('calendar-text').value,'保留的日程草稿');
  assert.equal(env.calls.filter(c=>c.method==='POST').length,0);purposes++;
}

{
  const env=setup({failCalendar:true});env.api.open();await flush();env.get('calendar-text').value='只提交一次';env.get('calendar-time').value=localTime(Date.now()+3600000);await submit(env);
  assert.equal(env.calls.filter(c=>c.method==='POST').length,1);assert.equal(env.get('calendar-save').disabled,true);
  assert.equal(env.get('calendar-text').value,'只提交一次');assert.match(env.get('workspace-status').textContent,/不会自动重发/);
  await click(env.get('workspace-refresh'));env.get('workspace-dialog').close();env.api.open();await flush();
  assert.equal(env.calls.filter(c=>c.method==='POST').length,1);assert.equal(env.get('calendar-text').value,'只提交一次');
  assert.equal(env.get('calendar-save').disabled,true);assert.equal(env.get('workspace-clear-pending').disabled,false);
  assert.equal(env.state.draft,'原聊天草稿');purposes++;
}

{
  const env=setup({perception:true});env.api.open();await flush();
  assert.equal(env.get('permission-perception-field').hidden,false);
  assert.equal(env.get('permission-perception').checked,false);
  env.get('permission-perception').checked=true;await click(env.get('workspace-save'));
  assert.deepEqual(env.calls.find(c=>c.method==='POST').body.changes,{linked_perception:true});
  assert.equal(env.settings.settings.values.linked_perception,true);
  const old=setup({legacy:true});old.api.open();await flush();
  assert.equal(old.get('permission-perception-field').hidden,true);purposes++;
}

console.log(JSON.stringify({purposes,passed:true,real_browser:false,apk_built:false,production_connection:false}));
