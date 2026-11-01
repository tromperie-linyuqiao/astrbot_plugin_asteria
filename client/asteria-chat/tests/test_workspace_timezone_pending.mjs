/* Current source functions and a local DOM/API fixture. No Android/server/send. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const source=await fs.readFile(new URL('../web/chat-workspace.js',import.meta.url),'utf8');
const exportMarker='return {open,scopeChanged};';
assert.equal(source.split(exportMarker).length,2,'only the fixture exposes private function references');
const fixtureSource=source.replace(exportMarker,'return {open,scopeChanged,__timezone:deviceTimezone};');
const clone=value=>JSON.parse(JSON.stringify(value));
const turn=()=>new Promise(resolve=>setImmediate(resolve));
async function flush(){for(let i=0;i<6;i++)await turn();}

class Element{
  constructor(tag,document){this.tagName=tag.toUpperCase();this.document=document;this.children=[];this.handlers={};this.value='';this.textContent='';this.disabled=false;this.hidden=false;this.open=false;this.checked=false;}
  set id(value){this._id=value;this.document.elements.set(value,this);}get id(){return this._id||'';}
  set innerHTML(value){this.children=[];for(const match of value.matchAll(/<([a-z][a-z0-9-]*)([^>]*\bid="([^"]+)"[^>]*)>/gi)){const item=new Element(match[1],this.document);item.id=match[3];item.hidden=/\bhidden\b/.test(match[2]);this.append(item);}}
  get options(){return this.children.filter(child=>child.tagName==='OPTION');}
  append(...items){for(const item of items){item.parent=this;this.children.push(item);if(this.tagName==='SELECT'&&!this.value)this.value=item.value;}}
  before(...items){for(const item of items)item.parent=this.parent;this.parent?.children.splice(this.parent.children.indexOf(this),0,...items);}
  after(...items){for(const item of items)item.parent=this.parent;this.parent?.children.splice(this.parent.children.indexOf(this)+1,0,...items);}
  setAttribute(name,value){this[name]=value;}
  replaceChildren(...items){this.children=[];if(this.tagName==='SELECT')this.value='';this.append(...items);}
  querySelectorAll(selector){return this.children.flatMap(child=>[...(child.tagName===selector.toUpperCase()?[child]:[]),...child.querySelectorAll(selector)]);}
  addEventListener(name,handler){(this.handlers[name]??=[]).push(handler);}
  showModal(){this.open=true;}close(){this.open=false;for(const handler of this.handlers.close||[])handler();}focus(){}
}

function setup({zone,offset=0,intlThrows=false,mount=false}={}){
  const document={elements:new Map(),handlers:{},getElementById(id){assert(this.elements.has(id),'missing fixture node '+id);return this.elements.get(id);},createElement(tag){return new Element(tag,this);},addEventListener(name,handler){this.handlers[name]=handler;}};
  document.body=new Element('body',document);const menu=new Element('div',document);menu.id='more-menu';document.body.append(menu);
  const state={server:'https://fixture.invalid/tls-chat-api',username:'fixture-user',activeId:'owned-1',authenticated:true,draft:'不触碰聊天草稿'};
  const settings={identity:{linked:true},supported_settings:['shared_memory','linked_calendar','linked_activity','linked_perception','proactive_destination'],destinations:{qq:'QQ',chat_text:'文字',chat_all:'全部'},settings:{revision:1,values:{shared_memory:true,linked_calendar:true,linked_activity:true,linked_perception:true,proactive_destination:'chat_all'}}};
  const calendar={items:[],notes:[],sources:[],writable:true,capabilities:{periodic:true,restore:true,recurrence_choices:['none','daily','weekly','monthly','yearly']}};
  const calls=[],failure='HTTP 400: invalid explicit UTC offset';
  const apiClient={async json(method,path,body){calls.push({method,path,body:body?clone(body):undefined});if(method==='GET')return clone(path.startsWith('/chat/workspace?')?settings:path.startsWith('/chat/important-dates?')?{records:[],sources:[],writable:true,capabilities:{}}:path.startsWith('/chat/proactive-state?')?{available:false}:calendar);assert.equal(path,'/chat/calendar');throw Object.assign(Error(failure),{status:400});}};
  class FixtureDate extends Date{getTimezoneOffset(){return offset;}}
  const fixtureIntl={DateTimeFormat(){if(intlThrows)throw Error('Intl unavailable');return {resolvedOptions:()=>({timeZone:zone})};}};
  const context=vm.createContext({window:{},document,state,apiClient,Intl:fixtureIntl,Date:FixtureDate,JSON,Map,Math,Number,Object,Array,Promise,encodeURIComponent,showNotice(){},hideMoreMenu(){},errorText:e=>e.message});
  vm.runInContext(fixtureSource,context,{filename:'chat-workspace.js'});
  if(mount)document.handlers.DOMContentLoaded();
  return {api:context.window.ChatWorkspace,calls,state,failure,get:id=>document.getElementById(id)};
}

const zones=[
  ['+00:00',0,'UTC+00:00'],['+08:00',0,'UTC+08:00'],['-03:30',0,'UTC-03:30'],
  ['-14:00',0,'UTC-14:00'],['+14:00',0,'UTC+14:00'],['UTC+05:45',0,'UTC+05:45'],
  ['Asia/Shanghai',0,'Asia/Shanghai'],['America/New_York',0,'America/New_York'],['UTC',0,'UTC'],
  ['+14:01',-480,'UTC+08:00'],['+24:00',-480,'UTC+08:00'],['+08:60',-480,'UTC+08:00'],
  ['-99:00',-480,'UTC+08:00'],['UTC+15:00',-480,'UTC+08:00'],['+8:00',-480,'UTC+08:00'],
  [undefined,330,'UTC-05:30'],['',-345,'UTC+05:45'],['+99:00',Infinity,'UTC']
];
for(const [zone,offset,expected]of zones)assert.equal(setup({zone,offset}).api.__timezone(),expected,JSON.stringify({zone,offset}));
assert.equal(setup({intlThrows:true,offset:-345}).api.__timezone(),'UTC+05:45');

const env=setup({zone:'+00:00',mount:true});env.api.open();await flush();
env.get('calendar-text').value='只提交一次的专项夹具';
const future=new Date(Date.now()+7200000);
env.get('calendar-time').value=new Date(future.getTime()-future.getTimezoneOffset()*60000).toISOString().slice(0,16);env.get('calendar-repeat').value='none';
await env.get('calendar-form').onsubmit({preventDefault(){}});await flush();
const posts=()=>env.calls.filter(row=>row.method==='POST');
assert.equal(posts().length,1);const body=posts()[0].body;
assert.deepEqual(Object.keys(body).sort(),['action','due_at','repeat','request_id','session_id','text','timezone']);
assert.equal(body.session_id,'owned-1');assert.equal(body.action,'create');assert.equal(body.repeat,'none');assert.equal(body.timezone,'UTC+00:00');
assert.match(body.request_id,/^chat-calendar-/);assert.equal(body.text,'只提交一次的专项夹具');assert(Number.isFinite(Date.parse(body.due_at)));
assert.match(env.get('workspace-status').textContent,/HTTP 400: invalid explicit UTC offset/);
assert.match(env.get('workspace-status').textContent,/已回读.*仍待核对.*不会自动重发/);
assert.equal(env.get('calendar-save').disabled,true,'empty GET must not release an unknown write');
assert.equal(env.get('calendar-text').value,body.text);assert.equal(env.get('workspace-clear-pending').hidden,false);
await env.get('workspace-refresh').onclick();await flush();
env.get('workspace-dialog').close();env.api.open();await flush();
assert.equal(posts().length,1,'refresh/reopen must never retry the write');
assert.match(env.get('workspace-status').textContent,/HTTP 400: invalid explicit UTC offset/);
assert.equal(env.get('calendar-save').disabled,true);assert.equal(env.get('calendar-text').value,body.text);
assert.equal(env.get('permission-memory').checked,true);assert.equal(env.get('permission-calendar').checked,true);
assert.equal(env.get('workspace-destination').value,'chat_all');assert.equal(env.state.draft,'不触碰聊天草稿');
console.log(JSON.stringify({purposes:2,timezone_cases:zones.length+1,passed:true,real_browser:false,android:false,production_connection:false,real_posts:0,fixture_posts:posts().length,auto_retries:0}));
