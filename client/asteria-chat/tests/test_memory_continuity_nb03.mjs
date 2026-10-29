/* Actual memory-module callbacks; API/DOM fixtures are not Android or production. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
const source=await fs.readFile(new URL('../web/chat-message-memory.js',import.meta.url),'utf8');
const clone=value=>JSON.parse(JSON.stringify(value));
const flush=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
class Element{
  constructor(tag,doc){this.tagName=tag.toUpperCase();this.doc=doc;this.children=[];this.events={};this.text='';this.value='';this.hidden=false;this.disabled=false;this.checked=false;this.open=false;}
  set id(value){this._id=value;this.doc.nodes.set(value,this);}get id(){return this._id||'';}
  set textContent(value){this.text=String(value??'');this.children=[];}get textContent(){return this.text+this.children.map(item=>item.textContent).join(' ');}
  append(...items){this.children.push(...items);}replaceChildren(...items){this.text='';this.children=[...items];}
  setAttribute(name,value){this[name]=String(value);}addEventListener(name,fn){(this.events[name]??=[]).push(fn);}
  showModal(){this.open=true;}close(){this.open=false;}
  async fire(name,event={}){for(const fn of this.events[name]||[])await fn(event);}
  async click(){if(!this.disabled&&!this.hidden)await this.fire('click');}
  all(tag){return this.children.flatMap(item=>[...(item.tagName===tag.toUpperCase()?[item]:[]),...item.all(tag)]);}
}
function fixture(){
  const document={nodes:new Map(),createElement(tag){return new Element(tag,this);},getElementById(id){return this.nodes.get(id)||null;}};document.body=document.createElement('body');
  const state={server:'https://fixture.invalid',username:'owner',activeId:'owned',authenticated:true,draft:'未发送的草稿'};
  const calls=[],deferred=[],notices=[];
  const behavior={defer:false,fail:false};
  const record={id:'important.81',content:'用户已纠正的柚子偏好',revision:2,source_id:'tls.chat.message.important',evidence_kind:'user_reported',memory_type:'explicit_memory',
    review_status:'manual',lifecycle:'stable_memory',editable:true,retrieval_lane:'real',real_recall_eligible:true,corrected:true,original_text:'用户原先的蓝莓偏好'};
  function search(url){return {query:url.searchParams.get('query'),records:[clone(record),...(url.searchParams.get('include_roleplay')==='true'?[{
    ...clone(record),id:'rp.81',content:'虚构剧情里的柚子',editable:false,corrected:false,original_text:null,evidence_kind:'roleplay_event',retrieval_lane:'roleplay',real_recall_eligible:false}]:[])],
    shared:{state:'ready',sections:[{text:'已经确认共享的另一端约定',evidence_kind:'user_reported',source:'original_memory'}]},limited:false};}
  const apiClient={async json(method,path,body){
    const url=new URL('https://fixture.invalid'+path);calls.push({method,path,body:body&&clone(body)});
    if(url.pathname==='/chat/memory-search'){
      assert.equal(method,'GET');assert.equal(url.searchParams.get('session_id'),state.activeId);
      if(behavior.defer)return new Promise(resolve=>deferred.push({resolve,value:search(url)}));
      if(behavior.fail)throw Error('服务器暂不可用');return search(url);
    }
    if(url.pathname==='/chat/message-memory')return {message:{message_id:'81',role:'user'},records:[clone(record)],candidates:[],pending_candidate:null,important_saved:true,important_state:'stable_memory',limited:true};
    if(url.pathname==='/chat/memory-detail')return {record:clone(record),history_total:2,history:[{revision:1,operation:'create',record:{content:record.original_text}},{revision:2,operation:'correct',record:clone(record)}]};
    assert.equal(url.pathname,'/chat/memory-correct');assert.equal(method,'POST');assert.equal(body.id,record.id);assert.equal(body.expected_revision,record.revision);
    record.content=body.content;record.revision++;return {record:clone(record)};
  }};
  const window={};vm.runInContext(source,vm.createContext({window,document,state,apiClient,showNotice:text=>notices.push(text),errorText:e=>e.message,
    Map,Set,JSON,Object,Array,Number,String,Date,Math,Promise,Error,encodeURIComponent}),{filename:'chat-message-memory.js'});
  const get=id=>{const node=document.getElementById(id);assert(node,'Missing real module node '+id);return node;};
  const button=label=>{const node=get('message-memory-dialog').all('button').find(item=>item.textContent===label);assert(node,'Missing real module button '+label);return node;};
  const click=async label=>{await button(label).click();await flush();};
  return {window,state,calls,behavior,deferred,record,get,button,click,posts:()=>calls.filter(row=>row.method==='POST')};
}
let purposes=0;
{
  const e=fixture();e.window.ChatMessageMemory.openSearch();await flush();assert.equal(e.calls.length,0);
  assert.equal(e.get('message-memory-propose').hidden,true);assert.equal(e.get('message-memory-search').open,true);
  e.get('message-memory-query').value='柚子';await e.click('搜索记忆');
  assert.equal(e.calls.length,1);assert.match(e.calls[0].path,/include_roleplay=false/);assert.equal(e.posts().length,0);
  const text=e.get('message-memory-search-results').textContent;assert.match(text,/已纠正的柚子/);assert.match(text,/当前版本可参与现实记忆检索/);assert.match(text,/只读/);
  assert.equal(e.get('message-memory-search-results').all('button').length,1,'shared source has no correction control');
  assert.equal(e.state.draft,'未发送的草稿');purposes++;
  e.get('message-memory-include-roleplay').checked=true;await e.click('搜索记忆');
  assert.match(e.get('message-memory-search-results').textContent,/RP 虚构记录，与现实经历分开保存/);
  assert.equal(e.posts().length,0);purposes++;
  await e.click('查看原文与纠错');assert.equal(e.get('message-memory-search').hidden,true);
  const textarea=e.get('message-memory-records').all('textarea')[0];textarea.value='用户最新明确的乌龙茶偏好';await textarea.fire('input');
  const confirm=e.get('message-memory-records').all('input')[0];confirm.checked=true;await confirm.fire('change');await e.click('保存纠错');
  assert.equal(e.posts().length,1);assert.equal(e.posts()[0].body.expected_revision,2);
  assert.match(e.get('message-memory-search-results').textContent,/用户最新明确的乌龙茶偏好/);
  assert.equal(e.get('message-memory-records').textContent,'');assert.equal(e.get('message-memory-search').hidden,false);
  assert.equal(e.calls.filter(call=>call.path.startsWith('/chat/message-memory')).length,0,'search-only correction returns to search, not invalid empty message lookup');purposes++;
}
{
  const e=fixture();e.window.openMessageMemory({serverId:81});await flush();
  assert.match(e.get('message-memory-records').textContent,/原始资料保留/);assert.match(e.get('message-memory-records').textContent,/显示已纠正的当前版本/);
  e.get('message-memory-query').value='柚子';e.behavior.fail=true;await e.click('搜索记忆');
  assert.match(e.get('message-memory-search-status').textContent,/服务器暂不可用/);assert.equal(e.posts().length,0);
  assert.equal(e.get('message-memory-search-button').disabled,false);purposes++;
}
{
  const e=fixture();e.window.ChatMessageMemory.openSearch();e.get('message-memory-query').value='柚子';e.behavior.defer=true;
  const operation=e.button('搜索记忆').click();await flush();assert.equal(e.get('message-memory-query').disabled,true);
  e.state.activeId='other';e.window.ChatMessageMemory.scopeChanged();assert.equal(e.get('message-memory-dialog').open,false);
  const later=e.deferred.shift();later.resolve(later.value);await operation;await flush();
  assert.equal(e.get('message-memory-search-results').textContent,'');assert.equal(e.posts().length,0);
  e.window.ChatMessageMemory.openSearch();assert.equal(e.get('message-memory-query').value,'','query is not retained across full scope');purposes++;
}
console.log(JSON.stringify({passed:true,purposes,actual_callbacks:true,production:false,models:0}));
